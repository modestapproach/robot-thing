from robot_gateway.camera import MockCamera
from robot_gateway.driver import MockArmDriver
from robot_gateway.gateway import Gateway
from shared.schemas import XY, CalibrationParameters, CommandStatus, MoveRequest


def gw(store, enabled=True):
    return Gateway(MockArmDriver(latency_s=0), MockCamera(CalibrationParameters()), "r", store=store, physical_enabled=enabled)


def req(h=40.0):
    return MoveRequest(target_mm=XY(x=10, y=10), height_mm=h)


def test_duplicate_idempotency_key_does_not_move_twice(store):
    g = gw(store)
    a = g.submit("k1", "hv", req(), XY(x=10, y=10))
    b = g.submit("k1", "hv", req(), XY(x=50, y=50))
    assert a.status == CommandStatus.ACKNOWLEDGED and b.id == a.id
    assert g.driver.commands_executed == 1


def test_restarted_gateway_does_not_reexecute(store):
    g1 = gw(store)
    g1.submit("k2", "hv", req(), XY(x=10, y=10))
    g2 = gw(store)  # fresh process, same DB
    g2.submit("k2", "hv", req(), XY(x=10, y=10))
    assert g2.driver.commands_executed == 0


def test_outside_workspace_rejected(store):
    g = gw(store)
    c = g.submit("k3", "hv", req(), XY(x=9999, y=0))
    assert c.status == CommandStatus.REJECTED and "safety" in c.rejection_reason
    assert g.driver.commands_executed == 0


def test_below_min_height_rejected(store):
    c = gw(store).submit("k4", "hv", req(h=5.0), XY(x=10, y=10))
    assert c.status == CommandStatus.REJECTED


def test_estop_blocks_motion(store):
    g = gw(store)
    g.engage_estop()
    c = g.submit("k5", "hv", req(), XY(x=10, y=10))
    assert c.status == CommandStatus.REJECTED and "emergency" in c.rejection_reason


def test_physical_disabled_by_default(store):
    c = gw(store, enabled=False).submit("k6", "hv", req(), XY(x=10, y=10))
    assert c.status == CommandStatus.REJECTED


def test_speed_is_clamped_not_loosened(store):
    c = gw(store).submit("k7", "hv", MoveRequest(target_mm=XY(x=1, y=1), height_mm=40, speed_fraction=1.0), XY(x=10, y=10))
    assert c.validated_action.speed_fraction <= 0.5


def test_failed_move_is_unknown_not_success(store):
    g = gw(store)

    def boom(*a, **k):
        raise TimeoutError("encoder timeout")

    g.driver.move_to = boom
    c = g.submit("k8", "hv", req(), XY(x=10, y=10))
    assert c.status == CommandStatus.UNKNOWN
