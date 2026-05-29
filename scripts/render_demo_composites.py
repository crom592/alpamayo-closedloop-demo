"""Render Tab ② timeline videos: 4 scenarios × 15 frames (t0 sweep).

For each of the 4 curated scenarios ([0,3,7,19]) the script:
  1. sweeps t0_us forward 15 steps at 0.3 s intervals,
  2. at each step, loads the Physical-AI AV clip frame + runs Alpamayo 1.5
     ONCE with the V2X nav_text (the active driving condition),
  3. renders a composite frame (camera + BEV trajectory + CoT subtitle),
  4. stitches the frames into a short mp4 at 2 fps (~7.5 s playback),
  5. saves to demo_cache/scen_XX/composite.mp4 .

The viewer sees the AV's reasoning evolve as time progresses through the
scene — mirroring the original Alpamayo 1.5 reference video format.

Loads the model once (eager attention, required on host venv where SDPA
is unsupported for Alpamayo1_5).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NB_DIR = REPO_ROOT / "alpamayo1.5" / "notebooks"
OVERLAY_NB = REPO_ROOT / "overlay" / "alpamayo1.5" / "notebooks"
sys.path.insert(0, str(REPO_ROOT / "alpamayo1.5" / "src"))
sys.path.insert(0, str(OVERLAY_NB))

import torch
import mediapy as mp
import numpy as np

from alpamayo1_5 import helper
from alpamayo1_5.load_physical_aiavdataset import load_physical_aiavdataset
from alpamayo1_5.models.alpamayo1_5 import Alpamayo1_5

from make_video_nav import (  # type: ignore
    run_one_condition,
    render_bev,
    composite_frame,
    COLORS,
    FRONT_WIDE_CAM_INDEX_IN_BATCH,
)

SCEN_INDICES = [0, 3, 7, 19]
N_FRAMES = 15           # match the Alpamayo 1.5 reference video length
STEP_US = 300_000       # 0.3 s between frames
FPS = 2                 # playback: 15 frames / 2 fps = 7.5 s


def main() -> int:
    samples_path = NB_DIR / "nav_demo_samples.json"
    cache_root = NB_DIR / "demo_cache"
    if not samples_path.exists():
        print(f"missing {samples_path}", file=sys.stderr)
        return 1
    samples = json.loads(samples_path.read_text())

    print("loading Alpamayo 1.5 (eager attention)...")
    t0_load = time.time()
    model = Alpamayo1_5.from_pretrained(
        "nvidia/Alpamayo-1.5-10B",
        dtype=torch.bfloat16,
        attn_implementation="eager",
    ).to("cuda")
    processor = helper.get_processor(model.tokenizer)
    print(f"  ready in {time.time() - t0_load:.1f}s")

    for idx in SCEN_INDICES:
        s = samples[idx]
        nav_text = s["nav_text"]
        scen_dir = cache_root / f"scen_{idx:02d}"
        scen_dir.mkdir(parents=True, exist_ok=True)
        out_path = scen_dir / "composite.mp4"

        print(
            f"\n[{idx}] clip={s['clip_id'][:8]} base_t0={s['t0_relative']/1e6:.2f}s "
            f"V2X='{nav_text}'"
        )
        t_scen = time.time()
        frames = []
        for k in range(N_FRAMES):
            t0_us = s["t0_relative"] + k * STEP_US
            try:
                data = load_physical_aiavdataset(s["clip_id"], t0_us=t0_us)
            except Exception as e:  # noqa: BLE001
                print(f"  frame {k} (t0={t0_us/1e6:.2f}s): load failed ({e}) — skip")
                continue

            t0_inf = time.time()
            pred, cot = run_one_condition(model, processor, data, nav_text)
            cam = (
                data["image_frames"][FRONT_WIDE_CAM_INDEX_IN_BATCH, -1]
                .permute(1, 2, 0).cpu().numpy()
            )
            if cam.dtype != np.uint8:
                cam = (
                    (cam.clip(0, 1) * 255).astype(np.uint8)
                    if cam.max() <= 1.5
                    else cam.astype(np.uint8)
                )
            gt_xy = data["ego_future_xyz"].cpu().numpy()[0, 0, :, :2].T
            bev = render_bev(
                {f"V2X: {nav_text}": (pred, COLORS["with_nav"])},
                gt_xy,
                v2x_text=nav_text,
                v2x_distance=s.get("distance_m"),
            )

            t_now = t0_us / 1e6
            title = (
                f"시나리오 [{idx}] {s.get('nav_maneuver', '')} "
                f"(거리 {s.get('distance_m', 0):.1f}m) · "
                f"t={t_now:.2f}s · 프레임 {k + 1}/{N_FRAMES}"
            )
            nav_lines = [
                (
                    f"AI 추론 ({nav_text}):",
                    COLORS["with_nav"],
                    cot or "(추론 사유 없음)",
                ),
            ]
            frames.append(composite_frame(cam, bev, title, nav_lines))
            print(f"  frame {k + 1:>2}/{N_FRAMES} t={t_now:.2f}s [{time.time() - t0_inf:.1f}s]")

        if not frames:
            print(f"  no frames produced for scen_{idx:02d}, skip mp4")
            continue
        mp.write_video(str(out_path), frames, fps=FPS)
        size_kb = out_path.stat().st_size / 1024
        elapsed = time.time() - t_scen
        print(
            f"  saved {out_path.relative_to(REPO_ROOT)} "
            f"({size_kb:.0f}KB, {len(frames)} frames @ {FPS}fps = {len(frames) / FPS:.1f}s) "
            f"[scenario total {elapsed:.0f}s]"
        )

    print("\nall done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
