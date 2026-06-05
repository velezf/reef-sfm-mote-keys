#!/usr/bin/env python3
"""marker_validation_calib.py — read-only dump of the per-marker statistics the
stage_markers validation gates need to be CALIBRATED against.

For each detected marker it reports, in the chunk's INTERNAL (pre-scale) frame:
  * projection count  — number of cameras in which the coded target was detected
    (gate (b): true targets sit in 100+ cameras; mis-decodes in a handful)
  * reprojection RMS in PIXELS — per-marker residual via the documented
    calibration.error() recipe (mirrors reprojection_rms_px.py); gate (b) ceiling
  * internal-unit position — m.position is in the bundle frame, BEFORE the
    transform's scale is applied, so pairwise norms are the pre-scale local
    lengths gate (c) compares (ratios are scale-invariant — firewall-safe).

It then lists every pairwise internal-unit distance (sorted) and the ID-adjacent
candidate-bar lengths so the inter-bar spread can be read directly.

Usage:  metashape.sh -platform offscreen -r marker_validation_calib.py -- <project.psx>
Read-only: opens read_only=True, takes no lock, runs no stage.
"""
import itertools
import json
import re
import sys

import Metashape


def _marker_id(label):
    m = re.findall(r"(\d+)", label)
    return int(m[-1]) if m else None


def _pctl(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    i = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return s[i]


def _marker_residuals(chunk, marker):
    """Per-camera reprojection errors (px) for a marker, over the cameras in
    which it was detected. Returns (n_proj, n_valid, [errs_px]). Robust stats
    (median/p90) are computed by the caller — RMS is wrecked by the few wild
    outlier projections a mis-decode produces in the un-optimized post-align
    state, so we keep the full vector and summarise robustly."""
    pos = marker.position
    if pos is None:
        return 0, 0, []
    n, n_valid, errs = 0, 0, []
    for cam in chunk.cameras:
        if not cam.transform:
            continue
        proj = marker.projections[cam]
        if proj is None:
            continue
        n += 1
        if getattr(proj, "valid", True):
            n_valid += 1
        predicted = cam.project(pos)   # world point -> image pixel (2D) or None
        if predicted is None:
            continue
        c = proj.coord
        errs.append(((c.x - predicted.x) ** 2 + (c.y - predicted.y) ** 2) ** 0.5)
    return n, n_valid, errs


def main():
    project = sys.argv[-1]
    doc = Metashape.Document()
    doc.open(project, read_only=True)
    ch = doc.chunks[0]

    markers = []
    recon = []
    for m in ch.markers:
        mid = _marker_id(m.label)
        n, n_valid, errs = _marker_residuals(ch, m)
        pos = m.position
        markers.append({
            "id": mid,
            "label": m.label,
            "reconstructed": pos is not None,
            "projection_count": n,
            "valid_projections": n_valid,
            "resid_px_min": round(min(errs), 4) if errs else None,
            "resid_px_median": round(_pctl(errs, 0.5), 4) if errs else None,
            "resid_px_p90": round(_pctl(errs, 0.9), 4) if errs else None,
            "resid_px_max": round(max(errs), 4) if errs else None,
        })
        if pos is not None:
            recon.append((mid, m.label, pos))

    # All pairwise internal-unit distances (pre-scale local lengths).
    pairs = []
    for (ida, la, pa), (idb, lb, pb) in itertools.combinations(recon, 2):
        pairs.append({"a": ida, "b": idb, "len_local": (pa - pb).norm()})
    pairs.sort(key=lambda x: x["len_local"])

    # ID-adjacent candidate bars (consecutive IDs).
    by_id = {mid: pos for mid, la, pos in recon}
    adj = []
    for mid in sorted(by_id):
        if mid + 1 in by_id:
            adj.append({"a": mid, "b": mid + 1,
                        "len_local": (by_id[mid] - by_id[mid + 1]).norm()})

    out = {
        "project": project,
        "chunk": ch.label,
        "transform_scale": ch.transform.scale if ch.transform else None,
        "n_markers": len(ch.markers),
        "n_scalebars": len(ch.scalebars),
        "scalebars": [{"label": sb.label,
                       "defined_m": sb.reference.distance,
                       "p0": sb.point0.label if sb.point0 else None,
                       "p1": sb.point1.label if sb.point1 else None}
                      for sb in ch.scalebars],
        "markers": markers,
        "pairwise_local": [{"a": p["a"], "b": p["b"],
                            "len_local": round(p["len_local"], 6)} for p in pairs],
        "adjacent_candidate_bars": [{"a": a["a"], "b": a["b"],
                                     "len_local": round(a["len_local"], 6)} for a in adj],
    }
    print("CALIB_JSON_BEGIN")
    print(json.dumps(out, indent=2))
    print("CALIB_JSON_END")


if __name__ == "__main__":
    main()
