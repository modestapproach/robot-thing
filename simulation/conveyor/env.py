"""Gymnasium environment for the SO-101 conveyor cell. Reward = fictional money earned per step.

Action (Box, 7): absolute targets for the 6 SO-101 position actuators (5 arm joints + gripper, rad)
                 and belt switch (>0 = run). Observation (Dict): belt camera RGB (240x320x3, uint8),
                 measured joint angles (6), belt state (1). Episodes are time-limited.
Compatible with any Gymnasium-based RL library; the scripted picker (picker.py) is a baseline.
"""
from __future__ import annotations

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from simulation.conveyor.cell import ConveyorCell
from simulation.conveyor.scene import CellLayout
from simulation.conveyor.vision import BeltCamera


class So101ConveyorEnv(gym.Env):
    metadata = {"render_modes": ["rgb_array"], "render_fps": 25}

    def __init__(self, episode_s: float = 60.0, ctrl_per_step: int = 2, render_mode: str | None = None, seed: int = 0) -> None:
        self.episode_s, self.ctrl_per_step, self.render_mode, self._seed = episode_s, ctrl_per_step, render_mode, seed
        self.cell: ConveyorCell | None = None
        lo = np.array([-1.92, -1.75, -1.69, -1.66, -2.74, -0.17, -1.0], dtype=np.float32)
        hi = np.array([1.92, 1.75, 1.69, 1.66, 2.84, 1.75, 1.0], dtype=np.float32)
        self.action_space = spaces.Box(lo, hi, dtype=np.float32)
        self.observation_space = spaces.Dict({
            "image": spaces.Box(0, 255, (240, 320, 3), dtype=np.uint8),
            "joints": spaces.Box(-np.pi, np.pi, (6,), dtype=np.float32),
            "belt_on": spaces.Box(0.0, 1.0, (1,), dtype=np.float32),
        })

    def _obs(self):
        return {"image": self.cam.rgb(), "joints": self.cell.arm_q().astype(np.float32),
                "belt_on": np.array([1.0 if self.cell.belt_on else 0.0], dtype=np.float32)}

    def reset(self, *, seed: int | None = None, options=None):
        super().reset(seed=seed)
        self.cell = ConveyorCell(CellLayout(seed=self._seed if seed is None else seed))
        self.cam = BeltCamera(self.cell.m, self.cell.d)
        q0 = np.array([-1.23, -0.21, 0.12, 1.66, 0.0, 0.55])  # above the collection bin, clear of the camera
        self.cell.set_arm(q0, snap=True)
        self._balance = 0.0
        return self._obs(), {"balance": 0.0}

    def step(self, action):
        a = np.clip(np.asarray(action, dtype=np.float64), self.action_space.low, self.action_space.high)
        self.cell.set_arm(a[:6])
        self.cell.set_belt(bool(a[6] > 0))
        self.cell.step(self.ctrl_per_step)
        bal = self.cell.ledger.balance
        reward, self._balance = bal - self._balance, bal
        truncated = self.cell.t >= self.episode_s
        info = {"balance": bal, "t": self.cell.t, "red_in_bin": self.cell.ledger.count("bin", "red_square")}
        return self._obs(), float(reward), False, truncated, info

    def render(self):
        return self.cam.rgb() if self.render_mode == "rgb_array" else None
