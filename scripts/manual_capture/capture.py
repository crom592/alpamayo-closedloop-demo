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
