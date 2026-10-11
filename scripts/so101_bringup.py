"""SO-101 bring-up: verify the real arm against the digital twin before letting AutoLab move it.

  .venv/bin/python scripts/so101_bringup.py --port /dev/tty.usbmodemXXXX            # read-only (default)
  .venv/bin/python scripts/so101_bringup.py --port ... --mirror 20                  # stream encoders -> twin for 20 s
  ROBOT_PHYSICAL_ENABLE=1 .venv/bin/python scripts/so101_bringup.py --port ... --move   # slow 3-pose check

Read-only mode prints each joint (LeRobot degrees and model radians) and the tool point
predicted by the SO-101 model from those encoder angles. Move the arm by hand (torque is
released in read-only mode) and check each joint's sign matches the MJCF; fix mismatches with
SO101_JOINT_MAP. --mirror records an encoder-driven trajectory (labelled real_hardware) that the
dashboard replays. --move visits three safe poses above the board centre at 15% speed.
"""
import argparse
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import shared.config  # noqa: F401

import numpy as np

from robot_gateway.drivers.so101_lerobot import So101LeRobotDriver
from shared.ids import new_id
from shared.schemas import XY, utcnow
from simulation.so101.kinematics import ARM_JOINTS

ap = argparse.ArgumentParser()
ap.add_argument("--port", default=os.environ.get("SO101_PORT"))
ap.add_argument("--id", default=os.environ.get("SO101_ID", "autolab_follower"))
ap.add_argument("--mirror", type=float, default=0.0, help="seconds of encoder mirroring to record")
ap.add_argument("--move", action="store_true")
a = ap.parse_args()
if not a.port:
    sys.exit("Pass --port (find it with `lerobot-find-port`).")

drv = So101LeRobotDriver(port=a.port, robot_id=a.id)
drv.connect()
try:
    if not a.move:
        drv.robot.bus.disable_torque()  # read-only: let the user move the arm by hand
    deg = drv._read_deg()
    q = drv.lerobot_deg_to_model(deg)
    print(f"{'joint':<14}{'lerobot deg':>12}{'model rad':>11}")
    for j, dd, qq in zip(ARM_JOINTS, deg, q):
        print(f"{j:<14}{dd:>12.2f}{qq:>11.3f}")
    p, z = drv.read_tool_position()
    print(f"tool point from encoders (F_base): x={p.x:.1f} y={p.y:.1f} z={z:.1f} mm")

    if a.mirror > 0:
        frames, t0 = [], time.monotonic()
        while time.monotonic() - t0 < a.mirror:
            frames.append(drv._frame(time.monotonic() - t0))
            time.sleep(0.05)
        from shared.store import get_store

        doc = {"_id": new_id("traj"), "command_id": "bringup_mirror", "robot_id": "robot_so101", "driver": "so101",
               "environment": "real_hardware", "source": "encoder mirror (hand-guided)", "target_base_mm": {"x": p.x, "y": p.y},
               "height_mm": z, "created_at": utcnow(), "t": [f[0] for f in frames],
               "bodies": ["base", "shoulder", "upper_arm", "lower_arm", "wrist", "gripper", "gripperframe"],
               "pos_mm": [f[1] for f in frames], "joints": ARM_JOINTS, "q_rad": [f[2] for f in frames], "dt_s": 0.05, "harness_version_id": None}
        get_store().insert("sim_trajectories", doc)
        print(f"recorded {len(frames)} encoder frames -> sim_trajectories/{doc['_id']} (shows on the dashboard)")

    if a.move:
        if os.environ.get("ROBOT_PHYSICAL_ENABLE") != "1":
            sys.exit("Refusing to move: set ROBOT_PHYSICAL_ENABLE=1 after clearing the workspace.")
        for x, y, h in [(190, 0, 90), (190, 40, 70), (190, -40, 70)]:
            ok, why = drv.can_reach(XY(x=x, y=y), h)
            if not ok:
                sys.exit(f"pose ({x},{y},{h}) unreachable: {why}")
            print(f"moving to ({x}, {y}, {h}) mm at 15% speed ...")
            drv.move_to(XY(x=x, y=y), h, 0.15, 8.0)
            p, z = drv.read_tool_position()
            print(f"  encoders say tool at ({p.x:.1f}, {p.y:.1f}, {z:.1f}) mm; check it visually against the command")
finally:
    drv.disconnect()
