#!/usr/bin/env python3
"""build_fullarea_visual.py — full-area site-overview DEM and orthomosaic.

Non-ESM, non-destructive: no point-cloud write, no region crop.  Run BEFORE
stage_aoi, which crops the cloud to the 10×1 m transect.

Products written to <out-dir>/:
    edr_t1_fullarea_dsm_<UTC>.tif   — 2 cm DEM, GeoTIFF
    edr_t1_fullarea_ortho_<UTC>.tif — 2 cm ortho, GeoTIFF (on DEM surface)

Usage (EC2 headless):
    /opt/metashape-pro/metashape.sh -platform offscreen \\
        -r /data/reef-sfm-mote-keys/scripts/metashape/build_fullarea_visual.py \\
        --project /data/edr_work/edr_t1.psx \\
        --out-dir /data/edr_work/products/EDR_T1 \\
        --resolution 0.02

After completion, the reported AOI Z range replaces the ADR-0026 model estimate.
Adjust --aoi-height in stage_aoi if local relief exceeds 5.4 m (7 m window).

IMPORTANT: do NOT call _local_planar_projection (which sets chunk.crs) when the
dense cloud is already loaded.  Setting chunk.crs on a 487M-pt cloud triggers an
expensive internal reprojection — even if the new CRS is identical to the old one.
chunk.crs is already LOCAL (set by stage_scale before dense was built).
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import Metashape  # type: ignore

# ---------------------------------------------------------------------------
# ADR-0026 AOI footprint — used for Z-range sampling from the full-area DEM
# Centre (−2.028, 3.774); long axis 135° → unit (−0.7071, 0.7071)
# Short axis 225° → unit (−0.7071, −0.7071); half-extents (5.0, 0.5) m
# ---------------------------------------------------------------------------
_AOI_CENTRE_XY = (-2.028, 3.774)
_AOI_LONG_UNIT = (-0.7071, 0.7071)
_AOI_SHORT_UNIT = (-0.7071, -0.7071)
_AOI_HALF_LEN = 5.0
_AOI_HALF_WID = 0.5

# Guard: abort if the DEM would exceed this cell count (ADR-0027 5M guard)
_MAX_DEM_CELLS = 5_000_000

# Metashape DEM no-data sentinel
_NODATA = -1e38


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _local_planar_proj_from_existing_crs(
        chunk: "Metashape.Chunk") -> "Metashape.OrthoProjection":
    """Build a top-down Planar OrthoProjection from the EXISTING chunk.crs.

    Does NOT assign chunk.crs — assigning it when the dense cloud is present
    triggers an expensive 487M-pt reprojection even when the new CRS equals the
    old one.  chunk.crs is already LOCAL (set by stage_scale, ADR-0024); we just
    read it here.
    """
    top_xy = Metashape.Matrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    origin = chunk.transform.matrix.mulp(Metashape.Vector([0, 0, 0]))
    lf = chunk.crs.localframe(origin)
    proj = Metashape.OrthoProjection()
    proj.crs = chunk.crs
    proj.type = Metashape.OrthoProjection.Type.Planar
    proj.matrix = (Metashape.Matrix.Rotation(top_xy)
                   * Metashape.Matrix.Rotation(lf.rotation()))
    _log(f"{chunk.label}: OrthoProjection built from existing chunk.crs={chunk.crs} "
         f"(LOCAL, ADR-0020/0024 — NOT re-set to avoid 487M-pt reprojection)")
    return proj


def _assert_writable(doc: "Metashape.Document") -> None:
    if doc.read_only:
        sys.exit("Project opened read-only (stale lock?). Aborting.")


def _verify_save(doc: "Metashape.Document", path: Path) -> None:
    mtime_before = path.stat().st_mtime if path.exists() else 0.0
    doc.save()
    mtime_after = path.stat().st_mtime if path.exists() else 0.0
    if mtime_after <= mtime_before:
        sys.exit(f"save() did not advance mtime on {path}.")
    _log(f"Project saved + mtime verified ({int(mtime_after)}).")


def _sample_aoi_z(el: "Metashape.Elevation") -> tuple[float, float] | None:
    """Sample DEM altitudes on a grid inside the ADR-0026 AOI footprint."""
    lx, ly = _AOI_LONG_UNIT
    sx, sy = _AOI_SHORT_UNIT
    cx, cy = _AOI_CENTRE_XY
    z_vals = []
    for t in range(-5, 6):          # 1 m steps along long axis (±5 m = ±half_len)
        for s_tenth in range(-5, 6, 2):   # 0.2 m steps across (±0.4 m < half_wid 0.5)
            s = s_tenth * 0.1
            x = cx + t * lx + s * sx
            y = cy + t * ly + s * sy
            z = el.altitude(Metashape.Vector([x, y]))
            if z is not None and z > _NODATA:
                z_vals.append(z)
    return (min(z_vals), max(z_vals)) if z_vals else None


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
    _log(f"Chunk: {chunk.label}  pts={chunk.point_cloud.point_count:,}  "
         f"scale={chunk.transform.scale:.8f} m/unit  crs={chunk.crs}")

    # --- Full-cloud region (not the transect bbox) ---
    chunk.resetRegion()
    scale = chunk.transform.scale
    reg = chunk.region
    world_x = reg.size.x * scale
    world_y = reg.size.y * scale
    pred_cells = int((world_x / resolution) * (world_y / resolution))
    _log(f"Full-area footprint: {world_x:.2f} × {world_y:.2f} m  "
         f"→ predicted DEM cells @ {resolution*100:.0f} cm: {pred_cells:,}")
    if pred_cells > _MAX_DEM_CELLS:
        sys.exit(f"Predicted cell count {pred_cells:,} exceeds guard {_MAX_DEM_CELLS:,}. "
                 f"Increase --resolution (≥ 0.03) or raise the guard.")

    # --- OrthoProjection from existing LOCAL crs (do NOT assign chunk.crs) ---
    proj = _local_planar_proj_from_existing_crs(chunk)

    # --- Build full-area DEM ---
    _log(f"Building full-area DEM @ {resolution*100:.0f} cm ...")
    t0 = time.time()
    chunk.buildDem(
        source_data=Metashape.PointCloudData,
        interpolation=Metashape.EnabledInterpolation,
        projection=proj,
        resolution=resolution,
    )
    _log(f"buildDem returned ({time.time()-t0:.1f} s)")
    el = chunk.elevation
    _log(f"chunk.elevation: {el}")
    if el is None:
        sys.exit("buildDem returned no elevation object — cannot export DSM or "
                 "sample Z range.")
    _log(f"DEM: {el.width} × {el.height} = {el.width*el.height:,} cells")

    # --- Z range within ADR-0026 AOI footprint ---
    _log("Sampling DEM Z in AOI footprint ...")
    z_result = _sample_aoi_z(el)
    if z_result is not None:
        z_min, z_max = z_result
        z_range = z_max - z_min
        _log(f"AOI Z: {z_min:.3f}–{z_max:.3f} m  range={z_range:.3f} m  "
             f"(ADR-0026 window=7.0 m — {'OK margin='+f'{7.0-z_range:.2f}m' if z_range<=7.0 else 'WARNING EXCEEDS WINDOW'})")
    else:
        z_result = None
        _log("WARNING: no valid DEM cells in AOI footprint. Z range not confirmed.")

    # --- Export DEM ---
    _log(f"Exporting DSM → {dsm_path} ...")
    chunk.exportRaster(path=str(dsm_path),
                       source_data=Metashape.ElevationData,
                       image_format=Metashape.ImageFormatTIFF,
                       save_alpha=False)
    dsm_mb = dsm_path.stat().st_size / 1e6
    _log(f"DSM exported: {dsm_mb:.1f} MB")

    # --- Build full-area orthomosaic on the DEM surface ---
    _log(f"Building full-area ortho @ {resolution*100:.0f} cm (DEM surface) ...")
    t0 = time.time()
    chunk.buildOrthomosaic(
        surface_data=Metashape.ElevationData,
        blending_mode=Metashape.MosaicBlending,
        fill_holes=True,
        resolution=resolution,
        projection=proj,
    )
    _log(f"buildOrthomosaic returned ({time.time()-t0:.1f} s)")
    ortho = chunk.orthomosaic
    if ortho is None:
        sys.exit("buildOrthomosaic returned no orthomosaic object.")
    _log(f"Ortho: {ortho.width} × {ortho.height} px  "
         f"res={ortho.resolution:.4f} m/px")

    # --- Export ortho ---
    _log(f"Exporting ortho → {ortho_path} ...")
    chunk.exportRaster(path=str(ortho_path),
                       source_data=Metashape.OrthomosaicData,
                       image_format=Metashape.ImageFormatTIFF,
                       save_alpha=False)
    ortho_mb = ortho_path.stat().st_size / 1e6
    _log(f"Ortho exported: {ortho_mb:.1f} MB")

    # --- Save ---
    _verify_save(doc, project_path)

    _log("=" * 60)
    _log("Full-area visual COMPLETE")
    _log(f"  DSM:   {dsm_path}  ({dsm_mb:.1f} MB)")
    _log(f"  Ortho: {ortho_path}  ({ortho_mb:.1f} MB)")
    if z_result is not None:
        _log(f"  AOI Z range confirmed: {z_min:.3f}–{z_max:.3f} m  ({z_range:.3f} m)")
    _log("  Non-ESM site-overview products (ADR-0026).")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--resolution", type=float, default=0.02,
                    help="DEM and ortho resolution in metres (default 0.02 = 2 cm).")
    args = ap.parse_args()

    if args.resolution < 0.015:
        sys.exit(f"--resolution {args.resolution} m is below 1.5 cm minimum. "
                 f"Full-area at 2 cm gives ~1.84M cells (well under 5M guard).")

    build_fullarea_visual(args.project, args.out_dir, args.resolution)


if __name__ == "__main__":
    main()
