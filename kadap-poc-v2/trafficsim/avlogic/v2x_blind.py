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
