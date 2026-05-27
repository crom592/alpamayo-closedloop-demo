#!/usr/bin/env bash
# Generates Alpasim docker-compose, applies the KADaP PoC env patches, then
# brings the stack up. Re-run anytime — wizard regenerates compose against
# the current arch. Override DRIVER / KADAP_DAEMON via env:
#     DRIVER=vavam bash scripts/run_closedloop.sh
#     KADAP_DAEMON=1 bash scripts/run_closedloop.sh   # opt into --serve
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

set -a; source .env; set +a
export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
DRIVER="${DRIVER:-alpamayo1_5}"
RUN_DIR="${RUN_DIR:-$REPO_ROOT/alpasim/run_dir}"
mkdir -p "$RUN_DIR"

echo "==> Generating docker-compose via alpasim_wizard (topology=1gpu, driver=$DRIVER)"
pushd "$REPO_ROOT/alpasim" >/dev/null
uv run alpasim_wizard \
  deploy=local \
  topology=1gpu \
  driver="$DRIVER" \
  wizard.log_dir="$RUN_DIR"

compose_file="$RUN_DIR/docker-compose.yaml"
if [[ ! -f "$compose_file" ]]; then
  compose_file="$(find "$RUN_DIR" -maxdepth 2 -name 'docker-compose.y*ml' | head -1)"
fi
if [[ -z "${compose_file:-}" || ! -f "$compose_file" ]]; then
  echo "ERROR: wizard did not produce a docker-compose file under $RUN_DIR" >&2
  exit 1
fi
popd >/dev/null

echo "==> Applying KADaP PoC env patches (HF token / xet / kernel mapping / startup_timeout_s)"
patch_args=()
if [[ "${KADAP_DAEMON:-0}" != "1" ]]; then
  patch_args+=(--no-daemon)
fi
python3 "$REPO_ROOT/scripts/patch_compose_for_daemon.py" \
  --run-dir "$(dirname "$compose_file")" "${patch_args[@]}"

echo "==> Bringing up closed-loop stack: $compose_file"
docker compose -f "$compose_file" up -d
docker compose -f "$compose_file" ps

echo ""
echo "==> Closed-loop stack is up. Watch logs:"
echo "    docker compose -f $compose_file logs -f controller-0 driver-0"
echo ""
echo "    Rollouts will accumulate under: $(dirname "$compose_file")/rollouts/"
