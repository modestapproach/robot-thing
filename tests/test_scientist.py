import os

from agents.scientist.scientist import Scientist
from agents.scientist.tools import ScientistTools
from evaluation.evaluator import evaluate_candidate
from harness.runtime import HarnessRuntime
from shared.schemas import XY
from simulation.world import make_world_factory


def test_scientist_never_sees_protected(store, v1, twin):
    gw = make_world_factory(store=store)()
    rt = HarnessRuntime(v1, twin, gw, store=store)
    rt.run("pro_01", XY(x=40, y=70))
    rt.run("sel_01", XY(x=50, y=50))
    tools = ScientistTools(store, review=lambda cid: None)
    rows = tools.search_prior_experiments({})
    assert rows and all(not r["scenario_id"].startswith("pro_") for r in rows)
    assert tools.search_prior_experiments({"scenario_id": "pro_01"}) == [] or all(not r["scenario_id"].startswith("pro_") for r in tools.search_prior_experiments({"scenario_id": "pro_01"}))


def test_scientist_cannot_weaken_safety_or_promote(store, v1, twin):
    tools = ScientistTools(store, review=lambda cid: None)
    assert not hasattr(tools, "promote") and not hasattr(tools, "approve_candidate")
    from shared.schemas import MutationType

    out = tools.propose_harness_mutation(MutationType.WORKFLOW, {"workflow_steps": [{"op": "observe"}, {"op": "set_speed_limit"}]}, "h", "e")
    assert out["candidate_id"] is None and "unsupported" in out["error"]


def test_investigation_end_to_end_deterministic(store, v1, twin, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    world = make_world_factory(store=store)
    rt = HarnessRuntime(v1, twin, world(), store=store)
    ids = [rt.run(f"sel_0{i}", XY(x=40 + 20 * i, y=60)).experiment_id for i in range(1, 6)]
    sci = Scientist(ScientistTools(store, review=lambda cid: evaluate_candidate(cid, twin, world, store)))
    res = sci.investigate(ids)
    decisions = [o["decision"] for o in res["outcomes"]]
    assert decisions[-1] == "approve" and "reject" in decisions
    assert res["engine"] == "deterministic"
