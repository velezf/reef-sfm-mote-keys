#!/usr/bin/env python3
"""t1_set_region.py — Derive and set chunk.region for EDR_T1 dense reconstruction.

Computes AABB in leveled world space from camera positions + sparse tie points.
Z: [0.5, 99.5] percentile trim on sparse. XY: cameras ∪ Z-trimmed sparse.
0.75 m margin all axes. Backs up .psx before any write.

Usage: metashape.sh -platform offscreen -r probes/t1_set_region.py <project.psx>
"""
from __future__ import annotations
import datetime, math, os, shutil, sys
from pathlib import Path
import Metashape


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return float("nan")
    n = len(sorted_vals)
    idx = p / 100.0 * (n - 1)
    lo, hi = int(idx), min(int(idx) + 1, n - 1)
    return sorted_vals[lo] * (1 - (idx - lo)) + sorted_vals[hi] * (idx - lo)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: t1_set_region.py <project.psx>")
        sys.exit(1)
    psx = sys.argv[1]
    psx_path = Path(psx)

    # ── Pre-write backup ─────────────────────────────────────────────────────
    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    bak_psx   = psx_path.with_name(f"edr_t1_preregion_{ts}.psx")
    bak_files = psx_path.with_name(f"edr_t1_preregion_{ts}.files")
    live_files = psx_path.with_name(psx_path.stem + ".files")
    print(f"Pre-write backup → {bak_psx}")
    shutil.copy2(psx, bak_psx)
    if live_files.exists():
        shutil.copytree(live_files, bak_files, symlinks=True)
    print(f"  .psx  {bak_psx.stat().st_size:,} bytes")
    print(f"  .files backed up OK")
    print()

    # ── Open for write + read_only guard ─────────────────────────────────────
    doc = Metashape.Document()
    doc.open(psx, read_only=False)
    if doc.read_only:
        print("ABORT: document opened read-only — stale lock present. Fix and retry.")
        sys.exit(1)
    chunk = doc.chunks[0]
    T     = chunk.transform.matrix
    T_inv = T.inv()
    scale = math.sqrt(T[0, 0] ** 2 + T[1, 0] ** 2 + T[2, 0] ** 2)

    print(f"chunk : {chunk.label}")
    print(f"scale : {scale:.6f} m/internal_unit")
    print(f"read_only: {doc.read_only}")
    print()

    # ── Collect camera world positions ────────────────────────────────────────
    cam_pts: list[tuple[float, float, float]] = []
    for cam in chunk.cameras:
        if cam.transform is None:
            continue
        cp = T.mulp(cam.transform.mulp(Metashape.Vector([0.0, 0.0, 0.0])))
        cam_pts.append((cp.x, cp.y, cp.z))
    print(f"Cameras with transform: {len(cam_pts)}")

    # ── Collect sparse tie-point world positions ──────────────────────────────
    tp_pts: list[tuple[float, float, float]] = []
    tp = chunk.tie_points
    if tp and tp.points:
        for pt in tp.points:
            if not pt.valid:
                continue
            w = T.mulp(Metashape.Vector([pt.coord.x, pt.coord.y, pt.coord.z]))
            tp_pts.append((w.x, w.y, w.z))
    print(f"Valid tie points: {len(tp_pts):,}")
    print()

    # ── Z trim [0.5, 99.5] on sparse ─────────────────────────────────────────
    MARGIN = 0.75
    Z_LO_PCT, Z_HI_PCT   = 0.5, 99.5
    XY_LO_PCT, XY_HI_PCT = 0.5, 99.5

    tp_z_sorted = sorted(p[2] for p in tp_pts)
    z_lo_trim = _percentile(tp_z_sorted, Z_LO_PCT)
    z_hi_trim = _percentile(tp_z_sorted, Z_HI_PCT)

    # XY: cameras ∪ Z-trimmed sparse, then [0.5,99.5] percentile trim on XY
    tp_trimmed = [p for p in tp_pts if z_lo_trim <= p[2] <= z_hi_trim]
    all_xy_pts = [(p[0], p[1]) for p in cam_pts] + [(p[0], p[1]) for p in tp_trimmed]

    xs = sorted(p[0] for p in all_xy_pts)
    ys = sorted(p[1] for p in all_xy_pts)
    x_lo_trim = _percentile(xs, XY_LO_PCT)
    x_hi_trim = _percentile(xs, XY_HI_PCT)
    y_lo_trim = _percentile(ys, XY_LO_PCT)
    y_hi_trim = _percentile(ys, XY_HI_PCT)

    # Final world-space AABB with margin
    box_x_lo = x_lo_trim - MARGIN;  box_x_hi = x_hi_trim + MARGIN
    box_y_lo = y_lo_trim - MARGIN;  box_y_hi = y_hi_trim + MARGIN
    box_z_lo = z_lo_trim  - MARGIN;  box_z_hi = z_hi_trim  + MARGIN

    sx = box_x_hi - box_x_lo
    sy = box_y_hi - box_y_lo
    sz = box_z_hi - box_z_lo
    cx = (box_x_lo + box_x_hi) / 2
    cy = (box_y_lo + box_y_hi) / 2
    cz = (box_z_lo + box_z_hi) / 2

    print("=== DERIVED REGION (world space, metres) ===")
    print(f"  Z trim input  : P{Z_LO_PCT} = {z_lo_trim:.3f} m,  P{Z_HI_PCT} = {z_hi_trim:.3f} m")
    print(f"  X  [{box_x_lo:+.3f}, {box_x_hi:+.3f}]   extent {sx:.3f} m")
    print(f"  Y  [{box_y_lo:+.3f}, {box_y_hi:+.3f}]   extent {sy:.3f} m")
    print(f"  Z  [{box_z_lo:+.3f}, {box_z_hi:+.3f}]   extent {sz:.3f} m")
    print(f"  center (world): ({cx:.3f}, {cy:.3f}, {cz:.3f})")
    print()

    # ── Build region in chunk space ───────────────────────────────────────────
    # Center: T_inv maps world → chunk
    center_chunk = T_inv.mulp(Metashape.Vector([cx, cy, cz]))

    # Rotation: columns = world-axis directions in chunk space
    # T_inv col i (normalized) = chunk-space unit vector for world axis i
    def _world_axis_in_chunk(i: int) -> Metashape.Vector:
        v = Metashape.Vector([T_inv[0, i], T_inv[1, i], T_inv[2, i]])
        L = math.sqrt(v.x ** 2 + v.y ** 2 + v.z ** 2) or 1.0
        return Metashape.Vector([v.x / L, v.y / L, v.z / L])

    col0 = _world_axis_in_chunk(0)  # world-X in chunk
    col1 = _world_axis_in_chunk(1)  # world-Y in chunk
    col2 = _world_axis_in_chunk(2)  # world-Z in chunk

    rot33 = Metashape.Matrix([
        [col0.x, col1.x, col2.x],
        [col0.y, col1.y, col2.y],
        [col0.z, col1.z, col2.z],
    ])

    # Size in chunk units (world metres / scale)
    size_chunk = Metashape.Vector([sx / scale, sy / scale, sz / scale])

    chunk.region.center = center_chunk
    chunk.region.rot    = rot33
    chunk.region.size   = size_chunk

    # ── Coverage verification ─────────────────────────────────────────────────
    def _in_box(px: float, py: float, pz: float) -> bool:
        return (box_x_lo <= px <= box_x_hi and
                box_y_lo <= py <= box_y_hi and
                box_z_lo <= pz <= box_z_hi)

    # Z-trimmed sparse coverage (the set used to define the box)
    n_trim = len(tp_trimmed)
    n_trim_in  = sum(1 for p in tp_trimmed if _in_box(*p))
    n_trim_out = n_trim - n_trim_in
    pct_trim   = 100.0 * n_trim_in / n_trim if n_trim else 0.0

    # All sparse coverage (Z-outliers will be outside by construction)
    n_all_tp   = len(tp_pts)
    n_all_in   = sum(1 for p in tp_pts if _in_box(*p))
    n_all_out  = n_all_tp - n_all_in
    pct_all    = 100.0 * n_all_in / n_all_tp if n_all_tp else 0.0

    # Camera coverage (informational)
    n_cam = len(cam_pts)
    n_cam_in  = sum(1 for p in cam_pts if _in_box(*p))
    n_cam_out = n_cam - n_cam_in

    print("=== COVERAGE ===")
    print(f"  trimmed sparse : {n_trim_in:,} / {n_trim:,} inside  "
          f"({pct_trim:.4f}%)  [{n_trim_out} outside]  "
          f"[{'PASS ≥99%' if pct_trim >= 99.0 else f'FAIL < 99%'}]")
    print(f"  all sparse     : {n_all_in:,} / {n_all_tp:,} inside  "
          f"({pct_all:.4f}%)  [{n_all_out} outside]  "
          f"(Z-tail points expected outside)")
    print(f"  cameras        : {n_cam_in} / {n_cam} inside  "
          f"({n_cam_out} outside — informational, expected on sloped transect)")
    print()

    if pct_trim < 99.0:
        print(f"ABORT: trimmed sparse coverage {pct_trim:.2f}% < 99%. Region NOT saved.")
        sys.exit(1)

    # ── Save + verify ─────────────────────────────────────────────────────────
    mtime_before = os.path.getmtime(psx)
    doc.save()
    mtime_after = os.path.getmtime(psx)
    if not mtime_after > mtime_before:
        print("ABORT: save did not advance mtime — write may have failed.")
        sys.exit(1)

    print("=== SAVE ===")
    print(f"  mtime {mtime_before:.0f} → {mtime_after:.0f}  (advanced ✓)")
    print()
    print("=== REGION SUMMARY ===")
    print(f"  X extent : {sx:.3f} m")
    print(f"  Y extent : {sy:.3f} m")
    print(f"  Z extent : {sz:.3f} m  (expected 14–16 m)")
    print(f"  Volume   : {sx * sy * sz:.1f} m³")
    print()
    print("STOP — region set. No dense launched.")


if __name__ == "__main__":
    main()
