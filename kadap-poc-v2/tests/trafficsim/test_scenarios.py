from trafficsim.avlogic.rule_based import RuleBasedLogic
from trafficsim.avlogic.alpamayo_proxy import AlpamayoLogic
from trafficsim.avlogic.v2x_blind import V2XBlindLogic
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


def test_scen_02_registered():
    assert "scen_02" in SCENARIOS


def test_scen_02_has_broken_light_and_tim():
    sim = _fresh_sim()
    apply_scenario(sim, "scen_02")
    sim.tick()
    assert any(tl.broken for tl in sim.traffic_lights)
    assert any(m.kind == "TIM" for m in sim.injected_msgs)


def test_scen_03_registered():
    assert "scen_03" in SCENARIOS


def test_scen_03_has_blind_side_vehicle_in_alley():
    sim = _fresh_sim()
    apply_scenario(sim, "scen_03")
    assert len(sim.vehicles) >= 1
    v = sim.vehicles[0]
    assert v.y > 5.0


def test_all_9_combos_tick_without_error():
    """9 조합 (3 시나리오 × 3 로직)이 1 tick 동안 예외 없이 진행되는지 smoke check."""
    logics = {
        "rule_based": lambda: RuleBasedLogic(),
        "alpamayo": lambda: AlpamayoLogic(),
        "v2x_blind": lambda: V2XBlindLogic(),
    }
    scenarios = ["scen_01", "scen_02", "scen_03"]
    for scen in scenarios:
        for logic_key, make in logics.items():
            sim = Sim(SimConfig(dt=0.1), logic=make(), world=load_default_map())
            apply_scenario(sim, scen)
            for _ in range(10):
                sim.tick()
            assert sim.tick_count == 10
            assert sim.last_action is not None
            assert sim.last_reason  # non-empty
