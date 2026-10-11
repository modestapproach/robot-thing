"""Scientist reasoning: evidence -> diagnosis -> ranked, competing mutation proposals.

``diagnose`` is deterministic statistics over structured experiment records
(numbers never come from generated text, PRD §9.3). ``propose`` asks Claude for
candidate mutations constrained to the closed op set and mutable fields; with no
credentials it falls back to a deterministic cheapest-hypothesis-first policy.
Either way every proposal still has to pass the independent evaluator.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel, Field

from harness.ops import ALLOWED_OPS
from harness.validate import MUTABLE_FIELDS
from shared.schemas import HarnessVersion, MutationType, RiskClassification

MODEL = os.environ.get("AUTOLAB_SCIENTIST_MODEL", "claude-opus-5-5")


@dataclass
class Diagnosis:
    n_failures: int
    n_total: int
    mean_error_mm: float
    bias_xy_mm: tuple[float, float]
    bias_to_spread: float  # |mean vector| / std of vectors: >2 means systematic, not noise
    retry_gain_mm: float  # mean(first attempt error - final error) on retried trials
    board_moved_seen: bool
    hypotheses: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def diagnose(experiments: list[dict], tolerance_mm: float = 2.0) -> Diagnosis:
    done = [e for e in experiments if e.get("position_error_mm") is not None and e.get("error_xy_mm")]
    fails = [e for e in done if e["position_error_mm"] > tolerance_mm]
    if not done:
        return Diagnosis(0, 0, float("nan"), (0.0, 0.0), 0.0, 0.0, False, [])
    vx = [e["error_xy_mm"]["x"] for e in done]
    vy = [e["error_xy_mm"]["y"] for e in done]
    mx, my = sum(vx) / len(vx), sum(vy) / len(vy)
    sd = math.sqrt(sum((x - mx) ** 2 + (y - my) ** 2 for x, y in zip(vx, vy)) / max(1, len(vx) - 1)) or 1e-6
    retried = [e for e in done if e.get("retries", 0) > 0 and e.get("first_attempt_error_mm") is not None]
    retry_gain = sum(e["first_attempt_error_mm"] - e["position_error_mm"] for e in retried) / len(retried) if retried else 0.0
    moved = any(e.get("board_moved_detected") for e in experiments)
    ratio = math.hypot(mx, my) / sd
    hyps = []
    hyps.append({"id": "transient_actuation_noise", "support": "weak" if ratio > 2 else "moderate",
                 "evidence": f"bias/spread={ratio:.1f}; noise would give ratio < 1"})
    hyps.append({"id": "environment_changed_since_calibration", "support": "strong" if moved else "moderate",
                 "evidence": f"board_moved flag {'set' if moved else 'not set'}; retry without re-observation recovered {retry_gain:+.2f} mm"})
    hyps.append({"id": "calibration_offset", "support": "strong" if ratio > 2 else "weak",
                 "evidence": f"mean error vector ({mx:+.2f}, {my:+.2f}) mm is systematic"})
    return Diagnosis(len(fails), len(done), sum(e["position_error_mm"] for e in done) / len(done), (mx, my), ratio, retry_gain, moved, hyps)


# ----------------------------------------------------------------- structured proposal schema
class RetryPolicyPatch(BaseModel):
    max_retries: int = Field(ge=0, le=3)
    reobserve_before_retry: bool
    replan_before_retry: bool


class MemoryPolicyPatch(BaseModel):
    retrieve_prior_failures: bool
    max_episodes: int = Field(ge=0, le=10)
    retrieve_procedures: bool


class ExperimentPolicyPatch(BaseModel):
    selection: Literal["random", "uncertainty_weighted"]
    coverage_floor: float = Field(ge=0.0, le=1.0)
    simulation_budget: int = Field(ge=1, le=2000)


class ProposedMutation(BaseModel):
    mutation_type: Literal["parameter", "workflow", "memory_policy", "experiment_policy"]
    workflow_ops: Optional[list[str]] = Field(None, description="Full ordered op list, only for workflow mutations")
    retry_policy: Optional[RetryPolicyPatch] = None
    memory_policy: Optional[MemoryPolicyPatch] = None
    experiment_policy: Optional[ExperimentPolicyPatch] = None
    hypothesis: str
    expected_improvement: str
    risk: Literal["low", "medium", "high"]


class ProposalSet(BaseModel):
    reasoning_summary: str
    proposals: list[ProposedMutation]


def to_patch(p: ProposedMutation) -> dict:
    patch: dict = {}
    if p.workflow_ops is not None:
        patch["workflow_steps"] = [{"op": o} for o in p.workflow_ops]
    if p.retry_policy is not None:
        patch["retry_policy"] = p.retry_policy.model_dump()
    if p.memory_policy is not None:
        patch["memory_policy"] = p.memory_policy.model_dump()
    if p.experiment_policy is not None:
        patch["experiment_policy"] = p.experiment_policy.model_dump()
    return patch


SYSTEM = """You are the Scientist agent in AutoLab, a robotics lab where a robot arm's operating harness is a versioned document.
You diagnose failures from structured evidence and propose candidate harness mutations. You cannot promote anything: an
independent evaluator runs protected held-out tests you never see and accepts or rejects each candidate. Rejections are
recorded as lessons. Propose 1-3 competing candidates that test distinct hypotheses, ranked cheapest/lowest-risk first.
Only use operations from the allowed list and only change fields permitted for the mutation type. Workflows must keep
observe -> plan_move -> execute_move -> verify -> record in that order and contain exactly one execute_move."""


def _prompt(diag: Diagnosis, active: HarnessVersion, lessons: list[dict], focus: str) -> str:
    return json.dumps(
        {
            "focus": focus,
            "diagnosis": diag.to_dict(),
            "active_harness": active.model_dump(mode="json", by_alias=True, exclude={"created_at"}),
            "allowed_ops": ALLOWED_OPS,
            "mutable_fields_by_type": {k.value: sorted(v) for k, v in MUTABLE_FIELDS.items() if k != MutationType.TOOL_POLICY},
            "recent_lessons": lessons,
        },
        indent=1,
        default=str,
    )


def propose_with_claude(diag: Diagnosis, active: HarnessVersion, lessons: list[dict], focus: str) -> ProposalSet:
    import anthropic

    client = anthropic.Anthropic()
    resp = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "high"},
        system=SYSTEM,
        messages=[{"role": "user", "content": _prompt(diag, active, lessons, focus)}],
        output_format=ProposalSet,
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"model refused: {resp.stop_details}")
    if resp.parsed_output is None:
        raise RuntimeError(f"no structured output (stop_reason={resp.stop_reason})")
    return resp.parsed_output


def propose_deterministic(diag: Diagnosis, active: HarnessVersion, lessons: list[dict], focus: str) -> ProposalSet:
    """Cheapest-hypothesis-first fallback. Each hypothesis maps to the minimal mutation that tests it."""
    tried = {(l["mutation_type"], l["status"]) for l in lessons}
    if focus == "experiment_policy":
        return ProposalSet(
            reasoning_summary="Calibration needed many observations; random target choice wastes trials on low-information points.",
            proposals=[ProposedMutation(
                mutation_type="experiment_policy",
                experiment_policy=ExperimentPolicyPatch(selection="uncertainty_weighted", coverage_floor=0.5, simulation_budget=active.experiment_policy.simulation_budget),
                hypothesis="Choosing calibration targets where the twin's predictive variance is highest (with a workspace coverage floor) identifies the board transform in fewer physical observations.",
                expected_improvement=">=10% fewer observations to reach 0.6 mm held-out twin RMSE",
                risk="low",
            )],
        )
    props = []
    if ("parameter", "REJECTED") not in tried:
        props.append(ProposedMutation(
            mutation_type="parameter",
            retry_policy=RetryPolicyPatch(max_retries=3, reobserve_before_retry=False, replan_before_retry=False),
            hypothesis="Misses are transient actuation noise; more retries of the same command will land within tolerance.",
            expected_improvement="higher task success at the cost of extra moves",
            risk="low",
        ))
    props.append(ProposedMutation(
        mutation_type="workflow",
        workflow_ops=["observe", "check_board_pose", "retrieve_calibration_uncertainty", "plan_move", "simulate_if_uncertain",
                      "execute_move", "verify", "retry_or_recover", "record"],
        retry_policy=RetryPolicyPatch(max_retries=1, reobserve_before_retry=True, replan_before_retry=True),
        hypothesis="The environment changed after calibration (systematic bias, board-moved flag, retries without re-observation recover nothing). "
                   "Checking board pose and calibration confidence before precision moves, then re-observing and replanning from the measured miss, recovers the task.",
        expected_improvement="success rate up, RMSE down >=10%, at most one extra observation per task",
        risk="medium",
    ))
    return ProposalSet(reasoning_summary=f"Hypotheses ranked by evidence: {[h['id'] + ':' + h['support'] for h in diag.hypotheses]}", proposals=props)


def propose(diag: Diagnosis, active: HarnessVersion, lessons: list[dict], focus: str = "task_failures") -> tuple[ProposalSet, str]:
    """Returns (proposals, engine) where engine is the model id or 'deterministic'."""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        try:
            return propose_with_claude(diag, active, lessons, focus), MODEL
        except Exception as e:
            print(f"[scientist] Claude proposal failed, using deterministic policy: {e}")
    return propose_deterministic(diag, active, lessons, focus), "deterministic"
