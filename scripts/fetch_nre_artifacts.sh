#!/usr/bin/env bash
# Triggers Alpasim's official NRE artifact download flow without running the full sim.
# Useful when you want to pre-warm the scene cache before the first closed-loop run.
#
# NOTE: NRE USDZ assets are NVIDIA-distributed; not redistributed via this repo.
# The wizard downloads them from NVIDIA's bucket and you accept their terms on first run.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

set -a; source .env; set +a
export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"

if [[ -z "${HF_TOKEN:-}" ]]; then
  echo "ERROR: HF_TOKEN required (the wizard authenticates via HF for some assets)" >&2
  exit 1
fi

pushd "$REPO_ROOT/alpasim" >/dev/null
echo "==> Running wizard in dry-run mode to fetch scenes only"
# The wizard caches scenes under data/nre-artifacts/ on first invocation.
# We invoke it with a small log_dir; on completion, the assets are cached even
# if the docker-compose stage fails (e.g. user kills it).
uv run alpasim_wizard \
  deploy=local \
  topology=1gpu \
  driver=alpamayo1_5 \
  wizard.log_dir="$REPO_ROOT/alpasim/run_dir_fetch_only" \
  || true

popd >/dev/null

echo ""
echo "==> NRE artifact cache:"
du -sh "$REPO_ROOT/alpasim/data/nre-artifacts" 2>/dev/null || echo "  (no artifacts dir yet)"
