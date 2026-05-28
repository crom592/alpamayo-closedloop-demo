#!/usr/bin/env python3
"""Probe NuRec USDZ artifacts for their trajectory length.

After the cu_seqlens_q + pose-seed work, every NuRec OSS scene has 20s of
recorded ground truth (verified for the first two clips). What still varies
between scenes is traffic density, road type, and ego speed profile — useful
metadata for the PoC catalog tab.

This tool reads ``rig_trajectories.json`` from inside locally-available USDZ
zips and reports trajectory span + pose count. Run with ``--download N`` to
fetch the next N un-cached scenes from HuggingFace before probing.

Output: ``kadap-poc/long_scenes.json`` — sorted by duration descending.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "kadap-poc"))

import scenarios  # noqa: E402  (path-injected)

OUT_PATH = REPO_ROOT / "kadap-poc" / "long_scenes.json"


def probe_one(usdz_path: Path) -> dict | None:
    """Return {'duration_s', 'pose_count', 'start_us'} or None on failure."""
    try:
        with zipfile.ZipFile(usdz_path) as z:
            if "rig_trajectories.json" not in z.namelist():
                return None
            rig = json.loads(z.read("rig_trajectories.json"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError):
        return None
    trajs = rig.get("rig_trajectories", [])
    if not trajs:
        return None
    ts = trajs[0].get("T_rig_world_timestamps_us", [])
    if not ts:
        return None
    return {
        "duration_s": (max(ts) - min(ts)) / 1e6,
        "pose_count": len(ts),
        "start_us": min(ts),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--download",
        type=int,
        default=0,
        metavar="N",
        help="download N additional remote scenes before probing (default 0)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=50,
        help="cap on number of scenes probed locally (default 50)",
    )
    args = p.parse_args()

    catalog = scenarios.load_catalog()
    catalog_by_scene = {r.scene_id: r for r in catalog}
    print(f"catalog: {len(catalog)} scenes total")

    # The CSV's uuid column doesn't match the USDZ on-disk filename in every
    # case; just walk the all-usdzs/ dir and read the scene_id out of each
    # rig_trajectories.json (it's embedded in camera/lidar timestamp keys).
    usdz_files = sorted(scenarios.USDZ_DIR.glob("*.usdz")) if scenarios.USDZ_DIR.exists() else []
    print(f"local: {len(usdz_files)} usdz files in all-usdzs/")

    if args.download > 0:
        remote = [r for r in catalog if not r.is_local()][: args.download]
        for i, row in enumerate(remote, 1):
            print(f"[{i}/{len(remote)}] downloading {row.scene_id[:40]}…")
            try:
                scenarios.download(row)
            except Exception as e:  # noqa: BLE001
                print(f"  -> failed: {e}")
                continue
        # refresh after download
        usdz_files = sorted(scenarios.USDZ_DIR.glob("*.usdz"))

    results: list[dict] = []
    for path in usdz_files[: args.limit]:
        info = probe_one(path)
        if info is None:
            print(f"  skip {path.name} (bad usdz or missing trajectory)")
            continue
        # Extract scene_id from any camera key, e.g.
        #   'camera_cross_left_120fov@clipgt-023b7fcc-...'
        scene_id = "?"
        try:
            with zipfile.ZipFile(path) as z:
                rig = json.loads(z.read("rig_trajectories.json"))
            cam_keys = list(rig["rig_trajectories"][0]["cameras_frame_timestamps_us"].keys())
            if cam_keys and "@" in cam_keys[0]:
                scene_id = cam_keys[0].split("@", 1)[1]
        except Exception:  # noqa: BLE001
            pass
        row = catalog_by_scene.get(scene_id)
        results.append(
            {
                "scene_id": scene_id,
                "uuid": row.uuid if row else path.stem,
                "usdz_filename": path.name,
                "size_mb": path.stat().st_size / 1e6,
                **info,
            }
        )

    results.sort(key=lambda x: -x["duration_s"])
    OUT_PATH.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {OUT_PATH.relative_to(REPO_ROOT)}  ({len(results)} entries)")
    print("\ntop 10 by duration:")
    for r in results[:10]:
        print(
            f"  {r['duration_s']:5.1f}s  poses={r['pose_count']:3d}  "
            f"size={r['size_mb']:6.1f} MB  {r['scene_id']}"
        )


if __name__ == "__main__":
    main()
