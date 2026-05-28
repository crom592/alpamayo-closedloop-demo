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
# Wizard, when invoked from $REPO_ROOT/alpasim with wizard.log_dir, resolves
# the path under that cwd and emits artifacts at .../alpasim/alpasim/run_dir.
# Mirror that here so the patcher finds the YAML it actually wrote. Force the
# absolute path even if .env defines a relative RUN_DIR (legacy override).
RUN_DIR="$REPO_ROOT/alpasim/alpasim/run_dir"
SCENE_IDS="${SCENE_IDS:-}"   # optional: pass as '["clipgt-…","clipgt-…"]'
mkdir -p "$RUN_DIR"

echo "==> Generating docker-compose via alpasim_wizard (topology=1gpu, driver=$DRIVER, no auto-up)"
pushd "$REPO_ROOT/alpasim" >/dev/null
# wizard.run_method=NONE prevents the wizard from invoking `docker compose up`
# itself; we run it ourselves below after the patcher injects HF token and the
# extended startup_timeout_s. Otherwise the wizard's foreground compose-up
# races the patcher and the (unpatched) runtime hits its 120s probe deadline
# while driver-0 is still loading the Alpamayo 1.5 weights.
wizard_extra=()
if [[ -n "$SCENE_IDS" ]]; then
  wizard_extra+=("scenes.scene_ids=$SCENE_IDS")
fi
# KADaP PoC: forward extra Hydra overrides (e.g. ablation knobs) via env.
# ABLATION_HYDRA expects whitespace-separated Hydra k=v pairs.
if [[ -n "${ABLATION_HYDRA:-}" ]]; then
  # shellcheck disable=SC2206
  wizard_extra+=( $ABLATION_HYDRA )
fi
# KADaP PoC: enable GT trajectory submit so our patched
# submit_recording_ground_truth handler can pre-seed pose history.
# Without this override the wizard default (false) skips the GT push
# entirely and the driver buffer stays empty for the first 15 cycles.
uv run alpasim_wizard \
  deploy=local \
  topology=1gpu \
  driver="$DRIVER" \
  wizard.log_dir="$RUN_DIR" \
  wizard.run_method=NONE \
  runtime.simulation_config.send_recording_ground_truth=true \
  runtime.simulation_config.time_start_offset_us=1700000 \
  "${wizard_extra[@]}"

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
