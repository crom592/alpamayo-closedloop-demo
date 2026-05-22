#!/usr/bin/env bash
# Launches the closed-loop dashboard webapp (Streamlit) on $DASHBOARD_PORT.
# The dashboard tails docker logs + serves rollout MP4s from RUN_DIR.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

set -a; source .env; set +a
RUN_DIR="${RUN_DIR:-$REPO_ROOT/alpasim/run_dir}"
DASHBOARD_PORT="${DASHBOARD_PORT:-7860}"

echo "==> Building dashboard image"
docker build -t alpamayo-closedloop-dashboard "$REPO_ROOT/dashboard"

echo "==> Stopping any previous dashboard container"
docker rm -f alpamayo-dashboard 2>/dev/null || true

echo "==> Running dashboard on :${DASHBOARD_PORT}"
docker run -d \
  --name alpamayo-dashboard \
  --restart unless-stopped \
  -p "${DASHBOARD_PORT}:8501" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$RUN_DIR:/run_dir:ro" \
  -e RUN_DIR=/run_dir \
  alpamayo-closedloop-dashboard

echo ""
echo "==> Dashboard up. Local: http://localhost:${DASHBOARD_PORT}"
echo "    Through KADaP port-forward: open the external URL configured for port ${DASHBOARD_PORT}."
echo "    Logs: docker logs -f alpamayo-dashboard"
