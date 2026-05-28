#!/usr/bin/env bash
# Build the demo_cache that Tab ③/④/⑤ depend on, using KADaP's host venv.
#
# The original POC ran inside `alpamayo-poc` docker on ARM. On KADaP A40 we
# just run host-side because the alpasim venv already has all of
# alpamayo1_5 / physical_ai_av / av / matplotlib / mediapy.
#
# Output: /home/kadap/alpamayo-closedloop-demo/alpamayo1.5/notebooks/demo_cache/
#
# Takes ~15 minutes total (model load 7min + prerender 8min). Requires GPU
# free — make sure no closed-loop sim is running.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$REPO_ROOT/alpasim/.venv/bin/python"
NB_DIR="$REPO_ROOT/alpamayo1.5/notebooks"

if [[ ! -x "$VENV_PY" ]]; then
  echo "missing $VENV_PY — alpasim venv not set up" >&2; exit 1
fi
if [[ ! -d "$NB_DIR" ]]; then
  echo "missing $NB_DIR — alpamayo1.5 submodule + overlay symlinks not present" >&2; exit 1
fi

echo "==> prerender_demo_cache.py (~7 min)"
cd "$NB_DIR"
PYTHONPATH="$REPO_ROOT/alpamayo1.5/src:." "$VENV_PY" -u prerender_demo_cache.py

echo "==> prerender_extras.py (~8 min)"
PYTHONPATH="$REPO_ROOT/alpamayo1.5/src:." "$VENV_PY" -u prerender_extras.py

echo "==> done. demo_cache contents:"
ls "$NB_DIR/demo_cache" | head -20
