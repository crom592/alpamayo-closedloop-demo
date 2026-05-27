"""Rollout ASL → driving-metric extraction for the KADaP PoC.

Reads ``controller_return`` log entries (one per simulation step), which carry
the propagated vehicle state (pose + dynamic state). The PoC v0 derives a
small Safety/Comfort/Progress summary; richer signals (collision events,
route progress %, plan deviation vs. ground truth) are future work.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from alpasim_utils.logs import async_read_pb_log


@dataclass
class Timeseries:
    t: np.ndarray  # seconds since sim start
    speed: np.ndarray  # m/s, magnitude of linear velocity
    lateral_accel: np.ndarray  # m/s^2, |a_y| in rig frame
    jerk: np.ndarray  # m/s^3, |d|a|/dt|


@dataclass
class RolloutMetrics:
    n_steps: int
    duration_s: float
    avg_speed: float
    max_speed: float
    max_lateral_accel: float
    max_jerk: float
    series: Timeseries

    @property
    def is_empty(self) -> bool:
        return self.n_steps == 0


async def _collect_states(asl_path: str):
    t: list[float] = []
    vx: list[float] = []
    vy: list[float] = []
    ax: list[float] = []
    ay: list[float] = []
    async for entry in async_read_pb_log(asl_path):
        if entry.WhichOneof("log_entry") != "controller_return":
            continue
        for st in entry.controller_return.states:
            t.append(st.timestamp_us / 1e6)
            vx.append(st.dynamic_state.linear_velocity.x)
            vy.append(st.dynamic_state.linear_velocity.y)
            ax.append(st.dynamic_state.linear_acceleration.x)
            ay.append(st.dynamic_state.linear_acceleration.y)
    return (
        np.asarray(t, dtype=np.float64),
        np.asarray(vx, dtype=np.float64),
        np.asarray(vy, dtype=np.float64),
        np.asarray(ax, dtype=np.float64),
        np.asarray(ay, dtype=np.float64),
    )


@lru_cache(maxsize=64)
def _compute_cached(asl_path: str, mtime_ns: int) -> RolloutMetrics:  # noqa: ARG001
    # mtime_ns is part of the cache key so rewritten asl files re-parse.
    t, vx, vy, ax, ay = asyncio.run(_collect_states(asl_path))
    if t.size == 0:
        empty = Timeseries(t, vx, vx, vx)
        return RolloutMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, empty)

    t_rel = t - t[0]
    speed = np.hypot(vx, vy)
    lateral_accel = np.abs(ay)
    accel_mag = np.hypot(ax, ay)

    if t.size >= 2:
        dt = np.diff(t)
        dt[dt == 0] = np.nan
        jerk_inner = np.abs(np.diff(accel_mag) / dt)
        jerk = np.append(jerk_inner, jerk_inner[-1] if jerk_inner.size else 0.0)
        jerk = np.nan_to_num(jerk, nan=0.0, posinf=0.0, neginf=0.0)
    else:
        jerk = np.zeros_like(t)

    return RolloutMetrics(
        n_steps=int(t.size),
        duration_s=float(t_rel[-1]) if t_rel.size > 1 else 0.0,
        avg_speed=float(speed.mean()),
        max_speed=float(speed.max()),
        max_lateral_accel=float(lateral_accel.max()),
        max_jerk=float(jerk.max()),
        series=Timeseries(t_rel, speed, lateral_accel, jerk),
    )


def compute(asl_path: str | Path) -> RolloutMetrics:
    p = Path(asl_path)
    if not p.exists():
        raise FileNotFoundError(p)
    return _compute_cached(str(p), p.stat().st_mtime_ns)
