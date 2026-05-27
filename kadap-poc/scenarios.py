"""Scenario catalog browser for the KADaP PoC.

Source of truth is ``alpasim/data/scenes/sim_scenes_2602.csv`` — 910 NRE
sample-set entries from the ``nvidia/PhysicalAI-Autonomous-Vehicles-NuRec``
HuggingFace dataset. Each row pairs a ``scene_id`` with the relative path
of its ``.usdz`` artifact and the dataset revision tag.

The runtime needs the .usdz under
``alpasim/data/nre-artifacts/all-usdzs/<asset_uuid>.usdz`` (or symlinked
into the active sceneset dir). On the PoC v0 only a handful are pre-fetched;
this module exposes the catalog, marks which entries are local, and
downloads the rest on demand via ``huggingface_hub.hf_hub_download``.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

HF_REPO = "nvidia/PhysicalAI-Autonomous-Vehicles-NuRec"
HF_REPO_TYPE = "dataset"

REPO_ROOT = Path(__file__).resolve().parent.parent
ALPASIM_ROOT = REPO_ROOT / "alpasim"
CATALOG_CSV = ALPASIM_ROOT / "data" / "scenes" / "sim_scenes_2602.csv"
USDZ_DIR = ALPASIM_ROOT / "data" / "nre-artifacts" / "all-usdzs"


@dataclass
class ScenarioRow:
    uuid: str
    scene_id: str
    nre_version: str
    path: str  # relative path in the HF dataset
    last_modified: str
    artifact_repository: str
    hf_revision: str

    @property
    def usdz_filename(self) -> str:
        """All-USDZ dir uses the artifact UUID as basename."""
        return f"{self.uuid}.usdz"

    @property
    def local_path(self) -> Path:
        return USDZ_DIR / self.usdz_filename

    def is_local(self) -> bool:
        return self.local_path.exists() and self.local_path.stat().st_size > 0


@lru_cache(maxsize=1)
def load_catalog(csv_path: Path = CATALOG_CSV) -> list[ScenarioRow]:
    if not csv_path.exists():
        return []
    rows = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                rows.append(
                    ScenarioRow(
                        uuid=r["uuid"],
                        scene_id=r["scene_id"],
                        nre_version=r["nre_version_string"],
                        path=r["path"],
                        last_modified=r["last_modified"],
                        artifact_repository=r["artifact_repository"],
                        hf_revision=r["hf_revision"],
                    )
                )
            except KeyError:
                continue
    return rows


def get(scene_id: str) -> ScenarioRow | None:
    for r in load_catalog():
        if r.scene_id == scene_id:
            return r
    return None


def download(row: ScenarioRow, hf_token: str | None = None) -> Path:
    """Fetch one USDZ from HF into nre-artifacts/all-usdzs/<uuid>.usdz."""
    from huggingface_hub import hf_hub_download  # local import: heavy

    USDZ_DIR.mkdir(parents=True, exist_ok=True)
    cached = hf_hub_download(
        repo_id=HF_REPO,
        repo_type=HF_REPO_TYPE,
        filename=row.path,
        revision=row.hf_revision,
        token=hf_token or os.environ.get("HF_TOKEN"),
    )
    cached_path = Path(cached)
    # HF gives us a cache path; copy/symlink to where the runtime expects it.
    target = row.local_path
    if target.exists():
        target.unlink()
    try:
        target.symlink_to(cached_path)
    except OSError:
        target.write_bytes(cached_path.read_bytes())
    return target


def summary() -> dict:
    cat = load_catalog()
    local = sum(1 for r in cat if r.is_local())
    return {
        "total": len(cat),
        "local": local,
        "remote": len(cat) - local,
        "csv": str(CATALOG_CSV.relative_to(REPO_ROOT)),
    }
