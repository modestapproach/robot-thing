"""Protected test suite. The Scientist may propose *additional* tests but cannot
replace or weaken these (PRD §5.1 Evaluator). Version bump this string when the
suite changes so every EvaluationResult records what it was judged against.
"""
from __future__ import annotations

import json
from pathlib import Path

PROTECTED_TEST_SET_VERSION = "protected_v1"
_FIX = Path(__file__).resolve().parent.parent / "fixtures" / "scenarios.json"


def protected_targets() -> list[dict]:
    return json.loads(_FIX.read_text())["protected"]


def non_protected_targets() -> list[dict]:
    d = json.loads(_FIX.read_text())
    return d["calibration"] + d["selection"]


# Acceptance thresholds for promotion (team-defined, PRD §14.6).
MIN_SUCCESS_RATE_DELTA = 0.0  # candidate must not be worse
MIN_RMSE_IMPROVEMENT_FRACTION = 0.10  # or must cut RMSE by >= 10 %
MAX_EXTRA_OBSERVATIONS_PER_TASK = 2.0
MAX_EXTRA_MOVEMENTS_PER_TASK = 1.0
