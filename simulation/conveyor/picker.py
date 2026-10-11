"""Vision-driven pick-and-place policy for the conveyor cell (stop-and-pick).

Loop: watch the belt camera; when a red square reaches the pick line, stop the line, re-detect
with a clear view, then grasp it (mink IK with the jaws aligned to the cube faces, Ruckig
trajectories at 50 Hz) and drop it in the collection bin. Blue circles ride past.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import mink
import mujoco
import numpy as np

from simulation.conveyor.cell import ConveyorCell
from simulation.conveyor.scene import BELT_TOP, BIN_CENTER, CUBE_HALF
from simulation.conveyor.vision import BeltCamera, Detection
from simulation.so101.collision import MENAGERIE_XML
from simulation.so101.kinematics import So101Kinematics
from simulation.so101.motion import plan_joint_trajectory

GRIPPER_OPEN, GRIPPER_CLOSED = 0.55, -0.12
JAW_OFFSET = 0.003      # measured: fixed finger inner face at -7.3 mm (body x), TCP at +12; cube centre at +9 leaves 4 mm clearance
HOVER_Z = 0.080
GRASP_Z = BELT_TOP + CUBE_HALF + 0.002
DROP = np.array([BIN_CENTER[0], BIN_CENTER[1], 0.09])


@dataclass
class PickerParams:
    pick_trigger_y: float = 0.03   # stop the line when a red square is at or past this y
    pick_min_y: float = -0.07      # beyond this the part is out of the reliable pick window
    speed: float = 0.6             # Ruckig speed fraction for arm moves
    settle_s: float = 0.25         # wait after stopping the belt before re-detecting
    grip_s: float = 0.35           # time to close/open the gripper


@dataclass
class PickStats:
    attempts: int = 0
    grasped: int = 0
    events: list[str] = field(default_factory=list)


class Picker:
    def __init__(self, cell: ConveyorCell, params: PickerParams = PickerParams(), on_frame: Callable[[], None] | None = None) -> None:
        self.cell, self.p = cell, params
        self.cam = BeltCamera(cell.m, cell.d)
        self.kin = So101Kinematics(mujoco.MjModel.from_xml_path(str(MENAGERIE_XML)))
        self.jaw_task = mink.AxisAlignTask("gripperframe", "site", axis=(0.0, 0.0, 1.0), cost=0.5, lm_damping=1e-3)
        self.stats = PickStats()
        self.on_frame = on_frame or (lambda: None)
        self.last_dets: list[Detection] = []
        self.target: Detection | None = None
        self.gripper = GRIPPER_OPEN
        self.home = self._ik(DROP, None)
        cell.set_arm(np.concatenate([self.home, [self.gripper]]), snap=True)

    # ------------------------------------------------------------------ IK helpers
    def _ik(self, target: np.ndarray, jaw_dir: np.ndarray | None, q0: np.ndarray | None = None):
        self.kin.extra_tasks = []
        if jaw_dir is not None:
            self.jaw_task.set_target(np.array([jaw_dir[0], jaw_dir[1], 0.0]))
            self.kin.extra_tasks = [self.jaw_task]
        r = self.kin.ik(np.asarray(target, float), q0=q0)
        self.kin.extra_tasks = []
        if not r.ok:
            raise RuntimeError(f"IK failed for {np.round(target, 3)} (err {r.pos_err_mm:.1f} mm, tilt {r.tilt_deg:.1f} deg)")
        return r.q

    def _grasp_plan(self, det: Detection):
        """Try the 4 jaw directions that square up with the cube; keep the one needing least motion."""
        q_now = self.cell.arm_q()[:5]
        best = None
        for k in range(4):
            a = det.yaw + k * math.pi / 2
            jaw = np.array([math.cos(a), math.sin(a)])
            centre = np.array([det.xy[0], det.xy[1]])
            tcp = centre + JAW_OFFSET * jaw
            try:
                q_hover = self._ik(np.array([tcp[0], tcp[1], HOVER_Z]), jaw, q0=q_now)
                q_grasp = self._ik(np.array([tcp[0], tcp[1], GRASP_Z]), jaw, q0=q_hover)
            except RuntimeError:
                continue
            cost = float(np.abs(q_hover - q_now).sum())
            if best is None or cost < best[0]:
                best = (cost, q_hover, q_grasp)
        if best is None:
            raise RuntimeError("no jaw orientation reachable")
        return best[1], best[2]

    # ------------------------------------------------------------------ motion primitives
    def _move(self, q_goal: np.ndarray) -> None:
        _, wps = plan_joint_trajectory(self.cell.arm_q()[:5], q_goal, self.p.speed)
        for wp in wps:
            self.cell.set_arm(np.concatenate([wp, [self.gripper]]))
            self.cell.step(1)
            self.on_frame()
        self._wait(0.08)

    def _grip(self, value: float) -> None:
        self.gripper = value
        self.cell.set_arm(np.concatenate([self.cell.d.ctrl[self.cell.arm_act][:5], [value]]))
        self._wait(self.p.grip_s)

    def _wait(self, seconds: float) -> None:
        for _ in range(max(1, int(seconds / 0.02))):
            self.cell.step(1)
            self.on_frame()

    # ------------------------------------------------------------------ perception
    def look(self) -> list[Detection]:
        self.last_dets = self.cam.detect(self.cam.rgb(), BELT_TOP + 2 * CUBE_HALF)
        return self.last_dets

    def _candidates(self) -> list[Detection]:
        return sorted([d for d in self.last_dets if d.kind == "red_square" and self.p.pick_min_y <= d.xy[1] <= self.p.pick_trigger_y],
                      key=lambda d: d.xy[1])

    # ------------------------------------------------------------------ one pick
    def pick(self, det: Detection) -> bool:
        self.stats.attempts += 1
        self.target = det
        q_hover, q_grasp = self._grasp_plan(det)
        self._grip(GRIPPER_OPEN)
        self._move(q_hover)
        self._move(q_grasp)
        self._grip(GRIPPER_CLOSED)
        self._move(q_hover)
        held = self._holding()
        self._move(self.home)
        self._grip(GRIPPER_OPEN)
        self.target = None
        if held:
            self.stats.grasped += 1
        self.stats.events.append(f"t={self.cell.t:.1f}s pick at ({det.xy[0]*1000:.0f},{det.xy[1]*1000:.0f}) mm: {'held' if held else 'slipped'}")
        return held

    def _holding(self) -> bool:
        tcp = self.cell.d.site_xpos[self.cell.m.site("gripperframe").id]
        for i, st in enumerate(self.cell.state):
            if st == "belt" and self.cell.kinds[i] == "red_square":
                p = self.cell.obj_pos(i)
                if p[2] > BELT_TOP + CUBE_HALF + 0.02 and np.linalg.norm(p[:2] - tcp[:2]) < 0.03:
                    return True
        return False

    # ------------------------------------------------------------------ episode
    def run(self, duration_s: float = 60.0, look_every_s: float = 0.1) -> None:
        look_n = max(1, int(look_every_s / 0.02))
        k = 0
        while self.cell.t < duration_s:
            if k % look_n == 0 and self.look() and self._candidates():
                self.cell.set_belt(False)
                self._wait(self.p.settle_s)
                while self.cell.t < duration_s:
                    self.look()
                    cands = self._candidates()
                    if not cands:
                        break
                    try:
                        self.pick(cands[0])
                    except RuntimeError as e:
                        self.stats.events.append(f"t={self.cell.t:.1f}s skipped: {e}")
                        break
                self.cell.set_belt(True)
            self.cell.step(1)
            self.on_frame()
            k += 1
