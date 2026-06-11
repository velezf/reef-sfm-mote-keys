#!/usr/bin/env python3
"""diag_transect_z_profile.py — read-only Z-profile diagnostic.

Opens a project (read-only, no save), clips the dense cloud to the transect
XY footprint with a wide Z range (±20 m from centre), exports that subset to
a temporary XYZ text file, then analyses Z distribution along the 10 m axis.

ADR-0026 transect geometry:
  centre:    (-2.028, 3.774, -6.477) LOCAL_CS m
  long axis: (-0.7071, 0.7071, 0)   135° bearing, half-length 5.0 m
  short axis:(-0.7071,-0.7071, 0)   225° bearing, half-width  0.5 m
  ADR Z window: [-9.977, -2.977] m  (ADR-0026 7 m estimate)

Exports a temporary XYZ subset then deletes it.

Usage (EC2 headless, read-only):
    /opt/metashape-pro/metashape.sh -platform offscreen \\
        -r /data/reef-sfm-mote-keys/scripts/metashape/diag_transect_z_profile.py \\
        --project /data/edr_work/edr_t1_postdense_20260610T181702Z.psx
"""
from __future__ import annotations
import sys
import math
import argparse
import tempfile
import os
from pathlib import Path
from datetime import datetime, timezone

import Metashape  # type: ignore

# ADR-0026 geometry (LOCAL_CS metres)
CEN    = (-2.028, 3.774, -6.477)
LONG_HAT  = (-0.7071,  0.7071, 0.0)
SHORT_HAT = (-0.7071, -0.7071, 0.0)
UP_HAT    = ( 0.0,     0.0,    1.0)
HALF_LONG  = 5.0
HALF_SHORT = 0.5
DIAG_HALF_Z = 15.0   # wide Z for diagnosis (±15 m from centre)
ADR_Z_LO   = -9.977
ADR_Z_HI   = -2.977
N_BINS = 10


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _log(msg: str) -> None:
    print(f"[{_ts()}] {msg}", flush=True)


def _make_obb_region(chunk, cen_local, long_hat, short_hat,
                     half_long, half_short, half_z):
    """Set chunk.region to an OBB around the transect XY with ±half_z.

    cen_local, long_hat, short_hat are in LOCAL_CS metres.
    Transforms to internal (chunk) coordinates.
    """
    T = chunk.transform.matrix
    T_inv = T.inv()
    scale = chunk.transform.scale

    def local_to_int(v):
        return T_inv.mulp(Metashape.Vector(v))

    # Centre in internal coords
    cen_int = local_to_int(cen_local)

    # Build OBB rotation: columns = long, short, up axes in internal space
    # We need to map LOCAL_CS unit vectors to internal unit vectors.
    # A LOCAL_CS vector v_local → internal via T_inv (but T_inv includes scale).
    # For a pure direction (no translation), use T_inv applied to (origin + v) - origin.
    origin_int = T_inv.mulp(Metashape.Vector([0, 0, 0]))

    def local_dir_to_int(d):
        p = T_inv.mulp(Metashape.Vector([d[0], d[1], d[2]]))
        return Metashape.Vector([p.x - origin_int.x,
                                  p.y - origin_int.y,
                                  p.z - origin_int.z]).normalized()

    long_int  = local_dir_to_int(long_hat)
    short_int = local_dir_to_int(short_hat)
    up_int    = local_dir_to_int(UP_HAT)

    rot = Metashape.Matrix([
        [long_int.x,  short_int.x,  up_int.x],
        [long_int.y,  short_int.y,  up_int.y],
        [long_int.z,  short_int.z,  up_int.z],
    ])

    size_int = Metashape.Vector([
        2 * half_long  / scale,
        2 * half_short / scale,
        2 * half_z     / scale,
    ])

    reg = chunk.region
    reg.center = cen_int
    reg.rot    = rot
    reg.size   = size_int
    chunk.region = reg


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, type=Path)
    args = ap.parse_args()

    _log(f"Opening {args.project} (read-only diagnostic — no save)")
    doc = Metashape.Document()
    doc.open(str(args.project), read_only=True)

    chunks = [c for c in doc.chunks if c.point_cloud is not None]
    if not chunks:
        sys.exit("No chunk with a dense cloud found.")
    chunk = chunks[0]
    scale = chunk.transform.scale
    n_pts = chunk.point_cloud.point_count
    _log(f"Chunk: {chunk.label}  pts={n_pts:,}  scale={scale:.8f} m/unit  crs={chunk.crs}")

    # Set a wide-Z region around the transect XY footprint
    _log(f"Setting transect XY region with ±{DIAG_HALF_Z} m Z (wide, for diagnosis) …")
    _make_obb_region(chunk, CEN, LONG_HAT, SHORT_HAT,
                     HALF_LONG, HALF_SHORT, DIAG_HALF_Z)
    reg = chunk.region
    _log(f"Region set: centre={reg.center} size={reg.size} (internal units)")

    # Export the clipped subset to a temp file
    tmp_xyz = Path(tempfile.mktemp(suffix="_transect_diag.xyz"))
    _log(f"Exporting clipped cloud → {tmp_xyz} …")
    chunk.exportPointCloud(
        path=str(tmp_xyz),
        source_data=Metashape.PointCloudData,
        clip_to_boundary=True,
        image_format=Metashape.ImageFormatNone,
        save_point_color=False,
        save_point_normal=False,
        save_point_intensity=False,
        crs=chunk.crs,
    )
    _log(f"Export done.  File size: {tmp_xyz.stat().st_size / 1e6:.1f} MB")

    # Parse the XYZ file and project onto transect axes
    T = chunk.transform.matrix
    bins_z = [[] for _ in range(N_BINS)]
    bin_width = (2 * HALF_LONG) / N_BINS
    n_total = 0

    _log("Parsing exported XYZ and binning by transect position …")
    with open(tmp_xyz) as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
            except ValueError:
                continue
            n_total += 1
            dx = x - CEN[0]
            dy = y - CEN[1]
            along = dx*LONG_HAT[0] + dy*LONG_HAT[1]
            if abs(along) > HALF_LONG:
                continue
            bin_idx = min(int((along + HALF_LONG) / bin_width), N_BINS - 1)
            bins_z[bin_idx].append(z)

    tmp_xyz.unlink(missing_ok=True)
    _log(f"Parsed {n_total:,} points from XYZ export.")
    _log("")
    _log("=" * 76)
    _log("Z PROFILE ALONG 10 m TRANSECT (bins 1 m wide, LOCAL_CS metres)")
    _log(f"  ADR-0026 centre Z: {CEN[2]:.3f} m")
    _log(f"  ADR-0026 Z window: [{ADR_Z_LO:.3f}, {ADR_Z_HI:.3f}] m  (7 m)")
    _log("=" * 76)
    _log(f"{'Bin':>4}  {'Along (m)':>12}  {'N pts':>8}  {'Z min':>8}  {'Z median':>9}  {'Z max':>8}  {'in window?':>10}")
    _log("-" * 76)

    all_z = []
    for i, zlist in enumerate(bins_z):
        lo = -HALF_LONG + i * bin_width
        hi = lo + bin_width
        if not zlist:
            _log(f"{i:>4}  [{lo:+5.1f},{hi:+5.1f}]  {'0':>8}  {'—':>8}  {'—':>9}  {'—':>8}  {'NO DATA':>10}")
            continue
        zlist.sort()
        zmin = zlist[0]
        zmax = zlist[-1]
        zmed = zlist[len(zlist)//2]
        in_window = ADR_Z_LO <= zmed <= ADR_Z_HI
        flag = "YES" if in_window else "** OUT **"
        _log(f"{i:>4}  [{lo:+5.1f},{hi:+5.1f}]  {len(zlist):>8}  {zmin:>8.3f}  {zmed:>9.3f}  {zmax:>8.3f}  {flag:>10}")
        all_z.extend(zlist)

    _log("=" * 76)
    if all_z:
        z_surf_min = min(all_z)
        z_surf_max = max(all_z)
        margin = 1.0   # 1 m margin
        z_lo_rec = z_surf_min - margin
        z_hi_rec = z_surf_max + margin
        z_height = z_hi_rec - z_lo_rec
        new_cen_z = (z_lo_rec + z_hi_rec) / 2.0
        _log(f"Full 10×1 m footprint surface Z range: [{z_surf_min:.3f}, {z_surf_max:.3f}] m "
             f"(span {z_surf_max - z_surf_min:.2f} m)")
        _log(f"ADR-0026 window captures: "
             f"[{max(z_surf_min, ADR_Z_LO):.3f}, {min(z_surf_max, ADR_Z_HI):.3f}] m")
        _log(f"Recommended Z window ({margin:.0f} m margin each side):")
        _log(f"  Z lo = {z_lo_rec:.3f} m  Z hi = {z_hi_rec:.3f} m  height = {z_height:.2f} m")
        _log(f"  new centre Z = {new_cen_z:.3f} m  "
             f"(shift from ADR-0026: {new_cen_z - CEN[2]:+.3f} m)")
        _log(f"  → --aoi-height {math.ceil(z_height * 2) / 2:.1f}  (round up to nearest 0.5 m)")
        _log(f"  → updated centre: ({CEN[0]:.3f}, {CEN[1]:.3f}, {new_cen_z:.3f})")

    _log("")
    _log("READ-ONLY diagnostic complete.  No save performed.")


if __name__ == "__main__":
    main()
