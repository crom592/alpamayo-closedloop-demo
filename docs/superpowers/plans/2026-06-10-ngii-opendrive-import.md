# NGII OpenDRIVE Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (user chose inline) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** OpenDRIVE(.xodr) 파일을 능동 traffic sim의 `WorldMap`으로 import하는 파이프라인을 구축한다 — esmini sample로 검증, NGII 데이터 입수 후 한 줄 인자 변경으로 즉시 교체 가능.

**Architecture:** stdlib `xml.etree.ElementTree`로 OpenDRIVE XML을 파싱해 내부 IR dict 생성 → `world.load_opendrive_map(path)`이 IR을 기존 `WorldMap(Lane/Intersection/Crosswalk)`으로 변환 (origin 좌표 정규화 포함) → 기존 `Sim`/`build_plotly_figure` 그대로 사용, viewport는 lane polyline에서 동적 산정 → UI에 "맵 소스" 토글 추가.

**Tech Stack:** Python stdlib (`xml.etree.ElementTree`, `math`, `pathlib`), 기존 trafficsim 모듈 (`world.py`/`engine.py`/`main.py`), pytest, FastAPI+HTMX+Plotly.

**Spec:** [`docs/superpowers/specs/2026-06-10-ngii-opendrive-import-design.md`](../specs/2026-06-10-ngii-opendrive-import-design.md)

---

## 좌표계 (참고)

- **OpenDRIVE inertial**: x=east, y=north, m. heading(hdg)은 rad, 0=동쪽
- **우리 sim**: 동일 (Active Traffic Sim spec과 일치)
- **origin 정규화**: 로더 마지막 단계에 모든 polyline의 min(x), min(y)를 `(0,0)`으로 평행이동

## pytest 명령

전 task에서 동일:
```
/home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/pytest /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/tests/trafficsim/ -v
```

특정 파일만:
```
/home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/pytest /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/tests/trafficsim/test_opendrive_loader.py -v
```

---

## File Structure

```
kadap-poc-v2/
  trafficsim/
    opendrive_loader.py        # NEW: geometry samplers + parse_xodr
    maps/
      __init__.py              # NEW: empty package marker
      e6mini.xodr              # NEW: esmini sample fixture
      NOTICE                   # NEW: 라이선스 attribution
    world.py                   # MODIFY: load_opendrive_map(path)
    engine.py                  # MODIFY: build_plotly_figure 동적 viewport
  templates/
    tab_trafficsim.html        # MODIFY: 맵 소스 fieldset
  tests/trafficsim/
    test_opendrive_loader.py   # NEW
    test_opendrive_map.py      # NEW
    test_dynamic_viewport.py   # NEW
  main.py                      # MODIFY: MAP_SOURCES + Form 파라미터 + opendrive 분기 + _NoopLogic
```

---

## Phase 1 — Parser foundation

### Task 1: geometry samplers (line / arc / spiral)

**Files:**
- Create: `kadap-poc-v2/trafficsim/opendrive_loader.py`
- Test: `kadap-poc-v2/tests/trafficsim/test_opendrive_loader.py`

- [ ] **Step 1: Write the failing test**

`kadap-poc-v2/tests/trafficsim/test_opendrive_loader.py`:
```python
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
    # curvature=1/r, r=10, length=π/2*r=5π for quarter — use length=π*10/2
    pts = _sample_geometry({
        "type": "arc", "x": 0.0, "y": 0.0, "hdg": 0.0,
        "length": math.pi * 10 / 2, "curvature": 0.1,
    })
    # κ>0: center is to the left of heading (positive y at hdg=0)
    # start at origin facing east; quarter arc CCW → end at (10, 10)
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
    # if curv_start == curv_end the spiral degenerates to an arc
    spiral = _sample_geometry({
        "type": "spiral", "x": 0.0, "y": 0.0, "hdg": 0.0,
        "length": math.pi * 10 / 2, "curv_start": 0.1, "curv_end": 0.1,
    })
    # rough endpoint match — spiral sampler uses midpoint integration so allow 1m tolerance
    assert math.isclose(spiral[-1][0], 10.0, abs_tol=1.0)
    assert math.isclose(spiral[-1][1], 10.0, abs_tol=1.0)


def test_unknown_geometry_raises():
    import pytest as _p
    with _p.raises(ValueError):
        _sample_geometry({"type": "elliptic", "x": 0, "y": 0, "hdg": 0, "length": 1})
```

- [ ] **Step 2: Run test to verify it fails**

```
/home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/pytest /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/tests/trafficsim/test_opendrive_loader.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'trafficsim.opendrive_loader'`

- [ ] **Step 3: Write minimal implementation**

`kadap-poc-v2/trafficsim/opendrive_loader.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```
/home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/pytest /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/tests/trafficsim/test_opendrive_loader.py -v
```
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
cd /home/kadap/alpamayo-closedloop-demo
git add kadap-poc-v2/trafficsim/opendrive_loader.py \
        kadap-poc-v2/tests/trafficsim/test_opendrive_loader.py
git commit -m "feat(opendrive): add geometry samplers (line/arc/spiral)"
```

---

### Task 2: parse_xodr — roads (planView + speed)

**Files:**
- Modify: `kadap-poc-v2/trafficsim/opendrive_loader.py` (append `parse_xodr`)
- Modify: `kadap-poc-v2/tests/trafficsim/test_opendrive_loader.py` (append tests)

- [ ] **Step 1: Append failing tests**

Append to `kadap-poc-v2/tests/trafficsim/test_opendrive_loader.py`:
```python


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
    # 40 km/h ≈ 11.111 m/s
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
    # 30 mph ≈ 13.41 m/s
    assert math.isclose(ir["roads"][0]["speed_max_mps"], 30.0 * 0.44704, abs_tol=1e-3)
```

- [ ] **Step 2: Run test to verify fail**

```
/home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/pytest /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/tests/trafficsim/test_opendrive_loader.py -v
```
Expected: 5 FAIL (ImportError on parse_xodr)

- [ ] **Step 3: Append parse_xodr to opendrive_loader.py**

Append to `kadap-poc-v2/trafficsim/opendrive_loader.py`:
```python


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


def parse_xodr(xml_str: str) -> dict:
    """Parse OpenDRIVE XML string into our internal IR dict.

    Returns:
      {
        "roads": [
            {"id": str, "length": float, "junction": str,
             "speed_max_mps": float, "polyline": [(x, y), ...],
             "objects": [...]},
            ...
        ],
        "junctions": [{"id": str, "connections": [...]}, ...],
      }

    `objects` and `junctions` are populated in Task 3.
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
            "objects": [],  # Task 3
        })
    junctions = []  # Task 3
    return {"roads": roads, "junctions": junctions}
```

- [ ] **Step 4: Verify**

```
/home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/pytest /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/tests/trafficsim/test_opendrive_loader.py -v
```
Expected: 11 PASS (6 prior + 5 new)

- [ ] **Step 5: Commit**

```bash
cd /home/kadap/alpamayo-closedloop-demo
git add kadap-poc-v2/trafficsim/opendrive_loader.py \
        kadap-poc-v2/tests/trafficsim/test_opendrive_loader.py
git commit -m "feat(opendrive): parse_xodr extracts roads (planView + speed)"
```

---

### Task 3: parse_xodr — junctions + crosswalks

**Files:**
- Modify: `kadap-poc-v2/trafficsim/opendrive_loader.py`
- Modify: `kadap-poc-v2/tests/trafficsim/test_opendrive_loader.py`

- [ ] **Step 1: Append failing tests**

Append to `kadap-poc-v2/tests/trafficsim/test_opendrive_loader.py`:
```python


XODR_WITH_JUNCTION_AND_CROSSWALK = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <header revMajor="1" revMinor="6" name="" version="1.0"/>
  <road id="1" name="" length="100" junction="-1">
    <type s="0"><speed max="50" unit="km/h"/></type>
    <planView>
      <geometry s="0" x="0" y="0" hdg="0" length="100">
        <line/>
      </geometry>
    </planView>
    <lanes>
      <laneSection s="0">
        <center><lane id="0" type="none" level="false"/></center>
        <right><lane id="-1" type="driving" level="false"/></right>
      </laneSection>
    </lanes>
    <objects>
      <object id="42" type="crosswalk" s="50" t="0" length="3" width="6" hdg="0"/>
    </objects>
  </road>
  <road id="2" name="" length="100" junction="-1">
    <planView>
      <geometry s="0" x="100" y="0" hdg="0" length="100">
        <line/>
      </geometry>
    </planView>
    <lanes>
      <laneSection s="0">
        <center><lane id="0" type="none" level="false"/></center>
        <right><lane id="-1" type="driving" level="false"/></right>
      </laneSection>
    </lanes>
  </road>
  <junction id="10" name="X">
    <connection id="0" incomingRoad="1" connectingRoad="2" contactPoint="end"/>
    <connection id="1" incomingRoad="2" connectingRoad="1" contactPoint="start"/>
  </junction>
</OpenDRIVE>"""


def test_parse_xodr_junction_collected():
    from trafficsim.opendrive_loader import parse_xodr

    ir = parse_xodr(XODR_WITH_JUNCTION_AND_CROSSWALK)
    assert len(ir["junctions"]) == 1
    assert ir["junctions"][0]["id"] == "10"


def test_parse_xodr_junction_connections():
    from trafficsim.opendrive_loader import parse_xodr

    ir = parse_xodr(XODR_WITH_JUNCTION_AND_CROSSWALK)
    conns = ir["junctions"][0]["connections"]
    assert len(conns) == 2
    assert conns[0]["incomingRoad"] == "1"
    assert conns[0]["connectingRoad"] == "2"
    assert conns[0]["contactPoint"] == "end"


def test_parse_xodr_crosswalk_object_collected():
    from trafficsim.opendrive_loader import parse_xodr

    ir = parse_xodr(XODR_WITH_JUNCTION_AND_CROSSWALK)
    road = ir["roads"][0]
    objs = road["objects"]
    assert len(objs) == 1
    assert objs[0]["id"] == "42"
    assert objs[0]["type"] == "crosswalk"
    assert math.isclose(objs[0]["s"], 50.0)
    assert math.isclose(objs[0]["width"], 6.0)


def test_parse_xodr_non_crosswalk_objects_excluded():
    xml_extra = XODR_WITH_JUNCTION_AND_CROSSWALK.replace(
        '<object id="42" type="crosswalk" s="50" t="0" length="3" width="6" hdg="0"/>',
        '<object id="42" type="crosswalk" s="50" t="0" length="3" width="6" hdg="0"/>'
        '<object id="99" type="pole" s="40" t="2" length="0.3" width="0.3" hdg="0"/>',
    )
    from trafficsim.opendrive_loader import parse_xodr

    ir = parse_xodr(xml_extra)
    assert len(ir["roads"][0]["objects"]) == 1  # pole skipped
```

- [ ] **Step 2: Verify fail**

```
/home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/pytest /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/tests/trafficsim/test_opendrive_loader.py -v
```
Expected: 4 FAIL

- [ ] **Step 3: Extend parse_xodr in opendrive_loader.py**

Replace `parse_xodr` and add the helper. Open `kadap-poc-v2/trafficsim/opendrive_loader.py` and replace the existing `parse_xodr` definition with:

```python
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
```

- [ ] **Step 4: Verify**

```
/home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/pytest /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/tests/trafficsim/test_opendrive_loader.py -v
```
Expected: 15 PASS

- [ ] **Step 5: Commit**

```bash
cd /home/kadap/alpamayo-closedloop-demo
git add kadap-poc-v2/trafficsim/opendrive_loader.py \
        kadap-poc-v2/tests/trafficsim/test_opendrive_loader.py
git commit -m "feat(opendrive): parse_xodr extracts junctions and crosswalk objects"
```

---

## Phase 2 — Fixture

### Task 4: e6mini.xodr fixture + NOTICE

**Files:**
- Create: `kadap-poc-v2/trafficsim/maps/__init__.py`
- Create: `kadap-poc-v2/trafficsim/maps/e6mini.xodr`
- Create: `kadap-poc-v2/trafficsim/maps/NOTICE`

- [ ] **Step 1: Create directory + empty package marker**

```bash
mkdir -p /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/trafficsim/maps
touch /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/trafficsim/maps/__init__.py
```

- [ ] **Step 2: Fetch e6mini.xodr from esmini repo**

```bash
curl -sSfL \
  https://raw.githubusercontent.com/esmini/esmini/master/resources/xodr/e6mini.xodr \
  -o /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/trafficsim/maps/e6mini.xodr
```

Verify size > 1 KB (real file, not 404 HTML):
```bash
ls -la /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/trafficsim/maps/e6mini.xodr
```
Expected: a file ≥ 1 KB.

If 404 or fetch fails, try alternative path:
```bash
curl -sSfL \
  https://raw.githubusercontent.com/esmini/esmini/main/resources/xodr/e6mini.xodr \
  -o /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/trafficsim/maps/e6mini.xodr
```

If both fail, fall back to a hand-authored 4-way mock xodr (Step 2b below).

- [ ] **Step 2b: Fallback — hand-authored 4-way xodr**

Only run if Step 2's `curl` failed.

Write `kadap-poc-v2/trafficsim/maps/e6mini.xodr`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <header revMajor="1" revMinor="6" name="kadap-fallback" version="1.0"/>
  <road id="1" name="WE" length="200" junction="-1">
    <type s="0"><speed max="50" unit="km/h"/></type>
    <planView>
      <geometry s="0" x="-100" y="0" hdg="0" length="200"><line/></geometry>
    </planView>
    <lanes>
      <laneSection s="0">
        <center><lane id="0" type="none" level="false"/></center>
        <right><lane id="-1" type="driving" level="false"/></right>
      </laneSection>
    </lanes>
    <objects>
      <object id="100" type="crosswalk" s="100" t="0" length="3" width="6" hdg="1.5707963"/>
    </objects>
  </road>
  <road id="2" name="NS" length="200" junction="-1">
    <type s="0"><speed max="50" unit="km/h"/></type>
    <planView>
      <geometry s="0" x="0" y="-100" hdg="1.5707963" length="200"><line/></geometry>
    </planView>
    <lanes>
      <laneSection s="0">
        <center><lane id="0" type="none" level="false"/></center>
        <right><lane id="-1" type="driving" level="false"/></right>
      </laneSection>
    </lanes>
  </road>
  <junction id="10" name="X">
    <connection id="0" incomingRoad="1" connectingRoad="2" contactPoint="end"/>
  </junction>
</OpenDRIVE>
```

- [ ] **Step 3: Write NOTICE**

`kadap-poc-v2/trafficsim/maps/NOTICE`:
```
=====================================================================
Third-party OpenDRIVE map fixtures bundled in this directory.
=====================================================================

e6mini.xodr
-----------
Source: esmini project (https://github.com/esmini/esmini)
License: Mozilla Public License 2.0 (MPL-2.0)
Upstream: resources/xodr/e6mini.xodr
Use: 능동 traffic sim 프로토타입 검증용 fixture. 변형 없이 그대로 보관.

Per MPL-2.0 §3.2, source-code-equivalent (the .xodr file itself) is
distributed in this directory and any future modifications will be
released under MPL-2.0. Upstream LICENSE text is available at the
esmini repository.

If Step 2 curl failed and a fallback hand-authored xodr is used
instead, that file is © KADaP PoC and follows this repository's license.
```

If the fallback xodr was used in Step 2b, prepend a note:
```
NOTE: This bundle uses the hand-authored fallback xodr (Step 2b of plan
Task 4), not the upstream esmini sample. esmini attribution above
remains for reference but does NOT apply to the included file.
```

- [ ] **Step 4: Smoke test that the file parses**

```bash
/home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/python -c "
from pathlib import Path
import sys
sys.path.insert(0, '/home/kadap/alpamayo-closedloop-demo/kadap-poc-v2')
from trafficsim.opendrive_loader import parse_xodr
ir = parse_xodr(Path('/home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/trafficsim/maps/e6mini.xodr').read_text())
print('roads:', len(ir['roads']), 'junctions:', len(ir['junctions']))
assert len(ir['roads']) >= 1, 'expected at least 1 road'
print('OK')
"
```
Expected output ends with `OK`.

- [ ] **Step 5: Commit**

```bash
cd /home/kadap/alpamayo-closedloop-demo
git add kadap-poc-v2/trafficsim/maps/
git commit -m "feat(opendrive): bundle e6mini.xodr fixture (esmini MPL-2.0)"
```

---

## Phase 3 — WorldMap conversion

### Task 5: load_opendrive_map(path)

**Files:**
- Modify: `kadap-poc-v2/trafficsim/world.py`
- Create: `kadap-poc-v2/tests/trafficsim/test_opendrive_map.py`

- [ ] **Step 1: Write the failing test**

`kadap-poc-v2/tests/trafficsim/test_opendrive_map.py`:
```python
from pathlib import Path

from trafficsim.world import WorldMap, load_opendrive_map

E6 = Path(__file__).resolve().parents[2] / "trafficsim" / "maps" / "e6mini.xodr"


def test_load_opendrive_returns_worldmap():
    wm = load_opendrive_map(E6)
    assert isinstance(wm, WorldMap)


def test_load_opendrive_has_lanes():
    wm = load_opendrive_map(E6)
    assert len(wm.lanes) >= 1
    lane = wm.lanes[0]
    assert lane.id.startswith("road_")
    assert len(lane.polyline) >= 2


def test_load_opendrive_origin_shifted_to_nonnegative():
    wm = load_opendrive_map(E6)
    all_x = [pt[0] for lane in wm.lanes for pt in lane.polyline]
    all_y = [pt[1] for lane in wm.lanes for pt in lane.polyline]
    assert min(all_x) >= -1e-6
    assert min(all_y) >= -1e-6


def test_load_opendrive_speed_limit_positive():
    wm = load_opendrive_map(E6)
    assert all(lane.speed_limit > 0 for lane in wm.lanes)
```

- [ ] **Step 2: Verify fail**

```
/home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/pytest /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/tests/trafficsim/test_opendrive_map.py -v
```
Expected: 4 FAIL — `ImportError: cannot import name 'load_opendrive_map'`

- [ ] **Step 3: Add load_opendrive_map to world.py**

Edit `kadap-poc-v2/trafficsim/world.py`. Add these imports at the top of the file (just below the existing imports):

```python
import math
from trafficsim.opendrive_loader import parse_xodr
```

Then append the conversion function and helpers at the bottom of the file:

```python


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
    # past the end → last segment endpoint with its heading
    (x0, y0), (x1, y1) = polyline[-2], polyline[-1]
    return (x1, y1, math.atan2(y1 - y0, x1 - x0))


def _crosswalk_polyline_from_object(
    road_polyline: list[tuple[float, float]], obj: dict
) -> list[tuple[float, float]]:
    """Build a 2-point crosswalk polyline perpendicular to road tangent at s.

    The crosswalk is rendered as a single LineString across the road
    (width spans across the road centerline). Length attribute (along-road)
    is ignored in the current visual model.
    """
    x, y, hdg = _interp_along_polyline(road_polyline, obj["s"])
    # offset along t (perpendicular to road tangent, +t = left)
    t = obj["t"]
    half_w = obj["width"] / 2.0
    nx, ny = -math.sin(hdg), math.cos(hdg)  # left normal unit vector
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

    # origin shift — make all coordinates non-negative
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
```

- [ ] **Step 4: Verify**

```
/home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/pytest /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/tests/trafficsim/ -v
```
Expected: 4 new + all prior PASS. No regression on `test_world.py` (mock map untouched).

- [ ] **Step 5: Commit**

```bash
cd /home/kadap/alpamayo-closedloop-demo
git add kadap-poc-v2/trafficsim/world.py \
        kadap-poc-v2/tests/trafficsim/test_opendrive_map.py
git commit -m "feat(opendrive): add load_opendrive_map (IR → WorldMap + origin shift)"
```

---

## Phase 4 — Dynamic viewport

### Task 6: build_plotly_figure viewport from lane polylines

**Files:**
- Modify: `kadap-poc-v2/trafficsim/engine.py`
- Create: `kadap-poc-v2/tests/trafficsim/test_dynamic_viewport.py`

- [ ] **Step 1: Write the failing test**

`kadap-poc-v2/tests/trafficsim/test_dynamic_viewport.py`:
```python
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
```

- [ ] **Step 2: Verify fail**

```
/home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/pytest /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/tests/trafficsim/test_dynamic_viewport.py -v
```
Expected: 2 FAIL (the lane-bound case differs; default-fallback cases may already pass)

- [ ] **Step 3: Modify build_plotly_figure**

Open `kadap-poc-v2/trafficsim/engine.py`, find the `build_plotly_figure` function (near the bottom). Locate this layout block:

```python
    layout = {
        "xaxis": {"range": [-50, 250], "title": "x (m)", "scaleanchor": "y", "scaleratio": 1},
        "yaxis": {"range": [-30, 100], "title": "y (m)"},
        ...
    }
```

Replace it with viewport-from-lanes logic. Insert before `layout = {...}`:

```python
    # Dynamic viewport: fit lane polylines + 20m margin, fall back to mock-map defaults
    VIEWPORT_MARGIN = 20.0
    x_range = [-50, 250]
    y_range = [-30, 100]
    if sim.world and sim.world.lanes:
        all_pts = [pt for lane in sim.world.lanes for pt in lane.polyline]
        if all_pts:
            xs = [p[0] for p in all_pts]
            ys = [p[1] for p in all_pts]
            x_range = [min(xs) - VIEWPORT_MARGIN, max(xs) + VIEWPORT_MARGIN]
            y_range = [min(ys) - VIEWPORT_MARGIN, max(ys) + VIEWPORT_MARGIN]
```

And change the layout block to consume those variables:

```python
    layout = {
        "xaxis": {"range": x_range, "title": "x (m)", "scaleanchor": "y", "scaleratio": 1},
        "yaxis": {"range": y_range, "title": "y (m)"},
        "margin": {"l": 50, "r": 10, "t": 10, "b": 40},
        "showlegend": True,
        "legend": {"orientation": "h", "y": -0.15},
        "paper_bgcolor": "#222",
        "plot_bgcolor": "#1a1a1a",
        "font": {"color": "#eee"},
    }
```

- [ ] **Step 4: Verify all viewport tests + no regression**

```
/home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/pytest /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/tests/trafficsim/ -v
```
Expected: all PASS (3 new + prior unaffected — mock map uses default fallback because mock map lane polyline x range is [-100, 200], so its dynamic viewport will now be roughly `[-120, 220]` not `[-50, 250]`. That's expected; mock map will display slightly differently but correctly. No test asserts hardcoded `[-50, 250]` outside of `test_dynamic_viewport`).

- [ ] **Step 5: Commit**

```bash
cd /home/kadap/alpamayo-closedloop-demo
git add kadap-poc-v2/trafficsim/engine.py \
        kadap-poc-v2/tests/trafficsim/test_dynamic_viewport.py
git commit -m "feat(opendrive): build_plotly_figure derives viewport from lane polylines"
```

---

## Phase 5 — UI + routing

### Task 7: map source toggle + opendrive 분기 + _NoopLogic + integration

**Files:**
- Modify: `kadap-poc-v2/templates/tab_trafficsim.html`
- Modify: `kadap-poc-v2/main.py`

This task is the only UI/integration task and bundles changes that are tightly coupled (registry, form param, branch, logic, template, has_opendrive flag).

- [ ] **Step 1: Add MAP_SOURCES + _NoopLogic + has_opendrive helper in main.py**

Open `kadap-poc-v2/main.py`. After `TRAFFICSIM_LOGICS` (defined in Task 10 of the prior plan), add:

```python
TRAFFICSIM_MAP_SOURCES = [
    {"key": "mock", "name": "Mock 한국형 (기본)"},
    {"key": "opendrive_e6mini", "name": "OpenDRIVE: esmini e6mini"},
]

TRAFFICSIM_OPENDRIVE_FILES = {
    "opendrive_e6mini": Path(__file__).resolve().parent / "trafficsim" / "maps" / "e6mini.xodr",
}


def _has_opendrive(key: str) -> bool:
    p = TRAFFICSIM_OPENDRIVE_FILES.get(key)
    return bool(p and p.exists())


class _NoopLogic:
    """Logic stub used in opendrive 시각화 mode — keeps ego stationary."""

    def decide(self, obs):
        from trafficsim.avlogic.interface import Action
        return Action(target_speed=0.0, steering=0.0, reason="opendrive 시각화 모드")
```

Also add this import at the top of `main.py` (with the other `trafficsim` imports):
```python
from trafficsim.world import load_default_map, load_opendrive_map
```

(Replace the existing `from trafficsim.world import load_default_map` with the line above so both functions are imported.)

- [ ] **Step 2: Pass map_sources + opendrive availability to tab template**

Find the existing `tab_trafficsim` endpoint in `main.py`:
```python
@app.get("/tab/trafficsim", response_class=HTMLResponse)
async def tab_trafficsim(request: Request):
    return TEMPLATES.TemplateResponse(
        request,
        "tab_trafficsim.html",
        {
            "scenarios": TRAFFICSIM_SCENARIOS,
            "logics": TRAFFICSIM_LOGICS,
        },
    )
```

Replace the context dict to include map sources with per-key availability:
```python
@app.get("/tab/trafficsim", response_class=HTMLResponse)
async def tab_trafficsim(request: Request):
    map_sources = [
        {**s, "available": s["key"] == "mock" or _has_opendrive(s["key"])}
        for s in TRAFFICSIM_MAP_SOURCES
    ]
    return TEMPLATES.TemplateResponse(
        request,
        "tab_trafficsim.html",
        {
            "scenarios": TRAFFICSIM_SCENARIOS,
            "logics": TRAFFICSIM_LOGICS,
            "map_sources": map_sources,
        },
    )
```

- [ ] **Step 3: Add map source fieldset to tab_trafficsim.html**

Open `kadap-poc-v2/templates/tab_trafficsim.html`. Find the form opening + the first fieldset (scenarios). Insert a new fieldset *immediately* before the scenarios fieldset:

```html
<fieldset style="margin-bottom:1rem; padding:0.75rem;">
  <legend>맵 소스</legend>
  {% for m in map_sources %}
  <label style="margin-right:1rem;">
    <input type="radio" name="map_source" value="{{ m.key }}"
           {% if loop.first %}checked{% endif %}
           {% if not m.available %}disabled{% endif %}>
    {{ m.name }}{% if not m.available %} <span class="muted">(파일 없음)</span>{% endif %}
  </label>
  {% endfor %}
</fieldset>
```

- [ ] **Step 4: Branch in /trafficsim/start on map_source**

Find the existing `trafficsim_start` endpoint:
```python
@app.post("/trafficsim/start", response_class=HTMLResponse)
async def trafficsim_start(
    request: Request,
    scenario: str = Form(...),
    logic: str = Form(...),
):
    sim = Sim(SimConfig(dt=0.1), logic=_make_logic(logic), world=load_default_map())
    _apply_scenario(sim, scenario)
    run_id = secrets.token_urlsafe(8)
    TRAFFICSIM_RUNS[run_id] = {
        "sim": sim,
        "paused": False,
        "scenario": scenario,
        "logic": logic,
    }
    return TEMPLATES.TemplateResponse(
        request,
        "_trafficsim_frame.html",
        {
            "run_id": run_id,
            "sim": sim,
            "figure": build_plotly_figure(sim),
            "paused": False,
        },
    )
```

Replace with a version that respects `map_source`:
```python
@app.post("/trafficsim/start", response_class=HTMLResponse)
async def trafficsim_start(
    request: Request,
    scenario: str = Form(...),
    logic: str = Form(...),
    map_source: str = Form("mock"),
):
    if map_source == "mock":
        sim = Sim(SimConfig(dt=0.1), logic=_make_logic(logic), world=load_default_map())
        _apply_scenario(sim, scenario)
    else:
        xodr_path = TRAFFICSIM_OPENDRIVE_FILES.get(map_source)
        if not xodr_path or not xodr_path.exists():
            return HTMLResponse(
                f'<div class="muted">맵 소스 "{map_source}" 파일을 찾을 수 없습니다.</div>',
                status_code=200,
            )
        sim = Sim(SimConfig(dt=0.1), logic=_NoopLogic(), world=load_opendrive_map(xodr_path))
        # OpenDRIVE 모드: ego를 첫 lane 시작점으로 이동, 시나리오 setup 생략
        if sim.world.lanes and sim.world.lanes[0].polyline:
            sim.ego.x, sim.ego.y = sim.world.lanes[0].polyline[0]
    run_id = secrets.token_urlsafe(8)
    TRAFFICSIM_RUNS[run_id] = {
        "sim": sim,
        "paused": False,
        "scenario": scenario,
        "logic": logic,
        "map_source": map_source,
    }
    return TEMPLATES.TemplateResponse(
        request,
        "_trafficsim_frame.html",
        {
            "run_id": run_id,
            "sim": sim,
            "figure": build_plotly_figure(sim),
            "paused": False,
        },
    )
```

- [ ] **Step 5: Syntax check + full test suite + manual integration**

```bash
python3 -c "import ast; ast.parse(open('/home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/main.py').read())"
```
Expected: no output (syntax OK).

```
/home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/pytest /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/tests/trafficsim/ -v
```
Expected: all PASS.

Programmatic integration smoke (no browser needed):
```bash
/home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/python -c "
import sys
sys.path.insert(0, '/home/kadap/alpamayo-closedloop-demo/kadap-poc-v2')
from pathlib import Path
from trafficsim.world import load_opendrive_map
from trafficsim.engine import Sim, SimConfig, build_plotly_figure
from trafficsim.avlogic.interface import Action, Observation

class _Noop:
    def decide(self, obs): return Action(target_speed=0.0, steering=0.0, reason='noop')

wm = load_opendrive_map(Path('/home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/trafficsim/maps/e6mini.xodr'))
sim = Sim(SimConfig(), logic=_Noop(), world=wm)
fig = build_plotly_figure(sim)
print(f'lanes={len(wm.lanes)} cw={len(wm.crosswalks)} intersections={len(wm.intersections)}')
print(f'viewport x={fig[\"layout\"][\"xaxis\"][\"range\"]} y={fig[\"layout\"][\"yaxis\"][\"range\"]}')
print('OK')
"
```
Expected: prints lane/cw/intersection counts (≥1 lane), a dynamic viewport, and `OK`.

- [ ] **Step 6: Commit**

```bash
cd /home/kadap/alpamayo-closedloop-demo
git add kadap-poc-v2/main.py kadap-poc-v2/templates/tab_trafficsim.html
git commit -m "feat(opendrive): UI 맵 소스 토글 + /trafficsim/start opendrive 분기"
```

---

## Verification (전체)

- [ ] 모든 단위 + 통합 테스트 PASS
- [ ] `kadap-poc-v2/trafficsim/maps/e6mini.xodr` 존재 + NOTICE 동봉
- [ ] 브라우저에서 `🗺 능동 traffic sim` 탭 → "OpenDRIVE: esmini e6mini" 라디오 활성, 선택 후 ▶ 시작 → 한국형 mock과 다른 도로 모양이 시각화됨
- [ ] mock 라디오 선택 시 기존 9 조합 데모 회귀 없음
- [ ] 좌표 범위가 다른 맵에서도 viewport가 자동으로 맞음

---

## Out of Scope (재확인)

- OpenDRIVE `<signal>` → TrafficLight 자동 생성
- 시나리오 anchor 추상화 (mock-only scen_01/02/03을 OpenDRIVE 맵에서 자동 동작시키기)
- NGII 실제 데이터 다운로드·전처리
- 정밀 spiral sampling (Fresnel integral)
- 3D 고도 z
- multi-map registry (현재 1개 OpenDRIVE 옵션만 + mock)
