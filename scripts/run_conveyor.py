"""Run the SO-101 conveyor picking episode and (optionally) record a video.

  .venv/bin/python scripts/run_conveyor.py                     # 60 s episode, writes video + ledger
  .venv/bin/python scripts/run_conveyor.py --seconds 30 --no-video
  .venv/bin/python scripts/run_conveyor.py --seed 3 --speed 0.8

Outputs: docs/media/conveyor_pick_demo.mp4 (main view + live belt-camera inset with OpenCV detections
+ money HUD), docs/conveyor_last_run.json (ledger, counts, pick log). Everything is simulated.
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mujoco
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from simulation.conveyor.cell import ConveyorCell
from simulation.conveyor.picker import Picker, PickerParams
from simulation.conveyor.scene import CellLayout

ap = argparse.ArgumentParser()
ap.add_argument("--seconds", type=float, default=60.0)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--speed", type=float, default=0.6, help="arm speed fraction (Ruckig)")
ap.add_argument("--no-video", action="store_true")
ap.add_argument("--out", default=str(ROOT / "docs/media/conveyor_pick_demo.mp4"))
a = ap.parse_args()

W, H, FPS = 960, 540, 25
cell = ConveyorCell(CellLayout(seed=a.seed), offscreen=(W, H))
ff = renderer = None
frame_i = 0
flash = []  # (until_t, text, colour)


def font(sz):
    for f in ["/System/Library/Fonts/SFNSMono.ttf", "/System/Library/Fonts/Menlo.ttc"]:
        if pathlib.Path(f).exists():
            return ImageFont.truetype(f, sz)
    return ImageFont.load_default()


F_BIG, F_MED, F_SM = font(30), font(17), font(13)
seen_entries = 0


def on_frame():
    global frame_i, seen_entries
    frame_i += 1
    if ff is None or frame_i % 2:
        return
    L = cell.ledger
    for e in L.entries[seen_entries:]:
        txt = f"{'+' if e.amount >= 0 else '-'}${abs(e.amount):.2f}  {e.kind.replace('_', ' ')} -> {e.outcome}"
        flash.append((cell.t + 1.6, txt, (108, 211, 143) if e.amount > 0 else (240, 112, 95) if e.amount < 0 else (138, 154, 150)))
    seen_entries = len(L.entries)
    renderer.update_scene(cell.d, cam)
    img = Image.fromarray(renderer.render())
    belt = picker.cam.annotate(picker.cam.rgb(), picker.last_dets, picker.target)
    inset = Image.fromarray(belt).resize((288, 216))
    img.paste(inset, (W - 288 - 14, 14))
    dr = ImageDraw.Draw(img, "RGBA")
    dr.rectangle([W - 288 - 14, 14, W - 14, 14 + 216], outline=(181, 156, 245), width=2)
    dr.text((W - 288 - 8, 14 + 216 + 4), "belt camera · OpenCV detections", font=F_SM, fill=(181, 156, 245))
    dr.rectangle([0, H - 96, 560, H], fill=(10, 13, 14, 210))
    dr.text((16, H - 90), f"${L.balance:,.2f}", font=F_BIG, fill=(236, 230, 210))
    dr.text((16, H - 50), f"red in bin {L.count('bin', 'red_square')}   blue in bin {L.count('bin', 'blue_circle')}   red missed {L.count('end', 'red_square')}   t={cell.t:4.1f}s",
            font=F_MED, fill=(138, 154, 150))
    dr.text((16, H - 26), "SIMULATED · MuJoCo · SO-101 (Menagerie) · mink + Ruckig · OpenCV", font=F_SM, fill=(181, 156, 245))
    y = H - 130
    for until, txt, col in [f for f in flash if f[0] > cell.t][-3:]:
        dr.text((16, y), txt, font=F_MED, fill=col)
        y -= 22
    dr.text((16, 12), f"belt {'RUNNING' if cell.belt_on else 'STOPPED - picking'}", font=F_MED, fill=(108, 211, 143) if cell.belt_on else (230, 180, 80))
    ff.stdin.write(np.asarray(img).tobytes())


picker = Picker(cell, PickerParams(speed=a.speed), on_frame=on_frame)
if not a.no_video:
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    renderer = mujoco.Renderer(cell.m, H, W)
    cam = mujoco.MjvCamera()
    cam.lookat[:] = [0.17, 0.04, 0.03]
    cam.distance, cam.azimuth, cam.elevation = 0.62, 200, -30
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "21", "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)

t0 = time.time()
picker.run(duration_s=a.seconds)
if ff:
    ff.stdin.close()
    ff.wait()
L = cell.ledger
summary = {
    "seconds_simulated": round(cell.t, 2), "wall_seconds": round(time.time() - t0, 1), "seed": a.seed, "arm_speed": a.speed,
    "balance": L.balance,
    "counts": {"red_in_bin": L.count("bin", "red_square"), "blue_in_bin": L.count("bin", "blue_circle"),
               "red_missed": L.count("end", "red_square"), "blue_passed": L.count("end", "blue_circle"),
               "dropped": L.count("table", "red_square") + L.count("table", "blue_circle")},
    "picks": {"attempts": picker.stats.attempts, "held": picker.stats.grasped, "log": picker.stats.events},
    "ledger": [e.__dict__ for e in L.entries],
    "environment": "simulation",
}
(ROOT / "docs/conveyor_last_run.json").write_text(json.dumps(summary, indent=1))
print(json.dumps({k: summary[k] for k in ("seconds_simulated", "wall_seconds", "balance", "counts")}, indent=1))
print(f"picks: {picker.stats.attempts} attempted, {picker.stats.grasped} held")
if not a.no_video:
    print(f"video: {a.out} ({pathlib.Path(a.out).stat().st_size / 1e6:.1f} MB)")
