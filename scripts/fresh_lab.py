"""Start a clean demo lab in a new Atlas database and point everything at it.

  .venv/bin/python scripts/fresh_lab.py --db so101_demo

1. Checks Atlas is reachable from this network FIRST (venue IP must be on the access list);
   if not, exits without touching anything.
2. Switches autolab/.env (URI path + AUTOLAB_DB) to the new database. Old databases are left
   untouched (nothing is deleted).
3. Seeds the SO-101 twin + baseline harness, runs the full campaign, and syncs the dashboard env.
Restart the dashboard afterwards so it reconnects to the new database.
"""
import argparse
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--db", required=True, help="new database name, e.g. so101_demo")
a = ap.parse_args()
if not re.fullmatch(r"[A-Za-z0-9_]{3,40}", a.db):
    sys.exit("database name must be 3-40 letters, digits or underscores")

env = ROOT / ".env"
text = env.read_text()
m = re.search(r"^MONGODB_URI=(mongodb\+srv://[^@]+@[^/]+)/([^?]*)\?(.*)$", text, re.M)
if not m:
    sys.exit("MONGODB_URI in autolab/.env is not a mongodb+srv URI with a database path")

from pymongo import MongoClient  # noqa: E402

new_uri = f"{m.group(1)}/{a.db}?{m.group(3)}"
try:
    MongoClient(new_uri, serverSelectionTimeoutMS=8000).admin.command("ping")
except Exception as e:
    sys.exit(f"Atlas is not reachable from this network ({type(e).__name__}). Nothing was changed.\n"
             "Switch back to the venue Wi-Fi (its IP is on the Atlas access list) and rerun.")
if MongoClient(new_uri, serverSelectionTimeoutMS=8000)[a.db].list_collection_names():
    sys.exit(f"database '{a.db}' already has collections; pick a new name (nothing was changed)")

text = text.replace(m.group(0), f"MONGODB_URI={new_uri}", 1)
text = re.sub(r"^AUTOLAB_DB=.*$", f"AUTOLAB_DB={a.db}", text, count=1, flags=re.M)
env.write_text(text)
print(f"autolab/.env now points at database '{a.db}' (previous database left as is)")

py = str(ROOT / ".venv" / "bin" / "python")
for script in ("check_atlas.py", "run_campaign.py", "sync_dashboard_env.py"):
    print(f"--- {script}")
    r = subprocess.run([py, str(ROOT / "scripts" / script)], cwd=ROOT, env={k: v for k, v in os.environ.items() if k not in ("MONGODB_URI", "AUTOLAB_DB")})
    if r.returncode != 0:
        sys.exit(f"{script} failed (exit {r.returncode})")
print("done: restart the dashboard to pick up the new database")
