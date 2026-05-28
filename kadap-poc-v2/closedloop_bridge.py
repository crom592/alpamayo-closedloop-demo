"""Bridge between v2 UI and Alpasim closed-loop with V2X nav_text injection.

`run_closedloop_with_v2x` wraps `kadap-poc/runner.run_oneshot` to:
    1. Set NAV_TEXT env so scripts/run_closedloop.sh propagates it to driver-0
    2. Optionally narrow to a single scene_id
    3. Stream progress back to the caller

End-to-end:
  v2 UI Tab ① → POST /closedloop/run {scene_id, v2x_text}
  → here → NAV_TEXT=<v2x> bash scripts/run_closedloop.sh
  → wizard + patcher injects KADAP_NAV_TEXT into driver-0 environment
  → driver Session.create reads env → session.nav_text
  → PredictionInput.nav_text → helper.create_message(..., nav_text=...)
  → Alpamayo VLM conditions on the V2X instruction
  → rollout.asl saved → v2 polls latest_rollout
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "kadap-poc"))

from runner import RolloutRef, run_oneshot  # noqa: E402


def run_closedloop_with_v2x(
    v2x_text: str,
    scene_id: str | None = None,
    on_progress: Callable[[float, str], None] | None = None,
    ablation_name: str = "base",
) -> RolloutRef:
    """Block-run a closed-loop simulation with V2X conditioning.

    ``v2x_text`` is propagated to driver-0 as KADAP_NAV_TEXT env via the
    patcher hook in `scripts/patch_compose_for_daemon.py`. Stays the same
    for the entire session.
    """
    prior = os.environ.get("NAV_TEXT")
    os.environ["NAV_TEXT"] = v2x_text or ""
    try:
        rollout = run_oneshot(
            driver="alpamayo1_5",
            on_progress=on_progress,
            scene_ids=[scene_id] if scene_id else None,
            ablation=None,  # NAV_TEXT is the only condition; no camera mask
        )
    finally:
        if prior is None:
            os.environ.pop("NAV_TEXT", None)
        else:
            os.environ["NAV_TEXT"] = prior

    # Stamp the rollout meta with the V2X text so UIs can show it.
    meta_path = rollout.dir / "kadap_meta.json"
    if meta_path.exists():
        import json

        meta = json.loads(meta_path.read_text())
        meta["v2x_text"] = v2x_text
        meta_path.write_text(json.dumps(meta, indent=2))
    return rollout
