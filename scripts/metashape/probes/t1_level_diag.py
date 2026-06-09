#!/usr/bin/env python3
"""t1_level_diag.py — Diagnose EDR_T1 leveling quality.

Five checks, all read-only:
  1. MARKERS    World positions of all markers; Z-spread (≈0 = coplanar + level).
  2. PLANE FIT  Least-squares plane z = ax + by + c through markers; normal direction;
                tilt from world-Z. Residual RMS = marker coplanarity.
  3. CAMERA-Z   Statistics of camera centre Z in world frame. Expected 2–3 m range for
                a nadir survey at constant altitude; >> 3 m → world-Z is not up.
  4. BORESIGHT  Mean camera boresight direction in world frame. Nadir cameras → mean
                boresight ≈ (0,0,−1) if Z is up; deviation = leveling error by camera
                geometry.
  5. METADATA   esm.level metadata: tilt_before / tilt_after / vetted markers.

No writes. Exits 0 (diagnostic only). Reports everything verbatim.

Usage:
    metashape.sh -platform offscreen -r probes/t1_level_diag.py <project.psx>
"""
from __future__ import annotations

import json
import math
import sys

import Metashape


# ─── helpers ─────────────────────────────────────────────────────────────────
def _mat_scale(m) -> float:
    return math.sqrt(m[0, 0] ** 2 + m[1, 0] ** 2 + m[2, 0] ** 2)


def _norm3(v: list[float]) -> list[float]:
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    return [x / n for x in v] if n > 1e-12 else [0.0, 0.0, 0.0]


def _dot3(a: list[float], b: list[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _angle_deg(a: list[float], b: list[float]) -> float:
    c = max(-1.0, min(1.0, _dot3(_norm3(a), _norm3(b))))
    return math.degrees(math.acos(c))


def _stats(vals: list[float]) -> dict:
    if not vals:
        return {}
    mn, mx = min(vals), max(vals)
    mu = sum(vals) / len(vals)
    std = math.sqrt(sum((v - mu) ** 2 for v in vals) / len(vals))
    return {"n": len(vals), "min": mn, "max": mx, "range": mx - mn,
            "mean": mu, "std": std}


def _fit_plane(pts: list[list[float]]) -> dict | None:
    """
    Fit z = a*x + b*y + c (horiz-plane form) to pts via normal equations.
    Returns: a, b, c, normal (unit, +Z hemisphere), tilt_deg from world-Z,
             rms residual.
    Degenerate (all same XY) → returns None.
    """
    n = len(pts)
    if n < 3:
        return None
    sxx = sxy = sxz = syy = syz = sx = sy = sz = 0.0
    for p in pts:
        x, y, z = p[0], p[1], p[2]
        sxx += x * x; sxy += x * y; sxz += x * z
        syy += y * y; syz += y * z
        sx  += x;     sy  += y;     sz  += z
    M = [
        [sxx, sxy, sx,  sxz],
        [sxy, syy, sy,  syz],
        [sx,  sy,  float(n), sz],
    ]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(M[r][col]))
        M[col], M[pivot] = M[pivot], M[col]
        if abs(M[col][col]) < 1e-12:
            return None
        M[col] = [x / M[col][col] for x in M[col]]
        for row in range(3):
            if row != col:
                f = M[row][col]
                M[row] = [M[row][j] - f * M[col][j] for j in range(4)]
    a, b, c = M[0][3], M[1][3], M[2][3]
    mag = math.sqrt(a * a + b * b + 1.0)
    nx, ny, nz = -a / mag, -b / mag, 1.0 / mag
    if nz < 0:
        nx, ny, nz = -nx, -ny, -nz   # point into +Z hemisphere
    tilt = math.degrees(math.acos(min(1.0, abs(nz))))
    rms = math.sqrt(sum((a * p[0] + b * p[1] + c - p[2]) ** 2 for p in pts) / n)
    return {"a": a, "b": b, "c": c,
            "normal": (nx, ny, nz), "tilt_deg": tilt, "rms_m": rms}


def _meta_get(chunk, key):
    try:
        raw = chunk.meta[key]
    except (KeyError, RuntimeError):
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def _sep(title: str) -> None:
    print(f"\n{'='*62}")
    print(f"  {title}")
    print(f"{'='*62}")


# ─── main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: t1_level_diag.py <project.psx>")
        sys.exit(0)
    psx = sys.argv[1]

    print("=== T1 LEVELING DIAGNOSIS ===")
    print(f"project: {psx}")

    doc = Metashape.Document()
    doc.open(psx, read_only=True)
    chunk = doc.chunks[0]
    T     = chunk.transform.matrix
    scale = _mat_scale(T)

    print(f"chunk          : {chunk.label}")
    print(f"transform scale: {scale:.6f} m/internal_unit")

    # Print full 4×4 transform matrix for inspection
    print("chunk.transform.matrix (chunk→world, each row):")
    for i in range(4):
        row = [f"{T[i,j]:+.6f}" for j in range(4)]
        print(f"  [{', '.join(row)}]")

    # ── 1. MARKER WORLD POSITIONS ─────────────────────────────────────────────
    _sep("1. MARKER WORLD POSITIONS")
    mk_world: list[dict] = []
    for m in chunk.markers:
        if m.position is None:
            continue
        p  = m.position
        pw = T.mulp(Metashape.Vector([p.x, p.y, p.z]))
        ref_en = m.reference.enabled if m.reference else None
        mk_world.append({"label": m.label,
                         "world": (pw.x, pw.y, pw.z),
                         "ref_en": ref_en})
        print(f"  {m.label:<8}  "
              f"({pw.x:+9.4f}, {pw.y:+9.4f}, {pw.z:+9.4f}) m  "
              f"ref.enabled={ref_en}")

    if mk_world:
        zv = [m["world"][2] for m in mk_world]
        xv = [m["world"][0] for m in mk_world]
        yv = [m["world"][1] for m in mk_world]
        zs = _stats(zv)
        print(f"\n  Marker X extent : {max(xv)-min(xv):.4f} m")
        print(f"  Marker Y extent : {max(yv)-min(yv):.4f} m")
        print(f"  Marker Z spread : {zs['range']:.4f} m  "
              f"(min={zs['min']:+.4f}  max={zs['max']:+.4f}  mean={zs['mean']:+.4f})")
        print(f"\n  EXPECT: Z spread ≈ 0 m (all markers on the same horizontal reef plane)")
        zdiag = ("OK — markers appear coplanar in world frame"
                 if zs['range'] < 0.15
                 else f"PROBLEM — markers span {zs['range']:.3f} m in world-Z "
                      f"(not coplanar; or leveling tilted the plane)")
        print(f"  VERDICT: {zdiag}")
    else:
        print("  WARNING: no markers with positions found")

    # ── 2. PLANE FIT TO MARKERS ───────────────────────────────────────────────
    _sep("2. PLANE FIT TO MARKERS (world frame)")
    if len(mk_world) >= 3:
        pts = [[m["world"][0], m["world"][1], m["world"][2]] for m in mk_world]
        res = _fit_plane(pts)
        if res:
            nx, ny, nz = res["normal"]
            print(f"  plane  : z = {res['a']:+.6f}·x  {res['b']:+.6f}·y  {res['c']:+.6f}")
            print(f"  normal : ({nx:+.6f}, {ny:+.6f}, {nz:+.6f})")
            print(f"  tilt from world-Z : {res['tilt_deg']:.4f} deg")
            print(f"  coplanarity RMS   : {res['rms_m']:.4f} m")
            print(f"\n  EXPECT: tilt ≈ 0° (normal ≈ world-Z) and RMS ≈ 0")
            tdiag = ("OK — marker plane is horizontal in world frame"
                     if res["tilt_deg"] < 1.0
                     else f"PROBLEM — marker plane tilted {res['tilt_deg']:.1f}° from world-Z; "
                          "leveling did not bring markers to horizontal")
            print(f"  VERDICT: {tdiag}")
        else:
            print("  Plane fit degenerate (markers collinear or all at same XY)")
    else:
        print(f"  Only {len(mk_world)} markers — need ≥3 for plane fit")

    # ── 3. CAMERA WORLD Z STATISTICS ─────────────────────────────────────────
    _sep("3. CAMERA WORLD Z STATISTICS")
    cam_wx: list[float] = []
    cam_wy: list[float] = []
    cam_wz: list[float] = []
    for cam in chunk.cameras:
        if cam.transform is None:
            continue
        # cam.transform maps camera→chunk; mulp([0,0,0]) = camera centre in chunk coords
        p_int = cam.transform.mulp(Metashape.Vector([0.0, 0.0, 0.0]))
        pw    = T.mulp(p_int)
        cam_wx.append(pw.x); cam_wy.append(pw.y); cam_wz.append(pw.z)

    if cam_wz:
        zs = _stats(cam_wz)
        xs = _stats(cam_wx)
        ys = _stats(cam_wy)
        print(f"  aligned cameras : {zs['n']}")
        print(f"  Camera X : min={xs['min']:+8.3f}  max={xs['max']:+8.3f}  "
              f"range={xs['range']:.3f}  mean={xs['mean']:+.3f}  std={xs['std']:.3f}  m")
        print(f"  Camera Y : min={ys['min']:+8.3f}  max={ys['max']:+8.3f}  "
              f"range={ys['range']:.3f}  mean={ys['mean']:+.3f}  std={ys['std']:.3f}  m")
        print(f"  Camera Z : min={zs['min']:+8.3f}  max={zs['max']:+8.3f}  "
              f"range={zs['range']:.3f}  mean={zs['mean']:+.3f}  std={zs['std']:.3f}  m")

        if mk_world:
            mk_z_mean = sum(m["world"][2] for m in mk_world) / len(mk_world)
            delta_z   = zs["mean"] - mk_z_mean
            print(f"\n  Mean camera Z − mean marker Z = {delta_z:+.4f} m")
            print(f"  (expect +1 to +2 m if cameras above markers and Z = up)")
            print(f"  (expect −1 to −2 m if Z convention is inverted)")

        print(f"\n  EXPECT: camera-Z range ≈ 2–3 m for a nadir survey at constant altitude")
        cdiag = (f"OK — camera-Z range {zs['range']:.1f} m within expected bounds"
                 if zs["range"] < 5
                 else f"PROBLEM — camera-Z range {zs['range']:.1f} m >> 3 m; "
                      "world-Z is not the vertical axis, OR extreme outlier cameras present")
        print(f"  VERDICT: {cdiag}")

    # ── 4. CAMERA BORESIGHT (NADIR DIRECTION CHECK) ───────────────────────────
    _sep("4. CAMERA BORESIGHT — NADIR DIRECTION CHECK")
    bs_sum = [0.0, 0.0, 0.0]
    n_bs   = 0
    for cam in chunk.cameras:
        if cam.transform is None:
            continue
        # Camera boresight = +Z in camera space.
        # cam.transform.mulv maps camera-direction → chunk-direction (no translation).
        bs_int = cam.transform.mulv(Metashape.Vector([0.0, 0.0, 1.0]))
        bs_w   = T.mulv(bs_int)
        bn     = _norm3([bs_w.x, bs_w.y, bs_w.z])
        bs_sum[0] += bn[0]; bs_sum[1] += bn[1]; bs_sum[2] += bn[2]
        n_bs += 1

    if n_bs > 0:
        bs_mean   = _norm3(bs_sum)   # already sum of unit vecs; normalize aggregate
        bx, by, bz = bs_mean

        # Also compute std of Z component across cameras
        bs_z_vals: list[float] = []
        for cam in chunk.cameras:
            if cam.transform is None:
                continue
            bs_int = cam.transform.mulv(Metashape.Vector([0.0, 0.0, 1.0]))
            bs_w   = T.mulv(bs_int)
            bn     = _norm3([bs_w.x, bs_w.y, bs_w.z])
            bs_z_vals.append(bn[2])
        bz_stats = _stats(bs_z_vals)

        print(f"  cameras sampled       : {n_bs}")
        print(f"  Mean boresight (world): ({bx:+.6f}, {by:+.6f}, {bz:+.6f})")
        print(f"  Boresight Z component : "
              f"mean={bz_stats['mean']:+.4f}  std={bz_stats['std']:.4f}  "
              f"min={bz_stats['min']:+.4f}  max={bz_stats['max']:+.4f}")

        # Angles
        ang_down = _angle_deg([bx, by, bz], [0, 0, -1])  # from "down" if Z-up
        ang_up   = _angle_deg([bx, by, bz], [0, 0,  1])  # from "up"  if Z-up
        print(f"\n  Angle from (0,0,−1) [down / Z-up convention]: {ang_down:.3f} deg")
        print(f"  Angle from (0,0,+1) [up   / Z-up convention]: {ang_up:.3f} deg")

        # Camera-geometry "up" estimate = opposite of mean boresight
        up_est = _norm3([-bx, -by, -bz])
        ang_up_vs_worldZ = _angle_deg(up_est, [0, 0, 1])
        print(f"\n  Camera-geometry 'up' estimate: "
              f"({up_est[0]:+.6f}, {up_est[1]:+.6f}, {up_est[2]:+.6f})")
        print(f"  Angle between camera-'up' and world-Z: {ang_up_vs_worldZ:.3f} deg")

        print(f"\n  EXPECT: angle from (0,0,−1) ≈ small (cameras look down = nadir); "
              f"world-Z IS up")
        if ang_down < 15:
            bdiag = (f"OK — cameras point mostly down ({ang_down:.1f}° from nadir); "
                     f"world-Z is up")
        elif ang_up < 15:
            bdiag = (f"INVERTED — cameras point mostly UP ({ang_up:.1f}° from zenith); "
                     f"world-Z is DOWN → Z-axis is inverted after leveling")
        else:
            bdiag = (f"TILTED — cameras point sideways ({ang_down:.1f}° from nadir, "
                     f"{ang_up:.1f}° from zenith); leveling severely wrong; "
                     f"camera-derived up is {ang_up_vs_worldZ:.1f}° from world-Z")
        print(f"  VERDICT: {bdiag}")

    # ── 5. STAGE_LEVEL METADATA ───────────────────────────────────────────────
    _sep("5. STAGE_LEVEL METADATA (esm.level)")
    lv = _meta_get(chunk, "esm.level")
    if lv is None:
        print("  esm.level: NOT FOUND")
    elif isinstance(lv, dict):
        for k, v in lv.items():
            print(f"  {k:<36}: {v}")
    else:
        print(f"  esm.level (raw): {lv}")

    # ── 6. SUMMARY ────────────────────────────────────────────────────────────
    _sep("6. SUMMARY AND LEVELING VERDICT")
    problems: list[str] = []
    notes:    list[str] = []

    if mk_world and cam_wz and n_bs > 0:
        mk_z_range = max(m["world"][2] for m in mk_world) - min(m["world"][2] for m in mk_world)
        cam_z_range = _stats(cam_wz)["range"]
        cam_z_mean  = _stats(cam_wz)["mean"]
        mk_z_mean   = sum(m["world"][2] for m in mk_world) / len(mk_world)
        cam_above   = cam_z_mean > mk_z_mean

        plane_tilt = res["tilt_deg"] if (len(mk_world) >= 3 and res) else None

        print(f"  marker Z spread      : {mk_z_range:.4f} m    (threshold < 0.15 m)")
        print(f"  marker plane tilt    : {plane_tilt:.4f} deg  (threshold < 1.0°)"
              if plane_tilt is not None else "  marker plane tilt    : N/A")
        print(f"  camera-Z range       : {cam_z_range:.3f} m    (threshold < 5 m)")
        print(f"  boresight from nadir : {ang_down:.3f} deg  (threshold < 15°)")
        print(f"  camera-'up' vs world-Z: {ang_up_vs_worldZ:.3f} deg  (threshold < 2°)")
        print(f"  cameras above markers: {cam_above}   (expect True if Z=up)")

        if mk_z_range > 0.15:
            problems.append(f"marker Z spread {mk_z_range:.3f} m > 0.15 m "
                            "(markers not coplanar in world frame after leveling)")
        if plane_tilt is not None and plane_tilt > 1.0:
            problems.append(f"marker plane tilted {plane_tilt:.2f}° from world-Z "
                            "(leveling rotation did not make marker plane horizontal)")
        if cam_z_range > 5:
            problems.append(f"camera-Z range {cam_z_range:.1f} m > 5 m "
                            "(world-Z is not the vertical axis)")
        if ang_down > 15:
            problems.append(f"mean camera boresight {ang_down:.1f}° from (0,0,-1) "
                            "(cameras not looking down; world-Z is not up)")
        if ang_up_vs_worldZ > 2:
            notes.append(f"camera-nadir implies 'up' is {ang_up_vs_worldZ:.1f}° from world-Z — "
                         "this is the re-level target angle")
        if not cam_above:
            problems.append("camera Z-mean below marker Z-mean (Z-axis may be inverted)")

        print()
        if problems:
            print("  OVERALL VERDICT: LEVELING IS INCORRECT")
            for p in problems:
                print(f"    PROBLEM: {p}")
        else:
            print("  OVERALL VERDICT: Leveling appears CORRECT")
        for note in notes:
            print(f"    NOTE: {note}")
    else:
        print("  (insufficient data for full summary)")

    print("\n=== END DIAGNOSIS ===")
    print("NO writes. Project untouched.")


if __name__ == "__main__":
    main()
