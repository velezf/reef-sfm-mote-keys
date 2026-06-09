#!/usr/bin/env python3
"""t1_postlevel_probe.py — Quality probe for EDR_T1 after stage_level.

Read-only. Reports the seven things needed before the dense GO decision:
  1. Cameras retained vs baseline 2348.
  2. Tie-point count pre/post reduce (from esm.reduce metadata).
  3. Post-reduce RMSE in filter units (esm.reduce) + live TiePoints.Filter RMS.
  4. Per-bar SIGNED scale-bar errors (mm) + inter-bar spread vs baseline ~1.11 mm.
  5. Leveling tilt before/after (from esm.level metadata).
  6. Guards fired Y/N (network_health_escalation.json exists?).

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
    raw = chunk.meta.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
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

    print("=== END PROBE ===")
    print("NO save. Project untouched.")


if __name__ == "__main__":
    main()
