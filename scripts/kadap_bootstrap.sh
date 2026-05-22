#!/usr/bin/env bash
# One-shot bootstrap to paste into the KADaP web terminal.
# Clones the repo, initializes submodules, prepares .env stub.
# Assumes the KADaP server has git + curl preinstalled (Linux DevTools image does).
set -euo pipefail

WORK_DIR="${WORK_DIR:-/data}"
REPO_URL="${REPO_URL:-https://github.com/crom592/alpamayo-closedloop-demo.git}"

echo "==> KADaP bootstrap starting in ${WORK_DIR}"
cd "$WORK_DIR"

if [[ ! -d alpamayo-closedloop-demo ]]; then
  git clone "$REPO_URL"
fi
cd alpamayo-closedloop-demo
git submodule update --init --recursive

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo ""
  echo "==> .env created from template."
  echo "    EDIT IT NOW: set HF_TOKEN=hf_xxx (read access to nvidia/Alpamayo-1.5-10B)"
  echo "    Run: nano .env   (or vi .env)"
  echo ""
  echo "    When done, run:  bash scripts/setup.sh 2>&1 | tee setup.log"
else
  echo "==> .env already exists — skipping template copy."
  echo "    Next: bash scripts/setup.sh 2>&1 | tee setup.log"
fi
