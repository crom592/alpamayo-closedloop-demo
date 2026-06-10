"""OpenDRIVE(.xodr) loader — stdlib XML 파싱 + 기하 sampling.

OpenDRIVE 1.x 스키마에서 우리가 필요한 element만 추출:
  · <road><planView><geometry>  — polyline
  · <junction>                  — 중심 좌표
  · <object type="crosswalk">   — 횡단보도

외부 라이브러리 없이 stdlib xml.etree.ElementTree로 직접 파싱.
"""

from __future__ import annotations

import math


def _sample_line(x0: float, y0: float, hdg: float, length: float, n_pts: int = 2) -> list[tuple[float, float]]:
    return [
        (x0 + length * (i / (n_pts - 1)) * math.cos(hdg),
         y0 + length * (i / (n_pts - 1)) * math.sin(hdg))
        for i in range(n_pts)
    ]


def _sample_arc(
    x0: float, y0: float, hdg: float, length: float, curvature: float, n_pts: int = 10
) -> list[tuple[float, float]]:
    if abs(curvature) < 1e-9:
        return _sample_line(x0, y0, hdg, length, 2)
    r = 1.0 / curvature
    cx = x0 - r * math.sin(hdg)
    cy = y0 + r * math.cos(hdg)
    start_angle = math.atan2(y0 - cy, x0 - cx)
    end_angle = start_angle + curvature * length
    pts: list[tuple[float, float]] = []
    for i in range(n_pts):
        t = i / (n_pts - 1)
        a = start_angle + t * (end_angle - start_angle)
        pts.append((cx + abs(r) * math.cos(a), cy + abs(r) * math.sin(a)))
    return pts


def _sample_spiral(
    x0: float, y0: float, hdg: float, length: float,
    curv_start: float, curv_end: float, n_pts: int = 10,
) -> list[tuple[float, float]]:
    pts = [(x0, y0)]
    x, y, h = x0, y0, hdg
    n_steps = n_pts - 1
    step = length / n_steps
    for i in range(n_steps):
        s_mid = (i + 0.5) * step
        kappa = curv_start + (curv_end - curv_start) * (s_mid / length)
        h += kappa * step
        x += step * math.cos(h)
        y += step * math.sin(h)
        pts.append((x, y))
    return pts


def _sample_geometry(geom: dict) -> list[tuple[float, float]]:
    """Convert one OpenDRIVE <geometry> element dict to a polyline.

    Required keys: type ('line'/'arc'/'spiral'), x, y, hdg, length.
    arc adds 'curvature'; spiral adds 'curv_start', 'curv_end'.
    """
    gtype = geom["type"]
    if gtype == "line":
        return _sample_line(geom["x"], geom["y"], geom["hdg"], geom["length"])
    if gtype == "arc":
        return _sample_arc(geom["x"], geom["y"], geom["hdg"], geom["length"], geom["curvature"])
    if gtype == "spiral":
        return _sample_spiral(
            geom["x"], geom["y"], geom["hdg"], geom["length"],
            geom["curv_start"], geom["curv_end"],
        )
    raise ValueError(f"unknown geometry type: {gtype}")


import xml.etree.ElementTree as ET

DEFAULT_SPEED_MPS = 13.8  # ~50 km/h
_MPH_TO_MPS = 0.44704
_KMH_TO_MPS = 1.0 / 3.6


def _parse_speed_mps(road_el: ET.Element) -> float:
    """Extract max speed in m/s from <type><speed max=... unit=.../></type>. Default 13.8 m/s."""
    speed_el = road_el.find("./type/speed")
    if speed_el is None:
        return DEFAULT_SPEED_MPS
    try:
        val = float(speed_el.get("max", "0"))
    except (TypeError, ValueError):
        return DEFAULT_SPEED_MPS
    unit = (speed_el.get("unit") or "m/s").lower()
    if unit == "km/h":
        return val * _KMH_TO_MPS
    if unit == "mph":
        return val * _MPH_TO_MPS
    return val  # assume m/s


def _parse_geometry_el(geom_el: ET.Element) -> dict:
    """Convert one <geometry> element to the dict shape expected by _sample_geometry."""
    base = {
        "s": float(geom_el.get("s", "0")),
        "x": float(geom_el.get("x", "0")),
        "y": float(geom_el.get("y", "0")),
        "hdg": float(geom_el.get("hdg", "0")),
        "length": float(geom_el.get("length", "0")),
    }
    if geom_el.find("line") is not None:
        base["type"] = "line"
        return base
    arc = geom_el.find("arc")
    if arc is not None:
        base["type"] = "arc"
        base["curvature"] = float(arc.get("curvature", "0"))
        return base
    spiral = geom_el.find("spiral")
    if spiral is not None:
        base["type"] = "spiral"
        base["curv_start"] = float(spiral.get("curvStart", "0"))
        base["curv_end"] = float(spiral.get("curvEnd", "0"))
        return base
    # Unsupported (paramPoly3 etc.) — treat as line for polyline continuity
    base["type"] = "line"
    return base


def _build_road_polyline(road_el: ET.Element) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for geom_el in road_el.findall("./planView/geometry"):
        seg = _sample_geometry(_parse_geometry_el(geom_el))
        if not pts:
            pts.extend(seg)
        else:
            pts.extend(seg[1:])  # avoid duplicating shared endpoint
    return pts


def _parse_crosswalk_objects(road_el: ET.Element) -> list[dict]:
    out = []
    for obj in road_el.findall("./objects/object"):
        if (obj.get("type") or "").lower() != "crosswalk":
            continue
        out.append({
            "id": obj.get("id", ""),
            "type": "crosswalk",
            "s": float(obj.get("s", "0")),
            "t": float(obj.get("t", "0")),
            "length": float(obj.get("length", "0")),
            "width": float(obj.get("width", "0")),
            "hdg": float(obj.get("hdg", "0")),
        })
    return out


def _parse_junction_el(j_el: ET.Element) -> dict:
    connections = []
    for c in j_el.findall("./connection"):
        connections.append({
            "id": c.get("id", ""),
            "incomingRoad": c.get("incomingRoad", ""),
            "connectingRoad": c.get("connectingRoad", ""),
            "contactPoint": c.get("contactPoint", "start"),
        })
    return {"id": j_el.get("id", ""), "connections": connections}


def parse_xodr(xml_str: str) -> dict:
    """Parse OpenDRIVE XML string into our internal IR dict.

    Returns:
      {
        "roads": [
            {"id": str, "length": float, "junction": str,
             "speed_max_mps": float, "polyline": [(x, y), ...],
             "objects": [{"id": str, "type": "crosswalk",
                          "s": float, "t": float, "length": float,
                          "width": float, "hdg": float}, ...]},
            ...
        ],
        "junctions": [
            {"id": str, "connections": [
                {"id": str, "incomingRoad": str, "connectingRoad": str,
                 "contactPoint": "start"|"end"}, ...
            ]},
            ...
        ],
      }
    """
    root = ET.fromstring(xml_str)
    roads = []
    for road_el in root.findall("./road"):
        roads.append({
            "id": road_el.get("id", ""),
            "length": float(road_el.get("length", "0")),
            "junction": road_el.get("junction", "-1"),
            "speed_max_mps": _parse_speed_mps(road_el),
            "polyline": _build_road_polyline(road_el),
            "objects": _parse_crosswalk_objects(road_el),
        })
    junctions = [_parse_junction_el(j) for j in root.findall("./junction")]
    return {"roads": roads, "junctions": junctions}
