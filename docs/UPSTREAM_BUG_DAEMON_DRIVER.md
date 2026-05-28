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

---

## Secondary finding (also worth filing): one-shot simulation terminates
## at 14 control cycles regardless of scenario length

Verified across two different OSS scenes (`clipgt-01d503d4`, ~1.5 GB USDZ
and `clipgt-023b7fcc`, ~1.4 GB USDZ) on the wizard's default
`topology=1gpu, driver=alpamayo1_5` deploy:

- ``rollout_metadata.session_metadata.n_sim_steps = 200`` (intent: ~20 s)
- ``ego_rig_recorded_ground_truth_trajectory.poses`` length is 202 — the
  scenario itself has 20 s of recorded GT available
- yet only **14 controller_return** entries land in the rollout, span
  ~1.4 s, after which the runtime logs ``Draining N outstanding tasks``
  and shuts the stack down
- driver's ``DriveResponse.trajectory.poses`` is **empty for all 14**
  cycles (alpamayo1_5 logs ``Pose history too short: available span
  1400.0ms < required 1500.0ms``)

So the closed loop *runs* — sensorsim renders 60 NRE frames, driver
fields 14 grpc calls, controller propagates a vehicle model — but the
driver never gets enough pose history to emit a real trajectory, so its
contribution to the rolled-out ego pose is effectively zero. The
simulator quits before pose history would have caught up.

If `n_sim_steps=200` is supposed to bound the run, something else is
ending it earlier; please document the actual termination condition or
let the driver warm up.

For the PoC this is the main reason the rollouts look "trivial" — they
are GT replay with a stalled driver, not genuine closed-loop inference.

---

## Update (2026-05-28): the 14-step termination IS the cu_seqlens_q bug

Re-running with ``runtime.simulation_config.send_recording_ground_truth=true``
and the [pose-seed driver patch](#pose-seed-driver-patch) below revealed that
the GT trajectory length is 20 s (202 poses) for every OSS NuRec clip
inspected. The 14-cycle ceiling is **not** a GT-length issue at all — it is
the same ``cu_seqlens_q must have shape (batch_size + 1)`` crash this doc
opens with, fired the moment the driver's pose-history buffer reaches the
required 1500 ms span and the first real ``sample_trajectories_from_data_with_vlm_rollout``
call lands. The runtime then unwinds the stack with ``Draining N outstanding
tasks`` and the rollout ends at whatever cycle the buffer first crossed 1.5 s.

So both findings collapse into the same single upstream issue. PoC v0
applies two driver-side workarounds in the ``crom592/alpasim`` fork:

### Pose-seed driver patch

``alpasim/src/driver/src/alpasim_driver/main.py:submit_recording_ground_truth``
no longer drops the GT. When the driver session's pose buffer still falls
short of 1.6 s, we splice the leading window of GT poses into
``session.poses`` so the model's 1500 ms history check passes from cycle 0.
The runtime must also be told to send GT in the first place
(``runtime.simulation_config.send_recording_ground_truth=true``); the wizard
default is ``false``. ``scripts/run_closedloop.sh`` sets this override
automatically.

### SDPA attention workaround

``alpasim/src/driver/src/alpasim_driver/models/alpamayo1_5_model.py`` now
passes ``attn_implementation="sdpa"`` to
``Alpamayo1_5.from_pretrained``, overriding the checkpoint's baked-in
``flash_attention_2``. With the native ``flash_attn`` package not installed,
transformers falls back to ``kernels-community/flash-attn``, whose
variable-length attention path is what produces the ``cu_seqlens_q``
shape error against the driver's batch shapes. SDPA runs entirely inside
PyTorch SDP / xformers fall-back, gives correct ``cu_seqlens_q`` layout, and
is acceptable accuracy-wise for a closed-loop PoC demo (accuracy parity vs
flash-attn-2 is bit-exact within bf16 noise on the matmuls we exercise).

Override via env: ``KADAP_ATTN_IMPL=flash_attention_2`` reverts to upstream
behaviour for testing.

Upstream-friendly fix would be to either bundle ``flash_attn`` properly in
the alpasim driver container, or to pin ``transformers`` to a version where
``kernels-community/flash-attn`` correctly shapes ``cu_seqlens_q`` for
single-sample batched VLM generation.
