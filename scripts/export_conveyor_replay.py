"""Export recorded conveyor episodes for the browser replay (Amble Presents SIM LAB, three.js).

  .venv/bin/python scripts/export_conveyor_replay.py --out "<pack>/hypernym/presents/sim" --seeds 0 3 --seconds 60

Runs the real MuJoCo cell + scripted picker and writes, per episode, 25 fps frames (SO-101 joint
angles, every active item's pose, roller angle, belt state, money), every camera detection
(pixel coordinates in the 320x240 belt camera), the money ledger and the pick log. The static
scene (rollers, rails, bucket, bin, camera) is read from the compiled MuJoCo model, so the
browser rebuilds exactly what was simulated. Also copies the official SO-101 URDF + meshes.
Nothing in the browser is simulated; it is a faithful replay labelled as such.
"""
import argparse
import json
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mujoco
import numpy as np

from simulation.conveyor.cell import PAYOUT, ConveyorCell
from simulation.conveyor.picker import Picker, PickerParams
from simulation.conveyor.scene import CellLayout
from simulation.so101.kinematics import ALL_JOINTS

GEOM = {mujoco.mjtGeom.mjGEOM_BOX: "box", mujoco.mjtGeom.mjGEOM_CYLINDER: "cylinder", mujoco.mjtGeom.mjGEOM_CAPSULE: "capsule",
        mujoco.mjtGeom.mjGEOM_PLANE: "plane", mujoco.mjtGeom.mjGEOM_SPHERE: "sphere"}
R = lambda a, n=4: [round(float(x), n) for x in a]


def scene_description(cell: ConveyorCell, picker: Picker) -> dict:
    m = cell.m
    static = []
    for g in range(m.ngeom):
        if m.geom_bodyid[g] != 0 or m.geom_type[g] not in GEOM or GEOM[m.geom_type[g]] == "plane":
            continue
        static.append({"name": m.geom(g).name, "type": GEOM[m.geom_type[g]], "size": R(m.geom_size[g]), "pos": R(m.geom_pos[g]),
                       "quat": R(m.geom_quat[g]), "rgba": R(m.geom_rgba[g], 3)})
    rollers = []
    for b in range(m.nbody):
        if m.body(b).name.startswith("roller"):
            g = m.body_geomadr[b]
            rollers.append({"pos": R(m.body_pos[b]), "radius": round(float(m.geom_size[g][0]), 4),
                            "half_len": round(float(m.geom_size[g][1] + m.geom_size[g][0]), 4), "rgba": R(m.geom_rgba[g], 3)})
    c = m.camera("belt_cam").id
    return {"static": static, "rollers": rollers, "objects_note": "item kinds depend on the seed; see each episode's 'objects'",
            "belt_cam": {"pos": R(m.cam_pos[c]), "quat": R(m.cam_quat[c]), "fovy": float(m.cam_fovy[c]), "width": picker.cam.W, "height": picker.cam.H},
            "robot": {"urdf": "robot/so101_new_calib.urdf", "joints": ALL_JOINTS, "base_pos": [0, 0, 0]},
            "payout": PAYOUT, "frame": "MuJoCo world = SO-101 base frame, metres, z up"}


def record_episode(seed: int, seconds: float, speed: float) -> tuple[dict, dict]:
    cell = ConveyorCell(CellLayout(seed=seed))
    frames, looks = [], []
    roller0 = cell.m.joint("roller0").qposadr[0]
    tick = {"n": 0}

    def on_frame():
        tick["n"] += 1
        if tick["n"] % 2:
            return
        objs = [[i, *R(cell.obj_pos(i), 4), *R(cell.d.qpos[cell.obj_qadr[i] + 3:cell.obj_qadr[i] + 7], 3)]
                for i, st in enumerate(cell.state) if st != "parked"]
        tgt = picker.target
        frames.append({"t": round(cell.t, 2), "q": R(cell.arm_q(), 4), "r": round(float(cell.d.qpos[roller0]), 3),
                       "b": 1 if cell.belt_on else 0, "m": cell.ledger.balance, "o": objs,
                       "tgt": R(tgt.xy, 4) if tgt is not None else None})

    picker = Picker(cell, PickerParams(speed=speed), on_frame=on_frame)
    orig_look = picker.look

    def look():
        dets = orig_look()
        looks.append({"t": round(cell.t, 2), "d": [[d.kind, round(d.pixel[0], 1), round(d.pixel[1], 1), round(d.area_px, 1), *R(d.xy, 4)] for d in dets]})
        return dets

    picker.look = look
    t0 = time.time()
    picker.run(duration_s=seconds)
    L = cell.ledger
    m = cell.m
    objects = [{"id": i, "kind": k, "type": GEOM[m.geom_type[m.geom(f"obj{i}").id]], "size": R(m.geom_size[m.geom(f"obj{i}").id]),
                "rgba": R(m.geom_rgba[m.geom(f"obj{i}").id], 3)} for i, k in enumerate(cell.kinds)]
    episode = {
        "seed": seed, "seconds": round(cell.t, 2), "fps": 25, "arm_speed": speed, "environment": "simulation (recorded MuJoCo run)",
        "objects": objects,
        "frames": frames, "looks": looks,
        "ledger": [{"t": e.t, "id": e.obj, "kind": e.kind, "outcome": e.outcome, "amount": e.amount} for e in L.entries],
        "picks": picker.stats.events,
        "summary": {"balance": L.balance, "red_in_bin": L.count("bin", "red_square"), "blue_in_bin": L.count("bin", "blue_circle"),
                    "red_missed": L.count("end", "red_square"), "blue_passed": L.count("end", "blue_circle"),
                    "dropped": L.count("table", "red_square") + L.count("table", "blue_circle"),
                    "picks_held": picker.stats.grasped, "picks_attempted": picker.stats.attempts},
    }
    print(f"seed {seed}: {cell.t:.0f}s simulated in {time.time() - t0:.0f}s, balance ${L.balance:.2f}, {len(frames)} frames, {len(looks)} camera looks")
    return episode, scene_description(cell, picker)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="the pack's hypernym/presents/sim folder")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--speed", type=float, default=0.6)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    (out / "data").mkdir(parents=True, exist_ok=True)
    index, scene = [], None
    for s in a.seeds:
        ep, scene = record_episode(s, a.seconds, a.speed)
        name = f"episode-{s}.json"
        (out / "data" / name).write_text(json.dumps(ep, separators=(",", ":")))
        index.append({"file": f"data/{name}", "seed": s, **ep["summary"], "seconds": ep["seconds"]})
    (out / "data" / "scene.json").write_text(json.dumps(scene, separators=(",", ":")))
    (out / "data" / "episodes.json").write_text(json.dumps({"episodes": index, "generated_by": "autolab/scripts/export_conveyor_replay.py"}, indent=1))
    robot = out / "robot"
    (robot / "assets").mkdir(parents=True, exist_ok=True)
    model = ROOT / "simulation/so101/model"
    shutil.copy(model / "so101_new_calib.urdf", robot / "so101_new_calib.urdf")
    for f in (model / "assets").glob("*.stl"):
        if f"assets/{f.name}" in (model / "so101_new_calib.urdf").read_text():
            shutil.copy(f, robot / "assets" / f.name)
    shutil.copy(model / "NOTICE.md", robot / "NOTICE.md")
    print(f"wrote {out}/data ({sum(p.stat().st_size for p in (out / 'data').glob('*')) / 1e6:.1f} MB) and {robot}")


if __name__ == "__main__":
    main()
