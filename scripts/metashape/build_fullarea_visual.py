#!/usr/bin/env python3
"""build_fullarea_visual.py — full-area site-overview orthomosaic.

Non-ESM, non-destructive: no point-cloud write, no region crop.  Run BEFORE
stage_aoi, which crops the cloud to the 10×1 m transect.

Product written to <out-dir>/:
    edr_t1_fullarea_ortho_<UTC>.tif  — 2 cm ortho, GeoTIFF

Usage (EC2 headless):
    /opt/metashape-pro/metashape.sh -platform offscreen \\
        -r /data/reef-sfm-mote-keys/scripts/metashape/build_fullarea_visual.py \\
        --project /data/edr_work/edr_t1.psx \\
        --out-dir /data/edr_work/products/EDR_T1 \\
        --resolution 0.02

Z RANGE NOTE: buildDem on the full 487M-pt cloud hangs indefinitely post-pyramid
(confirmed across 3 runs — Metashape 2.3.1 computes expensive per-point stats
after the rasterize/pyramid step).  The fullarea DEM is therefore skipped; this
script builds the ortho from PointCloudData directly.  The ADR-0026 7 m Z window
remains the accepted estimate; it will be confirmed from the transect DSM after
stage_aoi crops the cloud.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import Metashape  # type: ignore


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
    old one.  chunk.crs is already LOCAL (set by stage_scale, ADR-0024).
    """
    top_xy = Metashape.Matrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    origin = chunk.transform.matrix.mulp(Metashape.Vector([0, 0, 0]))
    lf = chunk.crs.localframe(origin)
    proj = Metashape.OrthoProjection()
    proj.crs = chunk.crs
    proj.type = Metashape.OrthoProjection.Type.Planar
    proj.matrix = (Metashape.Matrix.Rotation(top_xy)
                   * Metashape.Matrix.Rotation(lf.rotation()))
    _log(f"{chunk.label}: OrthoProjection from existing crs={chunk.crs} "
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


def build_fullarea_visual(project_path: Path, out_dir: Path,
                          resolution: float) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = _utcnow()
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
    _log(f"Full-area footprint: {world_x:.2f} × {world_y:.2f} m  "
         f"(ortho @ {resolution*100:.0f} cm)")

    # --- OrthoProjection from existing LOCAL crs (do NOT assign chunk.crs) ---
    proj = _local_planar_proj_from_existing_crs(chunk)

    # NOTE: buildDem on 487M pts hangs indefinitely post-pyramid in Metashape 2.3.1
    # (confirmed 3 independent runs; see script docstring).  Building ortho from
    # PointCloudData directly avoids the hang while still producing a valid
    # site-overview product.

    # --- Build full-area orthomosaic from point cloud surface ---
    _log(f"Building full-area ortho @ {resolution*100:.0f} cm "
         f"(PointCloudData surface) ...")
    t0 = time.time()
    chunk.buildOrthomosaic(
        surface_data=Metashape.PointCloudData,
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
    _log(f"Exporting → {ortho_path} ...")
    chunk.exportRaster(path=str(ortho_path),
                       source_data=Metashape.OrthomosaicData,
                       image_format=Metashape.ImageFormatTIFF,
                       save_alpha=False)
    ortho_mb = ortho_path.stat().st_size / 1e6
    _log(f"Exported: {ortho_mb:.1f} MB")

    # --- Save ---
    _verify_save(doc, project_path)

    _log("=" * 60)
    _log("Full-area visual COMPLETE")
    _log(f"  Ortho: {ortho_path}  ({ortho_mb:.1f} MB)")
    _log(f"  {ortho.width}×{ortho.height} px  res={ortho.resolution:.4f} m/px")
    _log("  Non-ESM site-overview product (ADR-0026).")
    _log("  Z range: ADR-0026 7 m window accepted; confirm from transect DSM.")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--resolution", type=float, default=0.02,
                    help="Ortho resolution in metres (default 0.02 = 2 cm). "
                         "Do NOT use 0 (native GSD) — sub-mm would never finish.")
    args = ap.parse_args()

    if args.resolution < 0.005:
        sys.exit(f"--resolution {args.resolution} m is below 5 mm. "
                 f"Use 0.02 (2 cm) for the full-area site overview.")

    build_fullarea_visual(args.project, args.out_dir, args.resolution)


if __name__ == "__main__":
    main()
