"""Physical SO-101 driver over LeRobot (``pip install 'lerobot[feetech]'``, Python >= 3.12).

Verified against lerobot main @ b9cb121 / PyPI 0.6.1:
- ``from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig``
- ``use_degrees=True``: arm joints in degrees, 0 = middle of the calibrated range, which is the
  convention of SO-ARM100's ``so101_new_calib`` MJCF/URDF (no documented per-joint sign flips).
- keys ``"<motor>.pos"``; gripper is 0..100 (not degrees) and is left untouched here.
- ``max_relative_target`` clips each goal to present ± cap (must be a float); we stream Ruckig
  jerk-limited waypoints at 50 Hz (LeRobot itself does no smoothing), so the clip never truncates a move.
- torque is ON after ``connect()``; ``bus.disable_torque()`` is our software e-stop. The
  hardware power cutoff stays the primary emergency stop.

Configuration (env): SO101_PORT (required, find with ``lerobot-find-port``), SO101_ID,
SO101_CALIBRATION_DIR, SO101_MAX_STEP_DEG (default 8.0), and SO101_JOINT_MAP — JSON
``{"joint": {"sign": 1, "offset_deg": 0}}`` to correct any convention mismatch found with
``scripts/so101_bringup.py``. Calibrate first: ``lerobot-calibrate --robot.type=so101_follower ...``.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from typing import Any, Optional

import numpy as np

from robot_gateway.driver import ArmDriver
from robot_gateway.safety import SO101_ENVELOPE
from shared.schemas import XY
from simulation.so101.kinematics import ARM_JOINTS, So101Kinematics
from simulation.so101.motion import CONTROL_DT, plan_joint_trajectory

ARRIVE_TOL_DEG = 1.5


class CalibrationMissing(RuntimeError):
    pass


class So101LeRobotDriver(ArmDriver):
    name = "so101"
    is_physical = True
    envelope = SO101_ENVELOPE

    def __init__(self, port: str | None = None, robot_id: str | None = None, robot_factory=None) -> None:
        self.port = port or os.environ.get("SO101_PORT", "")
        self.robot_id = robot_id or os.environ.get("SO101_ID", "autolab_follower")
        self.max_step = float(os.environ.get("SO101_MAX_STEP_DEG", "8.0"))
        jm = json.loads(os.environ.get("SO101_JOINT_MAP", "{}") or "{}")
        self.sign = np.array([float(jm.get(j, {}).get("sign", 1)) for j in ARM_JOINTS])
        self.offset = np.array([float(jm.get(j, {}).get("offset_deg", 0.0)) for j in ARM_JOINTS])
        self._factory = robot_factory  # injected in tests
        self.robot: Any = None
        self.kin = So101Kinematics()
        self._lock = threading.RLock()  # lerobot's bus has no lock; serialize serial-port access
        self._estop = threading.Event()
        self._collision = None
        self._traj: Optional[dict] = None
        self.commands_executed = 0

    # ------------------------------------------------------------------ unit conversion
    def model_to_lerobot_deg(self, q_rad: np.ndarray) -> np.ndarray:
        return self.sign * np.degrees(q_rad) + self.offset

    def lerobot_deg_to_model(self, deg: np.ndarray) -> np.ndarray:
        return np.radians((deg - self.offset) * self.sign)

    # ------------------------------------------------------------------ lifecycle
    def connect(self) -> None:
        if not self.port and self._factory is None:
            raise RuntimeError("SO101_PORT is not set (find it with `lerobot-find-port`)")
        if self._factory is not None:
            self.robot = self._factory()
        else:
            from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

            kw: dict[str, Any] = {"port": self.port, "id": self.robot_id, "use_degrees": True, "max_relative_target": float(self.max_step)}
            if os.environ.get("SO101_CALIBRATION_DIR"):
                from pathlib import Path

                kw["calibration_dir"] = Path(os.environ["SO101_CALIBRATION_DIR"])
            self.robot = SO101Follower(SO101FollowerConfig(**kw))
        with self._lock:
            self.robot.connect(calibrate=False)  # never block a service on lerobot's interactive prompt
            if not getattr(self.robot, "is_calibrated", True):
                cal = getattr(self.robot, "calibration", None)
                if not cal:
                    self.robot.disconnect()
                    raise CalibrationMissing(
                        f"No LeRobot calibration for id '{self.robot_id}'. Run: lerobot-calibrate --robot.type=so101_follower "
                        f"--robot.port={self.port} --robot.id={self.robot_id}")
                self.robot.bus.write_calibration(cal)  # file exists but motor registers differ
        self._estop.clear()

    def is_connected(self) -> bool:
        return bool(self.robot is not None and getattr(self.robot, "is_connected", False))

    # ------------------------------------------------------------------ state
    def _read_deg(self) -> np.ndarray:
        with self._lock:
            obs = self.robot.get_observation()
        return np.array([float(obs[f"{j}.pos"]) for j in ARM_JOINTS])

    def read_joints(self) -> Optional[list[float]]:
        return [float(v) for v in np.degrees(self.lerobot_deg_to_model(self._read_deg()))] if self.is_connected() else None

    def read_tool_position(self) -> tuple[XY, float]:
        """Forward kinematics of the *measured* encoder angles (proprioception, not the camera)."""
        p, _ = self.kin.fk(self.lerobot_deg_to_model(self._read_deg()))
        return XY(x=float(p[0] * 1000), y=float(p[1] * 1000)), float(p[2] * 1000)

    def can_reach(self, base_mm: XY, height_mm: float) -> tuple[bool, str]:
        """Pre-motion gate from the live encoder pose: mink IK + Ruckig path + Menagerie clearance."""
        from simulation.so101.collision import So101Collision, check_move

        if self._collision is None:
            self._collision = So101Collision()
        q0 = self.lerobot_deg_to_model(self._read_deg())
        ok, why, _ = check_move(self.kin, self._collision, q0, np.array([base_mm.x, base_mm.y, height_mm]) / 1000.0, 0.3)
        return ok, why

    # ------------------------------------------------------------------ motion
    def move_to(self, base_mm: XY, height_mm: float, speed_fraction: float, timeout_s: float) -> None:
        if not self.is_connected():
            raise RuntimeError("driver not connected")
        if self._estop.is_set():
            raise RuntimeError("software e-stop engaged")
        start_deg = self._read_deg()
        q0 = self.lerobot_deg_to_model(start_deg)
        r = self.kin.ik(np.array([base_mm.x, base_mm.y, height_mm]) / 1000.0, q0=q0)
        if not r.ok:
            raise RuntimeError(f"unreachable: IK residual {r.pos_err_mm:.1f} mm")
        goal_deg = self.model_to_lerobot_deg(r.q)
        # Jerk-limited, time-synchronized waypoints from Ruckig (same planner as the simulator).
        times, wps = plan_joint_trajectory(q0, r.q, speed_fraction, CONTROL_DT)
        if times[-1] > timeout_s:
            raise TimeoutError(f"planned move {times[-1]:.1f}s exceeds timeout {timeout_s}s")
        frames: list = []
        t0 = time.monotonic()
        for i, wp in enumerate(wps, start=1):
            if self._estop.is_set():
                raise RuntimeError("software e-stop engaged during motion")
            wp_deg = self.model_to_lerobot_deg(wp)
            with self._lock:
                self.robot.send_action({f"{j}.pos": float(v) for j, v in zip(ARM_JOINTS, wp_deg)})
            if i % 2 == 0:
                frames.append(self._frame(time.monotonic() - t0))
            time.sleep(max(0.0, t0 + i * CONTROL_DT - time.monotonic()))
        while True:  # settle: wait for the servos to arrive, never assume success
            cur = self._read_deg()
            if float(np.abs(cur - goal_deg).max()) <= ARRIVE_TOL_DEG:
                break
            if time.monotonic() - t0 > timeout_s:
                raise TimeoutError(f"servos did not arrive within {timeout_s}s (worst joint {np.abs(cur - goal_deg).max():.1f} deg off)")
            time.sleep(0.02)
        frames.append(self._frame(time.monotonic() - t0))
        self._traj = {"t": [f[0] for f in frames], "bodies": ["base", "shoulder", "upper_arm", "lower_arm", "wrist", "gripper", "gripperframe"],
                      "pos_mm": [f[1] for f in frames], "joints": ARM_JOINTS, "q_rad": [f[2] for f in frames], "dt_s": 2 * CONTROL_DT,
                      "source": "encoder telemetry replayed through the SO-101 model"}
        self.commands_executed += 1

    def _frame(self, t: float):
        q = self.lerobot_deg_to_model(self._read_deg())
        self.kin.fk(q)
        d, m = self.kin.d, self.kin.m
        pts = [d.xpos[m.body(b).id] * 1000 for b in ["base", "shoulder", "upper_arm", "lower_arm", "wrist", "gripper"]] + [d.site_xpos[self.kin.site] * 1000]
        return round(t, 3), [[round(float(v), 1) for v in p] for p in pts], [round(float(v), 4) for v in q]

    def last_trajectory(self) -> Optional[dict]:
        t, self._traj = self._traj, None
        return t

    def stop(self) -> None:
        """Software e-stop: abort streaming and drop torque. Physical cutoff remains primary."""
        self._estop.set()
        if self.robot is not None:
            with self._lock:
                self.robot.bus.disable_torque(num_retry=5)

    def home(self) -> None:
        self.move_to(XY(x=170.0, y=0.0), 80.0, 0.2, 8.0)

    def disconnect(self) -> None:
        if self.robot is not None:
            with self._lock:
                self.robot.disconnect()
