"""SO-101 simulated arm driver: the MuJoCo physics world behind the normal driver interface.

``is_physical = False`` — everything it produces is labelled simulation. The constructor
takes the *true* world (board pose, servo zero offsets) that the twin does not know.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from robot_gateway.driver import ArmDriver
from robot_gateway.safety import SO101_ENVELOPE
from shared.schemas import XY, CalibrationParameters
from simulation.so101.sim import NOMINAL_BOARD, MotionError, So101Sim


class So101SimDriver(ArmDriver):
    name = "so101_sim"
    is_physical = False
    envelope = SO101_ENVELOPE

    def __init__(self, board: CalibrationParameters = NOMINAL_BOARD, joint_offsets_deg: dict[str, float] | None = None) -> None:
        self.board = board
        self.offsets = joint_offsets_deg or {}
        self.sim: So101Sim | None = None
        self._traj: Optional[dict] = None
        self.commands_executed = 0

    def connect(self) -> None:
        self.sim = So101Sim(board=self.board, joint_offsets_deg=self.offsets)

    def is_connected(self) -> bool:
        return self.sim is not None

    def read_tool_position(self) -> tuple[XY, float]:
        assert self.sim
        p = self.sim.tool_mm()
        return XY(x=float(p[0]), y=float(p[1])), float(p[2])

    def read_joints(self) -> Optional[list[float]]:
        return [float(v) for v in np.degrees(self.sim.joints())] if self.sim else None

    def can_reach(self, base_mm: XY, height_mm: float) -> tuple[bool, str]:
        assert self.sim
        try:
            self.sim.plan(base_mm, height_mm)
            return True, ""
        except MotionError as e:
            return False, str(e)

    def move_to(self, base_mm: XY, height_mm: float, speed_fraction: float, timeout_s: float) -> None:
        if not self.sim:
            raise RuntimeError("driver not connected")
        r = self.sim.move_to(base_mm, height_mm, speed_fraction)
        if r.duration_s > timeout_s:
            raise TimeoutError(f"move took {r.duration_s:.2f}s > {timeout_s}s")
        if r.tracking_err_deg > 1.0:
            raise MotionError(f"servo did not settle (tracking error {r.tracking_err_deg:.2f} deg)")
        self._traj = r.trajectory
        self.commands_executed += 1

    def last_trajectory(self) -> Optional[dict]:
        t, self._traj = self._traj, None
        return t

    def stop(self) -> None:
        pass

    def home(self) -> None:
        self.connect()
