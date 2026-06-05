#!/usr/bin/env python3
"""marker_optimize_experiment.py — IN-MEMORY ONLY (never saves).

Question: T1's per-marker reprojection residuals are all garbage in the raw
post-align/pre-optimization state. Is that because the bundle hasn't been
optimized, and would optimization make a true mis-decode (rays that can't be
reconciled) separate cleanly from real targets (rays that intersect)?

Opens read_only=True, runs optimizeCameras() in memory (NO save), and prints
robust per-marker residuals before vs after. Read-only -> the on-disk project
is untouched; this is a measurement, not a pipeline step.

Usage: metashape.sh -platform offscreen -r marker_optimize_experiment.py <proj>
"""
import re
import sys

import Metashape


def _mid(label):
    m = re.findall(r"(\d+)", label)
    return int(m[-1]) if m else None


def _pctl(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    return s[max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))]


def _resid(chunk, marker):
    pos = marker.position
    if pos is None:
        return 0, []
    n, errs = 0, []
    for cam in chunk.cameras:
        if not cam.transform:
            continue
        proj = marker.projections[cam]
        if proj is None:
            continue
        n += 1
        pred = cam.project(pos)
        if pred is None:
            continue
        c = proj.coord
        errs.append(((c.x - pred.x) ** 2 + (c.y - pred.y) ** 2) ** 0.5)
    return n, errs


def snapshot(chunk, tag):
    print(f"\n=== {tag} ===")
    print(f"{'id':>4} {'n':>5} {'median_px':>16} {'p90_px':>16}")
    for m in chunk.markers:
        n, errs = _resid(chunk, m)
        med = _pctl(errs, 0.5)
        p90 = _pctl(errs, 0.9)
        print(f"{_mid(m.label):>4} {n:>5} "
              f"{(f'{med:.3f}' if med is not None else 'NA'):>16} "
              f"{(f'{p90:.3f}' if p90 is not None else 'NA'):>16}")


def main():
    project = sys.argv[-1]
    doc = Metashape.Document()
    doc.open(project, read_only=True)
    ch = doc.chunks[0]
    print(f"project={project} chunk={ch.label} read_only={doc.read_only} "
          f"cameras={len(ch.cameras)} markers={len(ch.markers)}")
    snapshot(ch, "BEFORE optimizeCameras (raw post-align)")
    print("\n[running optimizeCameras() in memory — NOT saved] ...", flush=True)
    try:
        ch.optimizeCameras()
    except Exception as exc:  # noqa: BLE001
        print(f"optimizeCameras failed in read-only memory: {exc}")
        return
    snapshot(ch, "AFTER optimizeCameras (in-memory, unsaved)")


if __name__ == "__main__":
    main()
