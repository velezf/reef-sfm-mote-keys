#!/usr/bin/env python3
"""t1_camz_diag.py — Read-only diagnostic for camera-Z spread classification.

Classifies 14.78 m camera-Z range as real topography vs outliers/distortion.
Usage: metashape.sh -platform offscreen -r probes/t1_camz_diag.py <project.psx>
"""
from __future__ import annotations
import math, sys
from pathlib import Path
import Metashape

def _percentile(sorted_vals, p):
    if not sorted_vals:
        return float("nan")
    n = len(sorted_vals)
    idx = p / 100.0 * (n - 1)
    lo, hi = int(idx), min(int(idx) + 1, n - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac

def _fit_plane(pts):
    """Fit plane z = ax + by + c via least squares. Returns (a,b,c,r2,rms,slope_deg)."""
    n = len(pts)
    if n < 3:
        return None
    sx = sum(p[0] for p in pts); sy = sum(p[1] for p in pts); sz = sum(p[2] for p in pts)
    sxx = sum(p[0]**2 for p in pts); syy = sum(p[1]**2 for p in pts)
    sxy = sum(p[0]*p[1] for p in pts)
    sxz = sum(p[0]*p[2] for p in pts); syz = sum(p[1]*p[2] for p in pts)
    mx = sx/n; my = sy/n; mz = sz/n
    # Normal equations for z = ax + by + c
    A = [[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, float(n)]]
    b = [sxz, syz, sz]
    # 3x3 solve via Cramer
    def det3(M):
        return (M[0][0]*(M[1][1]*M[2][2]-M[1][2]*M[2][1])
               -M[0][1]*(M[1][0]*M[2][2]-M[1][2]*M[2][0])
               +M[0][2]*(M[1][0]*M[2][1]-M[1][1]*M[2][0]))
    d = det3(A)
    if abs(d) < 1e-30:
        return None
    def col_replace(M, col, v):
        import copy; M2 = [list(r) for r in M]
        for i in range(3): M2[i][col] = v[i]
        return M2
    a = det3(col_replace(A, 0, b)) / d
    bv = det3(col_replace(A, 1, b)) / d
    c = det3(col_replace(A, 2, b)) / d
    # R² and RMS residual
    z_pred = [a*p[0] + bv*p[1] + c for p in pts]
    ss_res = sum((pts[i][2] - z_pred[i])**2 for i in range(n))
    ss_tot = sum((p[2] - mz)**2 for p in pts)
    r2 = 1.0 - ss_res/ss_tot if ss_tot > 0 else 0.0
    rms = math.sqrt(ss_res / n)
    slope_deg = math.degrees(math.atan(math.sqrt(a**2 + bv**2)))
    return a, bv, c, r2, rms, slope_deg

def main():
    if len(sys.argv) < 2:
        print("Usage: t1_camz_diag.py <project.psx>"); sys.exit(1)
    doc = Metashape.Document()
    doc.open(sys.argv[1], read_only=True)
    chunk = doc.chunks[0]
    T = chunk.transform.matrix

    print("=== T1 CAMERA-Z DIAGNOSTIC ===")
    print(f"project  : {sys.argv[1]}")
    print(f"chunk    : {chunk.label}")
    print()

    # ── 1. Camera world positions ────────────────────────────────────────────
    cam_pts = []
    for cam in chunk.cameras:
        if cam.transform is None:
            continue
        cp = T.mulp(cam.transform.mulp(Metashape.Vector([0.0, 0.0, 0.0])))
        cam_pts.append([cp.x, cp.y, cp.z])

    cam_z = sorted(p[2] for p in cam_pts)
    n = len(cam_z)
    pcts = [0, 1, 5, 25, 50, 75, 95, 99, 100]
    labels = ["min", "P1", "P5", "P25", "median", "P75", "P95", "P99", "max"]
    vals = [_percentile(cam_z, p) for p in pcts]
    mean_z = sum(cam_z) / n
    std_z = math.sqrt(sum((z - mean_z)**2 for z in cam_z) / n)
    full_range = cam_z[-1] - cam_z[0]
    p5_p95 = vals[labels.index("P95")] - vals[labels.index("P5")]

    print("=== 1. CAMERA-Z DISTRIBUTION ===")
    for lbl, v in zip(labels, vals):
        print(f"  {lbl:8s}: {v:+.3f} m")
    print(f"  std      : {std_z:.3f} m")
    print(f"  full range (max-min): {full_range:.3f} m")
    print(f"  P5–P95 spread       : {p5_p95:.3f} m")
    ratio = p5_p95 / full_range if full_range > 0 else 0
    classification_hint = "outlier-dominated tails" if ratio < 0.5 else "genuine spread"
    print(f"  P5–P95 / full range : {ratio:.2f}  → {classification_hint}")
    print()

    # ── 2. Plane fit to camera XYZ ───────────────────────────────────────────
    print("=== 2. PLANE FIT TO CAMERA CENTERS ===")
    result = _fit_plane(cam_pts)
    if result:
        a, bv, c, r2, rms, slope_deg = result
        print(f"  z = {a:.4f}*x + {bv:.4f}*y + {c:.4f}")
        print(f"  R²             : {r2:.4f}")
        print(f"  residual RMS   : {rms:.3f} m")
        print(f"  implied slope  : {slope_deg:.2f}°")
        if r2 > 0.85 and rms < 2.0:
            print("  → high R², low residual: consistent with smooth topographic gradient")
        elif r2 < 0.5:
            print("  → low R²: camera distribution not planar (scattered or distorted)")
        else:
            print("  → moderate R²: partial structure")
    else:
        print("  plane fit failed")
    print()

    # ── 3. Sparse tie-point Z extent (1–99 pct trim) ────────────────────────
    print("=== 3. SPARSE TIE-POINT Z (1–99 PCT TRIM) ===")
    tp = chunk.tie_points
    if tp and tp.points:
        pt_z = []
        for pt in tp.points:
            if not pt.valid:
                continue
            w = T.mulp(Metashape.Vector([pt.coord.x, pt.coord.y, pt.coord.z]))
            pt_z.append(w.z)
        pt_z.sort()
        n_tp = len(pt_z)
        tp_p1  = _percentile(pt_z, 1)
        tp_p99 = _percentile(pt_z, 99)
        tp_spread = tp_p99 - tp_p1
        print(f"  n valid points : {n_tp:,}")
        print(f"  P1             : {tp_p1:+.3f} m")
        print(f"  P99            : {tp_p99:+.3f} m")
        print(f"  P1–P99 spread  : {tp_spread:.3f} m  (reef surface relief estimate)")
        print(f"  vs camera P5–P95 spread: {p5_p95:.3f} m")
        if tp_spread > 0:
            r = p5_p95 / tp_spread
            print(f"  camera/tiepoint spread ratio: {r:.2f}"
                  f"  ({'consistent — cameras track reef relief' if 0.5 < r < 3.0 else 'inconsistent — investigate'})")
    else:
        print("  no tie points available")
    print()

    # ── 4. Full marker-Z range ───────────────────────────────────────────────
    print("=== 4. MARKER-Z RANGE ===")
    mk_z = []
    mk_xy = {}
    for m in chunk.markers:
        if m.position is None:
            continue
        w = T.mulp(Metashape.Vector([m.position.x, m.position.y, m.position.z]))
        mk_z.append(w.z)
        mk_xy[m.label] = (w.x, w.y, w.z)
        print(f"  {m.label:<28s}: Z={w.z:+.3f} m  XY=({w.x:+.1f}, {w.y:+.1f})")
    if mk_z:
        print(f"  marker Z min   : {min(mk_z):+.3f} m")
        print(f"  marker Z max   : {max(mk_z):+.3f} m")
        print(f"  marker Z spread: {max(mk_z)-min(mk_z):.3f} m")
    print()

    # ── 5. Camera outliers: count + horizontal position ─────────────────────
    print("=== 5. CAMERA-Z OUTLIERS (BELOW P5 OR ABOVE P95) ===")
    p5_val  = vals[labels.index("P5")]
    p95_val = vals[labels.index("P95")]
    below_p5 = [(p[0], p[1], p[2]) for p in cam_pts if p[2] < p5_val]
    above_p95 = [(p[0], p[1], p[2]) for p in cam_pts if p[2] > p95_val]
    print(f"  cameras below P5  ({p5_val:+.3f} m): {len(below_p5)} cameras")
    print(f"  cameras above P95 ({p95_val:+.3f} m): {len(above_p95)} cameras")

    # Cluster check: are outlier cameras near Marker 19/20?
    m19 = mk_xy.get("Marker 19") or mk_xy.get("19")
    m20 = mk_xy.get("Marker 20") or mk_xy.get("20")
    ref_pts = [v for v in [m19, m20] if v is not None]
    if below_p5 and ref_pts:
        print()
        print("  Below-P5 camera XY range:")
        bx = [p[0] for p in below_p5]; by = [p[1] for p in below_p5]
        print(f"    X: [{min(bx):+.1f}, {max(bx):+.1f}]  Y: [{min(by):+.1f}, {max(by):+.1f}]")
        for lbl, rp in [("Marker 19", m19), ("Marker 20", m20)]:
            if rp is None: continue
            # nearest outlier camera to this marker
            dists = [math.sqrt((p[0]-rp[0])**2 + (p[1]-rp[1])**2) for p in below_p5]
            print(f"    nearest below-P5 cam to {lbl}: {min(dists):.1f} m")
    if above_p95 and ref_pts:
        print()
        print("  Above-P95 camera XY range:")
        ax = [p[0] for p in above_p95]; ay = [p[1] for p in above_p95]
        print(f"    X: [{min(ax):+.1f}, {max(ax):+.1f}]  Y: [{min(ay):+.1f}, {max(ay):+.1f}]")
    print()

    # ── VERDICT ──────────────────────────────────────────────────────────────
    print("=== VERDICT ===")
    topo = (ratio >= 0.5 and result and result[3] > 0.7)
    outlier = (ratio < 0.4)
    if topo:
        print("  TOPOGRAPHY — P5–P95 accounts for ≥50% of total range;"
              " plane fit R² suggests smooth gradient.")
    elif outlier:
        print("  OUTLIERS/DISTORTION — tight core + bad tails;"
              " investigate below-P5 / above-P95 cameras.")
    else:
        print("  AMBIGUOUS — moderate spread + plane fit; review slope + tie-point relief.")
    print()
    print("=== END DIAGNOSTIC ===")
    print("NO save. Project untouched.")

if __name__ == "__main__":
    main()
