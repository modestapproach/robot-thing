"""SO-101 conveyor cell: belt physics, vision, a real grasp, money rules, Gymnasium API."""
import numpy as np
import pytest

pytest.importorskip("mujoco")
pytest.importorskip("cv2")

from simulation.conveyor.cell import PAYOUT, ConveyorCell  # noqa: E402
from simulation.conveyor.picker import Picker  # noqa: E402
from simulation.conveyor.scene import BELT_TOP, BELT_X, BELT_Y1, CUBE_HALF, DISC_HALF_H  # noqa: E402
from simulation.conveyor.vision import BeltCamera  # noqa: E402


def _place(cell, i, xy, yaw=0.0):
    h = CUBE_HALF if cell.kinds[i] == "red_square" else DISC_HALF_H
    cell._place(i, [xy[0], xy[1], BELT_TOP + h + 0.003], yaw)
    cell.state[i] = "belt"


def _first(cell, kind):
    return next(i for i, k in enumerate(cell.kinds) if k == kind)


def test_belt_carries_cubes_and_discs_by_friction():
    cell = ConveyorCell()
    cell.set_arm(np.array([-1.23, -0.21, 0.12, 1.66, 0.0, 0.55]), snap=True)
    cell._next_dispense = 1e9  # no feeder in this test
    r, b = _first(cell, "red_square"), _first(cell, "blue_circle")
    _place(cell, r, (BELT_X, 0.20), 0.4)
    _place(cell, b, (BELT_X, 0.12))
    y0 = cell.obj_pos(r)[1], cell.obj_pos(b)[1]
    cell.step(100)  # 2 s
    for i, y in zip((r, b), y0):
        speed = (y - cell.obj_pos(i)[1]) / 2.0
        assert 0.035 < speed < 0.055, (cell.kinds[i], speed)
    cell.set_belt(False)
    cell.step(25)
    y_stop = cell.obj_pos(r)[1]
    cell.step(50)
    assert abs(cell.obj_pos(r)[1] - y_stop) < 0.002  # line stops when the rollers stop


def test_vision_finds_red_squares_to_millimetres_and_ignores_blue():
    cell = ConveyorCell()
    cell.set_arm(np.array([-1.23, -0.21, 0.12, 1.66, 0.0, 0.55]), snap=True)
    reds = [i for i, k in enumerate(cell.kinds) if k == "red_square"][:2]
    blue = _first(cell, "blue_circle")
    truth = [(reds[0], (BELT_X + 0.01, 0.15), 0.3), (reds[1], (BELT_X - 0.012, 0.05), -0.5), (blue, (BELT_X, 0.10), 0.0)]
    for i, xy, yaw in truth:
        _place(cell, i, xy, yaw)
    cell.step(5)
    cam = BeltCamera(cell.m, cell.d)
    dets = cam.detect(cam.rgb(), BELT_TOP + 2 * CUBE_HALF)
    sq = [d for d in dets if d.kind == "red_square"]
    assert len(sq) == 2 and any(d.kind == "blue_circle" for d in dets)
    for i, _, _ in truth[:2]:
        p = cell.obj_pos(i)[:2]
        assert min(np.linalg.norm(d.xy - p) for d in sq) < 0.003


def test_scripted_picker_grasps_a_red_square_and_gets_paid():
    cell = ConveyorCell()
    pk = Picker(cell)
    pk.run(duration_s=12.0)  # first red square reaches the pick line at ~9 s with seed 0
    assert pk.stats.grasped >= 1
    assert cell.ledger.count("bin", "red_square") >= 1 and cell.ledger.balance >= PAYOUT["bin:red_square"] - 1e-9


def test_blue_circle_off_the_end_costs_nothing_and_red_costs_a_dollar():
    cell = ConveyorCell()
    cell.set_arm(np.array([-1.23, -0.21, 0.12, 1.66, 0.0, 0.55]), snap=True)
    cell._next_dispense = 1e9
    r, b = _first(cell, "red_square"), _first(cell, "blue_circle")
    _place(cell, r, (BELT_X, BELT_Y1 + 0.03))
    _place(cell, b, (BELT_X, BELT_Y1 + 0.06))
    cell.step(150)  # 3 s
    out = {(e.kind, e.outcome): e.amount for e in cell.ledger.entries}
    assert out.get(("red_square", "end")) == -1.0 and out.get(("blue_circle", "end")) == 0.0
    assert cell.ledger.balance == -1.0


def test_gymnasium_env_passes_the_official_checker():
    from gymnasium.utils.env_checker import check_env

    from simulation.conveyor.env import So101ConveyorEnv

    env = So101ConveyorEnv(episode_s=0.5)
    check_env(env, skip_render_check=True)
