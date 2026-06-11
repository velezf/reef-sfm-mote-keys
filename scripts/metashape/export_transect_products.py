#!/usr/bin/env python3
"""export_transect_products.py — ESM Step 16 export of transect DSM + ortho.

Exports chunk.elevation (DSM) and chunk.orthomosaic from the live project
to GeoTIFF.  Read-only input; writes only to --out-dir.

Usage (EC2 headless):
    /opt/metashape-pro/metashape.sh -platform offscreen \
        -r /data/reef-sfm-mote-keys/scripts/metashape/export_transect_products.py \
        --project /data/edr_work/edr_t1.psx \
        --out-dir /data/edr_work/products/EDR_T1
"""
from __future__ import annotations
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

import Metashape  # type: ignore


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    ts = _ts()

    _log(f"Opening {args.project} (read-only for export)")
    doc = Metashape.Document()
    doc.open(str(args.project), read_only=True)

    chunks = [c for c in doc.chunks if c.point_cloud is not None or c.elevation is not None]
    if not chunks:
        sys.exit("No usable chunk found.")
    chunk = chunks[0]
    _log(f"Chunk: {chunk.label}  scale={chunk.transform.scale:.8f} m/unit")

    # --- DSM export ---
    if chunk.elevation is None:
        sys.exit("No elevation (DSM) in chunk.")
    elev = chunk.elevation
    _log(f"DSM: {elev.width}×{elev.height} cells  res={elev.resolution:.4f} m/cell")
    dsm_path = args.out_dir / f"edr_t1_transect_dsm_{ts}.tif"
    _log(f"Exporting DSM → {dsm_path}")
    chunk.exportRaster(
        path=str(dsm_path),
        source_data=Metashape.ElevationData,
        image_format=Metashape.ImageFormatTIFF,
        save_alpha=False,
    )
    dsm_mb = dsm_path.stat().st_size / 1e6
    _log(f"DSM exported: {dsm_mb:.2f} MB")

    # --- Ortho export ---
    if chunk.orthomosaic is None:
        sys.exit("No orthomosaic in chunk.")
    ortho = chunk.orthomosaic
    _log(f"Ortho: {ortho.width}×{ortho.height} px  res={ortho.resolution:.4f} m/px")
    ortho_path = args.out_dir / f"edr_t1_transect_ortho_{ts}.tif"
    _log(f"Exporting ortho → {ortho_path}")
    chunk.exportRaster(
        path=str(ortho_path),
        source_data=Metashape.OrthomosaicData,
        image_format=Metashape.ImageFormatTIFF,
        save_alpha=False,
    )
    ortho_mb = ortho_path.stat().st_size / 1e6
    _log(f"Ortho exported: {ortho_mb:.2f} MB")

    _log("=" * 60)
    _log("ESM Step 16 export COMPLETE")
    _log(f"  DSM:   {dsm_path}  ({dsm_mb:.2f} MB)")
    _log(f"  Ortho: {ortho_path}  ({ortho_mb:.2f} MB)")
    _log("  Read-only — project not modified.")


if __name__ == "__main__":
    main()
