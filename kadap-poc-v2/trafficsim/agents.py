"""환경 agent: TrafficLight, Pedestrian, Vehicle.

Task 5 — TrafficLight. Task 6 — Pedestrian. Task 7 — Vehicle (IDM).
모두 매 tick `update(t, dt, world)` 받아 state 갱신.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

Phase = Literal["GREEN", "YELLOW", "RED", "OFF"]

GREEN_S = 15.0
YELLOW_S = 3.0
RED_S = 15.0
CYCLE_S = GREEN_S + YELLOW_S + RED_S


@dataclass
class TrafficLight:
    id: str
    x: float
    y: float
    offset: float = 0.0
    broken: bool = False
    phase: Phase = "GREEN"
    remaining_s: float = GREEN_S

    def update(self, t: float, dt: float = 0.0) -> None:
        if self.broken:
            self.phase = "OFF"
            self.remaining_s = 0.0
            return
        cycle_t = (t + self.offset) % CYCLE_S
        if cycle_t < GREEN_S:
            self.phase = "GREEN"
            self.remaining_s = GREEN_S - cycle_t
        elif cycle_t < GREEN_S + YELLOW_S:
            self.phase = "YELLOW"
            self.remaining_s = GREEN_S + YELLOW_S - cycle_t
        else:
            self.phase = "RED"
            self.remaining_s = CYCLE_S - cycle_t


@dataclass
class Pedestrian:
    id: str
    path: list[tuple[float, float]]
    speed: float = 1.2  # m/s (보행자 기본 보행 속도)
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    _idx: int = 1
    finished: bool = False

    def __post_init__(self) -> None:
        if self.path:
            self.x, self.y = self.path[0]

    def update(self, t: float, dt: float) -> None:
        if self.finished:
            self.vx = self.vy = 0.0
            return
        remaining_budget = self.speed * dt
        while remaining_budget > 0 and self._idx < len(self.path):
            tx, ty = self.path[self._idx]
            dx, dy = tx - self.x, ty - self.y
            d = math.hypot(dx, dy)
            if d < 1e-9:
                self._idx += 1
                continue
            step = min(remaining_budget, d)
            ux, uy = dx / d, dy / d
            self.x += ux * step
            self.y += uy * step
            self.vx = ux * self.speed
            self.vy = uy * self.speed
            remaining_budget -= step
            if step >= d - 1e-9:
                self._idx += 1
        if self._idx >= len(self.path):
            self.finished = True
            self.vx = self.vy = 0.0
