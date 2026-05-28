#!/usr/bin/env bash
#
# Launch the KADaP PoC Gradio frontend on top of the daemon-mode Alpasim
# runtime. Expects scripts/run_closedloop.sh + patch_compose_for_daemon.py to
# have been run already and the compose stack to be `docker compose up -d`.
#
# The frontend re-uses the alpasim host venv (which already has alpasim_grpc,
# gradio, reportlab installed).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PY="$REPO_ROOT/alpasim/.venv/bin/python"
APP="$REPO_ROOT/kadap-poc/app.py"
PORT="${KADAP_POC_PORT:-7870}"
HOST="${KADAP_POC_HOST:-0.0.0.0}"

if [[ ! -x "$VENV_PY" ]]; then
  echo "missing $VENV_PY — run scripts/setup.sh first" >&2
  exit 1
fi

if ! "$VENV_PY" -c "import gradio, alpasim_grpc" 2>/dev/null; then
  echo "==> installing missing python deps into alpasim venv"
  (cd "$REPO_ROOT/alpasim" && uv pip install gradio reportlab)
fi

echo "==> daemon TCP probe (127.0.0.1:50051) — optional in PoC v0 (one-shot mode)"
if timeout 3 bash -c '</dev/tcp/127.0.0.1/50051' 2>/dev/null; then
  echo "  daemon up. Daemon-mode client (client.py) available — but blocked by"
  echo "  upstream cu_seqlens_q bug, so the UI still uses one-shot compose."
else
  echo "  daemon not running — fine, PoC v0 uses one-shot runs orchestrated by"
  echo "  kadap-poc/runner.py via scripts/run_closedloop.sh per simulation."
fi

echo "==> launching Gradio on ${HOST}:${PORT}"
# Direct exec — the foreground process is what `bash scripts/run_kadap_poc.sh`
# users expect. For background use, prefix with nohup:
#   nohup bash scripts/run_kadap_poc.sh > /tmp/kadap-poc.log 2>&1 < /dev/null &
KADAP_POC_HOST="$HOST" KADAP_POC_PORT="$PORT" exec "$VENV_PY" "$APP"
