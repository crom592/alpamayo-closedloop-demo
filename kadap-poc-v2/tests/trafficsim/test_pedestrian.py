import math

from trafficsim.agents import Pedestrian


def test_starts_at_first_waypoint():
    p = Pedestrian(id="p1", path=[(0.0, 0.0), (10.0, 0.0)])
    assert math.isclose(p.x, 0.0)
    assert math.isclose(p.y, 0.0)


def test_moves_toward_next_waypoint():
    p = Pedestrian(id="p1", path=[(0.0, 0.0), (10.0, 0.0)], speed=1.0)
    p.update(t=0.0, dt=1.0)
    assert math.isclose(p.x, 1.0, abs_tol=1e-6)
    assert math.isclose(p.y, 0.0, abs_tol=1e-6)


def test_advances_to_next_waypoint_when_reached():
    p = Pedestrian(id="p1", path=[(0.0, 0.0), (1.0, 0.0), (1.0, 5.0)], speed=2.0)
    p.update(t=0.0, dt=1.0)
    assert math.isclose(p.x, 1.0, abs_tol=1e-6)
    assert math.isclose(p.y, 1.0, abs_tol=1e-6)


def test_stops_at_end_of_path():
    p = Pedestrian(id="p1", path=[(0.0, 0.0), (1.0, 0.0)], speed=2.0)
    p.update(t=0.0, dt=5.0)
    assert math.isclose(p.x, 1.0, abs_tol=1e-6)
    assert math.isclose(p.y, 0.0, abs_tol=1e-6)
    assert p.finished


def test_velocity_components():
    p = Pedestrian(id="p1", path=[(0.0, 0.0), (3.0, 4.0)], speed=5.0)
    p.update(t=0.0, dt=0.1)
    assert math.isclose(p.x, 0.3, abs_tol=1e-6)
    assert math.isclose(p.y, 0.4, abs_tol=1e-6)
    assert math.isclose(p.vx, 3.0, abs_tol=1e-6)
    assert math.isclose(p.vy, 4.0, abs_tol=1e-6)
