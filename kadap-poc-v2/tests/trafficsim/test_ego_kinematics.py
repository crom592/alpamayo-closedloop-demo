import math

from trafficsim.agents import TrafficLight, Vehicle
from trafficsim.avlogic.interface import Action, Observation
from trafficsim.engine import Sim, SimConfig
from trafficsim.world import load_default_map


class _ConstAction:
    def __init__(self, action: Action) -> None:
        self.action = action

    def decide(self, obs: Observation) -> Action:
        return self.action


def test_ego_accelerates_toward_target_speed():
    sim = Sim(
        SimConfig(dt=0.1),
        logic=_ConstAction(Action(target_speed=5.0, steering=0.0, reason="go")),
        world=load_default_map(),
    )
    for _ in range(30):
        sim.tick()
    assert sim.ego.speed > 1.0
    assert sim.ego.x > 0.0


def test_ego_stops_when_target_zero():
    sim = Sim(
        SimConfig(dt=0.1),
        logic=_ConstAction(Action(target_speed=0.0, steering=0.0, reason="stop")),
        world=load_default_map(),
    )
    sim.ego.speed = 5.0
    for _ in range(30):
        sim.tick()
    assert sim.ego.speed < 0.5


def test_ego_steering_changes_yaw():
    sim = Sim(
        SimConfig(dt=0.1),
        logic=_ConstAction(Action(target_speed=5.0, steering=0.1, reason="turn")),
        world=load_default_map(),
    )
    sim.ego.speed = 5.0
    yaw0 = sim.ego.yaw
    for _ in range(10):
        sim.tick()
    assert not math.isclose(sim.ego.yaw, yaw0, abs_tol=1e-3)


def test_sim_collects_spat_messages():
    captured: list = []

    class _Cap:
        def decide(self, obs: Observation) -> Action:
            captured.append(list(obs.v2x_messages))
            return Action(target_speed=0.0, steering=0.0, reason="cap")

    world = load_default_map()
    sim = Sim(SimConfig(dt=0.1), logic=_Cap(), world=world)
    sim.add_traffic_light(TrafficLight(id="rsu_main", x=0.0, y=0.0))
    sim.tick()
    assert captured[0], "should receive SPaT in first tick"
    kinds = {m.kind for m in captured[0]}
    assert "SPaT" in kinds


def test_sim_perception_picks_up_nearby_vehicle():
    captured: list = []

    class _Cap:
        def decide(self, obs: Observation) -> Action:
            captured.append(obs.perception.objects)
            return Action(target_speed=0.0, steering=0.0, reason="cap")

    sim = Sim(SimConfig(dt=0.1), logic=_Cap(), world=load_default_map())
    sim.add_vehicle(Vehicle(id="v_a", path=[(20.0, 0.0), (200.0, 0.0)]))
    sim.tick()
    assert any(o.obj_type == "vehicle" for o in captured[0])
