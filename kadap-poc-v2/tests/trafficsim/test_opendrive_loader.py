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


MINIMAL_XODR = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <header revMajor="1" revMinor="6" name="" version="1.0"/>
  <road id="1" name="" length="50" junction="-1">
    <type s="0"><speed max="40" unit="km/h"/></type>
    <planView>
      <geometry s="0" x="0" y="0" hdg="0" length="50">
        <line/>
      </geometry>
    </planView>
    <lanes>
      <laneSection s="0">
        <center><lane id="0" type="none" level="false"/></center>
        <right>
          <lane id="-1" type="driving" level="false"/>
        </right>
      </laneSection>
    </lanes>
  </road>
</OpenDRIVE>"""


def test_parse_xodr_extracts_one_road():
    from trafficsim.opendrive_loader import parse_xodr

    ir = parse_xodr(MINIMAL_XODR)
    assert len(ir["roads"]) == 1
    r = ir["roads"][0]
    assert r["id"] == "1"
    assert math.isclose(r["length"], 50.0)


def test_parse_xodr_road_polyline_from_line_geometry():
    from trafficsim.opendrive_loader import parse_xodr

    ir = parse_xodr(MINIMAL_XODR)
    r = ir["roads"][0]
    assert len(r["polyline"]) >= 2
    assert math.isclose(r["polyline"][0][0], 0.0)
    assert math.isclose(r["polyline"][-1][0], 50.0, abs_tol=1e-6)


def test_parse_xodr_road_speed_km_to_ms():
    from trafficsim.opendrive_loader import parse_xodr

    ir = parse_xodr(MINIMAL_XODR)
    assert math.isclose(ir["roads"][0]["speed_max_mps"], 40.0 / 3.6, abs_tol=1e-3)


def test_parse_xodr_default_speed_when_no_type():
    xml_no_type = MINIMAL_XODR.replace('<type s="0"><speed max="40" unit="km/h"/></type>', "")
    from trafficsim.opendrive_loader import parse_xodr

    ir = parse_xodr(xml_no_type)
    assert math.isclose(ir["roads"][0]["speed_max_mps"], 13.8, abs_tol=0.1)


def test_parse_xodr_road_speed_mph_to_ms():
    xml_mph = MINIMAL_XODR.replace('unit="km/h"', 'unit="mph"').replace('max="40"', 'max="30"')
    from trafficsim.opendrive_loader import parse_xodr

    ir = parse_xodr(xml_mph)
    assert math.isclose(ir["roads"][0]["speed_max_mps"], 30.0 * 0.44704, abs_tol=1e-3)
