import pytest

from harness.mutate import derive_candidate
from harness.validate import HarnessValidationError, validate_harness, validate_permissions
from shared.schemas import MutationType

from conftest import WORKFLOW_V2


def test_unsupported_operation_rejected(v1):
    doc = v1.model_dump(by_alias=True)
    doc["workflow_steps"].insert(1, {"op": "disable_estop"})
    with pytest.raises(HarnessValidationError, match="unsupported"):
        validate_harness(doc)


def test_two_physical_ops_rejected(v1):
    doc = v1.model_dump(by_alias=True)
    doc["workflow_steps"].insert(3, {"op": "execute_move"})
    with pytest.raises(HarnessValidationError, match="at most one physical"):
        validate_harness(doc)


def test_required_order_enforced(v1):
    doc = v1.model_dump(by_alias=True)
    doc["workflow_steps"] = [{"op": o} for o in ["observe", "execute_move", "plan_move", "verify", "record"]]
    with pytest.raises(HarnessValidationError):
        validate_harness(doc)


def test_parameter_mutation_cannot_touch_workflow():
    with pytest.raises(HarnessValidationError):
        validate_permissions(MutationType.PARAMETER, {"workflow_steps": []})


def test_protected_fields_rejected():
    with pytest.raises(HarnessValidationError, match="protected"):
        validate_permissions(MutationType.WORKFLOW, {"status": "ACTIVE"})


def test_candidate_is_new_version_and_base_unchanged(v1):
    before = v1.model_dump(by_alias=True)
    cand = derive_candidate(v1, MutationType.WORKFLOW, WORKFLOW_V2, "test")
    assert cand.version == v1.version + 1 and cand.parent_version_id == v1.id and cand.id != v1.id
    assert cand.status.value == "PROPOSED"
    assert v1.model_dump(by_alias=True) == before
