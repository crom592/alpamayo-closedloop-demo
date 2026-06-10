from trafficsim.avlogic.interface import (
    EgoState,
    Observation,
    PerceivedObject,
    PerceptionView,
    V2XMsg,
)
from trafficsim.avlogic.rule_based import RuleBasedLogic


def _obs(v2x=None, perception_objs=None, t=0.0):
    return Observation(
        ego=EgoState(x=0.0, y=0.0, yaw=0.0, speed=8.0, accel=0.0),
        v2x_messages=v2x or [],
        perception=PerceptionView(objects=perception_objs or []),
        t=t,
    )


def test_cruise_when_no_messages():
    a = RuleBasedLogic().decide(_obs())
    assert a.target_speed == 8.0
    assert "cruise" in a.reason.lower()


def test_psm_pedestrian_triggers_stop():
    psm = V2XMsg(
        kind="PSM",
        payload={"x": 10.0, "y": 0.0, "vx": 0.5, "vy": 0.0},
        source_id="ped_1",
        rx_time=0.0,
    )
    a = RuleBasedLogic().decide(_obs(v2x=[psm]))
    assert a.target_speed == 0.0
    assert "보행자" in a.reason or "pedestrian" in a.reason.lower()


def test_spat_red_imminent_triggers_decel():
    spat = V2XMsg(
        kind="SPaT",
        payload={"phase": "RED", "remaining_s": 1.0},
        source_id="rsu_1",
        rx_time=0.0,
    )
    a = RuleBasedLogic().decide(_obs(v2x=[spat]))
    assert a.target_speed < 8.0
    assert "신호" in a.reason or "spat" in a.reason.lower()


def test_spat_green_does_not_decel():
    spat = V2XMsg(
        kind="SPaT",
        payload={"phase": "GREEN", "remaining_s": 5.0},
        source_id="rsu_1",
        rx_time=0.0,
    )
    a = RuleBasedLogic().decide(_obs(v2x=[spat]))
    assert a.target_speed == 8.0


def test_tim_detour_decel():
    tim = V2XMsg(
        kind="TIM",
        payload={"message": "DETOUR", "severity": "HIGH"},
        source_id="rsu_2",
        rx_time=0.0,
    )
    a = RuleBasedLogic().decide(_obs(v2x=[tim]))
    assert a.target_speed < 8.0


def test_bsm_close_lead_matches_speed():
    bsm = V2XMsg(
        kind="BSM",
        payload={"x": 5.0, "y": 0.0, "speed": 3.0, "heading": 0.0},
        source_id="veh_a",
        rx_time=0.0,
    )
    a = RuleBasedLogic().decide(_obs(v2x=[bsm]))
    assert a.target_speed <= 4.0
