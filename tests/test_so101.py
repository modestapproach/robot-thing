"""SO-101 digital twin: kinematics, physics execution, gateway gates, provenance."""
import json
import math

import numpy as np
import pytest

mujoco = pytest.importorskip("mujoco")

from evaluation.protected import non_protected_targets, protected_targets  # noqa: E402
from harness.runtime import HarnessRuntime  # noqa: E402
from robot_gateway.drivers.so101_sim import So101SimDriver  # noqa: E402
from robot_gateway.camera import MockCamera  # noqa: E402
from robot_gateway.gateway import Gateway  # noqa: E402
from shared.schemas import XY, CommandStatus, HarnessVersion, MoveRequest, TwinVersion  # noqa: E402
from simulation.so101.kinematics import So101Kinematics  # noqa: E402
from simulation.so101.sim import NOMINAL_BOARD, So101Sim  # noqa: E402
from simulation.so101.twin import So101Twin, make_twin  # noqa: E402
from simulation.twin import board_to_base  # noqa: E402
from simulation.world import make_so101_world_factory  # noqa: E402


@pytest.fixture(scope="module")
def kin():
    return So101Kinematics()


def test_ik_reaches_every_fixture_target_pointing_down(kin):
    for t in non_protected_targets() + protected_targets():
        b = board_to_base(XY(x=t["x"], y=t["y"]), NOMINAL_BOARD)
        r = kin.ik(np.array([b.x, b.y, 40.0]) / 1000)
        assert r.ok, (t, r.pos_err_mm, r.tilt_deg)
        p, a = kin.fk(r.q)
        assert np.linalg.norm(p * 1000 - [b.x, b.y, 40.0]) < 1.0 and a[2] < -0.99


def test_ik_refuses_out_of_reach(kin):
    assert not kin.ik(np.array([0.60, 0.0, 0.04])).ok


def test_physics_move_without_offsets_is_submillimetre():
    sim = So101Sim(joint_offsets_deg={})
    b = board_to_base(XY(x=100, y=75), NOMINAL_BOARD)
    r = sim.move_to(b, 40.0)
    assert np.linalg.norm(r.tool_mm[:2] - [b.x, b.y]) < 0.5
    assert r.min_tool_z_mm > 30 and len(r.trajectory["t"]) > 5


def test_servo_offsets_create_pose_dependent_error():
    sim = So101Sim(joint_offsets_deg={"shoulder_lift": 0.6, "elbow_flex": -0.5})
    misses = []
    for bx, by in [(30, 30), (170, 120)]:
        b = board_to_base(XY(x=bx, y=by), NOMINAL_BOARD)
        r = sim.move_to(b, 40.0)
        misses.append(r.tool_mm[:2] - [b.x, b.y])
    assert all(0.1 < np.linalg.norm(m) < 3 for m in misses)
    assert np.linalg.norm(misses[0] - misses[1]) > 0.05  # not a pure translation


def test_gateway_rejects_unreachable_before_motion(store):
    drv = So101SimDriver(joint_offsets_deg={})
    gw = Gateway(drv, MockCamera(NOMINAL_BOARD), "so101", store=store, physical_enabled=True)
    c = gw.submit("far", "hv", MoveRequest(target_mm=XY(x=0, y=0), height_mm=40), XY(x=275, y=135))
    assert c.status == CommandStatus.REJECTED and "unreachable" in c.rejection_reason
    assert drv.commands_executed == 0
    c2 = gw.submit("base_box", "hv", MoveRequest(target_mm=XY(x=0, y=0), height_mm=40), XY(x=40, y=0))
    assert c2.status == CommandStatus.REJECTED and "safety" in c2.rejection_reason


def test_harness_on_so101_records_trajectories_and_labels_simulation(store):
    v1 = HarnessVersion.model_validate(json.load(open("fixtures/harness_v1.json")))
    tw = TwinVersion(_id="tw", robot_id="so101", backend="mujoco", robot_model="so101", calibration_parameters=NOMINAL_BOARD)
    assert isinstance(make_twin(tw), So101Twin)
    rt = HarnessRuntime(v1, tw, make_so101_world_factory(store=store)(), store=store)
    r = rt.run("sel_01", XY(x=50, y=50))
    e = store.get("experiments", r.experiment_id)
    assert e["execution_environment"] == "simulation"
    traj_ids = [a for a in e["artifact_refs"] if a.startswith("traj")]
    assert traj_ids and store.get("sim_trajectories", traj_ids[0])["bodies"][-1] == "gripperframe"
    assert 2.0 < r.error_mm < 12.0  # mis-placed board -> clear miss before calibration


def test_so101_twin_flags_unreachable_target():
    tw = TwinVersion(_id="tw", robot_id="so101", backend="mujoco", robot_model="so101",
                     calibration_parameters=NOMINAL_BOARD.model_copy(update={"offset_mm": XY(x=240, y=100)}))
    p = So101Twin(tw).predict(XY(x=100, y=140))  # board pushed far away -> beyond reach
    assert not p.admissible and "cannot reach" in p.reason
