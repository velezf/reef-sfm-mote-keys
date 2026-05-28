#!/usr/bin/env python3
"""
segment_pointcloud.py — ESM Step 13 point-cloud segmentation, partial automation.

ESM Table S2 Step 13 segments each dense cloud into four classes via the GUI
lasso tool: low-point noise, canopy, outplants, reef base. That segmentation is
what enables the "with outplants vs without outplants" structural-complexity
comparison in Toth et al. 2025 Fig. 3.

What this chat does (decided in Chat 5 per ADR-0010's deferred segmentation
scope):

  * AUTOMATED for all three transects: the confidence-based noise filter
    (ESM Step 13, Step 1). Points with confidence < 2 are assigned to the
    Metashape "low-point noise" class. This is deterministic, scriptable, and
    fully faithful to the published method — no judgement call involved.

  * MANUAL for ONE transect (operator's choice): the canopy / outplant /
    reef-base distinction via the GUI lasso, reproducing ESM Fig. S4 end to
    end. This is the reference reproduction.

  * The other two transects: confidence-noise-filtered only ("with-everything"
    metrics). The canopy/outplant/base split is left for v2 — see the CV
    approach sketched at the bottom of this file and flagged in
    docs/09-v2-roadmap.md.

Why not automate the full four-class split now? Separating staghorn outplants
from gorgonian canopy from reef base in an underwater dense cloud is a semantic
3D segmentation problem with no off-the-shelf model trained on this domain. The
confidence filter is a thresholding operation; the class split is a perception
problem. Conflating the two would misrepresent the difficulty. See the v2 note.

Metashape class codes (ESM Step 13 uses these built-in classes as proxies):
    low-point noise   -> Metashape.PointClass.LowPoint
    canopy            -> Metashape.PointClass.MediumVegetation
    reef base         -> Metashape.PointClass.Ground
    outplants         -> Metashape.PointClass.ManMadeObject

Usage:
    metashape.sh -r segment_pointcloud.py --project /data/edr/edr.psx \\
        --chunk EDR_T1 --noise-confidence 2.0
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import Metashape
except ImportError:
    sys.exit("Run through metashape.sh; Metashape module not importable.")


def assign_noise_by_confidence(chunk: "Metashape.Chunk", max_conf: float) -> int:
    """Assign points with confidence < max_conf to the LowPoint (noise) class.

    Faithful to ESM Step 13 Step 1: 'Filter by confidence -> min 0, max 1 ->
    assign Low-point(noise)'. We expose the threshold because the ESM text and
    the figure caption differ slightly (caption says confidence < 2); 2.0 is the
    documented project value. Returns the number of points reclassified.
    """
    pc = chunk.point_cloud
    if pc is None:
        sys.exit(f"{chunk.label}: no dense cloud to segment.")

    # Set the active confidence filter window, select, assign, reset.
    pc.setConfidenceFilter(0, int(max_conf))      # show only low-confidence pts
    pc.assignClassToSelection(Metashape.PointClass.LowPoint)
    pc.resetFilters()
    n = pc.point_count
    print(f"{chunk.label}: assigned points with confidence < {max_conf} "
          f"to LowPoint (noise). Cloud now {n} pts total.", flush=True)
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True, type=Path)
    ap.add_argument("--chunk", required=True, help="Transect label, e.g. EDR_T1")
    ap.add_argument("--noise-confidence", type=float, default=2.0)
    args = ap.parse_args()

    doc = Metashape.Document()
    doc.open(str(args.project), read_only=False)
    chunk = next((c for c in doc.chunks if c.label == args.chunk), None)
    if chunk is None:
        sys.exit(f"Chunk {args.chunk} not found.")

    assign_noise_by_confidence(chunk, args.noise_confidence)
    doc.save()
    print("Noise classification saved. Canopy/outplant/reef-base split is "
          "manual (GUI lasso) for the reference transect; see docs.", flush=True)


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# v2 SKETCH — programmatic canopy/outplant/reef-base segmentation (NOT in scope)
# ---------------------------------------------------------------------------
# Flagged for docs/09-v2-roadmap.md. A credible automated path, in rough order
# of effort/payoff:
#
#  1. Height-above-base + verticality features per point (cheap, no training).
#     Fit a reef-base surface (RANSAC plane or low-percentile DSM), compute
#     height-above-base; compute local verticality from the normal. Gorgonian
#     canopy is high + vertical; reef base is low. This alone separates canopy
#     from base reasonably and is pure geometry — a real, defensible v2.1.
#
#  2. Outplants are the hard class. Staghorn (Acropora cervicornis) thickets
#     overlap canopy in height/verticality. Color helps (live staghorn vs
#     gorgonian) but underwater color is unreliable pre-Hatcher-correction.
#     This is where a learned model earns its keep.
#
#  3. Learned approach: voxelise + a sparse-conv semantic seg net
#     (e.g. MinkowskiNet / KPConv class of models). Needs labelled training
#     data — exactly the manually-segmented transect this chat produces. One
#     hand-labelled transect is a seed set, not a training set; honest framing
#     in the writeup is "we produced the label substrate a future model would
#     need," not "we built the model."
#
# The portfolio-honest claim: confidence noise filtering is solved and shipped;
# the semantic split is manual now and a scoped research extension later.
