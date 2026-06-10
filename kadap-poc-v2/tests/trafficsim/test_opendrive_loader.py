import math

from trafficsim.opendrive_loader import _sample_geometry


def test_line_two_endpoints():
    pts = _sample_geometry({"type": "line", "x": 0.0, "y": 0.0, "hdg": 0.0, "length": 10.0})
    assert len(pts) == 2
    assert math.isclose(pts[0][0], 0.0)
    assert math.isclose(pts[0][1], 0.0)
    assert math.isclose(pts[1][0], 10.0, abs_tol=1e-6)
    assert math.isclose(pts[1][1], 0.0, abs_tol=1e-6)


def test_line_with_heading():
    pts = _sample_geometry({
        "type": "line", "x": 0.0, "y": 0.0,
        "hdg": math.pi / 2, "length": 5.0,
    })
    assert math.isclose(pts[1][0], 0.0, abs_tol=1e-6)
    assert math.isclose(pts[1][1], 5.0, abs_tol=1e-6)


def test_arc_quarter_circle_ccw():
    pts = _sample_geometry({
        "type": "arc", "x": 0.0, "y": 0.0, "hdg": 0.0,
        "length": math.pi * 10 / 2, "curvature": 0.1,
    })
    assert len(pts) == 10
    assert math.isclose(pts[0][0], 0.0, abs_tol=1e-6)
    assert math.isclose(pts[0][1], 0.0, abs_tol=1e-6)
    assert math.isclose(pts[-1][0], 10.0, abs_tol=1e-3)
    assert math.isclose(pts[-1][1], 10.0, abs_tol=1e-3)


def test_arc_zero_curvature_falls_back_to_line():
    pts = _sample_geometry({
        "type": "arc", "x": 0.0, "y": 0.0, "hdg": 0.0,
        "length": 10.0, "curvature": 0.0,
    })
    assert len(pts) == 2
    assert math.isclose(pts[-1][0], 10.0, abs_tol=1e-6)


def test_spiral_constant_curvature_matches_arc():
    spiral = _sample_geometry({
        "type": "spiral", "x": 0.0, "y": 0.0, "hdg": 0.0,
        "length": math.pi * 10 / 2, "curv_start": 0.1, "curv_end": 0.1,
    })
    assert math.isclose(spiral[-1][0], 10.0, abs_tol=1.0)
    assert math.isclose(spiral[-1][1], 10.0, abs_tol=1.0)


def test_unknown_geometry_raises():
    import pytest as _p
    with _p.raises(ValueError):
        _sample_geometry({"type": "elliptic", "x": 0, "y": 0, "hdg": 0, "length": 1})
