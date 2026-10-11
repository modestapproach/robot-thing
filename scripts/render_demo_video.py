"""Render a fallback demo video of the SO-101 campaign with MuJoCo's own renderer.

  .venv/bin/python scripts/render_demo_video.py            # runs the campaign in memory, writes docs/media/
  .venv/bin/python scripts/render_demo_video.py --hd       # 1280x720 instead of 960x540

Every clip replays a *recorded* trajectory from that campaign (true joint angles from the
physics) on the official SO-101 model, with the board at its true pose for that scene and
the measured error from the experiment record. Frames are captioned SIMULATED.
"""
import argparse
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("MONGODB_URI", None)

import math

import mujoco
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from orchestrator.campaign import BUMP, Campaign
from shared.store import MemoryStore
from simulation.so101.kinematics import ALL_JOINTS, MODEL_XML
from simulation.so101.sim import BOARD_H_MM, BOARD_T_MM, BOARD_W_MM
from simulation.world import so101_truth

ap = argparse.ArgumentParser()
ap.add_argument("--hd", action="store_true")
ap.add_argument("--out", default=str(ROOT / "docs/media/autolab_so101_demo.mp4"))
a = ap.parse_args()
W, H = (1280, 720) if a.hd else (960, 540)
FPS = 25


def scene(board):
    spec = mujoco.MjSpec.from_file(str(MODEL_XML))
    spec.visual.global_.offwidth, spec.visual.global_.offheight = W, H
    tex = spec.add_texture(name="checker", type=mujoco.mjtTexture.mjTEXTURE_2D, builtin=mujoco.mjtBuiltin.mjBUILTIN_CHECKER,
                           width=800, height=600, rgb1=[0.93, 0.9, 0.82], rgb2=[0.11, 0.13, 0.14])
    mat = spec.add_material(name="board_mat")
    mat.textures[mujoco.mjtTextureRole.mjTEXROLE_RGB] = "checker"
    mat.texrepeat = [4, 3]
    wb = spec.worldbody
    floor = wb.add_geom(name="floor", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[0.6, 0.6, 0.01], rgba=[0.09, 0.11, 0.12, 1])
    th = math.radians(board.rotation_deg)
    cx = board.offset_mm.x + (math.cos(th) * BOARD_W_MM / 2 - math.sin(th) * BOARD_H_MM / 2)
    cy = board.offset_mm.y + (math.sin(th) * BOARD_W_MM / 2 + math.cos(th) * BOARD_H_MM / 2)
    wb.add_geom(name="board", type=mujoco.mjtGeom.mjGEOM_BOX, size=[BOARD_W_MM / 2000, BOARD_H_MM / 2000, BOARD_T_MM / 2000],
                pos=[cx / 1000, cy / 1000, BOARD_T_MM / 2000], quat=[math.cos(th / 2), 0, 0, math.sin(th / 2)],
                material="board_mat", contype=0, conaffinity=0)
    tgt = wb.add_body(name="target", mocap=True)
    tgt.add_geom(type=mujoco.mjtGeom.mjGEOM_CYLINDER, size=[0.006, 0.0008, 0], rgba=[0.94, 0.44, 0.37, 1], contype=0, conaffinity=0)
    wb.add_light(pos=[0.1, -0.3, 0.8], dir=[0, 0.3, -1], diffuse=[0.7, 0.7, 0.7])
    m = spec.compile()
    return m, mujoco.MjData(m)


def font(size):
    for f in ["/System/Library/Fonts/SFNSMono.ttf", "/System/Library/Fonts/Menlo.ttc", "/Library/Fonts/Arial.ttf"]:
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


F_BIG, F_MED, F_SMALL = font(30 if a.hd else 24), font(20 if a.hd else 16), font(16 if a.hd else 13)


def caption(img, title, lines, tag="SIMULATED · MuJoCo · official SO-101 model (TheRobotStudio)"):
    im = Image.fromarray(img)
    d = ImageDraw.Draw(im, "RGBA")
    d.rectangle([0, 0, W, 78 if not a.hd else 100], fill=(10, 13, 14, 200))
    d.text((18, 10), title, font=F_BIG, fill=(236, 230, 210))
    y = H - 22 - 22 * len(lines)
    d.rectangle([0, y - 10, W, H], fill=(10, 13, 14, 190))
    for i, (txt, col) in enumerate(lines):
        d.text((18, y + 22 * i), txt, font=F_MED, fill=col)
    d.text((18, 50 if not a.hd else 66), tag, font=F_SMALL, fill=(181, 156, 245))
    return np.asarray(im)


def render_clip(ff, board, traj, target_mm, title, lines, hold_s=1.6):
    m, d = scene(board)
    r = mujoco.Renderer(m, H, W)
    cam = mujoco.MjvCamera()
    cam.lookat[:] = [0.15, 0.0, 0.10]
    cam.distance, cam.azimuth, cam.elevation = 0.74, 205, -24
    d.mocap_pos[0] = [target_mm["x"] / 1000, target_mm["y"] / 1000, BOARD_T_MM / 1000 + 0.0009]
    qadr = [m.joint(j).qposadr[0] for j in traj.get("joints", ALL_JOINTS)]
    frames = traj["q_rad"]
    for i in range(len(frames) + int(hold_s * FPS)):
        q = frames[min(i, len(frames) - 1)]
        d.qpos[qadr[: len(q)]] = q
        mujoco.mj_forward(m, d)
        r.update_scene(d, cam)
        done = i >= len(frames) - 1
        ff.stdin.write(caption(r.render(), title, lines if done else lines[:1]).tobytes())
    r.close()


def card(ff, title, lines, seconds=2.4):
    img = np.full((H, W, 3), (10, 13, 14), dtype=np.uint8)
    im = Image.fromarray(img)
    d = ImageDraw.Draw(im)
    d.text((60, H // 2 - 90), title, font=F_BIG, fill=(236, 230, 210))
    import textwrap

    y = H // 2 - 40
    for t, c in lines:
        for chunk in textwrap.wrap(t, width=int((W - 120) / (F_MED.size * 0.62))) or [""]:
            d.text((60, y), chunk, font=F_MED, fill=c)
            y += 26
    buf = np.asarray(im).tobytes()
    for _ in range(int(seconds * FPS)):
        ff.stdin.write(buf)


print("running campaign (in memory) ...")
store = MemoryStore()
camp = Campaign(store, log=lambda s: None)
out = camp.run()
truth = so101_truth()
bumped = truth.model_copy(update={"offset_mm": truth.offset_mm.model_copy(update={"x": truth.offset_mm.x + BUMP[0], "y": truth.offset_mm.y + BUMP[1]}),
                                  "rotation_deg": truth.rotation_deg + BUMP[2]})


def pick(stage, scenario="sel_03"):
    t = next(x for x in out[stage]["trials"] if x["scenario"] == scenario)
    e = store.get("experiments", t["experiment_id"])
    traj = store.get("sim_trajectories", [r for r in e["artifact_refs"] if r.startswith("traj")][-1])
    hv = store.get("harness_versions", e["harness_version_id"])
    return e, traj, hv


OK, BAD, DIM = (108, 211, 143), (240, 112, 95), (138, 154, 150)
out_path = pathlib.Path(a.out)
out_path.parent.mkdir(parents=True, exist_ok=True)
ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", str(out_path)], stdin=subprocess.PIPE)
inv = out["investigate"]["outcomes"]
card(ff, "AutoLab — the robot that learns how to learn", [("SO-101 digital twin · MuJoCo physics · mink IK · Ruckig trajectories", DIM),
                                                          ("Every clip below replays a recorded trajectory from one campaign.", DIM)])
e, tr, hv = pick("baseline")
render_clip(ff, truth, tr, e["target_position_mm"] and {"x": tr["target_base_mm"]["x"], "y": tr["target_base_mm"]["y"]},
            f"1 · Baseline (harness v{hv['version']}, tape-measured board)", [("target sel_03 · board placed a few mm off nominal", DIM), (f"measured miss {e['position_error_mm']:.2f} mm  (tolerance 2 mm)", BAD)])
e, tr, hv = pick("verify_calibration")
s = out["recalibrate"]["summary"]
render_clip(ff, truth, tr, tr["target_base_mm"], f"2 · After the Scientist refits the twin in simulation",
            [(f"twin prediction RMSE {s['prediction_rmse_mm_parent']:.2f} -> {s['prediction_rmse_mm_new']:.2f} mm ({s['candidates']} candidates, {s['rejected_inadmissible']} rejected)", DIM),
             (f"measured miss {e['position_error_mm']:.2f} mm", OK)])
e, tr, hv = pick("disturbance")
render_clip(ff, bumped, tr, tr["target_base_mm"], f"3 · Someone bumps the board (harness v{hv['version']})",
            [("board moved +2.5 mm, +3.0 mm, +0.6 deg; retry re-sends the same command", DIM), (f"measured miss {e['position_error_mm']:.2f} mm", BAD)])
card(ff, "4 · The Scientist proposes harness mutations", [(f"{o.get('mutation_type')}: {o['decision'].upper()} — {(o['reasons'] or [''])[-1]}", OK if o['decision'] == 'approve' else BAD) for o in inv], seconds=4.0)
e, tr, hv = pick("recovered")
render_clip(ff, bumped, tr, tr["target_base_mm"], f"5 · New tasks run harness v{hv['version']}: check board, re-observe, replan",
            [("same bumped board, same target", DIM), (f"measured miss {e['position_error_mm']:.2f} mm after {e['retries']} replanned retry", OK)])
meta = out["meta_improvement"]["outcomes"][0]
card(ff, "6 · It also improved how it learns", [(meta["reasons"][0], OK), ("Every change passed protected held-out tests before activation.", DIM)], seconds=4.0)
ff.stdin.close()
ff.wait()
print(f"wrote {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")
