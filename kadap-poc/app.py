"""KADaP Alpamayo PoC — interactive closed-loop testbed for KATECH.

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

import ablation  # noqa: E402
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
    latest_rollout_for_ablation,
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

# Tab ② now compares ablations on the same Alpamayo 1.5 driver instead of
# different policies (per user feedback: "알파마요만으로 평가" — the demo is
# about showing Alpamayo + Alpasim closed-loop, not other models).
ABLATION_LABEL = {
    "base": "Base (모든 카메라, t0=300ms)",
    "no_left": "좌측 카메라 마스킹",
    "no_tele": "전방 망원 마스킹",
    "front_only": "전방 wide 단독",
    "start_500ms": "시작 0.5s 지연",
    "start_2s": "시작 2.0s 지연",
    "start_5s": "시작 5.0s 지연",
}
ABLATION_CHOICES = [(ABLATION_LABEL[k], k) for k in ablation.PRESETS.keys()]


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
    mp4 = render_camera_mp4(r, force=True)
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
    mp4 = render_camera_mp4(new, force=True)
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
    mp4 = render_camera_mp4(rollout, force=True)
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


def _ablation_existing(scenario: str, ablations: list[str]):
    """Look up the most recent rollout for each (scenario, ablation) pair."""
    if not ablations:
        return ["ablation 1개 이상 선택"] + _compare_outputs([])
    slots = []
    hits = 0
    for name in ablations[:COMPARE_SLOTS]:
        r = latest_rollout_for_ablation(scenario, name)
        label = ABLATION_LABEL.get(name, name)
        if r is None:
            slots.append(_slot_for(None, ""))
        else:
            slots.append(_slot_for(r, label))
            hits += 1
    miss = len(ablations[:COMPARE_SLOTS]) - hits
    status = f"📁 {hits}/{len(ablations[:COMPARE_SLOTS])}개 ablation 매치"
    if miss:
        missing = [
            n for n in ablations[:COMPARE_SLOTS] if latest_rollout_for_ablation(scenario, n) is None
        ]
        status += f" (미발견: {', '.join(missing)})"
    return [status] + _compare_outputs(slots)


def _ablation_run(scenario: str, ablations: list[str], progress=gr.Progress()):
    """Sequentially run Alpamayo 1.5 on the same scene with N different ablations."""
    if not ablations:
        return ["ablation 1개 이상 선택"] + _compare_outputs([])
    n = min(len(ablations), COMPARE_SLOTS)
    slots = []
    for i, name in enumerate(ablations[:n]):
        base = i / n
        spec = ablation.PRESETS[name]
        label = ABLATION_LABEL.get(name, name)
        try:
            new = run_oneshot(
                driver="alpamayo1_5",
                scene_ids=[scenario] if scenario else None,
                ablation=spec,
                on_progress=lambda pct, msg, _b=base, _i=i, _n=n, _l=label: progress(
                    _b + pct / _n, desc=f"[{_i + 1}/{_n}] {_l}: {msg}"
                ),
            )
            slots.append(_slot_for(new, label))
        except Exception as e:  # noqa: BLE001
            slots.append(
                (
                    gr.update(value=None, visible=False),
                    gr.update(
                        value=f"**{label}**: ❌ {e.__class__.__name__}: {e}",
                        visible=True,
                    ),
                )
            )
    return [f"✅ ablation 순차 실행 완료 ({n}개)"] + _compare_outputs(slots)


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
    """Latest N rollout MP4s — cached only; no blocking conversion at page load.

    Returns ``None`` for rollouts whose MP4 hasn't been materialised yet. To
    extract frames the user can hit Tab ⑥'s "📷 frames 추출 / 갱신" button.
    """
    rollouts = existing_rollouts()[:n]
    mp4s: list[str | None] = []
    for r in rollouts:
        p = render_camera_mp4(r, force=False)  # cache-only
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
    fig.suptitle(f"{r.scenario_id[:14]}… / driver={r.driver} / abl={r.ablation}")
    fig.tight_layout()
    return summary, fig


def _metrics_overlay(uuids: list[str] | None):
    """Overlay 2–4 rollouts (same scene, different ablations) on one chart."""
    if not uuids:
        return "_rollout 2개 이상 선택_", None
    rollouts: list[RolloutRef] = []
    for u in uuids[:COMPARE_SLOTS]:
        r = _find_rollout(u)
        if r is not None:
            rollouts.append(r)
    if len(rollouts) < 2:
        return "_유효한 rollout 2개 이상 필요_", None

    fig, axes = plt.subplots(3, 1, figsize=(8, 6), sharex=True)
    rows = ["| ablation | n_steps | avg_speed | max_lat_acc | max_jerk |", "|---|---|---|---|---|"]
    cmap = plt.get_cmap("tab10")
    for i, r in enumerate(rollouts):
        try:
            m = metrics.compute(r.asl)
        except Exception:  # noqa: BLE001
            continue
        if m.is_empty:
            continue
        color = cmap(i % 10)
        label = f"{r.ablation} [{r.rollout_uuid[:6]}]"
        axes[0].plot(m.series.t, m.series.speed, color=color, label=label)
        axes[1].plot(m.series.t, m.series.lateral_accel, color=color)
        axes[2].plot(m.series.t, m.series.jerk, color=color)
        rows.append(
            f"| {r.ablation} | {m.n_steps} | {m.avg_speed:.2f} | "
            f"{m.max_lateral_accel:.3f} | {m.max_jerk:.3f} |"
        )
    axes[0].set_ylabel("speed (m/s)"); axes[0].legend(fontsize=8); axes[0].grid(alpha=0.3)
    axes[1].set_ylabel("|lat accel| (m/s²)"); axes[1].grid(alpha=0.3)
    axes[2].set_ylabel("jerk (m/s³)"); axes[2].set_xlabel("sim time (s)"); axes[2].grid(alpha=0.3)
    fig.suptitle(f"Ablation overlay — {rollouts[0].scenario_id[:18]}…")
    fig.tight_layout()
    return "\n".join(rows), fig


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

        with gr.Tab("② Ablation 비교") as _t2:
            with gr.Group(visible=False) as _g2:
                gr.Markdown(
                    "**Alpamayo 1.5 고정**, 같은 scene에 ablation 4가지를 나란히.  \n"
                    "**📁 기존 결과로 비교** — (scene, ablation) 쌍별 가장 최신 rollout 매치  \n"
                    "**▶ 순차 실행** — 선택한 ablation N개를 순차적으로 새 rollout 생성 (각 ~10–15분)  \n"
                    "_ablation 이름은 `kadap-poc/ablation.py` PRESETS — 사용 가능한 정의는 새로 추가 가능._"
                )
                with gr.Row():
                    cmp_scn = gr.Dropdown(
                        choices=[(v["label"], k) for k, v in SCENARIO_CATALOG.items()],
                        value=next(iter(SCENARIO_CATALOG)),
                        label="시나리오",
                    )
                    cmp_abls = gr.CheckboxGroup(
                        choices=ABLATION_CHOICES,
                        value=["base", "no_left"],
                        label="비교할 ablation (최대 4개)",
                    )
                with gr.Row():
                    cmp_load_btn = gr.Button("📁 기존 결과로 비교")
                    cmp_run_btn = gr.Button("▶ ablation 순차 실행", variant="primary")
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
                    _ablation_existing,
                    inputs=[cmp_scn, cmp_abls],
                    outputs=[cmp_status, *cmp_videos, *cmp_metas],
                )
                cmp_run_btn.click(
                    _ablation_run,
                    inputs=[cmp_scn, cmp_abls],
                    outputs=[cmp_status, *cmp_videos, *cmp_metas],
                )

            _t2.select(lambda: gr.update(visible=True), outputs=_g2)
        with gr.Tab("⑥ 🔬 closed-loop trace") as _t6:
            with gr.Group(visible=False) as _g6:
                gr.Markdown(
                    "**NRE → driver → controller 가 매 step 어떻게 연결되어 도는지 확인.**  \n"
                    "rollout 선택 → step slider 로 이동 → 그 step 의 NRE 렌더 4-카메라 + driver 가 낸 예측 "
                    "trajectory 길이 + controller 가 propagate 한 실제 ego pose / 속도 표시.  \n"
                    "_2026-05-28: pose-seed 패치 + SDPA 워크어라운드 이후 driver 가 실제 trajectory 를 "
                    "내놓는지 cycle 단위로 검증 가능. n_predicted 가 0 보다 크고 step 마다 last_predicted_xy "
                    "가 의미있게 바뀌면 OK._"
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

                def _trace_load(uuid, progress=gr.Progress()):
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
                    # Frame extraction is heavy (minutes for 191 MB asl) — leave it
                    # to the explicit 📷 button so tab navigation stays responsive.
                    progress(0.1, desc="rollout.asl 파싱 중...")
                    steps = trace.parse_steps(r)
                    progress(0.9, desc="step 정보 준비 중...")
                    n = max(1, len(steps) - 1)  # slider needs min<max even when empty
                    # cameras only render if frames are already extracted on disk
                    cams = _trace_cameras(uuid, 0)
                    meta = _trace_meta_md(uuid, 0)
                    cached = sum(1 for c in cams if c)
                    status = (
                        f"✅ {len(steps)} step parsed."
                        f"  카메라 frames: {cached}/4 캐시됨"
                        + ("  — 📷 frames 추출 / 갱신 버튼으로 4-cam 생성" if cached < 4 else "")
                    )
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
                    trace.ensure_frames_extracted(r, force=True)
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

            _t6.select(lambda: gr.update(visible=True), outputs=_g6)

        gr.Markdown(
            f"_repo: `{REPO_ROOT.name}`  •  daemon 모드: "
            "단발성 (Task #16 upstream 버그 해결 후 활성화 예정)_"
        )
    return demo


def main():
    host = os.environ.get("KADAP_POC_HOST", "0.0.0.0")
    port = int(os.environ.get("KADAP_POC_PORT", "7870"))
    share = os.environ.get("KADAP_POC_SHARE", "0") == "1"
    build_ui().launch(
        server_name=host,
        server_port=port,
        share=share,  # KADAP_POC_SHARE=1 → gradio.live tunnel (works around cloudflared/SSE issues)
        show_error=True,
        theme=gr.themes.Soft(),
        # rollout MP4s live under alpasim/.../rollouts/<scenario>/<uuid>/rollout_asl_frames/,
        # PDF reports under /tmp/kadap-poc-reports (default /tmp is allowed, but explicit).
        allowed_paths=[str(ROLLOUTS_DIR), "/tmp/kadap-poc-reports"],
    )


if __name__ == "__main__":
    main()
