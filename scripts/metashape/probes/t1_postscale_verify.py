#!/usr/bin/env python3
"""t1_postscale_verify.py — Gate: verify post-scale PSX matches the validated Arm B state.

All five checks must pass before reduce runs:
  1. chunk.crs is LOCAL (ADR-0024 fix applied — not WGS84).
  2. All marker reference.enabled == False (garbage GCPs neutralized).
  3. All camera reference.enabled == False (stub GPS neutralized).
  4. Matrix-derived transform scale in [0.05, 2.0].
     Pre-optimize (post-scale, pre-reduce): matrix scale ≈ 1.0 (identity).
     Post-optimize (post-reduce/level): matrix scale ≈ 0.153 (Arm B confirmed).
     chunk.transform.scale returns None on 2.3.1; derived from col-0 norm.
     Divergence would give >>100; [0.05, 2.0] catches both valid states.
  5. Exactly 4 scale bars, all reference.enabled=True, distance=0.25 m.

Exits 0 on PASS, 1 on FAIL. Halts the orchestration script on failure.

Usage: metashape.sh -platform offscreen -r probes/t1_postscale_verify.py <project.psx>
"""
from __future__ import annotations

import math
import sys

import Metashape

# Scale bounds cover both pre- and post-optimizeCameras states:
#   pre-optimize (post-scale, pre-reduce): matrix scale ≈ 1.0 (identity from align)
#   post-optimize (post-reduce/level): matrix scale ≈ 0.153 (Arm B confirmed)
# Both are well within [0.05, 2.0]; divergence would give >>100.
SCALE_PRE_OPT_LO, SCALE_PRE_OPT_HI = 0.05, 2.0
EXPECTED_BARS = 4
BAR_DIST_M = 0.25
BAR_DIST_TOL_M = 0.001


def main() -> None:
    project = sys.argv[-1]
    doc = Metashape.Document()
    doc.open(project, read_only=True)
    chunk = doc.chunks[0]

    print(f"=== POST-SCALE VERIFY ===")
    print(f"project  : {project}")
    print(f"chunk    : {chunk.label}")
    print()

    failures: list[str] = []

    def _mat_scale(m) -> float | None:
        try:
            return math.sqrt(m[0, 0] ** 2 + m[1, 0] ** 2 + m[2, 0] ** 2)
        except Exception:
            return None

    # 1. CRS
    crs_wkt = getattr(chunk.crs, "wkt", "") or ""
    if "LOCAL_CS" in crs_wkt:
        print(f"  [PASS] chunk.crs LOCAL ({chunk.crs.name!r})")
    else:
        msg = f"chunk.crs is NOT LOCAL: {chunk.crs!r}"
        failures.append(msg)
        print(f"  [FAIL] {msg}")

    # 2. Marker refs
    mk_on = [m.label for m in chunk.markers
             if m.reference is not None and m.reference.enabled]
    if not mk_on:
        print(f"  [PASS] all {len(chunk.markers)} marker reference.enabled = False")
    else:
        msg = f"{len(mk_on)} markers still have reference.enabled=True: {mk_on}"
        failures.append(msg)
        print(f"  [FAIL] {msg}")

    # 3. Camera refs
    cam_on = [c.label for c in chunk.cameras
              if c.reference is not None and c.reference.enabled]
    if not cam_on:
        print(f"  [PASS] all {len(chunk.cameras)} camera reference.enabled = False")
    else:
        msg = f"{len(cam_on)} cameras still have reference.enabled=True"
        failures.append(msg)
        print(f"  [FAIL] {msg}  (sample: {cam_on[:5]})")

    # 4. Matrix-derived scale (pre-optimize; ~1.0 from identity; 0.153 is post-optimize)
    scale = _mat_scale(chunk.transform.matrix) if chunk.transform else None
    if scale is not None and SCALE_PRE_OPT_LO <= scale <= SCALE_PRE_OPT_HI:
        print(f"  [PASS] matrix scale = {scale:.5f}  (pre-optimize; expect ~1.0)")
    else:
        msg = (f"matrix scale = {scale!r}  "
               f"(expected {SCALE_PRE_OPT_LO}–{SCALE_PRE_OPT_HI})")
        failures.append(msg)
        print(f"  [FAIL] {msg}")

    # 5. Scale bars
    n_bars = len(chunk.scalebars)
    bar_issues: list[str] = []
    for sb in chunk.scalebars:
        dist = getattr(sb.reference, "distance", None)
        en   = getattr(sb.reference, "enabled",  None)
        if not en:
            bar_issues.append(f"{sb.label}: reference.enabled={en}")
        if dist is None or abs(dist - BAR_DIST_M) > BAR_DIST_TOL_M:
            bar_issues.append(f"{sb.label}: distance={dist} (expect {BAR_DIST_M})")
    if n_bars == EXPECTED_BARS and not bar_issues:
        print(f"  [PASS] {n_bars} scale bars, all enabled=True, distance={BAR_DIST_M} m")
    else:
        msg = f"{n_bars} bars (expect {EXPECTED_BARS}); issues: {bar_issues}"
        failures.append(msg)
        print(f"  [FAIL] {msg}")

    print()
    if failures:
        print(f"POST-SCALE VERIFY: FAILED ({len(failures)} check(s))")
        for f in failures:
            print(f"  - {f}")
        print("HALTING — do NOT reduce on unexpected state.")
        sys.exit(1)
    else:
        print("POST-SCALE VERIFY: PASS — CRS LOCAL, refs disabled, bars intact. Safe to reduce.")
        sys.exit(0)


if __name__ == "__main__":
    main()
