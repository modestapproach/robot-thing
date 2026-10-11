"""Hardware driver interface. Implement ``ArmDriver`` once the arm is identified (PRD §6.2).

Only this file should ever import a manufacturer SDK. Everything above it talks in
F_base millimetres and never touches motors directly.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Optional

from shared.schemas import XY


class ArmDriver(ABC):
    name: str = "abstract"
    #: True only for drivers that move real hardware. Drives provenance labels (PRD §22).
    is_physical: bool = False
    #: Optional per-robot safety envelope; the gateway falls back to its default.
    envelope = None

    def can_reach(self, base_mm: XY, height_mm: float) -> tuple[bool, str]:
        """Pre-motion reachability check (IK). Default: no opinion."""
        return True, ""

    def last_trajectory(self) -> Optional[dict]:
        """Subsampled trajectory of the last move, if the driver records one (sim drivers do)."""
        return None

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def read_tool_position(self) -> tuple[XY, float]:
        """Current tool position in F_base (mm) and height (mm). Raise if unsupported."""

    @abstractmethod
    def read_joints(self) -> Optional[list[float]]: ...

    @abstractmethod
    def move_to(self, base_mm: XY, height_mm: float, speed_fraction: float, timeout_s: float) -> None:
        """Blocking Cartesian move. Must raise on failure/timeout; never return a false success."""

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def home(self) -> None: ...


class MockArmDriver(ArmDriver):
    """Kinematically perfect virtual arm with a hidden real-world miscalibration.

    The mock executes *exactly* the F_base command it is given. Observation error
    arises in the MockCamera, which converts base->board using the hidden *true*
    transform while the harness plans with the *believed* one. This mirrors the
    physical setup: the arm obeys its own frame; the camera reveals the mismatch.
    """

    name = "mock"

    def __init__(self, latency_s: float = 0.05) -> None:
        self._connected = False
        self._pos = XY(x=0.0, y=0.0)
        self._h = 120.0
        self._latency = latency_s
        self.commands_executed = 0

    def connect(self) -> None:
        self._connected = True

    def is_connected(self) -> bool:
        return self._connected

    def read_tool_position(self) -> tuple[XY, float]:
        return self._pos, self._h

    def read_joints(self) -> Optional[list[float]]:
        return None

    def move_to(self, base_mm: XY, height_mm: float, speed_fraction: float, timeout_s: float) -> None:
        if not self._connected:
            raise RuntimeError("driver not connected")
        time.sleep(self._latency / max(speed_fraction, 0.05) * 0.1)
        self._pos, self._h = base_mm, height_mm
        self.commands_executed += 1

    def stop(self) -> None:
        pass

    def home(self) -> None:
        self._pos, self._h = XY(x=0.0, y=0.0), 120.0


def load_driver(name: str) -> ArmDriver:
    if name == "mock":
        return MockArmDriver()
    if name == "so101_sim":
        from robot_gateway.drivers.so101_sim import So101SimDriver

        return So101SimDriver()
    if name == "so101":
        from robot_gateway.drivers.so101_lerobot import So101LeRobotDriver

        return So101LeRobotDriver()
    # e.g. "robot_gateway.drivers.dobot:DobotDriver"
    mod, _, cls = name.partition(":")
    import importlib

    return getattr(importlib.import_module(mod), cls)()
