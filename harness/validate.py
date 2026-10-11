"""Schema + permission validation for candidate harness versions (PRD §8.8, §21)."""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from harness.ops import ALLOWED_OPS, PHYSICAL_OPS
from shared.schemas import HarnessVersion, MutationType

# Fields the Scientist is permitted to touch, per mutation type (PRD §8.3).
MUTABLE_FIELDS: dict[MutationType, set[str]] = {
    MutationType.PARAMETER: {"retry_policy", "experiment_policy.simulation_budget"},
    MutationType.WORKFLOW: {"workflow_steps", "retry_policy"},
    MutationType.MEMORY_POLICY: {"memory_policy"},
    MutationType.EXPERIMENT_POLICY: {"experiment_policy"},
    MutationType.TOOL_POLICY: {"workflow_steps"},
}

# Never mutable from a document. Safety envelope lives in the gateway (PRD §6.6).
PROTECTED_FIELDS = {"_id", "version", "parent_version_id", "status", "created_by", "created_at", "schema_version"}

REQUIRED_SEQUENCE = ["observe", "plan_move", "execute_move", "verify", "record"]


class HarnessValidationError(Exception):
    pass


def validate_harness(doc: dict[str, Any]) -> HarnessVersion:
    try:
        hv = HarnessVersion.model_validate(doc)
    except ValidationError as e:
        raise HarnessValidationError(f"schema: {e.errors()[0]['msg']} at {e.errors()[0]['loc']}") from e

    ops = [s.op for s in hv.workflow_steps]
    unknown = [o for o in ops if o not in ALLOWED_OPS]
    if unknown:
        raise HarnessValidationError(f"unsupported operation(s): {unknown}")
    if sum(o in PHYSICAL_OPS for o in ops) > 1:
        raise HarnessValidationError("workflow may contain at most one physical motion op")
    # Required skeleton must appear in order (other ops may interleave).
    it = iter(ops)
    for req in REQUIRED_SEQUENCE:
        if not any(o == req for o in it):
            raise HarnessValidationError(f"workflow must contain '{req}' after preceding required ops")
    if hv.retry_policy.max_retries > 3:
        raise HarnessValidationError("max_retries > 3 exceeds the bounded-motion policy")
    if hv.experiment_policy.simulation_budget > 2000:
        raise HarnessValidationError("simulation_budget exceeds hard cap 2000")
    return hv


def _touched_paths(patch: dict[str, Any], prefix: str = "") -> set[str]:
    out: set[str] = set()
    for k, v in patch.items():
        path = f"{prefix}{k}"
        out.add(path)
        if isinstance(v, dict) and not path.startswith("workflow_steps"):
            out |= _touched_paths(v, path + ".")
    return out


def validate_permissions(mutation_type: MutationType, patch: dict[str, Any]) -> None:
    touched = _touched_paths(patch)
    if touched & PROTECTED_FIELDS:
        raise HarnessValidationError(f"patch touches protected fields: {sorted(touched & PROTECTED_FIELDS)}")
    allowed = MUTABLE_FIELDS[mutation_type]
    for path in patch.keys():
        if not any(path == a or path.startswith(a + ".") or a.startswith(path + ".") for a in allowed):
            raise HarnessValidationError(f"{mutation_type.value} mutation may not change '{path}'")
