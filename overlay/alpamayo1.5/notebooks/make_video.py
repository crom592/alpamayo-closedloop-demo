"""Run Alpamayo 1.5 over a temporal sequence of a single clip and render an mp4
showing the front-wide camera with predicted/GT trajectories and chain-of-causation
text overlaid. Open-loop: ego follows GT, model only observes and predicts.
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mediapy as mp
import numpy as np
import pandas as pd
import torch
from PIL import Image, ImageDraw, ImageFont

from alpamayo1_5 import helper
from alpamayo1_5.load_physical_aiavdataset import load_physical_aiavdataset
from alpamayo1_5.models.alpamayo1_5 import Alpamayo1_5

FRONT_WIDE_CAM_INDEX_IN_BATCH = 1  # camera_front_wide_120fov, after sort_order


def render_bev(pred_xy: np.ndarray, gt_xy: np.ndarray, size_px: int = 360) -> np.ndarray:
    """Render a small BEV plot of predicted vs GT trajectory and return as RGB array."""
    fig, ax = plt.subplots(figsize=(size_px / 100, size_px / 100), dpi=100)
    ax.plot(gt_xy[1], gt_xy[0], "w-", linewidth=2, label="GT")
    ax.plot(pred_xy[1], pred_xy[0], "o-", color="#00ff88", markersize=2, linewidth=1.5, label="Pred")
    ax.scatter([0], [0], c="red", s=40, zorder=5, label="ego")
    lim = max(20.0, np.abs(np.concatenate([pred_xy, gt_xy], axis=1)).max() * 1.1)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-5, lim * 2)
    ax.set_aspect("equal")
    ax.set_facecolor("#101418")
    ax.tick_params(colors="#888", labelsize=6)
    for spine in ax.spines.values():
        spine.set_color("#444")
    ax.legend(loc="upper right", fontsize=6, framealpha=0.4)
    ax.set_title("BEV (m)", color="#aaa", fontsize=8)
    fig.patch.set_facecolor("#101418")
    fig.tight_layout(pad=0.2)
    fig.canvas.draw()
    img = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()
    plt.close(fig)
    return img


def wrap_text(text: str, max_chars: int = 90) -> list[str]:
    """Naive word wrap."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines[:6]


def composite_frame(camera_rgb: np.ndarray, bev_rgb: np.ndarray, cot_text: str) -> np.ndarray:
    """Place camera as background, BEV in top-right corner, CoT text along the bottom."""
    H, W, _ = camera_rgb.shape
    canvas = Image.fromarray(camera_rgb)
    bev_img = Image.fromarray(bev_rgb)
    margin = 12
    canvas.paste(bev_img, (W - bev_img.width - margin, margin))

    draw = ImageDraw.Draw(canvas, "RGBA")
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except OSError:
        font = ImageFont.load_default()

    lines = wrap_text(cot_text, max_chars=int(W / 12))
    pad = 10
    line_h = 22
    box_h = line_h * len(lines) + pad * 2
    draw.rectangle([(0, H - box_h), (W, H)], fill=(0, 0, 0, 160))
    for i, line in enumerate(lines):
        draw.text((pad, H - box_h + pad + i * line_h), line, fill=(255, 255, 255), font=font)

    return np.array(canvas)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip-index", type=int, default=774, help="Index into clip_ids.parquet")
    ap.add_argument("--num-frames", type=int, default=20)
    ap.add_argument("--start-us", type=int, default=5_100_000)
    ap.add_argument("--step-us", type=int, default=300_000)  # 0.3s between frames -> 3.3 fps
    ap.add_argument("--fps", type=int, default=4)
    ap.add_argument("--out", type=str, default="alpamayo_openloop.mp4")
    args = ap.parse_args()

    notebook_dir = Path(__file__).parent
    clip_ids = pd.read_parquet(notebook_dir / "clip_ids.parquet")["clip_id"].tolist()
    clip_id = clip_ids[args.clip_index]
    print(f"clip_id = {clip_id}")

    print("Loading model (this can take a minute)...")
    model = Alpamayo1_5.from_pretrained(
        "nvidia/Alpamayo-1.5-10B", dtype=torch.bfloat16
    ).to("cuda")
    processor = helper.get_processor(model.tokenizer)
    print("Model ready.")

    video_frames = []
    for k in range(args.num_frames):
        t0 = args.start_us + k * args.step_us
        print(f"\n[{k + 1}/{args.num_frames}] t0_us = {t0}")
        try:
            data = load_physical_aiavdataset(clip_id, t0_us=t0)
        except Exception as e:
            print(f"  load failed: {e}; stopping early.")
            break

        messages = helper.create_message(
            frames=data["image_frames"].flatten(0, 1),
            camera_indices=data["camera_indices"],
        )
        inputs = processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=False,
            continue_final_message=True,
            return_dict=True,
            return_tensors="pt",
        )
        model_inputs = helper.to_device(
            {
                "tokenized_data": inputs,
                "ego_history_xyz": data["ego_history_xyz"],
                "ego_history_rot": data["ego_history_rot"],
            },
            "cuda",
        )
        torch.cuda.manual_seed_all(42 + k)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            pred_xyz, _, extra = model.sample_trajectories_from_data_with_vlm_rollout(
                data=model_inputs,
                top_p=0.98,
                temperature=0.6,
                num_traj_samples=1,
                max_generation_length=256,
                return_extra=True,
            )

        cot = extra["cot"][0] if extra.get("cot") else ""
        if isinstance(cot, str):
            cot_str = cot
        else:
            try:
                cot_str = " ".join(str(x) for x in cot)
            except TypeError:
                cot_str = str(cot)
        print("  CoT:", cot_str[:160].replace("\n", " "))

        # Camera frame: front-wide, latest of 4 history frames
        cam = (
            data["image_frames"][FRONT_WIDE_CAM_INDEX_IN_BATCH, -1]
            .permute(1, 2, 0)
            .cpu()
            .numpy()
        )
        if cam.dtype != np.uint8:
            cam = (cam.clip(0, 1) * 255).astype(np.uint8) if cam.max() <= 1.5 else cam.astype(np.uint8)

        pred_xy = pred_xyz.cpu().numpy()[0, 0, 0, :, :2].T  # (2, T)
        gt_xy = data["ego_future_xyz"].cpu().numpy()[0, 0, :, :2].T

        bev = render_bev(pred_xy, gt_xy)
        frame = composite_frame(cam, bev, cot_str)
        video_frames.append(frame)

    if not video_frames:
        raise SystemExit("No frames produced.")

    out_path = notebook_dir / args.out
    print(f"\nWriting {len(video_frames)} frames to {out_path} @ {args.fps} fps")
    mp.write_video(str(out_path), video_frames, fps=args.fps)
    print("Done.")


if __name__ == "__main__":
    main()
