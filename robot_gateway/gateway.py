"""Robot gateway core: the only path to motors (PRD §6.6, §10.6).

Guarantees: idempotency-key dedupe before any motion, one in-flight command,
safety validation independent of harness documents, state revalidation, and a
hard ``physical_enabled`` switch that defaults OFF.
"""
from __future__ import annotations

import threading
from typing import Optional

from robot_gateway.camera import Camera
from robot_gateway.driver import ArmDriver
from robot_gateway.safety import DEFAULT_ENVELOPE, SafetyEnvelope, SafetyViolation, validate_move
from shared.ids import new_id
from shared.schemas import XY, CommandStatus, HardwareCommand, MoveRequest, Observation, RobotState, utcnow
from shared.store import DuplicateKeyError, Store, get_store


class Gateway:
    def __init__(
        self,
        driver: ArmDriver,
        camera: Camera,
        robot_id: str,
        store: Store | None = None,
        envelope: SafetyEnvelope | None = None,
        physical_enabled: bool = False,
    ) -> None:
        self.driver = driver
        self.camera = camera
        self.robot_id = robot_id
        self.store = store or get_store()
        self.env = envelope or getattr(driver, "envelope", None) or DEFAULT_ENVELOPE
        self.physical_enabled = physical_enabled
        self.estop = False
        self._lock = threading.Lock()
        self._busy = False
        self._last_command_id: Optional[str] = None
        self.driver.connect()

    # ------------------------------------------------------------ state
    def state(self) -> RobotState:
        try:
            pos, h = self.driver.read_tool_position()
        except Exception:
            pos, h = None, None
        return RobotState(
            connected=self.driver.is_connected(),
            physical_enabled=self.physical_enabled,
            estop_engaged=self.estop,
            busy=self._busy,
            joint_positions=self.driver.read_joints(),
            tool_mm=pos,
            tool_height_mm=h,
            last_command_id=self._last_command_id,
        )

    def observe(self) -> Observation:
        try:
            pos, _ = self.driver.read_tool_position()
        except Exception:
            pos = None
        return self.camera.observe(pos)

    def engage_estop(self) -> None:
        self.estop = True
        self.driver.stop()

    def release_estop(self) -> None:
        """Operator-only. Never callable from an agent tool."""
        self.estop = False

    # ------------------------------------------------------------ commands
    def submit(self, idempotency_key: str, harness_version_id: str, req: MoveRequest, base_target: XY) -> HardwareCommand:
        """Validate and execute one bounded move. Duplicate keys return the original record."""
        existing = self.store.find("hardware_commands", {"idempotency_key": idempotency_key}, limit=1)
        if existing:
            return HardwareCommand.model_validate(existing[0])

        cmd = HardwareCommand(
            _id=new_id("cmd"),
            idempotency_key=idempotency_key,
            robot_id=self.robot_id,
            harness_version_id=harness_version_id,
            requested_action=req,
            controller_state_before=self.state().model_dump(),
        )
        try:
            self.store.insert("hardware_commands", cmd)
        except DuplicateKeyError:
            return HardwareCommand.model_validate(self.store.find("hardware_commands", {"idempotency_key": idempotency_key})[0])

        def _reject(reason: str) -> HardwareCommand:
            self.store.update("hardware_commands", cmd.id, {"status": CommandStatus.REJECTED.value, "rejection_reason": reason})
            self.store.audit("command_rejected", command_id=cmd.id, reason=reason)
            return cmd.model_copy(update={"status": CommandStatus.REJECTED, "rejection_reason": reason})

        if self.estop:
            return _reject("emergency stop engaged")
        if not self.physical_enabled:
            return _reject("physical execution disabled (ROBOT_PHYSICAL_ENABLE=0)")
        if not self._lock.acquire(blocking=False):
            return _reject("another command is in flight")
        try:
            self._busy = True
            cur = self.state()
            if not cur.connected:
                return _reject("robot disconnected")
            try:
                validated = validate_move(req, base_target, cur.tool_mm, self.env)
            except SafetyViolation as e:
                return _reject(f"safety: {e}")
            reachable, why = self.driver.can_reach(base_target, validated.height_mm)
            if not reachable:
                return _reject(f"unreachable: {why}")
            self.store.update("hardware_commands", cmd.id, {"status": CommandStatus.VALIDATED.value, "validated_action": validated.model_dump()})
            self.store.update("hardware_commands", cmd.id, {"status": CommandStatus.EXECUTING.value})
            try:
                self.driver.move_to(base_target, validated.height_mm, validated.speed_fraction, self.env.command_timeout_s)
            except Exception as e:
                # Motion outcome genuinely unknown after an exception mid-move.
                self.store.update("hardware_commands", cmd.id, {"status": CommandStatus.UNKNOWN.value, "rejection_reason": f"driver error: {e}"})
                self.store.audit("command_unknown", command_id=cmd.id, error=str(e))
                return cmd.model_copy(update={"status": CommandStatus.UNKNOWN, "rejection_reason": str(e)})
            after = self.state().model_dump()
            self._last_command_id = cmd.id
            traj = self.driver.last_trajectory()
            result_ref = None
            if traj:
                result_ref = new_id("traj")
                self.store.insert("sim_trajectories", {"_id": result_ref, "command_id": cmd.id, "robot_id": self.robot_id,
                                                       "harness_version_id": harness_version_id, "driver": self.driver.name,
                                                       "environment": "real_hardware" if self.driver.is_physical else "simulation",
                                                       "target_base_mm": base_target.model_dump(), "height_mm": validated.height_mm,
                                                       "created_at": utcnow(), **traj})
            self.store.update(
                "hardware_commands",
                cmd.id,
                {"status": CommandStatus.ACKNOWLEDGED.value, "acknowledged_at": utcnow(), "controller_state_after": after,
                 "validated_action": validated.model_dump(), "result_ref": result_ref},
            )
            return cmd.model_copy(update={"status": CommandStatus.ACKNOWLEDGED, "validated_action": validated, "controller_state_after": after, "result_ref": result_ref})
        finally:
            self._busy = False
            self._lock.release()
