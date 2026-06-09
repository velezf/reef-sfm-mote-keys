#!/usr/bin/env python3
"""t1_postscale_verify.py — Gate: verify post-scale PSX matches the validated Arm B state.

All five checks must pass before reduce runs:
  1. chunk.crs is LOCAL (ADR-0024 fix applied — not WGS84).
  2. All marker reference.enabled == False (garbage GCPs neutralized).
  3. All camera reference.enabled == False (stub GPS neutralized).
  4. transform.scale in [0.10, 0.25] — consistent with Arm B (0.153).
  5. Exactly 4 scale bars, all reference.enabled=True, distance=0.25 m.

Exits 0 on PASS, 1 on FAIL. Halts the orchestration script on failure.

Usage: metashape.sh -platform offscreen -r probes/t1_postscale_verify.py <project.psx>
"""
from __future__ import annotations

import sys

import Metashape

SCALE_LO, SCALE_HI = 0.10, 0.25    # Arm B confirmed 0.153
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

    # 4. Transform scale
    scale = chunk.transform.scale if chunk.transform else None
    if scale is not None and SCALE_LO <= scale <= SCALE_HI:
        print(f"  [PASS] transform.scale = {scale:.5f}  (Arm B was 0.153)")
    else:
        msg = f"transform.scale = {scale!r}  (expected {SCALE_LO}–{SCALE_HI})"
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
        print("POST-SCALE VERIFY: PASS — state matches Arm B. Safe to reduce.")
        sys.exit(0)


if __name__ == "__main__":
    main()
