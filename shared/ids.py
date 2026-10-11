"""Unique identifier helpers. Every operation in AutoLab has a unique ID (PRD §13.4)."""
from __future__ import annotations

import secrets
import time


def new_id(prefix: str) -> str:
    """Return a sortable, prefixed id like ``exp_018f3a2b_9c4d1e``."""
    ts = format(int(time.time() * 1000), "x")
    return f"{prefix}_{ts}_{secrets.token_hex(3)}"
