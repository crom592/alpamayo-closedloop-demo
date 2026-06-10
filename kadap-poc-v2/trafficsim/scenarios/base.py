"""시나리오 카탈로그 + sim setup 함수 registry."""

from __future__ import annotations

from typing import Callable

from trafficsim.engine import Sim

SCENARIOS: dict[str, Callable[[Sim], None]] = {}


def register(key: str):
    def deco(fn: Callable[[Sim], None]) -> Callable[[Sim], None]:
        SCENARIOS[key] = fn
        return fn
    return deco


def apply_scenario(sim: Sim, key: str) -> None:
    if key not in SCENARIOS:
        raise KeyError(f"unknown scenario: {key}")
    SCENARIOS[key](sim)
