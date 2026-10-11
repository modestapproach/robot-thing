"""Pydantic models for every structured AutoLab document (PRD §10).

All documents carry ``schema_version``. Numeric robotics state lives here, never
in generated-text memory (PRD §9.3).
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class XY(BaseModel):
    """A point in the calibration-board plane, millimetres."""

    x: float
    y: float

    def dist(self, other: "XY") -> float:
        return ((self.x - other.x) ** 2 + (self.y - other.y) ** 2) ** 0.5


class ExecutionEnvironment(str, Enum):
    SIMULATION = "simulation"
    REAL_HARDWARE = "real_hardware"
    REPLAY = "replay"


class VerificationStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    UNKNOWN = "unknown"  # unknown stays unknown (PRD §13.4)


class HarnessStatus(str, Enum):
    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    SIMULATED = "SIMULATED"
    ELIGIBLE_FOR_PHYSICAL_TEST = "ELIGIBLE_FOR_PHYSICAL_TEST"
    PHYSICALLY_TESTED = "PHYSICALLY_TESTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    ROLLED_BACK = "ROLLED_BACK"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    SUPERSEDED = "SUPERSEDED"


# Legal forward transitions in the mutation lifecycle (PRD §8.7).
LIFECYCLE_TRANSITIONS: dict[HarnessStatus, set[HarnessStatus]] = {
    HarnessStatus.PROPOSED: {HarnessStatus.VALIDATED, HarnessStatus.REJECTED, HarnessStatus.EXPIRED},
    HarnessStatus.VALIDATED: {HarnessStatus.SIMULATED, HarnessStatus.REJECTED, HarnessStatus.EXPIRED},
    HarnessStatus.SIMULATED: {
        HarnessStatus.ELIGIBLE_FOR_PHYSICAL_TEST,
        HarnessStatus.APPROVED,  # sim-only promotion allowed when physical evidence is not required
        HarnessStatus.REJECTED,
        HarnessStatus.NEEDS_REVIEW,
    },
    HarnessStatus.ELIGIBLE_FOR_PHYSICAL_TEST: {HarnessStatus.PHYSICALLY_TESTED, HarnessStatus.REJECTED, HarnessStatus.EXPIRED},
    HarnessStatus.PHYSICALLY_TESTED: {HarnessStatus.APPROVED, HarnessStatus.REJECTED, HarnessStatus.NEEDS_REVIEW},
    HarnessStatus.NEEDS_REVIEW: {HarnessStatus.APPROVED, HarnessStatus.REJECTED},
    HarnessStatus.APPROVED: {HarnessStatus.ACTIVE, HarnessStatus.EXPIRED},
    HarnessStatus.ACTIVE: {HarnessStatus.ROLLED_BACK, HarnessStatus.SUPERSEDED},
    HarnessStatus.ROLLED_BACK: set(),
    HarnessStatus.SUPERSEDED: {HarnessStatus.ACTIVE},  # restored by rollback
    HarnessStatus.REJECTED: set(),
    HarnessStatus.EXPIRED: set(),
}


class MutationType(str, Enum):
    PARAMETER = "parameter"
    WORKFLOW = "workflow"
    MEMORY_POLICY = "memory_policy"
    EXPERIMENT_POLICY = "experiment_policy"
    TOOL_POLICY = "tool_policy"


class Doc(BaseModel):
    schema_version: int = SCHEMA_VERSION
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------- robots / twins
class Robot(Doc):
    id: str = Field(alias="_id")
    name: str
    manufacturer: str = "unknown"
    model: str = "unknown"
    control_interface: str = "mock"
    joint_count: int = 0
    asset_uri: Optional[str] = None
    geometry_checksum: Optional[str] = None
    model_config = {"populate_by_name": True}


class CalibrationParameters(BaseModel):
    """Level-0 geometric twin parameters: board->base is a similarity transform."""

    offset_mm: XY = XY(x=0.0, y=0.0)
    rotation_deg: float = 0.0
    scale: float = 1.0
    calibration_version: str = "cal_v0"


class UncertaintyParameters(BaseModel):
    actuation_sigma_mm: float = 0.8
    observation_sigma_mm: float = 0.4


class TwinVersion(Doc):
    id: str = Field(alias="_id")
    robot_id: str
    parent_version_id: Optional[str] = None
    backend: Literal["geometric", "mujoco", "genesis"] = "geometric"
    robot_model: str = "generic"  # e.g. "so101" -> Level-1 MuJoCo twin of the SO-101
    backend_version: str = "0.1"
    calibration_parameters: CalibrationParameters = CalibrationParameters()
    uncertainty_parameters: UncertaintyParameters = UncertaintyParameters()
    source_experiment_ids: list[str] = []
    validation_summary: dict[str, Any] = {}
    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------- harness
class WorkflowStep(BaseModel):
    op: str
    params: dict[str, Any] = {}


class MemoryPolicy(BaseModel):
    retrieve_prior_failures: bool = False
    max_episodes: int = 3
    retrieve_procedures: bool = False


class RetryPolicy(BaseModel):
    max_retries: int = 1
    reobserve_before_retry: bool = False
    replan_before_retry: bool = False


class ExperimentPolicy(BaseModel):
    selection: Literal["random", "uncertainty_weighted"] = "random"
    coverage_floor: float = 0.0  # fraction of workspace cells that must stay covered
    simulation_budget: int = 50


class HarnessVersion(Doc):
    id: str = Field(alias="_id")
    version: int
    parent_version_id: Optional[str] = None
    status: HarnessStatus = HarnessStatus.PROPOSED
    workflow_steps: list[WorkflowStep]
    memory_policy: MemoryPolicy = MemoryPolicy()
    retry_policy: RetryPolicy = RetryPolicy()
    experiment_policy: ExperimentPolicy = ExperimentPolicy()
    model_config_ref: str = "default"
    created_by: str = "system"
    proposal_reason: str = ""
    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------- experiments
class Experiment(Doc):
    id: str = Field(alias="_id")
    campaign_id: Optional[str] = None
    scenario_id: str
    harness_version_id: str
    twin_version_id: str
    candidate_id: Optional[str] = None
    random_seed: int = 0
    target_position_mm: XY
    predicted_position_mm: Optional[XY] = None
    observed_position_mm: Optional[XY] = None
    position_error_mm: Optional[float] = None
    error_xy_mm: Optional[XY] = None
    execution_environment: ExecutionEnvironment
    verification_status: VerificationStatus = VerificationStatus.PENDING
    started_at: datetime = Field(default_factory=utcnow)
    completed_at: Optional[datetime] = None
    trace_id: Optional[str] = None
    artifact_refs: list[str] = []
    retries: int = 0
    observations: int = 0
    movements: int = 0
    board_moved_detected: bool = False
    first_attempt_error_mm: Optional[float] = None
    rejection_reason: Optional[str] = None
    finalized: bool = False  # append-only once finalized (PRD §13.4)
    model_config = {"populate_by_name": True}


class CampaignStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class ExperimentCampaign(Doc):
    id: str = Field(alias="_id")
    objective: str
    baseline_version_id: str
    candidate_ids: list[str] = []
    scenario_set_id: str
    status: CampaignStatus = CampaignStatus.CREATED
    completed_trial_ids: list[str] = []
    pending_trial_ids: list[str] = []
    budget: dict[str, Any] = {}
    checkpoint: dict[str, Any] = {}
    updated_at: datetime = Field(default_factory=utcnow)
    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------- hardware
class CommandStatus(str, Enum):
    REQUESTED = "requested"
    VALIDATED = "validated"
    REJECTED = "rejected"
    EXECUTING = "executing"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"
    UNKNOWN = "unknown"


class MoveRequest(BaseModel):
    target_mm: XY
    height_mm: float
    speed_fraction: float = Field(0.3, gt=0.0, le=1.0)


class HardwareCommand(Doc):
    id: str = Field(alias="_id")
    idempotency_key: str
    robot_id: str
    harness_version_id: str
    requested_action: MoveRequest
    validated_action: Optional[MoveRequest] = None
    controller_state_before: dict[str, Any] = {}
    controller_state_after: dict[str, Any] = {}
    status: CommandStatus = CommandStatus.REQUESTED
    rejection_reason: Optional[str] = None
    issued_at: datetime = Field(default_factory=utcnow)
    acknowledged_at: Optional[datetime] = None
    result_ref: Optional[str] = None
    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------- mutations / evaluation
class RiskClassification(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MutationProposal(Doc):
    id: str = Field(alias="_id")
    base_harness_version: str
    candidate_harness_version: str
    mutation_type: MutationType
    patch: dict[str, Any]
    hypothesis: str
    expected_improvement: str
    risk_classification: RiskClassification = RiskClassification.LOW
    evaluation_campaign_id: Optional[str] = None
    status: HarnessStatus = HarnessStatus.PROPOSED
    decision_reason: Optional[str] = None
    model_config = {"populate_by_name": True}


class Decision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    NEEDS_REVIEW = "needs_review"


class EvaluationResult(Doc):
    id: str = Field(alias="_id")
    candidate_version_id: str
    baseline_version_id: str
    protected_test_set_version: str
    simulation_metrics: dict[str, Any] = {}
    physical_metrics: dict[str, Any] = {}
    cost_metrics: dict[str, Any] = {}
    safety_invariants: dict[str, bool] = {}
    protected_tests: dict[str, bool] = {}
    decision: Decision
    reasons: list[str] = []
    evaluated_at: datetime = Field(default_factory=utcnow)
    model_config = {"populate_by_name": True}


class Observation(BaseModel):
    """One camera observation converted to board frame."""

    board_detected: bool
    board_moved: bool = False
    end_effector_mm: Optional[XY] = None
    confidence: float = 0.0
    image_ref: Optional[str] = None
    timestamp: datetime = Field(default_factory=utcnow)


class RobotState(BaseModel):
    connected: bool
    physical_enabled: bool
    estop_engaged: bool
    busy: bool
    joint_positions: Optional[list[float]] = None
    tool_mm: Optional[XY] = None
    tool_height_mm: Optional[float] = None
    last_command_id: Optional[str] = None
