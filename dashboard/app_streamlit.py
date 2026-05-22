"""Closed-loop dashboard for Alpamayo + Alpasim NRE demo.

Tails docker logs from the Alpasim wizard stack, lists the most recent rollout
videos under $RUN_DIR/rollouts/, and shows compose service health + GPU metrics.

Mounts expected when run in container:
  - /var/run/docker.sock  (to query docker on the host)
  - $RUN_DIR              (read-only, contains rollouts/)
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import streamlit as st

RUN_DIR = Path(os.environ.get("RUN_DIR", "/run_dir"))
ROLLOUTS_DIR = RUN_DIR / "rollouts"
EXPECTED_SERVICES = ["controller-0", "driver-0", "physics-0", "trafficsim-0", "nre-0"]

st.set_page_config(
    page_title="Alpamayo Closed-Loop",
    page_icon="🚗",
    layout="wide",
)


def _run(cmd: list[str], timeout: int = 5) -> str:
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return out.stdout + out.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return f"<<error: {e}>>"


def docker_ps_status() -> dict[str, dict]:
    """Returns {container_name: {state, health, image, started_at}}."""
    raw = _run(
        ["docker", "ps", "-a", "--format", "{{json .}}"],
        timeout=8,
    )
    services: dict[str, dict] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            info = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = info.get("Names", "")
        for svc in EXPECTED_SERVICES:
            if svc in name:
                services[svc] = {
                    "state": info.get("State", "?"),
                    "status": info.get("Status", "?"),
                    "image": info.get("Image", "?"),
                    "container": name,
                }
                break
    return services


def docker_logs(container_substr: str, tail: int = 200) -> str:
    name = _resolve_container(container_substr)
    if not name:
        return f"(container matching '{container_substr}' not found)"
    return _run(["docker", "logs", "--tail", str(tail), name], timeout=10)


def _resolve_container(substr: str) -> str | None:
    raw = _run(["docker", "ps", "-a", "--format", "{{.Names}}"], timeout=5)
    for n in raw.splitlines():
        if substr in n:
            return n.strip()
    return None


def list_rollouts(limit: int = 12) -> list[Path]:
    if not ROLLOUTS_DIR.exists():
        return []
    mp4s = sorted(
        ROLLOUTS_DIR.rglob("*.mp4"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return mp4s[:limit]


def gpu_metrics() -> list[dict]:
    raw = _run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
            "--format=csv,noheader,nounits",
        ],
        timeout=5,
    )
    rows: list[dict] = []
    for line in raw.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 6:
            continue
        rows.append(
            {
                "idx": parts[0],
                "name": parts[1],
                "util_pct": parts[2],
                "mem_used_mib": parts[3],
                "mem_total_mib": parts[4],
                "temp_c": parts[5],
            }
        )
    return rows


# ---------------- UI ----------------

st.title("🚗 Alpamayo 1.5 × Alpasim NRE — Closed-Loop Demo")
st.caption(
    f"RUN_DIR={RUN_DIR}  •  Watching {len(EXPECTED_SERVICES)} services  •  "
    f"Refresh manually with the sidebar control."
)

with st.sidebar:
    st.header("Controls")
    auto = st.checkbox("Auto-refresh every 10s", value=True)
    tail_n = st.slider("Log tail lines", 50, 1000, 200, step=50)
    rollout_n = st.slider("Rollout gallery size", 4, 24, 8, step=2)
    if st.button("Refresh now"):
        st.rerun()

services = docker_ps_status()
gpus = gpu_metrics()

# --- Service health row ---
st.subheader("Service health")
cols = st.columns(len(EXPECTED_SERVICES))
for col, svc in zip(cols, EXPECTED_SERVICES):
    info = services.get(svc)
    if info is None:
        col.metric(svc, "missing", help="container not found")
    else:
        state = info["state"]
        emoji = "🟢" if state == "running" and "healthy" in info["status"] else (
            "🟡" if state == "running" else "🔴"
        )
        col.metric(svc, f"{emoji} {state}", info["status"][:30])

# --- GPU metrics ---
st.subheader("GPU")
if not gpus:
    st.warning("nvidia-smi unavailable (check NVIDIA Container Toolkit + --gpus all)")
else:
    gpu_cols = st.columns(len(gpus))
    for col, g in zip(gpu_cols, gpus):
        try:
            mem_used = int(g["mem_used_mib"])
            mem_total = int(g["mem_total_mib"])
            mem_pct = 100 * mem_used / max(mem_total, 1)
        except ValueError:
            mem_pct = 0
        col.metric(
            f"GPU{g['idx']} {g['name'][:18]}",
            f"{g['util_pct']}% util",
            f"VRAM {g['mem_used_mib']}/{g['mem_total_mib']} MiB ({mem_pct:.0f}%)  •  {g['temp_c']}°C",
        )

# --- Tabs: logs + rollouts ---
tab_logs, tab_rollouts, tab_files = st.tabs(
    ["📜 Live logs", "🎞️ Rollouts", "📁 RUN_DIR tree"]
)

with tab_logs:
    log_cols = st.columns(2)
    with log_cols[0]:
        st.markdown("**controller-0** — episode/step orchestration")
        st.code(docker_logs("controller-0", tail=tail_n) or "(empty)", language="text")
    with log_cols[1]:
        st.markdown("**driver-0** — Alpamayo 1.5 inference")
        st.code(docker_logs("driver-0", tail=tail_n) or "(empty)", language="text")
    st.markdown("---")
    nre_cols = st.columns(2)
    with nre_cols[0]:
        st.markdown("**nre-0** — neural rendering")
        st.code(docker_logs("nre-0", tail=tail_n) or "(empty)", language="text")
    with nre_cols[1]:
        st.markdown("**physics-0** — vehicle dynamics")
        st.code(docker_logs("physics-0", tail=tail_n) or "(empty)", language="text")

with tab_rollouts:
    mp4s = list_rollouts(limit=rollout_n)
    if not mp4s:
        st.info(
            f"No rollout MP4s yet under {ROLLOUTS_DIR}. "
            "They appear once controller-0 completes its first episode."
        )
    else:
        st.caption(f"Showing {len(mp4s)} most recent rollouts (newest first)")
        for i in range(0, len(mp4s), 2):
            row = st.columns(2)
            for j, mp4 in enumerate(mp4s[i : i + 2]):
                with row[j]:
                    rel = mp4.relative_to(ROLLOUTS_DIR) if ROLLOUTS_DIR in mp4.parents else mp4
                    mtime = time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(mp4.stat().st_mtime)
                    )
                    st.markdown(f"**`{rel}`**  \nmodified: {mtime}")
                    st.video(str(mp4))

with tab_files:
    if not RUN_DIR.exists():
        st.warning(f"RUN_DIR {RUN_DIR} does not exist in this container.")
    else:
        top_level = sorted(p.name for p in RUN_DIR.iterdir())
        st.write(f"Top-level entries in `{RUN_DIR}`:")
        st.code("\n".join(top_level) or "(empty)", language="text")
        st.caption("Closed-loop stack writes here. `rollouts/` is the per-episode output.")

if auto:
    time.sleep(10)
    st.rerun()
