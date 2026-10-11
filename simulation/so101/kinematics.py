"""SO-101 forward/inverse kinematics on the official MJCF (TheRobotStudio, Apache-2.0).

IK is delegated to **mink** (differential IK as a QP over MuJoCo models, Apache-2.0):
- ``FrameTask`` on the ``gripperframe`` site, position only;
- ``AxisAlignTask`` pointing the site's local +X (the gripper's pointing axis) at world -Z,
  which constrains pointing but leaves wrist roll free — the right task for a 5-DOF arm;
- ``PostureTask`` (small cost) to stay near the seed, so consecutive solutions are continuous;
- ``ConfigurationLimit`` so every solution respects the model's joint ranges.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import mink
import mujoco
import numpy as np

MODEL_XML = Path(__file__).resolve().parent / "model" / "so101_new_calib.xml"
ARM_JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
ALL_JOINTS = ARM_JOINTS + ["gripper"]
TOOL_SITE = "gripperframe"
DOWN = np.array([0.0, 0.0, -1.0])

# Fallback seeds (rad) if the solve from the current pose does not converge.
SEEDS = [
    np.array([0.0, -0.9, 0.9, 1.3, 0.0]),
    np.array([0.0, -0.3, 0.6, 1.2, 0.0]),
    np.array([0.0, 0.3, 0.2, 1.3, 0.0]),
]


@dataclass
class IKResult:
    q: np.ndarray  # 5 arm joints, rad
    pos_err_mm: float
    tilt_deg: float  # angle between tool axis and straight down
    ok: bool
    iterations: int


class So101Kinematics:
    def __init__(self, model: mujoco.MjModel | None = None) -> None:
        self.m = model or mujoco.MjModel.from_xml_path(str(MODEL_XML))
        self.cfg = mink.Configuration(self.m)
        self.d = self.cfg.data
        self.site = self.m.site(TOOL_SITE).id
        self.qadr = np.array([self.m.joint(j).qposadr[0] for j in ARM_JOINTS])
        ids = [self.m.joint(j).id for j in ARM_JOINTS]
        self.lo, self.hi = self.m.jnt_range[ids, 0], self.m.jnt_range[ids, 1]
        self.pos_task = mink.FrameTask(TOOL_SITE, "site", position_cost=1.0, orientation_cost=0.0, lm_damping=1e-3)
        self.down_task = mink.AxisAlignTask(TOOL_SITE, "site", axis=(1.0, 0.0, 0.0), cost=1.0, lm_damping=1e-3)
        self.down_task.set_target(DOWN)
        self.posture = mink.PostureTask(self.m, cost=1e-3)
        self.limits = [mink.ConfigurationLimit(self.m)]

    def fk(self, q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Tool point (m) and tool axis (unit vector) in F_base for arm joints ``q``."""
        self.d.qpos[self.qadr] = q
        mujoco.mj_kinematics(self.m, self.d)
        return self.d.site_xpos[self.site].copy(), self.d.site_xmat[self.site].reshape(3, 3)[:, 0].copy()

    def _solve_from(self, target_m: np.ndarray, seed: np.ndarray, iters: int, tol_mm: float, tilt_tol_deg: float) -> IKResult:
        q_full = np.zeros(self.m.nq)
        q_full[self.qadr] = np.clip(seed, self.lo, self.hi)
        self.cfg.update(q_full)
        self.posture.set_target(q_full)
        self.pos_task.set_target(mink.SE3.from_translation(target_m))
        tasks = [self.pos_task, self.down_task, self.posture]
        it = 0
        for it in range(1, iters + 1):
            v = mink.solve_ik(self.cfg, tasks, 0.02, "daqp", damping=1e-3, limits=self.limits)
            self.cfg.integrate_inplace(v, 0.02)
            p = self.cfg.data.site_xpos[self.site]
            a = self.cfg.data.site_xmat[self.site].reshape(3, 3)[:, 0]
            if np.linalg.norm(target_m - p) * 1000 < tol_mm and np.degrees(np.arccos(np.clip(a @ DOWN, -1, 1))) < tilt_tol_deg:
                break
        q = self.cfg.q[self.qadr].copy()
        p, a = self.fk(q)
        err = float(np.linalg.norm(target_m - p) * 1000)
        tilt = float(np.degrees(np.arccos(np.clip(a @ DOWN, -1, 1))))
        return IKResult(q=q, pos_err_mm=err, tilt_deg=tilt, ok=err < 1.0 and tilt < 2.0, iterations=it)

    def ik(self, target_m: np.ndarray, q0: np.ndarray | None = None, tol_mm: float = 0.1, max_tilt_deg: float = 0.5,
           iters: int = 300) -> IKResult:
        best: IKResult | None = None
        for seed in ([q0] if q0 is not None else []) + SEEDS:
            r = self._solve_from(np.asarray(target_m, dtype=float), np.asarray(seed, dtype=float), iters, tol_mm, max_tilt_deg)
            if r.ok:
                return r
            if best is None or r.pos_err_mm + r.tilt_deg < best.pos_err_mm + best.tilt_deg:
                best = r
        return best  # type: ignore[return-value]
