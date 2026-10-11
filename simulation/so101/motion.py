"""Joint-space trajectory generation with **Ruckig** (jerk-limited, time-optimal, MIT).

One function, shared by the MuJoCo simulator and the LeRobot hardware driver, so the
simulated arm and the real arm receive the same 50 Hz waypoint stream. LeRobot does no
smoothing of its own and sets the STS3215 acceleration register to maximum, so host-side
jerk limiting is what keeps real moves smooth.

Ruckig Community has no position limits; callers pass goals that IK already clamped to the
joint ranges, and rest-to-rest moves between in-range points stay in range.
"""
from __future__ import annotations

import numpy as np
from ruckig import InputParameter, OutputParameter, Result, Ruckig

CONTROL_DT = 0.02  # 50 Hz, LeRobot send rate
# Per-joint limits at speed_fraction = 1.0 (STS3215 no-load ~4.7 rad/s; keep well below).
MAX_VEL = 3.0     # rad/s
MAX_ACC = 12.0    # rad/s^2
MAX_JERK = 120.0  # rad/s^3


def plan_joint_trajectory(q_start: np.ndarray, q_goal: np.ndarray, speed_fraction: float = 0.3,
                          dt: float = CONTROL_DT) -> tuple[np.ndarray, np.ndarray]:
    """Rest-to-rest move. Returns (times[N], positions[N, dof]) sampled every ``dt``,
    ending exactly at ``q_goal``. All joints are time-synchronized."""
    q_start = np.asarray(q_start, dtype=float)
    q_goal = np.asarray(q_goal, dtype=float)
    dof = len(q_start)
    s = float(np.clip(speed_fraction, 0.05, 1.0))
    otg, inp, out = Ruckig(dof, dt), InputParameter(dof), OutputParameter(dof)
    inp.current_position = q_start.tolist()
    inp.current_velocity = [0.0] * dof
    inp.current_acceleration = [0.0] * dof
    inp.target_position = q_goal.tolist()
    inp.target_velocity = [0.0] * dof
    inp.target_acceleration = [0.0] * dof
    inp.max_velocity = [MAX_VEL * s] * dof
    inp.max_acceleration = [MAX_ACC * s] * dof
    inp.max_jerk = [MAX_JERK * s] * dof
    times, pts = [], []
    res = Result.Working
    while res == Result.Working:
        res = otg.update(inp, out)
        times.append(out.time)
        pts.append(list(out.new_position))
        out.pass_to_input(inp)
    if res != Result.Finished:
        raise RuntimeError(f"Ruckig failed: {res}")
    return np.array(times), np.array(pts)
