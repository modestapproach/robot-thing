"""Level-0 geometric digital twin (PRD §7.2).

The twin is an *executable* predictive model: given a commanded board-frame
target and a calibration, it predicts where the end effector will land, with
uncertainty. It never claims rigid-body fidelity; Level 1/2 backends plug in
behind the same ``predict`` interface.

Frames (PRD §6.3): the robot executes commands in F_base; the camera measures in
F_board. The twin's calibration is the F_board -> F_base similarity transform.
Miscalibration (offset / rotation / scale error) is exactly what produces a
systematic positioning error on the real arm, so a candidate calibration is a
candidate *twin parameter set*.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from shared.schemas import XY, CalibrationParameters, TwinVersion, UncertaintyParameters

# Fixed, measured board geometry (fixtures/board_a4.json mirrors this).
BOARD_W_MM = 200.0
BOARD_H_MM = 150.0
SAFE_HEIGHT_MM = 40.0


def _T(cal: CalibrationParameters) -> np.ndarray:
    th = math.radians(cal.rotation_deg)
    c, s = math.cos(th), math.sin(th)
    return np.array(
        [
            [cal.scale * c, -cal.scale * s, cal.offset_mm.x],
            [cal.scale * s, cal.scale * c, cal.offset_mm.y],
            [0.0, 0.0, 1.0],
        ]
    )


def board_to_base(p: XY, cal: CalibrationParameters) -> XY:
    v = _T(cal) @ np.array([p.x, p.y, 1.0])
    return XY(x=float(v[0]), y=float(v[1]))


def base_to_board(p: XY, cal: CalibrationParameters) -> XY:
    v = np.linalg.inv(_T(cal)) @ np.array([p.x, p.y, 1.0])
    return XY(x=float(v[0]), y=float(v[1]))


def in_workspace(p: XY, margin_mm: float = 0.0) -> bool:
    return -margin_mm <= p.x <= BOARD_W_MM + margin_mm and -margin_mm <= p.y <= BOARD_H_MM + margin_mm


@dataclass
class Prediction:
    commanded_base_mm: XY
    predicted_board_mm: XY
    predicted_error_mm: float
    sigma_mm: float
    admissible: bool
    reason: str = ""


class GeometricTwin:
    """Predicts outcomes of commanding the arm to a board target under a calibration.

    ``believed`` is the calibration the harness uses to plan. ``truth`` is the
    (unknown) real transform; it is only supplied in simulation to generate
    synthetic observations. On real hardware the camera supplies truth.
    """

    def __init__(self, twin: TwinVersion, rng: np.random.Generator | None = None) -> None:
        self.twin = twin
        self.rng = rng or np.random.default_rng(0)

    @property
    def cal(self) -> CalibrationParameters:
        return self.twin.calibration_parameters

    @property
    def unc(self) -> UncertaintyParameters:
        return self.twin.uncertainty_parameters

    def plan(self, target_board: XY) -> XY:
        """Commanded F_base position for a board target under the believed calibration."""
        return board_to_base(target_board, self.cal)

    def predict(self, target_board: XY, truth: CalibrationParameters | None = None) -> Prediction:
        cmd = self.plan(target_board)
        if not in_workspace(target_board, margin_mm=5.0):
            return Prediction(cmd, target_board, float("inf"), 0.0, False, "target outside workspace")
        # Where the arm will actually land, expressed back in board frame.
        land = base_to_board(cmd, truth) if truth else target_board
        err = land.dist(target_board)
        sigma = math.hypot(self.unc.actuation_sigma_mm, self.unc.observation_sigma_mm)
        return Prediction(cmd, land, err, sigma, True)

    def synthesize_observation(self, target_board: XY, truth: CalibrationParameters, seed: int) -> XY:
        """Simulated camera measurement: truth landing point + actuation + observation noise."""
        rng = np.random.default_rng(seed)
        p = self.predict(target_board, truth).predicted_board_mm
        n = rng.normal(0.0, 1.0, 4)
        return XY(
            x=p.x + n[0] * self.unc.actuation_sigma_mm + n[2] * self.unc.observation_sigma_mm,
            y=p.y + n[1] * self.unc.actuation_sigma_mm + n[3] * self.unc.observation_sigma_mm,
        )


def fit_calibration(
    targets: list[XY], observed: list[XY], base_cal: CalibrationParameters
) -> CalibrationParameters:
    """Estimate a corrected F_board->F_base transform from (target, observed) pairs.

    The arm was commanded to ``board_to_base(target, base_cal)`` and the camera
    saw it at ``observed``. The true transform maps ``observed`` to that command,
    so fit a 2-D similarity ``observed -> commanded`` (Umeyama, closed form).
    Needs >= 3 non-collinear points for scale+rotation; with 1-2 points only the
    offset is updated.
    """
    if not targets:
        return base_cal
    cmd = np.array([[q.x, q.y] for q in (board_to_base(t, base_cal) for t in targets)])
    obs = np.array([[o.x, o.y] for o in observed])
    if len(targets) < 3:
        d = (cmd - obs).mean(axis=0)
        th = math.radians(base_cal.rotation_deg)
        # offset such that observed maps onto commanded with current rot/scale
        R = base_cal.scale * np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
        t = (cmd - obs @ R.T).mean(axis=0)
        return base_cal.model_copy(update={"offset_mm": XY(x=float(t[0]), y=float(t[1]))})
    mu_o, mu_c = obs.mean(0), cmd.mean(0)
    O, C = obs - mu_o, cmd - mu_c
    H = O.T @ C / len(obs)
    U, S, Vt = np.linalg.svd(H)
    D = np.eye(2)
    if np.linalg.det(U @ Vt) < 0:
        D[1, 1] = -1
    R = Vt.T @ D @ U.T
    var_o = (O**2).sum() / len(obs)
    scale = float((S * np.diag(D)).sum() / var_o)
    t = mu_c - scale * R @ mu_o
    rot = math.degrees(math.atan2(R[1, 0], R[0, 0]))
    return base_cal.model_copy(update={"offset_mm": XY(x=float(t[0]), y=float(t[1])), "rotation_deg": rot, "scale": scale})
