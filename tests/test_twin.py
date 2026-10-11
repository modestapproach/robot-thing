import math

from shared.schemas import XY, CalibrationParameters
from simulation.twin import base_to_board, board_to_base, fit_calibration


def test_transform_roundtrip():
    cal = CalibrationParameters(offset_mm=XY(x=5, y=-3), rotation_deg=2.0, scale=1.01)
    for p in [XY(x=0, y=0), XY(x=150, y=90), XY(x=-20, y=200)]:
        q = base_to_board(board_to_base(p, cal), cal)
        assert p.dist(q) < 1e-9


def test_fit_recovers_truth_without_noise():
    believed = CalibrationParameters()
    truth = CalibrationParameters(offset_mm=XY(x=6, y=-4), rotation_deg=1.5, scale=1.0)
    targets = [XY(x=30, y=30), XY(x=170, y=30), XY(x=170, y=120), XY(x=30, y=120)]
    observed = [base_to_board(board_to_base(t, believed), truth) for t in targets]
    fit = fit_calibration(targets, observed, believed)
    for t in [XY(x=100, y=75), XY(x=10, y=140)]:
        assert base_to_board(board_to_base(t, fit), truth).dist(t) < 1e-6
    assert math.isclose(fit.rotation_deg, 1.5, abs_tol=1e-6)
