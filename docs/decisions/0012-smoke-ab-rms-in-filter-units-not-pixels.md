# ADR 0012 — Smoke A/B reprojection RMS is in Metashape filter units, not image pixels

Status: Accepted
Date: 2026-05-28
Chat: 5

## Context

`smoke_test.py` runs a focal-length A/B (RISK 2 from
[ADR-0009](0009-exif-csv-and-tiff-encoding-metadata-loss.md)) on the smallest
transect: align twice — once with the bundle-adjusted fallback, once with the
manual S120 calibration — and pick the arm with lower post-error-reduction
reprojection RMS. The pick is written to `focal_decision.json`, which the full
run reads programmatically to decide whether to seed S120 intrinsics. The
decision is supposed to be an artifact, not an operator judgement call.

For the artifact to be a valid justification, the RMS needs to be a number you
can compare. We had three plausible ways to compute it on the live chunk after
error reduction, and the first two failed during smoke development:

1. **Custom per-projection RMS via `Camera.error(point.coord, projection.coord)`.**
   The Agisoft docs describe this as returning a pixel-error vector. In an
   unscaled chunk (no FocalLength EXIF, no scale bars yet — exactly the smoke
   state) it produced RMS values of ~19,000 (fallback) and ~19,100 (manual).
   Image dimensions are 4000×3000 px; an RMS of 19,000 is physically
   impossible after a 0.3-px reprojection-error filter, so the number is in
   some other unit, or the function's frame expectation is not what the docs
   suggest in this state.
2. **Custom per-projection RMS via `Camera.project(Vector3)` minus
   `projection.coord`.** Same idea, explicit Vector3 to rule out a Vector4-
   homogeneous mishandling. The fallback arm came out at ~19,143 and the
   manual arm at ~518,246,695. Both clearly not pixels; the manual arm's
   eight-orders-of-magnitude separation from the fallback was a strong tell
   that the coordinate frame the API expects differs from what we are passing,
   and that the discrepancy scales with whatever frame seeding we do
   (manual-arm intrinsics seed → wildly different chunk-internal scale).

In both cases the manual re-projection in chunk-internal coordinates is wrong
because the chunk has no metric scale: bundle adjustment is well-defined up to
a similarity, so "1 unit" in the chunk frame is arbitrary, and the projection
math we wrote does not absorb that scale correctly. This is not a bug in the
Metashape API — it is a category error in how we were using it pre-scale.

3. **Per-point reprojection-error filter values via
   `Metashape.TiePoints.Filter(ReprojectionError).values`.** This is the same
   per-point value the gradual-selection error-reduction step compares to its
   threshold. After a 0.3-threshold filter, every remaining value is ≤ 0.3 by
   construction, so an RMS in the 0.1–0.3 range is what you actually observe.
   Crucially, the units are **Metashape's normalized internal filter units, not
   raw image pixels.** They behave like pixels in relative comparisons (lower
   is better, threshold semantics work), but the absolute number is not the
   same number the Metashape report PDF prints when it says "Reprojection error
   (pix)".

We chose option 3 because it works in the unscaled smoke state — it is exactly
the metric Metashape's own filter compares against, so it is robust to the
chunk scale being arbitrary. The cost is that the smoke artifact's RMS is no
longer in the same units as Toth et al. 2025's published 0.27–0.52 px envelope,
which is what Chat 6's reconciliation pipeline compares against.

The full run is different: after the manual DCV interlude (marker detection,
scale-bar assignment, Jenkins coordinate-frame placement — see
[docs/05-metashape-processing.md](../05-metashape-processing.md)), the chunk
has metric scale and the report PDF's reprojection error is in real image
pixels. That is the number that goes into the Toth comparison.

## Decision

1. **The smoke A/B uses `TiePoints.Filter(ReprojectionError).values` as its
   RMS source.** This is the metric the gradual-selection step uses, so it is
   guaranteed to be in the same units as the thresholds the error reduction
   was driven by.
2. **The artifact field is named `reproj_rms_filter_units`** (renamed from
   `reproj_rms_px`), and the criterion record carries an explicit
   `rms_units_note` describing what these units are and what they are not.
   The decision margin constant is `RMS_MARGIN_FILTER`. Log lines and
   rationale strings say "filter units", never "px".
3. **The smoke RMS is for the A/B comparison only.** The pixel-calibrated RMS
   that Chat 6 reconciles against the Toth 0.27–0.52 px envelope comes from
   the **full-run** Metashape report PDF, after scale bars + coordinate frame
   are set — which is when the chunk's internal "pixel" units actually
   correspond to image pixels.
4. **No change to the decision logic.** The criterion is still RMS-primary,
   alignment-tiebreak. The DECIDED / NEEDS_REVIEW thresholds in
   `_decide_focal` apply to the filter-unit RMS gap as they would have to a
   pixel-unit RMS gap; the *relative* comparison between two arms measured
   the same way is what the decision turns on, and that is unaffected.

## Consequences

**Pro**

- The smoke artifact is correct and trustworthy as input to `run_pipeline.py`.
  Before this fix the artifact was numerically nonsense, even though the
  decision branch it triggered (DECIDED, fallback) happened to be reasonable.
- The unit confusion is now load-bearing in the schema: a future reader who
  greps for `reproj_rms_px` finds nothing in this codebase. Anyone reading
  `focal_decision.json` reads `reproj_rms_filter_units` and a unit note
  pointing to this ADR. The mistake is hard to re-make.
- The decision logic and unit tests are unchanged in behavior; only the field
  name moved, so the 7-case unit test suite continues to gate the criterion.

**Con**

- The smoke artifact no longer carries a number that Chat 6 can plug into its
  Toth-envelope reconciliation. That number was never going to be valid from
  the smoke anyway (the smoke runs on a subset, before scale, before the
  manual GUI interlude), but it is worth being explicit: the smoke is not a
  source of evidence about reconstruction quality vs Toth, only about which
  focal arm to commit to.
- Two adjacent RMS numbers will exist in the project: the smoke's
  filter-units RMS in `focal_decision.json`, and the full run's pixel-
  calibrated RMS in the Metashape report. A reviewer who skims could conflate
  them. The unit-note field in the artifact, the docstring on
  `_reprojection_rms`, the rationale strings, the smoke section in
  docs/05-metashape-processing.md, and this ADR exist to make conflation
  hard.
- Per-point RMS (this approach) differs from per-projection RMS (what
  Metashape's report quotes, with units transformed out) even at the same
  scale, so even after the unit clarification the smoke's RMS would not
  exactly match what a future report on the same chunk prints. They are
  related metrics over the same residuals, not the same number. For the A/B
  this is irrelevant; for the writeup it is worth noting.

## Notebook narrative

The focal-length A/B in `smoke_test.py` uses Metashape's per-point
reprojection-error filter values to compare the bundle-adjusted-fallback arm
against the manual-S120-calibration arm. These values are in Metashape's
internal filter units rather than raw image pixels because the smoke runs
before scale bars and the coordinate frame are set — the chunk's "pixel"
scale is arbitrary up to the bundle's similarity ambiguity. The unit choice
is correct for the smoke's purpose (relative comparison of two arms measured
the same way) but means the smoke's RMS is not directly comparable to Toth
et al. 2025's published 0.27–0.52 px envelope. That comparison uses the
pixel-calibrated RMS from the full-run Metashape report, after the manual
DCV interlude. The two RMS numbers are related metrics over the same kind of
residuals; they are not the same number.

#tags: smoke-test, focal-length, reprojection-error, metashape-api, units, ab-test
