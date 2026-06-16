"""Autoware Docker 컨테이너 lifecycle.

planning_simulator + rosbridge_server를 헤드리스로 기동.
이미지는 ghcr.io/autowarefoundation/autoware:latest-humble-runtime-amd64.
rosbridge_suite는 이미지에 이미 포함되어 있음.
"""

from __future__ import annotations

import json as _json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

CONTAINER_NAME = "autoware_sim_demo"
IMAGE = "ghcr.io/autowarefoundation/autoware:latest-humble-runtime-amd64"
ROSBRIDGE_PORT = 9091  # :9090 is cockpit.socket on this host

THIS_DIR = Path(__file__).resolve().parent
HOST_MAP_DIR = THIS_DIR / "maps" / "sample-map-planning"
CONTAINER_MAP_DIR = "/maps/sample-map-planning"


@dataclass
class ContainerStatus:
    exists: bool
    running: bool
    image: str | None
    rosbridge_reachable: bool


def _sh(cmd: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        shlex.split(cmd),
        check=check,
        capture_output=capture,
        text=True,
    )


def image_exists(tag: str) -> bool:
    r = _sh(f"docker image inspect {tag}", check=False)
    return r.returncode == 0


def container_status() -> ContainerStatus:
    inspect = _sh(f"docker container inspect {CONTAINER_NAME}", check=False)
    if inspect.returncode != 0:
        return ContainerStatus(
            exists=False, running=False, image=None, rosbridge_reachable=False
        )
    data = _json.loads(inspect.stdout)[0]
    running = data.get("State", {}).get("Running", False)
    image = data.get("Config", {}).get("Image", "")
    return ContainerStatus(
        exists=True,
        running=running,
        image=image,
        rosbridge_reachable=_probe_rosbridge() if running else False,
    )


def _probe_rosbridge(timeout: float = 1.0) -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", ROSBRIDGE_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def start_container() -> None:
    """컨테이너 기동 — planning_simulator launch + rosbridge_websocket :9090."""
    if not HOST_MAP_DIR.exists():
        raise RuntimeError(f"sample-map-planning not found: {HOST_MAP_DIR}")
    if not image_exists(IMAGE):
        raise RuntimeError(f"image not pulled: {IMAGE}")

    status = container_status()
    if status.running:
        return
    if status.exists:
        _sh(f"docker rm -f {CONTAINER_NAME}", check=False)

    # bash의 `&` 우선순위는 `&&`보다 낮아 fg 명령에서 source가 풀린다.
    # `{ ... }` 그룹으로 묶어 한 번만 source 후 bg + fg 동시 기동.
    inner_cmd = (
        f"source /opt/ros/humble/setup.bash && "
        f"source /opt/autoware/setup.bash && "
        f"{{ ros2 launch rosbridge_server rosbridge_websocket_launch.xml port:={ROSBRIDGE_PORT} > /tmp/rosbridge.log 2>&1 & "
        f"sleep 4 && "
        f"exec ros2 launch autoware_launch planning_simulator.launch.xml "
        f"map_path:={CONTAINER_MAP_DIR} "
        f"vehicle_model:=sample_vehicle "
        f"sensor_model:=sample_sensor_kit "
        f"rviz:=false "
        f"perception/enable_object_recognition:=false; }}"
    )
    cmd = [
        "docker", "run", "-d",
        "--name", CONTAINER_NAME,
        "--network", "host",
        "-v", f"{HOST_MAP_DIR}:{CONTAINER_MAP_DIR}:ro",
        "--entrypoint", "/bin/bash",
        IMAGE,
        "-lc", inner_cmd,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def stop_container() -> None:
    _sh(f"docker rm -f {CONTAINER_NAME}", check=False)


def container_logs(tail: int = 80) -> str:
    r = _sh(f"docker logs --tail {tail} {CONTAINER_NAME}", check=False)
    return (r.stdout or "") + (r.stderr or "")


def call_service(service: str, srv_type: str, args_yaml: str = "{}", timeout: int = 10) -> str:
    """컨테이너 내부에서 `ros2 service call` 실행. fire-and-forget성 호출 OK."""
    cmd = [
        "docker", "exec", CONTAINER_NAME, "bash", "-c",
        f". /opt/ros/humble/setup.bash && timeout {timeout} ros2 service call "
        f"{service} {srv_type} '{args_yaml}' 2>&1",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
    return (r.stdout or "") + (r.stderr or "")
