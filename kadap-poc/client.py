"""gRPC client wrapper for the Alpasim runtime daemon.

Talks to ``runtime-0`` (port 50051 on the host) which serves
``alpasim_grpc.v0.RuntimeService.simulate``. Used by the Gradio app to
trigger interactive scenario runs without paying the ~10-min per-process
model-load cost — the daemon stays up across calls.
"""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from typing import Iterable

import grpc
from alpasim_grpc.v0 import runtime_pb2 as rp
from alpasim_grpc.v0 import runtime_pb2_grpc as rg

DAEMON_ADDR = "127.0.0.1:50051"
DRIVER_IP = "driver-0"  # gRPC target visible inside the docker network
DRIVER_PORT = 6000
DEFAULT_TIMEOUT_S = 1200  # one rollout can take a few minutes incl. warmup


@dataclass
class RolloutOutcome:
    """Plain-Python view of a SimulationReturn.RolloutReturn for the UI."""

    scenario_id: str
    rollout_uuid: str
    success: bool
    error: str
    aggregated: dict[str, float]


def is_daemon_port_open(timeout: float = 2.0) -> bool:
    """Quick TCP probe — returns False if the runtime container isn't up."""
    host, port = DAEMON_ADDR.split(":")
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _build_request(
    scenario_ids: Iterable[str], n_rollouts_each: int = 1
) -> rp.SimulationRequest:
    return rp.SimulationRequest(
        available_drivers=[
            rp.SimulationRequest.DriverAddress(ip=DRIVER_IP, port=DRIVER_PORT)
        ],
        rollout_specs=[
            rp.RolloutSpec(scenario_id=sid, nr_rollouts=n_rollouts_each)
            for sid in scenario_ids
        ],
        n_concurrent_per_driver=1,
    )


async def _simulate_async(
    scenario_ids: list[str], n_rollouts_each: int, timeout_s: float
) -> list[RolloutOutcome]:
    async with grpc.aio.insecure_channel(DAEMON_ADDR) as channel:
        stub = rg.RuntimeServiceStub(channel)
        req = _build_request(scenario_ids, n_rollouts_each)
        reply = await asyncio.wait_for(stub.simulate(req), timeout=timeout_s)
    return [
        RolloutOutcome(
            scenario_id=r.rollout_spec.scenario_id,
            rollout_uuid=r.rollout_uuid,
            success=r.success,
            error=r.error,
            aggregated=dict(r.aggregated_metrics),
        )
        for r in reply.rollout_returns
    ]


def simulate(
    scenario_ids: list[str],
    n_rollouts_each: int = 1,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> list[RolloutOutcome]:
    """Blocking wrapper used by the Gradio handlers (own event loop per call)."""
    return asyncio.run(_simulate_async(scenario_ids, n_rollouts_each, timeout_s))


if __name__ == "__main__":
    import argparse
    import json

    p = argparse.ArgumentParser()
    p.add_argument("scenarios", nargs="+", help="scenario IDs to run")
    p.add_argument("-n", "--nr", type=int, default=1)
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    a = p.parse_args()

    if not is_daemon_port_open():
        raise SystemExit(f"daemon not reachable at {DAEMON_ADDR}")

    outcomes = simulate(a.scenarios, a.nr, a.timeout)
    for o in outcomes:
        print(json.dumps(o.__dict__, indent=2, default=str))
