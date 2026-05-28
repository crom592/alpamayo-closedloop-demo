"""Ablation specifications for the KADaP PoC closed-loop demo.

The PoC story for the Korean Automotive Research Institute (KATRI) is
"changed input → changed judgment" — showing that the Alpamayo 1.5 driver
genuinely reacts to perturbations rather than replaying the ground truth.

PoC v0 supports two ablation axes that are cheap to apply via the wizard
Hydra config:

* ``camera_mask``  — drop one or more cameras from
  ``driver.inference.use_cameras``; the remaining cameras still stream and
  the model must drive with fewer viewpoints.
* ``start_offset_us`` — override
  ``runtime.simulation_config.time_start_offset_us`` to begin the rollout
  at a different point in the recorded ground truth (different scene
  context, different initial ego speed).

Each spec is serialised to a whitespace-separated list of Hydra overrides
and forwarded to ``scripts/run_closedloop.sh`` via the ``ABLATION_HYDRA``
environment variable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ALL_CAMERAS = [
    "camera_cross_left_120fov",
    "camera_front_wide_120fov",
    "camera_cross_right_120fov",
    "camera_front_tele_30fov",
]


@dataclass
class AblationSpec:
    """Single ablation configuration applied on top of the wizard defaults."""

    name: str = "base"
    camera_mask: list[str] = field(default_factory=list)  # cameras to remove
    start_offset_us: int | None = None  # if set, overrides time_start_offset_us

    @property
    def is_base(self) -> bool:
        return not self.camera_mask and self.start_offset_us is None

    @property
    def hint(self) -> str:
        """Short human label for UI."""
        bits = []
        if self.camera_mask:
            bits.append("mask:" + ",".join(c.split("_")[1] for c in self.camera_mask))
        if self.start_offset_us is not None:
            bits.append(f"off:{self.start_offset_us / 1e6:.1f}s")
        return " ".join(bits) or "base"


def hydra_overrides(spec: AblationSpec) -> list[str]:
    """Translate spec into a list of Hydra ``k=v`` strings."""
    overrides: list[str] = []
    if spec.camera_mask:
        kept = [c for c in ALL_CAMERAS if c not in spec.camera_mask]
        if not kept:
            raise ValueError("camera_mask removes every camera; at least one required")
        # Hydra list syntax — bracket form, comma-separated, no whitespace
        overrides.append("driver.inference.use_cameras=[" + ",".join(kept) + "]")
    if spec.start_offset_us is not None:
        overrides.append(
            f"runtime.simulation_config.time_start_offset_us={int(spec.start_offset_us)}"
        )
    return overrides


def to_env_value(spec: AblationSpec) -> str:
    """Whitespace-joined Hydra overrides, ready for ``ABLATION_HYDRA`` env."""
    return " ".join(hydra_overrides(spec))


PRESETS: dict[str, AblationSpec] = {
    "base": AblationSpec(name="base"),
    "no_left": AblationSpec(
        name="no_left_camera", camera_mask=["camera_cross_left_120fov"]
    ),
    "no_tele": AblationSpec(
        name="no_tele_camera", camera_mask=["camera_front_tele_30fov"]
    ),
    "front_only": AblationSpec(
        name="front_wide_only",
        camera_mask=[
            "camera_cross_left_120fov",
            "camera_cross_right_120fov",
            "camera_front_tele_30fov",
        ],
    ),
    "start_500ms": AblationSpec(name="start_500ms", start_offset_us=500_000),
    "start_2s": AblationSpec(name="start_2s", start_offset_us=2_000_000),
    "start_5s": AblationSpec(name="start_5s", start_offset_us=5_000_000),
}
