from trafficsim.avlogic.interface import (
    EgoState,
    Observation,
    PerceivedObject,
    PerceptionView,
    V2XMsg,
)
from trafficsim.avlogic.v2x_blind import V2XBlindLogic


def _obs(v2x=None, perception_objs=None):
    return Observation(
        ego=EgoState(x=0.0, y=0.0, yaw=0.0, speed=8.0, accel=0.0),
        v2x_messages=v2x or [],
        perception=PerceptionView(objects=perception_objs or []),
        t=0.0,
    )


def test_ignores_v2x_messages():
    psm = V2XMsg(
        kind="PSM",
        payload={"x": 5.0, "y": 0.0, "vx": 0.0, "vy": 0.0},
        source_id="ped_1",
        rx_time=0.0,
    )
    a = V2XBlindLogic().decide(_obs(v2x=[psm]))
    assert a.target_speed >= 5.0


def test_decel_when_perceives_close_vehicle():
    a = V2XBlindLogic().decide(_obs(perception_objs=[
        PerceivedObject(obj_type="vehicle", x=8.0, y=0.0, speed=2.0)
    ]))
    assert a.target_speed < 8.0


def test_cruise_when_clear():
    a = V2XBlindLogic().decide(_obs())
    assert a.target_speed == 8.0
