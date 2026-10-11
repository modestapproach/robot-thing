"""mink IK + Ruckig trajectories on the official SO-101 model."""
import numpy as np
import pytest

pytest.importorskip("mink")
pytest.importorskip("ruckig")

from simulation.so101.kinematics import So101Kinematics  # noqa: E402
from simulation.so101.motion import CONTROL_DT, MAX_ACC, MAX_VEL, plan_joint_trajectory  # noqa: E402
from simulation.so101.sim import NOMINAL_BOARD  # noqa: E402
from simulation.twin import board_to_base  # noqa: E402
from shared.schemas import XY  # noqa: E402


def test_mink_ik_points_down_within_half_degree_and_respects_limits():
    k = So101Kinematics()
    for bx, by in [(0, 0), (200, 0), (0, 150), (200, 150), (100, 75)]:
        b = board_to_base(XY(x=bx, y=by), NOMINAL_BOARD)
        r = k.ik(np.array([b.x, b.y, 40.0]) / 1000)
        assert r.ok and r.pos_err_mm < 0.2 and r.tilt_deg < 0.5, (bx, by, r)
        assert np.all(r.q >= k.lo - 1e-9) and np.all(r.q <= k.hi + 1e-9)


def test_ik_is_continuous_from_the_current_pose():
    k = So101Kinematics()
    a = board_to_base(XY(x=100, y=75), NOMINAL_BOARD)
    b = board_to_base(XY(x=104, y=75), NOMINAL_BOARD)
    ra = k.ik(np.array([a.x, a.y, 40.0]) / 1000)
    rb = k.ik(np.array([b.x, b.y, 40.0]) / 1000, q0=ra.q)
    assert np.abs(rb.q - ra.q).max() < 0.1  # 4 mm move -> small joint change, no branch flip


@pytest.mark.parametrize("speed", [0.15, 0.5, 1.0])
def test_ruckig_trajectory_is_limited_synchronized_and_exact(speed):
    q0 = np.array([0.0, -0.9, 0.9, 1.3, 0.0])
    q1 = np.array([0.6, -0.2, 0.5, 1.4, 0.3])
    t, P = plan_joint_trajectory(q0, q1, speed)
    assert np.allclose(P[-1], q1, atol=1e-9) and np.allclose(np.diff(t), CONTROL_DT)
    V = np.diff(np.vstack([q0, P]), axis=0) / CONTROL_DT
    A = np.diff(V, axis=0) / CONTROL_DT
    assert np.abs(V).max() <= MAX_VEL * speed + 1e-6
    assert np.abs(A).max() <= MAX_ACC * speed * 1.05  # finite-difference slack
    # synchronized: every joint is still moving until near the end (none finishes early)
    moving = np.abs(V) > 1e-9
    assert all(moving[: len(V) - 3, j].all() for j in range(5) if abs(q1[j] - q0[j]) > 1e-6)


def test_menagerie_clearance_rejects_paths_into_the_table_before_motion(store):
    from robot_gateway.camera import MockCamera
    from robot_gateway.drivers.so101_sim import So101SimDriver
    from robot_gateway.gateway import Gateway
    from robot_gateway.safety import SafetyEnvelope
    from shared.schemas import CommandStatus, MoveRequest
    from simulation.so101.sim import MotionError, So101Sim

    sim = So101Sim(joint_offsets_deg={})
    b = board_to_base(XY(x=100, y=75), NOMINAL_BOARD)
    assert sim.plan(b, 40.0) is not None  # normal working height is clear
    with pytest.raises(MotionError, match="within"):
        sim.plan(b, 5.0)  # jaws would go into the table
    # Through the gateway with an envelope that would otherwise allow 5 mm: rejected before any motion.
    drv = So101SimDriver(joint_offsets_deg={})
    env = SafetyEnvelope(x_min=90, x_max=280, y_min=-140, y_max=140, min_height_mm=1.0, max_height_mm=200, max_step_mm=320)
    gw = Gateway(drv, MockCamera(NOMINAL_BOARD), "so101", store=store, envelope=env, physical_enabled=True)
    c = gw.submit("low", "hv", MoveRequest(target_mm=XY(x=100, y=75), height_mm=5.0), b)
    assert c.status == CommandStatus.REJECTED and "table" in c.rejection_reason and drv.commands_executed == 0


def test_collision_model_matches_official_kinematics():
    import mujoco

    from simulation.so101.collision import So101Collision

    col, k = So101Collision(), So101Kinematics()
    rng = np.random.default_rng(3)
    for _ in range(20):
        q = rng.uniform(-1.2, 1.2, 5)
        k.fk(q)
        col.pose_clearance(q)
        for body in ["upper_arm", "lower_arm", "wrist", "gripper"]:
            assert np.allclose(k.d.xpos[k.m.body(body).id], col.d.xpos[col.m.body(body).id], atol=1e-6)
