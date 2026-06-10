import math

from trafficsim.agents import TrafficLight


def test_starts_in_green_with_default():
    tl = TrafficLight(id="rsu_x", x=0.0, y=0.0)
    tl.update(t=0.0)
    assert tl.phase == "GREEN"


def test_phase_remaining_decreases():
    tl = TrafficLight(id="rsu_x", x=0.0, y=0.0)
    tl.update(t=0.0)
    r0 = tl.remaining_s
    tl.update(t=1.0)
    assert math.isclose(tl.remaining_s, r0 - 1.0, abs_tol=1e-6)


def test_transition_green_to_yellow_at_15s():
    tl = TrafficLight(id="rsu_x", x=0.0, y=0.0)
    tl.update(t=15.1)
    assert tl.phase == "YELLOW"


def test_transition_yellow_to_red_at_18s():
    tl = TrafficLight(id="rsu_x", x=0.0, y=0.0)
    tl.update(t=18.1)
    assert tl.phase == "RED"


def test_cycle_wraps():
    tl = TrafficLight(id="rsu_x", x=0.0, y=0.0)
    tl.update(t=33.5)
    assert tl.phase == "GREEN"


def test_offset_shifts_cycle():
    tl = TrafficLight(id="rsu_x", x=0.0, y=0.0, offset=15.0)
    tl.update(t=0.0)
    assert tl.phase == "YELLOW"


def test_broken_traffic_light_stays_dark():
    tl = TrafficLight(id="rsu_x", x=0.0, y=0.0, broken=True)
    tl.update(t=5.0)
    assert tl.phase == "OFF"
