"""Path clearance for the SO-101 using MuJoCo Menagerie's collision geometry (Apache-2.0).

The Menagerie ``robotstudio_so101`` model has the same link kinematics as the official
``so101_new_calib`` model plus simple box/sphere collision shapes, so distance queries are
cheap and exact for the shapes. The environment is the table top at the board's surface
height: the board lies flat on the table, so this check needs no knowledge of the board pose.
Distances come from ``mujoco.mj_geomDistance``; nothing here is hand-made geometry.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import mujoco
import numpy as np

from simulation.so101.kinematics import ARM_JOINTS

MENAGERIE_XML = Path(__file__).resolve().parent / "model" / "menagerie_so101.xml"
COLLISION_GROUP = 3            # Menagerie: primitive collision geoms (group 4 = gripper meshes, skipped)
IGNORE_BODIES = {"base", "shoulder"}  # bolted to the table / never near it
DEFAULT_MARGIN_MM = 5.0


@dataclass
class Clearance:
    min_mm: float
    body: str
    waypoint: int


class So101Collision:
    def __init__(self, surface_z_mm: float = 3.0) -> None:
        spec = mujoco.MjSpec.from_file(str(MENAGERIE_XML))
        table = spec.worldbody.add_geom()
        table.name, table.type = "table_surface", mujoco.mjtGeom.mjGEOM_PLANE
        table.size, table.pos = [1.0, 1.0, 0.01], [0.0, 0.0, surface_z_mm / 1000.0]
        table.group, table.contype, table.conaffinity = COLLISION_GROUP, 1, 1
        self.m = spec.compile()
        self.d = mujoco.MjData(self.m)
        self.table = self.m.geom("table_surface").id
        self.qadr = np.array([self.m.joint(j).qposadr[0] for j in ARM_JOINTS])
        self.robot_geoms = [
            g for g in range(self.m.ngeom)
            if g != self.table and self.m.geom_group[g] == COLLISION_GROUP
            and self.m.body(self.m.geom_bodyid[g]).name not in IGNORE_BODIES
        ]

    def pose_clearance(self, q: np.ndarray, gripper: float = 0.0) -> tuple[float, str]:
        self.d.qpos[self.qadr] = q
        self.d.qpos[self.m.joint("gripper").qposadr[0]] = gripper
        mujoco.mj_kinematics(self.m, self.d)
        best, who = float("inf"), ""
        for g in self.robot_geoms:
            dist = mujoco.mj_geomDistance(self.m, self.d, g, self.table, 0.2, None)
            if dist < best:
                best, who = dist, self.m.body(self.m.geom_bodyid[g]).name
        return best * 1000.0, who

    def path_clearance(self, waypoints: np.ndarray, gripper: float = 0.0, stride: int = 2) -> Clearance:
        worst = Clearance(float("inf"), "", -1)
        idx = list(range(0, len(waypoints), max(1, stride)))
        if idx[-1] != len(waypoints) - 1:
            idx.append(len(waypoints) - 1)
        for i in idx:
            d, who = self.pose_clearance(waypoints[i], gripper)
            if d < worst.min_mm:
                worst = Clearance(d, who, i)
        return worst


def check_move(kin, collision: So101Collision, q_start: np.ndarray, target_m: np.ndarray, speed_fraction: float,
               margin_mm: float = DEFAULT_MARGIN_MM) -> tuple[bool, str, np.ndarray | None]:
    """IK (mink) + trajectory (Ruckig) + clearance (Menagerie geoms). Returns (ok, reason, q_goal)."""
    from simulation.so101.motion import plan_joint_trajectory

    r = kin.ik(target_m, q0=q_start)
    if not r.ok:
        return False, f"IK residual {r.pos_err_mm:.1f} mm, tilt {r.tilt_deg:.1f} deg", None
    _, wps = plan_joint_trajectory(q_start, r.q, speed_fraction)
    c = collision.path_clearance(np.vstack([q_start, wps]))
    if c.min_mm < margin_mm:
        return False, f"planned path brings {c.body} within {c.min_mm:.1f} mm of the table (margin {margin_mm} mm)", None
    return True, "", r.q
