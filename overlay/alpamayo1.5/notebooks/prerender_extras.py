"""Prerender VQA answers + camera-count comparison results.

Adds two more sections to the existing demo_cache built by
prerender_demo_cache.py:

  demo_cache/scen_XX/vqa.json          — list of {q_en, q_kr, answer}
  demo_cache/scen_XX/cam_<n>cam.png    — BEV from inference with N cameras
  demo_cache/scen_XX/cam_<n>cam_meta.json — metrics + cot per camera config

Run inside alpamayo-poc:
    PYTHONPATH=/workspace/alpamayo1.5/src:. python prerender_extras.py
"""

import json
from pathlib import Path

import numpy as np
import physical_ai_av
import torch
from PIL import Image

from alpamayo1_5 import helper
from alpamayo1_5.load_physical_aiavdataset import load_physical_aiavdataset
from alpamayo1_5.models.alpamayo1_5 import Alpamayo1_5

from app import compute_metrics
from make_video_nav import COLORS, render_bev, run_one_condition

NOTEBOOK_DIR = Path(__file__).parent
CACHE_DIR = NOTEBOOK_DIR / "demo_cache"

DEMO_INDICES = [0, 3, 7, 19]

# (en, kr_label) — model answers in English; we display Korean labels in UI
VQA_QUESTIONS = [
    ("Describe the scene.",                                  "현재 장면을 묘사하라"),
    ("What is the color of the traffic light?",              "신호등의 색은?"),
    ("How many vehicles are visible ahead?",                 "전방에 보이는 차량 수는?"),
    ("Are there any pedestrians near the road?",             "도로 근처에 보행자가 있나?"),
    ("What is the weather condition?",                       "기상 조건은?"),
    ("Is there any potential hazard ahead?",                 "전방에 잠재적 위험이 있나?"),
    ("How many lanes does this road have?",                  "이 도로는 몇 차로인가?"),
    ("What action should the ego vehicle take next?",        "자차가 다음에 취해야 할 동작은?"),
]

# Camera configurations to compare
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


def run_vqa(model, processor, data, question):
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
    torch.cuda.manual_seed_all(42)
    with torch.autocast("cuda", dtype=torch.bfloat16):
        extra = model.generate_text(
            data=model_inputs,
            top_p=0.98,
            temperature=0.6,
            num_samples=1,
            max_generation_length=256,
        )
    ans = extra["answer"][0]
    if not isinstance(ans, str):
        try:
            ans = " ".join(str(x) for x in ans)
        except TypeError:
            ans = str(ans)
    return ans


def main():
    if not (CACHE_DIR / "metadata.json").exists():
        raise SystemExit("Run prerender_demo_cache.py first to build base cache.")

    with open(CACHE_DIR / "metadata.json") as f:
        meta = json.load(f)

    print("Loading Alpamayo-1.5-10B...")
    model = Alpamayo1_5.from_pretrained(
        "nvidia/Alpamayo-1.5-10B", dtype=torch.bfloat16
    ).to("cuda")
    processor = helper.get_processor(model.tokenizer)
    avdi = physical_ai_av.PhysicalAIAVDatasetInterface()
    print("Model ready.\n")

    for scen in meta["scenarios"]:
        scen_idx = scen["scen_idx"]
        clip_id = scen["clip_id"]
        scen_dir = CACHE_DIR / f"scen_{scen_idx:02d}"
        print(f"\n=== Scenario {scen_idx}: {scen['category']} | clip={clip_id[:8]} ===")

        # ---- VQA ----
        # Use 1-cam loader for VQA (matches notebook example)
        try:
            data_vqa = load_physical_aiavdataset(
                clip_id, avdi=avdi,
                camera_features=[avdi.features.CAMERA.CAMERA_FRONT_WIDE_120FOV],
            )
        except Exception as e:
            print(f"  VQA load failed: {e}")
            data_vqa = None

        vqa_results = []
        if data_vqa is not None:
            for q_en, q_kr in VQA_QUESTIONS:
                print(f"  [VQA] {q_kr}")
                try:
                    ans = run_vqa(model, processor, data_vqa, q_en)
                except Exception as e:
                    ans = f"(error: {e})"
                vqa_results.append({"q_en": q_en, "q_kr": q_kr, "answer": ans})
                print(f"      → {ans[:120]}")

        with open(scen_dir / "vqa.json", "w") as f:
            json.dump(vqa_results, f, indent=2, ensure_ascii=False)

        # ---- Camera-count comparison ----
        cam_meta = []
        for key, label in CAM_CONFIGS:
            print(f"  [CAM] {label}")
            try:
                data_c = load_physical_aiavdataset(
                    clip_id, avdi=avdi,
                    camera_features=get_cam_features(avdi, key),
                )
            except Exception as e:
                print(f"    load failed: {e}")
                continue
            pred_xy, cot = run_one_condition(model, processor, data_c, None)
            gt_xy = data_c["ego_future_xyz"].cpu().numpy()[0, 0, :, :2].T
            metrics = compute_metrics(pred_xy, gt_xy)
            bev = render_bev({label: (pred_xy, COLORS["with_nav"])}, gt_xy)
            Image.fromarray(bev).save(scen_dir / f"cam_{key}.png")
            cam_meta.append({
                "key": key,
                "label": label,
                "n_cams": int(key[0]),
                "cot": cot,
                "metrics": metrics,
            })
            print(f"    ADE={metrics['ADE (m)']:.2f}m  cot={cot[:80]}")

        with open(scen_dir / "cam_meta.json", "w") as f:
            json.dump(cam_meta, f, indent=2, ensure_ascii=False)

    print("\n✅ Extras cached.")


if __name__ == "__main__":
    main()
