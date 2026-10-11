# AutoLab — the robot that learns how to learn

MongoDB × Cerebral Valley hackathon, Oct 11 2026. Primary track: Recursive Harnessing.

A robot arm's operating procedure (the **harness**) is a versioned document. An Operator agent runs tasks under the
active harness; a Scientist agent diagnoses failures, refits the digital twin in simulation, and proposes harness
mutations; a deterministic evaluator tests every candidate on protected held-out targets (simulation gate, then a
physical stage) and is the only thing that can promote. Everything is persisted in one Atlas database and shown live
in a Modelence dashboard; agent runs are traced to Raindrop.

## Quick start (for someone cloning this repo)

```bash
git clone https://github.com/modestapproach/robot-thing.git && cd robot-thing
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev,sim]' anthropic raindrop-ai pillow
cp .env.example .env                                  # fill in keys; leave MONGODB_URI empty to run offline
.venv/bin/python -m pytest -q                         # 52 tests
.venv/bin/python scripts/run_campaign.py --fresh      # full SO-101 campaign, offline
.venv/bin/python scripts/render_demo_video.py         # writes docs/media/autolab_so101_demo.mp4
```

Dashboard (needs a MongoDB URI with the database name in the path):

```bash
cd dashboard && npm install && cp .modelence.env.example .modelence.env   # fill in MONGODB_URI + AUTOLAB_API_KEY
npm run dev                                                               # http://localhost:3001
```

No keys are committed. Templates: `.env.example`, `dashboard/.modelence.env.example`, `agentengine/*/.env.example`.

## SO-101 digital twin

The arm is the **SO-101** (TheRobotStudio / Hugging Face LeRobot). Nothing about its geometry is hand-made:

- **Model:** official `so101_new_calib` MJCF + URDF + STL meshes from
  [TheRobotStudio/SO-ARM100](https://github.com/TheRobotStudio/SO-ARM100) (Apache-2.0), vendored unmodified in
  `simulation/so101/model/`. The URDF and MJCF agree to 0.002 mm across random poses.
- **Physics:** MuJoCo 3.10.0 (`simulation/so101/sim.py`; the last release with Intel-Mac wheels) with the model's
  STS3215 position actuators.
- **Motion (no hand-rolled solvers):** [mink](https://github.com/kevinzakka/mink) 1.3.0 does IK on the MJCF
  (position task + `AxisAlignTask` pointing the gripper down, roll left free, joint limits), and
  [Ruckig](https://github.com/pantor/ruckig) 0.19.4 generates jerk-limited, time-synchronized joint trajectories at
  50 Hz. The simulator and the LeRobot driver stream the same waypoints (`simulation/so101/motion.py`).
- **Collision gate:** before any move, the planned path is checked against the table/board surface using the
  primitive collision shapes of DeepMind's [MuJoCo Menagerie `robotstudio_so101`](https://github.com/google-deepmind/mujoco_menagerie/tree/main/robotstudio_so101)
  model (same link kinematics as the official model) and `mj_geomDistance`; colliding paths are rejected with a reason.
  AutoLab's tool point is the official `gripperframe` site, at the fixed-jaw tip. The simulated "real world" adds a mis-placed
  board and small servo zero offsets the twin does not know about.
- **Viewer:** the dashboard loads the same URDF + meshes with [`urdf-loader`](https://github.com/gkjohnson/urdf-loaders)
  and three.js, and replays each move with the joint angles the physics recorded.
- **Real arm:** `robot_gateway/drivers/so101_lerobot.py` drives it through LeRobot (`lerobot.robots.so_follower`,
  degrees mode, zero = mid-range, matching the MJCF). Bring-up: `scripts/so101_bringup.py` (read-only by default).

Python 3.12 is required (MuJoCo has no Intel-Mac wheel for 3.14; LeRobot needs ≥3.12). On Intel Macs MuJoCo is
capped at 3.10.0 and Ruckig 0.19.4 builds from source (about a minute).

## Conveyor pick-and-sort cell (SO-101)

A camera-watched conveyor carries a random mix of **red squares** (24 mm cubes) and **blue circles** (24 mm discs)
out of a bucket feeder. The SO-101 picks as many red squares as it can into a bin and earns fictional money:

| Outcome | Money |
|---|---|
| red square in the bin | +$5.00 |
| blue circle in the bin | −$3.00 |
| red square falls off the end | −$1.00 |
| item dropped on the table | −$0.50 |
| blue circle rides off the end | $0.00 |

```bash
.venv/bin/pip install -e '.[conveyor]'
.venv/bin/python scripts/run_conveyor.py --seconds 60     # video: docs/media/conveyor_pick_demo.mp4, ledger: docs/conveyor_last_run.json
```

Built from existing pieces, nothing hand-made for the robot: MuJoCo physics (a conveyor of 43 velocity-driven capsule
rollers, so items ride by friction), the MuJoCo Menagerie SO-101 (its jaw collision pads make grasps real contacts),
an overhead camera rendered by MuJoCo with **OpenCV** colour + shape detection projected to metric belt coordinates,
mink IK with the jaws squared to each cube, Ruckig trajectories, and a **Gymnasium** environment
(`simulation/conveyor/env.py`, reward = money; passes `gymnasium.utils.env_checker`) for RL libraries.
The baseline policy (`simulation/conveyor/picker.py`) stops the line when a red square reaches the pick line,
re-detects with a clear view, grasps, drops it in the bin and restarts the line. Latest 60 s run: **$35.00**,
7/7 picks held, 0 wrong items, 0 misses (simulated).

## What runs today (no hardware, no cloud)

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev,sim]' anthropic raindrop-ai
.venv/bin/python -m pytest -q                       # 57 tests: safety, idempotency, lifecycle, promotion, resume, SO-101, mink/Ruckig, collisions, conveyor
.venv/bin/python scripts/run_campaign.py --fresh    # the 6-scene demo end to end
```

The "lab" is the SO-101 MuJoCo world (set `AUTOLAB_WORLD=mock` for the idealized mock arm). **Every simulated result
is labelled `simulation`**; nothing claims to be a physical measurement until the LeRobot driver is in use.

Latest campaign on the SO-101 physics twin (stored in Atlas DB `so101_lab`, also `docs/last_campaign.json`):

| Stage | Result |
|---|---|
| Baseline, tape-measured board pose | 0/12 within 2 mm, mean error 5.7 mm |
| Recalibration (8 simulated candidates, 1 rejected as implausible) | twin prediction RMSE 5.75 → 0.40 mm |
| Held-out check, 8 protected targets | RMSE 5.87 → 0.44 mm, success 0% → 100% |
| Board bumped | 0/6 within tolerance |
| Mutation A: retry 3× (parameter) | **rejected**: extra physical moves, no gain |
| Mutation B: board-pose check + re-observe/replan (workflow) | **approved**: held-out RMSE 5.36 → 0.55 mm on the SO-101 sim, success 0% → 100% |
| Harness v2 on new tasks | 6/6 within tolerance |
| Meta: uncertainty-weighted calibration targets (experiment policy) | **approved**: 8.3 → 5.9 observations to reach 0.6 mm (40 identical randomized problems) |

## Layout

| Path | What |
|---|---|
| `shared/` | schemas (PRD §10), store (Atlas or in-memory with file persistence), telemetry (Raindrop + `agent_traces`) |
| `harness/` | closed op set, validator (schema + mutation permissions), deterministic runtime |
| `robot_gateway/` | driver interface (mock today), fixed safety envelope, idempotent gateway, ChArUco camera skeleton, HTTP service + client |
| `simulation/` | Level-0 geometric twin, calibration fitter, batch service, experiment-selection study |
| `evaluation/` | protected suite, metrics, evaluator / promotion controller / rollback, review queue |
| `agents/` | Operator and Scientist cores (Claude `claude-opus-5-5` proposals when `ANTHROPIC_API_KEY` is set, deterministic otherwise) |
| `orchestrator/` | the checkpointed, resumable campaign (scenes 1-6) |
| `agentengine/` | Atlas Agent Engine workspaces (`agent.yaml` at repo root lists both) |
| `dashboard/` | Modelence app: Lab, Harness Evolution, Experiments, Digital Twin, Agent Traces, Safety |

## Connect Atlas

1. Put the connection string in `.env` as `MONGODB_URI=...autolab?...` (database name in the path).
2. `.venv/bin/python scripts/check_atlas.py` — pings, creates indexes, seeds harness v1 + twin v0.
3. `.venv/bin/python scripts/run_campaign.py` — the campaign now writes to Atlas.
4. Dashboard: `.venv/bin/python scripts/sync_dashboard_env.py && cd dashboard && npm run dev` → http://localhost:3001

## Demo

Runbook: [docs/DEMO.md](docs/DEMO.md). Fallback video: `docs/media/autolab_so101_demo.mp4` (`scripts/render_demo_video.py`).
Fresh lab on Atlas: `.venv/bin/python scripts/fresh_lab.py --db <new_name>`.

## Resume / pause

```bash
.venv/bin/python scripts/run_campaign.py --stop-after disturbance   # simulate an interruption
.venv/bin/python scripts/run_campaign.py --resume <campaign_id>      # continues; acknowledged moves are never re-sent
.venv/bin/python scripts/run_campaign.py --worker                    # picks up dashboard pause/resume/requests
```

## Agent Engine (needs Docker + the `agentengine` CLI)

```bash
.venv/bin/python scripts/sync_agent_core.py      # vendor the tested core into each workspace
agentengine auth login && agentengine init
agentengine secret set MONGODB_URI   # also ANTHROPIC_API_KEY, VOYAGE_API_KEY, A2A_JWT_SECRET, RAINDROP_WRITE_KEY, ROBOT_GATEWAY_URL/KEY
agentengine dev up --all             # local; playground on :3000
agentengine build --all && agentengine deploy --all
.venv/bin/python scripts/evaluator_worker.py     # local, independent evaluator for hosted Scientist candidates
```

Hosted agents reach the arm only through `robot_gateway/service.py` exposed via an authenticated tunnel; the safety
envelope, e-stop and idempotency stay local.

## Real arm (when identified)

Implement `robot_gateway/driver.py:ArmDriver` for the SDK, set `ROBOT_DRIVER=module:Class`, mount the camera and
use `CharucoCamera`, tighten `SafetyEnvelope` to the manufacturer limits, then `ROBOT_PHYSICAL_ENABLE=1`.
