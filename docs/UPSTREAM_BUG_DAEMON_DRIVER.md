# Upstream bug: daemon-path driver inference crashes with `cu_seqlens_q` shape error

This is a draft issue we should file against the alpasim and/or
alpamayo1.5 upstream repos. The PoC works around it by using one-shot
compose runs (Task #15 / [README](../kadap-poc/README.md)); the daemon
gRPC scaffolding in `kadap-poc/client.py` will start being useful again
once this is fixed.

## Target repos

- alpasim runtime daemon path: probably **NVlabs/alpasim** (this fork:
  `crom592/alpasim`, HEAD `a5767fd Sync to public repo (03/04/2026) (#64)`)
- alpamayo1.5 attention kernel call: probably **NVlabs/alpamayo1.5**
  (this fork: `crom592/alpamayo1.5`, HEAD
  `2eff703 Merge pull request #2 from NVlabs/yurongy/fix_test_inference_bug`)

File against whichever repo accepts integration-level reports first;
cross-link the other.

## Title

> `RuntimeError: cu_seqlens_q must have shape (batch_size + 1)` on the
> first daemon-mode `simulate` after `RuntimeDaemonApp.startup`

## Summary

The single-shot path (`alpasim_runtime.simulate.__main__:run_simulation`)
runs an Alpamayo 1.5 rollout to completion. Reusing the same
`alpasim_runtime.daemon.app.RuntimeDaemonApp` process for a
`RuntimeService.simulate` RPC immediately after the engine reports
ready dies inside the driver's first inference batch with a flash-attn
sequence-length tensor shape mismatch. The container is otherwise
healthy: empty `SimulationRequest` returns the full version IDs, and
the runtime/sensorsim/physics/controller pre-flight probes all succeed.

## Environment

- alpasim `a5767fd` (NVlabs sync 03/04/2026), via `crom592/alpasim` fork
- alpamayo1.5 `2eff703` driver model, via `crom592/alpamayo1.5` fork
- NRE container `nvcr.io/nvidia/nre/nre-ga:26.02`
- KADaP A40 (46 GB), NVIDIA driver 580.159.03-server, docker 29.5.2,
  docker daemon `mtu: 1450` and `data-root: /data/docker`
- All services run with `HF_HUB_DISABLE_XET=1` and
  `DISABLE_KERNEL_MAPPING=1` injected by `scripts/patch_compose_for_daemon.py`
  (without these the model load itself stalls on KADaP's network — see
  the patcher docstring)

## Repro

From the repo root:

```bash
bash scripts/run_closedloop.sh           # wizard + patcher (daemon by default)
KADAP_DAEMON=1 bash scripts/run_closedloop.sh   # opt back into --serve
# wait ~10 min for driver-0 to load Alpamayo 1.5 (GPU climbs to ~22 GB)
./alpasim/.venv/bin/python kadap-poc/client.py \
    clipgt-01d503d4-449b-46fc-8d78-9085e70d3554 -n 1
```

## Observed

The CLI receives a `SimulationReturn` with `success=False` and:

```text
RuntimeError: cu_seqlens_q must have shape (batch_size + 1)
```

raised from `egodriver.EgodriverService/drive`. The driver container logs:

```
[__main__][ERROR] - Inference batch failed
Traceback (most recent call last):
RuntimeError: cu_seqlens_q must have shape (batch_size + 1)
[__main__][ERROR] - Exception in drive
[grpc._cython.cygrpc][ERROR] - Unexpected [RuntimeError] raised by
  servicer method [/egodriver.EgodriverService/drive]
```

## Expected

Daemon-mode `simulate` should produce the same `rollout.asl` as a
single-shot wizard run against the same scenario.

## Suspected cause

The driver's flash-attn cumulative-seqlens tensor is shaped for the
single-shot worker's initial batch but not refreshed when a daemon-mode
worker dispatches its first `drive()` request, so the first inference
sees a stale per-session state. The runtime daemon serialises one
`simulate` at a time today, so it isn't a concurrency issue; it looks
like a missed `Session.create` reset on the model side.

Pointers for the bisect:

- `alpamayo1.5/src/alpamayo1_5/models/base_model.py` — attention setup
- `alpasim/src/runtime/alpasim_runtime/daemon/engine.py:startup` — vs
  `simulate/__main__.py:_run_one_shot_request`
- `alpasim/src/driver/src/alpasim_driver/main.py:Session.create` — what
  state, if any, must be invalidated on the model when a new gRPC
  driver session opens.

## Workaround in this fork

`scripts/patch_compose_for_daemon.py` defaults to `--no-daemon`; the
PoC uses one-shot compose runs (`kadap-poc/runner.py`). Daemon RPC
code in `kadap-poc/client.py` is retained verbatim so we can switch
back once the upstream fix lands.
