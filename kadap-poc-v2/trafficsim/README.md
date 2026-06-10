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
