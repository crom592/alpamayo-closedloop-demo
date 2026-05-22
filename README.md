# Alpamayo 1.5 + Alpasim NRE Closed-Loop Demo

Alpamayo 1.5 (10B VLM driver) × Alpasim (with NVIDIA Neural Rendering Engine) closed-loop autonomous-driving demo, packaged for deployment on the KADaP (자동차산업클라우드) cloud.

This repository is a meta-repo that combines:

- [`crom592/alpamayo1.5`](https://github.com/crom592/alpamayo1.5) — fork of NVlabs/alpamayo1.5 (pinned at `2eff703`)
- [`crom592/alpasim`](https://github.com/crom592/alpasim) — fork of NVlabs/alpasim (pinned at `a5767fd`)

…plus a thin overlay of demo code, setup scripts, and a closed-loop dashboard webapp.

## What this demo shows

Unlike the open-loop demo (which replays prerendered scenarios), this demo runs Alpamayo 1.5 as the policy driver inside Alpasim's full closed-loop:

```
NRE (photorealistic sensor render)
        │ camera frames
        ▼
   Alpamayo 1.5 (VLM reasoning → trajectory)
        │ ego trajectory
        ▼
   Physics + Traffic sim
        │ updated world state
        ▼
        ↻ back to NRE
```

A separate dashboard webapp (port 7860) tails live rollout MP4s, `controller-0` events, driver inference time, and GPU metrics — so you can see closed-loop driving actually happening.

## Quick start (KADaP server)

Provision a KADaP GPU server with:
- Ubuntu 22.04 + Linux DevTools image (Docker + GPU drivers preinstalled)
- 1× GPU with **≥ 24 GB VRAM** (L40S 48 GB or A100 40 GB recommended)
- 100 GB OS disk + **200 GB** additional disk mounted at `/data`
- Port forwarding: external 7860 → internal 7860 (TCP+SSL, web service)

Then in the web terminal:

```bash
cd /data
git clone https://github.com/crom592/alpamayo-closedloop-demo.git
cd alpamayo-closedloop-demo
git submodule update --init --recursive
cp .env.example .env
# Edit .env to set HF_TOKEN=hf_...
bash scripts/setup.sh 2>&1 | tee setup.log    # ~25-45 min
bash scripts/run_closedloop.sh                # starts Alpasim wizard + compose
bash scripts/run_dashboard.sh                 # serves dashboard on :7860
```

Open the KADaP-assigned external URL for port 7860 to see the dashboard.

## Architecture

```
KADaP GPU Server (x86, Ubuntu 22.04)
├── Alpasim wizard (generated docker-compose)
│   ├── physics-0       vehicle dynamics
│   ├── trafficsim-0    NPC traffic
│   ├── nre-0           NVIDIA NRE photorealistic rendering (USDZ scenes)
│   ├── driver-0        Alpamayo 1.5 10B (weights pulled from HuggingFace)
│   └── controller-0    rollout orchestration → run_dir/rollouts/
└── dashboard (Streamlit, port 7860)
    ├── latest rollout MP4 viewer
    ├── controller-0 live event stream
    ├── driver-0 inference latency + GPU metrics
    └── docker compose health check
```

## NRE artifacts

NVIDIA NRE neural scene assets (~1.5 GB USDZs) are **not** redistributed in this repo. `scripts/setup.sh` triggers Alpasim wizard's official download path on first run, which fetches from NVIDIA's public bucket and accepts their click-through license. See `alpasim/docs/TUTORIAL.md`.

## Why the local open-loop demo isn't enough

The Alpamayo repo's Gradio demo (`notebooks/app.py`) is open-loop only — it replays prerendered scenarios from `notebooks/demo_cache/`. The `app.py:952` notice explains: NRE doesn't support ARM, so closed-loop needs a separate x86 node. KADaP provides exactly that.

## Attribution

Both upstream projects are Apache 2.0 licensed by NVIDIA. See `NOTICE`.

## License

Apache License 2.0 — see [`LICENSE`](./LICENSE).
