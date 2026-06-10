from trafficsim.avlogic.interface import (
    Action,
    AVLogic,
    EgoState,
    Observation,
    PerceivedObject,
    PerceptionView,
    V2XMsg,
)


def test_ego_state_construct():
    ego = EgoState(x=10.0, y=20.0, yaw=0.0, speed=8.0, accel=0.0)
    assert ego.x == 10.0
    assert ego.speed == 8.0


def test_v2x_msg_construct():
    msg = V2XMsg(
        kind="SPaT",
        payload={"phase": "GREEN", "remaining_s": 5.0},
        source_id="rsu_001",
        rx_time=1.5,
    )
    assert msg.kind == "SPaT"
    assert msg.payload["phase"] == "GREEN"


def test_perception_view_default_empty():
    pv = PerceptionView(objects=[])
    assert pv.objects == []


def test_observation_construct():
    obs = Observation(
        ego=EgoState(x=0.0, y=0.0, yaw=0.0, speed=0.0, accel=0.0),
        v2x_messages=[],
        perception=PerceptionView(objects=[]),
        t=0.0,
    )
    assert obs.t == 0.0


def test_action_construct():
    a = Action(target_speed=5.0, steering=0.1, reason="cruise")
    assert a.target_speed == 5.0
    assert a.reason == "cruise"


def test_av_logic_is_protocol():
    class _Dummy:
        def decide(self, obs: Observation) -> Action:
            return Action(target_speed=0.0, steering=0.0, reason="dummy")

    d: AVLogic = _Dummy()
    out = d.decide(
        Observation(
            ego=EgoState(0.0, 0.0, 0.0, 0.0, 0.0),
            v2x_messages=[],
            perception=PerceptionView(objects=[]),
            t=0.0,
        )
    )
    assert out.target_speed == 0.0
