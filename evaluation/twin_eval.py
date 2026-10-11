"""Evaluator-side held-out check for a twin update (PRD §14.1).

Compares the parent and candidate twin on protected targets with the same
harness. Runs evaluator-side, so protected outcomes never reach the Scientist.
"""
from __future__ import annotations

from evaluation.evaluator import run_suite
from evaluation.metrics import summarize
from evaluation.protected import protected_targets
from shared.schemas import HarnessVersion, TwinVersion
from shared.store import Store


def heldout_twin_comparison(harness: HarnessVersion, parent: TwinVersion, cand: TwinVersion, world, store: Store) -> dict:
    t = protected_targets()
    before = summarize(run_suite(harness, parent, world, store, t))
    after = summarize(run_suite(harness, cand, world, store, t))
    return {"before": before.to_dict(), "after": after.to_dict(), "n_targets": len(t),
            "rmse_reduction": (before.rmse_mm - after.rmse_mm) / before.rmse_mm if before.rmse_mm else None}
