"""SO-101 physics simulation (MuJoCo) used as the simulated physical world and as the
Level-1 digital twin's executor.

Scene = official SO-101 MJCF (unchanged) + floor + calibration board at a given pose.
Motion = mink IK, then a Ruckig jerk-limited joint trajectory streamed at 50 Hz to the
STS3215 position actuators, with full rigid-body dynamics, then a settle phase. The "true" world can carry servo zero
offsets the controller does not know about, so physical error is not only board pose.
Every move returns the settled tool point and a subsampled trajectory for replay.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import mujoco
import numpy as np

from shared.schemas import XY, CalibrationParameters
from simulation.so101.kinematics import ALL_JOINTS, ARM_JOINTS, MODEL_XML, TOOL_SITE, So101Kinematics
from simulation.so101.collision import So101Collision, check_move
from simulation.so101.motion import CONTROL_DT, plan_joint_trajectory

BOARD_W_MM, BOARD_H_MM, BOARD_T_MM = 200.0, 150.0, 3.0
TRACE_BODIES = ["base", "shoulder", "upper_arm", "lower_arm", "wrist", "gripper"]
SETTLE_S = 0.4
# Nominal board placement (tape-measured): board origin 115 mm ahead, 100 mm left; board x runs right.
NOMINAL_BOARD = CalibrationParameters(offset_mm=XY(x=115.0, y=100.0), rotation_deg=-90.0, scale=1.0, calibration_version="nominal_tape")


class MotionError(Exception):
    pass


@dataclass
class MoveResult:
    tool_mm: np.ndarray            # settled tool point, F_base mm
    q_final: np.ndarray            # 6 joints, rad (true joint angles)
    tracking_err_deg: float        # |q - ctrl| after settle, worst arm joint
    min_tool_z_mm: float           # lowest tool point during the move
    duration_s: float
    trajectory: dict = field(default_factory=dict)


def build_scene(board: CalibrationParameters | None = None) -> mujoco.MjModel:
    spec = mujoco.MjSpec.from_file(str(MODEL_XML))
    wb = spec.worldbody
    floor = wb.add_geom()
    floor.name, floor.type, floor.size = "floor", mujoco.mjtGeom.mjGEOM_PLANE, [0.6, 0.6, 0.01]
    floor.rgba = [0.12, 0.15, 0.16, 1]
    if board is not None:
        th = math.radians(board.rotation_deg)
        cx = board.offset_mm.x + (math.cos(th) * BOARD_W_MM / 2 - math.sin(th) * BOARD_H_MM / 2)
        cy = board.offset_mm.y + (math.sin(th) * BOARD_W_MM / 2 + math.cos(th) * BOARD_H_MM / 2)
        g = wb.add_geom()
        g.name, g.type = "board", mujoco.mjtGeom.mjGEOM_BOX
        g.size = [BOARD_W_MM / 2000, BOARD_H_MM / 2000, BOARD_T_MM / 2000]
        g.pos = [cx / 1000, cy / 1000, BOARD_T_MM / 2000]
        g.quat = [math.cos(th / 2), 0, 0, math.sin(th / 2)]
        g.rgba = [0.92, 0.9, 0.82, 1]
        g.contype = g.conaffinity = 0
    cam = wb.add_camera()
    cam.name, cam.pos = "overhead", [0.19, 0.0, 0.55]
    cam.quat = [0.7071, 0, 0, -0.7071]  # look straight down, image x along -y(base)
    return spec.compile()


class So101Sim:
    def __init__(self, board: CalibrationParameters | None = NOMINAL_BOARD, joint_offsets_deg: dict[str, float] | None = None,
                 ready_q: np.ndarray | None = None) -> None:
        self.m = build_scene(board)
        self.d = mujoco.MjData(self.m)
        self.kin = So101Kinematics()  # controller's nominal model (no knowledge of offsets)
        self.collision: So101Collision | None = None
        self.site = self.m.site(TOOL_SITE).id
        self.qadr = np.array([self.m.joint(j).qposadr[0] for j in ALL_JOINTS])
        self.act = np.array([self.m.actuator(j).id for j in ALL_JOINTS])
        self.bodies = [self.m.body(b).id for b in TRACE_BODIES]
        self.offsets = np.array([math.radians((joint_offsets_deg or {}).get(j, 0.0)) for j in ALL_JOINTS])
        q0 = np.zeros(6)
        q0[:5] = ready_q if ready_q is not None else np.array([0.0, -0.9, 0.9, 1.3, 0.0])
        self.d.qpos[self.qadr] = q0 + self.offsets
        self.d.ctrl[self.act] = q0 + self.offsets
        self.cmd = q0.copy()  # what the controller believes it commanded
        mujoco.mj_forward(self.m, self.d)
        self._settle(0.5)

    # ------------------------------------------------------------------ state
    def tool_mm(self) -> np.ndarray:
        return self.d.site_xpos[self.site] * 1000.0

    def joints(self) -> np.ndarray:
        """Joint angles as the controller reads them (encoder = true angle - offset)."""
        return self.d.qpos[self.qadr] - self.offsets

    # ------------------------------------------------------------------ motion
    def plan(self, base_mm: XY, height_mm: float, speed_fraction: float = 0.3) -> np.ndarray:
        """mink IK + Ruckig path + Menagerie clearance check, from the current commanded pose."""
        if self.collision is None:
            self.collision = So101Collision()
        ok, why, q = check_move(self.kin, self.collision, self.cmd[:5], np.array([base_mm.x, base_mm.y, height_mm]) / 1000.0, speed_fraction)
        if not ok:
            raise MotionError(why if why.startswith("planned path") else f"unreachable: {why}")
        return q

    def move_to(self, base_mm: XY, height_mm: float, speed_fraction: float = 0.3, record_every_s: float = 0.04,
                min_clearance_mm: float = 8.0) -> MoveResult:
        """IK (mink) -> jerk-limited joint trajectory (Ruckig) streamed at 50 Hz to the position
        actuators -> full dynamics stepping -> settle. Same waypoint stream as the real arm."""
        q_goal = np.concatenate([self.plan(base_mm, height_mm, speed_fraction), self.cmd[5:]])
        times, wps = plan_joint_trajectory(self.cmd[:5], q_goal[:5], speed_fraction, CONTROL_DT)
        dt = self.m.opt.timestep
        sub = max(1, int(round(CONTROL_DT / dt)))
        rec_every = max(1, int(round(record_every_s / CONTROL_DT)))
        frames, min_z, t = [], float("inf"), 0.0
        settle_wps = int(SETTLE_S / CONTROL_DT)
        for k in range(len(wps) + settle_wps):
            if k < len(wps):
                self.cmd = np.concatenate([wps[k], self.cmd[5:]])
            self.d.ctrl[self.act] = self.cmd + self.offsets  # servo zero error lives here
            for _ in range(sub):
                mujoco.mj_step(self.m, self.d)
                min_z = min(min_z, self.d.site_xpos[self.site][2] * 1000)
            t += CONTROL_DT
            if k % rec_every == 0:
                frames.append(self._frame(t))
        frames.append(self._frame(t))
        track = float(np.degrees(np.abs(self.d.qpos[self.qadr] - self.d.ctrl[self.act])[:5].max()))
        if min_z < min_clearance_mm:
            raise MotionError(f"tool came within {min_z:.1f} mm of the table")
        return MoveResult(self.tool_mm(), self.d.qpos[self.qadr].copy(), track, min_z, t,
                          {"t": [f[0] for f in frames], "bodies": TRACE_BODIES + [TOOL_SITE], "pos_mm": [f[1] for f in frames],
                           "joints": ALL_JOINTS, "q_rad": [f[2] for f in frames], "dt_s": record_every_s,
                           "q_frame": "true joint angles (physics state, includes servo offsets)",
                           "planner": "mink IK + Ruckig jerk-limited trajectory, 50 Hz"})

    def _frame(self, t: float):
        pts = [self.d.xpos[b] * 1000 for b in self.bodies] + [self.d.site_xpos[self.site] * 1000]
        # Record the TRUE joint angles (what the physics did), so a URDF replay shows the real pose.
        return round(t, 3), [[round(float(v), 1) for v in p] for p in pts], [round(float(v), 4) for v in self.d.qpos[self.qadr]]

    def _settle(self, seconds: float) -> None:
        for _ in range(int(seconds / self.m.opt.timestep)):
            mujoco.mj_step(self.m, self.d)
