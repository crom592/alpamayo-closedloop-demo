from trafficsim.avlogic.interface import Action, Observation
from trafficsim.engine import Sim, SimConfig, build_plotly_figure
from trafficsim.world import Lane, WorldMap


class _Noop:
    def decide(self, obs: Observation) -> Action:
        return Action(target_speed=0.0, steering=0.0, reason="noop")


def _wm_with_lane(polyline):
    return WorldMap(lanes=[Lane(id="L", polyline=polyline, speed_limit=10.0)])


def test_viewport_uses_lane_bounds_when_world_has_lanes():
    sim = Sim(SimConfig(), logic=_Noop(), world=_wm_with_lane([(50.0, 50.0), (150.0, 80.0)]))
    fig = build_plotly_figure(sim)
    x_range = fig["layout"]["xaxis"]["range"]
    y_range = fig["layout"]["yaxis"]["range"]
    assert x_range[0] == 50.0 - 20.0
    assert x_range[1] == 150.0 + 20.0
    assert y_range[0] == 50.0 - 20.0
    assert y_range[1] == 80.0 + 20.0


def test_viewport_falls_back_to_default_when_no_lanes():
    sim = Sim(SimConfig(), logic=_Noop(), world=WorldMap())
    fig = build_plotly_figure(sim)
    assert fig["layout"]["xaxis"]["range"] == [-50, 250]
    assert fig["layout"]["yaxis"]["range"] == [-30, 100]


def test_viewport_falls_back_when_world_is_none():
    sim = Sim(SimConfig(), logic=_Noop(), world=None)
    fig = build_plotly_figure(sim)
    assert fig["layout"]["xaxis"]["range"] == [-50, 250]
    assert fig["layout"]["yaxis"]["range"] == [-30, 100]
