import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shared.schemas import HarnessVersion, TwinVersion  # noqa: E402
from shared.store import MemoryStore  # noqa: E402


@pytest.fixture
def store():
    return MemoryStore()


@pytest.fixture
def v1(store):
    hv = HarnessVersion.model_validate(json.loads((ROOT / "fixtures/harness_v1.json").read_text()))
    store.insert("harness_versions", hv)
    return hv


@pytest.fixture
def twin(store):
    t = TwinVersion(_id="twin_v0", robot_id="robot_sim")
    store.insert("twin_versions", t)
    return t


WORKFLOW_V2 = {
    "workflow_steps": [{"op": o} for o in ["observe", "check_board_pose", "retrieve_calibration_uncertainty", "plan_move",
                                           "simulate_if_uncertain", "execute_move", "verify", "retry_or_recover", "record"]],
    "retry_policy": {"max_retries": 1, "reobserve_before_retry": True, "replan_before_retry": True},
}
