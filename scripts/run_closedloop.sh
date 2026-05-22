#!/usr/bin/env bash
# Generates Alpasim docker-compose for the Alpamayo 1.5 driver and brings the stack up.
# Re-run anytime — wizard regenerates compose against the current arch.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

set -a; source .env; set +a
export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
RUN_DIR="${RUN_DIR:-$REPO_ROOT/alpasim/run_dir}"
mkdir -p "$RUN_DIR"

echo "==> Generating docker-compose via alpasim_wizard (topology=1gpu, driver=alpamayo1_5)"
pushd "$REPO_ROOT/alpasim" >/dev/null
uv run alpasim_wizard \
  deploy=local \
  topology=1gpu \
  driver=alpamayo1_5 \
  wizard.log_dir="$RUN_DIR"

compose_file="$RUN_DIR/docker-compose.yaml"
if [[ ! -f "$compose_file" ]]; then
  # wizard sometimes uses .yml or nests
  compose_file="$(find "$RUN_DIR" -maxdepth 2 -name 'docker-compose.y*ml' | head -1)"
fi
if [[ -z "${compose_file:-}" || ! -f "$compose_file" ]]; then
  echo "ERROR: wizard did not produce a docker-compose file under $RUN_DIR" >&2
  exit 1
fi

echo "==> Bringing up closed-loop stack: $compose_file"
docker compose -f "$compose_file" up -d
docker compose -f "$compose_file" ps
popd >/dev/null

echo ""
echo "==> Closed-loop stack is up. Watch logs:"
echo "    docker compose -f $compose_file logs -f controller-0 driver-0"
echo ""
echo "==> Health: all of physics-0, trafficsim-0, nre-0, driver-0, controller-0 should reach 'Up (healthy)'."
echo "    Rollouts will accumulate under: $RUN_DIR/rollouts/"
