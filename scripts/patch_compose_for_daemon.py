#!/usr/bin/env python3
"""Patch wizard-generated compose + user-config for KADaP PoC operation.

Idempotent — safe to re-run after every ``alpasim_wizard`` invocation.

Always applies (both daemon and one-shot modes):
    - all services .environment →  HF_TOKEN, HUGGING_FACE_HUB_TOKEN, HF_HOME,
                                    HF_HUB_DISABLE_XET=1, DISABLE_KERNEL_MAPPING=1
    - user-config.endpoints.startup_timeout_s  →  1800

Daemon mode (default; pass --no-daemon to skip):
    - runtime-0.command  →  add  --serve --listen-address [::]:50051
    - runtime-0.ports    →  expose 50051 to host

NOTE: daemon-path driver inference currently crashes with
``RuntimeError: cu_seqlens_q must have shape (batch_size + 1)`` (upstream
bug, tracked in Task #16). PoC v0 uses --no-daemon and triggers one-shot
compose runs per simulation; the daemon scaffolding is retained for when
the upstream fix lands.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUN_DIR = REPO_ROOT / "alpasim" / "alpasim" / "run_dir"
DAEMON_LISTEN = "[::]:50051"
DAEMON_HOST_PORT = 50051
STARTUP_TIMEOUT_S = 1800

ENV_VARS_FOR_ALL_SERVICES = {
    "HF_HOME": "/root/.cache/huggingface",
    "HF_HUB_DISABLE_XET": "1",
    "DISABLE_KERNEL_MAPPING": "1",
}


def load_hf_token(env_file: Path) -> str:
    if not env_file.exists():
        sys.exit(f"missing {env_file}; copy from .env.example and set HF_TOKEN")
    for line in env_file.read_text().splitlines():
        if line.startswith("HF_TOKEN="):
            return line.split("=", 1)[1].strip()
    sys.exit(f"HF_TOKEN not found in {env_file}")


def patch_runtime_command(cmd_list: list[str]) -> list[str]:
    """Inject --serve + --listen-address into runtime-0 command if absent."""
    if not cmd_list or len(cmd_list) < 2 or cmd_list[0] != "-c":
        sys.exit(f"unexpected runtime-0 command shape: {cmd_list!r}")
    script = cmd_list[1]
    if "--serve" in script:
        return cmd_list
    flags = f" --serve --listen-address {DAEMON_LISTEN}"
    new_script = script.rstrip() + flags
    return ["-c", new_script]


def patch_compose(path: Path, hf_token: str, daemon: bool) -> None:
    data = yaml.safe_load(path.read_text())
    services = data.get("services") or {}

    for name, svc in services.items():
        env = svc.get("environment") or {}
        if isinstance(env, list):
            env = dict(kv.split("=", 1) for kv in env if "=" in kv)
        env["HF_TOKEN"] = hf_token
        env["HUGGING_FACE_HUB_TOKEN"] = hf_token
        env.update(ENV_VARS_FOR_ALL_SERVICES)
        svc["environment"] = env

    if daemon:
        runtime = services.get("runtime-0")
        if runtime is None:
            sys.exit("services.runtime-0 missing from compose YAML")
        runtime["command"] = patch_runtime_command(runtime.get("command") or [])
        ports = runtime.get("ports") or []
        spec = f"{DAEMON_HOST_PORT}:{DAEMON_HOST_PORT}"
        if spec not in ports:
            ports.append(spec)
        runtime["ports"] = ports

    path.write_text(yaml.safe_dump(data, sort_keys=False))


def patch_user_config(path: Path) -> None:
    data = yaml.safe_load(path.read_text())
    endpoints = data.setdefault("endpoints", {})
    endpoints["startup_timeout_s"] = STARTUP_TIMEOUT_S
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=DEFAULT_RUN_DIR,
        help=f"wizard.log_dir contents (default: {DEFAULT_RUN_DIR})",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=REPO_ROOT / ".env",
        help="dotenv with HF_TOKEN (default: <repo>/.env)",
    )
    parser.add_argument(
        "--no-daemon",
        dest="daemon",
        action="store_false",
        help="skip --serve injection; produce a one-shot compose (PoC default)",
    )
    parser.set_defaults(daemon=True)
    args = parser.parse_args()

    compose = args.run_dir / "docker-compose.yaml"
    user_cfg = args.run_dir / "generated-user-config-0.yaml"
    if not compose.exists():
        sys.exit(f"missing {compose}; run alpasim_wizard first")
    if not user_cfg.exists():
        sys.exit(f"missing {user_cfg}; run alpasim_wizard first")

    hf_token = load_hf_token(args.env_file)
    patch_compose(compose, hf_token, daemon=args.daemon)
    patch_user_config(user_cfg)

    print(f"patched {compose.relative_to(REPO_ROOT)}")
    if args.daemon:
        print(f"  + runtime-0 --serve on host port {DAEMON_HOST_PORT}")
    else:
        print(f"  + one-shot mode (no --serve)")
    print(f"  + HF token / xet / kernel env on all services")
    print(f"patched {user_cfg.relative_to(REPO_ROOT)}")
    print(f"  + endpoints.startup_timeout_s = {STARTUP_TIMEOUT_S}")


if __name__ == "__main__":
    main()
