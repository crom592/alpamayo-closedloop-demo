#!/usr/bin/env python3
"""Capture KATECH demo UI screenshots via Playwright for the 사용 가이드 tab.

Connects to a running uvicorn (default http://localhost:7861), navigates each
tab, waits for content to settle, and saves PNGs to
kadap-poc-v2/static/manual/screenshots/.

Run with: scripts/manual_capture/.venv/bin/python scripts/manual_capture/capture.py
"""
from __future__ import annotations

import argparse
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright, Page

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = REPO_ROOT / "kadap-poc-v2" / "static" / "manual" / "screenshots"
VIEWPORT = {"width": 1440, "height": 900}


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


def capture_landing(page: Page, base_url: str, out: Path) -> None:
    page.goto(base_url, wait_until="networkidle")
    page.wait_for_timeout(800)
    page.screenshot(path=str(out), full_page=False)


# --- Tab ① 시나리오 단건 평가 ---
def cap_01_initial(page, base_url, out):
    goto_tab(page, base_url, "scenario_eval")
    page.screenshot(path=str(out))


def cap_01_input(page, base_url, out):
    goto_tab(page, base_url, "scenario_eval")
    page.select_option('select[name="scenario_idx"]', "5")
    page.wait_for_timeout(500)
    page.screenshot(path=str(out))


def cap_01_result(page, base_url, out):
    goto_tab(page, base_url, "scenario_eval")
    page.select_option('select[name="scenario_idx"]', "0")
    page.wait_for_timeout(300)
    page.click('button:has-text("▶ 3조건 단일 추론 실행")')
    page.wait_for_selector("#se-result img, #se-result .error, #se-result table", timeout=180000)
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
    page.wait_for_selector("#int-loaded video, #int-loaded button", timeout=10000)
    page.wait_for_timeout(800)
    btn = page.locator("#int-loaded button").first
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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://localhost:7861")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", help="Capture only this name (substring match)")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=== Ensuring Alpamayo model loaded (Tab ① /scenario_eval/load_model) ===")
    ensure_model_loaded(args.url)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport=VIEWPORT, locale="ko-KR")
        page = ctx.new_page()

        targets = [
            ("landing",                    capture_landing),
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
