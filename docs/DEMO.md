# AutoLab — 5-minute demo runbook

Everything shown is **simulated** (MuJoCo physics on the official SO-101 model) unless the LeRobot driver is
connected; the dashboard labels every number with its provenance. Say so out loud.

## Before going on stage (venue Wi-Fi — Atlas only allows the venue IP)

```bash
cd autolab
.venv/bin/python scripts/fresh_lab.py --db so101_demo   # new DB, seeds, runs the full campaign (~1-2 min on Atlas)
cd dashboard && npm run dev                              # http://localhost:3001 (or the deployed Modelence URL)
```

Fallback if Wi-Fi or Atlas fails: play `docs/media/autolab_so101_demo.mp4` (rendered from a real campaign run;
regenerate with `.venv/bin/python scripts/render_demo_video.py`). Offline campaign: `scripts/run_campaign.py --fresh`.

## Script

| Time | Say | Show |
|---|---|---|
| 0:00 | "Robots follow programs. When the model is wrong, an engineer fixes it. What if the robot ran its own experiments and improved the procedure itself?" | Lab page: SO-101 viewer (official URDF), campaign strip |
| 0:40 | Scene 1 — the arm misses: board placed from a tape measure. | Lab → Reality board plot (red vectors, ~5.7 mm misses), Experiments page replay of a baseline trial |
| 1:20 | Scene 2-3 — the Scientist refits the twin from the misses: 8 candidate calibrations simulated, 1 rejected as physically implausible. | Lab → Simulation: candidate ranking bars, prediction RMSE 5.7 → 0.4 mm; Digital Twin page lineage |
| 2:10 | Scene 4 — held-out improvement, measured on 8 protected targets the Scientist never saw. | Simulation panel: held-out RMSE ~5.9 → ~0.45 mm, success 0% → 100% |
| 3:00 | Scene 5 — someone bumps the board; the calibrated arm fails again. The Scientist proposes two competing harness changes. It cannot activate either. | Harness Evolution: v1 → v2 diff (`check_board_pose`, re-observe + replan) next to the metrics; the rejected "retry 3×" candidate with its reason |
| 3:40 | Scene 6 — v2 is promoted by the independent evaluator after a simulation gate and a physical-stage check; new tasks pin v2 and recover. | Lab → Experiments table (v2 rows within tolerance), Safety page (envelope, rejected commands) |
| 4:10 | Recursion: it also improved *how it learns* — uncertainty-weighted calibration targets need 28% fewer observations. | Harness Evolution: v3 (experiment_policy) with the 40-problem study |
| 4:30 | Long horizon + observability: every run is a trace; the campaign resumes from checkpoints without re-sending a motor command. | Agent Traces page; `scripts/run_campaign.py --stop-after disturbance` then `--resume <id>` |
| 4:45 | "The physical world gives evidence, MongoDB keeps the memory, the twin is a safe place to test ideas." | Lab page |

## Honest caveats to have ready
- The arm results are from the SO-101 MuJoCo twin unless the LeRobot driver is connected (`scripts/so101_bringup.py`).
- Sample sizes are small (8 protected targets; 40 virtual problems for the selection study).
- The Scientist uses Claude when `ANTHROPIC_API_KEY` is set, otherwise a deterministic cheapest-hypothesis-first policy;
  the trace shows which (`model` property).

## Stack credits (all open source, nothing hand-made for the robot)
Official SO-101 MJCF/URDF/meshes (TheRobotStudio, Apache-2.0) · MuJoCo 3.10 · mink (IK) · Ruckig (trajectories) ·
MuJoCo Menagerie `robotstudio_so101` collision shapes · urdf-loader + three.js (viewer) · LeRobot (hardware) ·
MongoDB Atlas + Agent Engine · Modelence · Raindrop.
