import math

from trafficsim.avlogic.interface import Action, AVLogic, Observation
from trafficsim.engine import Sim, SimConfig


class _Noop:
    def decide(self, obs: Observation) -> Action:
        return Action(target_speed=0.0, steering=0.0, reason="noop")


def test_sim_starts_at_t_zero():
    sim = Sim(SimConfig(), logic=_Noop())
    assert sim.t == 0.0
    assert sim.tick_count == 0


def test_sim_tick_advances_time():
    sim = Sim(SimConfig(dt=0.1), logic=_Noop())
    sim.tick()
    assert math.isclose(sim.t, 0.1, abs_tol=1e-9)
    assert sim.tick_count == 1


def test_sim_tick_ten_times_reaches_one_second():
    sim = Sim(SimConfig(dt=0.1), logic=_Noop())
    for _ in range(10):
        sim.tick()
    assert math.isclose(sim.t, 1.0, abs_tol=1e-9)


def test_sim_invokes_logic_each_tick():
    calls = []

    class _Counter:
        def decide(self, obs: Observation) -> Action:
            calls.append(obs.t)
            return Action(target_speed=0.0, steering=0.0, reason="counter")

    sim = Sim(SimConfig(dt=0.1), logic=_Counter())
    for _ in range(3):
        sim.tick()
    assert len(calls) == 3
    assert math.isclose(calls[0], 0.0, abs_tol=1e-9)
    assert math.isclose(calls[2], 0.2, abs_tol=1e-9)
