"""KADaP Alpamayo PoC — interactive closed-loop testbed for KATRI.

PoC v0 Gradio frontend. Each tab is added incrementally:
    ① 시나리오 평가   — existing rollout preview + one-shot trigger
    ② 정책 비교       — placeholder (Task #11)
    ③ 메트릭 대시보드 — placeholder (Task #12)
    ④ 시스템 상태     — placeholder (Task #13)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import gradio as gr

sys.path.insert(0, str(Path(__file__).parent))
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import metrics  # noqa: E402
import report  # noqa: E402
import scenarios  # noqa: E402
import trace  # noqa: E402
from runner import (  # noqa: E402
    REPO_ROOT,
    ROLLOUTS_DIR,
    RolloutRef,
    existing_rollouts,
    latest_rollout_for,
    render_camera_mp4,
    run_oneshot,
)

COMPARE_SLOTS = 4  # max policies side-by-side

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
POLICY_LABEL = {key: label for label, key in POLICY_CHOICES}


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


# ---- Compare-tab helpers ------------------------------------------------


def _slot_for(rollout: RolloutRef | None, label: str):
    """Pack one (video, meta) update pair for a comparison slot."""
    if rollout is None:
        return (
            gr.update(value=None, visible=False),
            gr.update(value=None, visible=False),
        )
    mp4 = render_camera_mp4(rollout)
    meta = (
        f"**{label}**  \n"
        f"uuid `{rollout.rollout_uuid[:12]}…`  •  "
        f"{rollout.asl.stat().st_size / 1024 / 1024:.1f} MB"
    )
    return (
        gr.update(value=str(mp4) if mp4 else None, visible=True, label=label),
        gr.update(value=meta, visible=True),
    )


def _empty_slot():
    return _slot_for(None, "")


def _compare_outputs(slots: list[tuple]) -> list:
    """Pad to COMPARE_SLOTS and flatten as [video..., meta...]."""
    while len(slots) < COMPARE_SLOTS:
        slots.append(_empty_slot())
    videos = [s[0] for s in slots[:COMPARE_SLOTS]]
    metas = [s[1] for s in slots[:COMPARE_SLOTS]]
    return videos + metas


def _compare_existing(scenario: str, policies: list[str]):
    if not policies:
        return ["정책을 1개 이상 선택하세요"] + _compare_outputs([])
    slots = []
    hits = 0
    for p in policies[:COMPARE_SLOTS]:
        r = latest_rollout_for(scenario, p)
        if r is None:
            slots.append(_slot_for(None, ""))
        else:
            slots.append(_slot_for(r, POLICY_LABEL.get(p, p)))
            hits += 1
    miss = len(policies[:COMPARE_SLOTS]) - hits
    status = f"📁 {hits}개 정책 매치"
    if miss:
        missing = [p for p in policies[:COMPARE_SLOTS] if latest_rollout_for(scenario, p) is None]
        status += f", {miss}개 미발견 ({', '.join(missing)})"
    return [status] + _compare_outputs(slots)


# ---- System-status helpers (Tab ④) --------------------------------------
# Adapted from overlay/alpamayo1.5/notebooks/app.py ⑦. ARM POC uses
# `nre-0/trafficsim-0`; KADaP wizard names them `sensorsim-0/runtime-0`.

CLOSED_LOOP_SERVICES = ["controller-0", "driver-0", "physics-0", "sensorsim-0", "runtime-0"]


def _shell(cmd: list[str], timeout: int = 8) -> str:
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return out.stdout + out.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return f"<<error: {e}>>"


def _resolve_container(substr: str) -> str | None:
    for line in _shell(["docker", "ps", "-a", "--format", "{{.Names}}"]).splitlines():
        if substr in line:
            return line.strip()
    return None


def sys_service_health() -> str:
    raw = _shell(["docker", "ps", "-a", "--format", "{{json .}}"])
    services: dict[str, dict] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            info = json.loads(line)
        except json.JSONDecodeError:
            continue
        for svc in CLOSED_LOOP_SERVICES:
            if svc in info.get("Names", ""):
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
            emoji, any_up = "🟢", True
        elif state == "running":
            emoji, any_up = "🟡", True
        else:
            emoji = "🔴"
        rows.append(f"| `{svc}` | {emoji} {state} | {s['status']} |")
    header = "### Alpasim 서비스 상태\n"
    if not any_up:
        header += "_컨테이너 미감지 — `bash scripts/run_closedloop.sh` 후 새로고침._\n\n"
    return header + "\n".join(rows)


def sys_gpu_metrics() -> str:
    raw = _shell(
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
            used, total = int(parts[3]), int(parts[4])
            pct = 100 * used / max(total, 1)
        except ValueError:
            used = total = 0
            pct = 0
        rows.append(
            f"| {parts[0]} `{parts[1][:24]}` | {parts[2]}% | "
            f"{used}/{total} ({pct:.0f}%) | {parts[5]}°C |"
        )
    if not found:
        return "### GPU\n_nvidia-smi 사용 불가_"
    return "### GPU\n" + "\n".join(rows)


def sys_container_log(substr: str, tail: int) -> str:
    name = _resolve_container(substr)
    if not name:
        return f"_{substr} 컨테이너가 없습니다._"
    raw = _shell(["docker", "logs", "--tail", str(tail), name], timeout=10)
    if not raw.strip():
        return "_(empty)_"
    return f"```\n{raw[-6000:]}\n```"


def sys_latest_rollouts(n: int = 4) -> list[str | None]:
    """Latest N rollout MP4s — auto-renders missing ones via asl_to_frames."""
    rollouts = existing_rollouts()[:n]
    mp4s: list[str | None] = []
    for r in rollouts:
        p = render_camera_mp4(r)
        mp4s.append(str(p) if p else None)
    while len(mp4s) < n:
        mp4s.append(None)
    return mp4s


def sys_refresh():
    health = sys_service_health()
    gpu = sys_gpu_metrics()
    ctrl_log = sys_container_log("controller-0", tail=80)
    drv_log = sys_container_log("driver-0", tail=40)
    vids = sys_latest_rollouts(n=4)
    meta = f"_rollouts: {sum(1 for v in vids if v)}/{len(vids)} 변환됨_"
    return health, gpu, ctrl_log, drv_log, meta, vids[0], vids[1], vids[2], vids[3]


def _catalog_choices(limit: int = 50) -> list[tuple[str, str]]:
    """First N scenarios as (label, scene_id) tuples. v0 keeps the dropdown sane."""
    rows = scenarios.load_catalog()[:limit]
    out: list[tuple[str, str]] = []
    for r in rows:
        mark = "✅" if r.is_local() else "⬇"
        out.append((f"{mark}  {r.scene_id[:32]}…", r.scene_id))
    return out


def _metrics_for(uuid: str | None):
    if not uuid:
        return "_rollout을 선택하세요_", None
    r = _find_rollout(uuid)
    if r is None:
        return f"❌ rollout {uuid} 없음", None
    try:
        m = metrics.compute(r.asl)
    except Exception as e:
        return f"❌ 파싱 실패: {e.__class__.__name__}: {e}", None
    if m.is_empty:
        return "⚠️ controller_return 메시지 없음 — 시뮬이 1 step 이상 안 돌았을 가능성", None

    summary = (
        f"### {r.driver}  •  uuid `{r.rollout_uuid[:12]}…`\n\n"
        f"| 항목 | 값 |\n"
        f"|---|---|\n"
        f"| n_steps (controller) | {m.n_steps} |\n"
        f"| 시뮬 시간 | {m.duration_s:.2f} s |\n"
        f"| 평균 속도 | {m.avg_speed:.2f} m/s |\n"
        f"| 최대 속도 | {m.max_speed:.2f} m/s |\n"
        f"| 최대 횡가속도 | {m.max_lateral_accel:.3f} m/s² |\n"
        f"| 최대 jerk | {m.max_jerk:.3f} m/s³ |\n"
    )

    fig, axes = plt.subplots(3, 1, figsize=(7, 5), sharex=True)
    axes[0].plot(m.series.t, m.series.speed, color="tab:blue")
    axes[0].set_ylabel("speed (m/s)")
    axes[0].grid(alpha=0.3)
    axes[1].plot(m.series.t, m.series.lateral_accel, color="tab:orange")
    axes[1].set_ylabel("|lat accel| (m/s²)")
    axes[1].grid(alpha=0.3)
    axes[2].plot(m.series.t, m.series.jerk, color="tab:red")
    axes[2].set_ylabel("jerk (m/s³)")
    axes[2].set_xlabel("sim time (s)")
    axes[2].grid(alpha=0.3)
    fig.suptitle(f"{r.scenario_id[:14]}… / driver={r.driver}")
    fig.tight_layout()
    return summary, fig


def _compare_run(scenario: str, policies: list[str], progress=gr.Progress()):
    if not policies:
        return ["정책을 1개 이상 선택하세요"] + _compare_outputs([])
    n = min(len(policies), COMPARE_SLOTS)
    slots = []
    for i, p in enumerate(policies[:n]):
        base = i / n
        try:
            new = run_oneshot(
                driver=p,
                on_progress=lambda pct, msg, _base=base, _idx=i: progress(
                    _base + pct / n, desc=f"[{_idx + 1}/{n}] {p}: {msg}"
                ),
            )
            slots.append(_slot_for(new, POLICY_LABEL.get(p, p)))
        except Exception as e:
            slots.append(
                (
                    gr.update(value=None, visible=False),
                    gr.update(
                        value=f"**{POLICY_LABEL.get(p, p)}**: ❌ {e.__class__.__name__}",
                        visible=True,
                    ),
                )
            )
    return [f"✅ 순차 실행 완료 ({n}개)"] + _compare_outputs(slots)


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

        with gr.Tab("② 정책 비교"):
            gr.Markdown(
                "**📁 기존 결과로 비교** — 정책별 가장 최신 rollout (kadap_meta.json 의 driver 필드 매치)  \n"
                "**▶ 순차 실행** — 선택한 정책 N개를 순서대로 단발성 실행 (정책당 ~10–15분)"
            )
            with gr.Row():
                cmp_scn = gr.Dropdown(
                    choices=[(v["label"], k) for k, v in SCENARIO_CATALOG.items()],
                    value=next(iter(SCENARIO_CATALOG)),
                    label="시나리오",
                )
                cmp_pols = gr.CheckboxGroup(
                    choices=POLICY_CHOICES,
                    value=["alpamayo1_5"],
                    label="비교할 정책 (최대 4개)",
                )
            with gr.Row():
                cmp_load_btn = gr.Button("📁 기존 결과로 비교")
                cmp_run_btn = gr.Button("▶ 순차 실행", variant="primary")
            cmp_status = gr.Textbox(label="상태", interactive=False, lines=2)
            with gr.Row():
                cmp_videos = [
                    gr.Video(label=f"슬롯 {i + 1}", visible=False, height=240)
                    for i in range(COMPARE_SLOTS)
                ]
            with gr.Row():
                cmp_metas = [
                    gr.Markdown(visible=False) for _ in range(COMPARE_SLOTS)
                ]

            cmp_load_btn.click(
                lambda scn, pols: _compare_existing(scn, pols),
                inputs=[cmp_scn, cmp_pols],
                outputs=[cmp_status, *cmp_videos, *cmp_metas],
            )
            cmp_run_btn.click(
                _compare_run,
                inputs=[cmp_scn, cmp_pols],
                outputs=[cmp_status, *cmp_videos, *cmp_metas],
            )

        with gr.Tab("③ 메트릭 대시보드"):
            gr.Markdown(
                "rollout.asl → controller_return 시계열 추출.  \n"
                "**v0 메트릭**: 평균/최대 속도, 최대 횡가속도, 최대 jerk."
            )
            with gr.Row():
                with gr.Column(scale=1):
                    m_rollout = gr.Dropdown(
                        choices=rollout_choices(),
                        label="rollout 선택",
                    )
                    m_refresh = gr.Button("↻ 새로고침", size="sm")
                    m_summary = gr.Markdown()
                with gr.Column(scale=2):
                    m_plot = gr.Plot(label="시계열 (속도 / 횡가속도 / jerk)")

            m_rollout.change(_metrics_for, inputs=m_rollout, outputs=[m_summary, m_plot])
            m_refresh.click(
                lambda: gr.update(choices=rollout_choices()),
                outputs=m_rollout,
            )

        with gr.Tab("④ 시스템 상태"):
            gr.Markdown(
                "**closed-loop 컨테이너 5종 + GPU + 최신 rollout 4분할 라이브 모니터.**  \n"
                "수동 새로고침 — 시뮬 중에는 GPU util과 driver/controller 로그가 가장 의미 있음."
            )
            with gr.Row():
                with gr.Column(scale=1):
                    sys_health = gr.Markdown()
                    sys_gpu = gr.Markdown()
                    sys_btn = gr.Button("🔄 새로고침", variant="primary")
                    gr.Markdown("---\n### driver-0 (Alpamayo 1.5 추론)")
                    sys_drv = gr.Markdown()
                with gr.Column(scale=2):
                    gr.Markdown("### controller-0 (orchestration)")
                    sys_ctrl = gr.Markdown()
                    gr.Markdown("### 최신 rollout MP4 (NRE 렌더링 결과)")
                    sys_meta = gr.Markdown()
                    with gr.Row():
                        sys_v1 = gr.Video(label="#1 (최신)", height=220)
                        sys_v2 = gr.Video(label="#2", height=220)
                    with gr.Row():
                        sys_v3 = gr.Video(label="#3", height=220)
                        sys_v4 = gr.Video(label="#4", height=220)
            sys_outs = [
                sys_health, sys_gpu, sys_ctrl, sys_drv,
                sys_meta, sys_v1, sys_v2, sys_v3, sys_v4,
            ]
            sys_btn.click(sys_refresh, outputs=sys_outs)
            demo.load(sys_refresh, outputs=sys_outs)

        with gr.Tab("⑤ 📄 리포트 export"):
            gr.Markdown(
                "선택한 rollout의 메타 + 메트릭 + 시계열 plot 을 한 페이지 PDF로 생성. "
                "한자연 납품용 1-pager."
            )
            with gr.Row():
                with gr.Column(scale=1):
                    rep_rollout = gr.Dropdown(
                        choices=rollout_choices(), label="rollout 선택"
                    )
                    rep_refresh = gr.Button("↻ 새로고침", size="sm")
                    rep_btn = gr.Button("📄 PDF 생성", variant="primary")
                    rep_status = gr.Markdown()
                with gr.Column(scale=1):
                    rep_file = gr.File(label="다운로드", interactive=False)

            def _gen_report(uuid):
                if not uuid:
                    return "_rollout을 선택하세요_", None
                r = _find_rollout(uuid)
                if r is None:
                    return f"❌ rollout {uuid} 없음", None
                try:
                    pdf = report.build_report(r)
                except Exception as e:
                    return f"❌ 생성 실패: {e.__class__.__name__}: {e}", None
                return (
                    f"✅ `{pdf.name}` 생성 ({pdf.stat().st_size / 1024:.1f} KB)",
                    str(pdf),
                )

            rep_btn.click(_gen_report, inputs=rep_rollout, outputs=[rep_status, rep_file])
            rep_refresh.click(
                lambda: gr.update(choices=rollout_choices()),
                outputs=rep_rollout,
            )

        with gr.Tab("⑥ 🔬 closed-loop trace"):
            gr.Markdown(
                "**NRE → driver → controller 가 매 step 어떻게 연결되어 도는지 확인.**  \n"
                "rollout 선택 → step slider 로 이동 → 그 step 의 NRE 렌더 4-카메라 + driver 가 낸 예측 "
                "trajectory 길이 + controller 가 propagate 한 실제 ego pose / 속도 표시.  \n"
                "_v0 한계: 현 시나리오는 1.5 초 클립 + driver 가 pose history 부족으로 빈 trajectory 를 반환합니다 — "
                "더 긴 시나리오를 Tab ⑥에서 받아 비교하면 driver 실효 추론이 드러납니다._"
            )
            tr_rollout = gr.Dropdown(
                choices=rollout_choices(), label="rollout 선택", value=None
            )
            with gr.Row():
                tr_refresh = gr.Button("↻ rollout 목록 새로고침", size="sm")
                tr_extract = gr.Button("📷 frames 추출 / 갱신", size="sm")
            tr_status = gr.Markdown("_rollout 선택_")
            tr_step = gr.Slider(0, 1, value=0, step=1, label="step idx", interactive=True)
            tr_meta = gr.Markdown()
            with gr.Row():
                tr_cam_fw = gr.Image(label="front_wide_120fov", height=220)
                tr_cam_ft = gr.Image(label="front_tele_30fov", height=220)
            with gr.Row():
                tr_cam_cl = gr.Image(label="cross_left_120fov", height=220)
                tr_cam_cr = gr.Image(label="cross_right_120fov", height=220)

            CAM_ORDER = [
                "camera_front_wide_120fov",
                "camera_front_tele_30fov",
                "camera_cross_left_120fov",
                "camera_cross_right_120fov",
            ]

            def _trace_cameras(uuid, step_idx):
                r = _find_rollout(uuid) if uuid else None
                if r is None:
                    return [None] * 4
                cams = trace.step_cameras(r, int(step_idx))
                return [str(cams[k]) if k in cams else None for k in CAM_ORDER]

            def _trace_meta_md(uuid, step_idx):
                r = _find_rollout(uuid) if uuid else None
                if r is None:
                    return "_rollout 미선택_"
                steps = trace.parse_steps(r)
                if not steps or int(step_idx) >= len(steps):
                    return "_step 정보 없음_"
                s = steps[int(step_idx)]
                pred_txt = (
                    f"{s.n_predicted} waypoints, last=({s.last_predicted_xy[0]:.2f}, {s.last_predicted_xy[1]:.2f})"
                    if s.n_predicted and s.last_predicted_xy
                    else "**빈 trajectory** (pose history 부족 가능성)"
                )
                return (
                    f"### step {s.step_idx} / sim_time {s.sim_time_s:.2f}s\n\n"
                    f"| 항목 | 값 |\n|---|---|\n"
                    f"| timestamp_us | {s.timestamp_us} |\n"
                    f"| ego pose (x, y) | ({s.ego_xy[0]:.2f}, {s.ego_xy[1]:.2f}) |\n"
                    f"| ego speed | {s.ego_speed:.2f} m/s |\n"
                    f"| driver 예측 trajectory | {pred_txt} |\n"
                )

            def _trace_load(uuid):
                if not uuid:
                    return (
                        gr.update(maximum=1, value=0),
                        "_rollout 선택_",
                        "_rollout 미선택_",
                        None, None, None, None,
                    )
                r = _find_rollout(uuid)
                if r is None:
                    return (gr.update(maximum=1, value=0), f"❌ {uuid} 없음", "", None, None, None, None)
                # ensure frames present; cheap if cached
                trace.ensure_frames_extracted(r)
                steps = trace.parse_steps(r)
                n = max(1, len(steps) - 1)  # slider needs min<max even when empty
                cams = _trace_cameras(uuid, 0)
                meta = _trace_meta_md(uuid, 0)
                status = f"✅ {len(steps)} step / 4-cam frames 캐시 완료"
                return gr.update(maximum=n, value=0), status, meta, *cams

            def _trace_step_change(uuid, step_idx):
                meta = _trace_meta_md(uuid, step_idx)
                cams = _trace_cameras(uuid, step_idx)
                return meta, *cams

            def _trace_extract(uuid):
                if not uuid:
                    return "_rollout 미선택_"
                r = _find_rollout(uuid)
                if r is None:
                    return f"❌ {uuid} 없음"
                trace.ensure_frames_extracted(r)
                return "✅ frames 캐시 갱신됨"

            tr_outs = [tr_step, tr_status, tr_meta, tr_cam_fw, tr_cam_ft, tr_cam_cl, tr_cam_cr]
            tr_rollout.change(_trace_load, inputs=tr_rollout, outputs=tr_outs)
            tr_step.change(
                _trace_step_change,
                inputs=[tr_rollout, tr_step],
                outputs=[tr_meta, tr_cam_fw, tr_cam_ft, tr_cam_cl, tr_cam_cr],
            )
            tr_refresh.click(
                lambda: gr.update(choices=rollout_choices()), outputs=tr_rollout
            )
            tr_extract.click(_trace_extract, inputs=tr_rollout, outputs=tr_status)

        with gr.Tab("⑦ 🗂 시나리오 카탈로그"):
            gr.Markdown(
                f"NVIDIA `{scenarios.HF_REPO}` (HF dataset) 의 시나리오 카탈로그.  \n"
                "**v0**: 로컬 디스크에 있는지 표시 + 단건 다운로드. wizard에 다른 "
                "시나리오 주입은 별도 작업 (현재 wizard 기본값 1개 시나리오로 고정)."
            )
            cat_summary = gr.Markdown()
            with gr.Row():
                with gr.Column(scale=2):
                    cat_dd = gr.Dropdown(
                        label="시나리오 (처음 50개)",
                        choices=_catalog_choices(),
                        value=None,
                    )
                    cat_refresh = gr.Button("↻ 새로고침", size="sm")
                    cat_dl_btn = gr.Button("⬇ 선택 시나리오 USDZ 다운로드", variant="primary")
                with gr.Column(scale=1):
                    cat_detail = gr.Markdown()
            cat_status = gr.Markdown()

            def _summary_md():
                s = scenarios.summary()
                return (
                    f"**총 {s['total']}** 시나리오  •  로컬 **{s['local']}**  •  "
                    f"원격 **{s['remote']}**  •  카탈로그: `{s['csv']}`"
                )

            def _detail(scene_id):
                if not scene_id:
                    return "_시나리오 선택_"
                r = scenarios.get(scene_id)
                if r is None:
                    return f"❌ {scene_id} 카탈로그에 없음"
                mark = "✅ 로컬" if r.is_local() else "⬇ 원격"
                return (
                    f"**{mark}**  \n"
                    f"scene_id: `{r.scene_id}`  \n"
                    f"asset uuid: `{r.uuid}`  \n"
                    f"nre_version: {r.nre_version}  \n"
                    f"hf_revision: {r.hf_revision}  \n"
                    f"path: `{r.path}`"
                )

            def _download(scene_id, progress=gr.Progress()):
                if not scene_id:
                    return "_시나리오 선택_", "_시나리오 선택_"
                r = scenarios.get(scene_id)
                if r is None:
                    return f"❌ {scene_id} 카탈로그에 없음", _summary_md()
                if r.is_local():
                    return f"✅ 이미 로컬에 있음 — `{r.local_path.name}`", _summary_md()
                progress(0.1, desc=f"HF에서 {r.path} 다운로드…")
                try:
                    p = scenarios.download(r)
                except Exception as e:
                    return f"❌ 다운로드 실패: {e.__class__.__name__}: {e}", _summary_md()
                progress(1.0, desc="완료")
                size_mb = p.stat().st_size / 1024 / 1024
                return (
                    f"✅ `{p.name}` 받음 ({size_mb:.1f} MB) — sceneset 등록은 별도",
                    _summary_md(),
                )

            cat_dd.change(_detail, inputs=cat_dd, outputs=cat_detail)
            cat_dl_btn.click(_download, inputs=cat_dd, outputs=[cat_status, cat_summary])
            cat_refresh.click(
                lambda: (gr.update(choices=_catalog_choices()), _summary_md()),
                outputs=[cat_dd, cat_summary],
            )
            demo.load(_summary_md, outputs=cat_summary)

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
        # rollout MP4s live under alpasim/.../rollouts/<scenario>/<uuid>/rollout_asl_frames/,
        # PDF reports under /tmp/kadap-poc-reports (default /tmp is allowed, but explicit).
        allowed_paths=[str(ROLLOUTS_DIR), "/tmp/kadap-poc-reports"],
    )


if __name__ == "__main__":
    main()
