"""Review queue: how a *hosted* Scientist hands candidates to the independent evaluator.

The Scientist can only set ``review_requested`` on a PROPOSED candidate. The
evaluator worker (scripts/evaluator_worker.py) runs locally beside the gateway,
owns the protected targets and the evaluation worlds, and is the only process
that can transition or promote harness versions.
"""
from __future__ import annotations

from shared.schemas import HarnessStatus, utcnow
from shared.store import Store


def request_review(store: Store, candidate_id: str) -> bool:
    ok = store.conditional_update(
        "harness_versions",
        {"_id": candidate_id, "status": HarnessStatus.PROPOSED.value},
        {"review_requested": True, "review_requested_at": utcnow()},
    )
    if ok:
        store.audit("review_requested", candidate=candidate_id)
    return ok


def review_status(store: Store, candidate_id: str) -> dict:
    hv = store.get("harness_versions", candidate_id) or {}
    ev = store.find("evaluation_results", {"candidate_version_id": candidate_id}, limit=1)
    return {
        "status": hv.get("status", "unknown"),
        "decision": ev[0]["decision"] if ev else None,
        "reasons": ev[0]["reasons"] if ev else [],
    }


def pending(store: Store) -> list[dict]:
    return store.find("harness_versions", {"status": HarnessStatus.PROPOSED.value, "review_requested": True}, sort=[("created_at", 1)])
