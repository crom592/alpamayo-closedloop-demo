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
