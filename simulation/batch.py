"""Simulation batch engine (PRD §7.4-7.5).

A batch evaluates candidate *twin parameter sets* (calibrations) against a set
of measured physical observations: for each candidate, how well does the twin
predict where the arm actually landed? Lower prediction error = better twin.
Cheap geometric checks run first; only admissible candidates are scored.
Results are always tagged ``simulation`` and never confused with measurements.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from shared.ids import new_id
from shared.schemas import XY, CalibrationParameters, TwinVersion
from simulation.twin import base_to_board, board_to_base


@dataclass
class BatchSpec:
    twin_version_id: str
    base_calibration: CalibrationParameters
    candidates: list[CalibrationParameters]
    # Physical evidence: (target_board, observed_board) from real/mocked runs commanded with base_calibration.
    evidence: list[tuple[XY, XY]]
    policy_version_id: str = ""
    max_trials: int = 1000
    render_sample_count: int = 0
    batch_id: str = field(default_factory=lambda: new_id("batch"))


@dataclass
class BatchResult:
    batch_id: str
    status: str = "queued"
    trials_completed: int = 0
    scores: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    best_index: Optional[int] = None
    duration_s: float = 0.0
    environment: str = "simulation"


def _admissible(c: CalibrationParameters, ref: CalibrationParameters) -> Optional[str]:
    """Plausibility relative to the current (measured) calibration, not to the origin."""
    if not (0.9 <= c.scale <= 1.1):
        return "scale outside physically plausible range [0.9, 1.1]"
    if abs((c.rotation_deg - ref.rotation_deg + 180) % 360 - 180) > 10:
        return "rotation change > 10 deg is implausible for a fixed board mount"
    if math.hypot(c.offset_mm.x - ref.offset_mm.x, c.offset_mm.y - ref.offset_mm.y) > 40:
        return "board shift > 40 mm contradicts measured mount tolerance"
    return None


def score_candidate(cand: CalibrationParameters, spec: BatchSpec) -> dict[str, Any]:
    """Predict each observed landing point under ``cand`` as the true transform."""
    errs = []
    for target, observed in spec.evidence:
        cmd = board_to_base(target, spec.base_calibration)
        predicted_landing = base_to_board(cmd, cand)
        errs.append(predicted_landing.dist(observed))
    # Residual error a *future* move would have if we planned with cand and cand were true:
    rmse = math.sqrt(sum(e * e for e in errs) / len(errs)) if errs else float("nan")
    return {"prediction_rmse_mm": rmse, "max_mm": max(errs) if errs else float("nan"), "n_evidence": len(errs)}


def run_batch(spec: BatchSpec, result: BatchResult | None = None) -> BatchResult:
    res = result or BatchResult(batch_id=spec.batch_id)
    res.status = "running"
    t0 = time.time()
    for i, c in enumerate(spec.candidates[: spec.max_trials]):
        why = _admissible(c, spec.base_calibration)
        if why:
            res.rejected.append({"index": i, "reason": why, "candidate": c.model_dump()})
        else:
            res.scores.append({"index": i, "candidate": c.model_dump(), **score_candidate(c, spec)})
        res.trials_completed += 1
    if res.scores:
        best = min(res.scores, key=lambda s: s["prediction_rmse_mm"])
        res.best_index = best["index"]
    res.scores.sort(key=lambda s: s["prediction_rmse_mm"])
    res.duration_s = time.time() - t0
    res.status = "completed"
    return res


class BatchRunner:
    """In-process async job runner. Long jobs return an id immediately (PRD §9.2)."""

    def __init__(self) -> None:
        self.jobs: dict[str, BatchResult] = {}

    def submit(self, spec: BatchSpec) -> str:
        res = BatchResult(batch_id=spec.batch_id)
        self.jobs[spec.batch_id] = res
        threading.Thread(target=run_batch, args=(spec, res), daemon=True).start()
        return spec.batch_id

    def get(self, batch_id: str) -> Optional[BatchResult]:
        return self.jobs.get(batch_id)
