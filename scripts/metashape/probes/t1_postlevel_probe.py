#!/usr/bin/env python3
"""t1_postlevel_probe.py — Quality probe for EDR_T1 after stage_level.

Read-only. Reports the checks needed before the dense GO decision:
  1. Cameras retained vs baseline 2348.
  2. Tie-point count pre/post reduce (from esm.reduce metadata).
  3. Post-reduce RMSE in filter units (esm.reduce) + live TiePoints.Filter RMS.
  4. Per-bar SIGNED scale-bar errors (mm) + inter-bar spread vs baseline ~1.11 mm.
  5. Leveling tilt before/after (from esm.level metadata).
  6. Guards fired Y/N (network_health_escalation.json exists?).
  7. ADR-0025 camera-nadir verification:
       level_method, spread_ratio, nadir_angle_deg
       Mean camera boresight direction in world space (should be ≈ (0,0,-1)).
       Boresight tilt from (0,0,-1) — GATE: < 5° for a nadir survey.
       Camera-Z range in world space — GATE: < 4 m.
       Cameras-above-markers check.
       Transform scale unchanged (should be ≈ 0.15246 m/internal_unit).

Usage: metashape.sh -platform offscreen -r probes/t1_postlevel_probe.py <project.psx> [out_root]
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import Metashape

BASELINE_CAMERAS = 2348
RMSE_LO, RMSE_HI = 0.27, 0.52          # ESM Toth 2025 envelope
OUT_ROOT_DEFAULT = Path("/data/edr_work/products")


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


def _world_xyz(T, p) -> list[float]:
    w = T.mulp(Metashape.Vector([p.x, p.y, p.z]))
    return [w.x, w.y, w.z]


def _reprojection_rms(chunk) -> tuple[float | None, int]:
    tp = chunk.tie_points
    if tp is None or not tp.points:
        return None, 0
    f = Metashape.TiePoints.Filter()
    f.init(chunk, criterion=Metashape.TiePoints.Filter.ReprojectionError)
    errs = list(f.values)
    if not errs:
        return None, 0
    rms = (sum(e * e for e in errs) / len(errs)) ** 0.5
    return rms, len(errs)


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: t1_postlevel_probe.py <project.psx> [out_root]")
        sys.exit(1)
    project = sys.argv[1]
    out_root = Path(sys.argv[2]) if len(sys.argv) > 2 else OUT_ROOT_DEFAULT

    doc = Metashape.Document()
    doc.open(project, read_only=True)
    chunk = doc.chunks[0]
    T = chunk.transform.matrix

    print(f"=== T1 POST-LEVEL PROBE ===")
    print(f"project  : {project}")
    print(f"chunk    : {chunk.label}")
    print(f"read_only: {doc.read_only}")
    print()

    # ── 1. CAMERAS ──────────────────────────────────────────────────────────
    n_aligned = sum(1 for c in chunk.cameras if c.transform is not None)
    delta = n_aligned - BASELINE_CAMERAS
    flag = "  *** COLLAPSE-SUSPECT" if n_aligned < BASELINE_CAMERAS * 0.90 else ""
    print("=== CAMERAS ===")
    print(f"  aligned : {n_aligned} / {len(chunk.cameras)}"
          f"  (baseline {BASELINE_CAMERAS}, delta {delta:+d}){flag}")
    print()

    # ── 2+3. REDUCE METADATA + LIVE RMS ─────────────────────────────────────
    rd = _meta_get(chunk, "esm.reduce")
    print("=== REDUCE (esm.reduce metadata) ===")
    if rd is None:
        print("  esm.reduce: NOT FOUND — stage_reduce did not complete")
    else:
        tp_before = rd.get("tie_points_before", "?")
        tp_after  = rd.get("tie_points_after",  "?")
        rms_pre   = rd.get("reproj_rms_pre_filter_units")
        rms_post  = rd.get("reproj_rms_post_filter_units")
        if isinstance(tp_before, int) and isinstance(tp_after, int):
            dropped = tp_before - tp_after
            pct_s = f"{100 * dropped / tp_before:.1f}%" if tp_before else "?"
        else:
            dropped, pct_s = "?", "?"
        print(f"  tie_points  : {tp_before:,} -> {tp_after:,}  (dropped {dropped:,} = {pct_s})")
        print(f"  RMSE (filter units): pre={rms_pre}  post={rms_post}")
        if rms_post is not None:
            in_range = RMSE_LO <= rms_post <= RMSE_HI
            tag = "IN RANGE" if in_range else f"OUT OF RANGE (expect {RMSE_LO}-{RMSE_HI})"
            print(f"  post RMSE   : {rms_post}  [{tag}]")
    rms_live, n_tp = _reprojection_rms(chunk)
    print(f"  live RMS    : {rms_live}  (n={n_tp:,} tie points after level)")
    print()

    # ── 4. SCALE-BAR RESIDUALS ───────────────────────────────────────────────
    mk = {m.label: m.position for m in chunk.markers if m.position is not None}
    print("=== SCALE-BAR RESIDUALS ===")
    bars: list[dict] = []
    for sb in chunk.scalebars:
        try:
            a, b = sb.point0.label, sb.point1.label
            wa = _world_xyz(T, mk[a])
            wb = _world_xyz(T, mk[b])
            dist = math.sqrt(sum((wa[i] - wb[i]) ** 2 for i in range(3)))
            ref = sb.reference.distance
            err_mm = (dist - ref) * 1000
            bars.append({"bar": sb.label, "dist_m": dist, "ref_m": ref,
                         "err_mm": err_mm})
        except (AttributeError, KeyError, TypeError) as exc:
            print(f"  {getattr(sb, 'label', '?')}: skipped ({exc})")
    if bars:
        errs = [b["err_mm"] for b in bars]
        spread_mm = max(errs) - min(errs)
        med_err = _median(errs)
        for b in bars:
            print(f"  {b['bar']:<30s}  dist={b['dist_m']:.5f} m"
                  f"  ref={b['ref_m']:.3f} m  err={b['err_mm']:+.3f} mm")
        print(f"  median error : {med_err:+.3f} mm")
        print(f"  spread (max-min): {spread_mm:.3f} mm  (baseline inter-bar ~1.11 mm)")
    else:
        print("  no usable scale bars")
    print()

    # ── 5. LEVEL METADATA ────────────────────────────────────────────────────
    lv = _meta_get(chunk, "esm.level")
    print("=== LEVEL (esm.level metadata) ===")
    if lv is None:
        print("  esm.level: NOT FOUND — stage_level did not complete")
    else:
        print(f"  level_method  : {lv.get('level_method', 'NOT PRESENT (pre-ADR-0025)')}")
        print(f"  spread_ratio  : {lv.get('level_spread_ratio', '?')}  "
              f"(eig1/eig0; <0.25 = collinear guard; T1 expected ~0.10)")
        print(f"  nadir_angle   : {lv.get('level_nadir_angle_deg', '?')} deg  "
              f"(marker_normal vs cam_up; >15° = nadir guard)")
        print(f"  tilt before   : {lv.get('marker_plane_tilt_before_deg', '?')} deg")
        print(f"  tilt after    : {lv.get('marker_plane_tilt_after_deg',  '?')} deg")
        print(f"  vetted markers: {lv.get('vetted_markers', '?')}")
        print(f"  excluded bars : {lv.get('excluded_bars', '?')}")
        implied = lv.get("implied_cross_floor_deg")
        if implied is not None:
            print(f"  cross-floor tilt: {implied} deg")
        print(f"  scale preserved: {lv.get('scale_preserved', '?')}")
    print()

    # ── 6. GUARDS FIRED? ────────────────────────────────────────────────────
    esc_path = out_root / chunk.label / "network_health_escalation.json"
    print("=== GUARDS (3a/3b/3c) ===")
    if esc_path.exists():
        try:
            esc = json.loads(esc_path.read_text())
            print(f"  *** ESCALATION FILE EXISTS: {esc_path}")
            print(f"  context      : {esc.get('context')}")
            print(f"  failed checks: {esc.get('failed_checks')}")
            print(f"  status       : {esc.get('status')}")
        except Exception as exc:
            print(f"  escalation file exists but unreadable: {exc}")
    else:
        print(f"  NO escalation — guards did not fire")
        print(f"  (checked: {esc_path})")
    print()

    # ── 7. ADR-0025 CAMERA-NADIR VERIFICATION ───────────────────────────────
    print("=== ADR-0025 LEVELING VERIFICATION ===")
    # Gather camera boresights in world space.
    boresights: list[list[float]] = []
    cam_z_world: list[float] = []
    mk_z_world: list[float] = []
    for cam in chunk.cameras:
        if cam.transform is None:
            continue
        # Camera position in world space
        cp = T.mulp(cam.transform.mulp(Metashape.Vector([0.0, 0.0, 0.0])))
        cam_z_world.append(cp.z)
        # Camera boresight in world space (camera +Z axis = direction camera looks)
        bc = cam.transform.mulv(Metashape.Vector([0.0, 0.0, 1.0]))
        bw = T.mulv(bc)
        bL = math.sqrt(bw.x**2 + bw.y**2 + bw.z**2) or 1.0
        boresights.append([bw.x/bL, bw.y/bL, bw.z/bL])
    # Marker world positions (for cameras-above check)
    for lab, pos in mk.items():
        w = _world_xyz(T, pos)
        mk_z_world.append(w[2])

    BORESIGHT_TILT_GATE = 5.0    # deg from (0,0,-1); gate for nadir survey
    CAM_Z_RANGE_GATE    = 4.0    # m; camera-Z spread gate

    if boresights:
        n_b = len(boresights)
        mean_b = [sum(b[i] for b in boresights) / n_b for i in range(3)]
        bL2 = math.sqrt(sum(x*x for x in mean_b)) or 1.0
        mean_b_u = [x/bL2 for x in mean_b]
        # Angle from (0,0,-1): cos(θ) = -mean_b_u[2] (Z component negated for down)
        dot_down = -mean_b_u[2]
        boresight_tilt = math.degrees(math.acos(max(-1.0, min(1.0, dot_down))))
        tilt_ok = boresight_tilt < BORESIGHT_TILT_GATE
        print(f"  mean boresight      : ({mean_b_u[0]:.4f}, {mean_b_u[1]:.4f}, {mean_b_u[2]:.4f})")
        print(f"  boresight tilt from (0,0,-1): {boresight_tilt:.2f}°"
              f"  [{'PASS' if tilt_ok else f'FAIL > {BORESIGHT_TILT_GATE}°'}]")

        cam_z_rng = max(cam_z_world) - min(cam_z_world)
        z_rng_ok = cam_z_rng < CAM_Z_RANGE_GATE
        print(f"  camera-Z range      : {cam_z_rng:.2f} m"
              f"  [{'PASS' if z_rng_ok else f'FAIL > {CAM_Z_RANGE_GATE} m'}]")

        if mk_z_world and cam_z_world:
            max_mk_z = max(mk_z_world)
            min_cam_z = min(cam_z_world)
            above = min_cam_z > max_mk_z
            print(f"  cameras above markers: min_cam_z={min_cam_z:.2f} m, "
                  f"max_mk_z={max_mk_z:.2f} m  "
                  f"[{'PASS' if above else 'FAIL — cameras below/at markers'}]")
        else:
            print("  cameras-above check: insufficient data")

        # Transform scale (should be unchanged at ~0.15246)
        T_mat = chunk.transform.matrix
        scale_live = math.sqrt(T_mat[0,0]**2 + T_mat[1,0]**2 + T_mat[2,0]**2)
        EXPECTED_SCALE_LO, EXPECTED_SCALE_HI = 0.14, 0.17
        scale_ok = EXPECTED_SCALE_LO <= scale_live <= EXPECTED_SCALE_HI
        print(f"  transform scale     : {scale_live:.6f} m/internal_unit"
              f"  (expect ~0.15246)"
              f"  [{'PASS' if scale_ok else f'FAIL outside [{EXPECTED_SCALE_LO}, {EXPECTED_SCALE_HI}]'}]")

        # Summary verdict
        all_ok = tilt_ok and z_rng_ok and scale_ok
        print()
        print(f"  ADR-0025 VERDICT: {'PASS — model correctly leveled' if all_ok else 'FAIL — check items above'}")
    else:
        print("  no aligned cameras — cannot verify boresight")
    print()

    print("=== END PROBE ===")
    print("NO save. Project untouched.")


if __name__ == "__main__":
    main()
