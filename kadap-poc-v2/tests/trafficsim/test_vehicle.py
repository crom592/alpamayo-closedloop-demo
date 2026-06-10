import math

from trafficsim.agents import Vehicle


def test_starts_at_first_waypoint():
    v = Vehicle(id="v1", path=[(0.0, 0.0), (100.0, 0.0)], desired_speed=10.0)
    assert math.isclose(v.x, 0.0)
    assert math.isclose(v.speed, 0.0)


def test_accelerates_toward_desired_speed_no_lead():
    v = Vehicle(id="v1", path=[(0.0, 0.0), (100.0, 0.0)], desired_speed=10.0)
    for _ in range(50):
        v.update(t=0.0, dt=0.1, lead_distance=None, lead_speed=None)
    assert v.speed > 1.0
    assert v.x > 0.0


def test_heading_along_path():
    v = Vehicle(id="v1", path=[(0.0, 0.0), (0.0, 100.0)], desired_speed=10.0)
    v.update(t=0.0, dt=0.1, lead_distance=None, lead_speed=None)
    assert math.isclose(v.heading, math.pi / 2, abs_tol=1e-6)


def test_decelerates_when_close_lead():
    v = Vehicle(id="v1", path=[(0.0, 0.0), (100.0, 0.0)], desired_speed=10.0)
    v.speed = 8.0
    a_free = v._compute_accel(lead_distance=None, lead_speed=None)
    a_close = v._compute_accel(lead_distance=5.0, lead_speed=0.0)
    assert a_close < a_free


def test_does_not_exceed_path_end():
    v = Vehicle(id="v1", path=[(0.0, 0.0), (5.0, 0.0)], desired_speed=10.0)
    v.speed = 10.0
    for _ in range(20):
        v.update(t=0.0, dt=0.1, lead_distance=None, lead_speed=None)
    assert v.x <= 5.0 + 1e-3
    assert v.finished
