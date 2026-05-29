"""For each scenario in nav_demo_samples.json (or a hand-picked subset), run
Alpamayo 1.5 three times on the same camera frame with three different navigation
instructions (assigned / counterfactual / none) and render a composite image.

All scenarios are stitched into a single mp4 with each scenario shown for several
seconds so the viewer can read the captions and compare BEV trajectories.

Open-loop: same camera input, only the text instruction changes.
"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as _fm

# Register Korean fonts so BEV legends/titles render Hangul without tofu boxes.
# NotoSansCJK-Regular.ttc is a TrueType Collection — matplotlib reads only the
# first face, which registers under the JP name (covers Hangul too).
for _f in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
           "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"):
    try:
        _fm.fontManager.addfont(_f)
    except Exception:
        pass
plt.rcParams["font.family"] = ["Noto Sans CJK JP", "NanumGothic", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
import mediapy as mp
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

from alpamayo1_5 import helper, nav_utils
from alpamayo1_5.load_physical_aiavdataset import load_physical_aiavdataset
from alpamayo1_5.models.alpamayo1_5 import Alpamayo1_5

FRONT_WIDE_CAM_INDEX_IN_BATCH = 1

# Color scheme for the three conditions
COLORS = {
    "with_nav": "#00d2ff",       # cyan
    "no_nav": "#ffaa00",          # orange
    "counterfactual": "#ff3366",  # pink
    "gt": "#ffffff",              # white
}


def load_font(size: int):
    # Prefer a CJK font so Korean caption text renders. Falls back through
    # latin-only options and finally PIL default.
    for path in (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def run_one_condition(model, processor, data, nav_text):
    """Run one inference. nav_text=None means unconditioned."""
    frames = data["image_frames"].flatten(0, 1)
    if nav_text is None:
        messages = helper.create_message(frames, camera_indices=data["camera_indices"])
    else:
        messages = helper.create_message(
            frames, camera_indices=data["camera_indices"], nav_text=nav_text
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
    torch.cuda.manual_seed_all(42)
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
    if not isinstance(cot, str):
        try:
            cot = " ".join(str(x) for x in cot)
        except TypeError:
            cot = str(cot)
    pred_xy = pred_xyz.cpu().numpy()[0, 0, 0, :, :2].T  # (2, T)
    return pred_xy, cot


def render_bev(pred_dict, gt_xy, size_px=480, v2x_text=None, v2x_distance=None):
    """Render map-style BEV with road surface, lane markings, V2X overlay, and trajectories.

    pred_dict: {label_key: (xy, color)}.
    v2x_text:  optional V2X message string to display as a banner.
    v2x_distance: optional distance in metres for a turn-direction arrow.
    """
    from matplotlib.patches import FancyArrowPatch, Rectangle
    import re

    fig, ax = plt.subplots(figsize=(size_px / 100, size_px / 100), dpi=100)
    all_pts = [gt_xy] + [v[0] for v in pred_dict.values()]
    flat = np.concatenate(all_pts, axis=1)
    lim = max(20.0, np.abs(flat).max() * 1.15)

    # --- Road surface background (grey) + lane markings ---
    road_hw = min(lim * 0.45, 8.0)  # half-width of road surface
    ax.axvspan(-road_hw, road_hw, color="#3a3a3a", zorder=0)  # road surface
    # Center dashes
    for y in np.arange(0, lim * 2, 3.0):
        ax.plot([0, 0], [y, y + 1.5], color="#cccccc", linewidth=0.8, zorder=1, alpha=0.6)
    # Edge lines
    ax.plot([-road_hw, -road_hw], [-5, lim * 2], color="white", linewidth=1.2, zorder=1, alpha=0.5)
    ax.plot([road_hw, road_hw], [-5, lim * 2], color="white", linewidth=1.2, zorder=1, alpha=0.5)

    # --- Trajectories ---
    ax.plot(gt_xy[1], gt_xy[0], "-", color=COLORS["gt"], linewidth=2.5, label="GT", zorder=3)
    for label, (xy, color) in pred_dict.items():
        ax.plot(xy[1], xy[0], "o-", color=color, markersize=3, linewidth=2, label=label, zorder=4)
    ax.scatter([0], [0], c="red", s=100, zorder=5, marker="^", edgecolors="white", linewidths=0.5)

    # --- V2X direction arrow ---
    if v2x_text and v2x_distance:
        is_left = "left" in v2x_text.lower()
        is_right = "right" in v2x_text.lower()
        d = min(v2x_distance, lim * 1.5)
        if is_left or is_right:
            dx = (-6 if is_left else 6)
            arrow = FancyArrowPatch(
                (0, d), (dx, d), arrowstyle="->,head_width=6,head_length=4",
                color="#ffee00", linewidth=2.5, zorder=6,
            )
            ax.add_patch(arrow)
            ax.plot([0], [d], "o", color="#ffee00", markersize=6, zorder=6)

    ax.set_xlim(-lim, lim)
    ax.set_ylim(-5, lim * 2)
    ax.set_aspect("equal")
    ax.invert_xaxis()  # ego-frame +y is left → flip so left turns appear on screen-left

    ax.set_facecolor("#2a2a2a")
    ax.tick_params(colors="#999", labelsize=7)
    for spine in ax.spines.values():
        spine.set_color("#555")

    # --- Legend ---
    leg = ax.legend(loc="upper right", fontsize=7, framealpha=0.7, labelcolor="white",
                    facecolor="#333", edgecolor="#666")
    leg.set_zorder(10)

    # --- V2X banner (top of BEV) ---
    if v2x_text:
        ax.text(
            0.5, 0.97, f"[V2X] {v2x_text}",
            transform=ax.transAxes, ha="center", va="top",
            fontsize=9, color="#00d2ff", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#111", edgecolor="#00d2ff", alpha=0.85),
            zorder=10,
        )

    # --- Compass + Scale bar ---
    ax.text(0.06, 0.95, "↑N", transform=ax.transAxes, fontsize=10, color="white",
            ha="center", va="top", fontweight="bold", zorder=10)
    # Scale bar (10m)
    bar_y = -2
    bar_x_start = lim * 0.3
    ax.plot([bar_x_start, bar_x_start + 10], [bar_y, bar_y], color="white", linewidth=2, zorder=6)
    ax.text(bar_x_start + 5, bar_y - 1.5, "10m", color="white", fontsize=7, ha="center", zorder=6)

    ax.set_title("BEV Map View — forward ↑", color="#ddd", fontsize=9)
    fig.patch.set_facecolor("#222")
    fig.tight_layout(pad=0.3)
    fig.canvas.draw()
    img = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()
    plt.close(fig)
    return img


def wrap_text(text, max_chars=70):
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
    return lines


def composite_frame(camera_rgb, bev_rgb, scenario_title, nav_lines):
    """Camera + BEV side-by-side + caption with scenario + per-condition CoT."""
    cam_img = Image.fromarray(camera_rgb)
    bev_img = Image.fromarray(bev_rgb)

    # Force fixed canvas size so all frames have identical shape (mediapy requirement).
    # Camera resized to fixed 800x480 (16:9.6); BEV is 480x480; caption strip 320 high.
    CAM_W, CAM_H = 800, 480
    cam_img = cam_img.resize((CAM_W, CAM_H))
    if bev_img.size != (480, 480):
        bev_img = bev_img.resize((480, 480))

    canvas_w = CAM_W + 480 + 24
    canvas_h = CAM_H + 320
    canvas = Image.new("RGB", (canvas_w, canvas_h), (10, 14, 20))
    canvas.paste(cam_img, (8, 8))
    canvas.paste(bev_img, (CAM_W + 16, 8))

    draw = ImageDraw.Draw(canvas)
    title_font = load_font(22)
    body_font = load_font(16)
    small_font = load_font(14)

    y = CAM_H + 18
    draw.text((12, y), scenario_title, fill=(255, 255, 255), font=title_font)
    y += 32

    for label, color, text in nav_lines:
        rgb = tuple(int(color.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
        draw.text((12, y), label, fill=rgb, font=body_font)
        y += 22
        for line in wrap_text(text, max_chars=int(canvas_w / 9)):
            draw.text((28, y), line, fill=(220, 220, 220), font=small_font)
            y += 18
        y += 4

    return np.array(canvas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples-json", type=str, default="nav_demo_samples.json")
    ap.add_argument(
        "--indices",
        type=str,
        default="0,3,7,19",
        help="Comma-separated indices into samples JSON",
    )
    ap.add_argument("--seconds-per-scenario", type=float, default=3.5)
    ap.add_argument("--fps", type=int, default=2)
    ap.add_argument("--out", type=str, default="alpamayo_nav_demo.mp4")
    args = ap.parse_args()

    notebook_dir = Path(__file__).parent
    with open(notebook_dir / args.samples_json) as f:
        samples = json.load(f)
    indices = [int(i) for i in args.indices.split(",")]
    selected = [samples[i] for i in indices]

    print(f"Selected {len(selected)} scenarios:")
    for s in selected:
        print(f"  clip={s['clip_id'][:8]} t0_us={s['t0_relative']:>10d} | {s['nav_text']}")

    print("\nLoading model...")
    model = Alpamayo1_5.from_pretrained(
        "nvidia/Alpamayo-1.5-10B", dtype=torch.bfloat16
    ).to("cuda")
    processor = helper.get_processor(model.tokenizer)
    print("Model ready.\n")

    video_frames = []
    for k, s in enumerate(selected):
        clip_id = s["clip_id"]
        t0 = s["t0_relative"]
        nav_text = s["nav_text"]
        try:
            counter_text = nav_utils.swap_direction(nav_text)
        except Exception:
            counter_text = nav_text.replace("right", "RIGHT").replace("left", "right").replace("RIGHT", "left")

        print(f"\n[{k + 1}/{len(selected)}] {clip_id[:8]} t0={t0} '{nav_text}'")
        try:
            data = load_physical_aiavdataset(clip_id, t0_us=t0)
        except Exception as e:
            print(f"  load failed: {e}")
            continue

        print(f"  (a) with nav: {nav_text}")
        pred_with, cot_with = run_one_condition(model, processor, data, nav_text)
        print(f"      CoT: {cot_with[:120]}")
        print(f"  (b) no nav")
        pred_no, cot_no = run_one_condition(model, processor, data, None)
        print(f"      CoT: {cot_no[:120]}")
        print(f"  (c) counterfactual: {counter_text}")
        pred_cf, cot_cf = run_one_condition(model, processor, data, counter_text)
        print(f"      CoT: {cot_cf[:120]}")

        cam = (
            data["image_frames"][FRONT_WIDE_CAM_INDEX_IN_BATCH, -1]
            .permute(1, 2, 0)
            .cpu()
            .numpy()
        )
        if cam.dtype != np.uint8:
            cam = (cam.clip(0, 1) * 255).astype(np.uint8) if cam.max() <= 1.5 else cam.astype(np.uint8)

        gt_xy = data["ego_future_xyz"].cpu().numpy()[0, 0, :, :2].T
        bev = render_bev(
            {
                f"with: {nav_text}": (pred_with, COLORS["with_nav"]),
                "no nav": (pred_no, COLORS["no_nav"]),
                f"cf: {counter_text}": (pred_cf, COLORS["counterfactual"]),
            },
            gt_xy,
        )

        title = f"Scenario {k + 1}/{len(selected)}: {s['nav_maneuver']} (dist={s['distance_m']:.1f}m)"
        nav_lines = [
            (f"WITH NAV ({nav_text}):", COLORS["with_nav"], cot_with),
            ("NO NAV (unconditioned):", COLORS["no_nav"], cot_no),
            (f"COUNTERFACTUAL ({counter_text}):", COLORS["counterfactual"], cot_cf),
        ]
        frame = composite_frame(cam, bev, title, nav_lines)

        n_repeat = max(1, int(round(args.seconds_per_scenario * args.fps)))
        video_frames.extend([frame] * n_repeat)

    if not video_frames:
        raise SystemExit("No frames produced.")

    out_path = notebook_dir / args.out
    print(f"\nWriting {len(video_frames)} frames to {out_path} @ {args.fps} fps")
    mp.write_video(str(out_path), video_frames, fps=args.fps)
    print("Done.")


if __name__ == "__main__":
    main()
