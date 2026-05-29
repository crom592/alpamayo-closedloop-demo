"""V2X Q&A — California-data inference for the KATECH demo.

Mirrors the original ARM POC's central feature ("change the V2X message ->
the model changes its judgment"). Runs Alpamayo 1.5 directly on the
PhysicalAI-AV parquet samples; no closed-loop simulator involved.

Lazy-loads the model on first call (one-time ~5-7 min + 22 GB VRAM on A40).
"""

from __future__ import annotations

import io
import json
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Korean glyph support for BEV legends/banners.
# Mirror make_video_nav.py:19-29 (the open-loop video pipeline already has it).
from matplotlib import font_manager as _fm
for _f in (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
):
    try:
        _fm.fontManager.addfont(_f)
    except Exception:
        pass
# NotoSansCJK-Regular.ttc is a TrueType Collection; matplotlib only reads the
# first face inside it, which registers under the JP name. The CJK Sans font
# covers Hangul/Kana/Hanzi alike, so the "JP" label still renders Korean.
plt.rcParams["font.family"] = ["Noto Sans CJK JP", "NanumGothic", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

import numpy as np
import torch

# Re-use the existing make_video_nav helpers in the overlay package.
NOTEBOOK_DIR = Path("/home/kadap/alpamayo-closedloop-demo/overlay/alpamayo1.5/notebooks")
sys.path.insert(0, str(NOTEBOOK_DIR))

# nav_demo_samples lives next to the submodule checkout, not the overlay.
SAMPLES_PATH = Path(
    "/home/kadap/alpamayo-closedloop-demo/alpamayo1.5/notebooks/nav_demo_samples.json"
)

from alpamayo1_5 import helper, nav_utils  # noqa: E402
from alpamayo1_5.load_physical_aiavdataset import load_physical_aiavdataset  # noqa: E402
from alpamayo1_5.models.alpamayo1_5 import Alpamayo1_5  # noqa: E402

FRONT_WIDE_CAM_INDEX_IN_BATCH = 1

# Color scheme — same as original POC for visual continuity.
COLORS = {
    "with_nav": "#00d2ff",
    "no_nav": "#ffaa00",
    "counterfactual": "#ff3366",
    "gt": "#1c1e21",
}

# Model singleton + load-state machine.
_MODEL = None
_PROCESSOR = None
_LOAD_LOCK = threading.Lock()
_LOAD_STATE = {"state": "idle", "msg": "not loaded"}  # idle | loading | ready | error


def categorize(s: dict) -> str:
    d = s["distance_m"]
    if "LEFT" in s["nav_maneuver"]:
        direction = "좌회전"
    elif "RIGHT" in s["nav_maneuver"]:
        direction = "우회전"
    else:
        direction = "직진"
    bucket = "근거리" if d < 15 else "중거리" if d < 50 else "원거리"
    return f"{bucket} {direction}"


def load_samples() -> list[dict]:
    if not SAMPLES_PATH.exists():
        return []
    with SAMPLES_PATH.open() as f:
        raw = json.load(f)
    for i, s in enumerate(raw):
        s["_idx"] = i
        s["_category"] = categorize(s)
    return raw


def model_status() -> dict:
    return dict(_LOAD_STATE)


def ensure_model() -> tuple[object, object]:
    """Load (or get cached) Alpamayo 1.5. Blocks for ~5-7 min on first call."""
    global _MODEL, _PROCESSOR
    with _LOAD_LOCK:
        if _MODEL is not None:
            return _MODEL, _PROCESSOR
        _LOAD_STATE.update({"state": "loading", "msg": "loading checkpoint..."})
        try:
            model = Alpamayo1_5.from_pretrained(
                "nvidia/Alpamayo-1.5-10B",
                dtype=torch.bfloat16,
                attn_implementation="eager",
            ).to("cuda")
            processor = helper.get_processor(model.tokenizer)
            _MODEL = model
            _PROCESSOR = processor
            _LOAD_STATE.update({"state": "ready", "msg": "model ready"})
        except Exception as e:  # noqa: BLE001
            _LOAD_STATE.update(
                {"state": "error", "msg": f"{e.__class__.__name__}: {e}"}
            )
            raise
    return _MODEL, _PROCESSOR


def run_one_condition(data, nav_text: str | None) -> tuple[np.ndarray, str]:
    """One forward pass. nav_text=None → V2X-미수신 baseline."""
    model, processor = ensure_model()
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


def run_live_vqa(scenario_idx: int, question_en: str) -> str:
    """Live VQA answer for a free-form question against a scenario's frames.

    Uses helper.create_vqa_message + model.generate_text. Loads the data
    fresh each call (lightweight). Returns the model's answer string.
    """
    samples = load_samples()
    if not (0 <= scenario_idx < len(samples)):
        raise ValueError(f"scenario_idx {scenario_idx} out of range")
    s = samples[scenario_idx]
    question = (question_en or "").strip()
    if not question:
        raise ValueError("question must be non-empty")

    data = load_physical_aiavdataset(s["clip_id"], t0_us=s["t0_relative"])
    model, processor = ensure_model()
    messages = helper.create_vqa_message(
        data["image_frames"].flatten(0, 1),
        question=question,
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
    model_inputs = helper.to_device({"tokenized_data": inputs}, "cuda")
    import random as _r
    torch.cuda.manual_seed_all(_r.randint(0, 2**31 - 1))
    with torch.autocast("cuda", dtype=torch.bfloat16):
        extra = model.generate_text(
            data=model_inputs,
            top_p=0.98,
            temperature=0.6,
            num_samples=1,
            max_generation_length=96,
        )
    raw = extra["answer"][0]
    # Alpamayo wraps every answer in a list, e.g. ['some text'] or
    # ['[0.306, 0.491, 0.325, 0.524]'] (the bbox is itself a string).
    # Unwrap until we have a plain string.
    while isinstance(raw, (list, tuple)) and len(raw) == 1:
        raw = raw[0]
    if not isinstance(raw, str):
        try:
            raw = " ".join(str(x) for x in raw)
        except TypeError:
            raw = str(raw)
    text = raw.strip()

    # Detect grounding output (1 or more bboxes). Each bbox is "[x1, y1, x2, y2]"
    # of 4 normalized floats in 0..1; multiple bboxes are comma-separated.
    import re as _re
    bbox_re = r"\[\s*[\d.]+(?:\s*,\s*[\d.]+){3}\s*\]"
    if _re.fullmatch(rf"{bbox_re}(?:\s*,\s*{bbox_re})*", text):
        bboxes: list[tuple[float, float, float, float]] = []
        for m in _re.finditer(bbox_re, text):
            nums = [float(n) for n in _re.findall(r"[\d.]+", m.group())]
            if len(nums) == 4 and all(0.0 <= n <= 1.0 for n in nums):
                bboxes.append(tuple(nums))  # type: ignore[arg-type]
        if bboxes:
            lines = [
                f"  · 영역 {i + 1}: ({b[0]:.3f}, {b[1]:.3f}) → ({b[2]:.3f}, {b[3]:.3f})"
                for i, b in enumerate(bboxes)
            ]
            return (
                f"[객체 감지] {len(bboxes)}개 정규화 bbox 영역 (좌표 0~1):\n"
                + "\n".join(lines)
                + "\n자연어 묘사를 원하면 도메인이 좁은 질문을 쓰세요 "
                "(예: \"Describe the road and weather.\", "
                "\"Describe the lighting and traffic.\")."
            )
    return text


def compute_metrics(pred_xy: np.ndarray, gt_xy: np.ndarray) -> dict:
    T = min(pred_xy.shape[1], gt_xy.shape[1])
    p = pred_xy[:, :T]
    g = gt_xy[:, :T]
    diff = np.linalg.norm(p - g, axis=0)
    ade = float(diff.mean())
    fde = float(diff[-1])
    lateral_dev = float(np.abs(p[1] - g[1]).max())
    head_err = 0.0
    if T >= 2:
        def heading(xy: np.ndarray) -> float:
            dx = xy[0, -1] - xy[0, -2]
            dy = xy[1, -1] - xy[1, -2]
            return float(np.degrees(np.arctan2(dy, dx)))

        head_err = float(abs((heading(p) - heading(g) + 180) % 360 - 180))
    return {
        "ADE": ade,
        "FDE": fde,
        "max_lat_dev": lateral_dev,
        "heading_err_deg": head_err,
    }


def fetch_camera_rgb(data) -> np.ndarray:
    cam = (
        data["image_frames"][FRONT_WIDE_CAM_INDEX_IN_BATCH, -1]
        .permute(1, 2, 0)
        .cpu()
        .numpy()
    )
    if cam.dtype != np.uint8:
        cam = (cam.clip(0, 1) * 255).astype(np.uint8) if cam.max() <= 1.5 else cam.astype(np.uint8)
    return cam


def render_bev_png(pred_dict: dict, gt_xy: np.ndarray, v2x_text: str | None = None) -> bytes:
    """Light BEV: GT + predicted trajectories. Returns PNG bytes."""
    fig, ax = plt.subplots(figsize=(5, 5), dpi=110)
    all_pts = [gt_xy] + [v[0] for v in pred_dict.values()]
    flat = np.concatenate(all_pts, axis=1)
    lim = max(20.0, float(np.abs(flat).max()) * 1.15)
    # road surface
    road_hw = min(lim * 0.45, 8.0)
    ax.axvspan(-road_hw, road_hw, color="#dde2e8", zorder=0)
    # dashes
    for y in np.arange(-lim, lim * 2, 3.0):
        ax.plot([0, 0], [y, y + 1.5], color="#999", linewidth=0.6, zorder=1)

    ax.plot(gt_xy[1], gt_xy[0], "-", color=COLORS["gt"], linewidth=2.5, label="GT (정답)", zorder=3)
    for label, (xy, color) in pred_dict.items():
        ax.plot(xy[1], xy[0], "o-", color=color, markersize=3, linewidth=2, label=label, zorder=4)
    ax.scatter([0], [0], c="#c0392b", s=120, zorder=5, marker="^", edgecolors="white", linewidths=1)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-5, lim * 2)
    ax.set_aspect("equal")
    ax.set_xlabel("lateral y (m)")
    ax.set_ylabel("forward x (m)")
    ax.legend(loc="upper left", fontsize=8, framealpha=0.85)
    if v2x_text:
        ax.text(0, lim * 1.95, f"🛰  {v2x_text}", ha="center", va="top", fontsize=9,
                bbox=dict(facecolor="#003366", edgecolor="none", pad=4), color="white")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def render_camera_png(cam_rgb: np.ndarray) -> bytes:
    """Encode a camera RGB array to PNG bytes."""
    from PIL import Image

    img = Image.fromarray(cam_rgb)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@dataclass
class VqaResult:
    bev_png: bytes
    camera_png: bytes
    scenario: dict
    v2x_text: str
    rows: list[dict]  # {condition, cot, metrics}


def run_three_conditions(
    scenario_idx: int,
    v2x_text: str | None,
    do_baseline: bool,
    do_counterfactual: bool,
) -> VqaResult:
    samples = load_samples()
    s = samples[scenario_idx]
    v2x_text = (v2x_text or "").strip() or s["nav_text"]

    data = load_physical_aiavdataset(s["clip_id"], t0_us=s["t0_relative"])
    gt_xy = data["ego_future_xyz"].cpu().numpy()[0, 0, :, :2].T

    pred_dict: dict = {}
    rows: list[dict] = []

    pred, cot = run_one_condition(data, v2x_text)
    pred_dict[f"V2X: {v2x_text}"] = (pred, COLORS["with_nav"])
    rows.append({"condition": f"V2X 연계: {v2x_text}", "cot": cot, "metrics": compute_metrics(pred, gt_xy)})

    if do_baseline:
        pred_b, cot_b = run_one_condition(data, None)
        pred_dict["차량 단독 (V2X 미수신)"] = (pred_b, COLORS["no_nav"])
        rows.append({"condition": "차량 단독 baseline", "cot": cot_b, "metrics": compute_metrics(pred_b, gt_xy)})

    if do_counterfactual:
        try:
            cf_text = nav_utils.swap_direction(v2x_text)
        except Exception:  # noqa: BLE001
            cf_text = v2x_text.replace("left", "RIGHT").replace("right", "left").replace("RIGHT", "right")
        pred_c, cot_c = run_one_condition(data, cf_text)
        pred_dict[f"반사실: {cf_text}"] = (pred_c, COLORS["counterfactual"])
        rows.append({"condition": f"반사실: {cf_text}", "cot": cot_c, "metrics": compute_metrics(pred_c, gt_xy)})

    bev = render_bev_png(pred_dict, gt_xy, v2x_text=v2x_text)
    cam = render_camera_png(fetch_camera_rgb(data))
    return VqaResult(
        bev_png=bev,
        camera_png=cam,
        scenario=s,
        v2x_text=v2x_text,
        rows=rows,
    )
