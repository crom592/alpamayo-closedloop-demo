"""AVLogic 인터페이스 — simulator와 자율주행 로직을 분리.

환경은 PoC 산출물, 자율주행 로직은 swappable plugin.
연구자는 AVLogic Protocol만 구현하면 inject 가능.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass
class EgoState:
    x: float
    y: float
    yaw: float
    speed: float
    accel: float


V2XKind = Literal["BSM", "SPaT", "PSM", "RSI", "TIM"]


@dataclass
class V2XMsg:
    kind: V2XKind
    payload: dict
    source_id: str
    rx_time: float


ObjType = Literal["vehicle", "pedestrian", "static"]


@dataclass
class PerceivedObject:
    obj_type: ObjType
    x: float
    y: float
    speed: float


@dataclass
class PerceptionView:
    objects: list[PerceivedObject] = field(default_factory=list)


@dataclass
class Observation:
    ego: EgoState
    v2x_messages: list[V2XMsg]
    perception: PerceptionView
    t: float


@dataclass
class Action:
    target_speed: float
    steering: float
    reason: str


class AVLogic(Protocol):
    def decide(self, obs: Observation) -> Action: ...
