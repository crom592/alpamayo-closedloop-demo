"""합성 카메라 publisher — 기존 closedloop rollout mp4 frame을 ROS 이미지로 발행.

ego 위치 변화 (Autoware planning_simulator가 publish하는 /localization/kinematic_state)에
대응하여 mp4 frame index를 보간. sim_time_s 기준 매핑.

Alpamayo 추론은 이 토픽을 구독.
"""

from __future__ import annotations

import asyncio
import base64
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from autoware_sim.rosbridge_client import RosBridgeClient

DEFAULT_FPS = 2.0
DEFAULT_TOPIC = "/sensing/camera/front/image_raw"
MSG_TYPE = "sensor_msgs/msg/CompressedImage"  # rosbridge가 base64 압축 이미지 지원


@dataclass
class SynthCameraPublisher:
    mp4_path: Path
    topic: str = DEFAULT_TOPIC
    fps: float = DEFAULT_FPS
    _frames_b64: list[str] = field(default_factory=list)
    _seq: int = 0
    _started: float = 0.0

    def load_frames(self) -> None:
        """ffmpeg로 mp4 → JPEG frame을 추출, base64 encode하여 메모리에 caching."""
        if not self.mp4_path.exists():
            raise FileNotFoundError(self.mp4_path)
        # ffmpeg → stdout MJPEG. 메모리 한도 위해 fps 강제 + scale 480.
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", str(self.mp4_path),
            "-vf", f"fps={self.fps},scale=480:-1",
            "-c:v", "mjpeg",
            "-f", "image2pipe",
            "pipe:1",
        ]
        proc = subprocess.run(cmd, capture_output=True, check=True)
        # JPEG SOI/EOI 마커로 split
        data = proc.stdout
        frames: list[bytes] = []
        i = 0
        while True:
            soi = data.find(b"\xff\xd8", i)
            if soi == -1:
                break
            eoi = data.find(b"\xff\xd9", soi)
            if eoi == -1:
                break
            frames.append(data[soi : eoi + 2])
            i = eoi + 2
        self._frames_b64 = [base64.b64encode(f).decode("ascii") for f in frames]

    def frame_count(self) -> int:
        return len(self._frames_b64)

    async def run(self, client: RosBridgeClient, stop: asyncio.Event) -> None:
        if not self._frames_b64:
            self.load_frames()
        await client.advertise(self.topic, MSG_TYPE)
        self._started = time.monotonic()
        interval = 1.0 / self.fps
        while not stop.is_set():
            idx = int((time.monotonic() - self._started) * self.fps) % len(self._frames_b64)
            now_s = time.time()
            sec = int(now_s)
            nsec = int((now_s - sec) * 1e9)
            await client.publish(
                self.topic,
                {
                    "header": {
                        "stamp": {"sec": sec, "nanosec": nsec},
                        "frame_id": "camera_front",
                    },
                    "format": "jpeg",
                    "data": self._frames_b64[idx],
                },
            )
            self._seq += 1
            await asyncio.sleep(interval)
