"""Level-1 digital twin for the SO-101: geometric calibration + MuJoCo kinematics.

Plans exactly like the geometric twin (board -> base through the believed calibration),
and additionally predicts admissibility from the robot's real kinematics: IK
reachability with the tool pointing down, residual, and tilt. It never claims to
know the physical world's servo offsets or the board's true pose.
"""
from __future__ import annotations

import numpy as np

from shared.schemas import XY, TwinVersion
from simulation.twin import GeometricTwin, Prediction, in_workspace


class So101Twin(GeometricTwin):
    _kin = None  # shared kinematics instance (model load is ~50 ms)

    def __init__(self, twin: TwinVersion, rng=None, height_mm: float = 40.0) -> None:
        super().__init__(twin, rng)
        self.height_mm = height_mm
        if So101Twin._kin is None:
            from simulation.so101.kinematics import So101Kinematics

            So101Twin._kin = So101Kinematics()

    def predict(self, target_board: XY, truth=None) -> Prediction:
        p = super().predict(target_board, truth)
        if not in_workspace(target_board, margin_mm=5.0):
            return p
        cmd = p.commanded_base_mm
        r = self._kin.ik(np.array([cmd.x, cmd.y, self.height_mm]) / 1000.0)
        if not r.ok:
            return Prediction(cmd, p.predicted_board_mm, float("inf"), p.sigma_mm, False,
                              f"SO-101 cannot reach ({r.pos_err_mm:.1f} mm residual, {r.tilt_deg:.1f} deg tilt)")
        return Prediction(cmd, p.predicted_board_mm, p.predicted_error_mm, p.sigma_mm + r.pos_err_mm, True, "")


def make_twin(tv: TwinVersion) -> GeometricTwin:
    if tv.backend == "mujoco" and tv.robot_model == "so101":
        return So101Twin(tv)
    return GeometricTwin(tv)
