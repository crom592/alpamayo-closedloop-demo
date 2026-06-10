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
