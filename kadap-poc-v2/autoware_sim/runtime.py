"""싱글톤 런타임 — FastAPI worker에서 안전하게 공유.

- BridgeState 한 개
- rosbridge WS 클라이언트 한 개
- 백그라운드 task 두 개 (camera publisher + alpamayo bridge)
- start/stop API
- Autoware 자동 초기화 (initial pose + goal + engage)
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from autoware_sim.alpamayo_bridge import BridgeState, run_bridge
from autoware_sim.rosbridge_client import RosBridgeClient
from autoware_sim.synth_camera import SynthCameraPublisher

# sample-map-planning lanelet 네트워크 내 검증된 좌표 쌍.
# 직접 OSM 노드 lat/lon → MGRS 54SVE 변환 후 routing 시뮬레이션으로 검증.
INIT_POSE = {
    "header": {"frame_id": "map"},
    "pose": {
        "pose": {
            "position": {"x": 3863.0, "y": 73749.0, "z": 19.5},
            "orientation": {"x": 0.0, "y": 0.0, "z": 1.0, "w": 0.0},  # ~180° (west)
        },
        "covariance": [0.25, 0.0, 0.0, 0.0, 0.0, 0.0,
                       0.0, 0.25, 0.0, 0.0, 0.0, 0.0,
                       0.0, 0.0, 0.07, 0.0, 0.0, 0.0,
                       0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                       0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                       0.0, 0.0, 0.0, 0.0, 0.0, 0.07],
    },
}
GOAL_POSE = {
    "header": {"frame_id": "map"},
    "pose": {
        "position": {"x": 3717.0, "y": 73745.0, "z": 19.5},
        "orientation": {"x": 0.0, "y": 0.0, "z": 1.0, "w": 0.0},
    },
}


@dataclass
class Runtime:
    state: BridgeState = field(default_factory=BridgeState)
    client: RosBridgeClient | None = None
    _stop: asyncio.Event | None = None
    _tasks: list[asyncio.Task] = field(default_factory=list)
    _loop: asyncio.AbstractEventLoop | None = None
    _thread: threading.Thread | None = None
    _mp4_path: Path | None = None
    _mode: str = "mock"
    running: bool = False
    error: str | None = None

    def start(self, mp4_path: Path, mode: str = "mock") -> None:
        if self.running:
            return
        self._mp4_path = mp4_path
        self._mode = mode
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        fut = asyncio.run_coroutine_threadsafe(self._async_start(), self._loop)
        fut.result(timeout=15)
        self.running = True
        self.error = None

    async def _async_start(self) -> None:
        self._stop = asyncio.Event()
        self.client = RosBridgeClient()
        try:
            await self.client.connect(timeout=10.0)
        except Exception as e:  # noqa: BLE001
            self.error = f"rosbridge connect 실패: {e}"
            raise
        cam = SynthCameraPublisher(mp4_path=self._mp4_path)
        self._tasks = [
            asyncio.create_task(cam.run(self.client, self._stop)),
            asyncio.create_task(
                run_bridge(self.state, self._stop, self.client, mode=self._mode)
            ),
            # Autoware 초기화는 백그라운드 — start API가 즉시 반환되도록.
            asyncio.create_task(self._init_autoware()),
        ]

    async def _init_autoware(self) -> None:
        """Autoware planning_simulator를 자율주행 모드로 진입시킨다.

        순서:
          1) initial pose publish (위치 인식 초기화)
          2) goal pose publish (mission_planner가 route 생성)
          3) engage publish (auto mode 진입)
        """
        assert self.client is not None
        c = self.client
        # 1) initial pose
        await c.advertise(
            "/initialpose3d", "geometry_msgs/msg/PoseWithCovarianceStamped"
        )
        now = time.time()
        stamp = {"sec": int(now), "nanosec": int((now - int(now)) * 1e9)}
        await c.publish(
            "/initialpose3d",
            {**INIT_POSE, "header": {**INIT_POSE["header"], "stamp": stamp}},
        )
        await asyncio.sleep(3.0)
        # 2) route 설정 — set_route_points service (mission_planner에 lanelet route 요청).
        import websockets
        import json as _json
        url = self.client.url
        async with websockets.connect(url) as ws:
            args = {
                "header": {"frame_id": "map", "stamp": {"sec": 0, "nanosec": 0}},
                "option": {"allow_goal_modification": True},
                "goal": GOAL_POSE["pose"],
                "waypoints": [],
            }
            await ws.send(_json.dumps({
                "op": "call_service",
                "service": "/api/routing/set_route_points",
                "type": "autoware_adapi_v1_msgs/srv/SetRoutePoints",
                "args": args,
                "id": "init-route",
            }))
            for _ in range(5):
                try:
                    m = _json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                    if m.get("op") == "service_response":
                        break
                except asyncio.TimeoutError:
                    break
        await asyncio.sleep(2.5)
        # 3) change_to_autonomous (별도 ws connection).
        async with websockets.connect(url) as ws:
            await ws.send(_json.dumps({
                "op": "call_service",
                "service": "/api/operation_mode/change_to_autonomous",
                "type": "autoware_adapi_v1_msgs/srv/ChangeOperationMode",
                "args": {},
                "id": "init-auto",
            }))
            for _ in range(5):
                try:
                    m = _json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
                    if m.get("op") == "service_response":
                        break
                except asyncio.TimeoutError:
                    break
        # legacy engage topic도 함께 publish (호환)
        await c.advertise(
            "/autoware/engage", "autoware_vehicle_msgs/msg/Engage"
        )
        await c.publish(
            "/autoware/engage",
            {"stamp": {"sec": int(time.time()), "nanosec": 0}, "engage": True},
        )
        self.state.last_decision = (
            "[초기화 완료] initial pose + route + autonomous mode 요청 송신 — "
            "Autoware 진단 통과 후 차량 출발"
        )

    def stop(self) -> None:
        if not self.running or self._loop is None:
            return
        async def _shutdown():
            if self._stop:
                self._stop.set()
            await asyncio.sleep(0.1)
            for t in self._tasks:
                t.cancel()
            if self.client:
                await self.client.close()
        try:
            fut = asyncio.run_coroutine_threadsafe(_shutdown(), self._loop)
            fut.result(timeout=5)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread:
                self._thread.join(timeout=3)
            self.running = False
            self._loop = None
            self._thread = None
            self._tasks = []
            self.client = None


_RUNTIME = Runtime()


def get_runtime() -> Runtime:
    return _RUNTIME
