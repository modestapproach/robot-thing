"""Simulated worlds: a gateway backed by the mock arm + mock camera with a hidden truth.

``make_world_factory`` returns a zero-arg callable that builds an identically
seeded world each call, so baseline and candidate harnesses face the same hidden
calibration error, the same noise, and the same disturbances (PRD §14.2 controls).
"""
from __future__ import annotations

from typing import Callable

from robot_gateway.camera import MockCamera
from robot_gateway.driver import MockArmDriver
from robot_gateway.gateway import Gateway
from shared.schemas import XY, CalibrationParameters
from shared.store import Store, get_store

# The "real" world differs from the believed identity calibration: the board was
# placed ~6 mm right, ~4 mm down and rotated 1.5 degrees relative to belief.
DEFAULT_TRUTH = CalibrationParameters(offset_mm=XY(x=6.0, y=-4.0), rotation_deg=1.5, scale=1.0, calibration_version="truth")


def make_world_factory(
    truth: CalibrationParameters = DEFAULT_TRUTH,
    seed: int = 7,
    observation_sigma_mm: float = 0.4,
    store: Store | None = None,
    board_bump: tuple[float, float, float] | None = None,
) -> Callable[[], Gateway]:
    def factory() -> Gateway:
        cam = MockCamera(truth, observation_sigma_mm=observation_sigma_mm, seed=seed)
        if board_bump:
            cam.nudge_board(*board_bump)
        return Gateway(MockArmDriver(latency_s=0.0), cam, robot_id="robot_sim", store=store or get_store(), physical_enabled=True)

    return factory


# ----------------------------------------------------------------------------- SO-101 physics world
# The lab's "real" SO-101 setup: board placed a few mm / ~1 deg off the tape-measured nominal,
# and two servos with small zero offsets the controller does not know about.
def so101_truth():
    from simulation.so101.sim import NOMINAL_BOARD

    return NOMINAL_BOARD.model_copy(update={
        "offset_mm": XY(x=NOMINAL_BOARD.offset_mm.x + 4.0, y=NOMINAL_BOARD.offset_mm.y - 3.0),
        "rotation_deg": NOMINAL_BOARD.rotation_deg + 1.2, "calibration_version": "truth"})


SO101_TRUE_JOINT_OFFSETS_DEG = {"shoulder_lift": 0.6, "elbow_flex": -0.5}


def make_so101_world_factory(
    board_truth: CalibrationParameters | None = None,
    joint_offsets_deg: dict[str, float] | None = None,
    seed: int = 7,
    observation_sigma_mm: float = 0.3,
    store: Store | None = None,
    board_bump: tuple[float, float, float] | None = None,
) -> Callable[[], Gateway]:
    """Fresh SO-101 MuJoCo world per call: identical truth, noise and disturbances for every harness.

    ``board_bump`` moves the physical board (truth) *and* the camera's reference, exactly like
    knocking the board on a real table.
    """
    from robot_gateway.drivers.so101_sim import So101SimDriver
    from simulation.twin import board_to_base  # noqa: F401

    truth = board_truth or so101_truth()
    if board_bump:
        truth = truth.model_copy(update={"offset_mm": XY(x=truth.offset_mm.x + board_bump[0], y=truth.offset_mm.y + board_bump[1]),
                                         "rotation_deg": truth.rotation_deg + board_bump[2]})
    offsets = SO101_TRUE_JOINT_OFFSETS_DEG if joint_offsets_deg is None else joint_offsets_deg

    def factory() -> Gateway:
        cam = MockCamera(truth, observation_sigma_mm=observation_sigma_mm, seed=seed)
        cam.board_moved = bool(board_bump)
        return Gateway(So101SimDriver(board=truth, joint_offsets_deg=offsets), cam, robot_id="robot_so101",
                       store=store or get_store(), physical_enabled=True)

    return factory
