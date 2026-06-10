# 능동 Traffic Sim 데모 탭 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** V2X-aware traffic simulation 환경과 swappable AVLogic 인터페이스를 제공하는 새 데모 탭("🗺 능동 traffic sim")을 kadap-poc-v2 FastAPI 앱에 추가한다. 평가위원이 토글로 시나리오·로직 조합 9개를 직접 비교할 수 있어야 한다.

**Architecture:** asyncio tick 엔진(10Hz)이 sim state(자차·신호등·보행자·주변차·V2X 큐)를 갱신하고, 매 tick `AVLogic.decide(Observation) → Action` 인터페이스로 자율주행 로직을 호출한다. 환경은 swappable plugin과 완전 분리. Web UI는 Plotly 2D top-down 맵 + HTMX polling으로 sim state를 시각화한다.

**Tech Stack:** Python 3.10+ asyncio, FastAPI + Jinja2 + HTMX, Plotly.js 2D, pytest. 외부 traffic simulator(CARLA/SUMO)는 비범위.

**Spec:** [`docs/superpowers/specs/2026-06-09-active-traffic-sim-design.md`](../specs/2026-06-09-active-traffic-sim-design.md)

---

## File Structure

새로 만들 파일 (모두 `kadap-poc-v2/` 하위):

```
trafficsim/
  __init__.py
  engine.py            # Sim, World, tick loop
  agents.py            # TrafficLight, Pedestrian, Vehicle agent classes
  v2x.py               # V2X 메시지 생성·라우팅
  world.py             # WorldMap loader (GeoJSON)
  map.geojson          # 한국형 mock 도로 (4-way 교차로 2개 + 골목 1개)
  avlogic/
    __init__.py
    interface.py       # EgoState, V2XMsg, PerceptionView, Observation, Action, AVLogic Protocol
    rule_based.py      # RuleBasedLogic
    alpamayo_proxy.py  # AlpamayoLogic
    v2x_blind.py       # V2XBlindLogic
  scenarios/
    __init__.py
    base.py            # Scenario dataclass + registry
    scen_01_pedestrian.py
    scen_02_signal_fail.py
    scen_03_alley_merge.py
templates/
  tab_trafficsim.html
  _trafficsim_frame.html  # HTMX polling 응답 (Plotly figure JSON + reasoning text)
tests/
  conftest.py            # pytest 환경 (sys.path setup)
  trafficsim/
    __init__.py
    test_interface.py
    test_engine.py
    test_rule_based.py
    test_world.py
    test_traffic_light.py
    test_pedestrian.py
    test_vehicle.py
    test_v2x_router.py
    test_ego_kinematics.py
    test_scenarios.py
    test_avlogic_v2x_blind.py
    test_avlogic_alpamayo.py
```

수정할 파일:
- `kadap-poc-v2/main.py`: 새 endpoint 5개 (`/tab/trafficsim`, `/trafficsim/start`, `/trafficsim/tick`, `/trafficsim/control`, `/trafficsim/reset`) + 탭 내비게이션 등록
- `kadap-poc-v2/templates/base.html`: 탭 메뉴에 "🗺 능동 traffic sim" 추가 (위치는 Task 10에서 확정)

---

## 좌표계 규약 (전 task 공통)

- **World frame**: 동(東)+x, 북(北)+y, m 단위
- **Yaw**: rad, 동쪽이 0, CCW 양수
- **Tick**: 100ms (10 Hz)
- **Sim time `t`**: 초 단위 float, 시나리오 시작 시 0
- **V2X 수신 반경**: 자차 중심 200m, line-of-sight 무시

---

## Phase 1 — Backend foundation

### Task 1: AVLogic 인터페이스 + dataclass 정의

**Files:**
- Create: `kadap-poc-v2/trafficsim/__init__.py`
- Create: `kadap-poc-v2/trafficsim/avlogic/__init__.py`
- Create: `kadap-poc-v2/trafficsim/avlogic/interface.py`
- Create: `kadap-poc-v2/tests/__init__.py`
- Create: `kadap-poc-v2/tests/conftest.py`
- Create: `kadap-poc-v2/tests/trafficsim/__init__.py`
- Test: `kadap-poc-v2/tests/trafficsim/test_interface.py`

- [ ] **Step 1: Write the failing test**

`kadap-poc-v2/tests/conftest.py`:
```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
```

`kadap-poc-v2/tests/trafficsim/test_interface.py`:
```python
from trafficsim.avlogic.interface import (
    Action,
    AVLogic,
    EgoState,
    Observation,
    PerceivedObject,
    PerceptionView,
    V2XMsg,
)


def test_ego_state_construct():
    ego = EgoState(x=10.0, y=20.0, yaw=0.0, speed=8.0, accel=0.0)
    assert ego.x == 10.0
    assert ego.speed == 8.0


def test_v2x_msg_construct():
    msg = V2XMsg(
        kind="SPaT",
        payload={"phase": "GREEN", "remaining_s": 5.0},
        source_id="rsu_001",
        rx_time=1.5,
    )
    assert msg.kind == "SPaT"
    assert msg.payload["phase"] == "GREEN"


def test_perception_view_default_empty():
    pv = PerceptionView(objects=[])
    assert pv.objects == []


def test_observation_construct():
    obs = Observation(
        ego=EgoState(x=0.0, y=0.0, yaw=0.0, speed=0.0, accel=0.0),
        v2x_messages=[],
        perception=PerceptionView(objects=[]),
        t=0.0,
    )
    assert obs.t == 0.0


def test_action_construct():
    a = Action(target_speed=5.0, steering=0.1, reason="cruise")
    assert a.target_speed == 5.0
    assert a.reason == "cruise"


def test_av_logic_is_protocol():
    class _Dummy:
        def decide(self, obs: Observation) -> Action:
            return Action(target_speed=0.0, steering=0.0, reason="dummy")

    d: AVLogic = _Dummy()
    out = d.decide(
        Observation(
            ego=EgoState(0.0, 0.0, 0.0, 0.0, 0.0),
            v2x_messages=[],
            perception=PerceptionView(objects=[]),
            t=0.0,
        )
    )
    assert out.target_speed == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_interface.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'trafficsim'`

- [ ] **Step 3: Write minimal implementation**

`kadap-poc-v2/trafficsim/__init__.py`:
```python
```

`kadap-poc-v2/trafficsim/avlogic/__init__.py`:
```python
```

`kadap-poc-v2/trafficsim/avlogic/interface.py`:
```python
"""AVLogic 인터페이스 — simulator와 자율주행 로직을 분리.

환경은 PoC 산출물, 자율주행 로직은 swappable plugin.
연구자는 AVLogic Protocol만 구현하면 inject 가능.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass
class EgoState:
    x: float
    y: float
    yaw: float
    speed: float
    accel: float


V2XKind = Literal["BSM", "SPaT", "PSM", "RSI", "TIM"]


@dataclass
class V2XMsg:
    kind: V2XKind
    payload: dict
    source_id: str
    rx_time: float


ObjType = Literal["vehicle", "pedestrian", "static"]


@dataclass
class PerceivedObject:
    obj_type: ObjType
    x: float
    y: float
    speed: float


@dataclass
class PerceptionView:
    objects: list[PerceivedObject] = field(default_factory=list)


@dataclass
class Observation:
    ego: EgoState
    v2x_messages: list[V2XMsg]
    perception: PerceptionView
    t: float


@dataclass
class Action:
    target_speed: float
    steering: float
    reason: str


class AVLogic(Protocol):
    def decide(self, obs: Observation) -> Action: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_interface.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add kadap-poc-v2/trafficsim/__init__.py \
        kadap-poc-v2/trafficsim/avlogic/__init__.py \
        kadap-poc-v2/trafficsim/avlogic/interface.py \
        kadap-poc-v2/tests/__init__.py \
        kadap-poc-v2/tests/conftest.py \
        kadap-poc-v2/tests/trafficsim/__init__.py \
        kadap-poc-v2/tests/trafficsim/test_interface.py
git commit -m "feat(trafficsim): add AVLogic Protocol + Observation/Action dataclasses"
```

---

### Task 2: Tick engine skeleton (시간만 진행)

**Files:**
- Create: `kadap-poc-v2/trafficsim/engine.py`
- Test: `kadap-poc-v2/tests/trafficsim/test_engine.py`

- [ ] **Step 1: Write the failing test**

`kadap-poc-v2/tests/trafficsim/test_engine.py`:
```python
import math

from trafficsim.avlogic.interface import Action, AVLogic, Observation
from trafficsim.engine import Sim, SimConfig


class _Noop:
    def decide(self, obs: Observation) -> Action:
        return Action(target_speed=0.0, steering=0.0, reason="noop")


def test_sim_starts_at_t_zero():
    sim = Sim(SimConfig(), logic=_Noop())
    assert sim.t == 0.0
    assert sim.tick_count == 0


def test_sim_tick_advances_time():
    sim = Sim(SimConfig(dt=0.1), logic=_Noop())
    sim.tick()
    assert math.isclose(sim.t, 0.1, abs_tol=1e-9)
    assert sim.tick_count == 1


def test_sim_tick_ten_times_reaches_one_second():
    sim = Sim(SimConfig(dt=0.1), logic=_Noop())
    for _ in range(10):
        sim.tick()
    assert math.isclose(sim.t, 1.0, abs_tol=1e-9)


def test_sim_invokes_logic_each_tick():
    calls = []

    class _Counter:
        def decide(self, obs: Observation) -> Action:
            calls.append(obs.t)
            return Action(target_speed=0.0, steering=0.0, reason="counter")

    sim = Sim(SimConfig(dt=0.1), logic=_Counter())
    for _ in range(3):
        sim.tick()
    assert len(calls) == 3
    assert math.isclose(calls[0], 0.0, abs_tol=1e-9)
    assert math.isclose(calls[2], 0.2, abs_tol=1e-9)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'trafficsim.engine'`

- [ ] **Step 3: Write minimal implementation**

`kadap-poc-v2/trafficsim/engine.py`:
```python
"""Tick 엔진 + Sim 상태 컨테이너.

매 tick: (1) agent 업데이트 (Task 9 이후), (2) Observation 구성,
(3) AVLogic.decide → Action, (4) 자차 kinematic 적용 (Task 9 이후).
지금은 시간 진행 + AVLogic 호출만.
"""

from __future__ import annotations

from dataclasses import dataclass

from trafficsim.avlogic.interface import (
    AVLogic,
    EgoState,
    Observation,
    PerceptionView,
)


@dataclass
class SimConfig:
    dt: float = 0.1  # tick interval (s) → 10 Hz


class Sim:
    def __init__(self, cfg: SimConfig, logic: AVLogic) -> None:
        self.cfg = cfg
        self.logic = logic
        self.t = 0.0
        self.tick_count = 0
        self.ego = EgoState(x=0.0, y=0.0, yaw=0.0, speed=0.0, accel=0.0)
        self.last_action = None
        self.last_reason = ""

    def _build_observation(self) -> Observation:
        return Observation(
            ego=self.ego,
            v2x_messages=[],
            perception=PerceptionView(objects=[]),
            t=self.t,
        )

    def tick(self) -> None:
        obs = self._build_observation()
        action = self.logic.decide(obs)
        self.last_action = action
        self.last_reason = action.reason
        self.t += self.cfg.dt
        self.tick_count += 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_engine.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add kadap-poc-v2/trafficsim/engine.py kadap-poc-v2/tests/trafficsim/test_engine.py
git commit -m "feat(trafficsim): add Sim tick engine skeleton (time + logic invocation)"
```

---

### Task 3: RuleBasedLogic (디폴트 자율주행 로직)

**Files:**
- Create: `kadap-poc-v2/trafficsim/avlogic/rule_based.py`
- Test: `kadap-poc-v2/tests/trafficsim/test_rule_based.py`

V2X 메시지 우선순위 (높은 게 먼저 적용):
1. PSM (보행자 근접) → 즉시 정지
2. SPaT YELLOW/RED 잔여 < 3s → 감속 정지
3. RSI 위험·TIM 우회 → 감속
4. BSM 전방 차량 가까움 → 차간거리 유지 (간단히 속도 매칭)
5. 기본 → 순항 (target_speed 8 m/s)

- [ ] **Step 1: Write the failing test**

`kadap-poc-v2/tests/trafficsim/test_rule_based.py`:
```python
from trafficsim.avlogic.interface import (
    EgoState,
    Observation,
    PerceivedObject,
    PerceptionView,
    V2XMsg,
)
from trafficsim.avlogic.rule_based import RuleBasedLogic


def _obs(v2x=None, perception_objs=None, t=0.0):
    return Observation(
        ego=EgoState(x=0.0, y=0.0, yaw=0.0, speed=8.0, accel=0.0),
        v2x_messages=v2x or [],
        perception=PerceptionView(objects=perception_objs or []),
        t=t,
    )


def test_cruise_when_no_messages():
    a = RuleBasedLogic().decide(_obs())
    assert a.target_speed == 8.0
    assert "cruise" in a.reason.lower()


def test_psm_pedestrian_triggers_stop():
    psm = V2XMsg(
        kind="PSM",
        payload={"x": 10.0, "y": 0.0, "vx": 0.5, "vy": 0.0},
        source_id="ped_1",
        rx_time=0.0,
    )
    a = RuleBasedLogic().decide(_obs(v2x=[psm]))
    assert a.target_speed == 0.0
    assert "보행자" in a.reason or "pedestrian" in a.reason.lower()


def test_spat_red_imminent_triggers_decel():
    spat = V2XMsg(
        kind="SPaT",
        payload={"phase": "RED", "remaining_s": 1.0},
        source_id="rsu_1",
        rx_time=0.0,
    )
    a = RuleBasedLogic().decide(_obs(v2x=[spat]))
    assert a.target_speed < 8.0
    assert "신호" in a.reason or "spat" in a.reason.lower()


def test_spat_green_does_not_decel():
    spat = V2XMsg(
        kind="SPaT",
        payload={"phase": "GREEN", "remaining_s": 5.0},
        source_id="rsu_1",
        rx_time=0.0,
    )
    a = RuleBasedLogic().decide(_obs(v2x=[spat]))
    assert a.target_speed == 8.0


def test_tim_detour_decel():
    tim = V2XMsg(
        kind="TIM",
        payload={"message": "DETOUR", "severity": "HIGH"},
        source_id="rsu_2",
        rx_time=0.0,
    )
    a = RuleBasedLogic().decide(_obs(v2x=[tim]))
    assert a.target_speed < 8.0


def test_bsm_close_lead_matches_speed():
    bsm = V2XMsg(
        kind="BSM",
        payload={"x": 5.0, "y": 0.0, "speed": 3.0, "heading": 0.0},
        source_id="veh_a",
        rx_time=0.0,
    )
    a = RuleBasedLogic().decide(_obs(v2x=[bsm]))
    assert a.target_speed <= 4.0  # 전방 차량 가까우면 속도 낮춤
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_rule_based.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`kadap-poc-v2/trafficsim/avlogic/rule_based.py`:
```python
"""RuleBasedLogic — V2X 메시지에 hand-written 우선순위로 반응하는 baseline.

평가 시 'V2X를 듣고 안전하게 운행하는 차'의 ground truth.
"""

from __future__ import annotations

import math

from trafficsim.avlogic.interface import Action, Observation, V2XMsg

CRUISE_SPEED = 8.0  # m/s
PSM_STOP_RADIUS = 25.0  # m
BSM_FOLLOW_RADIUS = 15.0  # m
SPaT_DECEL_REMAINING_S = 3.0


def _dist(ego_x: float, ego_y: float, x: float, y: float) -> float:
    return math.hypot(x - ego_x, y - ego_y)


class RuleBasedLogic:
    def decide(self, obs: Observation) -> Action:
        ego = obs.ego

        for m in obs.v2x_messages:
            if m.kind == "PSM":
                d = _dist(ego.x, ego.y, m.payload["x"], m.payload["y"])
                if d < PSM_STOP_RADIUS:
                    return Action(
                        target_speed=0.0,
                        steering=0.0,
                        reason=f"보행자 {d:.1f}m — 정지",
                    )

        for m in obs.v2x_messages:
            if m.kind == "SPaT":
                phase = m.payload.get("phase", "")
                remaining = float(m.payload.get("remaining_s", 99.0))
                if phase in ("RED", "YELLOW") and remaining < SPaT_DECEL_REMAINING_S:
                    return Action(
                        target_speed=1.0,
                        steering=0.0,
                        reason=f"SPaT {phase} 잔여 {remaining:.1f}s — 정지선 감속",
                    )

        for m in obs.v2x_messages:
            if m.kind in ("RSI", "TIM"):
                sev = m.payload.get("severity", "LOW")
                if sev in ("HIGH", "MEDIUM"):
                    return Action(
                        target_speed=3.0,
                        steering=0.0,
                        reason=f"{m.kind} {m.payload.get('message','위험')} — 감속",
                    )

        for m in obs.v2x_messages:
            if m.kind == "BSM":
                d = _dist(ego.x, ego.y, m.payload["x"], m.payload["y"])
                if d < BSM_FOLLOW_RADIUS:
                    lead_speed = float(m.payload.get("speed", 0.0))
                    return Action(
                        target_speed=max(0.0, lead_speed - 0.5),
                        steering=0.0,
                        reason=f"BSM 전방 차 {d:.1f}m — 차간거리 유지",
                    )

        return Action(target_speed=CRUISE_SPEED, steering=0.0, reason="cruise (V2X 무특이)")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_rule_based.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add kadap-poc-v2/trafficsim/avlogic/rule_based.py \
        kadap-poc-v2/tests/trafficsim/test_rule_based.py
git commit -m "feat(trafficsim): add RuleBasedLogic (V2X 우선순위 기반 baseline)"
```

---

## Phase 2 — Environment

### Task 4: 한국형 mock 도로 + WorldMap 로더

**Files:**
- Create: `kadap-poc-v2/trafficsim/map.geojson`
- Create: `kadap-poc-v2/trafficsim/world.py`
- Test: `kadap-poc-v2/tests/trafficsim/test_world.py`

좌표계는 mm 아닌 m. 4-way 교차로 2개(원점 + 동쪽 100m), 좁은 골목 1개(북쪽 80m), 보호좌회전+횡단보도 시나리오 1과 골목 합류 시나리오 3에 사용.

- [ ] **Step 1: Write the failing test**

`kadap-poc-v2/tests/trafficsim/test_world.py`:
```python
from pathlib import Path

from trafficsim.world import WorldMap, load_default_map

MAP_PATH = Path(__file__).resolve().parents[2] / "trafficsim" / "map.geojson"


def test_default_map_loads():
    wm = load_default_map()
    assert isinstance(wm, WorldMap)


def test_map_has_lanes():
    wm = load_default_map()
    assert len(wm.lanes) >= 4


def test_map_has_intersections():
    wm = load_default_map()
    # 4-way 교차로 2개
    assert len(wm.intersections) >= 2


def test_map_has_crosswalks():
    wm = load_default_map()
    assert len(wm.crosswalks) >= 1


def test_lane_has_polyline():
    wm = load_default_map()
    lane = wm.lanes[0]
    assert len(lane.polyline) >= 2
    x, y = lane.polyline[0]
    assert isinstance(x, float)
    assert isinstance(y, float)


def test_geojson_file_exists():
    assert MAP_PATH.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_world.py -v`
Expected: FAIL (module missing + file missing)

- [ ] **Step 3: Write minimal implementation**

`kadap-poc-v2/trafficsim/map.geojson`:
```json
{
  "type": "FeatureCollection",
  "name": "kadap-trafficsim-default",
  "features": [
    {
      "type": "Feature",
      "properties": {"kind": "lane", "id": "L_west_east_in", "speed_limit": 13.8},
      "geometry": {"type": "LineString", "coordinates": [[-100.0, 0.0], [0.0, 0.0]]}
    },
    {
      "type": "Feature",
      "properties": {"kind": "lane", "id": "L_west_east_out", "speed_limit": 13.8},
      "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [100.0, 0.0]]}
    },
    {
      "type": "Feature",
      "properties": {"kind": "lane", "id": "L_east_inter2_in", "speed_limit": 13.8},
      "geometry": {"type": "LineString", "coordinates": [[100.0, 0.0], [200.0, 0.0]]}
    },
    {
      "type": "Feature",
      "properties": {"kind": "lane", "id": "L_north_south_in", "speed_limit": 13.8},
      "geometry": {"type": "LineString", "coordinates": [[0.0, 80.0], [0.0, 0.0]]}
    },
    {
      "type": "Feature",
      "properties": {"kind": "lane", "id": "L_alley_merge", "speed_limit": 8.0},
      "geometry": {"type": "LineString", "coordinates": [[60.0, 30.0], [60.0, 0.0]]}
    },
    {
      "type": "Feature",
      "properties": {"kind": "intersection", "id": "X_main"},
      "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}
    },
    {
      "type": "Feature",
      "properties": {"kind": "intersection", "id": "X_east"},
      "geometry": {"type": "Point", "coordinates": [100.0, 0.0]}
    },
    {
      "type": "Feature",
      "properties": {"kind": "crosswalk", "id": "CW_main_north", "axis": "y"},
      "geometry": {"type": "LineString", "coordinates": [[-4.0, 4.0], [4.0, 4.0]]}
    },
    {
      "type": "Feature",
      "properties": {"kind": "crosswalk", "id": "CW_east_north", "axis": "y"},
      "geometry": {"type": "LineString", "coordinates": [[96.0, 4.0], [104.0, 4.0]]}
    }
  ]
}
```

`kadap-poc-v2/trafficsim/world.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_world.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add kadap-poc-v2/trafficsim/map.geojson \
        kadap-poc-v2/trafficsim/world.py \
        kadap-poc-v2/tests/trafficsim/test_world.py
git commit -m "feat(trafficsim): add WorldMap GeoJSON (2 intersections + alley + crosswalks)"
```

---

### Task 5: TrafficLight agent + SPaT cycle

**Files:**
- Create: `kadap-poc-v2/trafficsim/agents.py`
- Test: `kadap-poc-v2/tests/trafficsim/test_traffic_light.py`

SPaT cycle: GREEN 15s → YELLOW 3s → RED 15s → (반복). Phase 시작 시점은 시나리오에서 offset 지정 가능.

- [ ] **Step 1: Write the failing test**

`kadap-poc-v2/tests/trafficsim/test_traffic_light.py`:
```python
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
    # 15 + 3 + 15 = 33s 후 GREEN 복귀
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_traffic_light.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`kadap-poc-v2/trafficsim/agents.py`:
```python
"""환경 agent: TrafficLight, Pedestrian, Vehicle.

Task 5 — TrafficLight. Task 6 — Pedestrian. Task 7 — Vehicle (IDM).
모두 매 tick `update(t, dt, world)` 받아 state 갱신.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

Phase = Literal["GREEN", "YELLOW", "RED", "OFF"]

GREEN_S = 15.0
YELLOW_S = 3.0
RED_S = 15.0
CYCLE_S = GREEN_S + YELLOW_S + RED_S


@dataclass
class TrafficLight:
    id: str
    x: float
    y: float
    offset: float = 0.0
    broken: bool = False
    phase: Phase = "GREEN"
    remaining_s: float = GREEN_S

    def update(self, t: float, dt: float = 0.0) -> None:
        if self.broken:
            self.phase = "OFF"
            self.remaining_s = 0.0
            return
        cycle_t = (t + self.offset) % CYCLE_S
        if cycle_t < GREEN_S:
            self.phase = "GREEN"
            self.remaining_s = GREEN_S - cycle_t
        elif cycle_t < GREEN_S + YELLOW_S:
            self.phase = "YELLOW"
            self.remaining_s = GREEN_S + YELLOW_S - cycle_t
        else:
            self.phase = "RED"
            self.remaining_s = CYCLE_S - cycle_t
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_traffic_light.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add kadap-poc-v2/trafficsim/agents.py \
        kadap-poc-v2/tests/trafficsim/test_traffic_light.py
git commit -m "feat(trafficsim): add TrafficLight agent (SPaT cycle GREEN/YELLOW/RED + broken)"
```

---

### Task 6: Pedestrian agent (path-following, PSM 송신)

**Files:**
- Modify: `kadap-poc-v2/trafficsim/agents.py` (append)
- Test: `kadap-poc-v2/tests/trafficsim/test_pedestrian.py`

- [ ] **Step 1: Write the failing test**

`kadap-poc-v2/tests/trafficsim/test_pedestrian.py`:
```python
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
    # 방향 (3,4)/5 = (0.6, 0.8), 5 m/s, dt=0.1 → (0.3, 0.4)
    assert math.isclose(p.x, 0.3, abs_tol=1e-6)
    assert math.isclose(p.y, 0.4, abs_tol=1e-6)
    assert math.isclose(p.vx, 3.0, abs_tol=1e-6)
    assert math.isclose(p.vy, 4.0, abs_tol=1e-6)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_pedestrian.py -v`
Expected: FAIL with `ImportError: cannot import name 'Pedestrian'`

- [ ] **Step 3: Write minimal implementation**

Append to `kadap-poc-v2/trafficsim/agents.py`:
```python


@dataclass
class Pedestrian:
    id: str
    path: list[tuple[float, float]]
    speed: float = 1.2  # m/s (보행자 기본 보행 속도)
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    _idx: int = 1
    finished: bool = False

    def __post_init__(self) -> None:
        if self.path:
            self.x, self.y = self.path[0]

    def update(self, t: float, dt: float) -> None:
        if self.finished:
            self.vx = self.vy = 0.0
            return
        remaining_budget = self.speed * dt
        while remaining_budget > 0 and self._idx < len(self.path):
            tx, ty = self.path[self._idx]
            dx, dy = tx - self.x, ty - self.y
            d = math.hypot(dx, dy)
            if d < 1e-9:
                self._idx += 1
                continue
            step = min(remaining_budget, d)
            ux, uy = dx / d, dy / d
            self.x += ux * step
            self.y += uy * step
            self.vx = ux * self.speed
            self.vy = uy * self.speed
            remaining_budget -= step
            if step >= d - 1e-9:
                self._idx += 1
        if self._idx >= len(self.path):
            self.finished = True
            self.vx = self.vy = 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_pedestrian.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add kadap-poc-v2/trafficsim/agents.py \
        kadap-poc-v2/tests/trafficsim/test_pedestrian.py
git commit -m "feat(trafficsim): add Pedestrian agent (path-following waypoints)"
```

---

### Task 7: Vehicle agent (IDM following + heading)

**Files:**
- Modify: `kadap-poc-v2/trafficsim/agents.py` (append)
- Test: `kadap-poc-v2/tests/trafficsim/test_vehicle.py`

IDM 단순화 버전: free-flow에서는 desired_speed로 가속, 전방 차(lead)가 있으면 거리·속도차 기반 감속. 차로는 폴리라인 따라 진행.

- [ ] **Step 1: Write the failing test**

`kadap-poc-v2/tests/trafficsim/test_vehicle.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_vehicle.py -v`
Expected: FAIL with `ImportError: cannot import name 'Vehicle'`

- [ ] **Step 3: Write minimal implementation**

Append to `kadap-poc-v2/trafficsim/agents.py`:
```python


# IDM parameters (Treiber/Helbing 단순화)
IDM_A = 1.5  # max accel, m/s²
IDM_B = 2.5  # comfortable decel, m/s²
IDM_S0 = 2.0  # minimum gap, m
IDM_T = 1.2  # safety headway, s
IDM_DELTA = 4.0


@dataclass
class Vehicle:
    id: str
    path: list[tuple[float, float]]
    desired_speed: float = 10.0
    x: float = 0.0
    y: float = 0.0
    heading: float = 0.0
    speed: float = 0.0
    _idx: int = 1
    finished: bool = False

    def __post_init__(self) -> None:
        if self.path:
            self.x, self.y = self.path[0]
            if len(self.path) > 1:
                tx, ty = self.path[1]
                self.heading = math.atan2(ty - self.y, tx - self.x)

    def _compute_accel(self, lead_distance: float | None, lead_speed: float | None) -> float:
        v = self.speed
        v0 = self.desired_speed
        free_term = 1.0 - (v / v0) ** IDM_DELTA if v0 > 0 else 0.0
        if lead_distance is None:
            return IDM_A * free_term
        dv = v - (lead_speed if lead_speed is not None else 0.0)
        s = max(lead_distance, 0.1)
        s_star = IDM_S0 + max(0.0, v * IDM_T + v * dv / (2.0 * math.sqrt(IDM_A * IDM_B)))
        interaction = (s_star / s) ** 2
        return IDM_A * (free_term - interaction)

    def update(
        self,
        t: float,
        dt: float,
        lead_distance: float | None = None,
        lead_speed: float | None = None,
    ) -> None:
        if self.finished:
            self.speed = 0.0
            return
        a = self._compute_accel(lead_distance, lead_speed)
        self.speed = max(0.0, self.speed + a * dt)
        budget = self.speed * dt
        while budget > 0 and self._idx < len(self.path):
            tx, ty = self.path[self._idx]
            dx, dy = tx - self.x, ty - self.y
            d = math.hypot(dx, dy)
            if d < 1e-9:
                self._idx += 1
                continue
            step = min(budget, d)
            ux, uy = dx / d, dy / d
            self.x += ux * step
            self.y += uy * step
            self.heading = math.atan2(uy, ux)
            budget -= step
            if step >= d - 1e-9:
                self._idx += 1
        if self._idx >= len(self.path):
            self.finished = True
            self.speed = 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_vehicle.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add kadap-poc-v2/trafficsim/agents.py \
        kadap-poc-v2/tests/trafficsim/test_vehicle.py
git commit -m "feat(trafficsim): add Vehicle agent with IDM (free-flow + lead following)"
```

---

### Task 8: V2X 메시지 생성·라우팅

**Files:**
- Create: `kadap-poc-v2/trafficsim/v2x.py`
- Test: `kadap-poc-v2/tests/trafficsim/test_v2x_router.py`

router: 모든 agent로부터 V2X 메시지를 수집해서 자차 반경 200m 이내만 통과시킴. LOS 무시.

- [ ] **Step 1: Write the failing test**

`kadap-poc-v2/tests/trafficsim/test_v2x_router.py`:
```python
import math

from trafficsim.agents import Pedestrian, TrafficLight, Vehicle
from trafficsim.avlogic.interface import EgoState, V2XMsg
from trafficsim.v2x import (
    V2X_RX_RADIUS,
    bsm_from_vehicle,
    psm_from_pedestrian,
    route_messages,
    spat_from_traffic_light,
    tim_message,
)


def test_spat_message_shape():
    tl = TrafficLight(id="rsu_main", x=0.0, y=0.0)
    tl.update(t=0.0)
    m = spat_from_traffic_light(tl, rx_time=0.0)
    assert m.kind == "SPaT"
    assert m.payload["phase"] == "GREEN"
    assert m.source_id == "rsu_main"


def test_psm_message_shape():
    p = Pedestrian(id="p1", path=[(5.0, 0.0), (5.0, 10.0)], speed=1.0)
    p.update(t=0.0, dt=0.1)
    m = psm_from_pedestrian(p, rx_time=0.0)
    assert m.kind == "PSM"
    assert math.isclose(m.payload["x"], p.x)


def test_bsm_message_shape():
    v = Vehicle(id="veh_a", path=[(0.0, 0.0), (100.0, 0.0)], desired_speed=10.0)
    v.speed = 5.0
    m = bsm_from_vehicle(v, rx_time=0.0)
    assert m.kind == "BSM"
    assert m.payload["speed"] == 5.0


def test_tim_message_shape():
    m = tim_message(
        source_id="rsu_2",
        message="DETOUR",
        severity="HIGH",
        rx_time=1.0,
    )
    assert m.kind == "TIM"
    assert m.payload["severity"] == "HIGH"


def test_router_filters_by_radius():
    ego = EgoState(x=0.0, y=0.0, yaw=0.0, speed=0.0, accel=0.0)
    near = V2XMsg(
        kind="BSM",
        payload={"x": 50.0, "y": 0.0, "speed": 5.0, "heading": 0.0},
        source_id="near",
        rx_time=0.0,
    )
    far = V2XMsg(
        kind="BSM",
        payload={"x": V2X_RX_RADIUS + 100.0, "y": 0.0, "speed": 5.0, "heading": 0.0},
        source_id="far",
        rx_time=0.0,
    )
    out = route_messages([near, far], ego)
    ids = {m.source_id for m in out}
    assert "near" in ids
    assert "far" not in ids


def test_router_passes_msgs_without_xy_field():
    # TIM 등은 위치 무관 — 항상 통과
    ego = EgoState(x=0.0, y=0.0, yaw=0.0, speed=0.0, accel=0.0)
    tim = V2XMsg(
        kind="TIM",
        payload={"message": "DETOUR", "severity": "HIGH"},
        source_id="rsu_2",
        rx_time=0.0,
    )
    out = route_messages([tim], ego)
    assert len(out) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_v2x_router.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`kadap-poc-v2/trafficsim/v2x.py`:
```python
"""V2X 메시지 생성기 + 자차 수신 router.

수신 모델: 자차 중심 반경 V2X_RX_RADIUS m 이내, LOS 무시.
위치 정보 없는 메시지(TIM 등)는 시나리오 inject 시 항상 통과.
"""

from __future__ import annotations

import math

from trafficsim.agents import Pedestrian, TrafficLight, Vehicle
from trafficsim.avlogic.interface import EgoState, V2XMsg

V2X_RX_RADIUS = 200.0  # m


def spat_from_traffic_light(tl: TrafficLight, rx_time: float) -> V2XMsg:
    return V2XMsg(
        kind="SPaT",
        payload={
            "phase": tl.phase,
            "remaining_s": tl.remaining_s,
            "x": tl.x,
            "y": tl.y,
        },
        source_id=tl.id,
        rx_time=rx_time,
    )


def psm_from_pedestrian(p: Pedestrian, rx_time: float) -> V2XMsg:
    return V2XMsg(
        kind="PSM",
        payload={"x": p.x, "y": p.y, "vx": p.vx, "vy": p.vy},
        source_id=p.id,
        rx_time=rx_time,
    )


def bsm_from_vehicle(v: Vehicle, rx_time: float) -> V2XMsg:
    return V2XMsg(
        kind="BSM",
        payload={
            "x": v.x,
            "y": v.y,
            "speed": v.speed,
            "heading": v.heading,
        },
        source_id=v.id,
        rx_time=rx_time,
    )


def tim_message(source_id: str, message: str, severity: str, rx_time: float) -> V2XMsg:
    return V2XMsg(
        kind="TIM",
        payload={"message": message, "severity": severity},
        source_id=source_id,
        rx_time=rx_time,
    )


def rsi_message(
    source_id: str, message: str, severity: str, x: float, y: float, rx_time: float
) -> V2XMsg:
    return V2XMsg(
        kind="RSI",
        payload={"message": message, "severity": severity, "x": x, "y": y},
        source_id=source_id,
        rx_time=rx_time,
    )


def route_messages(messages: list[V2XMsg], ego: EgoState) -> list[V2XMsg]:
    out: list[V2XMsg] = []
    for m in messages:
        x = m.payload.get("x")
        y = m.payload.get("y")
        if x is None or y is None:
            out.append(m)
            continue
        if math.hypot(x - ego.x, y - ego.y) <= V2X_RX_RADIUS:
            out.append(m)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_v2x_router.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add kadap-poc-v2/trafficsim/v2x.py \
        kadap-poc-v2/tests/trafficsim/test_v2x_router.py
git commit -m "feat(trafficsim): add V2X message factories + radius router"
```

---

### Task 9: Ego kinematic update + 통합 tick

**Files:**
- Modify: `kadap-poc-v2/trafficsim/engine.py`
- Test: `kadap-poc-v2/tests/trafficsim/test_ego_kinematics.py`

Sim에 World·agents·V2X 통합. `tick()`이 (1) agent update, (2) V2X 수집·router, (3) perception(LOS — 100m + 시야 ±90°), (4) AVLogic.decide, (5) 자차 kinematic 적용 (target_speed 1차 추종 + steering로 yaw 변경 + 직선 forward).

- [ ] **Step 1: Write the failing test**

`kadap-poc-v2/tests/trafficsim/test_ego_kinematics.py`:
```python
import math

from trafficsim.agents import TrafficLight, Vehicle
from trafficsim.avlogic.interface import Action, Observation
from trafficsim.engine import Sim, SimConfig
from trafficsim.world import load_default_map


class _ConstAction:
    def __init__(self, action: Action) -> None:
        self.action = action

    def decide(self, obs: Observation) -> Action:
        return self.action


def test_ego_accelerates_toward_target_speed():
    sim = Sim(
        SimConfig(dt=0.1),
        logic=_ConstAction(Action(target_speed=5.0, steering=0.0, reason="go")),
        world=load_default_map(),
    )
    for _ in range(30):
        sim.tick()
    assert sim.ego.speed > 1.0
    assert sim.ego.x > 0.0


def test_ego_stops_when_target_zero():
    sim = Sim(
        SimConfig(dt=0.1),
        logic=_ConstAction(Action(target_speed=0.0, steering=0.0, reason="stop")),
        world=load_default_map(),
    )
    sim.ego.speed = 5.0
    for _ in range(30):
        sim.tick()
    assert sim.ego.speed < 0.5


def test_ego_steering_changes_yaw():
    sim = Sim(
        SimConfig(dt=0.1),
        logic=_ConstAction(Action(target_speed=5.0, steering=0.1, reason="turn")),
        world=load_default_map(),
    )
    sim.ego.speed = 5.0
    yaw0 = sim.ego.yaw
    for _ in range(10):
        sim.tick()
    assert not math.isclose(sim.ego.yaw, yaw0, abs_tol=1e-3)


def test_sim_collects_spat_messages():
    captured: list = []

    class _Cap:
        def decide(self, obs: Observation) -> Action:
            captured.append(list(obs.v2x_messages))
            return Action(target_speed=0.0, steering=0.0, reason="cap")

    world = load_default_map()
    sim = Sim(SimConfig(dt=0.1), logic=_Cap(), world=world)
    sim.add_traffic_light(TrafficLight(id="rsu_main", x=0.0, y=0.0))
    sim.tick()
    assert captured[0], "should receive SPaT in first tick"
    kinds = {m.kind for m in captured[0]}
    assert "SPaT" in kinds


def test_sim_perception_picks_up_nearby_vehicle():
    captured: list = []

    class _Cap:
        def decide(self, obs: Observation) -> Action:
            captured.append(obs.perception.objects)
            return Action(target_speed=0.0, steering=0.0, reason="cap")

    sim = Sim(SimConfig(dt=0.1), logic=_Cap(), world=load_default_map())
    sim.add_vehicle(Vehicle(id="v_a", path=[(20.0, 0.0), (200.0, 0.0)]))
    sim.tick()
    assert any(o.obj_type == "vehicle" for o in captured[0])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_ego_kinematics.py -v`
Expected: FAIL (Sim constructor doesn't accept `world`, no agent registries)

- [ ] **Step 3: Write minimal implementation**

Replace `kadap-poc-v2/trafficsim/engine.py` entirely:
```python
"""Tick 엔진 + Sim 상태 컨테이너.

매 tick: (1) agent 업데이트, (2) Observation 구성 (V2X 라우팅 + perception),
(3) AVLogic.decide → Action, (4) 자차 kinematic 적용.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from trafficsim.agents import Pedestrian, TrafficLight, Vehicle
from trafficsim.avlogic.interface import (
    Action,
    AVLogic,
    EgoState,
    Observation,
    PerceivedObject,
    PerceptionView,
    V2XMsg,
)
from trafficsim.v2x import (
    bsm_from_vehicle,
    psm_from_pedestrian,
    route_messages,
    spat_from_traffic_light,
)
from trafficsim.world import WorldMap

# 자차 kinematic
SPEED_TAU = 1.0          # 1차 지연 — 목표 속도까지 약 τ초
MAX_ACCEL = 3.0          # m/s²
MAX_DECEL = 4.0          # m/s²
YAW_RATE_GAIN = 1.0      # rad/s per (rad steering)
PERCEPTION_RANGE = 100.0
PERCEPTION_HALF_FOV = math.pi / 2  # ±90°


@dataclass
class SimConfig:
    dt: float = 0.1
    rng_seed: int = 0


@dataclass
class Sim:
    cfg: SimConfig
    logic: AVLogic
    world: WorldMap | None = None
    t: float = 0.0
    tick_count: int = 0
    ego: EgoState = field(
        default_factory=lambda: EgoState(x=0.0, y=0.0, yaw=0.0, speed=0.0, accel=0.0)
    )
    traffic_lights: list[TrafficLight] = field(default_factory=list)
    pedestrians: list[Pedestrian] = field(default_factory=list)
    vehicles: list[Vehicle] = field(default_factory=list)
    injected_msgs: list[V2XMsg] = field(default_factory=list)
    last_action: Action | None = None
    last_reason: str = ""

    def add_traffic_light(self, tl: TrafficLight) -> None:
        self.traffic_lights.append(tl)

    def add_pedestrian(self, p: Pedestrian) -> None:
        self.pedestrians.append(p)

    def add_vehicle(self, v: Vehicle) -> None:
        self.vehicles.append(v)

    def inject_message(self, msg: V2XMsg) -> None:
        self.injected_msgs.append(msg)

    def _update_agents(self) -> None:
        for tl in self.traffic_lights:
            tl.update(self.t)
        for p in self.pedestrians:
            p.update(self.t, self.cfg.dt)
        for v in self.vehicles:
            v.update(self.t, self.cfg.dt, lead_distance=None, lead_speed=None)

    def _collect_v2x(self) -> list[V2XMsg]:
        msgs: list[V2XMsg] = []
        for tl in self.traffic_lights:
            msgs.append(spat_from_traffic_light(tl, rx_time=self.t))
        for p in self.pedestrians:
            msgs.append(psm_from_pedestrian(p, rx_time=self.t))
        for v in self.vehicles:
            msgs.append(bsm_from_vehicle(v, rx_time=self.t))
        msgs.extend(m for m in self.injected_msgs if m.rx_time <= self.t)
        return route_messages(msgs, self.ego)

    def _build_perception(self) -> PerceptionView:
        objs: list[PerceivedObject] = []
        for v in self.vehicles:
            if self._in_fov(v.x, v.y):
                objs.append(
                    PerceivedObject(obj_type="vehicle", x=v.x, y=v.y, speed=v.speed)
                )
        for p in self.pedestrians:
            if self._in_fov(p.x, p.y):
                speed = math.hypot(p.vx, p.vy)
                objs.append(
                    PerceivedObject(obj_type="pedestrian", x=p.x, y=p.y, speed=speed)
                )
        return PerceptionView(objects=objs)

    def _in_fov(self, x: float, y: float) -> bool:
        dx = x - self.ego.x
        dy = y - self.ego.y
        d = math.hypot(dx, dy)
        if d > PERCEPTION_RANGE:
            return False
        if d < 1e-6:
            return True
        bearing = math.atan2(dy, dx) - self.ego.yaw
        bearing = (bearing + math.pi) % (2 * math.pi) - math.pi
        return abs(bearing) <= PERCEPTION_HALF_FOV

    def _apply_action(self, action: Action) -> None:
        dt = self.cfg.dt
        # 1차 추종 속도 + acceleration limit
        delta = (action.target_speed - self.ego.speed) / SPEED_TAU
        delta = max(-MAX_DECEL, min(MAX_ACCEL, delta))
        new_speed = max(0.0, self.ego.speed + delta * dt)
        self.ego.accel = (new_speed - self.ego.speed) / dt if dt > 0 else 0.0
        self.ego.speed = new_speed
        steering = max(-math.pi / 4, min(math.pi / 4, action.steering))
        yaw_rate = YAW_RATE_GAIN * steering
        self.ego.yaw += yaw_rate * dt
        self.ego.x += self.ego.speed * math.cos(self.ego.yaw) * dt
        self.ego.y += self.ego.speed * math.sin(self.ego.yaw) * dt

    def tick(self) -> None:
        self._update_agents()
        v2x = self._collect_v2x()
        perception = self._build_perception()
        obs = Observation(ego=self.ego, v2x_messages=v2x, perception=perception, t=self.t)
        action = self.logic.decide(obs)
        self._apply_action(action)
        self.last_action = action
        self.last_reason = action.reason
        self.t += self.cfg.dt
        self.tick_count += 1
```

- [ ] **Step 4: Run test to verify Task 2 + Task 9 both pass**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_engine.py tests/trafficsim/test_ego_kinematics.py -v`
Expected: PASS (Task 2의 4개 + Task 9의 5개 = 9 tests)

- [ ] **Step 5: Commit**

```bash
git add kadap-poc-v2/trafficsim/engine.py \
        kadap-poc-v2/tests/trafficsim/test_ego_kinematics.py
git commit -m "feat(trafficsim): integrate agents+V2X+perception into Sim tick; add ego kinematics"
```

---

## Phase 3 — Web UI

### Task 10: 새 탭 등록 + Plotly 2D 정적 렌더

**Files:**
- Create: `kadap-poc-v2/templates/tab_trafficsim.html`
- Modify: `kadap-poc-v2/templates/base.html` (탭 메뉴에 항목 1개 추가)
- Modify: `kadap-poc-v2/main.py` (GET `/tab/trafficsim` 추가)

Plotly 2D 렌더링 helper도 만들어둠 (Task 11에서 frame template에서 재사용).

- [ ] **Step 1: 현재 탭 메뉴 위치 확인**

Run: `cd kadap-poc-v2 && grep -n "tab/" templates/base.html | head -20`
Expected: 기존 탭 항목들 (`/tab/scenario_eval`, `/tab/closedloop` 등) 확인

- [ ] **Step 2: 탭 진입 endpoint + 기본 페이지 작성**

`kadap-poc-v2/templates/tab_trafficsim.html`:
```html
{% extends "base.html" %}
{% block content %}
<h2>🗺 능동 traffic sim</h2>
<p class="muted">
  V2X 인프라(신호등·RSU·보행자·주변차)가 포함된 시뮬레이션 환경에서
  자율주행 로직(swappable)을 테스트합니다.
</p>

<form id="ts-form" hx-post="/trafficsim/start" hx-target="#ts-stage" hx-swap="innerHTML">
  <fieldset style="margin-bottom:1rem; padding:0.75rem;">
    <legend>시나리오</legend>
    {% for s in scenarios %}
    <label style="margin-right:1rem;">
      <input type="radio" name="scenario" value="{{ s.key }}"
             {% if loop.first %}checked{% endif %}>
      {{ s.name }}
    </label>
    {% endfor %}
  </fieldset>

  <fieldset style="margin-bottom:1rem; padding:0.75rem;">
    <legend>자율주행 로직</legend>
    {% for l in logics %}
    <label style="margin-right:1rem;">
      <input type="radio" name="logic" value="{{ l.key }}"
             {% if loop.first %}checked{% endif %}>
      {{ l.name }}
    </label>
    {% endfor %}
  </fieldset>

  <button type="submit" class="btn btn-primary">▶ 시작</button>
</form>

<div id="ts-stage" style="margin-top:1.5rem;">
  <div class="muted">시나리오·로직을 선택하고 ▶ 시작을 누르세요.</div>
</div>
{% endblock %}
```

`kadap-poc-v2/templates/base.html` — 탭 메뉴(`<nav>`)의 `tab/closedloop` 항목 바로 다음에 추가:
```html
<a href="/tab/trafficsim" class="tab-link">🗺 능동 traffic sim</a>
```

`kadap-poc-v2/main.py` — 적당한 위치 (다른 `tab_*` endpoint 근처)에 추가:
```python
from trafficsim.world import load_default_map  # 파일 상단 import 블록에 추가

# Scenario·Logic 옵션 (Task 12-17에서 채워짐, 지금은 stub)
TRAFFICSIM_SCENARIOS = [
    {"key": "scen_01", "name": "① 보호좌회전 + 횡단보도 보행자"},
    {"key": "scen_02", "name": "② 신호등 고장 + RSU 우회 안내"},
    {"key": "scen_03", "name": "③ 골목 합류 + 사각지대 BSM"},
]
TRAFFICSIM_LOGICS = [
    {"key": "rule_based", "name": "RuleBased (V2X 우선순위)"},
    {"key": "alpamayo", "name": "Alpamayo VLA"},
    {"key": "v2x_blind", "name": "V2X 무시 (비교군)"},
]


@app.get("/tab/trafficsim", response_class=HTMLResponse)
async def tab_trafficsim(request: Request):
    return templates.TemplateResponse(
        request,
        "tab_trafficsim.html",
        {
            "scenarios": TRAFFICSIM_SCENARIOS,
            "logics": TRAFFICSIM_LOGICS,
        },
    )
```

- [ ] **Step 3: uvicorn에서 manual 확인**

기존 uvicorn은 reload 모드일 수 있음. 확인 후 재시작 필요.
Run: `ps aux | grep uvicorn | grep -v grep` — PID 확인
프로세스 살아 있으면 reload로 자동 적용 (`--reload` 옵션 여부 확인).

브라우저에서 `/tab/trafficsim` 접근:
- 탭 메뉴에 "🗺 능동 traffic sim" 노출됨
- 시나리오/로직 radio 그룹 보임
- ▶ 시작 누르면 fetch 실패 (endpoint 미존재) — Task 11에서 해결 예정

- [ ] **Step 4: Commit**

```bash
git add kadap-poc-v2/templates/tab_trafficsim.html \
        kadap-poc-v2/templates/base.html \
        kadap-poc-v2/main.py
git commit -m "feat(trafficsim): add UI tab skeleton (scenario/logic selectors)"
```

---

### Task 11: Sim runtime + HTMX polling endpoint + Plotly frame

**Files:**
- Create: `kadap-poc-v2/templates/_trafficsim_frame.html`
- Modify: `kadap-poc-v2/main.py` (`/trafficsim/start`, `/trafficsim/tick`, runtime registry)

Sim 객체를 `TRAFFICSIM_RUNS: dict[str, dict]`에 저장 (run_id → {sim, paused}). HTMX 2 Hz polling으로 frame template 반환. Plotly figure는 Plotly.react로 in-place 갱신.

이 task는 long but split하면 redundant — single task로 진행.

- [ ] **Step 1: Start/tick endpoint helper test (단위)**

Test없이 manual 검증으로 가도 되지만 핵심 helper는 단위 테스트 — `build_plotly_figure(sim) -> dict`만 단순 검증.

`kadap-poc-v2/tests/trafficsim/test_engine.py`에 다음 test 추가:
```python
def test_build_plotly_figure_shape():
    from trafficsim.engine import Sim, SimConfig, build_plotly_figure
    from trafficsim.world import load_default_map

    class _Noop:
        def decide(self, obs):
            from trafficsim.avlogic.interface import Action
            return Action(target_speed=0.0, steering=0.0, reason="noop")

    sim = Sim(SimConfig(), logic=_Noop(), world=load_default_map())
    fig = build_plotly_figure(sim)
    assert "data" in fig
    assert "layout" in fig
    assert any(tr.get("name", "").startswith("lane") for tr in fig["data"])
```

- [ ] **Step 2: Run test (FAIL — function 미존재)**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_engine.py::test_build_plotly_figure_shape -v`
Expected: FAIL

- [ ] **Step 3: build_plotly_figure 구현**

`kadap-poc-v2/trafficsim/engine.py` 하단에 추가:
```python


def build_plotly_figure(sim: "Sim") -> dict:
    """Sim 상태 → Plotly figure JSON (top-down 2D 맵)."""
    data: list[dict] = []

    if sim.world:
        for lane in sim.world.lanes:
            xs = [pt[0] for pt in lane.polyline]
            ys = [pt[1] for pt in lane.polyline]
            data.append({
                "type": "scatter", "mode": "lines",
                "x": xs, "y": ys,
                "name": f"lane:{lane.id}",
                "line": {"color": "#888", "width": 6},
                "hoverinfo": "skip",
                "showlegend": False,
            })
        for cw in sim.world.crosswalks:
            xs = [pt[0] for pt in cw.polyline]
            ys = [pt[1] for pt in cw.polyline]
            data.append({
                "type": "scatter", "mode": "lines",
                "x": xs, "y": ys,
                "name": f"crosswalk:{cw.id}",
                "line": {"color": "#fff", "width": 4, "dash": "dot"},
                "hoverinfo": "skip",
                "showlegend": False,
            })

    # 신호등
    for tl in sim.traffic_lights:
        color = {"GREEN": "#2ecc71", "YELLOW": "#f1c40f", "RED": "#e74c3c", "OFF": "#7f8c8d"}.get(tl.phase, "#888")
        data.append({
            "type": "scatter", "mode": "markers",
            "x": [tl.x], "y": [tl.y],
            "marker": {"size": 16, "color": color, "symbol": "square"},
            "name": f"SPaT {tl.id}",
            "text": [f"{tl.phase} {tl.remaining_s:.1f}s"],
            "hoverinfo": "text",
        })

    # 보행자
    if sim.pedestrians:
        data.append({
            "type": "scatter", "mode": "markers",
            "x": [p.x for p in sim.pedestrians],
            "y": [p.y for p in sim.pedestrians],
            "marker": {"size": 10, "color": "#3498db", "symbol": "circle"},
            "name": "보행자 (PSM)",
        })

    # 주변차
    if sim.vehicles:
        data.append({
            "type": "scatter", "mode": "markers",
            "x": [v.x for v in sim.vehicles],
            "y": [v.y for v in sim.vehicles],
            "marker": {"size": 14, "color": "#e67e22", "symbol": "triangle-up"},
            "name": "주변차 (BSM)",
        })

    # 자차
    data.append({
        "type": "scatter", "mode": "markers",
        "x": [sim.ego.x], "y": [sim.ego.y],
        "marker": {"size": 20, "color": "#c0392b", "symbol": "star"},
        "name": "자차",
    })

    layout = {
        "xaxis": {"range": [-50, 250], "title": "x (m)", "scaleanchor": "y", "scaleratio": 1},
        "yaxis": {"range": [-30, 100], "title": "y (m)"},
        "margin": {"l": 50, "r": 10, "t": 10, "b": 40},
        "showlegend": True,
        "legend": {"orientation": "h", "y": -0.15},
        "paper_bgcolor": "#222",
        "plot_bgcolor": "#1a1a1a",
        "font": {"color": "#eee"},
    }
    return {"data": data, "layout": layout}
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_engine.py -v`
Expected: PASS (5 tests including build_plotly_figure)

- [ ] **Step 5: Runtime registry + endpoint 추가**

`kadap-poc-v2/main.py` (적당한 위치, `tab_trafficsim` endpoint 다음):
```python
from fastapi import Form
from trafficsim.engine import Sim, SimConfig, build_plotly_figure
from trafficsim.avlogic.rule_based import RuleBasedLogic
from trafficsim.world import load_default_map
import secrets

TRAFFICSIM_RUNS: dict[str, dict] = {}


def _make_logic(key: str):
    if key == "rule_based":
        return RuleBasedLogic()
    # Task 16, 17에서 alpamayo / v2x_blind 추가
    return RuleBasedLogic()


def _apply_scenario(sim: Sim, key: str) -> None:
    # Task 13-15에서 시나리오별 setup 추가
    pass


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
    return templates.TemplateResponse(
        request,
        "_trafficsim_frame.html",
        {
            "run_id": run_id,
            "sim": sim,
            "figure": build_plotly_figure(sim),
            "paused": False,
        },
    )


@app.get("/trafficsim/tick", response_class=HTMLResponse)
async def trafficsim_tick(request: Request, run_id: str):
    state = TRAFFICSIM_RUNS.get(run_id)
    if not state:
        return HTMLResponse(
            '<div class="muted">세션 만료 — 다시 시작하세요.</div>',
            status_code=200,
        )
    sim: Sim = state["sim"]
    if not state["paused"]:
        # UI poll 주기보다 sim 주기가 짧음 → 한 번 poll = 2 tick (5 Hz UI, 10 Hz sim)
        for _ in range(2):
            sim.tick()
    return templates.TemplateResponse(
        request,
        "_trafficsim_frame.html",
        {
            "run_id": run_id,
            "sim": sim,
            "figure": build_plotly_figure(sim),
            "paused": state["paused"],
        },
    )
```

`kadap-poc-v2/templates/_trafficsim_frame.html`:
```html
<div id="ts-frame"
     hx-get="/trafficsim/tick?run_id={{ run_id }}"
     hx-trigger="load delay:200ms"
     hx-target="#ts-frame"
     hx-swap="outerHTML">
  <div style="display:grid; grid-template-columns:2fr 1fr; gap:1rem;">
    <div id="ts-plot-{{ run_id }}" style="height:520px;"></div>
    <div>
      <h3 style="margin-top:0;">tick {{ sim.tick_count }} · t={{ "%.1f"|format(sim.t) }}s</h3>
      <table class="step-meta" style="width:100%;">
        <tr><th>자차 속도</th><td>{{ "%.2f"|format(sim.ego.speed) }} m/s</td></tr>
        <tr><th>자차 위치</th><td>({{ "%.1f"|format(sim.ego.x) }}, {{ "%.1f"|format(sim.ego.y) }})</td></tr>
        <tr><th>로직 판단</th><td>{{ sim.last_reason or "—" }}</td></tr>
      </table>
      <div style="margin-top:1rem;">
        <button hx-post="/trafficsim/control?run_id={{ run_id }}&action=toggle_pause"
                hx-target="#ts-frame" hx-swap="outerHTML"
                class="btn">{% if paused %}▶ 재개{% else %}⏸ 일시정지{% endif %}</button>
        <button hx-post="/trafficsim/control?run_id={{ run_id }}&action=step"
                hx-target="#ts-frame" hx-swap="outerHTML"
                class="btn" {% if not paused %}disabled{% endif %}>⏭ 1 step</button>
        <button hx-post="/trafficsim/reset?run_id={{ run_id }}"
                hx-target="#ts-stage" hx-swap="innerHTML"
                class="btn">⟲ 리셋</button>
      </div>
    </div>
  </div>
</div>
<script>
  (function() {
    var fig = {{ figure|tojson }};
    var el = document.getElementById('ts-plot-{{ run_id }}');
    if (el && window.Plotly) Plotly.react(el, fig.data, fig.layout, {responsive: true, displayModeBar: false});
  })();
</script>
```

- [ ] **Step 6: Manual 확인**

uvicorn reload 후 브라우저: `/tab/trafficsim` → 시작 누르면 빈 맵에 자차(★) 표시, 2 Hz로 tick 카운터 증가하는 것 확인.

- [ ] **Step 7: Commit**

```bash
git add kadap-poc-v2/trafficsim/engine.py \
        kadap-poc-v2/tests/trafficsim/test_engine.py \
        kadap-poc-v2/templates/_trafficsim_frame.html \
        kadap-poc-v2/main.py
git commit -m "feat(trafficsim): add runtime registry + HTMX polling + Plotly 2D figure"
```

---

### Task 12: 재생 컨트롤 (일시정지·step·reset)

**Files:**
- Modify: `kadap-poc-v2/main.py`

`_trafficsim_frame.html` 에서 이미 버튼 ref 했으므로 endpoint만 추가.

- [ ] **Step 1: 컨트롤 endpoint 추가**

`kadap-poc-v2/main.py`:
```python
@app.post("/trafficsim/control", response_class=HTMLResponse)
async def trafficsim_control(request: Request, run_id: str, action: str):
    state = TRAFFICSIM_RUNS.get(run_id)
    if not state:
        return HTMLResponse(
            '<div class="muted">세션 만료 — 다시 시작하세요.</div>',
            status_code=200,
        )
    sim: Sim = state["sim"]
    if action == "toggle_pause":
        state["paused"] = not state["paused"]
    elif action == "step":
        sim.tick()
    return templates.TemplateResponse(
        request,
        "_trafficsim_frame.html",
        {
            "run_id": run_id,
            "sim": sim,
            "figure": build_plotly_figure(sim),
            "paused": state["paused"],
        },
    )


@app.post("/trafficsim/reset", response_class=HTMLResponse)
async def trafficsim_reset(request: Request, run_id: str):
    state = TRAFFICSIM_RUNS.pop(run_id, None)
    return HTMLResponse(
        '<div class="muted">리셋됨. 시나리오·로직을 다시 선택하세요.</div>',
        status_code=200,
    )
```

- [ ] **Step 2: Manual 확인**

브라우저에서 ⏸ → 카운터 멈춤, ⏭ → 1 step 진행, ▶ 재개 → 재진행, ⟲ → 첫 화면 복귀.
일시정지 중 polling은 멈추지 않지만 sim.tick()이 호출되지 않으므로 사실상 정지.

- [ ] **Step 3: Commit**

```bash
git add kadap-poc-v2/main.py
git commit -m "feat(trafficsim): add pause/step/reset controls"
```

---

## Phase 4 — 시나리오 + 추가 logics

### Task 13: 시나리오 base + scen_01 (보호좌회전 + 횡단보도 보행자)

**Files:**
- Create: `kadap-poc-v2/trafficsim/scenarios/__init__.py`
- Create: `kadap-poc-v2/trafficsim/scenarios/base.py`
- Create: `kadap-poc-v2/trafficsim/scenarios/scen_01_pedestrian.py`
- Test: `kadap-poc-v2/tests/trafficsim/test_scenarios.py`

각 시나리오는 `setup(sim: Sim) -> None`로 sim에 agents·initial ego 위치·V2X inject를 세팅. 시나리오 카탈로그(`SCENARIOS: dict[str, Callable]`)는 `base.py`에서 import 시 등록.

- [ ] **Step 1: Write the failing test**

`kadap-poc-v2/tests/trafficsim/test_scenarios.py`:
```python
from trafficsim.avlogic.rule_based import RuleBasedLogic
from trafficsim.engine import Sim, SimConfig
from trafficsim.scenarios.base import SCENARIOS, apply_scenario
from trafficsim.world import load_default_map


def _fresh_sim():
    return Sim(SimConfig(dt=0.1), logic=RuleBasedLogic(), world=load_default_map())


def test_scen_01_registered():
    assert "scen_01" in SCENARIOS


def test_scen_01_places_pedestrian_and_traffic_light():
    sim = _fresh_sim()
    apply_scenario(sim, "scen_01")
    assert len(sim.traffic_lights) >= 1
    assert len(sim.pedestrians) >= 1


def test_scen_01_ego_starts_west_of_main_intersection():
    sim = _fresh_sim()
    apply_scenario(sim, "scen_01")
    assert sim.ego.x < 0
    assert abs(sim.ego.y) < 5.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_scenarios.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`kadap-poc-v2/trafficsim/scenarios/__init__.py`:
```python
from trafficsim.scenarios import scen_01_pedestrian  # noqa: F401  (등록)
```

`kadap-poc-v2/trafficsim/scenarios/base.py`:
```python
"""시나리오 카탈로그 + sim setup 함수 registry."""

from __future__ import annotations

from typing import Callable

from trafficsim.engine import Sim

SCENARIOS: dict[str, Callable[[Sim], None]] = {}


def register(key: str):
    def deco(fn: Callable[[Sim], None]) -> Callable[[Sim], None]:
        SCENARIOS[key] = fn
        return fn
    return deco


def apply_scenario(sim: Sim, key: str) -> None:
    if key not in SCENARIOS:
        raise KeyError(f"unknown scenario: {key}")
    SCENARIOS[key](sim)
```

`kadap-poc-v2/trafficsim/scenarios/scen_01_pedestrian.py`:
```python
"""시나리오 1 — 보호좌회전 청신호 5초, 횡단보도 보행자 동시 진입.

V2X-aware 로직: 보행자 PSM 받으면 정지.
V2X-blind 로직: 좌회전 시도 → 충돌 위험.
"""

from __future__ import annotations

from trafficsim.agents import Pedestrian, TrafficLight
from trafficsim.engine import Sim
from trafficsim.scenarios.base import register


@register("scen_01")
def setup(sim: Sim) -> None:
    sim.ego.x = -30.0
    sim.ego.y = 0.0
    sim.ego.yaw = 0.0
    sim.ego.speed = 8.0

    tl = TrafficLight(id="rsu_main", x=0.0, y=0.0)
    tl.offset = 10.0  # GREEN 잔여 5초로 시작 (15 - 10 = 5)
    sim.add_traffic_light(tl)

    ped = Pedestrian(
        id="ped_main",
        path=[(0.0, -4.0), (0.0, 4.0), (0.0, 12.0)],
        speed=1.4,
    )
    sim.add_pedestrian(ped)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_scenarios.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: main.py에서 시나리오 적용 연결**

`kadap-poc-v2/main.py` — `_apply_scenario` 를 실제로 호출하도록 수정:
```python
from trafficsim.scenarios.base import apply_scenario as _apply_scn
# (기존 import 블록에 추가)


def _apply_scenario(sim: Sim, key: str) -> None:
    _apply_scn(sim, key)
```

그리고 import 부수효과를 위해 `trafficsim.scenarios` 패키지를 import:
```python
import trafficsim.scenarios  # noqa: F401  — 시나리오 모듈 등록
```

- [ ] **Step 6: Manual 확인 + commit**

브라우저: 시나리오 1 선택 → 시작 → 보행자 1명, 신호등 1개, 자차 (-30, 0) 표시. 자차가 cruising → 보행자 가까워지면 RuleBased가 정지.

```bash
git add kadap-poc-v2/trafficsim/scenarios/ \
        kadap-poc-v2/tests/trafficsim/test_scenarios.py \
        kadap-poc-v2/main.py
git commit -m "feat(trafficsim): add scenario registry + scen_01 (left turn + pedestrian)"
```

---

### Task 14: 시나리오 2 (신호등 고장 + RSU 우회 안내)

**Files:**
- Create: `kadap-poc-v2/trafficsim/scenarios/scen_02_signal_fail.py`
- Modify: `kadap-poc-v2/trafficsim/scenarios/__init__.py`
- Modify: `kadap-poc-v2/tests/trafficsim/test_scenarios.py` (append)

- [ ] **Step 1: Write the failing test (append)**

`kadap-poc-v2/tests/trafficsim/test_scenarios.py`에 추가:
```python
def test_scen_02_registered():
    assert "scen_02" in SCENARIOS


def test_scen_02_has_broken_light_and_tim():
    sim = _fresh_sim()
    apply_scenario(sim, "scen_02")
    sim.tick()  # 한 tick 돌려서 v2x 인젝션 적용 확인
    assert any(tl.broken for tl in sim.traffic_lights)
    assert any(m.kind == "TIM" for m in sim.injected_msgs)
```

- [ ] **Step 2: Run test (FAIL)**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_scenarios.py -v`
Expected: 새 2개 FAIL

- [ ] **Step 3: Implement**

`kadap-poc-v2/trafficsim/scenarios/scen_02_signal_fail.py`:
```python
"""시나리오 2 — 동쪽 교차로 신호등 고장 + RSU가 TIM(우회)·RSI(고장) 송출.

V2X-aware: TIM·RSI 받고 감속/우회 → 안전 통과
V2X-blind: 신호등 OFF 못 보고 그대로 진입 → 위험
"""

from __future__ import annotations

from trafficsim.agents import TrafficLight
from trafficsim.engine import Sim
from trafficsim.scenarios.base import register
from trafficsim.v2x import rsi_message, tim_message


@register("scen_02")
def setup(sim: Sim) -> None:
    sim.ego.x = 30.0
    sim.ego.y = 0.0
    sim.ego.yaw = 0.0
    sim.ego.speed = 8.0

    tl_broken = TrafficLight(id="rsu_east", x=100.0, y=0.0, broken=True)
    sim.add_traffic_light(tl_broken)

    sim.inject_message(
        rsi_message(
            source_id="rsu_east",
            message="SIGNAL_FAILURE",
            severity="HIGH",
            x=100.0,
            y=0.0,
            rx_time=0.0,
        )
    )
    sim.inject_message(
        tim_message(
            source_id="rsu_east",
            message="DETOUR",
            severity="HIGH",
            rx_time=0.0,
        )
    )
```

`kadap-poc-v2/trafficsim/scenarios/__init__.py`:
```python
from trafficsim.scenarios import scen_01_pedestrian  # noqa: F401
from trafficsim.scenarios import scen_02_signal_fail  # noqa: F401
```

- [ ] **Step 4: Run test (PASS)**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_scenarios.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add kadap-poc-v2/trafficsim/scenarios/scen_02_signal_fail.py \
        kadap-poc-v2/trafficsim/scenarios/__init__.py \
        kadap-poc-v2/tests/trafficsim/test_scenarios.py
git commit -m "feat(trafficsim): add scen_02 (broken signal + RSU TIM/RSI)"
```

---

### Task 15: 시나리오 3 (골목 합류 + 사각지대 BSM)

**Files:**
- Create: `kadap-poc-v2/trafficsim/scenarios/scen_03_alley_merge.py`
- Modify: `kadap-poc-v2/trafficsim/scenarios/__init__.py`
- Modify: `kadap-poc-v2/tests/trafficsim/test_scenarios.py` (append)

- [ ] **Step 1: Write the failing test (append)**

`kadap-poc-v2/tests/trafficsim/test_scenarios.py`에 추가:
```python
def test_scen_03_registered():
    assert "scen_03" in SCENARIOS


def test_scen_03_has_blind_side_vehicle_in_alley():
    sim = _fresh_sim()
    apply_scenario(sim, "scen_03")
    assert len(sim.vehicles) >= 1
    # 골목 차는 자차 시야 밖 (자차는 동쪽 방향, 차는 북쪽 골목)
    v = sim.vehicles[0]
    assert v.y > 5.0
```

- [ ] **Step 2: Run test (FAIL)**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_scenarios.py -v`
Expected: 새 2개 FAIL

- [ ] **Step 3: Implement**

`kadap-poc-v2/trafficsim/scenarios/scen_03_alley_merge.py`:
```python
"""시나리오 3 — 골목에서 합류하는 주변차가 자차 시야 사각지대에 있음.

V2X-aware: BSM 받고 감속·양보 → 안전
V2X-blind: BSM 없음 + 시야 가림 → 합류 충돌 위험
"""

from __future__ import annotations

from trafficsim.agents import Vehicle
from trafficsim.engine import Sim
from trafficsim.scenarios.base import register


@register("scen_03")
def setup(sim: Sim) -> None:
    sim.ego.x = 30.0
    sim.ego.y = 0.0
    sim.ego.yaw = 0.0
    sim.ego.speed = 8.0

    # 골목에서 남쪽으로 합류하는 차 — 자차 yaw 동쪽이므로 북쪽 차는 FOV 밖
    alley_car = Vehicle(
        id="veh_alley",
        path=[(60.0, 25.0), (60.0, 5.0), (80.0, 0.0)],
        desired_speed=6.0,
    )
    alley_car.speed = 5.0
    sim.add_vehicle(alley_car)
```

`kadap-poc-v2/trafficsim/scenarios/__init__.py`:
```python
from trafficsim.scenarios import scen_01_pedestrian  # noqa: F401
from trafficsim.scenarios import scen_02_signal_fail  # noqa: F401
from trafficsim.scenarios import scen_03_alley_merge  # noqa: F401
```

- [ ] **Step 4: Run test (PASS)**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_scenarios.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add kadap-poc-v2/trafficsim/scenarios/scen_03_alley_merge.py \
        kadap-poc-v2/trafficsim/scenarios/__init__.py \
        kadap-poc-v2/tests/trafficsim/test_scenarios.py
git commit -m "feat(trafficsim): add scen_03 (alley merge + blind-side BSM)"
```

---

### Task 16: AlpamayoLogic proxy

**Files:**
- Create: `kadap-poc-v2/trafficsim/avlogic/alpamayo_proxy.py`
- Test: `kadap-poc-v2/tests/trafficsim/test_avlogic_alpamayo.py`

전제: Alpamayo 1.5 VLA inference 호출은 비범위(카메라 frame 일치 mock이 아직 없음). 본 task는 **proxy**로서 다음과 같이 동작:
- 호출 시 백엔드 helper(`alpamayo_call`)에 obs를 넘기고 Action을 받음
- 백엔드는 환경변수 `TRAFFICSIM_ALPAMAYO_MODE`에 따라 동작:
  - `"mock"` (디폴트): RuleBasedLogic 결과 + reason에 "[Alpamayo mock]" 접두
  - `"live"`: 실제 호출 (별도 작업)

이로써 "프로토타입에 Alpamayo 슬롯이 존재"하지만 카메라 sync 미해결로 mock 동작하는 것을 명시.

- [ ] **Step 1: Write the failing test**

`kadap-poc-v2/tests/trafficsim/test_avlogic_alpamayo.py`:
```python
import os

from trafficsim.avlogic.alpamayo_proxy import AlpamayoLogic
from trafficsim.avlogic.interface import (
    EgoState,
    Observation,
    PerceptionView,
)


def _obs():
    return Observation(
        ego=EgoState(x=0.0, y=0.0, yaw=0.0, speed=8.0, accel=0.0),
        v2x_messages=[],
        perception=PerceptionView(objects=[]),
        t=0.0,
    )


def test_alpamayo_logic_returns_action(monkeypatch):
    monkeypatch.setenv("TRAFFICSIM_ALPAMAYO_MODE", "mock")
    a = AlpamayoLogic().decide(_obs())
    assert a is not None
    assert "Alpamayo" in a.reason


def test_alpamayo_logic_mock_uses_rule_based_baseline(monkeypatch):
    monkeypatch.setenv("TRAFFICSIM_ALPAMAYO_MODE", "mock")
    a = AlpamayoLogic().decide(_obs())
    assert a.target_speed == 8.0  # cruise


def test_alpamayo_logic_live_mode_raises_when_unavailable(monkeypatch):
    monkeypatch.setenv("TRAFFICSIM_ALPAMAYO_MODE", "live")
    monkeypatch.setenv("TRAFFICSIM_ALPAMAYO_ENDPOINT", "")
    import pytest as _pytest
    with _pytest.raises(RuntimeError):
        AlpamayoLogic().decide(_obs())
```

- [ ] **Step 2: Run test (FAIL)**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_avlogic_alpamayo.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`kadap-poc-v2/trafficsim/avlogic/alpamayo_proxy.py`:
```python
"""AlpamayoLogic — Alpamayo VLA 호출 proxy.

mode=mock (디폴트): RuleBasedLogic 결과 + Alpamayo 접두. 카메라 sync 미구현이므로
  실제 호출은 비범위. UI/시연용으로 'Alpamayo 슬롯이 살아있음'을 보여줌.
mode=live: 실제 endpoint 호출 (TRAFFICSIM_ALPAMAYO_ENDPOINT 필요).
"""

from __future__ import annotations

import os

from trafficsim.avlogic.interface import Action, Observation
from trafficsim.avlogic.rule_based import RuleBasedLogic


class AlpamayoLogic:
    def __init__(self) -> None:
        self._baseline = RuleBasedLogic()

    def decide(self, obs: Observation) -> Action:
        mode = os.environ.get("TRAFFICSIM_ALPAMAYO_MODE", "mock")
        if mode == "live":
            endpoint = os.environ.get("TRAFFICSIM_ALPAMAYO_ENDPOINT", "")
            if not endpoint:
                raise RuntimeError(
                    "TRAFFICSIM_ALPAMAYO_ENDPOINT not set — live mode unavailable"
                )
            # 실제 라이브 호출은 비범위 (카메라 sync 미구현)
            raise RuntimeError("live Alpamayo not implemented (camera sync pending)")
        base = self._baseline.decide(obs)
        return Action(
            target_speed=base.target_speed,
            steering=base.steering,
            reason=f"[Alpamayo mock] {base.reason}",
        )
```

- [ ] **Step 4: Run test (PASS)**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_avlogic_alpamayo.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: main.py에 등록**

`kadap-poc-v2/main.py`:
```python
from trafficsim.avlogic.alpamayo_proxy import AlpamayoLogic


def _make_logic(key: str):
    if key == "rule_based":
        return RuleBasedLogic()
    if key == "alpamayo":
        return AlpamayoLogic()
    return RuleBasedLogic()
```

- [ ] **Step 6: Commit**

```bash
git add kadap-poc-v2/trafficsim/avlogic/alpamayo_proxy.py \
        kadap-poc-v2/tests/trafficsim/test_avlogic_alpamayo.py \
        kadap-poc-v2/main.py
git commit -m "feat(trafficsim): add AlpamayoLogic proxy (mock + live mode stub)"
```

---

### Task 17: V2XBlindLogic (비교군)

**Files:**
- Create: `kadap-poc-v2/trafficsim/avlogic/v2x_blind.py`
- Test: `kadap-poc-v2/tests/trafficsim/test_avlogic_v2x_blind.py`

V2X 메시지 무시. perception만 사용. 같은 시나리오에서 V2X-aware 대비 위험한 결정을 내리는 것을 보여주는 게 목적.

- [ ] **Step 1: Write the failing test**

`kadap-poc-v2/tests/trafficsim/test_avlogic_v2x_blind.py`:
```python
from trafficsim.avlogic.interface import (
    EgoState,
    Observation,
    PerceivedObject,
    PerceptionView,
    V2XMsg,
)
from trafficsim.avlogic.v2x_blind import V2XBlindLogic


def _obs(v2x=None, perception_objs=None):
    return Observation(
        ego=EgoState(x=0.0, y=0.0, yaw=0.0, speed=8.0, accel=0.0),
        v2x_messages=v2x or [],
        perception=PerceptionView(objects=perception_objs or []),
        t=0.0,
    )


def test_ignores_v2x_messages():
    psm = V2XMsg(
        kind="PSM",
        payload={"x": 5.0, "y": 0.0, "vx": 0.0, "vy": 0.0},
        source_id="ped_1",
        rx_time=0.0,
    )
    a = V2XBlindLogic().decide(_obs(v2x=[psm]))
    # 동일 obs에서 RuleBased는 정지 — V2XBlind는 cruise
    assert a.target_speed >= 5.0


def test_decel_when_perceives_close_vehicle():
    a = V2XBlindLogic().decide(_obs(perception_objs=[
        PerceivedObject(obj_type="vehicle", x=8.0, y=0.0, speed=2.0)
    ]))
    assert a.target_speed < 8.0


def test_cruise_when_clear():
    a = V2XBlindLogic().decide(_obs())
    assert a.target_speed == 8.0
```

- [ ] **Step 2: Run test (FAIL)**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_avlogic_v2x_blind.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`kadap-poc-v2/trafficsim/avlogic/v2x_blind.py`:
```python
"""V2XBlindLogic — V2X 무시, perception만으로 운행.

V2X 효과 강조용 비교군. 같은 시나리오에서 V2X-aware 대비 위험 결정을 내림.
"""

from __future__ import annotations

import math

from trafficsim.avlogic.interface import Action, Observation

CRUISE_SPEED = 8.0
PERCEPTION_DECEL_RADIUS = 12.0


class V2XBlindLogic:
    def decide(self, obs: Observation) -> Action:
        ego = obs.ego
        closest = None
        for o in obs.perception.objects:
            d = math.hypot(o.x - ego.x, o.y - ego.y)
            if closest is None or d < closest[0]:
                closest = (d, o)
        if closest and closest[0] < PERCEPTION_DECEL_RADIUS:
            return Action(
                target_speed=max(0.0, closest[1].speed),
                steering=0.0,
                reason=f"perception 전방 {closest[0]:.1f}m — V2X 무시",
            )
        return Action(target_speed=CRUISE_SPEED, steering=0.0, reason="cruise (V2X 무시)")
```

- [ ] **Step 4: Run test (PASS)**

Run: `cd kadap-poc-v2 && python -m pytest tests/trafficsim/test_avlogic_v2x_blind.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: main.py에 등록**

`kadap-poc-v2/main.py`:
```python
from trafficsim.avlogic.v2x_blind import V2XBlindLogic


def _make_logic(key: str):
    if key == "rule_based":
        return RuleBasedLogic()
    if key == "alpamayo":
        return AlpamayoLogic()
    if key == "v2x_blind":
        return V2XBlindLogic()
    return RuleBasedLogic()
```

- [ ] **Step 6: Commit**

```bash
git add kadap-poc-v2/trafficsim/avlogic/v2x_blind.py \
        kadap-poc-v2/tests/trafficsim/test_avlogic_v2x_blind.py \
        kadap-poc-v2/main.py
git commit -m "feat(trafficsim): add V2XBlindLogic (perception-only, comparison baseline)"
```

---

## Phase 5 — 안정화 + 시연 검증

### Task 18: 사용 가이드 + 9 조합 시연 검증

**Files:**
- Create: `kadap-poc-v2/trafficsim/README.md` (사용 가이드)
- Modify: `kadap-poc-v2/templates/tab_trafficsim.html` (시연 안내 박스 추가)

- [ ] **Step 1: 사용 가이드 작성**

`kadap-poc-v2/trafficsim/README.md`:
```markdown
# 능동 traffic sim — 사용 가이드

## 개요
V2X 인프라가 포함된 시뮬레이션 환경. 자율주행 로직을 swappable plugin으로 끼워서
동일 환경 하에 정량 비교 가능.

## 빠른 시작
1. `python kadap-poc-v2/main.py` (uvicorn 띄우기)
2. 브라우저 → 탭 "🗺 능동 traffic sim"
3. 시나리오 + 로직 선택 → ▶ 시작
4. 5 Hz polling으로 자동 진행. ⏸ / ⏭ / ⟲ 컨트롤

## 시나리오 3개
| # | 시나리오 | V2X 메시지 | 예상 결과 |
|---|---|---|---|
| 1 | 보호좌회전 + 횡단보도 보행자 | SPaT, PSM | RuleBased/Alpamayo 정지, V2XBlind 진입 위험 |
| 2 | 신호등 고장 + RSU 우회 | RSI, TIM | RuleBased 감속, V2XBlind 무시 |
| 3 | 골목 합류 + 사각지대 BSM | BSM | RuleBased 양보, V2XBlind 합류 시도 |

## 내장 자율주행 로직 3개
- **RuleBased**: V2X 우선순위 hand-written
- **Alpamayo**: VLA proxy (mock — 카메라 sync 후속)
- **V2XBlind**: V2X 무시, perception만 사용 (비교군)

## 연구자가 자체 로직 inject 하기
`trafficsim/avlogic/` 아래 새 파일 추가하고 `AVLogic` Protocol 구현:
```python
from trafficsim.avlogic.interface import Action, Observation

class MyLogic:
    def decide(self, obs: Observation) -> Action:
        # obs.ego, obs.v2x_messages, obs.perception, obs.t 사용
        return Action(target_speed=5.0, steering=0.0, reason="my-logic")
```
`main.py`의 `_make_logic`과 `TRAFFICSIM_LOGICS`에 추가하고 서버 재시작.
(UI 업로드는 비범위.)
```

- [ ] **Step 2: tab_trafficsim.html 상단에 안내 박스**

`kadap-poc-v2/templates/tab_trafficsim.html` — `<h2>` 다음에 추가:
```html
<div class="muted" style="background:#1e2a3a; padding:0.75rem; border-left:3px solid #3498db; margin-bottom:1rem;">
  <strong>What's here:</strong> V2X (신호등·RSU·보행자·주변차) 메시지가 흐르는
  시뮬레이션 환경 + 자율주행 로직 3개(RuleBased / Alpamayo mock / V2X-blind).
  같은 시나리오에서 로직을 바꿔보며 정성 비교하세요. (Alpamayo live 호출은 카메라
  sync 후속 작업.)
</div>
```

- [ ] **Step 3: 9 조합 시연 검증 체크리스트**

전체 자동화는 비범위 — manual로 확인. 한 시나리오당 ~30s 진행:
- 시나리오 1 × RuleBased → 보행자 보고 정지 ✓
- 시나리오 1 × Alpamayo → 보행자 보고 정지 (Alpamayo mock 접두) ✓
- 시나리오 1 × V2XBlind → 보행자 PSM 무시, 미진입 보행자 perception에는 들어옴 (FOV) ✓
- 시나리오 2 × RuleBased → TIM 받고 감속 ✓
- 시나리오 2 × Alpamayo → 감속 (mock 접두) ✓
- 시나리오 2 × V2XBlind → 신호등 OFF / TIM 무시 → 통과 ✓
- 시나리오 3 × RuleBased → BSM 받고 양보 ✓
- 시나리오 3 × Alpamayo → 양보 (mock 접두) ✓
- 시나리오 3 × V2XBlind → BSM 무시, perception 사각지대 → 위험 ✓

- [ ] **Step 4: 전체 테스트 실행 (regression)**

Run: `cd kadap-poc-v2 && python -m pytest tests/ -v`
Expected: 모든 test PASS (Task 1-17 합계 약 50개)

- [ ] **Step 5: Commit**

```bash
git add kadap-poc-v2/trafficsim/README.md \
        kadap-poc-v2/templates/tab_trafficsim.html
git commit -m "feat(trafficsim): add usage guide + UI introduction box"
```

---

## Verification (전체)

- [ ] 새 탭 "🗺 능동 traffic sim" 메뉴에 노출됨
- [ ] 시나리오 3개 × 로직 3개 = 9 조합 모두 ▶ 시작 → tick 진행 → ⏸/⏭/⟲ 동작
- [ ] 자차/보행자/주변차/신호등 모두 Plotly 맵에 표시되고 매 frame 업데이트됨
- [ ] 로직 판단 reason이 UI에 표시됨
- [ ] V2X-blind vs V2X-aware 차이가 시각적으로 드러남 (시나리오 1·2·3)
- [ ] pytest 전체 통과
- [ ] AlpamayoLogic proxy는 mock 모드에서 동작하고 reason에 `[Alpamayo mock]` 접두
- [ ] `trafficsim/README.md` 가이드 존재

---

## Out of Scope (재확인)

- CARLA/SUMO/Mosaic 통합
- HD map 정식 import
- Alpamayo VLA 실제 호출 (카메라 sync 미해결)
- 연구자 SDK 정식 패키징
- 멀티 사용자 concurrency
- 시나리오 카탈로그 확장 (4개 이상)
- NRE Closed-Loop과의 통합
