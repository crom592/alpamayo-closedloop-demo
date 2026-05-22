# V2X Demo Overlay

These files are demo additions on top of upstream `NVlabs/alpamayo1.5` (V2X-linked Gradio UI used by KATECH). `scripts/setup.sh` symlinks them into the `alpamayo1.5/notebooks/` submodule checkout so the demo can run without modifying the submodule's commit pin.

| File | Purpose |
|---|---|
| `app.py` | Gradio open-loop demo entrypoint (6 tabs: single eval, demo, real-time playback, VQA, camera-count, history). Serves on `:7860` with basic auth (`researcher` / `alpamayo`). |
| `adapters.py` | Camera/BEV adapters used by the demo |
| `make_video.py`, `make_video_nav.py` | Video composition for demo cache prerender |
| `prerender_demo_cache.py`, `prerender_extras.py` | Build the `notebooks/demo_cache/` used by the real-time-playback tab (open-loop only) |

Note: the closed-loop path doesn't go through these files. Closed-loop runs through Alpasim's wizard + `EgodriverService` gRPC, observed via the separate `dashboard/` webapp.
