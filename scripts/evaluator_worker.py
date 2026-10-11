"""Independent evaluator worker. Runs next to the robot gateway, never inside an agent.

  .venv/bin/python scripts/evaluator_worker.py            # poll forever
  .venv/bin/python scripts/evaluator_worker.py --once     # drain the queue and exit

Evaluates every candidate a hosted Scientist submitted (``review_requested``) on the
protected suite: a simulated world built from the latest visible evidence, then the
physical stage on the lab gateway (mock until the real driver is configured).
"""
import argparse
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import shared.config  # noqa: F401

from agents.operator.operator import latest_twin
from evaluation import evaluator
from evaluation.review_queue import pending
from orchestrator.campaign import Campaign
from shared.store import get_store

ap = argparse.ArgumentParser()
ap.add_argument("--once", action="store_true")
a = ap.parse_args()

store = get_store()
print(f"evaluator worker on {type(store).__name__}")
while True:
    jobs = pending(store)
    for hv in jobs:
        camps = store.find("experiment_campaigns", {}, sort=[("updated_at", -1)], limit=1)
        lab = Campaign(store, campaign_id=camps[0]["_id"], log=lambda m: None) if camps else Campaign(store, log=lambda m: None)
        res = evaluator.evaluate_candidate(hv["_id"], latest_twin(store), lab._sim_world_from_evidence(), store, physical_world=lab.lab.factory())
        store.update("harness_versions", hv["_id"], {"review_requested": False})
        print(f"{hv['_id']}: {res.decision.value} - {res.reasons[-1] if res.reasons else ''}")
    if a.once:
        break
    time.sleep(3)
