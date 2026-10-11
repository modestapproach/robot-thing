"""The closed set of operations a harness workflow may reference (PRD §8.3).

The Scientist can reorder or add these; it cannot invent new ones. Each op is a
pure description; execution is delegated to a ``Toolbox`` the runtime is given.
"""
from __future__ import annotations

ALLOWED_OPS: dict[str, str] = {
    "observe": "Capture a camera observation and current robot state.",
    "check_board_pose": "Compare current board pose with the calibrated pose; flag movement.",
    "retrieve_calibration_uncertainty": "Read the active twin's uncertainty parameters.",
    "retrieve_prior_failures": "Fetch similar historical failures from memory/experiments.",
    "plan_move": "Compute the commanded position for the target using the twin.",
    "simulate_if_uncertain": "Preview the move on the twin; require sim pass if predicted error exceeds threshold.",
    "execute_move": "Submit a bounded physical/simulated move through the gateway.",
    "verify": "Measure the result and compute error.",
    "retry_or_recover": "Apply the retry policy on failure.",
    "record": "Persist the finalized experiment.",
}

# Ops that may issue a physical motion. At most one per workflow pass is enforced
# by the gateway, but the validator also refuses workflows with more than one.
PHYSICAL_OPS = {"execute_move"}
