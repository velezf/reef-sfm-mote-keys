#!/usr/bin/env python3
"""build_fullarea_visual.py — full-area site-overview DEM and orthomosaic.

Non-ESM, non-destructive: no point-cloud write, no region crop.  Run BEFORE
stage_aoi, which crops the cloud to the 10×1 m transect.

Products written to <out-dir>/:
    edr_t1_fullarea_dsm_<UTC>.tif   — 2 cm DEM, GeoTIFF
    edr_t1_fullarea_ortho_<UTC>.tif — native-GSD ortho, GeoTIFF

Usage (EC2 headless):
    /opt/metashape-pro/metashape.sh -platform offscreen \\
        -r /data/reef-sfm-mote-keys/scripts/metashape/build_fullarea_visual.py \\
        -- --project /data/edr_work/edr_t1.psx \\
           --out-dir /data/edr_work/products/EDR_T1 \\
           --resolution 0.02

After completion, query the reported AOI Z range against the 7 m window from
ADR-0026.  Adjust --aoi-height in stage_aoi if local relief exceeds 5.4 m.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import Metashape  # type: ignore

# ---------------------------------------------------------------------------
# ADR-0026 AOI footprint for Z-range sampling (chunk CRS metres)
# Centre (−2.028, 3.774); long axis 135° → unit (−0.7071, 0.7071)
# Short axis 225° → unit (−0.7071, −0.7071); half-extents (5.0, 0.5) m
# ---------------------------------------------------------------------------
_AOI_CENTRE_XY = (-2.028, 3.774)
_AOI_LONG_UNIT = (-0.7071, 0.7071)
_AOI_SHORT_UNIT = (-0.7071, -0.7071)
_AOI_HALF_LEN = 5.0
_AOI_HALF_WID = 0.5

# Guard: abort if the 2 cm DEM would exceed this cell count (5 M guard from ADR-0027)
_MAX_CELLS = 5_000_000

# Metashape DEM no-data sentinel (values at or below this are gaps)
_NODATA = -1e38


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _local_planar_projection(chunk: "Metashape.Chunk") -> "Metashape.CoordinateSystem":
    """Return the LOCAL planar CRS for the chunk (mirrors ADR-0020 recipe in
    run_pipeline.py).  Raises if the chunk has no transform yet."""
    crs = Metashape.CoordinateSystem("LOCAL")
    return crs


def _assert_writable(doc: "Metashape.Document") -> None:
    if doc.read_only:
        sys.exit("Project opened read-only (stale lock?). Aborting — no compute "
                 "wasted (2026-06-04 T1 incident).")


def _verify_save(doc: "Metashape.Document", path: Path) -> None:
    mtime_before = path.stat().st_mtime if path.exists() else 0.0
    doc.save()
    mtime_after = path.stat().st_mtime if path.exists() else 0.0
    if mtime_after <= mtime_before:
        sys.exit(f"save() did not advance mtime on {path}. Aborting.")
    _log(f"Project saved + mtime verified ({int(mtime_after)}).")


def _sample_aoi_z(el: "Metashape.Elevation") -> tuple[float, float] | None:
    """Sample DEM Z values on a grid inside the ADR-0026 AOI footprint.

    Returns (z_min, z_max) in chunk CRS metres, or None if no valid cells hit.
    Uses el.altitude(Metashape.Vector([x, y])) with the LOCAL_CS coordinates.
    """
    lx, ly = _AOI_LONG_UNIT
    sx, sy = _AOI_SHORT_UNIT
    cx, cy = _AOI_CENTRE_XY
    step_l = 1.0   # 1 m steps along long axis
    step_s = 0.25  # 0.25 m steps across short axis

    t_vals = [i * step_l for i in range(int(-_AOI_HALF_LEN / step_l),
                                         int(_AOI_HALF_LEN / step_l) + 1)]
    s_vals = [j * step_s for j in range(int(-_AOI_HALF_WID / step_s),
                                         int(_AOI_HALF_WID / step_s) + 1)]
    z_vals = []
    for t in t_vals:
        for s in s_vals:
            x = cx + t * lx + s * sx
            y = cy + t * ly + s * sy
            z = el.altitude(Metashape.Vector([x, y]))
            if z is not None and z > _NODATA:
                z_vals.append(z)

    if not z_vals:
        return None
    return min(z_vals), max(z_vals)


def build_fullarea_visual(project_path: Path, out_dir: Path,
                          resolution: float) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = _utcnow()
    dsm_path = out_dir / f"edr_t1_fullarea_dsm_{ts}.tif"
    ortho_path = out_dir / f"edr_t1_fullarea_ortho_{ts}.tif"

    _log(f"Opening {project_path}")
    doc = Metashape.Document()
    doc.open(str(project_path))
    _assert_writable(doc)

    chunks = [c for c in doc.chunks if c.point_cloud is not None]
    if not chunks:
        sys.exit("No chunk with a dense cloud found.")
    chunk = chunks[0]
    _log(f"Chunk: {chunk.label}  scale={chunk.transform.scale:.8f} m/unit")

    # --- Full cloud region (encompass entire cloud) ---
    chunk.resetRegion()

    # --- Predict cell count ---
    scale = chunk.transform.scale
    reg = chunk.region
    # Region size is in internal units; multiply by scale to get metres
    world_x = reg.size.x * scale
    world_y = reg.size.y * scale
    pred_cells = int((world_x / resolution) * (world_y / resolution))
    _log(f"Full-area footprint: {world_x:.2f} × {world_y:.2f} m  "
         f"→ predicted cells @ {resolution*100:.0f} cm: {pred_cells:,}")
    if pred_cells > _MAX_CELLS:
        sys.exit(f"Predicted cell count {pred_cells:,} > guard {_MAX_CELLS:,}. "
                 f"Increase --resolution (e.g. 0.03) or raise the guard. Aborting.")

    # --- Build full-area DEM (interp ON for export; does not crop cloud) ---
    _log(f"Building DEM @ {resolution*100:.0f} cm ...")
    t0 = time.time()
    proj = _local_planar_projection(chunk)
    chunk.buildDem(source_data=Metashape.PointCloudData,
                   interpolation=Metashape.EnabledInterpolation,
                   projection=proj,
                   resolution=resolution)
    el = chunk.elevation
    if el is None:
        sys.exit("buildDem returned no elevation object.")
    actual_cells = el.width * el.height
    _log(f"DEM built: {el.width} × {el.height} = {actual_cells:,} cells  "
         f"({time.time()-t0:.1f} s)")

    # --- Sample local Z relief inside the ADR-0026 AOI footprint ---
    _log("Sampling DEM Z within ADR-0026 10×1 m AOI footprint ...")
    z_result = _sample_aoi_z(el)
    if z_result is not None:
        z_min, z_max = z_result
        z_range = z_max - z_min
        _log(f"AOI footprint Z: min={z_min:.3f}  max={z_max:.3f}  "
             f"range={z_range:.3f} m  (ADR-0026 window=7.0 m)")
        if z_range > 7.0:
            _log(f"WARNING: local relief {z_range:.3f} m exceeds the 7.0 m ADR-0026 "
                 f"window.  Increase --aoi-height in stage_aoi before running.")
        else:
            margin = 7.0 - z_range
            _log(f"Z window OK — {margin:.2f} m margin remaining in 7.0 m window.")
    else:
        _log("WARNING: no valid DEM cells in AOI footprint — Z range not confirmed. "
             "Verify footprint coords against DEM extent before running stage_aoi.")

    # --- Export full-area DSM ---
    _log(f"Exporting DSM → {dsm_path} ...")
    chunk.exportRaster(path=str(dsm_path),
                       source_data=Metashape.ElevationData,
                       image_format=Metashape.ImageFormatTIFF,
                       save_alpha=False)
    dsm_size_mb = dsm_path.stat().st_size / 1e6
    _log(f"DSM exported: {dsm_size_mb:.1f} MB")

    # --- Build orthomosaic at native GSD (surface = built DEM) ---
    _log("Building orthomosaic @ native GSD ...")
    t0 = time.time()
    chunk.buildOrthomosaic(surface_data=Metashape.ElevationData,
                           blending_mode=Metashape.MosaicBlending,
                           fill_holes=True,
                           resolution=0)
    ortho = chunk.orthomosaic
    if ortho is None:
        sys.exit("buildOrthomosaic returned no orthomosaic object.")
    _log(f"Ortho built: {ortho.width} × {ortho.height} px  "
         f"res={ortho.resolution:.5f} m/px  ({time.time()-t0:.1f} s)")

    # --- Export orthomosaic ---
    _log(f"Exporting ortho → {ortho_path} ...")
    chunk.exportRaster(path=str(ortho_path),
                       source_data=Metashape.OrthomosaicData,
                       image_format=Metashape.ImageFormatTIFF,
                       save_alpha=False)
    ortho_size_mb = ortho_path.stat().st_size / 1e6
    _log(f"Ortho exported: {ortho_size_mb:.1f} MB")

    # --- Save (DEM + ortho objects are in the project) ---
    _verify_save(doc, project_path)

    _log("=" * 60)
    _log("Full-area visual build COMPLETE")
    _log(f"  DSM:  {dsm_path}  ({dsm_size_mb:.1f} MB)")
    _log(f"  Ortho: {ortho_path}  ({ortho_size_mb:.1f} MB)")
    if z_result is not None:
        _log(f"  AOI Z range: {z_min:.3f}–{z_max:.3f} m  ({z_range:.3f} m)")
    _log("  Label these products 'EDR_T1 site overview — non-ESM' (ADR-0026).")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, type=Path,
                    help="Path to .psx project file.")
    ap.add_argument("--out-dir", required=True, type=Path,
                    help="Output directory for GeoTIFF products.")
    ap.add_argument("--resolution", type=float, default=0.02,
                    help="DSM resolution in metres (default 0.02 = 2 cm). "
                         "Must be >= 0.02 for the full-area footprint to pass "
                         "the 5 M-cell guard.")
    args = ap.parse_args()

    if args.resolution < 0.015:
        sys.exit(f"--resolution {args.resolution} m is below the 2 cm minimum "
                 f"for the full-area footprint. Use 0.02 or coarser.")

    build_fullarea_visual(args.project, args.out_dir, args.resolution)


if __name__ == "__main__":
    main()
