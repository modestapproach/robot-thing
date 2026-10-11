"""Load ``autolab/.env`` into the process environment (no extra dependency).

Existing environment variables win, so CI/Agent Engine secrets override the file.
"""
from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path | None = None) -> None:
    p = path or _ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.split(" #", 1)[0].strip().strip('"').strip("'")
        if v and k.strip() not in os.environ:
            os.environ[k.strip()] = v


load_env()
