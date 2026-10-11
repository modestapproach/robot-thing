"""Fixed hardware safety envelope (PRD §6.6). Not reachable from any Atlas document.

The AI may tighten these through its harness (e.g. lower speed), never loosen them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shared.schemas import XY, MoveRequest
from simulation.twin import BOARD_H_MM, BOARD_W_MM


@dataclass(frozen=True)
class SafetyEnvelope:
    # F_base reachable box, mm. Generous default for the mock; tighten for the real arm.
    x_min: float = -50.0
    x_max: float = 300.0
    y_min: float = -50.0
    y_max: float = 250.0
    min_height_mm: float = 30.0
    max_height_mm: float = 200.0
    max_speed_fraction: float = 0.5
    command_timeout_s: float = 8.0
    max_step_mm: float = 250.0  # single-move travel cap


DEFAULT_ENVELOPE = SafetyEnvelope()

# SO-101 (TheRobotStudio / LeRobot): F_base mm, tool point = gripperframe between the jaw tips.
# Reach pointing down at 40 mm is ~265 mm from the base origin; keep a margin to the base itself.
SO101_ENVELOPE = SafetyEnvelope(
    x_min=90.0, x_max=280.0, y_min=-140.0, y_max=140.0,
    min_height_mm=25.0, max_height_mm=200.0,
    max_speed_fraction=0.5, command_timeout_s=8.0, max_step_mm=320.0,
)


class SafetyViolation(Exception):
    pass


def validate_move(req: MoveRequest, base_target: XY, current: XY | None, env: SafetyEnvelope = DEFAULT_ENVELOPE) -> MoveRequest:
    """Return a clamped-speed copy of ``req`` or raise. Position is never clamped: out = reject."""
    if not (env.x_min <= base_target.x <= env.x_max and env.y_min <= base_target.y <= env.y_max):
        raise SafetyViolation(f"base target {base_target} outside reachable box")
    if not (env.min_height_mm <= req.height_mm <= env.max_height_mm):
        raise SafetyViolation(f"height {req.height_mm} outside [{env.min_height_mm}, {env.max_height_mm}]")
    if current is not None and current.dist(base_target) > env.max_step_mm:
        raise SafetyViolation("single move exceeds max_step_mm")
    return req.model_copy(update={"speed_fraction": min(req.speed_fraction, env.max_speed_fraction)})
