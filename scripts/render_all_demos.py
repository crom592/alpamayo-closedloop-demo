"""Render the full demo_cache for all 20 scenarios in nav_demo_samples.json.

Replaces the trio of ARM-era scripts (prerender_demo_cache.py +
prerender_extras.py + render_demo_composites.py). Loads Alpamayo 1.5 once
(eager attention, required on KADaP host venv) and produces per scenario:

  scen_XX/camera.mp4          — ~10 s of front-wide footage (5 stitched chunks)
  scen_XX/bev_<preset>.png    — 8 V2X presets (default/baseline/left/right × 5,30,100m)
  scen_XX/cam_<n>cam.png      — 1/2/4 camera-count BEV comparisons
  scen_XX/cam_meta.json       — per cam-count CoT + metrics
  scen_XX/composite.mp4       — 15-frame timeline (0.3 s/frame, V2X-only)

  demo_cache/metadata.json    — top-level scenario index for Tab ③

VQA is no longer cached — Tab ④ runs live inference per user query.

Estimated GPU time: ~75 min (20 scen × ~3.5 min inferences + 5 min model load).
"""
from __future__ import annotations

import json
import re as _re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NB_DIR = REPO_ROOT / "alpamayo1.5" / "notebooks"
OVERLAY_NB = REPO_ROOT / "overlay" / "alpamayo1.5" / "notebooks"
sys.path.insert(0, str(REPO_ROOT / "alpamayo1.5" / "src"))
sys.path.insert(0, str(OVERLAY_NB))

import mediapy as mp
import numpy as np
import torch
from PIL import Image

import physical_ai_av
from alpamayo1_5 import helper
from alpamayo1_5.load_physical_aiavdataset import load_physical_aiavdataset
from alpamayo1_5.models.alpamayo1_5 import Alpamayo1_5

from make_video_nav import (  # type: ignore
    COLORS,
    FRONT_WIDE_CAM_INDEX_IN_BATCH,
    composite_frame,
    render_bev,
    run_one_condition,
)

CACHE_DIR = NB_DIR / "demo_cache"
SAMPLES_PATH = NB_DIR / "nav_demo_samples.json"

CAM_NUM_FRAMES = 20
CAM_NUM_CHUNKS = 5
CAM_SHIFT_US = 1_500_000
CAM_FPS = 10

TIMELINE_N = 15
TIMELINE_STEP_US = 300_000
TIMELINE_FPS = 2

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

CAM_CONFIGS = [
    ("1cam", "1 camera (front-wide only)"),
    ("2cam", "2 cameras (front-wide + front-tele)"),
    ("4cam", "4 cameras (cross-left, front-wide, cross-right, front-tele)"),
]


def get_cam_features(avdi, key):
    cf = avdi.features.CAMERA
    if key == "1cam":
        return [cf.CAMERA_FRONT_WIDE_120FOV]
    if key == "2cam":
        return [cf.CAMERA_FRONT_WIDE_120FOV, cf.CAMERA_FRONT_TELE_30FOV]
    return [
        cf.CAMERA_CROSS_LEFT_120FOV,
        cf.CAMERA_FRONT_WIDE_120FOV,
        cf.CAMERA_CROSS_RIGHT_120FOV,
        cf.CAMERA_FRONT_TELE_30FOV,
    ]


def compute_metrics(pred_xy: np.ndarray, gt_xy: np.ndarray) -> dict:
    T = min(pred_xy.shape[1], gt_xy.shape[1])
    p, g = pred_xy[:, :T], gt_xy[:, :T]
    diff = np.linalg.norm(p - g, axis=0)
    head_err = 0.0
    if T >= 2:
        def heading(xy):
            return float(np.degrees(np.arctan2(xy[1, -1] - xy[1, -2], xy[0, -1] - xy[0, -2])))
        head_err = abs(heading(p) - heading(g))
    return {
        "ADE (m)": float(diff.mean()),
        "FDE (m)": float(diff[-1]),
        "Max lateral dev (m)": float(np.abs(p[1] - g[1]).max()),
        "Heading err (°)": head_err,
    }


def safe_load(clip_id: str, t0: int, n: int):
    for num in (n, n // 2, 8, 4):
        try:
            return load_physical_aiavdataset(clip_id, t0_us=t0, num_frames=num)
        except Exception as e:
            print(f"      num_frames={num} failed: {e}")
    raise RuntimeError("all num_frames values failed")


def categorize(s: dict) -> str:
    d = float(s.get("distance_m", 0))
    direction = "좌회전" if "left" in s["nav_text"].lower() else "우회전"
    if d < 10:
        scale = "근거리"
    elif d < 50:
        scale = "중거리"
    else:
        scale = "원거리"
    return f"{scale} {direction}"


def render_camera_mp4(s: dict, scen_dir: Path) -> bool:
    t_start = time.time()
    center = s["t0_relative"]
    chunk_t0s = [
        center + (k - CAM_NUM_CHUNKS // 2) * CAM_SHIFT_US for k in range(CAM_NUM_CHUNKS)
    ]
    cam_frames: list[np.ndarray] = []
    for ci, ct0 in enumerate(chunk_t0s):
        if ct0 < 0:
            ct0 = max(2_000_000, ct0)
        try:
            data_cam = safe_load(s["clip_id"], int(ct0), CAM_NUM_FRAMES)
        except Exception as e:
            print(f"    chunk {ci} (t0={ct0}) failed: {e}")
            continue
        for f in data_cam["image_frames"][FRONT_WIDE_CAM_INDEX_IN_BATCH]:
            arr = f.permute(1, 2, 0).cpu().numpy()
            if arr.dtype != np.uint8:
                arr = (
                    (arr.clip(0, 1) * 255).astype(np.uint8)
                    if arr.max() <= 1.5
                    else arr.astype(np.uint8)
                )
            cam_frames.append(arr)
    if not cam_frames:
        return False
    mp.write_video(str(scen_dir / "camera.mp4"), cam_frames, fps=CAM_FPS)
    print(f"    camera.mp4 ({len(cam_frames)} frames, {time.time() - t_start:.1f}s)")
    return True


def render_bev_presets(s: dict, scen_dir: Path, model, processor) -> dict:
    data_inf = load_physical_aiavdataset(s["clip_id"], t0_us=s["t0_relative"])
    gt_xy = data_inf["ego_future_xyz"].cpu().numpy()[0, 0, :, :2].T
    meta = {
        "scen_idx": s["_idx"],
        "clip_id": s["clip_id"],
        "category": s["_category"],
        "distance_m": s["distance_m"],
        "default_nav_text": s["nav_text"],
        "camera_mp4": f"scen_{s['_idx']:02d}/camera.mp4",
        "presets": [],
    }
    for key, display, nav_arg in PRESETS:
        actual_nav = s["nav_text"] if nav_arg == "__USE_DEFAULT__" else nav_arg
        pred_xy, cot = run_one_condition(model, processor, data_inf, actual_nav)
        metrics = compute_metrics(pred_xy, gt_xy)
        color_key = "no_nav" if actual_nav is None else "with_nav"
        _dist_match = _re.search(r"(\d+)\s*m", actual_nav) if actual_nav else None
        _v2x_dist = float(_dist_match.group(1)) if _dist_match else None
        bev = render_bev(
            {display: (pred_xy, COLORS[color_key])},
            gt_xy,
            v2x_text=actual_nav,
            v2x_distance=_v2x_dist,
        )
        Image.fromarray(bev).save(scen_dir / f"bev_{key}.png")
        meta["presets"].append(
            {
                "key": key,
                "display": display,
                "actual_nav": actual_nav,
                "cot": cot,
                "metrics": metrics,
                "bev_path": f"scen_{s['_idx']:02d}/bev_{key}.png",
            }
        )
    return meta


def render_cam_count(s: dict, scen_dir: Path, model, processor, avdi) -> None:
    cam_meta = []
    for key, label in CAM_CONFIGS:
        try:
            data_c = load_physical_aiavdataset(
                s["clip_id"], avdi=avdi, camera_features=get_cam_features(avdi, key)
            )
        except Exception as e:
            print(f"    cam_{key} load failed: {e}")
            continue
        pred_xy, cot = run_one_condition(model, processor, data_c, None)
        gt_xy = data_c["ego_future_xyz"].cpu().numpy()[0, 0, :, :2].T
        metrics = compute_metrics(pred_xy, gt_xy)
        bev = render_bev({label: (pred_xy, COLORS["with_nav"])}, gt_xy)
        Image.fromarray(bev).save(scen_dir / f"cam_{key}.png")
        cam_meta.append(
            {
                "key": key,
                "label": label,
                "n_cams": int(key[0]),
                "cot": cot,
                "metrics": metrics,
            }
        )
    (scen_dir / "cam_meta.json").write_text(
        json.dumps(cam_meta, indent=2, ensure_ascii=False)
    )


def render_timeline_composite(s: dict, scen_dir: Path, model, processor) -> None:
    nav_text = s["nav_text"]
    frames = []
    for k in range(TIMELINE_N):
        t0_us = s["t0_relative"] + k * TIMELINE_STEP_US
        try:
            data = load_physical_aiavdataset(s["clip_id"], t0_us=t0_us)
        except Exception as e:
            print(f"    timeline frame {k} (t0={t0_us / 1e6:.2f}s): skip ({e})")
            continue
        pred, cot = run_one_condition(model, processor, data, nav_text)
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
            {f"V2X: {nav_text}": (pred, COLORS["with_nav"])},
            gt_xy,
            v2x_text=nav_text,
            v2x_distance=s.get("distance_m"),
        )
        t_now = t0_us / 1e6
        title = (
            f"시나리오 [{s['_idx']}] {s.get('nav_maneuver', '')} "
            f"(거리 {s.get('distance_m', 0):.1f}m) · "
            f"t={t_now:.2f}s · 프레임 {k + 1}/{TIMELINE_N}"
        )
        frames.append(
            composite_frame(
                cam,
                bev,
                title,
                [
                    (
                        f"AI 추론 ({nav_text}):",
                        COLORS["with_nav"],
                        cot or "(추론 사유 없음)",
                    )
                ],
            )
        )
    if frames:
        mp.write_video(str(scen_dir / "composite.mp4"), frames, fps=TIMELINE_FPS)


def main() -> int:
    if not SAMPLES_PATH.exists():
        print(f"missing {SAMPLES_PATH}", file=sys.stderr)
        return 1
    samples = json.loads(SAMPLES_PATH.read_text())
    for i, s in enumerate(samples):
        s["_idx"] = i
        s["_category"] = categorize(s)

    CACHE_DIR.mkdir(exist_ok=True)
    print(f"loading Alpamayo 1.5 (eager attention)... target {len(samples)} scenarios")
    t_load = time.time()
    model = Alpamayo1_5.from_pretrained(
        "nvidia/Alpamayo-1.5-10B",
        dtype=torch.bfloat16,
        attn_implementation="eager",
    ).to("cuda")
    processor = helper.get_processor(model.tokenizer)
    avdi = physical_ai_av.PhysicalAIAVDatasetInterface()
    print(f"  ready in {time.time() - t_load:.1f}s")

    metadata = {"scenarios": []}
    overall_t0 = time.time()
    for s in samples:
        idx = s["_idx"]
        scen_dir = CACHE_DIR / f"scen_{idx:02d}"
        scen_dir.mkdir(exist_ok=True)
        t_scen = time.time()
        print(
            f"\n=== [{idx + 1:>2}/{len(samples)}] scen_{idx:02d} | {s['_category']} | "
            f"clip={s['clip_id'][:8]} | base_t0={s['t0_relative'] / 1e6:.2f}s | "
            f"V2X='{s['nav_text']}' ==="
        )
        try:
            if not render_camera_mp4(s, scen_dir):
                print("  camera.mp4 produced no frames — skipping scenario")
                continue

            print("  [bev presets x 8]")
            scen_meta = render_bev_presets(s, scen_dir, model, processor)
            metadata["scenarios"].append(scen_meta)

            print("  [cam-count x 3]")
            render_cam_count(s, scen_dir, model, processor, avdi)

            print(f"  [timeline composite x {TIMELINE_N}]")
            render_timeline_composite(s, scen_dir, model, processor)

            print(
                f"  ✅ scen_{idx:02d} done in {time.time() - t_scen:.0f}s "
                f"(cumulative {(time.time() - overall_t0) / 60:.1f} min)"
            )
        except Exception as e:  # noqa: BLE001
            import traceback
            print(f"  ❌ scen_{idx:02d} FAILED: {e}")
            traceback.print_exc()

    meta_path = CACHE_DIR / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2, default=str, ensure_ascii=False))
    print(
        f"\n✅ all done. {len(metadata['scenarios'])} / {len(samples)} scenarios cached "
        f"in {(time.time() - overall_t0) / 60:.1f} min total."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
