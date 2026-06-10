import math

from trafficsim.agents import Pedestrian, TrafficLight, Vehicle
from trafficsim.avlogic.interface import EgoState, V2XMsg
from trafficsim.v2x import (
    V2X_RX_RADIUS,
    bsm_from_vehicle,
    psm_from_pedestrian,
    route_messages,
    spat_from_traffic_light,
    tim_message,
)


def test_spat_message_shape():
    tl = TrafficLight(id="rsu_main", x=0.0, y=0.0)
    tl.update(t=0.0)
    m = spat_from_traffic_light(tl, rx_time=0.0)
    assert m.kind == "SPaT"
    assert m.payload["phase"] == "GREEN"
    assert m.source_id == "rsu_main"


def test_psm_message_shape():
    p = Pedestrian(id="p1", path=[(5.0, 0.0), (5.0, 10.0)], speed=1.0)
    p.update(t=0.0, dt=0.1)
    m = psm_from_pedestrian(p, rx_time=0.0)
    assert m.kind == "PSM"
    assert math.isclose(m.payload["x"], p.x)


def test_bsm_message_shape():
    v = Vehicle(id="veh_a", path=[(0.0, 0.0), (100.0, 0.0)], desired_speed=10.0)
    v.speed = 5.0
    m = bsm_from_vehicle(v, rx_time=0.0)
    assert m.kind == "BSM"
    assert m.payload["speed"] == 5.0


def test_tim_message_shape():
    m = tim_message(
        source_id="rsu_2",
        message="DETOUR",
        severity="HIGH",
        rx_time=1.0,
    )
    assert m.kind == "TIM"
    assert m.payload["severity"] == "HIGH"


def test_router_filters_by_radius():
    ego = EgoState(x=0.0, y=0.0, yaw=0.0, speed=0.0, accel=0.0)
    near = V2XMsg(
        kind="BSM",
        payload={"x": 50.0, "y": 0.0, "speed": 5.0, "heading": 0.0},
        source_id="near",
        rx_time=0.0,
    )
    far = V2XMsg(
        kind="BSM",
        payload={"x": V2X_RX_RADIUS + 100.0, "y": 0.0, "speed": 5.0, "heading": 0.0},
        source_id="far",
        rx_time=0.0,
    )
    out = route_messages([near, far], ego)
    ids = {m.source_id for m in out}
    assert "near" in ids
    assert "far" not in ids


def test_router_passes_msgs_without_xy_field():
    ego = EgoState(x=0.0, y=0.0, yaw=0.0, speed=0.0, accel=0.0)
    tim = V2XMsg(
        kind="TIM",
        payload={"message": "DETOUR", "severity": "HIGH"},
        source_id="rsu_2",
        rx_time=0.0,
    )
    out = route_messages([tim], ego)
    assert len(out) == 1
