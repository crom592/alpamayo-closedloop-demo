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
            raise RuntimeError("live Alpamayo not implemented (camera sync pending)")
        base = self._baseline.decide(obs)
        return Action(
            target_speed=base.target_speed,
            steering=base.steering,
            reason=f"[Alpamayo mock] {base.reason}",
        )
