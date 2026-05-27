"""One-shot simulation orchestrator for the KADaP PoC.

PoC v0 reuses ``scripts/run_closedloop.sh`` to (re)bring the Alpasim stack
up per simulation. The daemon-mode gRPC path in ``client.py`` is retained
but unused — see Task #16 (upstream driver bug ``cu_seqlens_q must have
shape (batch_size + 1)`` on daemon path).

Each :func:`run_oneshot` invocation:
    1. compose down (kill any prior run)
    2. ``run_closedloop.sh`` — wizard + patcher (--no-daemon) + ``compose up -d``
    3. poll ``rollouts/`` for a newly-created scene/uuid directory
    4. wait for ``rollout.asl`` to stop growing (simulation finished)

End-to-end cost is ~10–15 min on an A40 (model load dominates).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_DIR = REPO_ROOT / "alpasim" / "alpasim" / "run_dir"
ROLLOUTS_DIR = RUN_DIR / "rollouts"
COMPOSE_FILE = RUN_DIR / "docker-compose.yaml"
RUN_CLOSEDLOOP = REPO_ROOT / "scripts" / "run_closedloop.sh"
VENV_PY = REPO_ROOT / "alpasim" / ".venv" / "bin" / "python"

OVERALL_TIMEOUT_S = 1800
ASL_STABLE_CHECKS = 3
POLL_INTERVAL_S = 10


KADAP_META = "kadap_meta.json"


@dataclass
class RolloutRef:
    scenario_id: str
    rollout_uuid: str
    dir: Path

    @property
    def asl(self) -> Path:
        return self.dir / "rollout.asl"

    @property
    def meta(self) -> dict:
        p = self.dir / KADAP_META
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return {}

    @property
    def driver(self) -> str:
        # explicit marker wins; otherwise unknown (pre-PoC rollouts have no marker)
        return self.meta.get("driver", "unknown")


def _write_meta(rollout: RolloutRef, driver: str) -> None:
    """Stamp the kadap_meta.json so downstream UIs know which policy ran."""
    payload = {
        "driver": driver,
        "scenario_id": rollout.scenario_id,
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    (rollout.dir / KADAP_META).write_text(json.dumps(payload, indent=2))


def existing_rollouts() -> list[RolloutRef]:
    """All rollouts with a completed (non-empty) rollout.asl on disk."""
    out: list[RolloutRef] = []
    if not ROLLOUTS_DIR.exists():
        return out
    for scn in sorted(ROLLOUTS_DIR.iterdir()):
        if not scn.is_dir():
            continue
        for r in scn.iterdir():
            asl = r / "rollout.asl"
            if asl.exists() and asl.stat().st_size > 0:
                out.append(RolloutRef(scn.name, r.name, r))
    out.sort(key=lambda r: r.dir.stat().st_mtime, reverse=True)
    return out


def render_camera_mp4(rollout: RolloutRef, timeout: int = 300) -> Path | None:
    """Convert rollout.asl → camera mp4 via ``alpasim_utils.asl_to_frames``."""
    frames_dir = rollout.dir / "rollout_asl_frames"
    if not frames_dir.exists() and rollout.asl.exists():
        subprocess.run(
            [
                str(VENV_PY),
                "-m",
                "alpasim_utils.asl_to_frames",
                str(rollout.asl),
                "--format",
                "mp4",
            ],
            check=False,
            capture_output=True,
            timeout=timeout,
        )
    if not frames_dir.exists():
        return None
    mp4s = sorted(frames_dir.rglob("*.mp4"))
    return mp4s[0] if mp4s else None


def _compose_down() -> None:
    if not COMPOSE_FILE.exists():
        return
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "down"],
        check=False,
        capture_output=True,
        timeout=120,
    )


def _start_wizard_and_compose(driver: str, scene_ids: list[str] | None = None) -> None:
    if not shutil.which("bash"):
        raise RuntimeError("bash not on PATH")
    env = {**os.environ, "DRIVER": driver}
    if scene_ids:
        # Hydra list override syntax for wizard.scenes.scene_ids
        env["SCENE_IDS"] = "[" + ",".join(scene_ids) + "]"
    subprocess.run(
        ["bash", str(RUN_CLOSEDLOOP)],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        timeout=300,  # wizard + compose up -d returns immediately after detach
    )


def _wait_for_new_rollout(
    pre_existing: set[tuple[str, str]],
    on_progress: Callable[[float, str], None] | None,
    overall_deadline: float,
) -> RolloutRef:
    """Poll rollouts/ until a directory not in pre_existing appears."""
    while time.time() < overall_deadline:
        for r in existing_rollouts():
            if (r.scenario_id, r.rollout_uuid) not in pre_existing:
                return r
        # Also accept just-created dirs without a finalised .asl yet
        if ROLLOUTS_DIR.exists():
            for scn in ROLLOUTS_DIR.iterdir():
                for r_dir in scn.iterdir():
                    if (scn.name, r_dir.name) in pre_existing:
                        continue
                    if r_dir.is_dir():
                        return RolloutRef(scn.name, r_dir.name, r_dir)
        elapsed = OVERALL_TIMEOUT_S - (overall_deadline - time.time())
        if on_progress:
            on_progress(
                min(0.4, 0.1 + elapsed / 900),
                f"driver 모델 적재 + 시뮬 시작 대기… ({int(elapsed)}s)",
            )
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError("새 rollout 디렉토리가 시간 내에 생성되지 않음")


def _wait_for_rollout_finalised(
    rollout: RolloutRef,
    on_progress: Callable[[float, str], None] | None,
    overall_deadline: float,
) -> None:
    last_size = -1
    stable = 0
    started = time.time()
    while time.time() < overall_deadline:
        size = rollout.asl.stat().st_size if rollout.asl.exists() else 0
        if size > 0 and size == last_size:
            stable += 1
            if stable >= ASL_STABLE_CHECKS:
                return
        else:
            stable = 0
            last_size = size
        elapsed = time.time() - started
        if on_progress:
            on_progress(
                min(0.95, 0.4 + elapsed / 600),
                f"시뮬 진행 중 — rollout.asl {size / 1024 / 1024:.1f} MB",
            )
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError("rollout.asl 크기가 안정되지 않음 (시뮬 미완)")


def run_oneshot(
    driver: str = "alpamayo1_5",
    on_progress: Callable[[float, str], None] | None = None,
    scene_ids: list[str] | None = None,
) -> RolloutRef:
    """Trigger a one-shot simulation. Blocking; ~10–15 min on A40.

    Args:
        driver: wizard driver name (alpamayo1_5 / vavam / manual / alpamayo1).
        on_progress: optional ``(pct, status)`` callback for UI feedback.
        scene_ids: optional list of catalog scene_ids; defaults to the
            wizard's built-in default (single 1.5s OSS clip) when None.

    Returns the new RolloutRef once rollout.asl is finalised.
    """
    if on_progress:
        on_progress(0.02, "이전 컨테이너 정리…")
    _compose_down()

    if on_progress:
        on_progress(0.05, f"wizard + compose up (driver={driver})…")
    pre = {(r.scenario_id, r.rollout_uuid) for r in existing_rollouts()}
    _start_wizard_and_compose(driver, scene_ids=scene_ids)

    if on_progress:
        on_progress(0.10, "컨테이너 기동 완료, 첫 rollout 생성 대기 중…")
    deadline = time.time() + OVERALL_TIMEOUT_S
    new_rollout = _wait_for_new_rollout(pre, on_progress, deadline)

    _wait_for_rollout_finalised(new_rollout, on_progress, deadline)
    _write_meta(new_rollout, driver)

    if on_progress:
        on_progress(1.0, f"✅ 완료 — uuid={new_rollout.rollout_uuid}")
    return new_rollout


def latest_rollout_for(scenario_id: str, driver: str) -> RolloutRef | None:
    """Most recent rollout for the (scenario, driver) pair, or None."""
    for r in existing_rollouts():
        if r.scenario_id == scenario_id and r.driver == driver:
            return r
    return None


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--driver", default="alpamayo1_5")
    p.add_argument("--scene-id", action="append", help="repeatable scene_id override")
    p.add_argument("--list", action="store_true")
    p.add_argument(
        "--backfill-driver",
        metavar="NAME",
        help="stamp every existing rollout missing kadap_meta.json with this driver",
    )
    args = p.parse_args()
    if args.list:
        for r in existing_rollouts():
            print(f"{r.scenario_id}/{r.rollout_uuid}  driver={r.driver}  ({r.dir})")
    elif args.backfill_driver:
        n = 0
        for r in existing_rollouts():
            if not (r.dir / KADAP_META).exists():
                _write_meta(r, args.backfill_driver)
                print(f"stamped {r.rollout_uuid[:8]}…  driver={args.backfill_driver}")
                n += 1
        print(f"backfilled {n} rollouts")
    else:
        out = run_oneshot(
            args.driver,
            on_progress=lambda pct, msg: print(f"[{pct:.0%}] {msg}"),
            scene_ids=args.scene_id,
        )
        print(f"DONE: {out.dir}")
