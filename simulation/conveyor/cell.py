"""Conveyor cell runtime: physics stepping, bucket feeder, belt control, and the money ledger.

Fictional money (the reward), settled once per item when it comes to rest:
  +$5.00  red square in the collection bin       (the job)
  -$3.00  blue circle in the collection bin      (wrong item)
  -$1.00  red square fell off the end of the belt (missed opportunity)
  -$0.50  any item dropped on the table          (handling error)
   $0.00  blue circle off the end of the belt     (correctly ignored)
Settled items are returned to the bucket, so the stream never runs dry.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import mujoco
import numpy as np

from simulation.conveyor.scene import (BELT_HALF_W, BELT_TOP, BELT_X, BELT_Y1, BIN_CENTER, BIN_HALF, CUBE_HALF, DISC_HALF_H,
                                       DISPENSE_Y, PARK_X, ROLLER_R, CellLayout, build_cell)
from simulation.so101.kinematics import ALL_JOINTS

PAYOUT = {"bin:red_square": 5.00, "bin:blue_circle": -3.00, "end:red_square": -1.00, "end:blue_circle": 0.00,
          "table:red_square": -0.50, "table:blue_circle": -0.50}
CONTROL_DT = 0.02


@dataclass
class LedgerEntry:
    t: float
    obj: int
    kind: str
    outcome: str      # bin | end | table
    amount: float


@dataclass
class Ledger:
    entries: list[LedgerEntry] = field(default_factory=list)

    @property
    def balance(self) -> float:
        return round(sum(e.amount for e in self.entries), 2)

    def count(self, outcome: str, kind: str) -> int:
        return sum(1 for e in self.entries if e.outcome == outcome and e.kind == kind)


class ConveyorCell:
    def __init__(self, layout: CellLayout = CellLayout(), belt_speed: float = 0.05, dispense_every=(1.4, 2.4), offscreen=(960, 540)) -> None:
        self.m, self.kinds = build_cell(layout, offscreen)
        self.d = mujoco.MjData(self.m)
        self.rng = np.random.default_rng(layout.seed + 101)
        self.belt_speed = belt_speed
        self.dispense_every = dispense_every
        self.rollers = np.array([i for i in range(self.m.nu) if self.m.actuator(i).name.startswith("roller")])
        self.arm_act = np.array([self.m.actuator(j).id for j in ALL_JOINTS])
        self.arm_qadr = np.array([self.m.joint(j).qposadr[0] for j in ALL_JOINTS])
        self.obj_qadr = [self.m.joint(f"obj{i}").qposadr[0] for i in range(len(self.kinds))]
        self.obj_dadr = [self.m.joint(f"obj{i}").dofadr[0] for i in range(len(self.kinds))]
        self.state = ["parked"] * len(self.kinds)   # parked | belt | handled
        self.queue = list(self.rng.permutation(len(self.kinds)))
        self.ledger = Ledger()
        self.t = 0.0
        self.belt_on = True
        self._next_dispense = 0.5
        self._belt_time = 0.0  # feeder runs on belt time, so it pauses with the line

    # ------------------------------------------------------------------ arm
    def set_arm(self, q6: np.ndarray, snap: bool = False) -> None:
        self.d.ctrl[self.arm_act] = q6
        if snap:
            self.d.qpos[self.arm_qadr] = q6
            self.d.qvel[:] = 0
            mujoco.mj_forward(self.m, self.d)

    def arm_q(self) -> np.ndarray:
        return self.d.qpos[self.arm_qadr].copy()

    # ------------------------------------------------------------------ objects
    def obj_pos(self, i: int) -> np.ndarray:
        a = self.obj_qadr[i]
        return self.d.qpos[a:a + 3].copy()

    def _place(self, i: int, pos, yaw: float = 0.0) -> None:
        a, v = self.obj_qadr[i], self.obj_dadr[i]
        self.d.qpos[a:a + 3] = pos
        self.d.qpos[a + 3:a + 7] = [np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]
        self.d.qvel[v:v + 6] = 0

    def _dispense(self) -> None:
        for _ in range(len(self.queue)):
            i = self.queue.pop(0)
            if self.state[i] == "parked":
                h = CUBE_HALF if self.kinds[i] == "red_square" else DISC_HALF_H
                self._place(i, [BELT_X + self.rng.uniform(-0.018, 0.018), DISPENSE_Y, BELT_TOP + h + 0.006], self.rng.uniform(-0.8, 0.8))
                self.state[i] = "belt"
                return
            self.queue.append(i)

    def _park(self, i: int) -> None:
        self._place(i, [PARK_X, -0.4 + 0.04 * i, 0.03])
        self.state[i] = "parked"
        self.queue.append(i)

    def _settle(self) -> None:
        for i, st in enumerate(self.state):
            if st == "parked":
                continue
            p = self.obj_pos(i)
            v = np.linalg.norm(self.d.qvel[self.obj_dadr[i]:self.obj_dadr[i] + 3])
            in_bin = abs(p[0] - BIN_CENTER[0]) < BIN_HALF and abs(p[1] - BIN_CENTER[1]) < BIN_HALF and p[2] < 0.035
            # fell off the downstream end: past the last roller, or at its foot below belt height
            off_end = p[1] < BELT_Y1 - 0.01 or (p[1] < BELT_Y1 + 0.03 and p[2] < BELT_TOP - 0.006)
            on_belt = abs(p[0] - BELT_X) < BELT_HALF_W + 0.01 and BELT_Y1 - 0.01 <= p[1] <= DISPENSE_Y + 0.03 and p[2] > BELT_TOP - 0.005
            on_table = p[2] < 0.02 and not in_bin
            outcome = None
            if in_bin and v < 0.02:
                outcome = "bin"
            elif off_end:
                outcome = "end"
            elif on_table and not on_belt and v < 0.02:
                outcome = "table"
            if outcome:
                kind = self.kinds[i]
                self.ledger.entries.append(LedgerEntry(round(self.t, 2), i, kind, outcome, PAYOUT[f"{outcome}:{kind}"]))
                self._park(i)

    # ------------------------------------------------------------------ stepping
    def set_belt(self, on: bool) -> None:
        self.belt_on = on

    def step(self, n_ctrl: int = 1) -> None:
        sub = int(round(CONTROL_DT / self.m.opt.timestep))
        for _ in range(n_ctrl):
            self.d.ctrl[self.rollers] = (self.belt_speed / ROLLER_R) if self.belt_on else 0.0
            if self.belt_on:
                self._belt_time += CONTROL_DT
                if self._belt_time >= self._next_dispense:
                    self._dispense()
                    self._next_dispense = self._belt_time + self.rng.uniform(*self.dispense_every)
            for _ in range(sub):
                mujoco.mj_step(self.m, self.d)
            self.t += CONTROL_DT
            self._settle()
