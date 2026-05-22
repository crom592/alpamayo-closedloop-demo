#!/usr/bin/env bash
# Bootstrap script for KADaP GPU server: prepares Alpasim + Alpamayo 1.5 closed-loop demo.
# Idempotent — safe to re-run.
#
# Assumes:
#   - Ubuntu 22.04 with Docker + NVIDIA Container Toolkit + nvidia-smi working
#   - Repo cloned to /data/alpamayo-closedloop-demo (or wherever pwd is)
#   - .env file present with HF_TOKEN set (copy from .env.example)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Loading .env"
if [[ ! -f .env ]]; then
  echo "ERROR: .env not found. Copy .env.example to .env and set HF_TOKEN." >&2
  exit 1
fi
set -a; source .env; set +a
if [[ -z "${HF_TOKEN:-}" ]]; then
  echo "ERROR: HF_TOKEN is empty in .env (needed for gated nvidia/Alpamayo-1.5-10B)" >&2
  exit 1
fi
export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
mkdir -p "$HF_HOME"

echo "==> Verifying GPU"
if ! command -v nvidia-smi >/dev/null; then
  echo "ERROR: nvidia-smi not on PATH — install NVIDIA driver" >&2
  exit 1
fi
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
gpu_mem_mb=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1 | tr -d ' ')
if (( gpu_mem_mb < 23000 )); then
  echo "WARN: GPU has ${gpu_mem_mb} MiB VRAM — Alpamayo 1.5 10B needs >= 24 GB. Closed-loop may OOM." >&2
fi

echo "==> Ensuring Docker is usable"
docker info >/dev/null || { echo "ERROR: docker daemon unreachable / no permission"; exit 1; }
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi -L \
  || { echo "ERROR: docker --gpus all failed. Check nvidia-container-toolkit."; exit 1; }

echo "==> Installing uv (if missing)"
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv --version

echo "==> Installing Rust toolchain (if missing) — needed by alpasim utils_rs"
if ! command -v cargo >/dev/null; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  source "$HOME/.cargo/env"
fi
cargo --version

echo "==> Initializing git submodules"
git submodule update --init --recursive

echo "==> Applying overlay (V2X demo files → alpamayo1.5/notebooks/)"
overlay_src="$REPO_ROOT/overlay/alpamayo1.5/notebooks"
overlay_dst="$REPO_ROOT/alpamayo1.5/notebooks"
mkdir -p "$overlay_dst"
for f in "$overlay_src"/*.py; do
  name="$(basename "$f")"
  ln -sfn "$f" "$overlay_dst/$name"
done
echo "  symlinked $(ls "$overlay_src"/*.py | wc -l) overlay files"

echo "==> Bootstrapping Alpasim environment (compiles protos, installs alpasim_wizard)"
pushd "$REPO_ROOT/alpasim" >/dev/null
# shellcheck disable=SC1091
source ./setup_local_env.sh
popd >/dev/null

echo "==> Pre-pulling HuggingFace models (Alpamayo 1.5 10B + Cosmos-Reason2-8B, ~30 GB total)"
echo "    This step can take 20-40 min depending on bandwidth."
huggingface-cli download nvidia/Alpamayo-1.5-10B --resume-download
huggingface-cli download nvidia/Cosmos-Reason2-8B --resume-download

echo ""
echo "==> Setup complete."
echo "    Next:"
echo "      bash scripts/run_closedloop.sh   # starts Alpasim wizard + docker compose stack"
echo "      bash scripts/run_dashboard.sh    # serves the closed-loop dashboard on :${DASHBOARD_PORT:-7860}"
