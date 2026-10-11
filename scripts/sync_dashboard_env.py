"""Copy the canonical DB settings from autolab/.env into dashboard/.modelence.env.

One database for Python services and the Modelence dashboard (PRD §5.4). The
dashboard runs on port 3001 so it does not collide with the Agent Engine
playground on 3000. Re-run after editing autolab/.env.
"""
import pathlib
import secrets
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import os

import shared.config  # noqa: F401

uri = os.environ.get("MONGODB_URI", "")
if not uri or "<db_password>" in uri:
    sys.exit("Set a real MONGODB_URI in autolab/.env first (replace <db_password>).")
target = ROOT / "dashboard" / ".modelence.env"
existing = dict(l.split("=", 1) for l in target.read_text().splitlines() if "=" in l) if target.exists() else {}
existing["MONGODB_URI"] = uri
existing.setdefault("MODELENCE_PORT", "3001")
existing.setdefault("AUTOLAB_API_KEY", os.environ.get("AUTOLAB_API_KEY") or secrets.token_urlsafe(24))
target.write_text("".join(f"{k}={v}\n" for k, v in existing.items()))
print(f"wrote {target} (MONGODB_URI, MODELENCE_PORT={existing['MODELENCE_PORT']}, AUTOLAB_API_KEY)")
