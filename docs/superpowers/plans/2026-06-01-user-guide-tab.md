# 📖 사용 가이드 탭 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 평가위원 첫 접속 시 자동 표출되는 `📖 사용 가이드` 탭 추가. Playwright Python으로 실제 UI 캡처 + 8 섹션 단일 페이지에 6개 평가 탭의 목적/단계/해석/FAQ + 트러블슈팅 정리.

**Architecture:** 별도 Python venv의 Playwright headless chromium이 가동 중인 uvicorn(`localhost:7861`)에 접속해 16 캡처 PNG를 정적 디렉터리에 저장 → FastAPI Jinja2 템플릿이 sticky toc + 8 섹션 단일 페이지를 렌더 → base.html의 기본 hx-trigger 탭을 이 가이드로 전환.

**Tech Stack:** Playwright Python (chromium headless), FastAPI/Jinja2/HTMX, 기존 CSS 변수(`--primary`, `--accent` 등) 재사용.

**Spec:** [`docs/superpowers/specs/2026-06-01-user-guide-tab-design.md`](../specs/2026-06-01-user-guide-tab-design.md)

---

## File Structure

| 파일 | 역할 | 신규/수정 |
|---|---|---|
| `scripts/manual_capture/requirements.txt` | playwright 의존성 | 신규 |
| `scripts/manual_capture/capture.py` | 16 캡처 자동 실행 CLI. 모델 적재 대기 + selector + 액션 정의 | 신규 |
| `scripts/manual_capture/.venv/` | 별도 Python venv (gitignore) | 신규 (gitignore) |
| `kadap-poc-v2/static/manual/screenshots/*.png` | 16 캡처 PNG | 신규 (git 추적) |
| `kadap-poc-v2/main.py` | `/tab/guide` endpoint 추가 | 수정 |
| `kadap-poc-v2/templates/base.html` | nav 맨 앞에 `📖 사용 가이드` + `hx-trigger` 기본값 `/tab/guide`로 변경 | 수정 |
| `kadap-poc-v2/templates/tab_guide.html` | 단일 페이지 + sticky toc + 8 섹션 콘텐츠 | 신규 |
| `kadap-poc-v2/static/app.css` | `.guide-toc` / `.guide-section` / `.guide-screenshot` / `.guide-purpose` / `.guide-faq` | 수정 |
| `.gitignore` | `scripts/manual_capture/.venv/` 추가 | 수정 |

---

## Task 1: Playwright venv + landing 캡처 dry-run

가장 위험한 통합(Playwright 설치 + chromium + uvicorn 접속)을 1장 캡처로 먼저 검증.

**Files:**
- Create: `scripts/manual_capture/requirements.txt`
- Create: `scripts/manual_capture/capture.py`
- Modify: `.gitignore`

- [ ] **Step 1: requirements.txt 작성**

`scripts/manual_capture/requirements.txt`:
```
playwright>=1.40
```

- [ ] **Step 2: .gitignore에 venv 추가**

`.gitignore` 끝에 추가:
```
# Manual capture Playwright venv (regenerable)
scripts/manual_capture/.venv/
```

- [ ] **Step 3: venv 생성 + Playwright 설치**

```bash
cd /home/kadap/alpamayo-closedloop-demo/scripts/manual_capture
python3 -m venv .venv
.venv/bin/pip install --quiet -r requirements.txt
.venv/bin/playwright install --with-deps chromium 2>&1 | tail -5
```

Expected: chromium 바이너리 다운로드 (~150MB). `Chromium <version> downloaded` 메시지. 만약 `--with-deps`가 sudo 권한 요청하면 `--with-deps` 빼고 재시도.

- [ ] **Step 4: 캡처 스크립트 골격 (landing만)**

`scripts/manual_capture/capture.py`:

```python
#!/usr/bin/env python3
"""Capture KATECH demo UI screenshots via Playwright for the 사용 가이드 tab.

Connects to a running uvicorn (default http://localhost:7861), navigates each
tab, waits for content to settle, and saves PNGs to
kadap-poc-v2/static/manual/screenshots/.

Run with: scripts/manual_capture/.venv/bin/python scripts/manual_capture/capture.py
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Page

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = REPO_ROOT / "kadap-poc-v2" / "static" / "manual" / "screenshots"
VIEWPORT = {"width": 1440, "height": 900}


def capture_landing(page: Page, base_url: str, out: Path) -> None:
    page.goto(base_url, wait_until="networkidle")
    page.wait_for_timeout(800)
    page.screenshot(path=str(out), full_page=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://localhost:7861")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", help="Capture only this name (substring match)")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport=VIEWPORT, locale="ko-KR")
        page = ctx.new_page()

        targets = [
            ("landing", capture_landing),
        ]
        for name, fn in targets:
            if args.only and args.only not in name:
                continue
            out = OUT_DIR / f"{name}.png"
            if out.exists() and not args.force and not args.only:
                print(f"  ✅ {name} cached (skip)")
                continue
            print(f"  · {name} capturing…")
            try:
                fn(page, args.url, out)
                size = out.stat().st_size / 1024
                print(f"  ✅ {name} → {out.name} ({size:.0f}KB)")
            except Exception as exc:  # noqa: BLE001
                print(f"  ❌ {name}: {exc}")

        browser.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: uvicorn 가동 확인 + landing dry-run**

uvicorn이 이미 떠 있어야 함. 없으면 띄움:
```bash
pgrep -af "python -u main.py" | grep -v grep || (cd /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2 && nohup /home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/python -u main.py > /tmp/uvicorn.log 2>&1 &)
sleep 5
curl -sI http://localhost:7861/ | head -1
```
Expected: `HTTP/1.1 200 OK`

캡처 실행:
```bash
cd /home/kadap/alpamayo-closedloop-demo
scripts/manual_capture/.venv/bin/python scripts/manual_capture/capture.py --only landing
```
Expected: `✅ landing → landing.png (NNNKB)`.

- [ ] **Step 6: 산출물 확인**

```bash
ls -la /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/static/manual/screenshots/landing.png
file /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/static/manual/screenshots/landing.png
```
Expected: `PNG image data, 1440 x 900, 8-bit/color RGBA, non-interlaced`.

- [ ] **Step 7: Commit**

```bash
cd /home/kadap/alpamayo-closedloop-demo
git add .gitignore scripts/manual_capture/requirements.txt scripts/manual_capture/capture.py kadap-poc-v2/static/manual/screenshots/landing.png
git commit -m "scripts: manual_capture/ Playwright venv + landing capture dry-run

사용 가이드 탭용 UI 캡처 자동화. 별도 Python venv + Playwright
chromium headless. landing 1장 dry-run 통과.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: 캡처 정의 16장 + 모델 적재 대기 + 일괄 실행

**Files:**
- Modify: `scripts/manual_capture/capture.py` (캡처 함수 16개 추가)

Spec 5.3 표에 정의된 16 캡처를 자동화. 모델 적재가 필요한 캡처는 시작 전 `/scenario_eval/load_model` POST → polling으로 `ready` 대기.

- [ ] **Step 1: 모델 적재 helper + 캡처 함수 추가**

`scripts/manual_capture/capture.py`의 import 아래에 helper 추가:

```python
import urllib.request
import json as _json


def ensure_model_loaded(base_url: str, timeout: int = 180) -> None:
    """Trigger model load if not ready, poll status until ready."""
    status_url = f"{base_url}/scenario_eval/model_status"
    load_url = f"{base_url}/scenario_eval/load_model"

    def _state() -> str:
        with urllib.request.urlopen(status_url, timeout=10) as r:
            html = r.read().decode()
        for s in ("ready", "loading", "error", "idle"):
            if s in html:
                return s
        return "unknown"

    if _state() == "ready":
        print("  · model already ready")
        return
    print("  · POST /scenario_eval/load_model")
    req = urllib.request.Request(load_url, data=b"", method="POST")
    urllib.request.urlopen(req, timeout=10).read()
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = _state()
        print(f"  · model state={st}")
        if st == "ready":
            return
        if st == "error":
            raise RuntimeError("model load reported error")
        time.sleep(5)
    raise TimeoutError(f"model not ready within {timeout}s")


def goto_tab(page: Page, base_url: str, slug: str) -> None:
    """Click the nav tab matching this slug and wait for #content to swap."""
    page.goto(base_url, wait_until="networkidle")
    page.wait_for_timeout(400)
    page.locator(f'a.tab[hx-get="/tab/{slug}"]').click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
```

- [ ] **Step 2: 16 캡처 함수 정의**

Step 1의 `capture_landing` 함수 아래에 추가. 각 함수는 (page, base_url, out) 시그니처:

```python
# --- Tab ① 시나리오 단건 평가 ---
def cap_01_initial(page, base_url, out):
    goto_tab(page, base_url, "scenario_eval")
    page.screenshot(path=str(out))


def cap_01_input(page, base_url, out):
    goto_tab(page, base_url, "scenario_eval")
    page.select_option('select[name="scenario_idx"]', "0")
    page.wait_for_timeout(300)
    page.select_option('select[name="v2x_text"]', label="↰ Turn left in 5m")
    page.wait_for_timeout(300)
    page.screenshot(path=str(out))


def cap_01_result(page, base_url, out):
    goto_tab(page, base_url, "scenario_eval")
    page.select_option('select[name="scenario_idx"]', "0")
    page.wait_for_timeout(300)
    page.click('button:has-text("▶ 평가 실행")')
    page.wait_for_selector("#se-result img, #se-result .error", timeout=180000)
    page.wait_for_timeout(600)
    page.screenshot(path=str(out), full_page=True)


# --- Tab ② 시연 자동 실행 ---
def cap_02_gallery(page, base_url, out):
    goto_tab(page, base_url, "demo_run")
    page.screenshot(path=str(out), full_page=True)


def cap_02_playing(page, base_url, out):
    goto_tab(page, base_url, "demo_run")
    page.locator("video").first.evaluate("v => v.play()")
    page.wait_for_timeout(1500)
    page.screenshot(path=str(out))


# --- Tab ③ 실시간 인터랙티브 ---
def cap_03_initial(page, base_url, out):
    goto_tab(page, base_url, "interactive")
    page.screenshot(path=str(out))


def cap_03_preset(page, base_url, out):
    goto_tab(page, base_url, "interactive")
    page.select_option('select[name="scen_idx"]', "0")
    page.wait_for_selector("#interactive-loaded video", timeout=10000)
    page.wait_for_timeout(800)
    # click a V2X preset button if any
    btn = page.locator("button.preset-btn").first
    if btn.count() > 0:
        btn.click()
        page.wait_for_timeout(600)
    page.screenshot(path=str(out), full_page=True)


# --- Tab ④ VQA ---
def cap_04_initial(page, base_url, out):
    goto_tab(page, base_url, "vqa")
    page.screenshot(path=str(out), full_page=True)


def cap_04_question(page, base_url, out):
    goto_tab(page, base_url, "vqa")
    page.select_option('#vqa-scen', "0")
    page.wait_for_selector("#vqa-loaded video", timeout=10000)
    page.fill('input[name="question"]', "Describe the road and weather.")
    page.wait_for_timeout(400)
    page.screenshot(path=str(out), full_page=True)


def cap_04_answer(page, base_url, out):
    goto_tab(page, base_url, "vqa")
    page.select_option('#vqa-scen', "0")
    page.wait_for_selector("#vqa-loaded video", timeout=10000)
    page.fill('input[name="question"]', "Describe the road and weather.")
    page.click('button:has-text("▶ 질문")')
    page.wait_for_selector("#vqa-live-result .cot-card", timeout=120000)
    page.wait_for_timeout(600)
    page.screenshot(path=str(out), full_page=True)


# --- Tab ⑤ 카메라 개수 ---
def cap_05_initial(page, base_url, out):
    goto_tab(page, base_url, "cam_count")
    page.screenshot(path=str(out))


def cap_05_result(page, base_url, out):
    goto_tab(page, base_url, "cam_count")
    page.select_option('select[name="scen_idx"]', "0")
    page.wait_for_selector("#cc-loaded img, #cc-loaded table", timeout=10000)
    page.wait_for_timeout(600)
    page.screenshot(path=str(out), full_page=True)


# --- Tab ⑥ Closed-Loop ---
def cap_06_initial(page, base_url, out):
    goto_tab(page, base_url, "closedloop")
    page.screenshot(path=str(out))


def cap_06_loaded(page, base_url, out):
    goto_tab(page, base_url, "closedloop")
    # pick the first option with content (skip the "rollout 선택" empty option)
    opts = page.locator('select[name="uuid"] option').all()
    chosen = None
    for o in opts:
        v = o.get_attribute("value") or ""
        if v:
            chosen = v
            break
    if chosen:
        page.select_option('select[name="uuid"]', chosen)
        page.wait_for_selector("#cl-loaded video, #cl-loaded .muted", timeout=15000)
        page.wait_for_timeout(800)
    page.screenshot(path=str(out), full_page=True)


# --- Tab ⓘ 시스템 ---
def cap_info_system(page, base_url, out):
    goto_tab(page, base_url, "system")
    page.screenshot(path=str(out), full_page=True)
```

- [ ] **Step 3: targets 리스트에 16 캡처 등록**

`main()` 안의 `targets = [...]`를 다음과 같이 교체:

```python
        targets = [
            ("landing",                capture_landing),
            ("01_scenario_eval_initial",   cap_01_initial),
            ("01_scenario_eval_input",     cap_01_input),
            ("01_scenario_eval_result",    cap_01_result),
            ("02_demo_run_gallery",        cap_02_gallery),
            ("02_demo_run_playing",        cap_02_playing),
            ("03_interactive_initial",     cap_03_initial),
            ("03_interactive_preset",      cap_03_preset),
            ("04_vqa_initial",             cap_04_initial),
            ("04_vqa_question",            cap_04_question),
            ("04_vqa_answer",              cap_04_answer),
            ("05_cam_count_initial",       cap_05_initial),
            ("05_cam_count_result",        cap_05_result),
            ("06_closedloop_initial",      cap_06_initial),
            ("06_closedloop_loaded",       cap_06_loaded),
            ("info_system",                cap_info_system),
        ]
```

- [ ] **Step 4: main()에 모델 적재 단계 추가**

`main()`의 `with sync_playwright() as pw:` 직전에 추가:

```python
    print("=== Ensuring Alpamayo model loaded (Tab ① /scenario_eval/load_model) ===")
    ensure_model_loaded(args.url)
```

- [ ] **Step 5: 전체 일괄 실행**

```bash
cd /home/kadap/alpamayo-closedloop-demo
scripts/manual_capture/.venv/bin/python scripts/manual_capture/capture.py --force 2>&1 | tee /tmp/manual_capture.log
```

Expected: 모델 적재 진행 메시지 + 16개 `✅ <name> → <name>.png (NNNKB)` 라인. Cap_01_result는 모델 추론 ~1분 소요, cap_04_answer는 VQA ~30초 소요.

- [ ] **Step 6: 산출물 확인**

```bash
ls /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/static/manual/screenshots/ | wc -l
# Expected: 16
for f in /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2/static/manual/screenshots/*.png; do
  echo "$(basename $f) $(file -b "$f" | head -c 50)"
done
```

Expected: 16개 모두 `PNG image data, 1440 x ...`.

- [ ] **Step 7: Commit (캡처 + 스크립트 변경)**

```bash
cd /home/kadap/alpamayo-closedloop-demo
git add scripts/manual_capture/capture.py kadap-poc-v2/static/manual/screenshots/
git commit -m "manual_capture: 16 캡처 자동화 + 모델 적재 대기

각 평가 탭의 초기/입력/결과 상태를 1440×900 PNG로 일괄 캡처.
모델 적재(~1분) 대기 후 Tab ① 결과 + Tab ④ VQA 응답까지
실측 캡처. 16장 모두 정상.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: tab_guide.html + endpoint + nav 변경

**Files:**
- Create: `kadap-poc-v2/templates/tab_guide.html` (8 섹션, sticky toc)
- Modify: `kadap-poc-v2/main.py` (`/tab/guide` endpoint)
- Modify: `kadap-poc-v2/templates/base.html` (nav + hx-trigger)

가장 큰 콘텐츠 작업. tab_guide.html을 한 번에 작성.

- [ ] **Step 1: main.py에 `/tab/guide` endpoint 추가**

`main.py`의 `@app.get("/", ...)` 랜딩 핸들러 근처(또는 시스템 탭 endpoint 위/아래)에 다음 추가. 라인 117 부근:

```python
@app.get("/tab/guide", response_class=HTMLResponse)
async def tab_guide(request: Request):
    return TEMPLATES.TemplateResponse(request, "tab_guide.html", {})
```

- [ ] **Step 2: base.html nav 변경**

`kadap-poc-v2/templates/base.html` 라인 19-27의 tabs 리스트 맨 앞에 가이드 추가:

```jinja
  {% set tabs = [
    ('guide',         '📖 사용 가이드'),
    ('scenario_eval', '① 시나리오 단건 평가'),
    ('demo_run',      '② 시연 자동 실행'),
    ('interactive',   '③ 실시간 인터랙티브'),
    ('vqa',           '④ VQA'),
    ('cam_count',     '⑤ 카메라 입력 개수'),
    ('closedloop',    '⑥ NRE Closed-Loop'),
    ('system',        'ⓘ 시스템'),
  ] %}
```

- [ ] **Step 3: base.html 기본 hx-trigger 변경**

라인 37의 `<main>`에서 `hx-get="/tab/scenario_eval"`을 `hx-get="/tab/guide"`로 변경:

```html
<main id="content" hx-get="/tab/guide" hx-trigger="load" hx-swap="innerHTML">
  <div class="muted">로딩 중…</div>
</main>
```

- [ ] **Step 4: tab_guide.html 작성**

`kadap-poc-v2/templates/tab_guide.html` 신규 작성. 길이가 길어 단일 파일로 작성:

```html
<section class="card guide-page">
  <div class="guide-layout">
    <aside class="guide-toc">
      <h3>목차</h3>
      <ol>
        <li><a href="#guide-1">1. 시작하기</a></li>
        <li><a href="#guide-2">2. 시나리오 단건 평가</a></li>
        <li><a href="#guide-3">3. 시연 자동 실행</a></li>
        <li><a href="#guide-4">4. 실시간 인터랙티브</a></li>
        <li><a href="#guide-5">5. VQA</a></li>
        <li><a href="#guide-6">6. 카메라 입력 개수</a></li>
        <li><a href="#guide-7">7. Closed-Loop</a></li>
        <li><a href="#guide-8">8. 트러블슈팅</a></li>
      </ol>
    </aside>

    <article class="guide-body">

      <section id="guide-1" class="guide-section">
        <h2>1. 시작하기</h2>
        <p class="guide-purpose">
          본 플랫폼은 한국형 V2X 자율주행 의사결정 평가용 데모입니다.
          NVIDIA Alpamayo 1.5(10B VLA)와 Cosmos-Reason2 8B(VLM)를 기반으로,
          V2X 메시지가 자율주행 모델의 의사결정에 미치는 영향을 정량 평가합니다.
        </p>
        <figure class="guide-screenshot">
          <img src="/static/manual/screenshots/landing.png" alt="첫 화면">
          <figcaption>첫 화면: 좌측부터 가이드 → 평가 탭 ①~⑥ → 시스템</figcaption>
        </figure>
        <h3>권장 평가 흐름</h3>
        <ol>
          <li><strong>① 시나리오 단건 평가</strong>: 가장 먼저 모델을 적재(~1분)하고 V2X 효과를 정량 확인</li>
          <li><strong>② 시연 자동 실행</strong>: 사전 렌더링된 20 시나리오 시연 영상 갤러리</li>
          <li><strong>③ 실시간 인터랙티브</strong>: V2X preset을 즉시 전환하며 BEV 변화 관찰</li>
          <li><strong>④ VQA</strong>: 주행 장면에 자유 질의 응답</li>
          <li><strong>⑤ 카메라 입력 개수</strong>: 1/2/4cam 구성별 강건성 비교</li>
          <li><strong>⑥ Closed-Loop</strong>: NRE 폐루프 시뮬레이션 결과 재생</li>
        </ol>
        <h3>사전 준비</h3>
        <p>최초 진입 시 <strong>① 탭에서 모델 적재 버튼을 누르고 약 1분 대기</strong>. 적재 후엔 모든 탭이 즉시 응답합니다.</p>
      </section>

      <section id="guide-2" class="guide-section">
        <h2>2. ① 시나리오 단건 평가</h2>
        <p class="guide-purpose">
          단일 시나리오에 대해 V2X 메시지 / baseline(V2X 미수신) / 반사실(counterfactual)
          3조건의 궤적 예측을 비교, ADE / FDE / 측방 편차 / 방위 오차를 BEV 위에 즉시 정량 비교.
        </p>
        <figure class="guide-screenshot">
          <img src="/static/manual/screenshots/01_scenario_eval_initial.png" alt="초기 상태">
          <figcaption>초기: 모델 적재 버튼 + 시나리오/V2X preset 드롭다운</figcaption>
        </figure>
        <figure class="guide-screenshot">
          <img src="/static/manual/screenshots/01_scenario_eval_input.png" alt="입력 선택">
          <figcaption>시나리오 + V2X preset 선택</figcaption>
        </figure>
        <figure class="guide-screenshot">
          <img src="/static/manual/screenshots/01_scenario_eval_result.png" alt="결과 BEV + 메트릭">
          <figcaption>결과: BEV 궤적 비교 + 메트릭 테이블</figcaption>
        </figure>
        <h3>사용 절차</h3>
        <ol>
          <li>처음 진입 시 <strong>"모델 적재"</strong> 클릭 → 약 1분 대기 (상태 자동 갱신)</li>
          <li>시나리오 드롭다운에서 평가 대상 선택 (예: <code>[00] 근거리 좌회전 · 11.2m</code>)</li>
          <li>V2X preset 선택 (예: <code>↰ Turn left in 5m</code>)</li>
          <li>baseline / 반사실 체크박스 그대로 두고 <strong>"▶ 평가 실행"</strong> 클릭</li>
          <li>약 30~60초 후 BEV 이미지 3장 + 메트릭 테이블 출력</li>
        </ol>
        <h3>결과 해석</h3>
        <ul>
          <li><strong>ADE</strong> (Average Displacement Error): 예측과 GT 궤적의 평균 거리. 작을수록 양호.</li>
          <li><strong>FDE</strong> (Final Displacement Error): 마지막 시점의 거리. ADE보다 큰 경향.</li>
          <li><strong>Max lateral deviation</strong>: 측방 최대 편차 — 차선 이탈 위험 지표.</li>
          <li><strong>Heading error</strong>: 방위 오차 — 진로 방향 정확도.</li>
          <li>해석 기준: <strong>V2X 조건 ADE ≤ baseline ADE</strong>면 V2X 메시지의 의사결정 개선 효과 확인.</li>
        </ul>
        <h3>자주 묻는 질문</h3>
        <dl class="guide-faq">
          <dt>Q. "모델이 적재되지 않았습니다" 경고가 보입니다.</dt>
          <dd>A. 모델 적재 버튼을 누르고 상태가 <code>ready</code>가 될 때까지 (~1분) 기다린 후 다시 실행하세요.</dd>
          <dt>Q. 반사실(counterfactual)은 무엇을 의미하나요?</dt>
          <dd>A. 같은 시나리오에 정반대 V2X 메시지를 주입했을 때의 모델 응답입니다. V2X 메시지가 모델 의사결정에 실제 영향을 주는지의 sanity check.</dd>
        </dl>
      </section>

      <section id="guide-3" class="guide-section">
        <h2>3. ② 시연 자동 실행</h2>
        <p class="guide-purpose">
          사전 렌더링된 20개 시나리오의 시연 영상 갤러리. 각 영상은 카메라 + V2X 배너 + AI reasoning 자막 + 예측 BEV가 7.5초 합성된 timeline.
        </p>
        <figure class="guide-screenshot">
          <img src="/static/manual/screenshots/02_demo_run_gallery.png" alt="갤러리">
          <figcaption>20개 시나리오 영상 갤러리 (2×N 그리드)</figcaption>
        </figure>
        <figure class="guide-screenshot">
          <img src="/static/manual/screenshots/02_demo_run_playing.png" alt="재생 중">
          <figcaption>영상 재생 중 — V2X 배너 + AI reasoning 자막</figcaption>
        </figure>
        <h3>사용 절차</h3>
        <ol>
          <li>관심 시나리오 영상의 ▶ 버튼 클릭 → 7.5초 재생 (loop)</li>
          <li>영상을 일시정지/탐색하려면 video controls 사용</li>
          <li>다른 영상도 동시에 재생 가능</li>
        </ol>
        <h3>결과 해석</h3>
        <ul>
          <li>2 fps × 15 프레임 = 7.5초. 실시간이 아닌 슬로우 모션 시각화.</li>
          <li>좌상단 V2X 배너 / 좌하단 AI 추론 자막 / 우하단 메트릭 동시 비교.</li>
          <li>시나리오 라벨은 거리/방향 카테고리로 표기 (예: <code>[15] 중거리 좌회전 · 17.8m</code>).</li>
        </ul>
        <h3>자주 묻는 질문</h3>
        <dl class="guide-faq">
          <dt>Q. 영상이 짧아 보입니다.</dt>
          <dd>A. 의도된 7.5초 슬로우 모션입니다. 시각적 임팩트를 위해 loop 자동 재생.</dd>
          <dt>Q. 영상이 로드되지 않습니다.</dt>
          <dd>A. 페이지 새로고침 후 재시도. 그래도 안 되면 운영자에 문의.</dd>
        </dl>
      </section>

      <section id="guide-4" class="guide-section">
        <h2>4. ③ 실시간 인터랙티브</h2>
        <p class="guide-purpose">
          시나리오를 선택하면 카메라 영상과 BEV 예측이 즉시 표출되고,
          V2X preset 버튼으로 메시지를 바꿔가며 BEV 변화를 실시간 비교 가능.
        </p>
        <figure class="guide-screenshot">
          <img src="/static/manual/screenshots/03_interactive_initial.png" alt="초기">
          <figcaption>초기: 시나리오 드롭다운</figcaption>
        </figure>
        <figure class="guide-screenshot">
          <img src="/static/manual/screenshots/03_interactive_preset.png" alt="V2X preset 전환">
          <figcaption>시나리오 선택 + V2X preset 적용 후 BEV</figcaption>
        </figure>
        <h3>사용 절차</h3>
        <ol>
          <li>시나리오 드롭다운에서 평가 대상 선택</li>
          <li>카메라 영상 + 기본 BEV 자동 표출</li>
          <li>V2X preset 버튼 (예: <code>Turn left in 30m</code>) 클릭 → BEV 즉시 갱신</li>
          <li>여러 preset을 순서대로 클릭하며 BEV 차이 관찰</li>
        </ol>
        <h3>결과 해석</h3>
        <ul>
          <li>preset 전환 시 BEV 궤적이 메시지 거리/방향에 정합하면 V2X 효과 시각 확인.</li>
          <li>preset 간 차이가 없으면 모델이 V2X에 둔감하거나 시나리오가 V2X 무관.</li>
        </ul>
        <h3>자주 묻는 질문</h3>
        <dl class="guide-faq">
          <dt>Q. preset 클릭해도 BEV가 변하지 않습니다.</dt>
          <dd>A. 일부 시나리오는 V2X 효과가 미미할 수 있습니다. ① 탭에서 정량 메트릭으로 추가 확인 권장.</dd>
        </dl>
      </section>

      <section id="guide-5" class="guide-section">
        <h2>5. ④ VQA — 시각 질의응답 (라이브)</h2>
        <p class="guide-purpose">
          Alpamayo 1.5의 VLM 부분(Cosmos-Reason2 8B)에 주행 장면에 대해 자유 질문을 던지면 30~40초 후 응답 표출.
          Dual-mode 모델 — 질문 유형에 따라 자연어 / bbox 좌표 응답이 자동 결정됨.
        </p>
        <figure class="guide-screenshot">
          <img src="/static/manual/screenshots/04_vqa_initial.png" alt="초기">
          <figcaption>초기: 시나리오 드롭다운 + 가이드 표</figcaption>
        </figure>
        <figure class="guide-screenshot">
          <img src="/static/manual/screenshots/04_vqa_question.png" alt="질문 입력">
          <figcaption>시나리오 선택 + 질문 입력 후</figcaption>
        </figure>
        <figure class="guide-screenshot">
          <img src="/static/manual/screenshots/04_vqa_answer.png" alt="라이브 응답">
          <figcaption>라이브 VQA 응답</figcaption>
        </figure>
        <h3>사용 절차</h3>
        <ol>
          <li>시나리오 드롭다운에서 장면 선택 → 카메라 영상 표출</li>
          <li>가이드 표를 참고해 질문 입력 (자연어 응답이 보장된 질문 권장)</li>
          <li><strong>"▶ 질문"</strong> 클릭 → 30~40초 대기 → 응답 표출</li>
        </ol>
        <h3>결과 해석</h3>
        <ul>
          <li><strong>자연어 응답</strong>: "맑은 날씨, 평탄한 아스팔트…" 형태. 날씨/조명/도로 속성 질문이 트리거.</li>
          <li><strong>bbox 좌표</strong>: <code>[0.303, 0.221, 0.589, 0.674]</code> 형태. 장면/객체/사건 질문이 트리거 (객체 감지 모드).</li>
          <li>모드는 모델 내부에서 결정. 프롬프트로 강제 불가.</li>
        </ul>
        <h3>자주 묻는 질문</h3>
        <dl class="guide-faq">
          <dt>Q. <code>Describe the scene.</code>에 좌표만 나옵니다.</dt>
          <dd>A. 정상 동작. 장면/객체 질문은 객체 감지 모드를 트리거. 자연어 응답을 원하면 <code>Describe the road and weather.</code> 같은 속성 질문 사용.</dd>
          <dt>Q. 응답이 너무 느립니다.</dt>
          <dd>A. VLM 추론은 1회 ~30초가 정상. 캐시되지 않은 라이브 추론입니다.</dd>
        </dl>
      </section>

      <section id="guide-6" class="guide-section">
        <h2>6. ⑤ 카메라 입력 개수 평가</h2>
        <p class="guide-purpose">
          동일 시나리오에 카메라 입력을 1/2/4개 구성으로 변경해 추론, 센서 일부 고장 / 비용 절감 / 강건성 평가.
        </p>
        <figure class="guide-screenshot">
          <img src="/static/manual/screenshots/05_cam_count_initial.png" alt="초기">
          <figcaption>초기: 시나리오 드롭다운</figcaption>
        </figure>
        <figure class="guide-screenshot">
          <img src="/static/manual/screenshots/05_cam_count_result.png" alt="결과">
          <figcaption>1/2/4cam 구성별 BEV + 메트릭 비교</figcaption>
        </figure>
        <h3>사용 절차</h3>
        <ol>
          <li>시나리오 드롭다운에서 평가 대상 선택</li>
          <li>1cam / 2cam / 4cam 각 구성의 BEV 이미지 + Chain-of-Thought + 메트릭 표 자동 표출</li>
        </ol>
        <h3>결과 해석</h3>
        <ul>
          <li><strong>cam 수가 늘수록 ADE/FDE 감소</strong>면 다중 카메라 효과 정상.</li>
          <li>1cam에서 ADE > 5m 등 극단 수치면 단일 센서 한계 시연.</li>
          <li>2cam vs 4cam 차이가 작으면 후방/측면 카메라 보조 효과 제한적.</li>
        </ul>
        <h3>자주 묻는 질문</h3>
        <dl class="guide-faq">
          <dt>Q. CoT 텍스트가 동일합니다.</dt>
          <dd>A. 시나리오가 단순하면 추론 근거가 같을 수 있음. 다른 시나리오로 비교 권장.</dd>
        </dl>
      </section>

      <section id="guide-7" class="guide-section">
        <h2>7. ⑥ NRE Closed-Loop 시뮬레이션 분석</h2>
        <p class="guide-purpose">
          NVIDIA Neural Reconstruction Engine으로 6대 카메라를 신경망 재합성하며 매 step
          Alpamayo↔물리↔컨트롤러가 RPC로 사이클을 도는 closed-loop 시뮬레이션 결과 재생.
          시연 자리에서는 사전 렌더링된 영상 + trace + 메트릭 + PDF.
        </p>
        <figure class="guide-screenshot">
          <img src="/static/manual/screenshots/06_closedloop_initial.png" alt="초기">
          <figcaption>초기: rollout 드롭다운</figcaption>
        </figure>
        <figure class="guide-screenshot">
          <img src="/static/manual/screenshots/06_closedloop_loaded.png" alt="rollout 선택 후">
          <figcaption>rollout 선택 후 — NRE 합성 영상 + 메트릭 plot + step trace</figcaption>
        </figure>
        <h3>사용 절차</h3>
        <ol>
          <li>rollout 드롭다운에서 분석 대상 선택</li>
          <li>최상단에 NRE 합성 영상 (front_wide 120fov + V2X/메트릭/속도 오버레이) 자동 재생</li>
          <li>아래로 스크롤 → 시뮬 시간/속도/측방 가속 plot + step-by-step trace slider</li>
          <li>"📷 frames 추출" / "📄 PDF 생성" 버튼으로 보조 자료 생성 (선택)</li>
        </ol>
        <h3>결과 해석</h3>
        <ul>
          <li>NRE 영상은 매 step 신경망 재합성된 실제 시뮬 데이터.</li>
          <li>속도/측방 가속 plot이 안정적이면 controller가 정상 작동.</li>
          <li>jerk가 큰 시점이 있으면 급제동/급조작 → 사고 회피 또는 모델 불안정 흔적.</li>
        </ul>
        <h3>자주 묻는 질문</h3>
        <dl class="guide-faq">
          <dt>Q. rollout 선택 시 "영상 미생성" 안내가 나옵니다.</dt>
          <dd>A. 해당 rollout의 NRE frame 데이터가 누락. 운영자 호출.</dd>
          <dt>Q. 폐루프 시뮬을 새로 돌릴 수 있나요?</dt>
          <dd>A. ① 탭의 "Closed-Loop 시뮬레이션 실행" 버튼으로 가능하나 단일 scene당 60~80분 소요. 시연 자리에서는 사전 렌더 결과 재생을 권장.</dd>
        </dl>
      </section>

      <section id="guide-8" class="guide-section">
        <h2>8. 트러블슈팅</h2>
        <p class="guide-purpose">평가위원이 자가 해결 가능한 일반적 상황.</p>
        <dl class="guide-faq">
          <dt>"모델이 아직 적재되지 않았습니다." 경고</dt>
          <dd>① 탭의 모델 적재 버튼 클릭 → 상태가 <code>ready</code>가 될 때까지 (~1분) 대기. 한 세션 내 1회만 필요.</dd>

          <dt>④ VQA 응답이 <code>[0.3, 0.5, ...]</code> 좌표만 나옴</dt>
          <dd>Dual-mode 모델의 정상 동작. 객체 감지 모드가 트리거된 것입니다. 자연어 응답이 필요하면 가이드 표의 "자연어 응답 보장 질문"을 참고.</dd>

          <dt>⑥ rollout 선택 시 "영상 미생성" 안내</dt>
          <dd>사전 렌더링이 누락된 rollout. 다른 rollout 선택 또는 운영자 호출.</dd>

          <dt>② 카메라 영상이 첫 프레임만 길게 멈춤</dt>
          <dd>시뮬 데이터가 짧을 때 정상 (Tab ②는 2 fps 슬로우 모션 7.5초). 다른 시나리오 선택.</dd>

          <dt>탭을 클릭해도 콘텐츠가 안 뜸</dt>
          <dd>브라우저 새로고침 (F5). 그래도 안 되면 운영자 호출.</dd>

          <dt>한글이 □□□로 깨져 보임</dt>
          <dd>브라우저에 한글 폰트가 없는 경우. 시스템 한글 폰트(Noto Sans KR / 맑은 고딕 등) 설치 후 재접속.</dd>
        </dl>
      </section>

    </article>
  </div>
</section>
```

- [ ] **Step 5: uvicorn 재시작 + 가이드 탭 응답 확인**

```bash
kill $(pgrep -f "python -u main.py") 2>/dev/null; sleep 2
cd /home/kadap/alpamayo-closedloop-demo/kadap-poc-v2 && nohup /home/kadap/alpamayo-closedloop-demo/alpasim/.venv/bin/python -u main.py > /tmp/uvicorn.log 2>&1 &
sleep 8
echo "=== / 접속 시 기본 탭 ==="
curl -s http://localhost:7861/ | grep -E "hx-get|tab/guide" | head -3
echo "=== /tab/guide 응답 ==="
curl -s http://localhost:7861/tab/guide | head -20
echo "=== nav 순서 ==="
curl -s http://localhost:7861/ | grep -oE "📖 사용 가이드|① 시나리오|⑥ NRE"
```

Expected:
- 기본 `<main>`이 `hx-get="/tab/guide"`
- `/tab/guide` 응답 첫 줄에 `<section class="card guide-page">` 포함
- nav에 가이드가 시나리오보다 먼저

- [ ] **Step 6: Commit**

```bash
cd /home/kadap/alpamayo-closedloop-demo
git add kadap-poc-v2/main.py kadap-poc-v2/templates/base.html kadap-poc-v2/templates/tab_guide.html
git commit -m "kadap-poc-v2: 사용 가이드 탭 (8 섹션, 16 캡처 임베드)

평가위원 첫 접속 자동 표출. 시작하기/평가 6탭/트러블슈팅 단일
페이지 + sticky toc. base.html hx-trigger 기본 탭을 guide로 전환.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: app.css 스타일 + end-to-end 검증 + push

**Files:**
- Modify: `kadap-poc-v2/static/app.css`

- [ ] **Step 1: app.css 끝에 가이드 스타일 추가**

`kadap-poc-v2/static/app.css` 끝(현재 233줄 이후)에 추가:

```css
/* ---------- 사용 가이드 탭 ---------- */
.guide-page {
  padding: 0;
}
.guide-layout {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 2rem;
  align-items: start;
}
.guide-toc {
  position: sticky;
  top: 1rem;
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 1rem 1.25rem;
  font-size: 0.9rem;
}
.guide-toc h3 {
  margin: 0 0 0.5rem;
  font-size: 0.95rem;
  color: var(--primary);
}
.guide-toc ol {
  margin: 0;
  padding-left: 1.25rem;
}
.guide-toc li { margin-bottom: 0.35rem; }
.guide-toc a {
  color: var(--fg);
  text-decoration: none;
}
.guide-toc a:hover {
  color: var(--primary);
  text-decoration: underline;
}

.guide-body { max-width: 900px; }

.guide-section {
  margin-bottom: 3rem;
  padding-bottom: 2rem;
  border-bottom: 1px solid var(--border);
}
.guide-section:last-child { border-bottom: none; }
.guide-section h2 {
  color: var(--primary);
  margin-top: 0;
  scroll-margin-top: 1rem;
}
.guide-section h3 {
  margin-top: 1.5rem;
  font-size: 1rem;
  color: var(--primary);
}

.guide-purpose {
  background: #fff7e6;
  border-left: 3px solid var(--accent);
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
}

.guide-screenshot {
  margin: 1.25rem 0;
  text-align: center;
}
.guide-screenshot img {
  max-width: 100%;
  border: 1px solid var(--border);
  border-radius: 4px;
  box-shadow: 0 2px 6px rgba(0,0,0,0.05);
}
.guide-screenshot figcaption {
  font-size: 0.85rem;
  color: var(--muted);
  margin-top: 0.4rem;
}

.guide-faq dt {
  font-weight: 600;
  margin-top: 0.75rem;
}
.guide-faq dd {
  margin-left: 1rem;
  color: var(--fg);
}

@media (max-width: 900px) {
  .guide-layout {
    grid-template-columns: 1fr;
  }
  .guide-toc {
    position: static;
  }
}
```

- [ ] **Step 2: uvicorn 재시작 + 시각 검증**

(uvicorn은 일반적으로 정적 파일 변경 즉시 반영, 재시작 불필요. 한 번 강제 확인)
```bash
curl -sI http://localhost:7861/static/app.css | head -3
curl -s http://localhost:7861/static/app.css | grep -c "guide-toc"
```
Expected: 200 OK + `guide-toc` 매치 > 0.

- [ ] **Step 3: 캡처 정적 서빙 확인**

```bash
curl -sI http://localhost:7861/static/manual/screenshots/landing.png | head -3
curl -sI http://localhost:7861/static/manual/screenshots/06_closedloop_loaded.png | head -3
```
Expected: 둘 다 `HTTP/1.1 200 OK`.

- [ ] **Step 4: 가이드 페이지 렌더 시각 검증**

별도 캡처로 가이드 페이지 자체를 캡쳐해 사용자에게 전달 (controller):
```bash
scripts/manual_capture/.venv/bin/python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    p = b.new_context(viewport={'width':1440,'height':900}, locale='ko-KR').new_page()
    p.goto('http://localhost:7861/', wait_until='networkidle')
    p.wait_for_timeout(1500)
    p.screenshot(path='/tmp/guide_page.png', full_page=True)
    b.close()
print('saved /tmp/guide_page.png')
"
ls -la /tmp/guide_page.png
```
Expected: 1440 wide, full_page (높이는 콘텐츠 길이만큼).

- [ ] **Step 5: Commit**

```bash
cd /home/kadap/alpamayo-closedloop-demo
git add kadap-poc-v2/static/app.css
git commit -m "kadap-poc-v2: 사용 가이드 탭 CSS — sticky toc + 섹션 + 캡처 스타일

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

- [ ] **Step 6: Push**

```bash
cd /home/kadap/alpamayo-closedloop-demo
git push origin main 2>&1 | tail -5
```

Expected: `main -> main` (no force, hooks pass).

---

## Self-Review

**Spec coverage (Sections 1-12 of spec):**

1. 목표 — Task 3 (탭) + Task 1-2 (캡처) + Task 4 (스타일) ✅
2. 비목표 — 운영자 매뉴얼/동영상/다국어/PDF/검색 모두 plan 범위 밖 ✅
3. 위치 & 라벨 — Task 3 Step 2-3 (nav + hx-trigger) ✅
4. 콘텐츠 구조 — Task 3 Step 4 tab_guide.html (8 섹션, 좌측 toc + 우측 body) ✅
5. 캡처 자동화 — Task 1 (venv + dry-run) + Task 2 (16장 일괄) ✅
   - 5.1 환경 — Task 1 Step 1-3 ✅
   - 5.2 캡처 스크립트 — Task 1 Step 4 + Task 2 Step 1-4 ✅
   - 5.3 16 캡처 — Task 2 Step 2-3 (16 함수 + targets) ✅
   - 5.4 파일 저장 — Task 2 Step 6 commit으로 git 추적 ✅
6. 가이드 페이지 UI — Task 4 (CSS) + Task 3 Step 4 (마크업) ✅
7. 데이터 흐름 — Task 3 Step 2-3 (hx-trigger), Task 3 Step 4 (앵커 링크) ✅
8. 에러 처리 — `<img>` 깨진 아이콘 fallback은 브라우저 기본 동작, plan에서 추가 코드 없음. 캡처 실패 시 Task 2 함수의 try/except가 stderr 출력. ✅
9. 파일 변경/신규 — File Structure 표 1:1 매핑 ✅
10. 테스트 — Task 1 Step 5 (dry-run) + Task 2 Step 5-6 (batch + 16장 확인) + Task 4 Step 3-4 (정적 서빙 + 렌더 캡처) ✅
11. 범위 — plan 어디에도 운영자 매뉴얼/검색/다국어/PDF 안 들어감 ✅
12. 소요 추정 — plan task별 step 수가 spec 추정 (~105분)에 부합 ✅

**Placeholder scan:** 모든 step에 실제 코드/명령. "TODO" / "TBD" / "fill in" 패턴 없음. tab_guide.html 콘텐츠는 8 섹션 모두 텍스트가 plan에 적힘 (subagent가 작성 시 추측 불필요). ✅

**Type consistency:** `cap_NN_xxx` 함수명 일관, `targets` 리스트와 함수명 1:1, `OUT_DIR` / `VIEWPORT` 변수명 Task 1 → Task 2 동일. CSS 클래스명 (`.guide-toc` / `.guide-section` / `.guide-screenshot` / `.guide-purpose` / `.guide-faq`) Task 3 마크업 / Task 4 CSS 사이 일관. ✅
