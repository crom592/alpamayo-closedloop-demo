"""rosbridge WebSocket 클라이언트 (호스트 → 컨테이너 :9090).

websockets 라이브러리 사용. ROS 2 토픽을 JSON으로 publish/subscribe.

rosbridge protocol v2: https://github.com/RobotWebTools/rosbridge_suite/blob/ros2/ROSBRIDGE_PROTOCOL.md
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import websockets


@dataclass
class RosBridgeClient:
    url: str = "ws://127.0.0.1:9091"
    _ws: websockets.WebSocketClientProtocol | None = None
    _subs: dict[str, Callable[[dict], None]] = field(default_factory=dict)
    _advertised: set[str] = field(default_factory=set)
    _task: asyncio.Task | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _seq: int = 0

    async def connect(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self._ws = await websockets.connect(self.url, max_size=None)
                self._task = asyncio.create_task(self._reader())
                return
            except (OSError, ConnectionRefusedError) as e:
                last_err = e
                await asyncio.sleep(0.5)
        raise RuntimeError(f"rosbridge {self.url} 접속 실패: {last_err}")

    async def close(self) -> None:
        self._stop.set()
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()

    async def _reader(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if msg.get("op") == "publish":
                    topic = msg.get("topic")
                    cb = self._subs.get(topic)
                    if cb:
                        try:
                            cb(msg.get("msg") or {})
                        except Exception as e:  # noqa: BLE001
                            print(f"[rosbridge] sub callback error on {topic}: {e}")
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass

    async def _send(self, payload: dict) -> None:
        assert self._ws is not None
        await self._ws.send(json.dumps(payload))

    async def subscribe(
        self,
        topic: str,
        msg_type: str,
        callback: Callable[[dict], None],
        throttle_rate_ms: int = 0,
        queue_length: int = 1,
    ) -> None:
        self._subs[topic] = callback
        await self._send(
            {
                "op": "subscribe",
                "topic": topic,
                "type": msg_type,
                "throttle_rate": throttle_rate_ms,
                "queue_length": queue_length,
            }
        )

    async def advertise(self, topic: str, msg_type: str) -> None:
        if topic in self._advertised:
            return
        await self._send({"op": "advertise", "topic": topic, "type": msg_type})
        self._advertised.add(topic)

    async def publish(self, topic: str, msg: dict) -> None:
        await self._send({"op": "publish", "topic": topic, "msg": msg})
