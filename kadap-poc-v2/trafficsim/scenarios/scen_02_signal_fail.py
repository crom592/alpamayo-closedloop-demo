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
            rx_time=4.0,
        )
    )
    sim.inject_message(
        tim_message(
            source_id="rsu_east",
            message="DETOUR",
            severity="HIGH",
            rx_time=4.0,
        )
    )
