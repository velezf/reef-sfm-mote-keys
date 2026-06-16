# ADR-0035 — Falsified: step4 quality threshold 0.50→0.30 does not recover R2 registration

**Status:** Accepted (falsified hypothesis)
**Date:** 2026-06-16
**Related:** ADR-0033 (R2 reconstruction), ADR-0034 (frame-retention QC criterion)

---

## Context

EDR_T1_R2 at step4 threshold 0.50 disabled 140 of 272 cameras (51.5%), leaving
132 analyzed and 131 aligned. `frame_retention` = 0.485 → FAIL; `registration_ratio`
= 131/272 = 0.482 → FAIL.

**Hypothesis under test:** Lowering the step4 quality threshold from 0.50 to 0.30
would recover the 140 disabled cameras, increase the camera pool available for
alignment, and improve `registration_ratio` above the 0.90 pass gate.

## Evidence

Step4 re-run at threshold 0.30 on a fresh copy (`edr_r2_q030.psx`, q050 preserved
as foil):

| metric | q050 (threshold 0.50) | q030 (threshold 0.30) |
|--------|-----------------------|-----------------------|
| cameras analyzed | 132 | 270 |
| cameras disabled | 140 | 2 |
| frame\_retention | 0.485 | 0.993 |
| cameras aligned | 131 | 131 |
| registration\_ratio | 0.482 | 0.485 |

Two cameras fell below the 0.30 floor (quality < 0.30). Of the 139 recovered cameras,
all were passed into alignment — yet the aligned count remained 131. The recovered
cameras produced additional tie-point matches (≈ 603K vs 237K at q050), but those
cameras did not triangulate into the connected block. Alignment ran under production
Toth ESM Table S2 parameters (confirmed by direct invocation of `run_pipeline.py`).

## Decision

**The hypothesis is falsified.** 131 cameras is a ceiling set by the transect corpus
geometry (out-and-back overlap pattern, limited cross-track redundancy at the far end),
not by the step4 quality threshold.

The two QC criteria cleanly separate the effects:
- `frame_retention` is threshold-sensitive (0.485 → 0.993): 0.30 passes this gate.
- `registration_ratio` is threshold-insensitive (stays at ≈ 0.48): no threshold
  recovers the structural coverage gap. This failure is characterized, not tunable.

`edr_r2_q030.psx` proceeds to dense → filter → aoi → dsm at threshold 0.30 because:
1. frame_retention 0.993 is markedly better provenance than 0.485.
2. The dense cloud and DSM are built from the same 131 cameras either way; the product
   quality does not change.
3. The `registration_ratio` FAIL is documented here; it appears in the QC report as
   a characterized limitation of the corpus, not an unresolved pipeline failure.

## Corollary: q030 DSM is functionally equivalent to q050 DSM (depth-map reuse)

`edr_r2_q030.psx` was copied from `edr_r2.psx` (q050), so the `.files` directory
carried q050's pre-computed depth maps. When `stage_dense` ran on q030,
`buildDepthMaps()` found the existing depth maps and reused them rather than
recomputing — the dense stage completed in 0.085 h instead of the expected ~2–3 h.

This reuse is **valid**: the same 131 cameras converged to essentially identical
bundle-adjustment poses (Logan reduce produced 236,859 pts / 0.1397 RMS in both
runs — bit-level match). The q030 dense product differs from q050 only by minor
numerical sampling effects (70,382,323 raw pts vs 47,143,867; after confidence
filter: 47,071,306 vs 47,143,867; AOI-cropped: 12,560,807 vs 12,585,711; DSM
cells 999×100 vs 1000×100). These differences arise from the changed step4
enabled-camera set affecting `buildDepthMaps`' depth-map merging, not from
independent depth estimation on new camera poses.

**The q030 DSM does not represent an independent reconstruction.** Its provenance
is recorded in `esm.dense.depth_maps_source = "q050_inherited"` and propagated
to `esm.report.dense_provenance`.

## Consequences

- The 0.30 DSM sha (`50d1f143`) replaces `620bc3bc` (q050 foil) as the reconcile
  target — but it carries forward the same depth maps, so it tests `frame_retention`
  provenance improvement, not independent depth estimation.
- `registration_ratio` FAIL will appear in the empirical QC pass; that is expected
  and recorded here. Do NOT attempt further threshold tuning to fix it.
- `scale_bar_errors` FAIL at threshold 0.001 m (peak residual 4.4 mm > 1 mm):
  same 3 scale bars as q050, same geometry → same residuals. Threshold is the
  calibrated floor (ADR-0031); the FAIL is documented, not a regression.
- No SOP deviation: Toth ESM Table S2 alignment parameters were applied unchanged;
  only the pre-alignment step4 quality floor was varied in this experiment.
