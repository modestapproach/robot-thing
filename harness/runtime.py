"""Deterministic harness runtime (PRD §5.1 "Harness Runtime", §8.1).

Interprets an approved, pinned ``HarnessVersion`` for one task: move the tool to
a board target. Executes only ops in ``ALLOWED_OPS``. The runtime is the same
object whether the Toolbox is backed by the mock arm, the real arm, or the
simulation, so baseline and candidate harnesses are compared on identical code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from harness.ops import ALLOWED_OPS
from robot_gateway.gateway import Gateway
from shared.ids import new_id
from shared.schemas import (
    XY,
    CommandStatus,
    Experiment,
    ExecutionEnvironment,
    HarnessVersion,
    MoveRequest,
    TwinVersion,
    VerificationStatus,
    utcnow,
)
from shared.store import Store, get_store
from simulation.twin import SAFE_HEIGHT_MM, GeometricTwin


def env_for(gw: Gateway) -> ExecutionEnvironment:
    return ExecutionEnvironment.REAL_HARDWARE if getattr(gw.driver, "is_physical", False) else ExecutionEnvironment.SIMULATION


@dataclass
class TaskResult:
    experiment_id: str
    success: bool
    error_mm: Optional[float]
    observations: int
    movements: int
    retries: int
    sim_previews: int
    board_moved_detected: bool
    steps: list[str] = field(default_factory=list)
    status: str = "unknown"


class HarnessRuntime:
    def __init__(
        self,
        harness: HarnessVersion,
        twin: TwinVersion,
        gateway: Gateway,
        store: Store | None = None,
        environment: ExecutionEnvironment | None = None,
        tolerance_mm: float = 2.0,
        uncertainty_threshold_mm: float = 1.5,
        campaign_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        self.h = harness
        from simulation.so101.twin import make_twin

        self.twin = make_twin(twin)
        self.twin_id = twin.id
        self.gw = gateway
        self.store = store or get_store()
        # Honest labelling: anything that is not a physical driver is simulation, whatever the caller intended.
        self.env = environment or env_for(gateway)
        if not getattr(gateway.driver, "is_physical", False):
            self.env = ExecutionEnvironment.SIMULATION
        self.tol = tolerance_mm
        self.unc_thresh = uncertainty_threshold_mm
        self.campaign_id = campaign_id
        self.trace_id = trace_id
        for s in harness.workflow_steps:
            if s.op not in ALLOWED_OPS:
                raise ValueError(f"unsupported op {s.op}")

    # ------------------------------------------------------------------ run
    def run(self, scenario_id: str, target: XY, seed: int = 0, idem_prefix: str | None = None) -> TaskResult:
        """Run one task. ``idem_prefix`` makes motion commands deterministic per trial so a
        resumed campaign never re-executes an acknowledged move (PRD §2, §10.6)."""
        ctx: dict[str, Any] = {
            "idem_prefix": idem_prefix,
            "attempt": 0,
            "target": target,
            "observations": 0,
            "movements": 0,
            "retries": 0,
            "sim_previews": 0,
            "board_moved": False,
            "last_obs": None,
            "error": None,
            "command_status": None,
            "replan": False,
        }
        exp = Experiment(
            _id=new_id("exp"),
            campaign_id=self.campaign_id,
            scenario_id=scenario_id,
            harness_version_id=self.h.id,
            twin_version_id=self.twin_id,
            random_seed=seed,
            target_position_mm=target,
            execution_environment=self.env,
            trace_id=self.trace_id,
        )
        self.store.insert("experiments", exp)
        steps: list[str] = []
        self._pass(ctx, steps)
        err = ctx["error"]
        success = err is not None and err <= self.tol
        status = VerificationStatus.VERIFIED if err is not None else VerificationStatus.UNKNOWN
        if ctx["command_status"] in (CommandStatus.REJECTED, CommandStatus.UNKNOWN):
            status = VerificationStatus.FAILED if ctx["command_status"] == CommandStatus.REJECTED else VerificationStatus.UNKNOWN
        obs = ctx["last_obs"]
        self.store.update(
            "experiments",
            exp.id,
            {
                "predicted_position_mm": ctx.get("predicted").model_dump() if ctx.get("predicted") else None,
                "observed_position_mm": obs.end_effector_mm.model_dump() if obs and obs.end_effector_mm else None,
                "position_error_mm": err,
                "error_xy_mm": ctx.get("error_xy").model_dump() if ctx.get("error_xy") else None,
                "verification_status": status.value,
                "completed_at": utcnow(),
                "artifact_refs": ([obs.image_ref] if obs and obs.image_ref else []) + ctx.get("trajectory_refs", []),
                "rejection_reason": ctx.get("rejection"),
                "retries": ctx["retries"],
                "observations": ctx["observations"],
                "movements": ctx["movements"],
                "board_moved_detected": ctx["board_moved"],
                "first_attempt_error_mm": ctx.get("first_error"),
                "finalized": True,
            },
        )
        return TaskResult(
            experiment_id=exp.id,
            success=success,
            error_mm=err,
            observations=ctx["observations"],
            movements=ctx["movements"],
            retries=ctx["retries"],
            sim_previews=ctx["sim_previews"],
            board_moved_detected=ctx["board_moved"],
            steps=steps,
            status=status.value,
        )

    def _pass(self, ctx: dict[str, Any], steps: list[str]) -> None:
        for step in self.h.workflow_steps:
            handler = getattr(self, f"op_{step.op}")
            steps.append(step.op)
            handler(ctx, step.params)
            if ctx.get("abort"):
                return

    # ------------------------------------------------------------------ ops
    def op_observe(self, ctx, params):
        ctx["last_obs"] = self.gw.observe()
        ctx["observations"] += 1

    def op_check_board_pose(self, ctx, params):
        obs = ctx["last_obs"] or self.gw.observe()
        if obs.board_moved:
            ctx["board_moved"] = True
            ctx["replan"] = True  # tells plan_move to apply a fresh offset estimate

    def op_retrieve_calibration_uncertainty(self, ctx, params):
        ctx["sigma"] = (self.twin.unc.actuation_sigma_mm**2 + self.twin.unc.observation_sigma_mm**2) ** 0.5

    def op_retrieve_prior_failures(self, ctx, params):
        if not self.h.memory_policy.retrieve_prior_failures:
            return
        q = {"harness_version_id": self.h.id, "verification_status": "verified"}
        prior = self.store.find("experiments", q, sort=[("started_at", -1)], limit=self.h.memory_policy.max_episodes)
        # Empirical residual correction from recent verified trials (append-only evidence, not text memory).
        residuals = [
            (e["target_position_mm"]["x"] - e["observed_position_mm"]["x"], e["target_position_mm"]["y"] - e["observed_position_mm"]["y"])
            for e in prior
            if e.get("observed_position_mm")
        ]
        if residuals:
            ctx["residual_correction"] = XY(x=sum(r[0] for r in residuals) / len(residuals), y=sum(r[1] for r in residuals) / len(residuals))

    def op_plan_move(self, ctx, params):
        target: XY = ctx["target"]
        corr = ctx.get("residual_correction")
        if corr and ctx.get("replan", True):
            target = XY(x=target.x + corr.x, y=target.y + corr.y)
        pred = self.twin.predict(target)
        ctx["commanded_base"] = pred.commanded_base_mm
        ctx["predicted"] = ctx["target"]  # believed landing point is the target itself
        ctx["admissible"] = pred.admissible

    def op_simulate_if_uncertain(self, ctx, params):
        sigma = ctx.get("sigma") or self.unc_thresh
        if sigma >= self.unc_thresh or ctx.get("board_moved"):
            ctx["sim_previews"] += 1
            pred = self.twin.predict(ctx["target"])
            if not pred.admissible:
                ctx["abort"] = True

    def op_execute_move(self, ctx, params):
        if not ctx.get("admissible", True):
            ctx["command_status"] = CommandStatus.REJECTED
            return
        req = MoveRequest(target_mm=ctx["target"], height_mm=SAFE_HEIGHT_MM, speed_fraction=params.get("speed_fraction", 0.3))
        ctx["attempt"] += 1
        key = f"{ctx['idem_prefix']}:move{ctx['attempt']}" if ctx["idem_prefix"] else new_id("idem")
        cmd = self.gw.submit(key, self.h.id, req, ctx["commanded_base"])
        ctx["command_status"] = cmd.status
        ctx["last_command"] = cmd
        if cmd.status == CommandStatus.REJECTED:
            ctx["rejection"] = cmd.rejection_reason
        if cmd.status == CommandStatus.ACKNOWLEDGED:
            ctx["movements"] += 1
            if cmd.result_ref:
                ctx.setdefault("trajectory_refs", []).append(cmd.result_ref)

    def op_verify(self, ctx, params):
        if ctx["command_status"] != CommandStatus.ACKNOWLEDGED:
            ctx["error"] = None
            return
        obs = self.gw.observe()
        ctx["observations"] += 1
        ctx["last_obs"] = obs
        if obs.end_effector_mm is None or obs.confidence < 0.5:
            ctx["error"] = None  # unknown stays unknown
            return
        t: XY = ctx["target"]
        ctx["error_xy"] = XY(x=obs.end_effector_mm.x - t.x, y=obs.end_effector_mm.y - t.y)
        ctx["error"] = obs.end_effector_mm.dist(t)
        ctx.setdefault("first_error", ctx["error"])

    def op_retry_or_recover(self, ctx, params):
        rp = self.h.retry_policy
        while (ctx["error"] is None or ctx["error"] > self.tol) and ctx["retries"] < rp.max_retries:
            if ctx["command_status"] == CommandStatus.REJECTED:
                break
            ctx["retries"] += 1
            if rp.reobserve_before_retry:
                self.op_observe(ctx, {})
                self.op_check_board_pose(ctx, {})
            if rp.replan_before_retry and ctx.get("error_xy"):
                # One-shot empirical correction from the measured miss.
                e = ctx["error_xy"]
                prev = ctx.get("residual_correction") or XY(x=0.0, y=0.0)
                ctx["residual_correction"] = XY(x=prev.x - e.x, y=prev.y - e.y)
                ctx["replan"] = True
            self.op_plan_move(ctx, {})
            self.op_execute_move(ctx, {})
            self.op_verify(ctx, {})

    def op_record(self, ctx, params):
        pass  # finalization happens in run()
