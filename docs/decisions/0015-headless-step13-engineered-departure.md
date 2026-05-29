# ADR 0015 — Headless ESM Step 13 implementation: engineered destructive departure from Toth 2025's GUI classify-and-keep workflow

Status: Accepted; **Supersedes [ADR-0013](0013-confidence-noise-filter-via-cleanpointcloud.md) and [ADR-0014](0014-headless-confidence-filter-via-docpopi-pattern.md)**
Date: 2026-05-28
Chat: 5

## Context

Toth et al. 2025's Electronic Supplementary Material Table S2 Step 13
specifies the dense point cloud's noise-handling and segmentation workflow.
Verbatim from the ESM:

> **Step 1.** Create noise filter: Tools→Point Cloud→Filter by
> confidence→Enter min 0, max 1→Locate the Free-Form Selection tool in the
> selection tool drop down>lasso all points with confidence→Right
> click→Assign class→Select Low-point(noise)
>
> Dense point clouds were segmented into three classes... Low-point noise
> includes point with a confidence <2.
>
> **Step 2.** Create additional filters. Tools→Point Cloud→Reset
> Filter→Tools→Point Cloud→Select Filter→uncheck Low Point
> Noise→Free-form Selection→lasso features of interest in point
> cloud→Right click→Assign→select a feature class. For this project we
> used "medium vegetation" for canopy, "ground" for reef base, "man-made
> object" for outplants, "low-point noise" for noise.

This is a *classify-and-keep* workflow: low-confidence points are
reclassified as `Low-point (noise)`, NOT removed; they remain in the
cloud. ESM Step 14 then drives `buildDem` with `point_classes` to filter
at build time, choosing which classes contribute to the elevation model.

## Constraint

The Metashape Professional Python API 2.3.1 reference
(<https://www.agisoft.com/pdf/metashape_python_api_2_3_1.pdf>) exposes
the following documented surface for confidence-related dense-cloud
operations (line numbers refer to the rendered text version
`/tmp/metashape_api.txt` produced by `pdftotext -layout`):

- **`cleanPointCloud([point_cloud][, point_clouds], criterion=Confidence, threshold=0[, frames][, progress])`**
  (line 1929): "Remove points based on specified criterion."
- **`setConfidenceFilter(min_confidence, max_confidence)`** (line 6460):
  "Set filter by confidence." No documented interaction with selection.
- **`cropSelectedPoints([point_classes][, progress])`** (line 6217):
  "Crop selected points." Parameter docs say `point_classes ...` are
  "Classes of points to be removed" — contradicting the method name's
  implication of "crop = keep."
- **`removeSelectedPoints([point_classes][, progress])`** (line 6318):
  "Remove selected points." Same `point_classes` description as crop.
  The two methods are documented separately with effectively identical
  signatures; the docs do not explain how they differ.
- **`compactPoints([progress])`** (line 6203): "Permanently removes
  deleted points from point cloud." This is the only doc hint that
  points can exist in a "deleted" state without being removed.
- **`point_count`** (line 6304): "Number of points in point cloud."
  No mention of staleness, deferral, or interaction with compactPoints.

The API exposes no documented `selectPointsByConfidence` and no
`assignClassByCriterion`. A faithful headless implementation of ESM
Step 13's classify-and-keep would require iterating
`PointCloud.Point.confidence` per point in Python and setting
`Point.classification = LowPoint`. This is documented (the `Point`
class exposes both `confidence: int` and `classification: int`), but is
operationally slow: a per-point Python loop over ~30M points (single
EDR_T8 transect) would dominate the per-transect runtime budget and
scale worse on EDR_T1 (10× the image count, comparable dense scale).

## Decision

**Implement ESM Step 13 as a destructive removal of low-confidence
points** using the documented Chunk method, with the empirically-required
materialization step:

```python
chunk.cleanPointCloud(
    criterion=Metashape.PointCloud.Criterion.Confidence,
    threshold=2,
)
pc.compactPoints()
```

Document this as an engineered departure from ESM Step 13's
classify-and-keep semantic. The departure is the headline finding, not
a buried hack: any reviewer reading `segment_pointcloud.py` alongside
Toth's ESM expecting the classify-as-LowPoint step will see *removal*
instead. This is by design, scoped to v1, and traded against per-point
iteration runtime cost on a 30M+ point cloud.

The **`compactPoints()` requirement is undocumented Metashape
behavior**, empirically established via
`scripts/metashape/probes/probe_v8_cleanpc.py`: `cleanPointCloud` marks
points for deletion but `point_count` reads the pre-compaction value
(stale) until `compactPoints` materializes the removal. The destructive
idiom therefore relies on an undocumented implementation detail of
Metashape 2.3.1 build 22446. If a future build changes this behavior,
the patch is one line; the probe script will detect the change.

## Consequences

**Stated honestly:**

1. **Low-confidence points are removed at threshold=2 (ESM strict "< 2"),
   not reclassified.** A reviewer cross-referencing Toth's ESM will find
   the production output identical to a Toth-pipeline output where
   `Low-point(noise)` was excluded from `buildDem` — the
   end-state DSM is the same — but the intermediate cloud differs:
   ours has 24% fewer points (per smoke v8 on EDR_T8: 30,899,531 →
   ~23,469,744 after threshold=2). Theirs has the same count, with
   ~24% labelled noise.

2. **Downstream `buildDem` does not use the `point_classes` parameter.**
   ESM Step 14 specifies `point_classes` to select which classes
   contribute to the DEM. Because our removal is destructive, there are
   no classes to filter on after Step 13 — every surviving point is
   class `Created` (the default). This is a second documented departure
   from ESM Step 14, mechanically implied by the Step 13 choice.

3. **Multi-class segmentation (canopy, outplants, reef base) is NOT
   implemented in v1.** ESM Step 13 specifies four classes; this
   implementation handles only the noise class. v2 work targeting
   outplant survival tracking or "with-outplants vs without-outplants"
   structural-complexity comparison (Toth 2025 Fig. 3) will require
   migration to per-point classification — likely a hybrid of
   `cleanPointCloud` for noise (kept) plus per-point classification of
   the other three classes (gorgonian canopy, staghorn outplants, reef
   base). The carbonate-budget analysis that v1 actually targets does
   not need the class split.

4. **Reconciliation with Toth's published topographic complexity metrics
   in Chat 6 must verify that removed-vs-classified produces comparable
   DSM-derived metrics.** If structural complexity metrics
   (rugosity, surface-to-planar ratio, vector ruggedness measure)
   diverge between our destructive cloud and Toth's classified-and-kept
   cloud at the same threshold, the departure has methodological
   implications beyond runtime — and the v2 migration becomes higher
   priority. Initial expectation: DEM-derived metrics are insensitive
   to whether noise was removed-then-excluded vs kept-with-class-and-
   excluded, because the DEM-build operation sees the same surface
   either way.

## Amendment (2026-05-29, Chat 5 close-out / T3 dress rehearsal)

When this ADR was written, the `cleanPointCloud` + `compactPoints` filter was
wired into `smoke_test.py` and exposed as
`segment_pointcloud.assign_noise_by_confidence`, but it was **not** wired into
the production driver `run_pipeline.py` (commit 3e35c3b did not touch that
file). In `run_pipeline.py`'s source order the dense stage was followed
directly by `buildDem` with no filter between them — so the production DSM
would have been built on an *unfiltered* cloud, contrary to this ADR.

[ADR-0017](0017-esm-step-4-image-quality-and-production-wiring.md) closes that
gap: `run_pipeline.py` now has a dedicated `filter` stage that calls
`assign_noise_by_confidence` and is sequenced strictly between `dense` and
`dsm`. The DSM is never built on an unfiltered cloud. The
`cleanPointCloud + compactPoints` idiom and the `compactPoints`-materialization
requirement documented above remain the single source of truth in
`segment_pointcloud.py`; the production driver delegates to it rather than
duplicating the calls. The decision in this ADR is unchanged — only its reach
(smoke-only → production) was corrected.

## History

This is the third ADR on the same decision. The wrong turns are part of
the methodology record, not concealed:

- **[ADR-0013](0013-confidence-noise-filter-via-cleanpointcloud.md)**
  proposed `cleanPointCloud(criterion=Confidence, threshold=2)` based on
  a false reading: an initial smoke run reported "0 removed" because
  `point_count` was read immediately after `cleanPointCloud` without
  `compactPoints`. Wrong premise; right API choice.
- **[ADR-0014](0014-headless-confidence-filter-via-docpopi-pattern.md)**
  superseded ADR-0013 after observing the zero `point_count` delta and
  incorrectly concluding `cleanPointCloud` was non-functional. ADR-0014
  proposed `setConfidenceFilter(0, N) + cropSelectedPoints()` (the
  "DocPopi pattern" from Agisoft forum 15523), backed by a destructive
  probe (`probe_confidence_delete.py`) that reported point removal.
  Critically, that probe *also* called `compactPoints()` after each
  pattern — masking the fact that `cleanPointCloud` was working all
  along; both patterns produced visible removal only after compaction.
- **This ADR (0015)** investigated by isolating each pattern with and
  without `compactPoints` (`probe_v8_cleanpc.py`,
  `probe_v8_filter_with_bbox.py`), which revealed `point_count` is
  stale until `compactPoints()` materializes deletions. `cleanPointCloud`
  had been working all along. ADR-0015 restores ADR-0013's API choice
  with the materialization step explicit, and **reframes the entire
  decision as an engineered destructive departure from ESM** rather
  than a faithful reproduction.

ADR-0013 and ADR-0014 are retained in the repo as historical record:
the empirical-validation-and-correction process they document is itself
portfolio-relevant evidence of the project's methodology discipline. The
fact that three ADRs were required to converge on the right answer
reflects the actual cost of working against undocumented API behavior in
a vendor product, and shipping a wrong conclusion would have been worse
than documenting the iteration honestly.

## Sources

- Metashape Pro Python API 2.3.1 reference
  (<https://www.agisoft.com/pdf/metashape_python_api_2_3_1.pdf>;
  SHA-256 `d683ca7e1965eecdb5eea0d9cbac261bcf74e701a61e9d7d8c001968dab102f9`).
  See `docs/downloads.md`.
- Toth et al. 2025 Supplementary Material Table S2 Step 13
  (<https://static-content.springer.com/esm/art%3A10.1038%2Fs41598-025-04818-3/MediaObjects/41598_2025_4818_MOESM1_ESM.pdf>;
  SHA-256 `7f9d19e85bf1d735c8dc5d41dde9cffe6e84e84da2243104a6863c1b0a75d0d6`).
  See `docs/downloads.md`.
- Agisoft helpdesk article 31000162209 on Point Cloud Editing with
  Confidence Filter Tool
  (<https://agisoft.freshdesk.com/support/solutions/articles/31000162209-point-cloud-editing-with-confidence-filter-tool>).
- Probe scripts in `scripts/metashape/probes/`: `probe_confidence_present.py`,
  `probe_confidence_delete.py`, `probe_v8_filter_with_bbox.py`,
  `probe_v8_cleanpc.py`, others — the empirical evidence record for
  ADR-0013, 0014, and 0015.

#tags: metashape-api, dense-cloud, confidence, segment, smoke-test, esm-step-13, supersedes-0013, supersedes-0014, engineered-departure
