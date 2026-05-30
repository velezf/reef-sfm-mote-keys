#!/usr/bin/env python3
"""reprojection_rms_px.py — read-only post-reduction reprojection RMS in PIXELS.

The run_pipeline.py `reduce` stage records RMS in Metashape *filter units*
(ADR-0012), which is valid for before/after comparison but NOT directly
comparable to Toth's ESM 0.27-0.52 px envelope. This probe computes the
pixel-calibrated reprojection RMS directly from tie-point residuals via the
documented calibration.error() recipe — no PDF parsing.

Usage:
    metashape.sh -platform offscreen -r reprojection_rms_px.py
(edit PROJECT below or wrap in a runner). Read-only: opens read_only=True.
"""
import math

import Metashape

PROJECT = "/data/edr_work/edr_t3.psx"
ESM_LO, ESM_HI = 0.27, 0.52  # Toth et al. 2025 reported reprojection-error envelope (px)


def main():
    doc = Metashape.Document()
    doc.open(PROJECT, read_only=True)
    ch = doc.chunks[0]
    pc = ch.tie_points
    pts = pc.points
    proj = pc.projections
    pid = [-1] * len(pc.tracks)
    for i in range(len(pts)):
        pid[pts[i].track_id] = i
    sse, n = 0.0, 0
    for cam in ch.cameras:
        if not cam.transform:
            continue
        T = cam.transform.inv()
        calib = cam.sensor.calibration
        for p in proj[cam]:
            j = pid[p.track_id]
            if j < 0:
                continue
            pt = pts[j]
            if not pt.valid:
                continue
            e = calib.error(T.mulp(pt.coord), p.coord)
            sse += e.norm() ** 2
            n += 1
    rms = math.sqrt(sse / n) if n else float("nan")
    where = ("WITHIN" if ESM_LO <= rms <= ESM_HI
             else "BELOW" if rms < ESM_LO else "ABOVE")
    print(f"scale_bars={len(ch.scalebars)}  tie_points={len(pts)}  "
          f"projections_used={n}")
    print(f"POST-REDUCTION reprojection RMS = {rms:.4f} px")
    print(f"ESM envelope (Toth) = {ESM_LO}-{ESM_HI} px  ->  {where} envelope")
    for sb in ch.scalebars:
        print(f"  scalebar {sb.label}: defined={sb.reference.distance} m")


if __name__ == "__main__":
    main()
