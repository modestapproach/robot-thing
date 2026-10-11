"""Operator agent core (PRD §5.1, §13.1).

Runs tasks under a harness version pinned at task start, reports failures, and
delegates investigation to the Scientist. It cannot modify configuration or
bypass the gateway. The Agent Engine entrypoint (agents/operator/main.py) wraps
this class; locally it is called directly.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from evaluation.evaluator import get_active
from harness.runtime import HarnessRuntime, TaskResult
from robot_gateway.gateway import Gateway
from shared.schemas import XY, HarnessVersion, TwinVersion
from shared.store import Store
from shared.telemetry import telemetry


def latest_twin(store: Store) -> TwinVersion:
    docs = store.find("twin_versions", {}, sort=[("created_at", -1)], limit=1)
    if not docs:
        raise RuntimeError("no twin version")
    return TwinVersion.model_validate(docs[0])


class Operator:
    def __init__(self, store: Store, gateway: Gateway, delegate: Optional[Callable[[dict], dict]] = None, tolerance_mm: float = 2.0) -> None:
        self.store = store
        self.gw = gateway
        self.delegate = delegate  # A2A call to the Scientist in deployment
        self.tol = tolerance_mm

    # ---------------------------------------------------------------- tools
    def observe_robot(self) -> dict:
        return {"state": self.gw.state().model_dump(), "observation": self.gw.observe().model_dump()}

    def get_active_harness(self) -> HarnessVersion:
        return get_active(self.store)

    def preview_movement(self, target: XY) -> dict:
        from simulation.twin import GeometricTwin

        p = GeometricTwin(latest_twin(self.store)).predict(target)
        return {"commanded_base_mm": p.commanded_base_mm.model_dump(), "admissible": p.admissible, "sigma_mm": p.sigma_mm, "reason": p.reason}

    # ---------------------------------------------------------------- task
    def run_task(self, scenario_id: str, target: XY, campaign_id: str | None = None, idem_prefix: str | None = None, seed: int = 0) -> TaskResult:
        harness = self.get_active_harness()  # pinned for the whole task
        twin = latest_twin(self.store)
        with telemetry.trace(
            "autolab-operator", "robot_task", f"move to {scenario_id} ({target.x:.0f},{target.y:.0f})",
            campaign_id=campaign_id, harness_version_id=harness.id, twin_version_id=twin.id, scenario_id=scenario_id,
        ) as t:
            with telemetry.span(t, "harness_run", harness_version=harness.version):
                rt = HarnessRuntime(harness, twin, self.gw, store=self.store, campaign_id=campaign_id, trace_id=t.trace_id, tolerance_mm=self.tol)
                r = rt.run(scenario_id, target, seed=seed, idem_prefix=idem_prefix)
            t.properties.update(experiment_id=r.experiment_id, outcome="success" if r.success else r.status, position_error_mm=r.error_mm)
            t.output = f"error={r.error_mm if r.error_mm is None else round(r.error_mm, 2)} mm, success={r.success}, steps={r.steps}"
            if not r.success:
                telemetry.signal(t, "robot_target_missed", error_mm=r.error_mm, experiment_id=r.experiment_id)
            elif r.retries > 0:
                telemetry.signal(t, "task_recovered", retries=r.retries, experiment_id=r.experiment_id)
            if r.retries > 0 and r.error_mm is not None and r.error_mm > self.tol:
                telemetry.signal(t, "unnecessary_retry", retries=r.retries, experiment_id=r.experiment_id)
        return r

    def report_failure(self, experiment_ids: list[str], focus: str = "task_failures") -> Optional[dict]:
        """Persist is already done by the runtime; this delegates investigation (A2A)."""
        self.store.audit("failure_reported", experiment_ids=experiment_ids)
        if self.delegate:
            return self.delegate({"type": "investigate", "experiment_ids": experiment_ids, "focus": focus})
        return None
