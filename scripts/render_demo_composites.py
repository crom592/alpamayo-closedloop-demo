"""Render Tab ② composite videos: 4 scenarios × 3 conditions.

For each of the 4 curated scenarios ([0,3,7,19]) the script:
  1. loads the Physical-AI AV clip,
  2. runs Alpamayo 1.5 three times (V2X / no-nav / counterfactual),
  3. renders one composite frame (camera + BEV + per-condition CoT lines),
  4. writes a short mp4 that holds the frame so the viewer can read it,
  5. saves to demo_cache/scen_XX/composite.mp4 .

Loads the model once (eager attention so it works on host venv where SDPA
isn't supported for Alpamayo1_5).
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

from alpamayo1_5 import helper, nav_utils
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
HOLD_SECONDS = 6.0
FPS = 2


def main() -> int:
    samples_path = NB_DIR / "nav_demo_samples.json"
    cache_root = NB_DIR / "demo_cache"
    if not samples_path.exists():
        print(f"missing {samples_path}", file=sys.stderr)
        return 1
    samples = json.loads(samples_path.read_text())

    print("loading Alpamayo 1.5 (eager attention)...")
    t0 = time.time()
    model = Alpamayo1_5.from_pretrained(
        "nvidia/Alpamayo-1.5-10B",
        dtype=torch.bfloat16,
        attn_implementation="eager",
    ).to("cuda")
    processor = helper.get_processor(model.tokenizer)
    print(f"  ready in {time.time() - t0:.1f}s")

    n_frames = max(1, int(round(HOLD_SECONDS * FPS)))

    for idx in SCEN_INDICES:
        s = samples[idx]
        nav_text = s["nav_text"]
        try:
            cf_text = nav_utils.swap_direction(nav_text)
        except Exception:
            cf_text = (
                nav_text.replace("right", "RIGHT")
                .replace("left", "right")
                .replace("RIGHT", "left")
            )

        scen_dir = cache_root / f"scen_{idx:02d}"
        scen_dir.mkdir(parents=True, exist_ok=True)
        out_path = scen_dir / "composite.mp4"

        print(f"\n[{idx}] clip={s['clip_id'][:8]} t0={s['t0_relative']} '{nav_text}'")
        t0 = time.time()
        data = load_physical_aiavdataset(s["clip_id"], t0_us=s["t0_relative"])

        print(f"  (a) with nav: {nav_text}")
        pred_with, cot_with = run_one_condition(model, processor, data, nav_text)
        print(f"  (b) no nav")
        pred_no, cot_no = run_one_condition(model, processor, data, None)
        print(f"  (c) counterfactual: {cf_text}")
        pred_cf, cot_cf = run_one_condition(model, processor, data, cf_text)

        cam = (
            data["image_frames"][FRONT_WIDE_CAM_INDEX_IN_BATCH, -1]
            .permute(1, 2, 0)
            .cpu()
            .numpy()
        )
        if cam.dtype != np.uint8:
            cam = (
                (cam.clip(0, 1) * 255).astype(np.uint8)
                if cam.max() <= 1.5
                else cam.astype(np.uint8)
            )

        gt_xy = data["ego_future_xyz"].cpu().numpy()[0, 0, :, :2].T
        bev = render_bev(
            {
                f"V2X: {nav_text}": (pred_with, COLORS["with_nav"]),
                "차량 단독 (V2X 미수신)": (pred_no, COLORS["no_nav"]),
                f"반사실: {cf_text}": (pred_cf, COLORS["counterfactual"]),
            },
            gt_xy,
            v2x_text=nav_text,
            v2x_distance=s.get("distance_m"),
        )

        title = (
            f"시나리오 [{idx}] {s.get('nav_maneuver', '')} "
            f"(거리 {s.get('distance_m', 0):.1f}m)"
        )
        nav_lines = [
            (f"V2X 연계 ({nav_text}):", COLORS["with_nav"], cot_with),
            ("차량 단독 (V2X 미수신):", COLORS["no_nav"], cot_no),
            (f"반사실 ({cf_text}):", COLORS["counterfactual"], cot_cf),
        ]
        frame = composite_frame(cam, bev, title, nav_lines)
        mp.write_video(str(out_path), [frame] * n_frames, fps=FPS)
        size_kb = out_path.stat().st_size / 1024
        print(
            f"  saved {out_path.relative_to(REPO_ROOT)} "
            f"({size_kb:.0f}KB, {n_frames} frames @ {FPS}fps = {HOLD_SECONDS:.1f}s)  "
            f"[{time.time() - t0:.1f}s]"
        )

    print("\nall done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
