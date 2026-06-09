#!/usr/bin/env python3
"""Render a sync video: NRE camera mp4 + top-down BEV mini-map (PiP).

Pipeline:
  1. parse_steps(rollout) → list[StepInfo] with ego_xy / last_predicted_xy
  2. for each step, render a BEV PNG showing
        · accumulated ego trail (where the car has been)
        · current ego position + heading triangle
        · the driver's predicted future endpoint (rig-frame → world)
        · V2X banner + sim time + speed
  3. ffmpeg the PNG sequence to a BEV mp4 (same FPS as camera mp4).
  4. ffmpeg overlay BEV onto the camera mp4 (upper-right PiP) →
        kadap-poc-v2/closedloop_videos/sync_<uuid>.mp4

CLI:
  python render_minimap_camera_sync.py --uuid 38e6fafa     # one rollout
  python render_minimap_camera_sync.py --all               # all rollouts
"""
from __future__ import annotations

import argparse
import math
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "kadap-poc"))

from runner import existing_rollouts, RolloutRef  # noqa: E402
import trace as trace_mod  # noqa: E402

import matplotlib
matplotlib.use("Agg")
from matplotlib import font_manager as _fm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

for _f in (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
):
    try:
        _fm.fontManager.addfont(_f)
    except Exception:
        pass
plt.rcParams["font.family"] = ["Noto Sans CJK JP", "NanumGothic", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

CACHE_DIR = REPO_ROOT / "kadap-poc-v2" / "closedloop_videos"
FPS = 2  # match render_closedloop_videos.py


def _yaw_from_quat_z(qz: float) -> float:
    """Recover yaw (rad) from the z component of a unit quaternion (rough)."""
    qz = max(-1.0, min(1.0, qz))
    return 2.0 * math.asin(qz)


def _render_bev_frame(
    out_png: Path,
    steps,
    k: int,
    v2x_text: str,
    x_lim: tuple[float, float],
    y_lim: tuple[float, float],
    fig_size: tuple[float, float] = (5.0, 5.0),
    dpi: int = 120,
) -> None:
    """Render one minimap PNG for step k (0-indexed)."""
    cur = steps[k]
    fig, ax = plt.subplots(figsize=fig_size, dpi=dpi)
    fig.patch.set_facecolor("#0e1117")
    ax.set_facecolor("#0e1117")

    # Accumulated trail (past + current)
    xs = [s.ego_xy[0] for s in steps[: k + 1]]
    ys = [s.ego_xy[1] for s in steps[: k + 1]]
    ax.plot(xs, ys, color="#888888", lw=1.5, alpha=0.7, label="궤적")

    # Current ego (triangle pointing along yaw)
    ego_x, ego_y = cur.ego_xy
    yaw = _yaw_from_quat_z(cur.ego_yaw_quat_z)
    tri_size = 2.5
    pts = np.array([
        [tri_size, 0.0],
        [-tri_size * 0.6, tri_size * 0.6],
        [-tri_size * 0.6, -tri_size * 0.6],
    ])
    rot = np.array([[math.cos(yaw), -math.sin(yaw)], [math.sin(yaw), math.cos(yaw)]])
    pts = pts @ rot.T + np.array([ego_x, ego_y])
    ax.fill(pts[:, 0], pts[:, 1], color="#e74c3c", zorder=5, label="자차")

    # Driver's predicted future endpoint (rig-frame → world via yaw)
    if cur.last_predicted_xy is not None:
        px_r, py_r = cur.last_predicted_xy
        # rotate rig-frame point into world frame
        wx = ego_x + math.cos(yaw) * px_r - math.sin(yaw) * py_r
        wy = ego_y + math.sin(yaw) * px_r + math.cos(yaw) * py_r
        ax.plot([ego_x, wx], [ego_y, wy], color="#2ecc71", lw=2.0, alpha=0.8)
        ax.scatter([wx], [wy], s=50, color="#2ecc71", zorder=6, label="예측 의도")

    ax.set_xlim(*x_lim)
    ax.set_ylim(*y_lim)
    ax.set_aspect("equal")
    ax.set_xlabel("world x (m)", color="#cccccc", fontsize=9)
    ax.set_ylabel("world y (m)", color="#cccccc", fontsize=9)
    ax.tick_params(colors="#888888", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#444444")
    ax.grid(True, alpha=0.15, color="#444444")

    # V2X banner top
    ax.text(
        0.02, 0.98, f"[V2X] {v2x_text}",
        transform=ax.transAxes, fontsize=10, color="black",
        bbox=dict(facecolor="#f1c40f", edgecolor="none", pad=4),
        verticalalignment="top", horizontalalignment="left",
    )
    # Time + speed bottom
    ax.text(
        0.98, 0.02, f"t={cur.sim_time_s:.1f}s · v={cur.ego_speed:.1f}m/s",
        transform=ax.transAxes, fontsize=10, color="white",
        bbox=dict(facecolor="black", alpha=0.7, edgecolor="none", pad=4),
        verticalalignment="bottom", horizontalalignment="right",
    )
    # Title
    ax.text(
        0.5, 1.04, "BEV 미니맵 (자차 + 예측 의도)",
        transform=ax.transAxes, fontsize=11, color="#dddddd",
        verticalalignment="bottom", horizontalalignment="center",
    )

    fig.subplots_adjust(left=0.13, right=0.97, top=0.92, bottom=0.10)
    fig.savefig(out_png, dpi=120, facecolor=fig.get_facecolor())
    plt.close(fig)


def _bev_axis_limits(steps) -> tuple[tuple[float, float], tuple[float, float]]:
    """Compute global axis limits covering all ego positions with padding."""
    xs = [s.ego_xy[0] for s in steps]
    ys = [s.ego_xy[1] for s in steps]
    if not xs:
        return ((-20.0, 20.0), (-20.0, 20.0))
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    cx, cy = (x_min + x_max) / 2, (y_min + y_max) / 2
    half = max(x_max - x_min, y_max - y_min, 30.0) / 2 + 8.0
    return ((cx - half, cx + half), (cy - half, cy + half))


def render_sync(rollout: RolloutRef, force: bool = False, minimap_only: bool = False) -> Path | None:
    """Render the BEV minimap mp4 (always). If minimap_only is False, also PiP-overlay onto the camera mp4."""
    cam_mp4 = CACHE_DIR / f"{rollout.rollout_uuid}.mp4"
    if not minimap_only and not cam_mp4.exists():
        print(f"  ❌ {rollout.rollout_uuid[:12]}: camera mp4 missing (need --minimap-only for camera-less rollouts)")
        return None

    prefix = "minimap" if minimap_only else "sync"
    out = CACHE_DIR / f"{prefix}_{rollout.rollout_uuid}.mp4"
    if out.exists() and not force:
        print(f"  ✅ {rollout.rollout_uuid[:12]} {prefix} cached (skip)")
        return out

    print(f"  · {rollout.rollout_uuid[:12]}: parsing ASL steps…")
    steps = trace_mod.parse_steps(rollout)
    if not steps:
        print(f"  ❌ {rollout.rollout_uuid[:12]}: 0 steps")
        return None

    v2x_text = rollout.meta.get("v2x_text") or "(V2X 미기록)"
    x_lim, y_lim = _bev_axis_limits(steps)

    fig_size = (10.0, 7.0) if minimap_only else (5.0, 5.0)
    dpi = 120

    print(f"  · {rollout.rollout_uuid[:12]}: rendering {len(steps)} BEV frames…")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for k in range(len(steps)):
            _render_bev_frame(tmp_dir / f"bev_{k:04d}.png", steps, k, v2x_text, x_lim, y_lim,
                              fig_size=fig_size, dpi=dpi)

        if minimap_only:
            out.parent.mkdir(parents=True, exist_ok=True)
            r = subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-framerate", str(FPS),
                "-i", str(tmp_dir / "bev_%04d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                str(out),
            ], capture_output=True)
            if r.returncode != 0:
                out.unlink(missing_ok=True)
                print(f"  ❌ minimap ffmpeg fail: {r.stderr.decode()[:200]}")
                return None
        else:
            bev_mp4 = tmp_dir / "bev.mp4"
            r = subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-framerate", str(FPS),
                "-i", str(tmp_dir / "bev_%04d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                str(bev_mp4),
            ], capture_output=True)
            if r.returncode != 0:
                print(f"  ❌ BEV ffmpeg fail: {r.stderr.decode()[:200]}")
                return None

            print(f"  · {rollout.rollout_uuid[:12]}: PiP overlay…")
            out.parent.mkdir(parents=True, exist_ok=True)
            r = subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(cam_mp4),
                "-i", str(bev_mp4),
                "-filter_complex",
                "[1:v]scale=iw*0.45:-1[bev];[0:v][bev]overlay=W-w-20:20",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-shortest",
                str(out),
            ], capture_output=True)
            if r.returncode != 0:
                out.unlink(missing_ok=True)
                print(f"  ❌ sync ffmpeg fail: {r.stderr.decode()[:200]}")
                return None

    size_kb = out.stat().st_size / 1024
    print(f"  ✅ {rollout.rollout_uuid[:12]} → {out.name} ({size_kb:.0f}KB, {len(steps)} steps)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--uuid", help="rollout uuid substring (renders just this one)")
    ap.add_argument("--all", action="store_true", help="render all rollouts")
    ap.add_argument("--minimap-only", action="store_true",
                    help="render BEV minimap mp4 without PiP (camera mp4 not required) — for ⓑ-2 light-weight track demo")
    args = ap.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    rollouts = existing_rollouts()
    if args.uuid:
        rollouts = [r for r in rollouts if args.uuid in r.rollout_uuid]
    elif not args.all:
        # default: just the first non-empty rollout
        rollouts = rollouts[:1]
    print(f"=== Rendering sync for {len(rollouts)} rollout(s) ===")
    ok = fail = 0
    for r in rollouts:
        try:
            res = render_sync(r, force=args.force, minimap_only=args.minimap_only)
            ok += 1 if res else 0
            fail += 0 if res else 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ {r.rollout_uuid[:12]} exception: {exc}")
            fail += 1
    print(f"=== done: {ok} ok, {fail} fail ===")


if __name__ == "__main__":
    main()
