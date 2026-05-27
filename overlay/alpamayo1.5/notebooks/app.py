"""KATECH V2X-Linked Autonomous Driving Evaluation POC.

Researcher-facing Gradio console for evaluating Alpamayo 1.5 trajectory
predictions under (a) vehicle-only perception and (b) vehicle + V2X /
infrastructure message conditioning.

Run inside the alpamayo-poc container:
    PYTHONPATH=/workspace/alpamayo1.5/src:. python app.py --host 0.0.0.0 --port 7860
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import time
from pathlib import Path

import gradio as gr
import matplotlib

matplotlib.use("Agg")
import mediapy as mp
import numpy as np
import torch

from alpamayo1_5 import helper, nav_utils
from alpamayo1_5.load_physical_aiavdataset import load_physical_aiavdataset
from alpamayo1_5.models.alpamayo1_5 import Alpamayo1_5

from adapters import V2XAdapter, VehicleDataAdapter
from make_video_nav import (
    COLORS,
    FRONT_WIDE_CAM_INDEX_IN_BATCH,
    composite_frame,
    render_bev,
    run_one_condition,
)

NOTEBOOK_DIR = Path(__file__).parent
SAMPLES_PATH = NOTEBOOK_DIR / "nav_demo_samples.json"
OUT_DIR = NOTEBOOK_DIR / "ui_outputs"
OUT_DIR.mkdir(exist_ok=True)

VEHICLE_ADAPTER = VehicleDataAdapter()
V2X_ADAPTER = V2XAdapter()

# In-memory tensor cache: key = (clip_id, num_cams_str) → loaded data dict.
# Avoids the ~8s parquet decode penalty when the user issues multiple queries
# against the same scenario (typical validation workflow).
_DATA_CACHE: dict = {}


def cached_load(clip_id, t0_us, cam_features=None, cam_key="default4"):
    """Memoized loader. cam_key disambiguates 1cam/2cam/4cam variants."""
    key = (clip_id, t0_us, cam_key)
    if key in _DATA_CACHE:
        return _DATA_CACHE[key]
    if cam_features is None:
        data = load_physical_aiavdataset(clip_id, t0_us=t0_us)
    else:
        import physical_ai_av
        avdi = physical_ai_av.PhysicalAIAVDatasetInterface()
        data = load_physical_aiavdataset(
            clip_id, avdi=avdi, t0_us=t0_us, camera_features=cam_features
        )
    _DATA_CACHE[key] = data
    return data

_MODEL = None
_PROCESSOR = None
_SAMPLES: list[dict] = []

# Live interactive demo state — read every frame by the playback generator,
# updated by the V2X textbox / preset-button click handlers.
LIVE_STATE = {
    "v2x_text": "",
    "stop": False,
    "running": False,
}


# ---------- Model loading ----------

def get_model():
    global _MODEL, _PROCESSOR
    if _MODEL is None:
        print("Loading Alpamayo-1.5-10B (one-time)...")
        _MODEL = Alpamayo1_5.from_pretrained(
            "nvidia/Alpamayo-1.5-10B", dtype=torch.bfloat16
        ).to("cuda")
        _PROCESSOR = helper.get_processor(_MODEL.tokenizer)
        print("Model ready.")
    return _MODEL, _PROCESSOR


# ---------- Sample catalog with Korean categories ----------

def categorize(s: dict) -> str:
    d = s["distance_m"]
    direction = "좌회전" if "LEFT" in s["nav_maneuver"] else "우회전" if "RIGHT" in s["nav_maneuver"] else "직진"
    if d < 15:
        bucket = "근거리"
    elif d < 50:
        bucket = "중거리"
    else:
        bucket = "원거리"
    return f"{bucket} {direction}"


def load_samples():
    global _SAMPLES
    if not _SAMPLES:
        with open(SAMPLES_PATH) as f:
            raw = json.load(f)
        for i, s in enumerate(raw):
            s["_idx"] = i
            s["_category"] = categorize(s)
        _SAMPLES = raw
    return _SAMPLES


def sample_label(s: dict) -> str:
    return f"[{s['_idx']:02d}] {s['_category']:<10} | d={s['distance_m']:>5.1f}m | clip={s['clip_id'][:8]} | {s['nav_text']}"


def list_sample_choices():
    return [sample_label(s) for s in load_samples()]


def parse_choice_idx(choice: str) -> int:
    return int(choice[1:3])


# ---------- Metrics ----------

def compute_metrics(pred_xy: np.ndarray, gt_xy: np.ndarray) -> dict:
    """pred_xy / gt_xy: shape (2, T) — row 0 = forward(x), row 1 = lateral(y)."""
    T = min(pred_xy.shape[1], gt_xy.shape[1])
    p = pred_xy[:, :T]
    g = gt_xy[:, :T]
    diff = np.linalg.norm(p - g, axis=0)
    ade = float(diff.mean())
    fde = float(diff[-1])
    lateral_dev = float(np.abs(p[1] - g[1]).max())
    # Heading at end of horizon, from last segment
    if T >= 2:
        def heading(xy):
            dx = xy[0, -1] - xy[0, -2]
            dy = xy[1, -1] - xy[1, -2]
            return np.degrees(np.arctan2(dy, dx))
        head_err = float(abs((heading(p) - heading(g) + 180) % 360 - 180))
    else:
        head_err = 0.0
    return {"ADE (m)": ade, "FDE (m)": fde, "Max lateral dev (m)": lateral_dev, "Heading err (°)": head_err}


def metrics_table(rows: list[tuple[str, dict]]) -> str:
    if not rows:
        return ""
    keys = list(rows[0][1].keys())
    header = "| 조건 | " + " | ".join(keys) + " |"
    sep = "|" + "---|" * (len(keys) + 1)
    body = []
    for name, m in rows:
        body.append("| " + name + " | " + " | ".join(f"{m[k]:.2f}" for k in keys) + " |")
    return "\n".join([header, sep] + body)


# ---------- Inference helpers ----------

def fetch_camera_rgb(payload):
    cam = (
        payload["image_frames"][FRONT_WIDE_CAM_INDEX_IN_BATCH, -1]
        .permute(1, 2, 0)
        .cpu()
        .numpy()
    )
    if cam.dtype != np.uint8:
        cam = (cam.clip(0, 1) * 255).astype(np.uint8) if cam.max() <= 1.5 else cam.astype(np.uint8)
    return cam


def preview_clip(choice: str):
    if not choice:
        return None, "시나리오를 선택하세요."
    s = load_samples()[parse_choice_idx(choice)]
    try:
        obs = VEHICLE_ADAPTER.fetch(s["clip_id"], s["t0_relative"])
    except Exception as e:
        return None, f"[차량 어댑터] 로드 실패: {e}"
    cam = fetch_camera_rgb(obs.payload)
    info = (
        f"카테고리: {s['_category']}\n"
        f"clip_id: {s['clip_id']}\n"
        f"t0_relative_us: {s['t0_relative']}\n"
        f"기동: {s['nav_maneuver']}  |  거리: {s['distance_m']:.1f}m\n"
        f"기준 V2X 메시지: {s['nav_text']}\n"
        f"기준 의사결정 (CoT): {s.get('cot', '')}"
    )
    return cam, info


def run_inference(choice, v2x_text, run_baseline, run_counterfactual, history):
    if not choice:
        return None, None, "시나리오를 선택하세요.", "", history, ""
    s = load_samples()[parse_choice_idx(choice)]
    v2x_text = (v2x_text or "").strip() or s["nav_text"]
    v2x_msg = V2X_ADAPTER.from_text(v2x_text, source="operator")

    try:
        obs = VEHICLE_ADAPTER.fetch(s["clip_id"], s["t0_relative"])
    except Exception as e:
        return None, None, f"[차량 어댑터] 로드 실패: {e}", "", history, ""
    data = obs.payload

    model, processor = get_model()
    log = [f"### 시나리오: {s['_category']}  (거리 {s['distance_m']:.1f}m, clip `{s['clip_id'][:8]}`)"]

    pred_dict: dict = {}
    metric_rows: list[tuple[str, dict]] = []
    gt_xy = data["ego_future_xyz"].cpu().numpy()[0, 0, :, :2].T

    # (1) V2X-conditioned
    pred_v2x, cot_v2x = run_one_condition(model, processor, data, v2x_msg.text)
    pred_dict[f"V2X 연계: {v2x_msg.text}"] = (pred_v2x, COLORS["with_nav"])
    metric_rows.append(("V2X 연계", compute_metrics(pred_v2x, gt_xy)))
    log += [f"\n**[V2X 연계]** `{v2x_msg.source}` → *{v2x_msg.text}*", cot_v2x]

    cot_base = ""
    if run_baseline:
        pred_base, cot_base = run_one_condition(model, processor, data, None)
        pred_dict["차량 단독"] = (pred_base, COLORS["no_nav"])
        metric_rows.append(("차량 단독 baseline", compute_metrics(pred_base, gt_xy)))
        log += ["\n**[차량 단독 — V2X 미수신]**", cot_base]

    cot_cf = ""
    counter_text = ""
    if run_counterfactual:
        try:
            counter_text = nav_utils.swap_direction(v2x_msg.text)
        except Exception:
            counter_text = v2x_msg.text.replace("left", "RIGHT").replace("right", "left").replace("RIGHT", "right")
        pred_cf, cot_cf = run_one_condition(model, processor, data, counter_text)
        pred_dict[f"반사실: {counter_text}"] = (pred_cf, COLORS["counterfactual"])
        metric_rows.append(("반사실 검증", compute_metrics(pred_cf, gt_xy)))
        log += [f"\n**[반사실 검증]** *{counter_text}*", cot_cf]

    # GT row for reference
    metric_rows.insert(0, ("GT (정답 궤적)", {"ADE (m)": 0.0, "FDE (m)": 0.0, "Max lateral dev (m)": 0.0, "Heading err (°)": 0.0}))

    cam = fetch_camera_rgb(data)
    bev = render_bev(pred_dict, gt_xy)

    history = (history or []) + [
        {
            "ts": dt.datetime.now().strftime("%H:%M:%S"),
            "category": s["_category"],
            "clip": s["clip_id"][:8],
            "v2x": v2x_msg.text,
            "cot_v2x": cot_v2x,
            "cot_base": cot_base,
            "cot_cf": cot_cf,
            "metrics": metric_rows,
        }
    ]
    return cam, bev, "\n".join(log), metrics_table(metric_rows), history, ""


# ---------- Demo run (time-rolling video) ----------

# (sample_idx, n_frames, label_for_summary)
# Headliner first: scenario 0 (11m left turn) gets longer rollout.
DEMO_PLAN = [
    (0, 12, "headliner"),
    (3, 6, ""),
    (7, 6, ""),
    (19, 6, ""),
]
STEP_US = 300_000  # 0.3 s between rolled frames
FPS = 4


def _render_one(s, t0_us, model, processor, k_global, k_total):
    """Run 3 conditions at one t0 and return (frame_rgb, metrics_v2x, metrics_base) or None."""
    try:
        obs = VEHICLE_ADAPTER.fetch(s["clip_id"], t0_us)
    except Exception as e:
        print(f"  load failed at t0={t0_us}: {e}")
        return None
    data = obs.payload
    v2x_text = s["nav_text"]
    try:
        counter_text = nav_utils.swap_direction(v2x_text)
    except Exception:
        counter_text = v2x_text

    pred_v2x, cot_v2x = run_one_condition(model, processor, data, v2x_text)
    pred_base, cot_base = run_one_condition(model, processor, data, None)
    pred_cf, cot_cf = run_one_condition(model, processor, data, counter_text)

    gt_xy = data["ego_future_xyz"].cpu().numpy()[0, 0, :, :2].T
    m_v2x = compute_metrics(pred_v2x, gt_xy)
    m_base = compute_metrics(pred_base, gt_xy)
    delta_ade = m_base["ADE (m)"] - m_v2x["ADE (m)"]

    cam = fetch_camera_rgb(data)
    bev = render_bev(
        {
            f"V2X 연계: {v2x_text}": (pred_v2x, COLORS["with_nav"]),
            "차량 단독": (pred_base, COLORS["no_nav"]),
            f"반사실: {counter_text}": (pred_cf, COLORS["counterfactual"]),
        },
        gt_xy,
    )
    title = (
        f"[{k_global + 1}/{k_total}] {s['_category']} "
        f"(d={s['distance_m']:.1f}m)  ΔADE={delta_ade:+.2f}m  t={t0_us / 1e6:.1f}s"
    )
    nav_lines = [
        (f"V2X 연계 ({v2x_text}):", COLORS["with_nav"], cot_v2x),
        ("차량 단독 baseline:", COLORS["no_nav"], cot_base),
        (f"반사실 검증 ({counter_text}):", COLORS["counterfactual"], cot_cf),
    ]
    frame = composite_frame(cam, bev, title, nav_lines)
    return frame, m_v2x, m_base


def demo_run(progress=gr.Progress()):
    samples = load_samples()
    model, processor = get_model()

    plan = [(samples[i], n, tag) for (i, n, tag) in DEMO_PLAN if i < len(samples)]
    total_steps = sum(n for _, n, _ in plan)
    done = 0
    frames = []
    summary_rows = []

    for s, n_frames, tag in plan:
        # Center the rollout around s['t0_relative']: start (n//2) steps before, go n forward.
        start_us = max(0, s["t0_relative"] - (n_frames // 2) * STEP_US)
        per_scen_v2x_ades = []
        per_scen_base_ades = []
        for k in range(n_frames):
            t0 = start_us + k * STEP_US
            progress(done / total_steps, desc=f"{s['_category']}  frame {k + 1}/{n_frames}  (t={t0/1e6:.1f}s)")
            res = _render_one(s, t0, model, processor, done, total_steps)
            done += 1
            if res is None:
                continue
            frame, m_v2x, m_base = res
            frames.append(frame)
            per_scen_v2x_ades.append(m_v2x["ADE (m)"])
            per_scen_base_ades.append(m_base["ADE (m)"])

        if per_scen_v2x_ades:
            v2x_avg = float(np.mean(per_scen_v2x_ades))
            base_avg = float(np.mean(per_scen_base_ades))
            delta = base_avg - v2x_avg
            head_mark = " ⭐" if tag == "headliner" else ""
            summary_rows.append(
                f"- **{s['_category']}**{head_mark} (d={s['distance_m']:.1f}m, "
                f"{len(per_scen_v2x_ades)}프레임 평균): "
                f"V2X ADE={v2x_avg:.2f}m  vs  차량단독 ADE={base_avg:.2f}m  (Δ={delta:+.2f}m)"
            )

    if not frames:
        return None, "프레임을 생성하지 못했습니다."
    out = OUT_DIR / f"demo_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
    mp.write_video(str(out), frames, fps=FPS)
    return (
        str(out),
        f"## 시연 결과 요약\n"
        f"- 총 {len(frames)} 프레임 @ {FPS}fps  ({len(frames) / FPS:.1f}초)\n"
        f"- 시간 진행 모드 (시나리오당 t0를 0.3s씩 전진)\n\n"
        + "\n".join(summary_rows),
    )


# ---------- Fast inference (interactive mode) ----------

def run_one_condition_fast(model, processor, data, nav_text, max_gen=64):
    """Like run_one_condition but with shorter CoT generation for ~2x speedup."""
    frames_t = data["image_frames"].flatten(0, 1)
    if nav_text is None:
        messages = helper.create_message(frames_t, camera_indices=data["camera_indices"])
    else:
        messages = helper.create_message(
            frames_t, camera_indices=data["camera_indices"], nav_text=nav_text
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
            max_generation_length=max_gen,
            return_extra=True,
        )
    cot = extra["cot"][0] if extra.get("cot") else ""
    if not isinstance(cot, str):
        try:
            cot = " ".join(str(x) for x in cot)
        except TypeError:
            cot = str(cot)
    pred_xy = pred_xyz.cpu().numpy()[0, 0, 0, :, :2].T
    return pred_xy, cot


# ---------- Interactive live playback ----------

V2X_PRESETS = [
    "Turn left in 30m",
    "Turn right in 30m",
    "Construction ahead, left lane closed",
    "Stop, pedestrian crossing",
    "Slow down, congestion ahead",
    "Yield to emergency vehicle",
]


def set_live_v2x(text):
    LIVE_STATE["v2x_text"] = (text or "").strip()
    return f"🛰️  Active V2X: **{LIVE_STATE['v2x_text'] or '(시나리오 기본값)'}**"


def stop_live():
    LIVE_STATE["stop"] = True
    return "⏹  중지 요청됨"


def play_live(choice, n_frames, step_seconds):
    """Generator: streams frames live; reads LIVE_STATE['v2x_text'] each frame."""
    if not choice:
        yield None, None, "시나리오를 선택하세요.", "", ""
        return
    if LIVE_STATE["running"]:
        yield None, None, "이미 재생 중입니다. 먼저 중지하세요.", "", ""
        return

    s = load_samples()[parse_choice_idx(choice)]
    LIVE_STATE["stop"] = False
    LIVE_STATE["running"] = True

    try:
        model, processor = get_model()
        step_us = int(step_seconds * 1_000_000)
        n_frames = int(n_frames)
        # Center the rollout around the labeled t0
        start_us = max(0, s["t0_relative"] - (n_frames // 3) * step_us)

        for k in range(n_frames):
            if LIVE_STATE["stop"]:
                break
            t0 = start_us + k * step_us
            try:
                obs = VEHICLE_ADAPTER.fetch(s["clip_id"], t0)
            except Exception as e:
                yield None, None, f"frame {k + 1}: 로드 실패 — {e}", "", ""
                continue
            data = obs.payload

            v2x_text = LIVE_STATE["v2x_text"] or s["nav_text"]
            pred_v2x, cot_v2x = run_one_condition_fast(model, processor, data, v2x_text)
            pred_base, cot_base = run_one_condition_fast(model, processor, data, None)

            gt_xy = data["ego_future_xyz"].cpu().numpy()[0, 0, :, :2].T
            cam = fetch_camera_rgb(data)
            bev = render_bev(
                {
                    f"V2X: {v2x_text}": (pred_v2x, COLORS["with_nav"]),
                    "차량 단독": (pred_base, COLORS["no_nav"]),
                },
                gt_xy,
            )
            m_v2x = compute_metrics(pred_v2x, gt_xy)
            m_base = compute_metrics(pred_base, gt_xy)
            delta = m_base["ADE (m)"] - m_v2x["ADE (m)"]

            status = (
                f"▶ frame {k + 1}/{n_frames}  |  t={t0 / 1e6:.1f}s  |  "
                f"🛰️ V2X: **{v2x_text}**  |  ΔADE={delta:+.2f}m"
            )
            cot_md = (
                f"**[V2X 연계]** {cot_v2x}\n\n"
                f"**[차량 단독]** {cot_base}"
            )
            metrics_md = metrics_table([("V2X 연계", m_v2x), ("차량 단독", m_base)])
            yield cam, bev, status, cot_md, metrics_md
    finally:
        LIVE_STATE["running"] = False
        LIVE_STATE["stop"] = False


# ---------- Cached interactive demo (prerendered) ----------

CACHE_DIR = NOTEBOOK_DIR / "demo_cache"


def load_cache_metadata():
    """Read metadata.json built by prerender_demo_cache.py."""
    meta_path = CACHE_DIR / "metadata.json"
    if not meta_path.exists():
        return None
    with open(meta_path) as f:
        return json.load(f)


def cache_scenario_choices():
    meta = load_cache_metadata()
    if not meta:
        return []
    return [
        f"[{s['scen_idx']:02d}] {s['category']:<10} | d={s['distance_m']:.1f}m | {s['default_nav_text']}"
        for s in meta["scenarios"]
    ]


def _scenario_by_choice(choice: str):
    meta = load_cache_metadata()
    if not meta or not choice:
        return None
    idx = int(choice[1:3])
    for s in meta["scenarios"]:
        if s["scen_idx"] == idx:
            return s
    return None


def _load_bev_array(rel_path: str):
    """Load BEV PNG as numpy array — Gradio Image refreshes reliably this way."""
    from PIL import Image as _PILImage
    return np.asarray(_PILImage.open(CACHE_DIR / rel_path).convert("RGB"))


def cache_load_scenario(choice: str):
    """When user picks a scenario: return camera mp4 path + default-preset BEV/CoT/metrics."""
    s = _scenario_by_choice(choice)
    if not s:
        return None, None, "캐시에 없는 시나리오입니다. prerender_demo_cache.py 를 먼저 실행하세요.", "", ""
    cam_mp4 = str(CACHE_DIR / s["camera_mp4"])
    default = next((p for p in s["presets"] if p["key"] == "default"), s["presets"][0])
    bev_arr = _load_bev_array(default["bev_path"])
    status = (
        f"🎬 시나리오 {s['scen_idx']}: **{s['category']}** (d={s['distance_m']:.1f}m)  \n"
        f"🛰️ 현재 V2X: **{default['display']}**  →  *{default['actual_nav']}*"
    )
    metrics_md = metrics_table([("현재 조건", default["metrics"])])
    cot_md = f"**Chain-of-Causation:** {default['cot']}"
    return cam_mp4, bev_arr, status, metrics_md, cot_md


def cache_apply_preset(choice: str, preset_key: str):
    """Switch BEV to a different preset of the same scenario (instant)."""
    s = _scenario_by_choice(choice)
    if not s:
        return None, "시나리오 미선택", "", ""
    p = next((p for p in s["presets"] if p["key"] == preset_key), None)
    if not p:
        return None, f"프리셋 {preset_key} 없음", "", ""
    bev_arr = _load_bev_array(p["bev_path"])
    status = (
        f"🎬 시나리오 {s['scen_idx']}: **{s['category']}** (d={s['distance_m']:.1f}m)  \n"
        f"🛰️ 현재 V2X: **{p['display']}**  →  *{p['actual_nav']}*"
    )
    metrics_md = metrics_table([("현재 조건", p["metrics"])])
    cot_md = f"**Chain-of-Causation:** {p['cot']}"
    return bev_arr, status, metrics_md, cot_md


# ---------- VQA cache ----------

def load_vqa(scen_idx: int):
    p = CACHE_DIR / f"scen_{scen_idx:02d}" / "vqa.json"
    if not p.exists():
        return []
    with open(p) as f:
        return json.load(f)


def vqa_load_scenario(choice: str):
    """Return camera mp4 + Q&A list for a scenario."""
    s = _scenario_by_choice(choice)
    if not s:
        return None, "시나리오 미선택", ""
    cam_mp4 = str(CACHE_DIR / s["camera_mp4"])
    qa = load_vqa(s["scen_idx"])
    if not qa:
        return cam_mp4, "VQA 캐시가 없습니다. prerender_extras.py 를 실행하세요.", ""
    md = "\n\n".join(
        f"**Q{i+1}. {q['q_kr']}**  \n_{q['q_en']}_  \n→ {q['answer']}"
        for i, q in enumerate(qa)
    )
    status = f"🎬 시나리오 {s['scen_idx']}: **{s['category']}** — {len(qa)}개 질문 캐시됨"
    return cam_mp4, status, md


def vqa_run_live(choice: str, question_en: str):
    """Run VQA live for an arbitrary user question (~15-20 sec). Generator
    yields a 'thinking' status immediately so the user gets visual feedback."""
    if not choice:
        yield "⚠️ 시나리오를 선택하세요."
        return
    if not question_en or not question_en.strip():
        yield "⚠️ 질문을 입력하세요."
        return
    s = _scenario_by_choice(choice)
    if not s:
        yield "⚠️ 시나리오 미선택"
        return

    cache_key = (s["clip_id"], None, "vqa1cam")
    cache_hit = cache_key in _DATA_CACHE
    yield f"⏳ **데이터 {'캐시 히트 ✓' if cache_hit else '로드 중 (~8초, 첫 호출)'}**"
    try:
        import physical_ai_av
        avdi = physical_ai_av.PhysicalAIAVDatasetInterface()
        if cache_hit:
            data = _DATA_CACHE[cache_key]
        else:
            data = load_physical_aiavdataset(
                s["clip_id"], avdi=avdi,
                camera_features=[avdi.features.CAMERA.CAMERA_FRONT_WIDE_120FOV],
            )
            _DATA_CACHE[cache_key] = data
    except Exception as e:
        yield f"❌ 데이터 로드 실패: {e}"
        return
    yield f"⏳ **모델 추론 중...** _(질문: {question_en})_"

    model, processor = get_model()
    messages = helper.create_vqa_message(
        data["image_frames"].flatten(0, 1),
        question=question_en,
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
            max_generation_length=96,  # shorter than nav (256) — VQA answers are concise
        )
    ans = extra["answer"][0]
    if not isinstance(ans, str):
        try:
            ans = " ".join(str(x) for x in ans)
        except TypeError:
            ans = str(ans)
    if not ans.strip():
        ans = (
            "_(모델이 빈 응답을 반환했습니다. Alpamayo의 VQA는 장면 묘사형 질문에 "
            "특화되어 있습니다. 행동 결정(\"...할 수 있나?\")은 ③ 탭의 nav conditioning을 "
            "사용하세요. 묘사형 질문 예: \"What do you see?\", \"Describe the road.\")_"
        )
    yield f"✅ **Q.** {question_en}\n\n**A.** {ans}"


# ---------- Camera-count cache ----------

def load_cam_meta(scen_idx: int):
    p = CACHE_DIR / f"scen_{scen_idx:02d}" / "cam_meta.json"
    if not p.exists():
        return []
    with open(p) as f:
        return json.load(f)


def cam_load_scenario(choice: str):
    s = _scenario_by_choice(choice)
    if not s:
        return None, None, None, "시나리오 미선택", ""
    cam_meta = load_cam_meta(s["scen_idx"])
    if not cam_meta:
        return None, None, None, "카메라 캐시가 없습니다. prerender_extras.py 를 실행하세요.", ""

    bevs = {c["key"]: c for c in cam_meta}
    def _img(key):
        if key not in bevs:
            return None
        path = CACHE_DIR / f"scen_{s['scen_idx']:02d}" / f"cam_{key}.png"
        if not path.exists():
            return None
        return np.asarray(Image.open(path).convert("RGB"))

    bev1 = _img("1cam")
    bev2 = _img("2cam")
    bev4 = _img("4cam")

    rows = [(c["label"], c["metrics"]) for c in cam_meta]
    metrics_md = metrics_table(rows)
    cot_md = "\n\n".join(f"**{c['label']}**  \nADE={c['metrics']['ADE (m)']:.2f}m  \nCoT: {c['cot']}" for c in cam_meta)
    status = f"🎬 시나리오 {s['scen_idx']}: **{s['category']}**  —  카메라 개수별 비교"
    return bev1, bev2, bev4, status, metrics_md + "\n\n" + cot_md


# ---------- UI ----------

# PIL import (deferred to avoid top-of-file noise)
from PIL import Image  # noqa: E402

CSS = """
#title-row { background: linear-gradient(90deg,#0a1628,#1a3d5c); padding: 18px 24px; border-radius: 8px; margin-bottom: 8px; }
#title-row h1 { color: #fff !important; margin: 0 0 4px 0; }
#title-row p { color: #8fb8d8 !important; margin: 0; }
"""


# ============================================================================
# Closed-loop (NRE) integration helpers — Tab ⑦.
#
# These talk to the Alpasim docker compose stack that's brought up by
# `scripts/run_closedloop.sh` on a GPU-capable x86 host (KADaP A40 48GB or
# similar). On the ARM POC node they will report "미감지", which is expected.
# ============================================================================

CLOSED_LOOP_SERVICES = ["controller-0", "driver-0", "physics-0", "trafficsim-0", "nre-0"]
CL_RUN_DIR = Path(
    os.environ.get("RUN_DIR", str(NOTEBOOK_DIR.parent.parent / "alpasim" / "run_dir"))
)


def _cl_run(cmd: list[str], timeout: int = 5) -> str:
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return out.stdout + out.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return f"<<error: {e}>>"


def _cl_resolve_container(substr: str) -> str | None:
    raw = _cl_run(["docker", "ps", "-a", "--format", "{{.Names}}"], timeout=5)
    for n in raw.splitlines():
        if substr in n:
            return n.strip()
    return None


def cl_service_health() -> str:
    raw = _cl_run(["docker", "ps", "-a", "--format", "{{json .}}"], timeout=8)
    services: dict[str, dict] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            info = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = info.get("Names", "")
        for svc in CLOSED_LOOP_SERVICES:
            if svc in name:
                services[svc] = {
                    "state": info.get("State", "?"),
                    "status": info.get("Status", "?"),
                }
                break
    rows = ["| 서비스 | 상태 | 상세 |", "|---|---|---|"]
    any_up = False
    for svc in CLOSED_LOOP_SERVICES:
        s = services.get(svc)
        if s is None:
            rows.append(f"| `{svc}` | ⚪ 미감지 | _컨테이너 없음_ |")
            continue
        state = s["state"]
        if state == "running" and "healthy" in s["status"]:
            emoji = "🟢"
            any_up = True
        elif state == "running":
            emoji = "🟡"
            any_up = True
        else:
            emoji = "🔴"
        rows.append(f"| `{svc}` | {emoji} {state} | {s['status']} |")
    header = "### Alpasim 서비스 상태\n"
    if not any_up:
        header += (
            "_컨테이너가 감지되지 않습니다._ closed-loop 환경에서 "
            "`bash scripts/run_closedloop.sh` 실행 후 새로고침하세요.\n\n"
        )
    return header + "\n".join(rows)


def cl_gpu_metrics() -> str:
    raw = _cl_run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
            "--format=csv,noheader,nounits",
        ],
        timeout=5,
    )
    rows = ["| GPU | util | VRAM (MiB) | 온도 |", "|---|---|---|---|"]
    found = False
    for line in raw.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 6:
            continue
        found = True
        try:
            mem_used = int(parts[3])
            mem_total = int(parts[4])
            mem_pct = 100 * mem_used / max(mem_total, 1)
        except ValueError:
            mem_used = mem_total = 0
            mem_pct = 0
        rows.append(
            f"| {parts[0]} `{parts[1][:20]}` | {parts[2]}% | {mem_used}/{mem_total} ({mem_pct:.0f}%) | {parts[5]}°C |"
        )
    if not found:
        return "### GPU\n_nvidia-smi 사용 불가 (ARM 노드이거나 NVIDIA Container Toolkit 미설정)_"
    return "### GPU\n" + "\n".join(rows)


def cl_container_log(substr: str, tail: int) -> str:
    name = _cl_resolve_container(substr)
    if not name:
        return f"_{substr} 컨테이너가 없습니다._"
    raw = _cl_run(["docker", "logs", "--tail", str(tail), name], timeout=10)
    if not raw.strip():
        return "_(empty)_"
    return f"```\n{raw[-6000:]}\n```"


def cl_latest_rollouts(n: int = 4) -> list[str | None]:
    rollouts_dir = CL_RUN_DIR / "rollouts"
    if not rollouts_dir.exists():
        return [None] * n
    mp4s = sorted(
        rollouts_dir.rglob("*.mp4"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    out: list[str | None] = [str(p) for p in mp4s[:n]]
    while len(out) < n:
        out.append(None)
    return out


def cl_panel_refresh():
    """One-shot refresh of all closed-loop panel components."""
    health = cl_service_health()
    gpu = cl_gpu_metrics()
    ctrl_log = cl_container_log("controller-0", tail=80)
    drv_log = cl_container_log("driver-0", tail=40)
    vids = cl_latest_rollouts(n=4)
    rollout_meta = (
        f"_RUN_DIR=`{CL_RUN_DIR}`  •  감지된 MP4: {sum(1 for v in vids if v)}개_"
    )
    return health, gpu, ctrl_log, drv_log, rollout_meta, vids[0], vids[1], vids[2], vids[3]


def build_ui():
    with gr.Blocks(title="KATECH V2X 자율주행 평가 POC") as demo:
        with gr.Row(elem_id="title-row"):
            gr.Markdown(
                "# 한국자동차연구원 V2X 자율주행 평가환경 POC\n"
                "Alpamayo 1.5 기반 차량–인프라 융합 의사결정 검증"
            )

        history_state = gr.State([])

        with gr.Tab("① 시나리오 단건 평가"):
            with gr.Row():
                with gr.Column(scale=1):
                    clip_dd = gr.Dropdown(
                        choices=list_sample_choices(),
                        label="시나리오 선택 (카테고리 / 거리 / clip)",
                    )
                    preview_btn = gr.Button("📷 카메라 미리보기")
                    info_box = gr.Textbox(label="시나리오 정보", lines=6, interactive=False)

                    gr.Markdown("---\n**V2X / 인프라 메시지 (어댑터 입력)**")
                    v2x_in = gr.Textbox(
                        label="메시지 (비우면 시나리오 기본값 사용)",
                        placeholder="예: 전방 30m 좌회전 / 200m 전방 공사구간 1차로 폐쇄",
                    )
                    base_chk = gr.Checkbox(label="차량 단독(V2X 미수신) baseline 동시 실행", value=True)
                    cf_chk = gr.Checkbox(label="반사실(direction swap) 검증 동시 실행", value=True)
                    run_btn = gr.Button("▶ 추론 실행", variant="primary")

                with gr.Column(scale=2):
                    cam_out = gr.Image(label="차량 전방 카메라 (Vehicle Adapter)", height=320)
                    bev_out = gr.Image(label="BEV — 예측 궤적 vs 정답", height=420)
                    metrics_out = gr.Markdown(label="평가 지표")
                    log_out = gr.Markdown(label="모델 의사결정 (Chain-of-Causation)")

            preview_btn.click(preview_clip, [clip_dd], [cam_out, info_box])
            run_btn.click(
                run_inference,
                [clip_dd, v2x_in, base_chk, cf_chk, history_state],
                [cam_out, bev_out, log_out, metrics_out, history_state, gr.State()],
            )

        with gr.Tab("② 시연 자동 실행 (Demo Run)"):
            gr.Markdown(
                "사전 큐레이션된 4개 시나리오에 대해 **시간 진행 모드** 로 시연 영상을 생성합니다.  \n"
                "각 시나리오에서 t0를 0.3초씩 전진시키며 매 프레임 **차량 단독 / V2X 연계 / 반사실** 세 조건을 "
                "추론하여 실제로 흐르는 영상을 만듭니다.  \n"
                "헤드라이너(11m 좌회전)는 12프레임, 나머지는 6프레임. 총 30프레임 × 3조건 = **90회 추론** "
                "(약 5–10분 소요). 사업단 시연용."
            )
            demo_btn = gr.Button("🎬 시연 자동 실행", variant="primary")
            demo_video = gr.Video(label="시연 영상")
            demo_summary = gr.Markdown()
            demo_btn.click(demo_run, [], [demo_video, demo_summary])

        with gr.Tab("③ 실시간 인터랙티브 시연"):
            gr.Markdown(
                "사전 캐시된 시나리오를 **즉시 재생**하며, V2X 프리셋 버튼으로 모델 의사결정 변화를 "
                "즉시 비교합니다.  \n"
                "카메라 영상은 네이티브 fps로 자동 재생, BEV는 프리셋 클릭 시 0초 지연으로 갱신.  \n"
                "_*캐시 빌드: `python prerender_demo_cache.py`_"
            )
            cache_choices = cache_scenario_choices()
            with gr.Row():
                with gr.Column(scale=1):
                    cache_dd = gr.Dropdown(
                        choices=cache_choices,
                        label="시나리오 (캐시)",
                        value=cache_choices[0] if cache_choices else None,
                    )
                    load_btn = gr.Button("🎬 불러오기", variant="primary")

                    gr.Markdown("---\n### 🛰️ V2X 프리셋 (즉시 전환)")
                    preset_buttons = []
                    preset_specs = [
                        ("default",   "✅ 기본 V2X (시나리오 기본값)"),
                        ("baseline",  "🚫 차량 단독 (V2X 미수신)"),
                        ("left_5",    "↰ Turn left in 5m"),
                        ("left_30",   "↰ Turn left in 30m"),
                        ("left_100",  "↰ Turn left in 100m"),
                        ("right_5",   "↱ Turn right in 5m"),
                        ("right_30",  "↱ Turn right in 30m"),
                        ("right_100", "↱ Turn right in 100m"),
                    ]
                    for key, label in preset_specs:
                        b = gr.Button(label, size="sm")
                        preset_buttons.append((b, key))

                    gr.Markdown(
                        "---\n"
                        "ⓘ **본 모델은 `Turn {left/right} in Nm` 형식의 V2X 메시지에 학습**되어 있습니다. "
                        "보행자/공사/응급 등 자연어 V2X 메시지에 대한 응답은 **1차년도 한국 데이터 fine-tuning** "
                        "과제로 진행됩니다. 이 한계 자체가 본 사업의 fine-tuning 필요성을 정량적으로 보여줍니다."
                    )

                with gr.Column(scale=2):
                    cache_video = gr.Video(
                        label="차량 전방 카메라 (자동재생, 루프)",
                        autoplay=True,
                        loop=True,
                        height=320,
                    )
                    cache_bev = gr.Image(label="BEV — 모델 의사결정 (즉시 전환)", height=380)
                    cache_status = gr.Markdown()
                    cache_metrics = gr.Markdown()
                    cache_cot = gr.Markdown()

            load_btn.click(
                cache_load_scenario,
                [cache_dd],
                [cache_video, cache_bev, cache_status, cache_metrics, cache_cot],
            )
            for b, key in preset_buttons:
                b.click(
                    lambda choice, k=key: cache_apply_preset(choice, k),
                    [cache_dd],
                    [cache_bev, cache_status, cache_metrics, cache_cot],
                )

        with gr.Tab("④ 🗨️ VQA (시각 질의응답)"):
            gr.Markdown(
                "현재 주행 장면에 대해 자연어로 질의응답합니다. 미리 캐시된 8개 질문은 즉시 표시되고, "
                "임의 질문은 라이브 추론(~10초)으로 답변합니다.  \n"
                "_본 모델은 영어 질의에 가장 안정적으로 응답합니다 (한국어 라벨은 표시용)._"
            )
            with gr.Row():
                with gr.Column(scale=1):
                    vqa_dd = gr.Dropdown(choices=cache_scenario_choices(), label="시나리오 (캐시)")
                    vqa_load_btn = gr.Button("🎬 불러오기", variant="primary")
                    gr.Markdown("---\n### 자유 질문 (라이브, ~10초)")
                    vqa_q_in = gr.Textbox(
                        label="Question (영어 권장, 묘사형 질문)",
                        placeholder="e.g. What do you see? / Is the road wet? / How wide is the lane?",
                        info="✓ 묘사형: 'What...', 'How many...', 'Describe...'\n✗ 결정형: 'Can I...', 'Should I...' (이건 ③ 탭 nav conditioning 사용)",
                    )
                    vqa_run_btn = gr.Button("▶ 라이브 질의", variant="secondary")
                    vqa_live_out = gr.Markdown()
                with gr.Column(scale=2):
                    vqa_video = gr.Video(label="장면", autoplay=True, loop=True, height=320)
                    vqa_status = gr.Markdown()
                    vqa_md = gr.Markdown(label="캐시된 Q&A")

            vqa_load_btn.click(vqa_load_scenario, [vqa_dd], [vqa_video, vqa_status, vqa_md])
            vqa_run_btn.click(vqa_run_live, [vqa_dd, vqa_q_in], [vqa_live_out])

        with gr.Tab("⑤ 📹 카메라 입력 개수 평가"):
            gr.Markdown(
                "동일 시나리오에서 모델 입력으로 사용되는 카메라 개수를 1/2/4개로 변경하여 결과를 비교합니다.  \n"
                "**용도**: 차량 센서 일부 고장 시나리오, 비용 절감을 위한 카메라 축소 평가, 모델 강건성 검증."
            )
            with gr.Row():
                with gr.Column(scale=1):
                    cam_dd = gr.Dropdown(choices=cache_scenario_choices(), label="시나리오 (캐시)")
                    cam_load_btn = gr.Button("🎬 불러오기", variant="primary")
                    cam_status = gr.Markdown()
                with gr.Column(scale=3):
                    with gr.Row():
                        cam_bev1 = gr.Image(label="1 cam (front-wide)", height=260)
                        cam_bev2 = gr.Image(label="2 cam (front-wide + tele)", height=260)
                        cam_bev4 = gr.Image(label="4 cam (cross + front + tele)", height=260)
                    cam_metrics = gr.Markdown()

            cam_load_btn.click(
                cam_load_scenario,
                [cam_dd],
                [cam_bev1, cam_bev2, cam_bev4, cam_status, cam_metrics],
            )

        with gr.Tab("⑥ 평가 이력"):
            history_md = gr.Markdown("_아직 실행 이력이 없습니다._")
            refresh_btn = gr.Button("🔄 새로고침")

            def render_hist(h):
                if not h:
                    return "_아직 실행 이력이 없습니다._"
                blocks = []
                for x in reversed(h):
                    block = (
                        f"### {x['ts']} — {x['category']}  `{x['clip']}`\n"
                        f"**V2X 메시지:** {x['v2x']}\n\n"
                        f"{metrics_table(x['metrics'])}\n\n"
                        f"- **V2X 연계 CoT:** {x['cot_v2x']}\n"
                    )
                    if x["cot_base"]:
                        block += f"- **차량 단독 CoT:** {x['cot_base']}\n"
                    if x["cot_cf"]:
                        block += f"- **반사실 CoT:** {x['cot_cf']}\n"
                    blocks.append(block)
                return "\n---\n".join(blocks)

            refresh_btn.click(render_hist, [history_state], [history_md])

        with gr.Tab("⑦ 🌐 Closed-loop (NRE)"):
            gr.Markdown(
                "**Alpasim + NVIDIA NRE(Neural Rendering Engine)** 가 차량 센서 영상을 사진실사로 "
                "렌더링하고, Alpamayo 1.5 는 그 영상만 보고 운전합니다. 시뮬레이터가 차량 동역학을 닫고 "
                "모델 출력이 다음 프레임의 상태를 결정하는 **closed-loop** 구성입니다.\n\n"
                "이 탭은 closed-loop 환경(예: KADaP A40 48GB GPU 서버)에서 "
                "`bash scripts/run_closedloop.sh` 실행 후 자동으로 데이터가 채워집니다. "
                "**본 ARM POC 노드에서는 \"미감지\"가 정상**입니다 — NRE 는 x86 + 대형 GPU 만 지원."
            )
            with gr.Row():
                with gr.Column(scale=1):
                    cl_health_md = gr.Markdown()
                    cl_gpu_md = gr.Markdown()
                    cl_refresh_btn = gr.Button("🔄 새로고침", variant="primary")
                    gr.Markdown("---\n### driver-0 (Alpamayo 1.5 추론)")
                    cl_drv_md = gr.Markdown()
                with gr.Column(scale=2):
                    gr.Markdown("### controller-0 (rollout orchestration)")
                    cl_ctrl_md = gr.Markdown()
                    gr.Markdown("### 최신 rollout MP4 (NRE 렌더링 결과)")
                    cl_meta_md = gr.Markdown()
                    with gr.Row():
                        cl_v1 = gr.Video(label="rollout #1 (최신)", height=220)
                        cl_v2 = gr.Video(label="rollout #2", height=220)
                    with gr.Row():
                        cl_v3 = gr.Video(label="rollout #3", height=220)
                        cl_v4 = gr.Video(label="rollout #4", height=220)

            _cl_outs = [
                cl_health_md, cl_gpu_md, cl_ctrl_md, cl_drv_md,
                cl_meta_md, cl_v1, cl_v2, cl_v3, cl_v4,
            ]
            cl_refresh_btn.click(cl_panel_refresh, [], _cl_outs)
            demo.load(cl_panel_refresh, [], _cl_outs)

        with gr.Tab("ⓘ 시스템 구성"):
            gr.Markdown(
                """
### 데이터 어댑터 구성

| 어댑터 | 입력 출처 (실증환경) | 본 POC 구현 |
|---|---|---|
| **차량 데이터 어댑터** (Vehicle CAN/Camera) | 실증차량 카메라 + IMU + ego pose | `physical_aiavdataset` parquet 로더 |
| **V2X / 인프라-라이다 어댑터** | 도로변 RSU·신호제어기·도로변 라이다·기상센서 (SAE J2735 / ETSI ITS-G5) | 운영자 텍스트 입력 또는 시나리오 기본 메시지 |

두 어댑터 모두 `adapters.py` 의 `VehicleDataAdapter` / `V2XAdapter` 인터페이스를 따르며,
실증환경 통합 시 라이브 ROS·DDS·MQTT 구독자로 교체됩니다.

### 모델
- **Alpamayo 1.5 (10B)** — NVIDIA의 vision-language-action 모델
- 입력: 멀티카메라 + ego 히스토리 (+ 자연어 instruction)
- 출력: 미래 궤적 (xy, rotation) + chain-of-causation 자연어 추론

### 평가 지표
- **ADE / FDE** — 예측 궤적과 정답 궤적의 평균/최종 L2 오차
- **Max lateral deviation** — 최대 횡방향 편차
- **Heading error** — 종단부 진행각 오차

### 한계 및 본 사업 1차년도 연계 사항
- **Closed-loop 시뮬레이션은 별도 x86 노드 필요**: NVIDIA NRE(Neural Rendering Engine)가 ARM 미지원
  → **KADaP 자동차산업클라우드(A40 48GB) 환경에 closed-loop 배포 완료** — Tab ⑦ 참조
- **현재 클립은 NVIDIA 제공 미국 주행 데이터**: 한국 도로/V2X 메시지 포맷에 맞춘 fine-tuning이 본 사업 1차년도 핵심 과제
- 반사실 검증 결과(direction swap)에서 일부 시나리오는 V2X 메시지를 모델이 무시 → 한국 데이터 도메인 적응 필요성의 정량 근거
                """
            )

    return demo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("--user", default="researcher")
    ap.add_argument("--password", default="alpamayo")
    args = ap.parse_args()

    demo = build_ui()
    demo.queue(max_size=4).launch(
        server_name=args.host,
        server_port=args.port,
        auth=(args.user, args.password),
        theme=gr.themes.Soft(primary_hue="blue", secondary_hue="cyan"),
        css=CSS,
        show_error=True,
    )


if __name__ == "__main__":
    main()
