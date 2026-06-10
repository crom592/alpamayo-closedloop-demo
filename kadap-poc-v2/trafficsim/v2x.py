"""V2X 메시지 생성기 + 자차 수신 router.

수신 모델: 자차 중심 반경 V2X_RX_RADIUS m 이내, LOS 무시.
위치 정보 없는 메시지(TIM 등)는 시나리오 inject 시 항상 통과.
"""

from __future__ import annotations

import math

from trafficsim.agents import Pedestrian, TrafficLight, Vehicle
from trafficsim.avlogic.interface import EgoState, V2XMsg

V2X_RX_RADIUS = 200.0  # m


def spat_from_traffic_light(tl: TrafficLight, rx_time: float) -> V2XMsg:
    return V2XMsg(
        kind="SPaT",
        payload={
            "phase": tl.phase,
            "remaining_s": tl.remaining_s,
            "x": tl.x,
            "y": tl.y,
        },
        source_id=tl.id,
        rx_time=rx_time,
    )


def psm_from_pedestrian(p: Pedestrian, rx_time: float) -> V2XMsg:
    return V2XMsg(
        kind="PSM",
        payload={"x": p.x, "y": p.y, "vx": p.vx, "vy": p.vy},
        source_id=p.id,
        rx_time=rx_time,
    )


def bsm_from_vehicle(v: Vehicle, rx_time: float) -> V2XMsg:
    return V2XMsg(
        kind="BSM",
        payload={
            "x": v.x,
            "y": v.y,
            "speed": v.speed,
            "heading": v.heading,
        },
        source_id=v.id,
        rx_time=rx_time,
    )


def tim_message(source_id: str, message: str, severity: str, rx_time: float) -> V2XMsg:
    return V2XMsg(
        kind="TIM",
        payload={"message": message, "severity": severity},
        source_id=source_id,
        rx_time=rx_time,
    )


def rsi_message(
    source_id: str, message: str, severity: str, x: float, y: float, rx_time: float
) -> V2XMsg:
    return V2XMsg(
        kind="RSI",
        payload={"message": message, "severity": severity, "x": x, "y": y},
        source_id=source_id,
        rx_time=rx_time,
    )


def route_messages(messages: list[V2XMsg], ego: EgoState) -> list[V2XMsg]:
    out: list[V2XMsg] = []
    for m in messages:
        x = m.payload.get("x")
        y = m.payload.get("y")
        if x is None or y is None:
            out.append(m)
            continue
        if math.hypot(x - ego.x, y - ego.y) <= V2X_RX_RADIUS:
            out.append(m)
    return out
