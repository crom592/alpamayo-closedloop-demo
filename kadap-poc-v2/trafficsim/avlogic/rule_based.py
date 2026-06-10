"""RuleBasedLogic — V2X 메시지에 hand-written 우선순위로 반응하는 baseline.

평가 시 'V2X를 듣고 안전하게 운행하는 차'의 ground truth.
"""

from __future__ import annotations

import math

from trafficsim.avlogic.interface import Action, Observation

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
