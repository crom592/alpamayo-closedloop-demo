#!/usr/bin/env python3
"""Render NRE closed-loop rollout → mp4 with V2X/metrics/speed overlay.

For each rollout under alpasim run_dir/rollouts/, materialise
front_wide_120fov frames (if needed), parse step metrics, render
matplotlib overlay panels, then ffmpeg-encode as 2fps mp4 cached
under kadap-poc-v2/closedloop_videos/<rollout_uuid>.mp4.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "kadap-poc"))

from runner import RolloutRef, existing_rollouts  # noqa: E402
import trace as trace_mod  # noqa: E402
import metrics as metrics_mod  # noqa: E402

from matplotlib import font_manager as _fm
import matplotlib.pyplot as plt
from PIL import Image

# Korean glyph support (mirror vlm_qa.py / make_video_nav.py).
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
CAMERA_NAME = "camera_front_wide_120fov"
FPS = 2  # matches Tab ② composite pattern


def render_one(rollout: RolloutRef, force: bool) -> Path | None:
    """Render this rollout's mp4. Returns the mp4 path on success, None on skip/fail."""
    out = CACHE_DIR / f"{rollout.rollout_uuid}.mp4"
    if out.exists() and not force:
        print(f"  ✅ {rollout.rollout_uuid[:12]} cached (skip)")
        return out

    print(f"  · {rollout.rollout_uuid[:12]}: ensuring frames…")
    try:
        frames_dir = trace_mod.ensure_frames_extracted(rollout, force=True, timeout=900)
    except Exception as exc:
        print(f"  ❌ {rollout.rollout_uuid[:12]}: frame extract failed: {exc}")
        return None
    cam_dir = frames_dir / CAMERA_NAME
    if not cam_dir.exists():
        print(f"  ❌ {rollout.rollout_uuid[:12]}: no {CAMERA_NAME} after extract")
        return None
    jpgs = sorted(cam_dir.glob("*.jpg"))
    if not jpgs:
        print(f"  ❌ {rollout.rollout_uuid[:12]}: 0 frames")
        return None

    print(f"  · {rollout.rollout_uuid[:12]}: parsing ASL ({len(jpgs)} frames)…")
    steps = trace_mod.parse_steps(rollout)
    m = metrics_mod.compute(rollout.asl)
    v2x_text = rollout.meta.get("v2x_text") or "(V2X 미기록)"
    ade_str = f"avg_v={m.avg_speed:.2f}m/s" if not m.is_empty else "metrics=N/A"
    max_str = f"max_v={m.max_speed:.2f}m/s" if not m.is_empty else ""

    print(f"  · {rollout.rollout_uuid[:12]}: composing {len(jpgs)} overlay frames…")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for k, jpg in enumerate(jpgs):
            step = steps[k] if k < len(steps) else None
            overlay_path = tmp_dir / f"frame_{k:04d}.png"
            _compose_frame(jpg, overlay_path, v2x_text, ade_str, max_str, k, len(jpgs), step)
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-framerate", str(FPS),
            "-i", str(tmp_dir / "frame_%04d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
            str(out),
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            out.unlink(missing_ok=True)
            print(f"  ❌ {rollout.rollout_uuid[:12]} ffmpeg fail: {result.stderr.decode()[:200]}")
            return None

    size_kb = out.stat().st_size / 1024
    print(f"  ✅ {rollout.rollout_uuid[:12]} → {out.name} ({size_kb:.0f}KB)")
    return out


def _compose_frame(jpg_in, png_out, v2x_text, ade_str, max_str, k, n, step):
    """Burn V2X/metrics/step overlay onto a single front_wide frame."""
    img = Image.open(jpg_in)
    w, h = img.size
    fig, ax = plt.subplots(figsize=(w / 100, h / 100), dpi=100)
    ax.imshow(img)
    ax.set_axis_off()
    ax.set_xlim(0, w); ax.set_ylim(h, 0)

    # Top-left V2X banner (yellow background)
    ax.text(
        20, 40, f"[V2X] {v2x_text}",
        fontsize=18, color="black",
        bbox=dict(facecolor="#f1c40f", edgecolor="none", pad=8),
        verticalalignment="top",
    )

    # Top-right step indicator
    if step is not None:
        step_str = f"step {k+1}/{n} · t={step.sim_time_s:.1f}s · v={step.ego_speed:.1f}m/s · plan {step.n_predicted} pts"
    else:
        step_str = f"step {k+1}/{n}"
    ax.text(
        w - 20, 40, step_str,
        fontsize=12, color="white",
        bbox=dict(facecolor="black", alpha=0.6, edgecolor="none", pad=6),
        verticalalignment="top", horizontalalignment="right",
    )

    # Bottom-right metrics
    metric_str = f"{ade_str} | {max_str}".strip(" |")
    ax.text(
        w - 20, h - 20, metric_str,
        fontsize=14, color="white",
        bbox=dict(facecolor="black", alpha=0.6, edgecolor="none", pad=6),
        verticalalignment="bottom", horizontalalignment="right",
    )

    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    fig.savefig(png_out, dpi=100, bbox_inches=None, pad_inches=0)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="Re-render even if mp4 exists")
    ap.add_argument("--uuid", help="Render only this rollout uuid (substring match)")
    args = ap.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    rollouts = existing_rollouts()
    if args.uuid:
        rollouts = [r for r in rollouts if args.uuid in r.rollout_uuid]
    print(f"=== Rendering {len(rollouts)} rollout(s) ===")
    ok = fail = 0
    for r in rollouts:
        try:
            res = render_one(r, force=args.force)
            ok += 1 if res else 0
            fail += 0 if res else 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ {r.rollout_uuid[:12]} exception: {exc}")
            fail += 1
    print(f"=== done: {ok} ok, {fail} fail ===")


if __name__ == "__main__":
    main()
