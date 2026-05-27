"""Step-by-step closed-loop trace for the KADaP PoC.

For every simulation control cycle (controller_return), surface what the
operator needs to see to convince themselves the closed loop is actually
closing:

    1. NRE-rendered camera frames the driver saw      (sensorsim → driver)
    2. driver's predicted future trajectory waypoints (driver → controller)
    3. controller's final ego pose + velocity         (controller → physics)

The first frame extraction per rollout calls ``alpasim_utils.asl_to_frames
--format frames``, which writes JPEGs alongside the .asl. Subsequent calls
hit the on-disk cache.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from alpasim_utils.logs import async_read_pb_log

from runner import RolloutRef

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PY = REPO_ROOT / "alpasim" / ".venv" / "bin" / "python"
FRAMES_DIRNAME = "rollout_asl_frames_jpeg"  # separate from the mp4 cache dir


@dataclass
class StepInfo:
    step_idx: int
    timestamp_us: int
    sim_time_s: float  # seconds since first controller cycle
    n_predicted: int  # driver's predicted trajectory horizon (waypoints)
    last_predicted_xy: tuple[float, float] | None  # final waypoint in rig frame
    ego_xy: tuple[float, float]  # controller's final propagated ego pose
    ego_yaw_quat_z: float  # rough heading proxy (quaternion z component)
    ego_speed: float  # m/s, hypot(vx, vy) from controller dynamic_state


def ensure_frames_extracted(rollout: RolloutRef, timeout: int = 600) -> Path:
    """Materialise JPEG frames under ``<rollout>/rollout_asl_frames_jpeg/``."""
    target = rollout.dir / FRAMES_DIRNAME
    if target.exists() and any(target.rglob("*.jpg")):
        return target
    tmp_root = rollout.dir / "_frames_tmp"
    tmp_root.mkdir(exist_ok=True)
    subprocess.run(
        [
            str(VENV_PY),
            "-m",
            "alpasim_utils.asl_to_frames",
            str(rollout.asl),
            "--format",
            "frames",
            "--log-save-dir",
            str(tmp_root),
        ],
        check=False,
        capture_output=True,
        timeout=timeout,
    )
    # asl_to_frames nests output as
    #   <tmp_root>/<scene_id>/<rollout_uuid>/<asl_stem>/<camera_id>/<ts>.jpg
    # Flatten to <target>/<camera_id>/<ts>.jpg for simple slider indexing.
    target.mkdir(exist_ok=True)
    for jpg in tmp_root.rglob("*.jpg"):
        cam_dir = target / jpg.parent.name
        cam_dir.mkdir(exist_ok=True)
        jpg.rename(cam_dir / jpg.name)
    shutil.rmtree(tmp_root, ignore_errors=True)
    return target


@lru_cache(maxsize=8)
def _parse_steps_cached(asl_path: str, mtime_ns: int) -> list[StepInfo]:  # noqa: ARG001
    return asyncio.run(_parse_steps_async(asl_path))


async def _parse_steps_async(asl_path: str) -> list[StepInfo]:
    driver_returns = []
    controller_returns = []
    async for e in async_read_pb_log(asl_path):
        kind = e.WhichOneof("log_entry")
        if kind == "driver_return":
            driver_returns.append(e.driver_return)
        elif kind == "controller_return":
            controller_returns.append(e.controller_return)

    steps: list[StepInfo] = []
    t0: int | None = None
    for i, (dr, cr) in enumerate(zip(driver_returns, controller_returns)):
        waypoints = dr.trajectory.poses
        n_pred = len(waypoints)
        last_pred = (
            (waypoints[-1].pose.vec.x, waypoints[-1].pose.vec.y)
            if n_pred
            else None
        )
        if cr.states:
            st = cr.states[-1]
            ts = int(st.timestamp_us)
            if t0 is None:
                t0 = ts
            v = st.dynamic_state.linear_velocity
            speed = (v.x**2 + v.y**2) ** 0.5
            ego_xy = (st.pose_local_to_rig.vec.x, st.pose_local_to_rig.vec.y)
            yaw_z = st.pose_local_to_rig.quat.z
        else:
            ts = 0
            ego_xy = (0.0, 0.0)
            yaw_z = 0.0
            speed = 0.0
        steps.append(
            StepInfo(
                step_idx=i,
                timestamp_us=ts,
                sim_time_s=(ts - (t0 or ts)) / 1e6,
                n_predicted=n_pred,
                last_predicted_xy=last_pred,
                ego_xy=ego_xy,
                ego_yaw_quat_z=yaw_z,
                ego_speed=speed,
            )
        )
    return steps


def parse_steps(rollout: RolloutRef) -> list[StepInfo]:
    return _parse_steps_cached(str(rollout.asl), rollout.asl.stat().st_mtime_ns)


def step_cameras(rollout: RolloutRef, step_idx: int) -> dict[str, Path]:
    """Map camera_logical_id → JPEG path for the requested step."""
    fd = ensure_frames_extracted(rollout)
    out: dict[str, Path] = {}
    if not fd.exists():
        return out
    for cam_dir in sorted(fd.iterdir()):
        if not cam_dir.is_dir():
            continue
        jpegs = sorted(cam_dir.glob("*.jpg"))
        if step_idx < len(jpegs):
            out[cam_dir.name] = jpegs[step_idx]
    return out
