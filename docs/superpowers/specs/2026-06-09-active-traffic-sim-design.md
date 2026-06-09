# 능동 Traffic Sim 데모 탭 — 디자인 스펙

**작성일**: 2026-06-09
**저자**: PoC 작성자
**상태**: User review 대기

---

## Context

### 작성 배경
KATECH PoC 프로토타입이 그동안 "**Alpamayo 1.5가 자율주행 로직으로 자차를 운행하는 데모**" 방향으로 진화해왔습니다. 그러나 사용자가 본질을 재정의하였습니다:

> "**V2X 인프라 데이터를 포함하는 시뮬레이션 환경을 제공**하고, 자기 자율주행 로직을 가지고 있는 차가 그 환경에서 운행하는 자율주행 테스트 플랫폼"

이 framing에서:
- **PoC 산출물 = 환경 (V2X-aware traffic simulation)**
- **자율주행 로직 = swappable plugin** (Alpamayo는 baseline 중 하나일 뿐, 주인공이 아님)
- **KATECH 연구자 가치 = 자기 로직을 inject하여 같은 환경에서 정량 평가**

이 본질을 prototype에서 시연 가능한 형태로 보여주기 위해 Tab "🗺 능동 traffic sim" 신설.

### 본 문서가 다루는 범위
prototype 단계의 데모 탭 구현. 본격 PoC 영역(다중 카메라 sensor sim, HD map import, 연구자 SDK 정식 릴리즈)은 별도 작업.

---

## Architecture

```
┌─ Web UI (FastAPI + HTMX + Plotly 2D) ──────────┐
│  · 한국 도로 mock 맵 (top-down)                  │
│  · V2X 인프라 노드·메시지 표시                   │
│  · 자차·보행자·주변차 agent 실시간              │
│  · 로직 selector / 시나리오 selector             │
│  · 재생·일시정지·step / V2X inject               │
└────────────────────▲────────────────────────────┘
                     │ HTMX polling (2-5 Hz)
┌────────────────────┴────────────────────────────┐
│  Simulation Backend (Python, asyncio)            │
│  · Tick engine (10 Hz, 100ms step)               │
│  · Agents: 보행자(path-following) · 주변차(IDM)  │
│  · 신호등 SPaT cycle                             │
│  · V2X message generator (RSU·V2V·V2P)           │
│  · 자차 ego state                                │
└────────────────────▲────────────────────────────┘
                     │ AVLogic 인터페이스
┌────────────────────┴────────────────────────────┐
│  Swappable 자율주행 로직 (Python plugin)         │
│  내장 옵션:                                       │
│   · RuleBasedLogic — 디폴트, SPaT/PSM/BSM 반응   │
│   · AlpamayoLogic — Alpamayo baseline 호출       │
│   · V2XBlindLogic — V2X 무시 (비교군)            │
│  확장: KATECH 연구자 자체 Python class           │
└──────────────────────────────────────────────────┘
```

**핵심 분리**: simulator(환경)와 자율주행 로직이 `AVLogic` 인터페이스로 완전 분리. 환경은 PoC 산출물, 로직은 평가위원/연구자가 자유롭게 갈아끼움.

---

## Components

### 환경 (PoC 산출물 자체)

| 컴포넌트 | 내용 | 데이터 |
|---|---|---|
| **Map** | 한국형 mock 도로 (4-way 교차로 2-3개 + 좁은 골목 1개 + 보호좌회전·횡단보도) | GeoJSON, top-down 좌표 |
| **신호등 (V2I/SPaT)** | 교차로마다 SPaT 사이클 (직진·좌회전·보행자 phase + 잔여 시간) | RSU가 BSM-style 방송 |
| **RSU (V2I/RSI·TIM)** | 도로 위험·우회 안내·속도 권고 | 정적 위치 + 이벤트 송신 |
| **보행자 (V2P/PSM)** | path-following, 일부 무단횡단 | PSM 메시지 송신 (위치·진행 방향) |
| **주변차 (V2V/BSM)** | IDM following + 신호등 반응 | BSM 메시지 송신 (위치·속도·헤딩) |
| **자차** | AVLogic이 control | ego state, 수신 V2X 수집 |

### Simulator Engine
- **Tick rate**: 10 Hz (100ms/step), `asyncio` background task
- **상태 관리**: 모든 agent 위치/속도, 신호등 phase, 활성 V2X 메시지 큐
- **V2X 수신 모델**: 자차로부터 반경 N m 이내의 모든 메시지 + line-of-sight 무시 (V2X 본질은 NLOS 통신이므로)
- **종료 조건**: 시나리오 정의된 step 수 도달 또는 충돌·이탈

### AVLogic 인터페이스

```python
from dataclasses import dataclass
from typing import Protocol, Literal

@dataclass
class EgoState:
    x: float; y: float                 # world frame, m
    yaw: float                          # rad
    speed: float                        # m/s
    accel: float                        # m/s²

@dataclass
class V2XMsg:
    kind: Literal["BSM", "SPaT", "PSM", "RSI", "TIM"]
    payload: dict                       # 메시지 종류별 표준 필드
    source_id: str                      # RSU/agent ID
    rx_time: float                      # sim time

@dataclass
class PerceivedObject:
    obj_type: Literal["vehicle", "pedestrian", "static"]
    x: float; y: float
    speed: float                        # 정적 객체는 0

@dataclass
class PerceptionView:
    objects: list[PerceivedObject]      # 자차 시야 내 객체 (line-of-sight 적용)

@dataclass
class Observation:
    ego: EgoState
    v2x_messages: list[V2XMsg]          # 이 tick에 수신한 V2X
    perception: PerceptionView          # 카메라 sensor sim 출력 (mock: ground-truth + LOS filter)
    t: float                            # sim time, s

@dataclass
class Action:
    target_speed: float                 # m/s
    steering: float                     # rad, [-π/4, π/4]
    reason: str                         # 자연어 reasoning, UI에 표시

class AVLogic(Protocol):
    def decide(self, obs: Observation) -> Action: ...
```

### 내장 AVLogic 옵션

| 옵션 | 동작 | 비고 |
|---|---|---|
| **RuleBasedLogic** (디폴트) | SPaT 받으면 정지선 감속, PSM 받으면 횡단보도 정지, BSM 받으면 차간거리 유지. `reason`은 hand-written | 가장 빠르고 안정 |
| **AlpamayoLogic** | Alpamayo VLA 호출. 카메라 input은 기존 NuRec rollout의 frame을 placeholder reuse (mock 환경과 sync는 후속 작업) | "실제 모델이 동작" 시연용 |
| **V2XBlindLogic** | V2X 메시지 무시, `perception`만 사용 | V2X 효과 강조용 비교군 |
| **(연구자 inject)** | `AVLogic` Protocol만 구현하면 동작. prototype에선 **인터페이스 제공만** — 연구자가 파일 추가 + 재시작으로 가능. UI 업로드는 비범위 (후속) | KATECH 시범 사용 가능 |

---

## Data Flow (한 tick = 100ms)

```
1. simulator: 모든 agent 위치 업데이트, 신호등 phase tick, V2X 메시지 큐 갱신
2. observation 구성:
   · ego state
   · 반경 내 V2X 메시지 수집
   · line-of-sight perception 계산
3. AVLogic.decide(observation) → Action
4. simulator: 자차 control 적용 (target_speed/steering → kinematic update)
5. UI: 맵 + agent + V2X 메시지 + reasoning text 업데이트 (HTMX poll 응답)
```

---

## 시연 시나리오 3개

| # | 시나리오 | V2X 메시지 셋 | 기대 결과 (로직별) |
|---|---|---|---|
| 1 | **보호좌회전 + 횡단보도 보행자** | SPaT (좌회전 청신호 잔여 5초) + PSM (보행자 횡단 시작) | RuleBased/Alpamayo: 정지 · V2XBlind: 좌회전 시도 → 충돌 위험 |
| 2 | **신호등 고장 교차로 + RSU 우회 안내** | TIM (우회 안내) + RSI (신호등 고장) | RuleBased: 우회 · V2XBlind: 정지 후 진입 (위험) |
| 3 | **골목 합류 + 사각지대 주변차 BSM** | BSM (시야 밖 차 위치·속도) | RuleBased/Alpamayo: 양보 · V2XBlind: 합류 시도 (충돌 위험) |

각 시나리오 × 3 로직 = 9 조합. 평가위원이 토글로 직접 비교.

---

## 작업 범위 분해 (3-5일)

| Day | 작업 | 결과물 |
|---|---|---|
| 1 | simulator backend tick engine + AVLogic 인터페이스 + RuleBasedLogic | CLI에서 tick log 확인 가능 |
| 2 | GeoJSON map + 신호등 SPaT cycle + 보행자/주변차 agent + V2X 메시지 generator | 모든 agent 동작, V2X 메시지 정상 생성 |
| 3 | Plotly 2D UI + HTMX polling + 토글·재생 컨트롤 | 화면에서 환경 + 자차 관찰·조작 가능 |
| 4 | 3 시나리오 정의 + AlpamayoLogic 통합 + V2XBlindLogic | 9 조합 모두 동작 |
| 5 | 사용 가이드 + 안정화 + 평가위원 시연 검증 | end-to-end 시연 준비 완료 |

---

## Stack

| 영역 | 선택 |
|---|---|
| Backend simulator | 자체 lightweight Python (asyncio tick loop) |
| Frontend | Plotly 2D + HTMX polling |
| Tick rate | 10 Hz (sim), 2-5 Hz (UI poll) |
| 자율주행 로직 plugin | `importlib` 기반 동적 import |
| UI 통합 | 기존 `kadap-poc-v2/main.py` + `templates/` 확장 |

CARLA/SUMO/Mosaic 같은 외부 traffic simulator는 통합 자체가 3-5일 초과이므로 본격 PoC 영역으로 분리.

---

## 비범위 (Out of Scope)

- CARLA/SUMO/Mosaic 통합
- HD map 정식 import (한국 도로 vector data)
- 카메라 sensor sim (Alpamayo용 mock 환경 일치 카메라 frame 생성)
- 연구자 SDK 정식 패키징·문서·인증
- KATECH 자체 V2X 데이터셋 통합
- 멀티 평가위원 동시 시연 (concurrency)
- NRE Closed-Loop과의 통합

---

## Testing

- **Unit**: 각 AVLogic의 `decide`가 정의된 obs에 대해 기대 Action을 반환 (시나리오별 fixture)
- **Integration**: simulator 1 tick = (obs 생성 → AVLogic → action 적용 → 다음 tick state 일관) end-to-end 테스트
- **시연 검증**: 9 조합(3 시나리오 × 3 로직) 각각 시각적 확인 — 가이드 캡쳐 자동화 (Playwright)

---

## File Structure (예상)

```
kadap-poc-v2/
  trafficsim/
    __init__.py
    engine.py          # Tick engine, simulator state
    agents.py          # 보행자·주변차·신호등 agent classes
    v2x.py             # V2X 메시지 생성·라우팅
    avlogic/
      __init__.py
      interface.py     # Observation/Action/AVLogic Protocol
      rule_based.py
      alpamayo_proxy.py
      v2x_blind.py
    scenarios/
      __init__.py
      scen_01_pedestrian.py
      scen_02_signal_fail.py
      scen_03_alley_merge.py
    map.geojson        # 한국형 mock 도로
  templates/
    tab_trafficsim.html
    _trafficsim_frame.html  # HTMX polling 응답
  main.py              # /tab/trafficsim, /trafficsim/tick, /trafficsim/reset, /trafficsim/inject
```
