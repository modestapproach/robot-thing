"""Create a candidate harness version by applying a patch to a base version.

Candidates never mutate the active harness in place (PRD §13.4).
"""
from __future__ import annotations

import copy
from typing import Any

from harness.validate import validate_harness, validate_permissions
from shared.ids import new_id
from shared.schemas import HarnessStatus, HarnessVersion, MutationType


def apply_patch(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in patch.items():
        cur = out
        parts = k.split(".")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        if isinstance(v, dict) and isinstance(cur.get(parts[-1]), dict):
            cur[parts[-1]] = {**cur[parts[-1]], **v}
        else:
            cur[parts[-1]] = copy.deepcopy(v)
    return out


def derive_candidate(
    base: HarnessVersion,
    mutation_type: MutationType,
    patch: dict[str, Any],
    reason: str,
    created_by: str = "autolab-scientist",
) -> HarnessVersion:
    validate_permissions(mutation_type, patch)
    base_doc = base.model_dump(by_alias=True)
    cand = apply_patch(base_doc, patch)
    cand["_id"] = new_id("hv")
    cand["version"] = base.version + 1
    cand["parent_version_id"] = base.id
    cand["status"] = HarnessStatus.PROPOSED.value
    cand["created_by"] = created_by
    cand["proposal_reason"] = reason
    cand.pop("created_at", None)
    return validate_harness(cand)
