"""Run the full AutoLab demo campaign.

  .venv/bin/python scripts/run_campaign.py                     # in-memory (or Atlas if MONGODB_URI set)
  .venv/bin/python scripts/run_campaign.py --stop-after disturbance
  .venv/bin/python scripts/run_campaign.py --resume <campaign_id>

Without MONGODB_URI, state persists to .autolab-state.pkl so --resume works offline.
"""
import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import shared.config  # noqa: F401

ap = argparse.ArgumentParser()
ap.add_argument("--resume")
ap.add_argument("--stop-after")
ap.add_argument("--fresh", action="store_true", help="discard offline state file first")
ap.add_argument("--report", default=str(ROOT / "docs/last_campaign.json"))
ap.add_argument("--worker", action="store_true", help="poll for dashboard-requested or resume-requested campaigns")
a = ap.parse_args()

if not os.environ.get("MONGODB_URI") or "<db_password>" in os.environ.get("MONGODB_URI", ""):
    state = ROOT / ".autolab-state.pkl"
    if a.fresh and state.exists():
        state.unlink()
    os.environ.setdefault("AUTOLAB_STORE_FILE", str(state))

from orchestrator.campaign import Campaign, CampaignInterrupted
from shared.store import get_store

store = get_store()
print(f"store: {type(store).__name__}")

if a.worker:
    import time

    print("worker: polling for requested / resume-requested campaigns (Ctrl+C to stop)")
    while True:
        jobs = store.find("experiment_campaigns", {"status": "requested"}) + store.find("experiment_campaigns", {"resume_requested": True})
        for j in jobs:
            print(f"worker: running {j['_id']}")
            try:
                Campaign(store, campaign_id=j["_id"]).run()
            except CampaignInterrupted as e:
                print(f"[paused] {e}")
        time.sleep(3)

camp = Campaign(store, campaign_id=a.resume)
print(f"campaign: {camp.c.id}")
try:
    out = camp.run(stop_after=a.stop_after)
except CampaignInterrupted as e:
    print(f"[paused] {e}")
    sys.exit(0)
pathlib.Path(a.report).write_text(json.dumps(out, indent=1, default=str))
print(f"report: {a.report}")
