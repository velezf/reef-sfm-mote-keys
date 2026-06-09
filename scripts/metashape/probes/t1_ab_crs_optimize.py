#!/usr/bin/env python3
"""t1_ab_crs_optimize.py — A/B: does LOCAL_CS + disabled refs fix the optimize divergence?

ARM A (datum as-is): open a copy, run Logan's exact optimizeCameras call.
ARM B (fix): open a copy, set LOCAL_CS + disable ALL marker/camera reference.enabled,
             same optimizeCameras call.

Copies only — the live PSX is never opened. No saves to the live project.

Usage:
    metashape.sh -platform offscreen -r t1_ab_crs_optimize.py <project.psx> <ab_workdir>

Where <ab_workdir> is a writable scratch directory (will be created if needed).
Copies are made there and cleaned up after reporting.
"""
import math
import os
import shutil
import sys

import Metashape

LOCAL_CS_WKT = (
    'LOCAL_CS["Local Coordinates (m)",LOCAL_DATUM["Local Datum",0],'
    'UNIT["metre",1]]'
)

# Logan's exact optimizeCameras kwargs (Logan maps cal_* dict -> fit_* kwargs internally;
# see Align_RuPaRe_v2_Metashape.py lines 547-558 / 701-712).
LOGAN_CAM_OPT = {
    "fit_f": True, "fit_cx": True, "fit_cy": True,
    "fit_k1": True, "fit_k2": True, "fit_k3": True, "fit_p1": True, "fit_p2": True,
    "fit_b1": False, "fit_b2": False, "fit_k4": False,
    "fit_corrections": False,
}


def _mat_scale(m):
    try:
        return math.sqrt(m[0, 0] ** 2 + m[1, 0] ** 2 + m[2, 0] ** 2)
    except Exception:
        return None


def _reprojection_stats(chunk):
    """Return (median, max, n) of tie-point reprojection filter values.
    Uses TiePoints.Filter (same API as run_pipeline._reprojection_rms).
    Values are in Metashape filter units (valid for before/after comparison).
    """
    tp = chunk.tie_points
    if tp is None or not tp.points:
        return None, None, 0
    try:
        f = Metashape.TiePoints.Filter()
        f.init(chunk, criterion=Metashape.TiePoints.Filter.ReprojectionError)
        vals = sorted(f.values)
    except Exception as exc:
        return f"ERR:{exc}", f"ERR:{exc}", 0
    if not vals:
        return None, None, 0
    n = len(vals)
    median = vals[n // 2]
    return median, vals[-1], n


def _copy_project(src_psx, dst_psx):
    """Copy a .psx + its .files directory to dst_psx (parallel .files dir)."""
    shutil.copy2(src_psx, dst_psx)
    src_files = src_psx.replace(".psx", ".files")
    dst_files = dst_psx.replace(".psx", ".files")
    if os.path.isdir(src_files):
        shutil.copytree(src_files, dst_files)


def run_arm(label, psx, setup_fn=None):
    """Open psx, optionally call setup_fn(chunk), run Logan optimize, report."""
    print(f"\n{'=' * 60}")
    print(f"ARM {label}: {psx}")
    print(f"{'=' * 60}")

    doc = Metashape.Document()
    doc.open(psx)
    # Must NOT be read_only — we're optimizing in memory
    assert not doc.read_only, f"ARM {label}: unexpected read_only open"

    chunk = doc.chunks[0]
    print(f"  chunk.label   : {chunk.label}")
    print(f"  chunk.crs     : {chunk.crs} / authority={chunk.crs.authority!r}")

    def _fmt(v):
        if v is None:
            return "N/A"
        if isinstance(v, float):
            return f"{v:.6g}"
        return str(v)

    # baseline reprojection (pre-optimize)
    med_pre, max_pre, n_pre = _reprojection_stats(chunk)
    sc_pre = _mat_scale(chunk.transform.matrix)
    print(f"  PRE-optimize  : transform.scale={_fmt(sc_pre)}"
          f"  median={_fmt(med_pre)}  max={_fmt(max_pre)}  n={n_pre}")

    if setup_fn is not None:
        setup_fn(chunk)
        print(f"  POST-setup crs: {chunk.crs} / authority={chunk.crs.authority!r}")

    # Logan's exact optimizeCameras call
    try:
        chunk.optimizeCameras(**LOGAN_CAM_OPT)
        print("  optimizeCameras: COMPLETED")
    except Exception as exc:
        print(f"  optimizeCameras: EXCEPTION — {exc}")

    # post-optimize
    med_post, max_post, n_post = _reprojection_stats(chunk)
    sc_post = _mat_scale(chunk.transform.matrix)
    print(f"  POST-optimize : transform.scale={_fmt(sc_post)}"
          f"  median={_fmt(med_post)}  max={_fmt(max_post)}  n={n_post}")
    print(f"  chunk.crs     : {chunk.crs}")

    doc.clear()  # release without saving
    return sc_post, med_post, max_post


def setup_arm_b(chunk):
    """ARM B fix: LOCAL_CS + disable all marker and camera reference locations."""
    chunk.crs = Metashape.CoordinateSystem(LOCAL_CS_WKT)
    disabled_markers, disabled_cameras = 0, 0
    for m in chunk.markers:
        if m.reference is not None and m.reference.enabled:
            m.reference.enabled = False
            disabled_markers += 1
    for c in chunk.cameras:
        if c.reference is not None and c.reference.enabled:
            c.reference.enabled = False
            disabled_cameras += 1
    print(f"  ARM B setup   : LOCAL_CS set; disabled {disabled_markers} marker refs, "
          f"{disabled_cameras} camera refs (scale bars untouched)")


def main():
    if len(sys.argv) < 3:
        print("Usage: t1_ab_crs_optimize.py <project.psx> <ab_workdir>")
        sys.exit(1)

    src_psx = sys.argv[-2]
    workdir = sys.argv[-1]
    os.makedirs(workdir, exist_ok=True)

    psx_a = os.path.join(workdir, "copy_arm_a.psx")
    psx_b = os.path.join(workdir, "copy_arm_b.psx")

    print(f"Source PSX : {src_psx}")
    print(f"Work dir   : {workdir}")
    print(f"Copying to {psx_a} ...")
    _copy_project(src_psx, psx_a)
    print(f"Copying to {psx_b} ...")
    _copy_project(src_psx, psx_b)
    print("Copies ready. Starting arms.")

    sc_a, med_a, max_a = run_arm("A (datum as-is)", psx_a, setup_fn=None)
    sc_b, med_b, max_b = run_arm("B (LOCAL_CS + refs disabled)", psx_b, setup_fn=setup_arm_b)

    def _fmt(v):
        if v is None:
            return "N/A"
        if isinstance(v, float):
            return f"{v:.6g}"
        return str(v)

    print(f"\n{'=' * 60}")
    print("COMPARISON SUMMARY")
    print(f"{'=' * 60}")
    print(f"ARM A: transform.scale={_fmt(sc_a)}  median={_fmt(med_a)}  max={_fmt(max_a)}")
    print(f"ARM B: transform.scale={_fmt(sc_b)}  median={_fmt(med_b)}  max={_fmt(max_b)}")

    print(f"\nCleaning up copies in {workdir} ...")
    shutil.rmtree(workdir, ignore_errors=True)
    print("Done. Copies removed.")


if __name__ == "__main__":
    main()
