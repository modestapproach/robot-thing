"""The path hosted agents use: HTTP gateway client + review queue + evaluator worker."""
import importlib

from fastapi.testclient import TestClient

from agents.operator.operator import Operator
from agents.scientist.tools import ScientistTools
from evaluation import evaluator
from evaluation.review_queue import pending, request_review, review_status
from harness.runtime import HarnessRuntime
from shared.schemas import XY, MutationType
from shared.store import set_store
from simulation.world import make_world_factory

from conftest import WORKFLOW_V2


def test_remote_gateway_runs_harness_and_dedupes(store, v1, twin, monkeypatch):
    set_store(store)
    monkeypatch.setenv("ROBOT_PHYSICAL_ENABLE", "1")
    import robot_gateway.service as svc
    svc = importlib.reload(svc)
    from robot_gateway.client import RemoteGateway

    gw = RemoteGateway(url="http://testserver", key="dev-gateway-key", http=TestClient(svc.app))
    assert gw.driver.name == "mock"
    op = Operator(store, gw)  # type: ignore[arg-type]
    r = op.run_task("sel_01", XY(x=50, y=50), idem_prefix="t:sel_01")
    assert r.error_mm is not None and store.get("experiments", r.experiment_id)["execution_environment"] == "simulation"
    before = svc.gateway.driver.commands_executed
    op.run_task("sel_01", XY(x=50, y=50), idem_prefix="t:sel_01")  # same keys: no new motion
    assert svc.gateway.driver.commands_executed == before


def test_bad_gateway_key_refused(store, monkeypatch):
    set_store(store)
    import robot_gateway.service as svc
    c = TestClient(svc.app)
    assert c.get("/v1/state", headers={"x-api-key": "wrong"}).status_code == 401


def test_review_queue_only_evaluator_promotes(store, v1, twin):
    tools = ScientistTools(store, review=lambda cid: None)
    out = tools.propose_harness_mutation(MutationType.WORKFLOW, WORKFLOW_V2, "replan after miss", "recover")
    cid = out["candidate_id"]
    assert request_review(store, cid)
    assert not request_review(store, "hv_does_not_exist")
    assert evaluator.get_active(store).id == v1.id  # queueing changes nothing
    assert [h["_id"] for h in pending(store)] == [cid]
    world = make_world_factory(store=store)
    for hv in pending(store):  # what scripts/evaluator_worker.py does
        evaluator.evaluate_candidate(hv["_id"], twin, world, store)
        store.update("harness_versions", hv["_id"], {"review_requested": False})
    st = review_status(store, cid)
    assert st["decision"] == "approve" and st["status"] == "ACTIVE" and pending(store) == []
