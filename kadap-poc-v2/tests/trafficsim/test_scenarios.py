from trafficsim.avlogic.rule_based import RuleBasedLogic
from trafficsim.engine import Sim, SimConfig
from trafficsim.scenarios.base import SCENARIOS, apply_scenario
from trafficsim.world import load_default_map


def _fresh_sim():
    return Sim(SimConfig(dt=0.1), logic=RuleBasedLogic(), world=load_default_map())


def test_scen_01_registered():
    assert "scen_01" in SCENARIOS


def test_scen_01_places_pedestrian_and_traffic_light():
    sim = _fresh_sim()
    apply_scenario(sim, "scen_01")
    assert len(sim.traffic_lights) >= 1
    assert len(sim.pedestrians) >= 1


def test_scen_01_ego_starts_west_of_main_intersection():
    sim = _fresh_sim()
    apply_scenario(sim, "scen_01")
    assert sim.ego.x < 0
    assert abs(sim.ego.y) < 5.0


def test_scen_01_traffic_light_starts_green_with_5s_remaining():
    sim = _fresh_sim()
    apply_scenario(sim, "scen_01")
    # Need to call tl.update once to apply offset
    sim.traffic_lights[0].update(t=0.0)
    assert sim.traffic_lights[0].phase == "GREEN"
    assert abs(sim.traffic_lights[0].remaining_s - 5.0) < 0.01
