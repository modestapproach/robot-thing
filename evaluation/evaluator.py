"""The promotion controller (PRD §8.8).

Runs baseline and candidate harnesses on the *same* protected scenarios against
the *same* simulated world, applies protected acceptance rules, writes an
EvaluationResult, and promotes with an atomic conditional update on the
active-version pointer. Nothing here is reachable as an unrestricted tool.
"""
from __future__ import annotations

import math
from typing import Callable

from evaluation.metrics import HarnessMetrics, summarize
from evaluation.protected import (
    MAX_EXTRA_MOVEMENTS_PER_TASK,
    MAX_EXTRA_OBSERVATIONS_PER_TASK,
    MIN_RMSE_IMPROVEMENT_FRACTION,
    MIN_SUCCESS_RATE_DELTA,
    PROTECTED_TEST_SET_VERSION,
    protected_targets,
)
from harness.runtime import HarnessRuntime, TaskResult
from harness.validate import HarnessValidationError, validate_harness
from shared.ids import new_id
from shared.schemas import (
    XY,
    Decision,
    EvaluationResult,
    ExecutionEnvironment,
    HarnessStatus,
    HarnessVersion,
    LIFECYCLE_TRANSITIONS,
    TwinVersion,
)
from shared.store import Store, get_store

# A factory that builds a fresh, identically-seeded simulated world (gateway) for each harness run,
# so baseline and candidate face the same hidden truth and the same disturbances.
WorldFactory = Callable[[], object]


class PromotionError(Exception):
    pass


def transition(store: Store, harness_id: str, to: HarnessStatus, reason: str = "") -> None:
    doc = store.get("harness_versions", harness_id)
    if not doc:
        raise PromotionError(f"unknown harness {harness_id}")
    frm = HarnessStatus(doc["status"])
    if to not in LIFECYCLE_TRANSITIONS[frm]:
        raise PromotionError(f"illegal transition {frm.value} -> {to.value}")
    ok = store.conditional_update("harness_versions", {"_id": harness_id, "status": frm.value}, {"status": to.value})
    if not ok:
        raise PromotionError("concurrent status change")
    store.audit("harness_transition", harness_id=harness_id, **{"from": frm.value, "to": to.value, "reason": reason})


def run_suite(harness: HarnessVersion, twin: TwinVersion, world: WorldFactory, store: Store, targets: list[dict], env: ExecutionEnvironment | None = None) -> list[TaskResult]:
    gw = world()
    rt = HarnessRuntime(harness, twin, gw, store=store, environment=env, campaign_id="eval")
    return [rt.run(t["id"], XY(x=t["x"], y=t["y"]), seed=i) for i, t in enumerate(targets)]


def safety_invariants(cand: HarnessVersion, base: HarnessVersion) -> dict[str, bool]:
    return {
        "single_physical_op": sum(s.op == "execute_move" for s in cand.workflow_steps) <= 1,
        "retries_bounded": cand.retry_policy.max_retries <= 3,
        "sim_budget_capped": cand.experiment_policy.simulation_budget <= 2000,
        "protected_fields_untouched": cand.parent_version_id == base.id and cand.version == base.version + 1,
    }


def compare(base: HarnessMetrics, cand: HarnessMetrics) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    ok = True
    if cand.unknown_rate > base.unknown_rate:
        ok = False
        reasons.append(f"unknown-outcome rate rose {base.unknown_rate:.2f} -> {cand.unknown_rate:.2f}")
    if cand.success_rate < base.success_rate + MIN_SUCCESS_RATE_DELTA:
        ok = False
        reasons.append(f"success rate {cand.success_rate:.2f} < baseline {base.success_rate:.2f}")
    rmse_gain = (base.rmse_mm - cand.rmse_mm) / base.rmse_mm if base.rmse_mm and not math.isnan(base.rmse_mm) else 0.0
    improved = cand.success_rate > base.success_rate or rmse_gain >= MIN_RMSE_IMPROVEMENT_FRACTION
    if not improved:
        ok = False
        reasons.append(f"no material improvement (RMSE gain {rmse_gain:+.1%}, success {base.success_rate:.2f} -> {cand.success_rate:.2f})")
    if cand.observations_per_task - base.observations_per_task > MAX_EXTRA_OBSERVATIONS_PER_TASK:
        ok = False
        reasons.append("too many extra observations per task")
    if cand.movements_per_task - base.movements_per_task > MAX_EXTRA_MOVEMENTS_PER_TASK:
        ok = False
        reasons.append("too many extra physical movements per task")
    if ok:
        reasons.append(f"RMSE {base.rmse_mm:.2f} -> {cand.rmse_mm:.2f} mm ({rmse_gain:+.1%}); success {base.success_rate:.0%} -> {cand.success_rate:.0%}")
    return ok, reasons


def evaluate_candidate(
    candidate_id: str,
    twin: TwinVersion,
    world: WorldFactory,
    store: Store | None = None,
    env: ExecutionEnvironment = ExecutionEnvironment.SIMULATION,
    physical_world: WorldFactory | None = None,
) -> EvaluationResult:
    """Full pipeline: validate -> protected tests -> compare -> decide -> (promote|reject)."""
    store = store or get_store()
    cdoc = store.get("harness_versions", candidate_id)
    if not cdoc:
        raise PromotionError("candidate not found")
    base_doc = store.get("harness_versions", cdoc["parent_version_id"])
    if not base_doc:
        raise PromotionError("baseline not found")
    base = HarnessVersion.model_validate(base_doc)

    reasons: list[str] = []
    inv: dict[str, bool] = {}
    try:
        cand = validate_harness(cdoc)
        inv = safety_invariants(cand, base)
        if cdoc["status"] == HarnessStatus.PROPOSED.value:
            transition(store, candidate_id, HarnessStatus.VALIDATED, "schema+permissions ok")
    except HarnessValidationError as e:
        reasons.append(f"schema/permission: {e}")
        if cdoc["status"] == HarnessStatus.PROPOSED.value:
            transition(store, candidate_id, HarnessStatus.REJECTED, str(e))
        res = EvaluationResult(
            _id=new_id("eval"), candidate_version_id=candidate_id, baseline_version_id=base.id,
            protected_test_set_version=PROTECTED_TEST_SET_VERSION, safety_invariants=inv,
            protected_tests={"schema": False}, decision=Decision.REJECT, reasons=reasons,
        )
        store.insert("evaluation_results", res)
        _mark_proposal(store, candidate_id, HarnessStatus.REJECTED, "; ".join(reasons))
        return res

    if not all(inv.values()):
        bad = [k for k, v in inv.items() if not v]
        reasons.append(f"safety invariants failed: {bad}")
        transition(store, candidate_id, HarnessStatus.REJECTED, reasons[-1])
        res = EvaluationResult(
            _id=new_id("eval"), candidate_version_id=candidate_id, baseline_version_id=base.id,
            protected_test_set_version=PROTECTED_TEST_SET_VERSION, safety_invariants=inv,
            protected_tests={"invariants": False}, decision=Decision.REJECT, reasons=reasons,
        )
        store.insert("evaluation_results", res)
        _mark_proposal(store, candidate_id, HarnessStatus.REJECTED, "; ".join(reasons))
        return res

    if _only_experiment_policy_changed(base, cand):
        return _evaluate_experiment_policy(store, base, cand, inv)

    targets = protected_targets()
    base_res = run_suite(base, twin, world, store, targets, env)
    cand_res = run_suite(cand, twin, world, store, targets, env)
    bm, cm = summarize(base_res), summarize(cand_res)
    passed, cmp_reasons = compare(bm, cm)
    reasons += cmp_reasons
    transition(store, candidate_id, HarnessStatus.SIMULATED, "protected suite run")

    physical: dict = {}
    protected = {"schema": True, "invariants": True, "simulation_comparison": passed}
    if passed and physical_world is not None:
        transition(store, candidate_id, HarnessStatus.ELIGIBLE_FOR_PHYSICAL_TEST, "simulation gate passed")
        pb = run_suite(base, twin, physical_world, store, targets)
        pc = run_suite(cand, twin, physical_world, store, targets)
        pbm, pcm = summarize(pb), summarize(pc)
        p_ok, p_reasons = compare(pbm, pcm)
        pgw = physical_world()
        gw_env = HarnessRuntime(cand, twin, pgw, store=store).env.value
        driver = pgw.driver.name
        physical = {"baseline": pbm.to_dict(), "candidate": pcm.to_dict(), "n_targets": len(targets), "environment": gw_env, "driver": driver}
        protected["physical_comparison"] = p_ok
        label = {"mock": "mock arm", "so101_sim": "SO-101 physics sim"}.get(driver, driver)
        reasons += [f"physical stage [{label}]: " + r for r in p_reasons]
        transition(store, candidate_id, HarnessStatus.PHYSICALLY_TESTED, "physical protected suite run")
        passed = passed and p_ok

    decision = Decision.APPROVE if passed else Decision.REJECT
    res = EvaluationResult(
        _id=new_id("eval"),
        candidate_version_id=candidate_id,
        baseline_version_id=base.id,
        protected_test_set_version=PROTECTED_TEST_SET_VERSION,
        simulation_metrics={"baseline": bm.to_dict(), "candidate": cm.to_dict(), "n_targets": len(targets)},
        physical_metrics=physical,
        cost_metrics={"baseline_experiments": len(base_res), "candidate_experiments": len(cand_res)},
        safety_invariants=inv,
        protected_tests=protected,
        decision=decision,
        reasons=reasons,
    )
    store.insert("evaluation_results", res)
    if passed:
        transition(store, candidate_id, HarnessStatus.APPROVED, "protected comparison passed")
        promote(store, candidate_id, expected_active=base.id)
        _mark_proposal(store, candidate_id, HarnessStatus.ACTIVE, "; ".join(reasons))
    else:
        transition(store, candidate_id, HarnessStatus.REJECTED, "; ".join(reasons))
        _mark_proposal(store, candidate_id, HarnessStatus.REJECTED, "; ".join(reasons))
    return res


def _mark_proposal(store: Store, candidate_id: str, status: HarnessStatus, reason: str) -> None:
    for p in store.find("mutation_proposals", {"candidate_harness_version": candidate_id}):
        store.update("mutation_proposals", p["_id"], {"status": status.value, "decision_reason": reason})


def promote(store: Store, candidate_id: str, expected_active: str) -> None:
    """Atomic: demote the expected active version only if it is still active, then activate candidate."""
    cand = store.get("harness_versions", candidate_id)
    if not cand or cand["status"] != HarnessStatus.APPROVED.value:
        raise PromotionError("candidate must be APPROVED before activation")
    demoted = store.conditional_update(
        "harness_versions", {"_id": expected_active, "status": HarnessStatus.ACTIVE.value}, {"status": HarnessStatus.SUPERSEDED.value}
    )
    if not demoted:
        raise PromotionError(f"active version is no longer {expected_active}; concurrent promotion refused")
    activated = store.conditional_update(
        "harness_versions", {"_id": candidate_id, "status": HarnessStatus.APPROVED.value}, {"status": HarnessStatus.ACTIVE.value}
    )
    if not activated:  # restore
        store.conditional_update("harness_versions", {"_id": expected_active}, {"status": HarnessStatus.ACTIVE.value})
        raise PromotionError("candidate changed state during promotion; rolled back pointer")
    store.audit("harness_promoted", candidate=candidate_id, previous=expected_active)


def rollback(store: Store, reason: str) -> str:
    """Restore the active version's parent. History is never deleted."""
    active = store.find("harness_versions", {"status": HarnessStatus.ACTIVE.value}, limit=1)
    if not active:
        raise PromotionError("no active harness")
    cur = active[0]
    parent_id = cur.get("parent_version_id")
    if not parent_id:
        raise PromotionError("active harness has no predecessor")
    store.conditional_update("harness_versions", {"_id": cur["_id"], "status": HarnessStatus.ACTIVE.value}, {"status": HarnessStatus.ROLLED_BACK.value})
    store.conditional_update("harness_versions", {"_id": parent_id}, {"status": HarnessStatus.ACTIVE.value})
    store.audit("harness_rollback", **{"from": cur["_id"], "to": parent_id, "reason": reason})
    return parent_id


def get_active(store: Store) -> HarnessVersion:
    docs = store.find("harness_versions", {"status": HarnessStatus.ACTIVE.value}, limit=1)
    if not docs:
        raise PromotionError("no active harness")
    return HarnessVersion.model_validate(docs[0])


def _only_experiment_policy_changed(base: HarnessVersion, cand: HarnessVersion) -> bool:
    return (
        cand.experiment_policy != base.experiment_policy
        and cand.workflow_steps == base.workflow_steps
        and cand.retry_policy == base.retry_policy
        and cand.memory_policy == base.memory_policy
    )


# Protected study settings for experiment-policy mutations (PRD §14.3).
STUDY_THRESHOLD_MM = 0.6
STUDY_PROBLEMS = 40
STUDY_MIN_IMPROVEMENT = 0.10  # >= 10 % fewer observations to reach threshold


def _evaluate_experiment_policy(store: Store, base: HarnessVersion, cand: HarnessVersion, inv: dict[str, bool]) -> EvaluationResult:
    from simulation.selection_study import run_study

    held = [XY(x=t["x"], y=t["y"]) for t in protected_targets()]
    b = run_study(base.experiment_policy, held, n_problems=STUDY_PROBLEMS, threshold_mm=STUDY_THRESHOLD_MM)
    c = run_study(cand.experiment_policy, held, n_problems=STUDY_PROBLEMS, threshold_mm=STUDY_THRESHOLD_MM)
    gain = (b.mean_observations - c.mean_observations) / b.mean_observations
    passed = gain >= STUDY_MIN_IMPROVEMENT and c.reached_fraction >= b.reached_fraction
    reasons = [
        f"observations to reach {STUDY_THRESHOLD_MM} mm held-out twin RMSE: {b.mean_observations:.2f} -> {c.mean_observations:.2f} ({gain:+.1%}); "
        f"reached {b.reached_fraction:.0%} -> {c.reached_fraction:.0%} over {STUDY_PROBLEMS} identical randomized problems"
    ]
    if not passed:
        reasons.append(f"requires >= {STUDY_MIN_IMPROVEMENT:.0%} fewer observations without lower reach rate")
    transition(store, cand.id, HarnessStatus.SIMULATED, "experiment-policy study run")
    res = EvaluationResult(
        _id=new_id("eval"),
        candidate_version_id=cand.id,
        baseline_version_id=base.id,
        protected_test_set_version=PROTECTED_TEST_SET_VERSION + "+selection_study_v1",
        simulation_metrics={
            "kind": "experiment_selection_study",
            "baseline": {"policy": b.policy, "mean_observations": b.mean_observations, "median_observations": b.median_observations, "reached_fraction": b.reached_fraction},
            "candidate": {"policy": c.policy, "mean_observations": c.mean_observations, "median_observations": c.median_observations, "reached_fraction": c.reached_fraction},
            "threshold_mm": STUDY_THRESHOLD_MM,
            "n_problems": STUDY_PROBLEMS,
        },
        safety_invariants=inv,
        protected_tests={"schema": True, "invariants": True, "selection_study": passed},
        decision=Decision.APPROVE if passed else Decision.REJECT,
        reasons=reasons,
    )
    store.insert("evaluation_results", res)
    if passed:
        transition(store, cand.id, HarnessStatus.APPROVED, reasons[0])
        promote(store, cand.id, expected_active=base.id)
        _mark_proposal(store, cand.id, HarnessStatus.ACTIVE, "; ".join(reasons))
    else:
        transition(store, cand.id, HarnessStatus.REJECTED, "; ".join(reasons))
        _mark_proposal(store, cand.id, HarnessStatus.REJECTED, "; ".join(reasons))
    return res
