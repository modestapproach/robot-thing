"""Scientist tools (PRD §13.2). Narrow, auditable, and blind to protected targets.

The Scientist can create candidates and submit them for review. It cannot
promote, cannot touch the safety envelope, and never receives protected
scenario ids or their outcomes (PRD §14.4).
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from evaluation import evaluator
from harness.mutate import derive_candidate
from harness.validate import HarnessValidationError
from shared.ids import new_id
from shared.schemas import (
    XY,
    CalibrationParameters,
    ExperimentCampaign,
    HarnessVersion,
    MutationProposal,
    MutationType,
    RiskClassification,
    TwinVersion,
)
from shared.store import Store
from simulation.batch import BatchRunner, BatchSpec, BatchResult, run_batch
from simulation.twin import fit_calibration

PROTECTED_PREFIX = "pro_"


def _visible(e: dict) -> bool:
    return not str(e.get("scenario_id", "")).startswith(PROTECTED_PREFIX)


class ScientistTools:
    def __init__(self, store: Store, review: Callable[[str], Any], sim: BatchRunner | None = None) -> None:
        """``review`` is bound by the deployment to the independent evaluator; the Scientist
        cannot choose the evaluation world, targets, or thresholds."""
        self.store = store
        self._review = review
        self.sim = sim

    # ---------------------------------------------------------------- read
    def inspect_harness(self, version_id: str) -> dict:
        d = self.store.get("harness_versions", version_id)
        if not d:
            raise KeyError(version_id)
        return d

    def active_harness(self) -> HarnessVersion:
        return evaluator.get_active(self.store)

    def search_prior_experiments(self, query: dict[str, Any] | None = None, limit: int = 50) -> list[dict]:
        """Exact structured lookup. Protected scenarios are filtered out unconditionally."""
        q = {k: v for k, v in (query or {}).items() if k != "scenario_id" or not str(v).startswith(PROTECTED_PREFIX)}
        rows = self.store.find("experiments", q, sort=[("started_at", -1)])
        return [e for e in rows if _visible(e)][:limit]

    def lessons(self, limit: int = 5) -> list[dict]:
        """Procedural memory: past decisions with reasons (structured mirror of Agent Engine memory)."""
        rows = self.store.find("mutation_proposals", {}, sort=[("created_at", -1)], limit=limit)
        return [{"mutation_type": r["mutation_type"], "hypothesis": r["hypothesis"], "status": r["status"], "decision_reason": r.get("decision_reason")} for r in rows]

    # ---------------------------------------------------------------- experiments
    def create_experiment_campaign(self, objective: str, baseline_version_id: str, scenario_set_id: str = "targets_v1", budget: dict | None = None) -> str:
        c = ExperimentCampaign(_id=new_id("camp"), objective=objective, baseline_version_id=baseline_version_id, scenario_set_id=scenario_set_id, budget=budget or {})
        return self.store.insert("experiment_campaigns", c)

    def calibration_candidates(self, evidence: list[tuple[XY, XY]], base: CalibrationParameters) -> list[CalibrationParameters]:
        """Hypothesis-driven candidate set: offset-only, full similarity, and perturbations around it."""
        full = fit_calibration([t for t, _ in evidence], [o for _, o in evidence], base)
        off_only = fit_calibration([t for t, _ in evidence][:2], [o for _, o in evidence][:2], base)
        cands = [base, off_only, full]
        for dx in (-1.0, 1.0):
            for dr in (-0.5, 0.5):
                cands.append(full.model_copy(update={"offset_mm": XY(x=full.offset_mm.x + dx, y=full.offset_mm.y), "rotation_deg": full.rotation_deg + dr}))
        cands.append(full.model_copy(update={"scale": 1.25}))  # deliberately implausible: shows admissibility gate
        return cands

    def run_simulation_batch(self, twin: TwinVersion, candidates: list[CalibrationParameters], evidence: list[tuple[XY, XY]]) -> str | BatchResult:
        spec = BatchSpec(twin_version_id=twin.id, base_calibration=twin.calibration_parameters, candidates=candidates, evidence=evidence)
        if self.sim:
            return self.sim.submit(spec)
        return run_batch(spec)

    def get_batch_results(self, batch_id: str) -> Optional[BatchResult]:
        return self.sim.get(batch_id) if self.sim else None

    # ---------------------------------------------------------------- mutations
    def propose_harness_mutation(
        self,
        mutation_type: MutationType,
        patch: dict[str, Any],
        hypothesis: str,
        expected_improvement: str,
        risk: RiskClassification = RiskClassification.LOW,
    ) -> dict:
        base = self.active_harness()
        try:
            cand = derive_candidate(base, mutation_type, patch, reason=hypothesis)
        except HarnessValidationError as e:
            # Record the refused proposal too: failed ideas are evidence.
            pid = new_id("mut")
            self.store.insert(
                "mutation_proposals",
                MutationProposal(
                    _id=pid, base_harness_version=base.id, candidate_harness_version="(invalid)", mutation_type=mutation_type,
                    patch=patch, hypothesis=hypothesis, expected_improvement=expected_improvement, risk_classification=risk,
                    status="REJECTED", decision_reason=f"validation: {e}",
                ),
            )
            return {"proposal_id": pid, "candidate_id": None, "error": str(e)}
        self.store.insert("harness_versions", cand)
        pid = new_id("mut")
        self.store.insert(
            "mutation_proposals",
            MutationProposal(
                _id=pid, base_harness_version=base.id, candidate_harness_version=cand.id, mutation_type=mutation_type,
                patch=patch, hypothesis=hypothesis, expected_improvement=expected_improvement, risk_classification=risk,
            ),
        )
        self.store.audit("mutation_proposed", proposal_id=pid, candidate=cand.id, base=base.id)
        return {"proposal_id": pid, "candidate_id": cand.id}

    def submit_candidate_for_review(self, candidate_id: str) -> dict:
        """Hands the candidate to the independent evaluator. Returns only the decision + reasons."""
        try:
            res = self._review(candidate_id)
        except evaluator.PromotionError as e:
            return {"decision": "reject", "reasons": [f"promotion refused: {e}"], "evaluation_id": None}
        return {"decision": res.decision.value, "reasons": res.reasons, "evaluation_id": res.id}
