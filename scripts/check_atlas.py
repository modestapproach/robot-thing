"""Verify the Atlas connection, create indexes, and seed the baseline harness + twin.

Usage:  .venv/bin/python scripts/check_atlas.py
Reads MONGODB_URI from autolab/.env. Safe to re-run (idempotent seeding).
"""
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import shared.config  # noqa: F401  (loads .env)

uri = os.environ.get("MONGODB_URI")
if not uri:
    sys.exit("MONGODB_URI is not set. Paste the Atlas connection string into autolab/.env")
if "<db_password>" in uri:
    sys.exit("Replace <db_password> in autolab/.env with the ted-dessert database user's password (URL-encode special characters).")

from pymongo import MongoClient

client = MongoClient(uri, serverSelectionTimeoutMS=8000)
try:
    client.admin.command("ping")
except Exception as e:
    hint = ""
    if "auth" in str(e).lower():
        hint = "\n  -> check the database user's password in the URI (URL-encode special characters)."
    elif "timed out" in str(e).lower() or "ServerSelection" in type(e).__name__:
        hint = "\n  -> your current IP is probably not on the Atlas IP Access List."
    sys.exit(f"Atlas ping failed: {e}{hint}")

db_name = os.environ.get("AUTOLAB_DB", "autolab")
print(f"connected: {client.address} db={db_name}")

from orchestrator.campaign import Campaign, world_kind
from shared.store import MongoStore

store = MongoStore(uri, db_name)  # creates indexes
# Same world-aware seeding the campaign uses (SO-101 twin when MuJoCo is available).
seeder = Campaign.__new__(Campaign)
seeder.store = store
seeder._seed()
print("world:", world_kind(), "| twin:", store.find("twin_versions", {}, sort=[("created_at", -1)], limit=1)[0]["_id"])
print("collections:", sorted(client[db_name].list_collection_names()))
print("active harness:", store.find("harness_versions", {"status": "ACTIVE"}, limit=1)[0]["_id"])
