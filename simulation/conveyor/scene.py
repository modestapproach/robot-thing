"""SO-101 conveyor pick-and-sort cell, built on MuJoCo.

- Robot: MuJoCo Menagerie ``robotstudio_so101`` (Apache-2.0; same kinematics as TheRobotStudio's
  official model, plus primitive collision shapes and high-friction jaw pads for real grasps).
- Conveyor: a row of rollers on hinge joints driven by velocity actuators. Objects ride on the
  rollers by friction (no teleporting), and stopping the rollers stops the line.
- Bucket feeder at the upstream end; collection bin beside the belt; objects that reach the end
  fall off into the catch zone.
- ``belt_cam``: fixed overhead camera over the belt (image right = +y, image up = -x).

World frame = robot base frame, metres, z up. The belt runs from +y (bucket) to -y.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import mujoco
import numpy as np

from simulation.so101.collision import MENAGERIE_XML

BELT_X = 0.21            # belt centreline
BELT_HALF_W = 0.05       # belt half-width (x)
BELT_Y0, BELT_Y1 = 0.26, -0.26   # upstream (bucket) -> downstream (end)
ROLLER_R = 0.0055        # rollers much closer than the smallest item, so a cube always rests on >= 2
ROLLER_Z = 0.0165        # roller axle height -> belt top 22 mm (the SO-101 can only point straight down up to ~85 mm)
BELT_TOP = ROLLER_Z + ROLLER_R
ROLLER_PITCH = 0.012
CUBE_HALF = 0.012        # red square: 24 mm cube
DISC_R, DISC_HALF_H = 0.012, 0.006  # blue circle: 24 mm disc, 12 mm tall
BIN_CENTER = np.array([0.10, 0.17])
BIN_HALF = 0.035
BIN_WALL_H = 0.04
DISPENSE_Y = 0.235
PARK_X = -3.0   # well outside every camera view


@dataclass
class CellLayout:
    n_objects: int = 24
    seed: int = 0
    red_fraction: float = 0.55


def _quat_axis_angle(axis, angle):
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    return [math.cos(angle / 2), *(axis * math.sin(angle / 2))]


def build_cell(layout: CellLayout = CellLayout(), offscreen=(960, 540)) -> tuple[mujoco.MjModel, list[str]]:
    """Returns the compiled model and the object kinds in pool order ("red_square" | "blue_circle")."""
    spec = mujoco.MjSpec.from_file(str(MENAGERIE_XML))
    spec.visual.global_.offwidth, spec.visual.global_.offheight = offscreen
    spec.option.timestep = 0.002
    spec.option.noslip_iterations = 3  # steadier grasps
    spec.option.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST  # stable with velocity-servoed rollers
    wb = spec.worldbody
    wb.add_light(pos=[0.15, -0.2, 1.0], dir=[0, 0.2, -1], diffuse=[0.75, 0.75, 0.75], castshadow=True)
    wb.add_light(pos=[-0.3, 0.3, 0.8], dir=[0.3, -0.3, -1], diffuse=[0.35, 0.35, 0.35], castshadow=False)
    wb.add_geom(name="table", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[1.2, 1.2, 0.01], rgba=[0.13, 0.15, 0.16, 1], friction=[1, 0.005, 0.0001])

    # --- conveyor frame (side rails double as low guards) ---------------------------------------
    length = BELT_Y0 - BELT_Y1
    yc = (BELT_Y0 + BELT_Y1) / 2
    for side in (-1, 1):
        wb.add_geom(name=f"rail_{'n' if side < 0 else 'f'}", type=mujoco.mjtGeom.mjGEOM_BOX,
                    size=[0.004, length / 2, 0.016], pos=[BELT_X + side * (BELT_HALF_W + 0.006), yc, 0.016],
                    rgba=[0.35, 0.38, 0.4, 1])
    for k, y in enumerate([BELT_Y0 - 0.01, BELT_Y1 + 0.01]):
        for side in (-1, 1):
            wb.add_geom(type=mujoco.mjtGeom.mjGEOM_BOX, size=[0.004, 0.004, 0.012], pos=[BELT_X + side * 0.06, y, 0.012],
                        rgba=[0.25, 0.27, 0.29, 1], contype=0, conaffinity=0)
    # --- rollers --------------------------------------------------------------------------------
    n_rollers = int(length / ROLLER_PITCH)
    for i in range(n_rollers):
        y = BELT_Y0 - ROLLER_PITCH / 2 - i * ROLLER_PITCH
        b = wb.add_body(name=f"roller{i}", pos=[BELT_X, y, ROLLER_Z])
        # armature = reflected motor/gearbox inertia; without it the tiny roller inertia makes the servo unstable
        b.add_joint(name=f"roller{i}", type=mujoco.mjtJoint.mjJNT_HINGE, axis=[1, 0, 0], damping=0.0005, armature=0.002)
        # capsule rollers: MuJoCo has a dedicated, stable box-capsule collider (box-cylinder goes through MPR and stalls)
        b.add_geom(type=mujoco.mjtGeom.mjGEOM_CAPSULE, size=[ROLLER_R, BELT_HALF_W - ROLLER_R, 0], quat=_quat_axis_angle([0, 1, 0], math.pi / 2),
                   rgba=[0.55, 0.57, 0.6, 1] if i % 2 else [0.48, 0.5, 0.53, 1], mass=0.03, friction=[1.2, 0.005, 0.0001])
        spec.add_actuator(name=f"roller{i}", target=f"roller{i}", trntype=mujoco.mjtTrn.mjTRN_JOINT,
                          gaintype=mujoco.mjtGain.mjGAIN_FIXED, biastype=mujoco.mjtBias.mjBIAS_AFFINE,
                          gainprm=[0.02] + [0] * 9, biasprm=[0, 0, -0.02] + [0] * 7, forcerange=[-0.15, 0.15], forcelimited=True)

    # --- bucket feeder (visual hopper over the belt start) --------------------------------------
    hx, hy, top, bot = 0.045, 0.035, 0.15, 0.065
    for dx, dy, sx, sy in [(-hx, 0, 0.003, hy), (hx, 0, 0.003, hy), (0, -hy, hx, 0.003), (0, hy, hx, 0.003)]:
        wb.add_geom(type=mujoco.mjtGeom.mjGEOM_BOX, size=[sx, sy, (top - bot) / 2], pos=[BELT_X + dx, DISPENSE_Y + 0.01 + dy, (top + bot) / 2],
                    rgba=[0.86, 0.62, 0.18, 0.55], contype=0, conaffinity=0)
    # --- collection bin -------------------------------------------------------------------------
    cx, cy = BIN_CENTER
    wb.add_geom(name="bin_floor", type=mujoco.mjtGeom.mjGEOM_BOX, size=[BIN_HALF, BIN_HALF, 0.002], pos=[cx, cy, 0.002], rgba=[0.2, 0.42, 0.33, 1])
    for dx, dy, sx, sy in [(-BIN_HALF, 0, 0.002, BIN_HALF), (BIN_HALF, 0, 0.002, BIN_HALF), (0, -BIN_HALF, BIN_HALF, 0.002), (0, BIN_HALF, BIN_HALF, 0.002)]:
        wb.add_geom(type=mujoco.mjtGeom.mjGEOM_BOX, size=[sx, sy, BIN_WALL_H / 2], pos=[cx + dx, cy + dy, BIN_WALL_H / 2], rgba=[0.3, 0.6, 0.47, 1])

    # --- cameras --------------------------------------------------------------------------------
    wb.add_camera(name="belt_cam", pos=[BELT_X, 0.07, 0.40], quat=_quat_axis_angle([0, 0, 1], math.pi / 2), fovy=45)

    # --- object pool (parked off the table, dispensed from the bucket) ---------------------------
    rng = np.random.default_rng(layout.seed)
    kinds = ["red_square" if rng.random() < layout.red_fraction else "blue_circle" for _ in range(layout.n_objects)]
    for i, kind in enumerate(kinds):
        b = wb.add_body(name=f"obj{i}", pos=[PARK_X, -0.4 + 0.04 * i, 0.03])
        b.add_freejoint(name=f"obj{i}")
        if kind == "red_square":
            b.add_geom(name=f"obj{i}", type=mujoco.mjtGeom.mjGEOM_BOX, size=[CUBE_HALF] * 3, rgba=[0.86, 0.12, 0.12, 1],
                       mass=0.008, friction=[1.0, 0.005, 0.0001], condim=4)
        else:
            b.add_geom(name=f"obj{i}", type=mujoco.mjtGeom.mjGEOM_CYLINDER, size=[DISC_R, DISC_HALF_H, 0], rgba=[0.12, 0.3, 0.9, 1],
                       mass=0.006, friction=[1.0, 0.005, 0.0001], condim=4)
    return spec.compile(), kinds
