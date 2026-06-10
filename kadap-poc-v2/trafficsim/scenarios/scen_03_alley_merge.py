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

    alley_car = Vehicle(
        id="veh_alley",
        path=[(60.0, 25.0), (60.0, 5.0), (80.0, 0.0)],
        desired_speed=6.0,
    )
    alley_car.speed = 5.0
    sim.add_vehicle(alley_car)
