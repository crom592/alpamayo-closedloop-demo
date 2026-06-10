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
