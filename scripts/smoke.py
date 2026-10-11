"""Quick end-to-end smoke: baseline harness vs. a recover-and-replan candidate."""
import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from shared.store import MemoryStore
from shared.schemas import HarnessVersion, TwinVersion, MutationType
from harness.mutate import derive_candidate
from evaluation.evaluator import evaluate_candidate, get_active
from simulation.world import make_world_factory

store = MemoryStore()
v1 = HarnessVersion.model_validate(json.load(open("fixtures/harness_v1.json")))
store.insert("harness_versions", v1)
twin = TwinVersion(_id="twin_v0", robot_id="robot_sim")
store.insert("twin_versions", twin)
world = make_world_factory(store=store)
cand = derive_candidate(v1, MutationType.WORKFLOW, {
  "workflow_steps": [{"op":"observe"},{"op":"check_board_pose"},{"op":"retrieve_calibration_uncertainty"},{"op":"plan_move"},{"op":"simulate_if_uncertain"},{"op":"execute_move"},{"op":"verify"},{"op":"retry_or_recover"},{"op":"record"}],
  "retry_policy": {"max_retries": 1, "reobserve_before_retry": True, "replan_before_retry": True}}, "reobserve and replan after miss")
store.insert("harness_versions", cand)
r = evaluate_candidate(cand.id, twin, world, store)
print(r.decision, r.reasons)
print(json.dumps(r.simulation_metrics, indent=1, default=str)[:1500])
print("active:", get_active(store).version)
