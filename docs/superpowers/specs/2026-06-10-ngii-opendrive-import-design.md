# NGII OpenDRIVE Import — 능동 traffic sim 데이터 소스 확장 설계 스펙

**작성일**: 2026-06-10
**저자**: PoC 작성자
**상태**: User review 대기

---

## Context

### 배경
"능동 traffic sim" 데모 탭 1차 PoC ([2026-06-09 design](2026-06-09-active-traffic-sim-design.md))는 mock GeoJSON 9개 feature (2 교차로 + 골목 + 횡단보도 2)로 한국형 도로를 흉내냈습니다. KATECH 시연에서 "한국형 PoC" 주장에 실제 데이터 뒷받침이 필요합니다.

### 데이터 소스 결정
**국토지리정보원(NGII) 정밀도로지도** — OpenDRIVE(.xodr) 포맷, 무료 공개. 검색으로 다음을 확인:

- 입수: `map.ngii.go.kr/ms/pblictn/preciseRoadMap.do` 직접 다운로드 (회원가입), 또는 `data.go.kr/data/15059912`
- 포맷: OpenDRIVE — 자율주행 시뮬레이션 업계 표준 (CARLA/SUMO/Apollo 모두 지원), 향후 통합에 그대로 사용 가능
- 커버리지: 고속도로·일반국도 완료. 도심 4차로 이상은 2027 목표
- KATECH가 2022년 "정밀도로지도 제작 및 데이터 가시화 시스템 개발" RFP 발행 — KATECH 사내 보유 데이터 활용 가능성 있음

### 단계적 도입
**Prototype-first** (메모리 [[feedback_prototype_over_reports]] 정합). NGII 데이터 입수 절차를 기다리는 대신:
1. OpenDRIVE 파이프라인을 esmini 공개 sample로 먼저 구축·검증
2. NGII 데이터 입수 후 `load_opendrive_map(path=…)` 인자 한 줄 변경으로 즉시 교체

### 본 문서가 다루는 범위
1차 prototype 단계의 OpenDRIVE import. 시나리오 좌표 통합·NGII 자동화·신호등 자동 추출은 비범위.

---

## Architecture

```
NGII/esmini OpenDRIVE (.xodr)
        │
        ▼
[opendrive_loader.py]   ← lxml 직접 파싱 (외부 OpenDRIVE 라이브러리 없음)
        │  내부 IR (dict)
        ▼
[world.py: load_opendrive_map(path)]
        │  WorldMap(lanes, intersections, crosswalks)  — 기존 데이터 모델 그대로
        ▼
[engine.py: Sim(world=...)]   ← 기존 코드 변경 없음
```

**핵심 원칙**: 기존 `WorldMap` / `Lane` / `Intersection` / `Crosswalk` 데이터 모델 변경 없음. `load_default_map()`은 mock GeoJSON 그대로 보존. 새 함수 `load_opendrive_map(path)` 추가. 시나리오·로직·V2X·UI 모두 데이터 소스를 모르고 동작.

---

## Components

| 파일 | 상태 | 책임 |
|---|---|---|
| `kadap-poc-v2/trafficsim/opendrive_loader.py` | NEW | `.xodr` lxml 파싱 → 내부 IR dict (roads, junctions, objects) |
| `kadap-poc-v2/trafficsim/world.py` | MODIFY | `load_opendrive_map(path)` 추가, IR → `WorldMap` 변환 |
| `kadap-poc-v2/trafficsim/maps/__init__.py` | NEW | empty package marker |
| `kadap-poc-v2/trafficsim/maps/e6mini.xodr` | NEW | esmini BSD-3 sample fixture |
| `kadap-poc-v2/trafficsim/maps/NOTICE` | NEW | 라이선스 명기 |
| `kadap-poc-v2/trafficsim/engine.py` | MODIFY | `build_plotly_figure` viewport 동적 산정 (lane polyline min/max + margin) |
| `kadap-poc-v2/templates/tab_trafficsim.html` | MODIFY | 맵 소스 토글 (mock / opendrive) |
| `kadap-poc-v2/main.py` | MODIFY | `MAP_SOURCES` registry, `map_source` Form 파라미터, `/trafficsim/start`의 opendrive 분기 |
| `kadap-poc-v2/tests/trafficsim/test_opendrive_loader.py` | NEW | inline xodr 문자열 → IR 검증 |
| `kadap-poc-v2/tests/trafficsim/test_opendrive_map.py` | NEW | `load_opendrive_map(e6mini.xodr)` → WorldMap shape 검증 |
| `kadap-poc-v2/tests/trafficsim/test_dynamic_viewport.py` | NEW | viewport range가 polyline min/max + margin인지 검증 |

### 파싱 라이브러리 선택
**`lxml` 직접 파싱**. 전용 라이브러리(`pyOpenDRIVE`/`opendrive2lanelet`)는 도입 비용 크고 유지보수 약함. OpenDRIVE 1.x XML 스키마는 공개되어 있고, 우리는 다음 3개 element만 추출:
- `<road><planView>` — geometry → polyline
- `<junction>` — center 좌표
- `<object type="crosswalk">` — polyline

### 파싱 범위 (1차)
- `<road><planView><geometry type="line">` — 직선 (start + length → 2 points)
- `<road><planView><geometry type="arc">` — 원호 (curvature, length → 10점 sampling)
- `<road><planView><geometry type="spiral">` — clothoid (start↔end curvature linear interp → 10점 거친 근사)
- `<road><lanes>` — `driving` lane만, lane id+width 무시(폴리라인은 road reference line 기준)
- `<road>` `speed` attribute → Lane.speed_limit (없으면 13.8)
- `<junction>` — `<connection>`의 incomingRoad/connectingRoad들의 road centerline 끝점 평균 → 중심점
- `<object type="crosswalk">` — `s`, `t`, `length`, `width`로 4점 사각형 polyline (s,t → road 기준 → inertial(x,y))

### 좌표계
- OpenDRIVE inertial frame: x=east, y=north, m. 우리 sim과 동일.
- xodr에 따라 좌표가 크고 음수일 수 있음 → 로더 시점에 **origin 보정**: 모든 lanes의 min(x), min(y)를 0,0으로 평행이동.

---

## Data Flow

```
1. lxml.etree.parse(path).getroot()
2. Iterate <road id=...>:
     a. planView 각 geometry → polyline 점들 누적
        · line: 2점
        · arc: curvature·length → 10점 sample
        · spiral: start↔end curvature 선형 보간 → 10점 거친 근사
     b. polyline에 lane id="road_{roadId}" speed_limit=road.@speed or 13.8 → Lane
3. Iterate <junction id=...>:
     a. <connection>의 incoming/connecting roads의 polyline 끝점 들 평균 → 중심
     b. Intersection(id=f"j_{junctionId}", x, y)
4. Iterate <road>/<objects>/<object type="crosswalk">:
     a. road의 s 좌표 → road polyline 상의 점 (s를 길이로 lookup)
     b. road tangent 방향 → t 방향 unit vector
     c. (s,t,length,width) → 4점 사각형
     d. Crosswalk(id=f"cw_{objectId}", polyline, axis="y")
5. 모든 polyline의 min(x), min(y)를 (0,0)으로 평행이동
6. WorldMap(lanes, intersections, crosswalks) 반환
```

---

## Fixture 선정

**1차: esmini `e6mini.xodr`** — esmini 프로젝트가 BSD-3로 공개하는 4-way 단순 교차로 OpenDRIVE sample. 시연 시나리오 3개(보호좌회전, 신호등 고장, 골목 합류) 매핑 가능. 다운로드:
- 출처: `https://github.com/esmini/esmini` (`resources/xodr/e6mini.xodr`)
- 라이선스: BSD-3 Clause
- 보관: `kadap-poc-v2/trafficsim/maps/e6mini.xodr` + `NOTICE` 파일 동봉

**2차 (이번 작업 비범위): NGII OpenDRIVE 데이터**
- `map.ngii.go.kr` 회원가입 + 다운로드. 입수 후 `kadap-poc-v2/trafficsim/maps/ngii_<지역>.xodr`에 저장 + 라이선스 NOTICE 추가
- 같은 `load_opendrive_map(path)` 함수로 즉시 처리

---

## 시나리오 좌표 정책

**1차는 manual 분리** (anchor 추상화는 후속):

- `load_default_map()` (mock GeoJSON) — 기존 시나리오 3개(scen_01/02/03)는 그대로 mock map 좌표에서 동작
- `load_opendrive_map(path)` (OpenDRIVE) — **시나리오 통합 없음**. NGII/esmini 맵은 "데이터 import 시각화 검증" 용도로 우선
- UI에서 맵 소스 선택 시:
  - "mock" → 시연 시나리오 3개 × 로직 3개 = 9 조합 그대로 동작 (현재 데모)
  - "opendrive: e6mini" → 맵만 표시, 자차/시나리오 agent 없음 또는 0,0에 정지 ego만

이로써 **기존 9 조합 데모는 변경 없음**, NGII 맵은 시각화 단계까지 본 작업 범위. 시나리오 통합은 데이터 입수 후 별도 작업.

---

## UI 변경

### 맵 소스 토글
`tab_trafficsim.html` 상단 시나리오/로직 셀렉터 위에 새 fieldset:

```html
<fieldset>
  <legend>맵 소스</legend>
  <label><input type="radio" name="map_source" value="mock" checked> Mock 한국형 (기본)</label>
  <label><input type="radio" name="map_source" value="opendrive_e6mini"
         {% if not has_opendrive %}disabled{% endif %}>
         OpenDRIVE: esmini e6mini</label>
</fieldset>
```

`has_opendrive` = `e6mini.xodr` 파일 존재 여부.

### 시작 분기
- `map_source == "mock"` → 기존 `/trafficsim/start` 흐름 그대로
- `map_source == "opendrive_e6mini"` → 새 분기:
  - `Sim(world=load_opendrive_map(maps/e6mini.xodr))` 생성
  - 시나리오 setup 호출 X (시나리오 통합 비범위)
  - logic은 `_NoopLogic` (main.py 내부 정의): `decide(obs) -> Action(target_speed=0, steering=0, reason="opendrive 시각화 모드")` — 자차는 first lane polyline의 첫 점에 배치, 정지 상태 유지
  - 시나리오 / 로직 라디오 그룹은 폼 검증에서 무시 (받아도 미사용)

### 동적 viewport
`build_plotly_figure`:
```python
if sim.world and sim.world.lanes:
    xs = [pt[0] for lane in sim.world.lanes for pt in lane.polyline]
    ys = [pt[1] for lane in sim.world.lanes for pt in lane.polyline]
    margin = 20.0
    x_range = [min(xs) - margin, max(xs) + margin]
    y_range = [min(ys) - margin, max(ys) + margin]
else:
    x_range, y_range = [-50, 250], [-30, 100]  # fallback
layout["xaxis"]["range"] = x_range
layout["yaxis"]["range"] = y_range
```

---

## Testing

| 레벨 | 대상 | 검증 |
|---|---|---|
| Unit | `opendrive_loader.parse_xodr(xml_str)` | inline 최소 xodr (1 road + 1 junction + 1 crosswalk) → IR dict의 roads/junctions/crosswalks 개수 + id |
| Unit | `opendrive_loader._sample_geometry({type: "line", ...})` | 직선 geometry 2점 sampling |
| Unit | `opendrive_loader._sample_geometry({type: "arc", curvature: ..., length: ...})` | 원호 → 첫 점이 start, 마지막 점이 끝, 중간 점이 곡선 위 |
| Unit | `world.load_opendrive_map(maps/e6mini.xodr)` | `len(lanes) >= 4`, `len(intersections) >= 1` |
| Unit | `build_plotly_figure` 동적 viewport | lanes 좌표 범위 → x_range/y_range가 min/max + 20 margin |
| Integration | mock map 회귀 | 기존 66 tests 그대로 PASS (`load_default_map` 동작 변화 없음) |
| Integration | `/trafficsim/start` mock 분기 | 기존과 동일 응답 |
| Integration | `/trafficsim/start` opendrive 분기 | 새 응답 (자차만 표시, 시나리오 agent 없음) |
| Manual | 브라우저 토글 | "OpenDRIVE: e6mini" 선택 → 한국 도로 polyline 표시, 좌표 범위 자동 맞춤 |

---

## File Structure

```
kadap-poc-v2/
  trafficsim/
    opendrive_loader.py        # NEW: lxml 파서 + geometry sampler
    maps/
      __init__.py              # NEW: empty package marker
      e6mini.xodr              # NEW: esmini BSD-3 sample
      NOTICE                   # NEW: license attribution
    world.py                   # MODIFY: load_opendrive_map(path) 추가
    engine.py                  # MODIFY: build_plotly_figure 동적 viewport
  templates/
    tab_trafficsim.html        # MODIFY: 맵 소스 fieldset
  tests/trafficsim/
    test_opendrive_loader.py   # NEW: parse_xodr, _sample_geometry
    test_opendrive_map.py      # NEW: load_opendrive_map(e6mini) WorldMap shape
    test_dynamic_viewport.py   # NEW: build_plotly_figure viewport range
  main.py                      # MODIFY: MAP_SOURCES, map_source Form param, opendrive 분기
```

---

## Out of Scope

- OpenDRIVE `<signal>` 노드 → TrafficLight 자동 생성 (후속 단계)
- 정밀 lane connectivity graph (lane change/successor/predecessor)
- 3D 고도 (z 무시)
- Spiral 정밀 sampling (Fresnel integral 정확 — 1차는 거친 선형 근사 10점)
- NGII 실제 데이터 다운로드·전처리 (수동, 별도)
- 시나리오 anchor 추상화 (mock-only 시나리오를 NGII 맵에서도 자동 동작시키기)
- multi-map registry (한 번에 한 fixture 외 토글만)
- Plotly viewport scale 1:1 비율 (기존 `scaleanchor: "y"` 그대로 — OpenDRIVE 큰 좌표에서 zoom-fit 동작 확인 필요)

---

## 후속 단계 (이 spec 외)

1. NGII OpenDRIVE 데이터 입수 + maps/ 디렉토리 추가
2. OpenDRIVE `<signal>` → TrafficLight 자동 추출
3. 시나리오 anchor 추상화 — `"primary intersection"` 의미 lookup으로 다른 맵에서도 시나리오 동작
4. NGII 맵 + 9 조합 통합 시연
