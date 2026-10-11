"""LeRobot SO-101 driver against a stub follower (no hardware, no lerobot install)."""
import math

import numpy as np
import pytest

pytest.importorskip("mujoco")

from robot_gateway.drivers.so101_lerobot import CalibrationMissing, So101LeRobotDriver  # noqa: E402
from shared.schemas import XY  # noqa: E402
from simulation.so101.kinematics import ARM_JOINTS  # noqa: E402
from simulation.so101.sim import NOMINAL_BOARD  # noqa: E402
from simulation.twin import board_to_base  # noqa: E402


class StubBus:
    def __init__(self):
        self.torque = True

    def disable_torque(self, motors=None, num_retry=0):
        self.torque = False

    def write_calibration(self, cal):
        pass


class StubFollower:
    """Mimics SO101Follower(use_degrees=True, max_relative_target=cap): clips each goal to present ± cap."""

    def __init__(self, cap=8.0, calibrated=True, follow=1.0):
        self.cap, self.is_calibrated, self.calibration = cap, calibrated, ({"x": 1} if calibrated else {})
        self.pos = {f"{j}.pos": 0.0 for j in ARM_JOINTS}
        self.is_connected, self.bus, self.sent, self.follow = False, StubBus(), 0, follow

    def connect(self, calibrate=True):
        assert calibrate is False  # driver must never block on the interactive prompt
        self.is_connected = True

    def get_observation(self):
        return dict(self.pos)

    def send_action(self, action):
        assert all(isinstance(v, float) for v in action.values())
        for k, v in action.items():
            cur = self.pos[k]
            goal = min(cur + self.cap, max(cur - self.cap, v))  # ensure_safe_goal_position
            self.pos[k] = cur + (goal - cur) * self.follow
        self.sent += 1
        return action

    def disconnect(self):
        self.is_connected = False


def driver(**kw):
    d = So101LeRobotDriver(port="stub", robot_factory=lambda: StubFollower(**kw))
    d.connect()
    return d


def test_unit_conversion_roundtrip_with_joint_map(monkeypatch):
    monkeypatch.setenv("SO101_JOINT_MAP", '{"elbow_flex": {"sign": -1, "offset_deg": 2.5}}')
    d = So101LeRobotDriver(port="stub", robot_factory=StubFollower)
    q = np.array([0.1, -0.2, 0.3, 0.4, -0.5])
    assert np.allclose(d.lerobot_deg_to_model(d.model_to_lerobot_deg(q)), q)
    assert d.model_to_lerobot_deg(q)[2] == pytest.approx(-math.degrees(0.3) + 2.5)


def test_move_reaches_target_through_per_step_clipping():
    d = driver(cap=8.0)
    target = board_to_base(XY(x=100, y=75), NOMINAL_BOARD)
    d.move_to(target, 40.0, 0.5, 8.0)
    p, z = d.read_tool_position()
    assert abs(p.x - target.x) < 3 and abs(p.y - target.y) < 3 and abs(z - 40) < 3
    tr = d.last_trajectory()
    assert tr and tr["bodies"][-1] == "gripperframe" and len(tr["t"]) > 3


def test_servo_that_never_arrives_times_out_not_success():
    d = driver(cap=8.0, follow=0.0)  # torque-less / jammed servo: nothing moves
    with pytest.raises(TimeoutError):
        d.move_to(board_to_base(XY(x=100, y=75), NOMINAL_BOARD), 40.0, 0.5, 2.0)


def test_estop_drops_torque_and_blocks_motion():
    d = driver()
    d.stop()
    assert d.robot.bus.torque is False
    with pytest.raises(RuntimeError, match="e-stop"):
        d.move_to(board_to_base(XY(x=100, y=75), NOMINAL_BOARD), 40.0, 0.5, 8.0)


def test_missing_calibration_fails_fast_with_instructions():
    d = So101LeRobotDriver(port="/dev/tty.usbmodem1", robot_factory=lambda: StubFollower(calibrated=False))
    with pytest.raises(CalibrationMissing, match="lerobot-calibrate"):
        d.connect()


def test_driver_is_physical_and_uses_so101_envelope():
    d = So101LeRobotDriver(port="stub", robot_factory=StubFollower)
    assert d.is_physical and d.envelope.x_max == 280.0
