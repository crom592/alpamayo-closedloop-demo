"""Alpamayo bridge — 호스트에서 ROS 2 토픽을 rosbridge로 처리.

구독:
  /sensing/camera/front/image_raw      (CompressedImage)
  /localization/kinematic_state        (Odometry, ego pose+twist)

발행:
  /planning/scenario_planning/trajectory  (Trajectory, Alpamayo 결과)
  /autoware_sim/decision                  (String, Alpamayo reason text — 디버그/UI용)

mode=mock: 카메라 frame index를 사용해 가짜 trajectory + 가짜 reason 생성.
mode=live: alpamayo1.5 inference call (구현 예정).
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import time
from dataclasses import dataclass, field

from autoware_sim.rosbridge_client import RosBridgeClient

# Alpamayo 결과는 별도 namespace로 publish.
# Autoware planning을 대체하려면 /planning/scenario_planning/trajectory에 쏘면 됨;
# 단 trajectory_validation 통과 + 충분한 rate 필요. C-실용에선 일단 별도 토픽으로
# 흐름만 보여주고 Autoware가 스스로 운전. 본격 PoC 단계에서 대체 교체 가능.
TRAJECTORY_TOPIC = "/autoware_sim/alpamayo_trajectory"
TRAJECTORY_TYPE = "autoware_planning_msgs/msg/Trajectory"
DECISION_TOPIC = "/autoware_sim/decision"
DECISION_TYPE = "std_msgs/msg/String"
CAMERA_TOPIC = "/sensing/camera/front/image_raw"
CAMERA_TYPE = "sensor_msgs/msg/CompressedImage"
ODOM_TOPIC = "/localization/kinematic_state"
ODOM_TYPE = "nav_msgs/msg/Odometry"

INFER_INTERVAL = 1.0  # 초; mock에선 1Hz가 충분


@dataclass
class BridgeState:
    """UI 노출용 최신 상태 캐시."""
    last_decision: str = "(초기화)"
    last_camera_seq: int = 0
    last_camera_thumb_b64: str = ""
    ego_x: float = 0.0
    ego_y: float = 0.0
    ego_speed: float = 0.0
    trajectory_pts: list[tuple[float, float]] = field(default_factory=list)
    updated_at: float = 0.0


def _yaw_from_quat(qz: float, qw: float) -> float:
    """planar yaw (radian)을 quaternion (z, w)에서 추출. roll/pitch 무시."""
    import math
    return math.atan2(2.0 * qz * qw, 1.0 - 2.0 * qz * qz)


def _quat_from_yaw(yaw: float) -> tuple[float, float, float, float]:
    import math
    return (0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0))


def _build_trajectory(
    ego_x: float, ego_y: float, yaw: float, ego_speed: float
) -> dict:
    """ego heading 방향으로 40 m 직진 trajectory.

    pts: 0.5 m 간격 80개.
    속도: 현재 ego_speed → target_speed(5 m/s) 까지 5 m 동안 ramp, 이후 5 m/s 유지.
    Heading: 모든 점이 ego yaw와 동일 (직진).
    """
    import math
    ux, uy = math.cos(yaw), math.sin(yaw)
    qx, qy, qz, qw = _quat_from_yaw(yaw)
    now = time.time()
    sec = int(now)
    nsec = int((now - sec) * 1e9)
    TARGET_V = 5.0
    RAMP_DIST = 5.0
    pts = []
    s_cumulative = 0.0
    n_pts = 80
    for i in range(n_pts):
        s = i * 0.5
        if s < RAMP_DIST:
            v = ego_speed + (TARGET_V - ego_speed) * (s / RAMP_DIST)
        else:
            v = TARGET_V
        avg_v = max(0.1, (v + (ego_speed if i == 0 else pts[-1]["longitudinal_velocity_mps"])) / 2.0)
        dt = 0.5 / avg_v
        s_cumulative += dt if i > 0 else 0.0
        pts.append(
            {
                "time_from_start": {
                    "sec": int(s_cumulative),
                    "nanosec": int((s_cumulative - int(s_cumulative)) * 1e9),
                },
                "pose": {
                    "position": {"x": ego_x + ux * s, "y": ego_y + uy * s, "z": 0.0},
                    "orientation": {"x": qx, "y": qy, "z": qz, "w": qw},
                },
                "longitudinal_velocity_mps": v,
                "lateral_velocity_mps": 0.0,
                "acceleration_mps2": 0.5 if s < RAMP_DIST else 0.0,
                "heading_rate_rps": 0.0,
                "front_wheel_angle_rad": 0.0,
                "rear_wheel_angle_rad": 0.0,
            }
        )
    return {
        "header": {"stamp": {"sec": sec, "nanosec": nsec}, "frame_id": "map"},
        "points": pts,
    }


async def run_bridge(
    state: BridgeState,
    stop: asyncio.Event,
    client: RosBridgeClient,
    mode: str | None = None,
) -> None:
    mode = mode or os.environ.get("AUTOWARE_SIM_ALPAMAYO_MODE", "mock")

    # 카메라 frame 캐시 (썸네일 + count)
    last_yaw = [0.0]  # closure

    def on_camera(msg: dict) -> None:
        state.last_camera_seq += 1
        data_b64 = msg.get("data", "")
        if data_b64:
            state.last_camera_thumb_b64 = data_b64
        state.updated_at = time.time()

    def on_odom(msg: dict) -> None:
        pose = msg.get("pose", {}).get("pose", {})
        pos = pose.get("position", {})
        ori = pose.get("orientation", {})
        twist = msg.get("twist", {}).get("twist", {})
        lin = twist.get("linear", {})
        state.ego_x = float(pos.get("x", 0.0))
        state.ego_y = float(pos.get("y", 0.0))
        qz = float(ori.get("z", 0.0))
        qw = float(ori.get("w", 1.0))
        last_yaw[0] = _yaw_from_quat(qz, qw)
        vx = float(lin.get("x", 0.0))
        vy = float(lin.get("y", 0.0))
        # Odometry twist는 base_link frame이므로 |vx|가 종속도. vy는 lateral.
        state.ego_speed = abs(vx)
        state.updated_at = time.time()

    await client.subscribe(CAMERA_TOPIC, CAMERA_TYPE, on_camera, throttle_rate_ms=500)
    await client.subscribe(ODOM_TOPIC, ODOM_TYPE, on_odom, throttle_rate_ms=200)
    await client.advertise(TRAJECTORY_TOPIC, TRAJECTORY_TYPE)
    await client.advertise(DECISION_TOPIC, DECISION_TYPE)

    while not stop.is_set():
        if mode == "live":
            # TODO: alpamayo1.5 호출 (camera frame + ego state → trajectory + reason)
            decision = "[Alpamayo live] 추론 결과 (구현 예정)"
        else:
            import math as _m
            yaw_deg = _m.degrees(last_yaw[0])
            decision = (
                f"[Alpamayo mock] cam#{state.last_camera_seq} "
                f"ego=({state.ego_x:.1f},{state.ego_y:.1f}) "
                f"yaw={yaw_deg:.0f}° v={state.ego_speed:.1f}m/s → 5m/s 유지 + 직진"
            )
        traj = _build_trajectory(state.ego_x, state.ego_y, last_yaw[0], state.ego_speed)
        await client.publish(TRAJECTORY_TOPIC, traj)
        await client.publish(DECISION_TOPIC, {"data": decision})
        state.last_decision = decision
        state.trajectory_pts = [
            (pt["pose"]["position"]["x"], pt["pose"]["position"]["y"])
            for pt in traj["points"][::4]
        ]
        state.updated_at = time.time()
        await asyncio.sleep(INFER_INTERVAL)
