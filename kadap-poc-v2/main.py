"""KADaP Alpamayo PoC v2 — KATECH V2X 자율주행 평가환경 PoC.

탭 구조 (원본 ARM POC와 동일 + NRE closed-loop 연결):
    ① 시나리오 단건 평가   — V2X 3조건 추론 + "NRE 검증" 버튼
    ② 시연 자동 실행      — 4 시나리오 × 3조건 mp4 (캐시 필요)
    ③ 실시간 인터랙티브   — 캐시 기반 V2X 프리셋 즉시 전환
    ④ VQA                — 시각 질의응답 (캐시 + 라이브)
    ⑤ 카메라 입력 개수    — 1/2/4 cam 비교 (캐시 필요)
    ⑥ NRE Closed-Loop    — step-by-step trace + Plotly trajectory
    ⓘ 시스템             — docker/gpu 상태 + 시나리오 카탈로그 + 시스템 구성

원본 POC 함수 (`overlay/alpamayo1.5/notebooks/...`) 그대로 import 재사용.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Backend modules from kadap-poc/ and overlay/alpamayo1.5/notebooks/ are
# re-used verbatim — no code duplication.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "kadap-poc"))
NOTEBOOK_DIR = REPO_ROOT / "overlay" / "alpamayo1.5" / "notebooks"
if NOTEBOOK_DIR.exists():
    sys.path.insert(0, str(NOTEBOOK_DIR))
ARM_NB_DIR = REPO_ROOT / "alpamayo1.5" / "notebooks"  # holds nav_demo_samples + demo_cache
DEMO_CACHE_DIR = ARM_NB_DIR / "demo_cache"

from runner import (  # noqa: E402
    ROLLOUTS_DIR,
    RolloutRef,
    existing_rollouts,
    render_camera_mp4,
)

import vlm_qa  # noqa: E402

HERE = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(HERE / "templates"))

app = FastAPI(title="한국형 V2X 자율주행 평가 플랫폼")
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
app.mount("/artifacts", StaticFiles(directory=str(ROLLOUTS_DIR)), name="artifacts")
if DEMO_CACHE_DIR.exists():
    app.mount(
        "/demo_cache", StaticFiles(directory=str(DEMO_CACHE_DIR)), name="demo_cache"
    )
CLOSEDLOOP_VIDEOS_DIR = HERE / "closedloop_videos"
if CLOSEDLOOP_VIDEOS_DIR.exists():
    app.mount(
        "/closedloop_videos",
        StaticFiles(directory=str(CLOSEDLOOP_VIDEOS_DIR)),
        name="closedloop_videos",
    )

SIM_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sim")
PARSE_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="parse")
JOBS: dict[str, dict] = {}
LAST_VQA: dict[str, vlm_qa.VqaResult] = {}


# V2X presets shown in Tab ① and ③ — match original POC.
V2X_PRESETS = [
    ("✅ 기본 V2X (시나리오 기본값)", ""),  # empty → use scenario default
    ("🚫 차량 단독 (V2X 미수신)", None),  # special: None = no nav_text
    ("↰ Turn left in 5m", "Turn left in 5m"),
    ("↰ Turn left in 30m", "Turn left in 30m"),
    ("↰ Turn left in 100m", "Turn left in 100m"),
    ("↱ Turn right in 5m", "Turn right in 5m"),
    ("↱ Turn right in 30m", "Turn right in 30m"),
    ("↱ Turn right in 100m", "Turn right in 100m"),
]


# Traffic-sim tab (🗺 능동 traffic sim) — scenario + logic options.
TRAFFICSIM_SCENARIOS = [
    {"key": "scen_01", "name": "① 보호좌회전 + 횡단보도 보행자"},
    {"key": "scen_02", "name": "② 신호등 고장 + RSU 우회 안내"},
    {"key": "scen_03", "name": "③ 골목 합류 + 사각지대 BSM"},
]
TRAFFICSIM_LOGICS = [
    {"key": "rule_based", "name": "RuleBased (V2X 우선순위)"},
    {"key": "alpamayo", "name": "Alpamayo VLA"},
    {"key": "v2x_blind", "name": "V2X 무시 (비교군)"},
]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _rollout_to_view(r: RolloutRef) -> dict:
    return {
        "uuid": r.rollout_uuid,
        "uuid_short": r.rollout_uuid[:12],
        "scenario_id": r.scenario_id,
        "scenario_short": r.scenario_id[:24],
        "driver": r.driver,
        "ablation": r.ablation,
        "v2x_text": r.meta.get("v2x_text", ""),
        "asl_mb": r.asl.stat().st_size / 1024 / 1024,
    }


def _scenario_view(s: dict) -> dict:
    """View-dict for a nav_demo_samples entry."""
    return {
        "idx": s["_idx"],
        "category": s["_category"],
        "distance_m": s["distance_m"],
        "clip_id": s["clip_id"],
        "clip_short": s["clip_id"][:8],
        "nav_text": s["nav_text"],
        "label": f"[{s['_idx']:02d}] {s['_category']} · d={s['distance_m']:.1f}m · {s['nav_text']}",
    }


# ---------------------------------------------------------------------------
# Landing
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return TEMPLATES.TemplateResponse(
        request, "base.html", {"active_tab": "guide"}
    )


@app.get("/tab/guide", response_class=HTMLResponse)
async def tab_guide(request: Request):
    return TEMPLATES.TemplateResponse(request, "tab_guide.html", {})


# ---------------------------------------------------------------------------
# Tab ① 시나리오 단건 평가 — V2X 3조건 + NRE 검증
# ---------------------------------------------------------------------------


@app.get("/tab/scenario_eval", response_class=HTMLResponse)
async def tab_scenario_eval(request: Request):
    samples = vlm_qa.load_samples()
    return TEMPLATES.TemplateResponse(
        request,
        "tab_scenario_eval.html",
        {
            "samples": [_scenario_view(s) for s in samples],
            "presets": V2X_PRESETS,
            "state": vlm_qa.model_status(),
        },
    )


@app.get("/scenario_eval/model_status", response_class=HTMLResponse)
async def scenario_eval_model_status(request: Request):
    return TEMPLATES.TemplateResponse(
        request, "_model_status.html", {"state": vlm_qa.model_status()}
    )


@app.post("/scenario_eval/load_model", response_class=HTMLResponse)
async def scenario_eval_load_model(request: Request):
    def _load() -> None:
        try:
            vlm_qa.ensure_model()
        except Exception:  # noqa: BLE001
            pass

    PARSE_EXECUTOR.submit(_load)
    return TEMPLATES.TemplateResponse(
        request, "_model_status.html", {"state": vlm_qa.model_status()}
    )


@app.post("/scenario_eval/run", response_class=HTMLResponse)
async def scenario_eval_run(request: Request):
    form = await request.form()
    try:
        idx = int(form.get("scenario_idx", "0"))
    except ValueError:
        idx = 0
    v2x_text = form.get("v2x_text", "")
    do_baseline = form.get("do_baseline") == "on"
    do_counterfactual = form.get("do_counterfactual") == "on"
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            PARSE_EXECUTOR,
            lambda: vlm_qa.run_three_conditions(
                idx, v2x_text, do_baseline, do_counterfactual
            ),
        )
    except Exception as e:  # noqa: BLE001
        return HTMLResponse(
            f"<div class='error'>추론 실패: {e.__class__.__name__}: {e}</div>"
        )
    token = uuid.uuid4().hex[:8]
    LAST_VQA[token] = result
    return TEMPLATES.TemplateResponse(
        request, "_scenario_eval_result.html", {"token": token, "result": result}
    )


@app.get("/scenario_eval/img/{token}/{kind}")
async def scenario_eval_img(token: str, kind: str):
    result = LAST_VQA.get(token)
    if result is None:
        return Response(status_code=404)
    if kind == "bev":
        return Response(content=result.bev_png, media_type="image/png")
    if kind == "cam":
        return Response(content=result.camera_png, media_type="image/png")
    return Response(status_code=404)


# ---------------------------------------------------------------------------
# NRE Closed-loop trigger (called from Tab ① 검증 버튼)
# ---------------------------------------------------------------------------


def _nre_runner(job_id: str, v2x_text: str, scene_id: str | None) -> None:
    import closedloop_bridge

    def on_progress(pct: float, msg: str) -> None:
        JOBS[job_id]["pct"] = pct
        JOBS[job_id]["msg"] = msg

    try:
        rollout = closedloop_bridge.run_closedloop_with_v2x(
            v2x_text=v2x_text, scene_id=scene_id, on_progress=on_progress
        )
        JOBS[job_id].update(
            {
                "state": "done",
                "pct": 1.0,
                "msg": "완료",
                "rollout_uuid": rollout.rollout_uuid,
            }
        )
    except Exception as e:  # noqa: BLE001
        JOBS[job_id].update(
            {"state": "error", "msg": f"{e.__class__.__name__}: {e}", "pct": 0.0}
        )


@app.post("/closedloop/run", response_class=HTMLResponse)
async def closedloop_run(request: Request):
    form = await request.form()
    v2x_text = form.get("v2x_text", "")
    scene_id = form.get("scene_id") or None
    job_id = uuid.uuid4().hex[:8]
    JOBS[job_id] = {
        "kind": "nre",
        "state": "running",
        "pct": 0.0,
        "msg": "큐 진입",
        "v2x_text": v2x_text,
        "scene_id": scene_id,
    }
    SIM_EXECUTOR.submit(_nre_runner, job_id, v2x_text, scene_id)
    return TEMPLATES.TemplateResponse(
        request, "_nre_progress.html", {"job_id": job_id, "job": JOBS[job_id]}
    )


@app.get("/closedloop/run/{job_id}", response_class=HTMLResponse)
async def closedloop_run_poll(request: Request, job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        return HTMLResponse("<div class='error'>unknown job</div>")
    return TEMPLATES.TemplateResponse(
        request, "_nre_progress.html", {"job_id": job_id, "job": job}
    )


# ---------------------------------------------------------------------------
# Tab ② 시연 자동 실행 — placeholder until demo_cache rebuilt
# ---------------------------------------------------------------------------


@app.get("/tab/demo_run", response_class=HTMLResponse)
async def tab_demo_run(request: Request):
    cache_ready = DEMO_CACHE_DIR.exists()
    composites: list[dict] = []
    if cache_ready:
        try:
            samples = vlm_qa.load_samples()
        except Exception:
            samples = []
        sample_by_idx = {i: s for i, s in enumerate(samples)}
        for scen_dir in sorted(DEMO_CACHE_DIR.glob("scen_*")):
            mp4 = scen_dir / "composite.mp4"
            if not mp4.exists():
                continue
            idx = int(scen_dir.name.split("_")[1])
            s = sample_by_idx.get(idx, {})
            composites.append(
                {
                    "scen_idx": idx,
                    "label": f"[{idx}] {s.get('_category', s.get('nav_maneuver', ''))}"
                    f" · {s.get('distance_m', 0):.1f}m"
                    f" · V2X=\"{s.get('nav_text', '')}\"",
                    "mp4_url": f"/demo_cache/scen_{idx:02d}/composite.mp4",
                }
            )
    return TEMPLATES.TemplateResponse(
        request,
        "tab_demo_run.html",
        {"cache_ready": cache_ready, "composites": composites},
    )


# ---------------------------------------------------------------------------
# Tab ③ 실시간 인터랙티브 — cache-based V2X preset switching
# ---------------------------------------------------------------------------


@app.get("/tab/interactive", response_class=HTMLResponse)
async def tab_interactive(request: Request):
    cache_ready = DEMO_CACHE_DIR.exists()
    cache_meta = {}
    scenarios_in_cache: list[dict] = []
    if cache_ready:
        meta_path = DEMO_CACHE_DIR / "metadata.json"
        if meta_path.exists():
            cache_meta = json.loads(meta_path.read_text())
            for entry in cache_meta.get("scenarios", []):
                scenarios_in_cache.append(
                    {
                        "scen_idx": entry["scen_idx"],
                        "label": f"[{entry['scen_idx']:02d}] {entry.get('category', '?')} · {entry.get('default_nav_text', '')}",
                        "default_nav_text": entry.get("default_nav_text", ""),
                    }
                )
    return TEMPLATES.TemplateResponse(
        request,
        "tab_interactive.html",
        {
            "cache_ready": cache_ready,
            "scenarios": scenarios_in_cache,
            "presets": V2X_PRESETS,
        },
    )


@app.get("/interactive/load", response_class=HTMLResponse)
async def interactive_load(request: Request, scen_idx: int):
    """Load a scenario's camera mp4 + default preset BEV."""
    if not DEMO_CACHE_DIR.exists():
        return HTMLResponse(
            "<div class='error'>demo_cache 없음 — prerender_demo_cache.py 먼저 실행</div>"
        )
    scen_dir = DEMO_CACHE_DIR / f"scen_{scen_idx:02d}"
    if not scen_dir.exists():
        return HTMLResponse(f"<div class='error'>scen_{scen_idx:02d} 없음</div>")
    return TEMPLATES.TemplateResponse(
        request,
        "_interactive_loaded.html",
        {
            "scen_idx": scen_idx,
            "camera_mp4": f"/demo_cache/scen_{scen_idx:02d}/camera.mp4",
            "bev_default": f"/demo_cache/scen_{scen_idx:02d}/bev_default.png",
        },
    )


@app.get("/interactive/preset", response_class=HTMLResponse)
async def interactive_preset(request: Request, scen_idx: int, key: str):
    """Apply a V2X preset → swap the BEV image."""
    if not DEMO_CACHE_DIR.exists():
        return HTMLResponse("<div class='error'>cache 없음</div>")
    bev_url = f"/demo_cache/scen_{scen_idx:02d}/bev_{key}.png"
    return HTMLResponse(f'<img src="{bev_url}" alt="BEV {key}" style="max-width:100%;">')


# ---------------------------------------------------------------------------
# Tab ④ VQA — visual Q&A on cached scenarios
# ---------------------------------------------------------------------------


@app.get("/tab/vqa", response_class=HTMLResponse)
async def tab_vqa(request: Request):
    cache_ready = DEMO_CACHE_DIR.exists()
    cache_scenarios: list[dict] = []
    if cache_ready:
        try:
            samples = vlm_qa.load_samples()
        except Exception:
            samples = []
        sample_by_idx = {i: s for i, s in enumerate(samples)}
        for scen_dir in sorted(DEMO_CACHE_DIR.glob("scen_*")):
            cam_path = scen_dir / "camera.mp4"
            if not cam_path.exists():
                continue
            idx = int(scen_dir.name.split("_")[1])
            s = sample_by_idx.get(idx, {})
            label = (
                f"[{idx}] {s.get('_category', s.get('nav_maneuver', ''))}"
                f" · {s.get('distance_m', 0):.1f}m"
                f" · V2X=\"{s.get('nav_text', '')}\""
            )
            cache_scenarios.append({"scen_idx": idx, "label": label})
    return TEMPLATES.TemplateResponse(
        request,
        "tab_vqa.html",
        {"cache_ready": cache_ready, "scenarios": cache_scenarios},
    )


@app.post("/vqa/live", response_class=HTMLResponse)
async def vqa_live(request: Request):
    form = await request.form()
    try:
        scen_idx = int(form.get("scen_idx", "-1"))
    except ValueError:
        return HTMLResponse("<div class='error'>잘못된 시나리오 인덱스</div>")
    question = str(form.get("question", "")).strip()
    if not question:
        return HTMLResponse("<div class='error'>질문을 입력해 주세요.</div>")
    if vlm_qa.model_status().get("state") != "ready":
        return HTMLResponse(
            "<div class='error'>모델이 아직 적재되지 않았습니다. ① 탭에서 먼저 모델을 적재해 주세요.</div>"
        )

    def _run() -> str:
        return vlm_qa.run_live_vqa(scen_idx, question)

    try:
        answer = await asyncio.get_event_loop().run_in_executor(PARSE_EXECUTOR, _run)
    except Exception as e:  # noqa: BLE001
        return HTMLResponse(f"<div class='error'>추론 실패: {e.__class__.__name__}: {e}</div>")
    return TEMPLATES.TemplateResponse(
        request,
        "_vqa_live_answer.html",
        {"question": question, "answer": answer},
    )


@app.get("/vqa/preset", response_class=HTMLResponse)
async def vqa_preset(request: Request, scen_idx: int):
    """Show only the scenario camera preview — cached Q&A list was removed
    because the canned answers didn't always match the actual scene. Live
    inference (POST /vqa/live) is now the single source of VQA answers."""
    if not DEMO_CACHE_DIR.exists():
        return HTMLResponse("<div class='error'>cache 없음</div>")
    scen_dir = DEMO_CACHE_DIR / f"scen_{scen_idx:02d}"
    if not scen_dir.exists():
        return HTMLResponse(f"<div class='error'>scen_{scen_idx:02d} 없음</div>")
    return TEMPLATES.TemplateResponse(
        request,
        "_vqa_preset.html",
        {
            "scen_idx": scen_idx,
            "camera_mp4": f"/demo_cache/scen_{scen_idx:02d}/camera.mp4",
        },
    )


# ---------------------------------------------------------------------------
# Tab ⑤ 카메라 입력 개수 평가 — cached comparison
# ---------------------------------------------------------------------------


@app.get("/tab/cam_count", response_class=HTMLResponse)
async def tab_cam_count(request: Request):
    cache_ready = DEMO_CACHE_DIR.exists()
    cache_scenarios: list[dict] = []
    if cache_ready:
        try:
            samples = vlm_qa.load_samples()
        except Exception:
            samples = []
        sample_by_idx = {i: s for i, s in enumerate(samples)}
        for scen_dir in sorted(DEMO_CACHE_DIR.glob("scen_*")):
            cam_meta_path = scen_dir / "cam_meta.json"
            if not cam_meta_path.exists():
                continue
            idx = int(scen_dir.name.split("_")[1])
            s = sample_by_idx.get(idx, {})
            label = (
                f"[{idx}] {s.get('_category', s.get('nav_maneuver', ''))}"
                f" · {s.get('distance_m', 0):.1f}m"
                f" · V2X=\"{s.get('nav_text', '')}\""
            )
            cache_scenarios.append({"scen_idx": idx, "label": label})
    return TEMPLATES.TemplateResponse(
        request,
        "tab_cam_count.html",
        {"cache_ready": cache_ready, "scenarios": cache_scenarios},
    )


@app.get("/cam_count/load", response_class=HTMLResponse)
async def cam_count_load(request: Request, scen_idx: int):
    if not DEMO_CACHE_DIR.exists():
        return HTMLResponse("<div class='error'>cache 없음</div>")
    meta_path = DEMO_CACHE_DIR / f"scen_{scen_idx:02d}" / "cam_meta.json"
    if not meta_path.exists():
        return HTMLResponse("<div class='error'>cam_meta.json 없음</div>")
    data = json.loads(meta_path.read_text())
    rows = data if isinstance(data, list) else data.get("configs", [])
    return TEMPLATES.TemplateResponse(
        request,
        "_cam_count_load.html",
        {
            "scen_idx": scen_idx,
            "rows": rows,
            "cache_dir": f"/demo_cache/scen_{scen_idx:02d}",
        },
    )


# ---------------------------------------------------------------------------
# Tab ⑥ NRE Closed-Loop — trace + metrics + PDF report
# ---------------------------------------------------------------------------


@app.get("/tab/closedloop", response_class=HTMLResponse)
async def tab_closedloop(request: Request):
    rollouts = [_rollout_to_view(r) for r in existing_rollouts()]
    return TEMPLATES.TemplateResponse(
        request, "tab_closedloop.html", {"rollouts": rollouts}
    )


@app.get("/closedloop/load", response_class=HTMLResponse)
async def closedloop_load(request: Request, uuid: str | None = None):
    if not uuid:
        return HTMLResponse("<div class='muted'>_rollout 선택_</div>")
    rollout = next((r for r in existing_rollouts() if r.rollout_uuid == uuid), None)
    if rollout is None:
        return HTMLResponse(f"<div class='error'>{uuid} 없음</div>")
    import trace as trace_mod

    loop = asyncio.get_event_loop()
    steps = await loop.run_in_executor(
        PARSE_EXECUTOR, lambda: trace_mod.parse_steps(rollout)
    )
    import metrics

    m = await loop.run_in_executor(PARSE_EXECUTOR, lambda: metrics.compute(rollout.asl))
    return TEMPLATES.TemplateResponse(
        request,
        "_closedloop_loaded.html",
        {
            "uuid": uuid,
            "rollout": _rollout_to_view(rollout),
            "n_steps": len(steps),
            "max_step": max(0, len(steps) - 1),
            "frames_cached": (rollout.dir / trace_mod.FRAMES_DIRNAME).exists(),
            "composite_url": (
                f"/closedloop_videos/{uuid}.mp4"
                if (CLOSEDLOOP_VIDEOS_DIR / f"{uuid}.mp4").exists()
                else None
            ),
            "sync_url": (
                f"/closedloop_videos/sync_{uuid}.mp4"
                if (CLOSEDLOOP_VIDEOS_DIR / f"sync_{uuid}.mp4").exists()
                else None
            ),
            "minimap_url": (
                f"/closedloop_videos/minimap_{uuid}.mp4"
                if (CLOSEDLOOP_VIDEOS_DIR / f"minimap_{uuid}.mp4").exists()
                else None
            ),
            "m_summary": {
                "n_steps": m.n_steps,
                "duration_s": m.duration_s,
                "avg_speed": m.avg_speed,
                "max_speed": m.max_speed,
                "max_lat": m.max_lateral_accel,
                "max_jerk": m.max_jerk,
            }
            if not m.is_empty
            else None,
            "t": list(map(float, m.series.t)) if not m.is_empty else [],
            "speed": list(map(float, m.series.speed)) if not m.is_empty else [],
            "lat": list(map(float, m.series.lateral_accel)) if not m.is_empty else [],
            "jerk": list(map(float, m.series.jerk)) if not m.is_empty else [],
        },
    )


@app.get("/closedloop/step", response_class=HTMLResponse)
async def closedloop_step(request: Request, uuid: str, step: int = 0):
    rollout = next((r for r in existing_rollouts() if r.rollout_uuid == uuid), None)
    if rollout is None:
        return HTMLResponse(f"<div class='error'>{uuid} 없음</div>")
    import trace as trace_mod

    loop = asyncio.get_event_loop()
    steps = await loop.run_in_executor(
        PARSE_EXECUTOR, lambda: trace_mod.parse_steps(rollout)
    )
    if not steps:
        return HTMLResponse("<div class='muted'>step 없음</div>")
    step_idx = max(0, min(int(step), len(steps) - 1))
    s = steps[step_idx]
    cam_dict = trace_mod.step_cameras(rollout, step_idx)
    cams = []
    for cam_id in [
        "camera_front_wide_120fov",
        "camera_front_tele_30fov",
        "camera_cross_left_120fov",
        "camera_cross_right_120fov",
    ]:
        p = cam_dict.get(cam_id)
        url = None
        if p is not None:
            try:
                url = f"/artifacts/{p.relative_to(ROLLOUTS_DIR).as_posix()}"
            except ValueError:
                pass
        cams.append({"id": cam_id, "url": url})
    window = max(0, step_idx - 20)
    past = steps[window : step_idx + 1]
    return TEMPLATES.TemplateResponse(
        request,
        "_closedloop_step.html",
        {
            "step": s,
            "step_idx": step_idx,
            "cams": cams,
            "ego_xs": [p.ego_xy[0] for p in past],
            "ego_ys": [p.ego_xy[1] for p in past],
            "pred_xy": s.last_predicted_xy,
        },
    )


@app.post("/closedloop/extract_frames", response_class=HTMLResponse)
async def closedloop_extract_frames(uuid: str):
    rollout = next((r for r in existing_rollouts() if r.rollout_uuid == uuid), None)
    if rollout is None:
        return HTMLResponse(f"<div class='error'>{uuid} 없음</div>")
    import trace as trace_mod

    await asyncio.get_event_loop().run_in_executor(
        SIM_EXECUTOR, lambda: trace_mod.ensure_frames_extracted(rollout, force=True)
    )
    return HTMLResponse(
        "<div class='success'>✅ frames 캐시 갱신 — rollout 다시 선택하세요</div>"
    )


@app.post("/closedloop/report", response_class=HTMLResponse)
async def closedloop_report(uuid: str):
    rollout = next((r for r in existing_rollouts() if r.rollout_uuid == uuid), None)
    if rollout is None:
        return HTMLResponse(f"<div class='error'>{uuid} 없음</div>")
    import report

    try:
        pdf = report.build_report(rollout)
    except Exception as e:  # noqa: BLE001
        return HTMLResponse(f"<div class='error'>{e.__class__.__name__}: {e}</div>")
    return HTMLResponse(
        f"<div class='success'>✅ <a href='/closedloop/report_file/{pdf.name}'>{pdf.name}</a> 생성 ({pdf.stat().st_size / 1024:.1f} KB)</div>"
    )


@app.get("/closedloop/report_file/{name}")
async def closedloop_report_file(name: str):
    p = Path("/tmp/kadap-poc-reports") / name
    if not p.exists():
        return HTMLResponse("not found", status_code=404)
    return FileResponse(str(p), media_type="application/pdf", filename=name)


# ---------------------------------------------------------------------------
# Tab 🗺 능동 traffic sim — scenario + AV logic selector
# ---------------------------------------------------------------------------


@app.get("/tab/trafficsim", response_class=HTMLResponse)
async def tab_trafficsim(request: Request):
    return TEMPLATES.TemplateResponse(
        request,
        "tab_trafficsim.html",
        {
            "scenarios": TRAFFICSIM_SCENARIOS,
            "logics": TRAFFICSIM_LOGICS,
        },
    )


# ---------------------------------------------------------------------------
# Tab ⓘ 시스템 — docker/gpu 상태 + 카탈로그 + 시스템 구성 정적 정보
# ---------------------------------------------------------------------------


@app.get("/tab/system", response_class=HTMLResponse)
async def tab_system(request: Request):
    return TEMPLATES.TemplateResponse(request, "tab_system.html", {})


@app.get("/system/refresh", response_class=HTMLResponse)
async def system_refresh(request: Request):
    def sh(cmd: list[str], timeout: int = 8) -> str:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return (r.stdout + r.stderr).strip()
        except Exception as e:  # noqa: BLE001
            return f"<<error: {e}>>"

    services = ["controller-0", "driver-0", "physics-0", "sensorsim-0", "runtime-0"]
    service_labels = {
        "controller-0": "차량 컨트롤러",
        "driver-0": "자율주행 모델 (Alpamayo)",
        "physics-0": "물리 시뮬레이터",
        "sensorsim-0": "센서 시뮬레이터",
        "runtime-0": "시뮬레이션 런타임",
    }
    docker_ps = sh(["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"])
    svc_status = {s: "—" for s in services}
    for line in docker_ps.splitlines():
        if "\t" not in line:
            continue
        name, status = line.split("\t", 1)
        for s in services:
            if s in name:
                svc_status[s] = status
                break
    rows = [
        {"label": service_labels[s], "status": svc_status[s]} for s in services
    ]
    gpu = sh(
        [
            "nvidia-smi",
            "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
            "--format=csv,noheader,nounits",
        ],
        timeout=5,
    )
    return TEMPLATES.TemplateResponse(
        request, "_system_refresh.html", {"rows": rows, "gpu": gpu}
    )


@app.get("/system/catalog", response_class=HTMLResponse)
async def system_catalog(request: Request):
    import scenarios

    rows = []
    for r in scenarios.load_catalog()[:50]:
        rows.append(
            {
                "scene_id": r.scene_id,
                "scene_short": r.scene_id[:36],
                "is_local": r.is_local(),
            }
        )
    return TEMPLATES.TemplateResponse(
        request,
        "_system_catalog.html",
        {"rows": rows, "summary": scenarios.summary()},
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "rollouts": len(existing_rollouts()),
            "demo_cache_ready": DEMO_CACHE_DIR.exists(),
            "samples": len(vlm_qa.load_samples()),
        }
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("KADAP_POC_PORT", "7861"))
    host = os.environ.get("KADAP_POC_HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port, log_level="info")
