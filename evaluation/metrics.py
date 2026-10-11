from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from harness.runtime import TaskResult


@dataclass
class HarnessMetrics:
    n: int
    success_rate: float
    mean_error_mm: float
    median_error_mm: float
    rmse_mm: float
    p90_error_mm: float
    unknown_rate: float
    observations_per_task: float
    movements_per_task: float
    retries_per_task: float
    sim_previews_per_task: float

    def to_dict(self) -> dict:
        return asdict(self)


def summarize(results: list[TaskResult]) -> HarnessMetrics:
    n = len(results)
    errs = sorted(r.error_mm for r in results if r.error_mm is not None)
    k = len(errs)

    def pct(p: float) -> float:
        if not errs:
            return float("nan")
        i = min(k - 1, int(math.ceil(p * k)) - 1)
        return errs[max(i, 0)]

    return HarnessMetrics(
        n=n,
        success_rate=sum(r.success for r in results) / n if n else 0.0,
        mean_error_mm=sum(errs) / k if k else float("nan"),
        median_error_mm=pct(0.5),
        rmse_mm=math.sqrt(sum(e * e for e in errs) / k) if k else float("nan"),
        p90_error_mm=pct(0.9),
        unknown_rate=(n - k) / n if n else 0.0,
        observations_per_task=sum(r.observations for r in results) / n if n else 0.0,
        movements_per_task=sum(r.movements for r in results) / n if n else 0.0,
        retries_per_task=sum(r.retries for r in results) / n if n else 0.0,
        sim_previews_per_task=sum(r.sim_previews for r in results) / n if n else 0.0,
    )
