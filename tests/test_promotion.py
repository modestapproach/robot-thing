import pytest

from evaluation import evaluator
from evaluation.evaluator import PromotionError, evaluate_candidate, get_active, promote, rollback, transition
from harness.mutate import derive_candidate
from harness.runtime import HarnessRuntime
from shared.schemas import XY, HarnessStatus, MutationType
from shared.store import ImmutableDocumentError
from simulation.world import make_world_factory

from conftest import WORKFLOW_V2


def test_workflow_candidate_promoted_and_retry_only_rejected(store, v1, twin):
    world = make_world_factory(store=store)
    bad = derive_candidate(v1, MutationType.PARAMETER, {"retry_policy": {"max_retries": 3}}, "more retries")
    store.insert("harness_versions", bad)
    r = evaluate_candidate(bad.id, twin, world, store)
    assert r.decision.value == "reject"
    assert store.get("harness_versions", bad.id)["status"] == "REJECTED"
    good = derive_candidate(v1, MutationType.WORKFLOW, WORKFLOW_V2, "replan")
    store.insert("harness_versions", good)
    r = evaluate_candidate(good.id, twin, world, store)
    assert r.decision.value == "approve"
    assert get_active(store).id == good.id
    assert store.get("harness_versions", v1.id)["status"] == "SUPERSEDED"


def test_cannot_skip_proposed_to_active(store, v1):
    c = derive_candidate(v1, MutationType.WORKFLOW, WORKFLOW_V2, "x")
    store.insert("harness_versions", c)
    with pytest.raises(PromotionError):
        transition(store, c.id, HarnessStatus.ACTIVE)
    with pytest.raises(PromotionError):
        promote(store, c.id, expected_active=v1.id)


def test_concurrent_promotion_refused(store, v1):
    a = derive_candidate(v1, MutationType.WORKFLOW, WORKFLOW_V2, "a")
    b = derive_candidate(v1, MutationType.PARAMETER, {"retry_policy": {"max_retries": 2}}, "b")
    for c in (a, b):
        store.insert("harness_versions", {**c.model_dump(by_alias=True), "status": "APPROVED"})
    promote(store, a.id, expected_active=v1.id)
    with pytest.raises(PromotionError, match="concurrent"):
        promote(store, b.id, expected_active=v1.id)
    assert get_active(store).id == a.id


def test_rollback_restores_parent_and_keeps_history(store, v1):
    a = derive_candidate(v1, MutationType.WORKFLOW, WORKFLOW_V2, "a")
    store.insert("harness_versions", {**a.model_dump(by_alias=True), "status": "APPROVED"})
    promote(store, a.id, expected_active=v1.id)
    assert rollback(store, "regression") == v1.id
    assert get_active(store).id == v1.id
    assert store.get("harness_versions", a.id)["status"] == "ROLLED_BACK"


def test_running_task_stays_pinned(store, v1, twin):
    world = make_world_factory(store=store)
    rt = HarnessRuntime(v1, twin, world(), store=store)
    a = derive_candidate(v1, MutationType.WORKFLOW, WORKFLOW_V2, "a")
    store.insert("harness_versions", {**a.model_dump(by_alias=True), "status": "APPROVED"})
    promote(store, a.id, expected_active=v1.id)
    r = rt.run("sel_01", XY(x=50, y=50))
    assert store.get("experiments", r.experiment_id)["harness_version_id"] == v1.id


def test_finalized_experiments_are_append_only(store, v1, twin):
    r = HarnessRuntime(v1, twin, make_world_factory(store=store)(), store=store).run("sel_01", XY(x=50, y=50))
    with pytest.raises(ImmutableDocumentError):
        store.update("experiments", r.experiment_id, {"position_error_mm": 0.0})


def test_mock_runs_are_labelled_simulation(store, v1, twin):
    from shared.schemas import ExecutionEnvironment

    rt = HarnessRuntime(v1, twin, make_world_factory(store=store)(), store=store, environment=ExecutionEnvironment.REAL_HARDWARE)
    r = rt.run("sel_01", XY(x=50, y=50))
    assert store.get("experiments", r.experiment_id)["execution_environment"] == "simulation"
