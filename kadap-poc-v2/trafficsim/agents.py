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
