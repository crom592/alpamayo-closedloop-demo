# Closed-Loop NRE 영상 Tab ⑥ 임베드 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Closed-loop rollout마다 NRE가 합성한 front_wide 카메라 영상에 V2X/메트릭/속도 오버레이를 입힌 mp4를 사전 일괄 생성하고, Tab ⑥에서 rollout 선택 즉시 임베드 재생되도록 한다.

**Architecture:** 사전 batch 영상화 스크립트 + FastAPI StaticFiles 정적 서빙 + htmx 응답 HTML에 `<video controls>` 임베드. 시연 시 라이브 합성 없음, 정적 mp4 재생만.

**Tech Stack:** Python 3.12 (alpasim venv), matplotlib + PIL (오버레이), ffmpeg (인코딩), FastAPI/Jinja2/HTMX, Noto Sans CJK JP (한글 폰트).

**Spec:** [`docs/superpowers/specs/2026-06-01-closedloop-video-embed-design.md`](../specs/2026-06-01-closedloop-video-embed-design.md)

**Spec 대비 보정 사항** (구현 중 확인된 데이터 한계로 plan에서 명시):
- StepInfo에 `chain_of_thought`/`msg` 필드 없음 → 자막은 정량 정보 사용:
  `step k/N · t=X.Xs · v=Y.Ym/s · plan N pts`
- 기존 6개 rollout의 `kadap_meta.json`엔 `v2x_text` 키 없음 → `(V2X 미기록)` 표기. 신규 rollout (closedloop_bridge로 만든 것)만 V2X 값 정상 표출.

---

## File Structure

| 파일 | 역할 | 신규/수정 |
|---|---|---|
| `scripts/render_closedloop_videos.py` | 8 rollout 일괄 영상화 엔트리포인트. CLI: `--force`, `--uuid <uuid>` | 신규 |
| `kadap-poc-v2/closedloop_videos/` | mp4 캐시 디렉터리 (1개당 ~수백 KB) | 신규 |
| `kadap-poc-v2/closedloop_videos/.gitkeep` | 디렉터리 git 추적, mp4는 ignore | 신규 |
| `.gitignore` | `kadap-poc-v2/closedloop_videos/*.mp4` 무시 | 수정 |
| `kadap-poc-v2/main.py` | StaticFiles mount `/closedloop_videos`, `_rollout_to_view`에 `composite_url` 필드 추가 | 수정 |
| `kadap-poc-v2/templates/_closedloop_loaded.html` | 최상단 video 임베드 (영상 있으면) 또는 안내 div (없으면) | 수정 |

스크립트는 `scripts/render_all_demos.py`(20시나리오 일괄 렌더)와 같은 패턴 — 작은 단일 파일, CLI 진입, repo root에서 실행.

---

## Task 1: 영상 캐시 디렉터리 + .gitignore + StaticFiles mount

**Files:**
- Create: `kadap-poc-v2/closedloop_videos/.gitkeep` (empty)
- Modify: `.gitignore` (root)
- Modify: `kadap-poc-v2/main.py:55-60` (mount block, after `/demo_cache` mount)

- [ ] **Step 1: 디렉터리 + .gitkeep 생성**

```bash
mkdir -p /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/closedloop_videos
touch /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/closedloop_videos/.gitkeep
```

- [ ] **Step 2: .gitignore에 mp4 패턴 추가**

`/home/kadap/alpamayo-closedloop-demo/.gitignore` 끝에 추가:

```gitignore
# Closed-loop rendered videos (artifacts, can be regenerated)
kadap-poc-v2/closedloop_videos/*.mp4
```

- [ ] **Step 3: main.py에 StaticFiles mount 추가**

`kadap-poc-v2/main.py`의 `app.mount("/demo_cache", ...)` 블록 직후에 추가:

```python
CLOSEDLOOP_VIDEOS_DIR = HERE / "closedloop_videos"
if CLOSEDLOOP_VIDEOS_DIR.exists():
    app.mount(
        "/closedloop_videos",
        StaticFiles(directory=str(CLOSEDLOOP_VIDEOS_DIR)),
        name="closedloop_videos",
    )
```

- [ ] **Step 4: uvicorn 재시작 + mount 동작 확인**

```bash
kill $(pgrep -f "python -u main.py") 2>/dev/null; sleep 2
cd /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2 && nohup /home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/python -u main.py > /tmp/uvicorn.log 2>&1 &
sleep 8
curl -sI http://localhost:7861/closedloop_videos/.gitkeep | head -3
```

Expected: `HTTP/1.1 200 OK`

- [ ] **Step 5: Commit**

```bash
cd /home/kadap/alpamayo-closedloop-demo
git add .gitignore kadap-poc-v2/closedloop_videos/.gitkeep kadap-poc-v2/main.py
git commit -m "kadap-poc-v2: Tab ⑥ closed-loop 영상 캐시 디렉터리 + StaticFiles mount

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: 단일 rollout 영상화 dry-run (frames_jpeg가 이미 있는 2233cbf6)

**Files:**
- Create: `scripts/render_closedloop_videos.py`

가장 위험한 통합 (matplotlib 폰트 + PIL + ffmpeg + StepInfo 파싱)을 1개 rollout으로 먼저 검증.

- [ ] **Step 1: 스크립트 골격 작성 (단일 rollout, 하드코딩)**

`scripts/render_closedloop_videos.py` (단일 진입, repo root에서 실행):

```python
#!/usr/bin/env python3
"""Render NRE closed-loop rollout → mp4 with V2X/metrics/speed overlay.

For each rollout under alpasim run_dir/rollouts/, materialise
front_wide_120fov frames (if needed), parse step metrics, render
matplotlib overlay panels, then ffmpeg-encode as 2fps mp4 cached
under kadap-poc-v2/closedloop_videos/<rollout_uuid>.mp4.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "kadap-poc"))

from runner import RolloutRef, existing_rollouts  # noqa: E402
import trace as trace_mod  # noqa: E402
import metrics as metrics_mod  # noqa: E402

from matplotlib import font_manager as _fm
import matplotlib.pyplot as plt
from PIL import Image

# Korean glyph support (mirror vlm_qa.py / make_video_nav.py).
for _f in (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
):
    try:
        _fm.fontManager.addfont(_f)
    except Exception:
        pass
plt.rcParams["font.family"] = ["Noto Sans CJK JP", "NanumGothic", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

CACHE_DIR = REPO_ROOT / "kadap-poc-v2" / "closedloop_videos"
CAMERA_NAME = "camera_front_wide_120fov"
FPS = 2  # matches Tab ② composite pattern


def render_one(rollout: RolloutRef, force: bool) -> Path | None:
    """Render this rollout's mp4. Returns the mp4 path on success, None on skip/fail."""
    out = CACHE_DIR / f"{rollout.rollout_uuid}.mp4"
    if out.exists() and not force:
        print(f"  ✅ {rollout.rollout_uuid[:12]} cached (skip)")
        return out

    print(f"  · {rollout.rollout_uuid[:12]}: ensuring frames…")
    frames_dir = trace_mod.ensure_frames_extracted(rollout, force=True, timeout=900)
    cam_dir = frames_dir / CAMERA_NAME
    if not cam_dir.exists():
        print(f"  ❌ {rollout.rollout_uuid[:12]}: no {CAMERA_NAME} after extract")
        return None
    jpgs = sorted(cam_dir.glob("*.jpg"))
    if not jpgs:
        print(f"  ❌ {rollout.rollout_uuid[:12]}: 0 frames")
        return None

    print(f"  · {rollout.rollout_uuid[:12]}: parsing ASL ({len(jpgs)} frames)…")
    steps = trace_mod.parse_steps(rollout)
    m = metrics_mod.compute(rollout.asl)
    v2x_text = rollout.meta.get("v2x_text") or "(V2X 미기록)"
    ade_str = f"avg_v={m.avg_speed:.2f}m/s" if not m.is_empty else "metrics=N/A"
    max_str = f"max_v={m.max_speed:.2f}m/s" if not m.is_empty else ""

    print(f"  · {rollout.rollout_uuid[:12]}: composing {len(jpgs)} overlay frames…")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for k, jpg in enumerate(jpgs):
            step = steps[k] if k < len(steps) else None
            overlay_path = tmp_dir / f"frame_{k:04d}.png"
            _compose_frame(jpg, overlay_path, v2x_text, ade_str, max_str, k, len(jpgs), step)
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-framerate", str(FPS),
            "-i", str(tmp_dir / "frame_%04d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
            str(out),
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            print(f"  ❌ {rollout.rollout_uuid[:12]} ffmpeg fail: {result.stderr.decode()[:200]}")
            return None

    size_kb = out.stat().st_size / 1024
    print(f"  ✅ {rollout.rollout_uuid[:12]} → {out.name} ({size_kb:.0f}KB)")
    return out


def _compose_frame(jpg_in, png_out, v2x_text, ade_str, max_str, k, n, step):
    """Burn V2X/metrics/step overlay onto a single front_wide frame."""
    img = Image.open(jpg_in)
    w, h = img.size
    fig, ax = plt.subplots(figsize=(w / 100, h / 100), dpi=100)
    ax.imshow(img)
    ax.set_axis_off()
    ax.set_xlim(0, w); ax.set_ylim(h, 0)

    # Top-left V2X banner (yellow background)
    ax.text(
        20, 40, f"[V2X] {v2x_text}",
        fontsize=18, color="black",
        bbox=dict(facecolor="#f1c40f", edgecolor="none", pad=8),
        verticalalignment="top",
    )

    # Top-right step indicator
    if step is not None:
        step_str = f"step {k+1}/{n} · t={step.sim_time_s:.1f}s · v={step.ego_speed:.1f}m/s · plan {step.n_predicted} pts"
    else:
        step_str = f"step {k+1}/{n}"
    ax.text(
        w - 20, 40, step_str,
        fontsize=12, color="white",
        bbox=dict(facecolor="black", alpha=0.6, edgecolor="none", pad=6),
        verticalalignment="top", horizontalalignment="right",
    )

    # Bottom-right metrics
    metric_str = f"{ade_str} | {max_str}".strip(" |")
    ax.text(
        w - 20, h - 20, metric_str,
        fontsize=14, color="white",
        bbox=dict(facecolor="black", alpha=0.6, edgecolor="none", pad=6),
        verticalalignment="bottom", horizontalalignment="right",
    )

    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    fig.savefig(png_out, dpi=100, bbox_inches=None, pad_inches=0)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="Re-render even if mp4 exists")
    ap.add_argument("--uuid", help="Render only this rollout uuid (substring match)")
    args = ap.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    rollouts = existing_rollouts()
    if args.uuid:
        rollouts = [r for r in rollouts if args.uuid in r.rollout_uuid]
    print(f"=== Rendering {len(rollouts)} rollout(s) ===")
    ok = fail = 0
    for r in rollouts:
        try:
            res = render_one(r, force=args.force)
            ok += 1 if res else 0
            fail += 0 if res else 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ {r.rollout_uuid[:12]} exception: {exc}")
            fail += 1
    print(f"=== done: {ok} ok, {fail} fail ===")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: ffmpeg 가용성 확인**

```bash
which ffmpeg && ffmpeg -version 2>&1 | head -1
```

Expected: 경로 출력 + 버전 라인. 없으면 `sudo apt install -y ffmpeg`.

- [ ] **Step 3: 단일 rollout dry-run (frames_jpeg 이미 있는 것)**

```bash
cd /home/kadap/alpamayo-closedloop-demo
/home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/python scripts/render_closedloop_videos.py --uuid 2233cbf6 --force 2>&1 | tee /tmp/render_cl_dry.log
```

Expected:
```
=== Rendering 1 rollout(s) ===
  · 2233cbf6-598: ensuring frames…
  · 2233cbf6-598: parsing ASL (15 frames)…
  · 2233cbf6-598: composing 15 overlay frames…
  ✅ 2233cbf6-598 → 2233cbf6-5987-11f1-a97d-43a445f12e68.mp4 (XXXkB)
=== done: 1 ok, 0 fail ===
```

- [ ] **Step 4: 산출물 시각 검증**

```bash
ffprobe -v error -show_entries stream=duration,nb_frames,width,height \
  /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/closedloop_videos/2233cbf6-5987-11f1-a97d-43a445f12e68.mp4
```

Expected:
- `duration=7.5` (or close, 15 frames @ 2fps)
- `nb_frames=15`
- `width` / `height` 짝수 (yuv420p 요구)

```bash
# Send to user for visual verification — Korean text, V2X banner, step counter all visible
```

오버레이 한글 정상 표출 / V2X 배너 / step 카운터 / 메트릭 확인.

- [ ] **Step 5: Commit (스크립트만, mp4는 .gitignore)**

```bash
cd /home/kadap/alpamayo-closedloop-demo
git add scripts/render_closedloop_videos.py
git commit -m "scripts: render_closedloop_videos.py 신규 (단일 rollout dry-run 검증)

front_wide 120fov NRE 카메라 frame들을 ASL 메트릭/V2X와 함께
matplotlib overlay → ffmpeg 2fps mp4로 인코딩. 단일 rollout
2233cbf6 dry-run 통과.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: closedloop_load endpoint에 composite_url 필드 추가

**Files:**
- Modify: `kadap-poc-v2/main.py:515-555` (closedloop_load endpoint)
- Modify: `kadap-poc-v2/templates/_closedloop_loaded.html:1` (top of file, before existing muted div)

- [ ] **Step 1: closedloop_load context dict에 composite_url 추가**

`closedloop_load` 함수의 `TemplateResponse` 컨텍스트 dict에 다음 라인을 `"frames_cached": ...` 직후에 추가:

```python
        "composite_url": (
            f"/closedloop_videos/{uuid}.mp4"
            if (CLOSEDLOOP_VIDEOS_DIR / f"{uuid}.mp4").exists()
            else None
        ),
```

- [ ] **Step 2: _closedloop_loaded.html 최상단에 video 임베드 블록 추가**

파일 첫 줄(`<div class="muted">` 위)에 삽입:

```html
{% if composite_url %}
<div class="closedloop-video">
  <h3 style="margin-top:0;">▶ NRE 합성 영상 (front_wide 120fov)</h3>
  <video src="{{ composite_url }}" controls loop preload="metadata"
         style="max-width:640px; display:block; margin-bottom:1rem;"></video>
</div>
{% else %}
<div class="muted" style="margin-bottom:1rem;">
  ℹ 영상 미생성. <code>python scripts/render_closedloop_videos.py</code> 실행 후 rollout 재선택.
</div>
{% endif %}
```

- [ ] **Step 3: uvicorn 재시작 + Tab ⑥ 응답 확인**

```bash
kill $(pgrep -f "python -u main.py") 2>/dev/null; sleep 2
cd /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2 && nohup /home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/python -u main.py > /tmp/uvicorn.log 2>&1 &
sleep 8
curl -s "http://localhost:7861/closedloop/load?uuid=2233cbf6-5987-11f1-a97d-43a445f12e68" | head -20
```

Expected: `<video src="/closedloop_videos/2233cbf6-5987-11f1-a97d-43a445f12e68.mp4" controls ...>` 가 응답 HTML 최상단에 포함.

- [ ] **Step 4: 영상이 없는 rollout으로 fallback 확인**

```bash
# 아직 영상 안 만든 rollout 하나 찾기
ls /home/kadap/alpamayo-closedloop-demo/alpasim/alpasim/run_dir/rollouts/clipgt-01d503d4-449b-46fc-8d78-9085e70d3554/ | head -2
# 그 중 영상 없는 UUID로 closedloop/load 호출
TEST_UUID=$(ls /home/kadap/alpamayo-closedloop-demo/alpasim/alpasim/run_dir/rollouts/clipgt-01d503d4-449b-46fc-8d78-9085e70d3554/ | grep -v 2233cbf6 | head -1)
curl -s "http://localhost:7861/closedloop/load?uuid=$TEST_UUID" | grep -E "영상 미생성|composite|render_closedloop"
```

Expected: "영상 미생성. python scripts/render_closedloop_videos.py 실행 후 rollout 재선택." 라인 출력. video 태그 없음.

- [ ] **Step 5: Commit**

```bash
cd /home/kadap/alpamayo-closedloop-demo
git add kadap-poc-v2/main.py kadap-poc-v2/templates/_closedloop_loaded.html
git commit -m "kadap-poc-v2: Tab ⑥ rollout 선택 시 NRE 합성 영상 임베드

closedloop_load 응답에 composite_url 필드 추가, 영상이 캐시되어
있으면 최상단에 video controls 임베드, 없으면 생성 안내 div로
퇴화. 기존 trace/Plotly/PDF 섹션은 모두 유지.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: 나머지 7개 rollout batch 렌더 + end-to-end 검증

**Files:** (코드 변경 없음, 산출물 생성 + 검증만)

- [ ] **Step 1: 폐루프 시뮬 현황 확인 (신규 rollout 완료 여부)**

```bash
docker logs --tail 5 run_dir-controller-0-1 2>&1 | tail -3
ls /home/kadap/alpamayo-closedloop-demo/alpasim/alpasim/run_dir/rollouts/clipgt-01d503d4-449b-46fc-8d78-9085e70d3554/ | wc -l
```

신규 rollout이 완료되면 디렉터리 카운트가 +1. 미완 상태면 이 plan은 기존 7개에 대해서만 실행하고, 신규 완료 시 `python scripts/render_closedloop_videos.py` 재실행하면 자동 처리됨.

- [ ] **Step 2: 전체 batch 실행 (Task 2의 2233cbf6는 skip됨)**

```bash
cd /home/kadap/alpamayo-closedloop-demo
/home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/python scripts/render_closedloop_videos.py 2>&1 | tee /tmp/render_cl_batch.log
```

Expected: 각 rollout마다 `✅ <uuid> → <name>.mp4 (XXXkB)` 또는 `❌` + 사유. 마지막 라인 `=== done: N ok, M fail ===`. 예상 시간: rollout당 frame extract ~수분 (asl_to_frames subprocess), parse + render + ffmpeg ~15s. 보수적으로 rollout당 3~5분 × 7 = **20~35분**. (spec의 5분 추정은 frames가 이미 다 있을 때 기준이었으나 실제로는 6/7이 _jpeg 없음.)

- [ ] **Step 3: 모든 영상 산출물 점검**

```bash
ls -la /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/closedloop_videos/*.mp4
for f in /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/closedloop_videos/*.mp4; do
  echo "--- $(basename $f) ---"
  ffprobe -v error -show_entries stream=duration,nb_frames /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/closedloop_videos/$(basename $f) 2>&1 | grep -E "duration|nb_frames"
done
```

Expected: 7~8개 mp4, 각 duration 수 초 (rollout마다 step 수 다름), nb_frames > 0.

- [ ] **Step 4: 비-dry-run rollout 1개 시각 검증 (사용자에 SendUserFile)**

```bash
# 2233cbf6가 아닌 다른 영상 하나 사용자에 전달
SAMPLE=$(ls /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/closedloop_videos/*.mp4 | grep -v 2233cbf6 | head -1)
echo "검증할 샘플: $SAMPLE"
```

→ SendUserFile로 전달, 사용자 시각 확인. V2X 배너/메트릭/step 카운터/한글 정상.

- [ ] **Step 5: Tab ⑥에서 rollout 선택 시 video 재생 검증**

```bash
# v2 UI HTML이 video 태그를 응답에 포함하는지 다시 확인
UUID=$(basename $SAMPLE .mp4)
curl -s "http://localhost:7861/closedloop/load?uuid=$UUID" | grep -E "video|composite"
```

Expected: `<video src="/closedloop_videos/<UUID>.mp4" ...>` 라인 출력.

브라우저(또는 cloudflared 터널)에서 Tab ⑥ → rollout 드롭다운 → 영상 자동 표출 확인.

- [ ] **Step 6: Commit**

mp4는 .gitignore되어 있어 자동 제외. 코드 변경은 이전 task에서 다 commit됨. 이 task는 산출물만 생성 → commit 없음.

만약 batch 중 패치/수정이 필요했다면 그 변경분만 별도 commit.

- [ ] **Step 7: Push**

```bash
cd /home/kadap/alpamayo-closedloop-demo
git push origin main 2>&1 | tail -5
```

---

## Self-Review

**Spec coverage (10개 섹션 확인):**
1. 목표 — Task 2~4 전부 ✅
2. 비목표 (4항목) — 모두 plan 범위 밖 명시 ✅
3. 아키텍처 — Task 1(mount) + Task 2(렌더) + Task 3(임베드) ✅
4. 컴포넌트 5개 — File Structure 표에 1:1 매핑 ✅
5. 영상 사양 — Task 2 _compose_frame + ffmpeg 옵션 (yuv420p, 2fps) ✅
6. 데이터 흐름 — Task 3 검증 단계가 이 흐름 그대로 ✅
7. 사전 생성 절차 — Task 2 (단일 dry-run) + Task 4 (batch) ✅
8. 에러 처리 — render_one의 return None, 템플릿 else 분기 ✅
9. 테스트 — Task 2 Step 4 (dry-run 시각) + Task 3 Step 4 (fallback) + Task 4 Step 4 (비-dry-run 시각) ✅
10. 범위 — File Structure가 제외 항목 (다른 카메라, slider 변경, 다운로드 버튼 등) 자동 충족 ✅

**Placeholder scan:** 모든 step에 실제 코드/명령 포함. "TODO" / "TBD" / "add error handling" 같은 모호한 표현 없음. ✅

**Type consistency:** `RolloutRef`, `StepInfo`, `existing_rollouts`, `ensure_frames_extracted`, `parse_steps`, `metrics.compute`, `CLOSEDLOOP_VIDEOS_DIR`, `composite_url` — Task 1~4 전반에서 동일 명칭 사용. `_compose_frame` 시그니처 (jpg_in, png_out, v2x_text, ade_str, max_str, k, n, step) 일관. ✅

**Spec 보정 사항 명시:** chain_of_thought 부재 → 정량 자막 / v2x_text 부재 rollout → `(V2X 미기록)` 표기. 두 가지 모두 plan 헤더 + Task 2 코드에 반영. ✅
