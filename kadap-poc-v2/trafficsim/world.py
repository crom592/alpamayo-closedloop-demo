"""WorldMap — GeoJSON으로 정의한 한국형 mock 도로."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

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
