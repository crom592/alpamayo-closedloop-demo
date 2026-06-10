"""WorldMap — GeoJSON으로 정의한 한국형 mock 도로."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from trafficsim.opendrive_loader import parse_xodr

MAP_PATH = Path(__file__).resolve().parent / "map.geojson"


@dataclass
class Lane:
    id: str
    polyline: list[tuple[float, float]]
    speed_limit: float = 13.8


@dataclass
class Intersection:
    id: str
    x: float
    y: float


@dataclass
class Crosswalk:
    id: str
    polyline: list[tuple[float, float]]
    axis: str = "y"


@dataclass
class WorldMap:
    lanes: list[Lane] = field(default_factory=list)
    intersections: list[Intersection] = field(default_factory=list)
    crosswalks: list[Crosswalk] = field(default_factory=list)


def load_default_map(path: Path | None = None) -> WorldMap:
    p = path or MAP_PATH
    data = json.loads(p.read_text())
    wm = WorldMap()
    for feat in data["features"]:
        props = feat["properties"]
        kind = props["kind"]
        geom = feat["geometry"]
        if kind == "lane":
            coords = [(float(x), float(y)) for x, y in geom["coordinates"]]
            wm.lanes.append(
                Lane(
                    id=props["id"],
                    polyline=coords,
                    speed_limit=float(props.get("speed_limit", 13.8)),
                )
            )
        elif kind == "intersection":
            x, y = geom["coordinates"]
            wm.intersections.append(Intersection(id=props["id"], x=float(x), y=float(y)))
        elif kind == "crosswalk":
            coords = [(float(x), float(y)) for x, y in geom["coordinates"]]
            wm.crosswalks.append(
                Crosswalk(
                    id=props["id"],
                    polyline=coords,
                    axis=str(props.get("axis", "y")),
                )
            )
    return wm


def _interp_along_polyline(polyline: list[tuple[float, float]], s: float) -> tuple[float, float, float]:
    """Walk polyline by arc length and return (x, y, heading_rad) at s."""
    if len(polyline) < 2:
        x, y = polyline[0] if polyline else (0.0, 0.0)
        return x, y, 0.0
    remaining = max(s, 0.0)
    for (x0, y0), (x1, y1) in zip(polyline, polyline[1:]):
        dx, dy = x1 - x0, y1 - y0
        seg_len = math.hypot(dx, dy)
        if seg_len < 1e-9:
            continue
        if remaining <= seg_len:
            t = remaining / seg_len
            return (x0 + t * dx, y0 + t * dy, math.atan2(dy, dx))
        remaining -= seg_len
    (x0, y0), (x1, y1) = polyline[-2], polyline[-1]
    return (x1, y1, math.atan2(y1 - y0, x1 - x0))


def _crosswalk_polyline_from_object(
    road_polyline: list[tuple[float, float]], obj: dict
) -> list[tuple[float, float]]:
    """Build a 2-point crosswalk polyline perpendicular to road tangent at s."""
    x, y, hdg = _interp_along_polyline(road_polyline, obj["s"])
    t = obj["t"]
    half_w = obj["width"] / 2.0
    nx, ny = -math.sin(hdg), math.cos(hdg)
    center_x = x + t * nx
    center_y = y + t * ny
    return [
        (center_x - half_w * nx, center_y - half_w * ny),
        (center_x + half_w * nx, center_y + half_w * ny),
    ]


def _junction_center(ir: dict, junction: dict) -> tuple[float, float] | None:
    """Compute centroid of a junction from connecting roads' polyline endpoints."""
    road_map = {r["id"]: r for r in ir["roads"]}
    xs, ys = [], []
    for conn in junction["connections"]:
        for road_id in (conn["incomingRoad"], conn["connectingRoad"]):
            road = road_map.get(road_id)
            if not road or not road["polyline"]:
                continue
            cp = conn.get("contactPoint", "start")
            pt = road["polyline"][-1] if cp == "end" else road["polyline"][0]
            xs.append(pt[0])
            ys.append(pt[1])
    if not xs:
        return None
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def load_opendrive_map(path) -> WorldMap:
    """Load an OpenDRIVE .xodr file into our WorldMap dataclass.

    Origin is shifted so that min(x), min(y) across all lane polylines become
    (0, 0) — keeps Plotly viewport math simple and comparable across maps.
    """
    p = Path(path)
    ir = parse_xodr(p.read_text(encoding="utf-8"))

    lanes: list[Lane] = []
    crosswalks: list[Crosswalk] = []
    intersections: list[Intersection] = []

    for road in ir["roads"]:
        if not road["polyline"]:
            continue
        lanes.append(
            Lane(
                id=f"road_{road['id']}",
                polyline=list(road["polyline"]),
                speed_limit=road["speed_max_mps"],
            )
        )
        for obj in road["objects"]:
            if obj["type"] != "crosswalk":
                continue
            cw_poly = _crosswalk_polyline_from_object(road["polyline"], obj)
            crosswalks.append(Crosswalk(id=f"cw_{obj['id']}", polyline=cw_poly, axis="y"))

    for junction in ir["junctions"]:
        ctr = _junction_center(ir, junction)
        if ctr is None:
            continue
        intersections.append(Intersection(id=f"j_{junction['id']}", x=ctr[0], y=ctr[1]))

    all_pts = [pt for lane in lanes for pt in lane.polyline]
    if all_pts:
        dx = -min(p[0] for p in all_pts)
        dy = -min(p[1] for p in all_pts)
        if dx != 0 or dy != 0:
            for lane in lanes:
                lane.polyline = [(x + dx, y + dy) for x, y in lane.polyline]
            for cw in crosswalks:
                cw.polyline = [(x + dx, y + dy) for x, y in cw.polyline]
            intersections = [
                Intersection(id=i.id, x=i.x + dx, y=i.y + dy) for i in intersections
            ]

    return WorldMap(lanes=lanes, intersections=intersections, crosswalks=crosswalks)
