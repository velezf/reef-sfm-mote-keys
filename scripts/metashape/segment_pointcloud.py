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
    """Remove dense-cloud points with confidence < max_conf.

    Implements ESM Step 13 Step 1 noise handling as an *engineered
    destructive departure* from Toth's classify-and-keep GUI workflow.
    See ADR-0015 for the full reasoning. The function name is retained
    for run_pipeline.py call-site compatibility but is slightly
    misleading: it removes the noise points outright rather than
    assigning them to the LowPoint class.

    Implementation: chunk.cleanPointCloud(Confidence, threshold) is the
    documented destructive API (Metashape 2.3.1 Python reference line
    1929, "Remove points based on specified criterion"); compactPoints()
    is required to materialize the deletion (point_count is stale until
    compact is called — undocumented Metashape behavior empirically
    established via scripts/metashape/probes/probe_v8_cleanpc.py).

    Returns the dense-cloud point_count after removal.
    """
    pc = chunk.point_cloud
    if pc is None:
        sys.exit(f"{chunk.label}: no dense cloud to segment.")

    # Engineered destructive departure from ESM Step 13's classify-and-keep
    # workflow. See ADR-0015 for full reasoning. Documented as remove
    # (cleanPointCloud line 1929) followed by undocumented-but-required
    # compactPoints materialization (line 6203).
    n_before = pc.point_count
    chunk.cleanPointCloud(
        criterion=Metashape.PointCloud.Criterion.Confidence,
        threshold=int(max_conf),
    )
    pc.compactPoints()
    n_after = pc.point_count
    removed = n_before - n_after
    print(f"{chunk.label}: ESM Step 13 noise removal (cleanPointCloud + "
          f"compactPoints, threshold={max_conf}): {n_before:,} -> {n_after:,} "
          f"({removed:,} points removed, {100*removed/max(n_before,1):.1f}%). "
          f"See ADR-0015.", flush=True)
    if n_before > 0 and removed == 0:
        print(f"WARNING: {chunk.label}: ESM Step 13 removed 0 points at "
              f"threshold={max_conf}. This is expected if the dense cloud "
              f"has no points with confidence < {max_conf}; not necessarily "
              f"an error. See bbox_pre_post_filter.json to verify cloud "
              f"state.", flush=True)
    return n_after


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
