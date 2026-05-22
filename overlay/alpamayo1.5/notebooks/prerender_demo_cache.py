"""Prerender demo cache for the interactive tab.

For each demo scenario, render once (offline):
  - camera.mp4   : ~2 sec of front-wide camera footage (loop in UI)
  - bev_<preset>.png + metadata : BEV image + CoT + metrics for each V2X preset

Caches everything under notebooks/demo_cache/, then the Gradio app reads from
disk for instant playback (no model invocation in the UI hot path).

Run inside alpamayo-poc:
    PYTHONPATH=/workspace/alpamayo1.5/src:. python prerender_demo_cache.py
"""

import json
from pathlib import Path

import mediapy as mp
import numpy as np
import torch
from PIL import Image

from alpamayo1_5 import helper
from alpamayo1_5.load_physical_aiavdataset import load_physical_aiavdataset
from alpamayo1_5.models.alpamayo1_5 import Alpamayo1_5

from app import compute_metrics, load_samples
from make_video_nav import (
    COLORS,
    FRONT_WIDE_CAM_INDEX_IN_BATCH,
    render_bev,
    run_one_condition,
)

NOTEBOOK_DIR = Path(__file__).parent
CACHE_DIR = NOTEBOOK_DIR / "demo_cache"
CACHE_DIR.mkdir(exist_ok=True)

DEMO_INDICES = [0, 3, 7, 19]

# Camera prerender: each load returns `num_frames=20` history frames at 0.1s spacing
# = 2 sec of footage ending at t0. To get a longer video we stitch multiple loads,
# each shifted forward by SHIFT_US so the chunks overlap minimally.
CAM_NUM_FRAMES = 20         # frames per load (~2 sec)
CAM_NUM_CHUNKS = 5          # 5 chunks × 2 sec = ~10 sec total camera (with some overlap)
CAM_SHIFT_US = 1_500_000    # 1.5 s shift between chunks → ~0.5 s overlap
CAM_FPS = 10

# (key, display_text, nav_arg)  — nav_arg=None means baseline (no V2X)
# Alpamayo was trained on the canonical "Turn {left/right} in Nm" nav_text
# format. Out-of-distribution natural-language V2X messages (e.g. "pedestrian",
# "construction") are silently ignored by the model, so we use only canonical-
# format presets for the demo. The fact that OOD messages are ignored is
# itself an argument for the 1차년도 한국 데이터 fine-tuning task.
PRESETS = [
    ("default",   "기본 V2X (시나리오 기본값)", "__USE_DEFAULT__"),
    ("baseline",  "차량 단독 (V2X 미수신)",     None),
    ("left_5",    "Turn left in 5m",          "Turn left in 5m"),
    ("left_30",   "Turn left in 30m",         "Turn left in 30m"),
    ("left_100",  "Turn left in 100m",        "Turn left in 100m"),
    ("right_5",   "Turn right in 5m",         "Turn right in 5m"),
    ("right_30",  "Turn right in 30m",        "Turn right in 30m"),
    ("right_100", "Turn right in 100m",       "Turn right in 100m"),
]


def safe_load(clip_id, t0, n):
    """Try num_frames=n, fall back to smaller if out of range."""
    for num in (n, n // 2, 8, 4):
        try:
            return load_physical_aiavdataset(clip_id, t0_us=t0, num_frames=num), num
        except Exception as e:
            print(f"    num_frames={num} failed: {e}")
    raise RuntimeError("all num_frames values failed")


def main():
    samples = load_samples()
    print("Loading Alpamayo-1.5-10B...")
    model = Alpamayo1_5.from_pretrained(
        "nvidia/Alpamayo-1.5-10B", dtype=torch.bfloat16
    ).to("cuda")
    processor = helper.get_processor(model.tokenizer)
    print("Model ready.\n")

    metadata = {"scenarios": []}

    for scen_idx in DEMO_INDICES:
        if scen_idx >= len(samples):
            continue
        s = samples[scen_idx]
        scen_dir = CACHE_DIR / f"scen_{scen_idx:02d}"
        scen_dir.mkdir(exist_ok=True)
        print(f"\n=== Scenario {scen_idx}: {s['_category']} | d={s['distance_m']:.1f}m | clip={s['clip_id'][:8]} ===")

        # ---- Camera mp4 (stitched from multiple t0 chunks for longer footage) ----
        print(f"  [1/2] Loading camera sequence: {CAM_NUM_CHUNKS} chunks × {CAM_NUM_FRAMES} frames...")
        # Center the chunks around the labeled t0_relative
        center = s["t0_relative"]
        chunk_start_t0s = [center + (k - CAM_NUM_CHUNKS // 2) * CAM_SHIFT_US for k in range(CAM_NUM_CHUNKS)]
        cam_frames = []
        for ci, ct0 in enumerate(chunk_start_t0s):
            if ct0 < 0:
                ct0 = max(2_000_000, ct0)
            try:
                data_cam, _ = safe_load(s["clip_id"], int(ct0), CAM_NUM_FRAMES)
            except Exception as e:
                print(f"    chunk {ci} (t0={ct0}) failed: {e}; skipping")
                continue
            cam_seq = data_cam["image_frames"][FRONT_WIDE_CAM_INDEX_IN_BATCH]  # [N,3,H,W]
            for f in cam_seq:
                arr = f.permute(1, 2, 0).cpu().numpy()
                if arr.dtype != np.uint8:
                    arr = (arr.clip(0, 1) * 255).astype(np.uint8) if arr.max() <= 1.5 else arr.astype(np.uint8)
                cam_frames.append(arr)
            print(f"    chunk {ci + 1}/{CAM_NUM_CHUNKS} ok (cumulative {len(cam_frames)} frames)")

        if not cam_frames:
            print("  No camera frames; skipping scenario")
            continue
        cam_mp4 = scen_dir / "camera.mp4"
        mp.write_video(str(cam_mp4), cam_frames, fps=CAM_FPS)
        print(f"    saved {cam_mp4.name} ({len(cam_frames)} frames @ {CAM_FPS}fps = {len(cam_frames) / CAM_FPS:.1f}s)")

        # ---- BEV per preset ----
        print("  [2/2] Inferring BEV for each preset...")
        # Use default num_frames for inference (model-compatible)
        data_inf = load_physical_aiavdataset(s["clip_id"], t0_us=s["t0_relative"])
        gt_xy = data_inf["ego_future_xyz"].cpu().numpy()[0, 0, :, :2].T

        scen_meta = {
            "scen_idx": scen_idx,
            "clip_id": s["clip_id"],
            "category": s["_category"],
            "distance_m": s["distance_m"],
            "default_nav_text": s["nav_text"],
            "camera_mp4": f"scen_{scen_idx:02d}/camera.mp4",
            "presets": [],
        }

        for key, display, nav_arg in PRESETS:
            actual_nav = s["nav_text"] if nav_arg == "__USE_DEFAULT__" else nav_arg
            label = f"{display}" + (f" → {actual_nav}" if nav_arg == "__USE_DEFAULT__" else "")
            print(f"    - {key}: {actual_nav}")
            pred_xy, cot = run_one_condition(model, processor, data_inf, actual_nav)
            metrics = compute_metrics(pred_xy, gt_xy)

            color_key = "no_nav" if actual_nav is None else "with_nav"
            # Extract distance from nav text for the BEV turn arrow
            import re as _re
            _dist_match = _re.search(r"(\d+)\s*m", actual_nav) if actual_nav else None
            _v2x_dist = float(_dist_match.group(1)) if _dist_match else None
            bev = render_bev(
                {display: (pred_xy, COLORS[color_key])}, gt_xy,
                v2x_text=actual_nav, v2x_distance=_v2x_dist,
            )
            bev_path = scen_dir / f"bev_{key}.png"
            Image.fromarray(bev).save(bev_path)

            scen_meta["presets"].append({
                "key": key,
                "display": display,
                "actual_nav": actual_nav,
                "cot": cot,
                "metrics": metrics,
                "bev_path": f"scen_{scen_idx:02d}/bev_{key}.png",
            })

        metadata["scenarios"].append(scen_meta)
        print(f"  Done.")

    meta_path = CACHE_DIR / "metadata.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2, default=str)
    print(f"\n✅ Cache built: {len(metadata['scenarios'])} scenarios → {meta_path}")


if __name__ == "__main__":
    main()
