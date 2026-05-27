"""KADaP Alpamayo PoC — interactive closed-loop testbed for KATRI.

PoC v0 Gradio frontend. Each tab is added incrementally:
    ① 시나리오 평가   — existing rollout preview + one-shot trigger
    ② 정책 비교       — placeholder (Task #11)
    ③ 메트릭 대시보드 — placeholder (Task #12)
    ④ 시스템 상태     — placeholder (Task #13)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import gradio as gr

sys.path.insert(0, str(Path(__file__).parent))
from runner import (  # noqa: E402
    REPO_ROOT,
    RolloutRef,
    existing_rollouts,
    render_camera_mp4,
    run_oneshot,
)

SCENARIO_CATALOG: dict[str, dict] = {
    "clipgt-01d503d4-449b-46fc-8d78-9085e70d3554": {
        "label": "도심 일반 주행 (clipgt-01d503d4)",
        "description": (
            "기본 NRE artifact — 도심 일반 주행 시나리오. v0 데모용 단일 클립.\n"
            "Task #15에서 NRE artifact 추가 풀링으로 시나리오 카탈로그 확장."
        ),
    },
}

POLICY_CHOICES = [
    ("Alpamayo 1.5 (10B, 권장)", "alpamayo1_5"),
    ("Alpamayo 1.0", "alpamayo1"),
    ("VaVAM", "vavam"),
    ("Manual replay", "manual"),
]


# ---- Rollout helpers ----------------------------------------------------


def _rollout_label(r: RolloutRef) -> str:
    return f"{r.rollout_uuid[:8]}…  ({r.scenario_id[:14]}…)"


def rollout_choices() -> list[tuple[str, str]]:
    return [(_rollout_label(r), r.rollout_uuid) for r in existing_rollouts()]


def _find_rollout(uuid: str) -> RolloutRef | None:
    for r in existing_rollouts():
        if r.rollout_uuid == uuid:
            return r
    return None


def preview_rollout(uuid: str | None):
    """Render the selected pre-existing rollout (no simulation)."""
    if not uuid:
        return None, "_선택된 rollout 없음_", ""
    r = _find_rollout(uuid)
    if r is None:
        return None, f"❌ rollout {uuid} 디스크에 없음", ""
    mp4 = render_camera_mp4(r)
    meta = (
        f"**scenario**: `{r.scenario_id}`  \n"
        f"**uuid**: `{r.rollout_uuid}`  \n"
        f"**rollout.asl**: {r.asl.stat().st_size / 1024 / 1024:.1f} MB"
    )
    return (str(mp4) if mp4 else None), meta, ""


def trigger_oneshot(driver: str, scenario: str, progress=gr.Progress()):
    """Block-run a fresh simulation. Returns the same UI tuple as preview_rollout."""
    progress(0, desc="시작…")
    try:
        new = run_oneshot(
            driver=driver,
            on_progress=lambda pct, msg: progress(pct, desc=msg),
        )
    except Exception as e:
        return None, f"❌ 실행 실패: {e.__class__.__name__}: {e}", ""
    mp4 = render_camera_mp4(new)
    meta = (
        f"**scenario**: `{new.scenario_id}`  \n"
        f"**uuid**: `{new.rollout_uuid}`  \n"
        f"**rollout.asl**: {new.asl.stat().st_size / 1024 / 1024:.1f} MB"
    )
    return (str(mp4) if mp4 else None), meta, ""


def refresh_existing():
    """Re-list rollouts (after a new run completes the disk picks it up)."""
    choices = rollout_choices()
    value = choices[0][1] if choices else None
    return gr.update(choices=choices, value=value)


# ---- UI -----------------------------------------------------------------


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="KADaP Alpamayo PoC") as demo:
        gr.Markdown(
            "# KADaP Alpamayo 자율주행 테스트베드 PoC\n"
            "한국자동차연구원 납품용 — NVIDIA Alpamayo 1.5 + Alpasim + NRE closed-loop 시뮬레이션"
        )

        with gr.Tab("① 시나리오 평가"):
            gr.Markdown(
                "**📁 기존 결과 미리보기** (즉시) — 디스크에 이미 누적된 rollout 재생  \n"
                "**▶ 새 시뮬레이션 실행** (~10–15분) — wizard + compose up → driver 추론 → 새 rollout"
            )
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 📁 기존 결과")
                    existing_dd = gr.Dropdown(
                        choices=rollout_choices(),
                        value=None,
                        label="rollout (최신순)",
                    )
                    refresh_btn = gr.Button("↻ 새로고침", size="sm")

                    gr.Markdown("---\n### ▶ 새 시뮬레이션")
                    scn = gr.Dropdown(
                        choices=[(v["label"], k) for k, v in SCENARIO_CATALOG.items()],
                        value=next(iter(SCENARIO_CATALOG)),
                        label="시나리오 (v0: 1개 고정)",
                    )
                    scn_desc = gr.Markdown(
                        SCENARIO_CATALOG[next(iter(SCENARIO_CATALOG))]["description"]
                    )
                    pol = gr.Dropdown(
                        choices=POLICY_CHOICES,
                        value="alpamayo1_5",
                        label="정책 (driver)",
                    )
                    run_btn = gr.Button("▶ 새 시뮬레이션 실행 (~10–15분)", variant="primary")
                    run_status = gr.Textbox(label="실행 상태", interactive=False, lines=2)
                with gr.Column(scale=2):
                    video = gr.Video(label="결과 비디오 (front-wide camera)")
                    meta_md = gr.Markdown()

            scn.change(
                lambda k: SCENARIO_CATALOG.get(k, {}).get("description", ""),
                inputs=scn,
                outputs=scn_desc,
            )
            existing_dd.change(preview_rollout, inputs=existing_dd, outputs=[video, meta_md, run_status])
            refresh_btn.click(refresh_existing, outputs=existing_dd)
            run_btn.click(
                trigger_oneshot,
                inputs=[pol, scn],
                outputs=[video, meta_md, run_status],
            ).then(refresh_existing, outputs=existing_dd)

        with gr.Tab("② 정책 비교 (예정)"):
            gr.Markdown("_Task #11 — alpamayo1.5 / vavam / manual side-by-side_")

        with gr.Tab("③ 메트릭 대시보드 (예정)"):
            gr.Markdown(
                "_Task #12 — rollout.asl 파싱 → Safety / Comfort / Progress 시계열 + 누적 비교_"
            )

        with gr.Tab("④ 시스템 상태 (예정)"):
            gr.Markdown(
                "_Task #13 — docker ps / nvidia-smi / driver 추론 로그 / 최신 rollout MP4 4분할_"
            )

        gr.Markdown(
            f"_repo: `{REPO_ROOT.name}`  •  daemon 모드: "
            "단발성 (Task #16 upstream 버그 해결 후 활성화 예정)_"
        )

    return demo


def main():
    host = os.environ.get("KADAP_POC_HOST", "0.0.0.0")
    port = int(os.environ.get("KADAP_POC_PORT", "7870"))
    build_ui().launch(
        server_name=host,
        server_port=port,
        show_error=True,
        theme=gr.themes.Soft(),
    )


if __name__ == "__main__":
    main()
