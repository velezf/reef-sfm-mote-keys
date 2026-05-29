# ADR 0017 — Wire ESM Step 4 image-quality filter before alignment; wire ADR-0015's confidence filter into the production driver; extend `--stage` rather than add CLI flags; confirm DSM = 1 cm (1 mm was a misattribution)

Status: Accepted
Date: 2026-05-29
Chat: 5 (close-out / T3 dress rehearsal)

## Context

The Chat 5 smoke validated alignment, error reduction, the focal-length A/B,
the dense build, and the ESM Step 13 confidence filter end-to-end on EDR_T8.
But two of those validations lived only in `smoke_test.py`. The production
driver `run_pipeline.py` (at commit 3e35c3b) was still the pre-ADR-0015 version
and had three gaps that the T3 dress rehearsal exposed when read against Toth
et al. 2025 ESM Table S2:

1. **ESM Step 4 (image-quality filter) was never wired anywhere.** Table S2
   Step 4 estimates per-image quality and disables blurred frames before
   matching. The smoke skipped it. The empirical cost showed up in the smoke
   A/B: only **129 of 325 EDR_T8 cameras aligned (39.7%)** — ~60% failed to
   align. Both focal arms (bundle-adjusted fallback and manual S120 5.2 mm)
   aligned the *same* 129/325, so focal length was NOT the cause. With focal
   length ruled out, image quality (motion blur, backscatter, turbidity — all
   expected in 30 m-deep reef transect video frames) is the leading remaining
   driver. ESM Step 4 is the published method's answer to exactly this, and it
   was missing.

2. **ADR-0015's confidence filter was never in the production driver.** Commit
   3e35c3b wired `cleanPointCloud` + `compactPoints` into `smoke_test.py` and
   `segment_pointcloud.py`, but `run_pipeline.py` was not touched by that
   commit. In `run_pipeline.py`'s source order the dense stage
   (`buildPointCloud`) was followed directly by the DSM stage (`buildDem`) with
   **no filter between them** — i.e. `buildDem` precedes (runs without) the
   ESM Step 13 filter. A DSM built on an unfiltered cloud is not what ADR-0015
   specifies and would carry the low-confidence outliers into the elevation
   surface.

3. **DSM resolution was described inconsistently.** The Chat 5 close-out task
   text asserted "DSM at 1 mm (ESM Table S2)". The code, ADR-0010, the
   docs/05 parameter table, and Chat 6's reconciliation needs all say **1 cm**.

A fourth, smaller question was how to control the headless→GUI→headless split
without the dense run sweeping in every transect or losing resumability.

## Decision

### 1. Add ESM Step 4 as a stage before `matchPhotos`

`filter_low_quality_images(chunk, quality_threshold=0.50)`:

- calls `chunk.analyzeImages(regular_cameras)` (verified signature on the
  installed build: `analyzeImages([cameras], filter_mask=False, [progress])`,
  Metashape 2.3.1 build 22446 — stores the score under the `Image/Quality`
  camera-metadata key);
- parses `cam.meta["Image/Quality"]` as float;
- disables cameras with quality `< 0.50` via `cam.enabled = False`;
- leaves cameras with no quality metadata enabled and excludes them from the
  disabled tally (we do not disable on missing data);
- returns `{analyzed, with_quality, no_metadata, disabled, threshold,
  min_quality, max_quality, median_quality, seconds}`.

The call site is a dedicated `step4` stage that runs after `import` and before
`align`, so disabled cameras never enter `matchPhotos`.

**Threshold pinned at 0.50, not stricter.** Agisoft's own `analyzeImages`
documentation states: *"Cameras with quality less than 0.5 are considered
blurred and we recommend to disable them."* 0.50 is therefore the vendor
recommendation, and it is what we read ESM Step 4 to mean (the ESM does not
publish a stricter cutoff). We do not invent a stricter number; if a stricter
threshold is ever justified it will be its own ADR with its own evidence. A
sanity alarm fires if Step 4 disables more than 200 of ~522 cameras — that
would indicate either a bad threshold or a genuinely unusable transect, and the
run stops for review rather than silently aligning a decimated set.

### 2. Wire ADR-0015's confidence filter into the production driver as a `filter` stage between `dense` and `dsm`

`run_pipeline.py` now has a `filter` stage that calls
`segment_pointcloud.assign_noise_by_confidence(chunk, noise_confidence)` —
the single source of the `cleanPointCloud(Confidence, threshold) +
compactPoints()` idiom (ADR-0015). It is sequenced strictly between `dense`
and `dsm`. **The DSM is never built on an unfiltered cloud.** This is the
production realization of ADR-0015, which until now existed only in the smoke.
See the ADR-0015 amendment.

### 3. Extend the `--stage` model; do NOT add `--chunk` / `--stop-after` / `--start-from`

Stages are now `import, step4, align, reduce, dense, filter, dsm, ortho,
report`. The headless→GUI→headless split is expressed by *which stages you
run*: the align portion (`import` → `reduce`) headless, then the GUI handoff
(scale bars + Jenkins coordinate frame), then the dense portion (`dense` →
`report`) headless. Each invocation opens the `.psx`, runs the requested
stage(s), and saves; each stage skips work that already exists in the project.
That already provides both resumability and the handoff split, so a separate
`--stop-after`/`--start-from`/`--chunk` mechanism would be redundant surface
area. Dataset scoping (run a dev pass on EDR_T3 only, not all 3271 images) is a
*different* concern and is handled by `--transect`, which filters the **import**
— every downstream stage then naturally operates on whatever chunks the project
contains.

### 4. DSM resolution is 1 cm (`dsm_resolution_m = 0.01`); the 1 mm figure is a misattribution

ESM Table S2 Step 14 is silent on the absolute number ("default"). Toth et al.
2025's main text states 1 cm; ADR-0010's parameter table records Toth = 1 cm
vs PIFSC = 1 mm; Chat 6 reconciliation needs 1 cm to compare against the
published P13HMEON products. The "1 mm" value is the **PIFSC SOP** figure, not
ESM — attributing it to ESM Table S2 was an error, corrected here. Operationally
1 cm is also ~100× fewer raster cells than 1 mm for the same extent, which
materially reduces the `buildDem` memory footprint that ADR-0016 flags as the
open OOM risk.

## Manifest schema additions

`pipeline_summary.json` (extended, not a separate `processing_report.json` —
Chat 6 parses this one file) now carries, per chunk:

- `stage_step4`: the Step 4 stats dict above;
- `stage_align`: `cameras_enabled`, `cameras_aligned`, `alignment_rate`,
  `focal_mode`, `tie_points`, `reproj_rms_filter_units`;
- `stage_reduce`: `reduction_path` (`logan:<mod>` or `builtin_fallback`),
  `markers_detected`, pre/post RMS, the thresholds used;
- `stage_dense`: `point_count`, `transform_scale`, region extent, hours;
- `stage_filter`: `points_before`, `points_after`, `removed`,
  `removed_fraction`;
- `stage_dsm`: raster `width`/`height`/`cells`, `resolution_m`,
  `region_clip_workaround_applied` (False), `transform_scale`;
- `stage_import`: image count + SHA-256 aggregate of the input set;
- top level: `metashape_version`, `gpu_devices`, `esm_parameters`,
  `generated_utc`, and a `dsm_resolution_note` recording the 1 cm vs 1 mm
  provenance so the number is never silently questioned again.

Each stage persists its stats into `chunk.meta` (as JSON strings) at the time
it runs, so the values survive across the separate `--stage` invocations that
the GUI handoff forces, and the `report` stage assembles them into the manifest.

## Consequences

- **The smoke's 39.7% alignment is now expected to improve** once Step 4 drops
  the blurred frames before matching — but by how much is an *open empirical
  question*, not a closed one. This ADR does NOT claim Step 4 fully explains the
  ~60% loss. Other candidates remain: insufficient overlap at transect ends,
  the two known LZW-undecodable frames (ADR-0009), genuine turbidity. Full
  alignment-loss attribution is a separate investigation; this ADR only wires
  the published method's quality gate and records the before number.
- **Disabling cameras changes the denominator.** The alignment-rate sanity
  alarm (< 70% of *enabled*) is measured against post-Step-4 enabled cameras,
  not the raw 522. The manifest records both `cameras_total` and
  `cameras_enabled` so the distinction is auditable.
- **Built-in error reduction is currently the only path.** The Logan USGS
  script is not vendored on the instance (`import reduce_error` fails; no clone
  on disk), so the `reduce` stage uses the faithful built-in transcription and
  records `reduction_path = "builtin_fallback"`. Per ADR-0010 Logan is the
  preferred tool; using the fallback is logged loudly as a per-run documented
  departure rather than silently preferred. Vendoring Logan is tracked as
  follow-up; see docs/05 "Logan integration".
- **ADR-0016 is now testable.** With a `filter` stage before `dsm`, a 1 cm
  resolution, and a metric-scaled chunk (post-GUI handoff), the `dsm` stage
  calls `buildDem` with NO `region=` clip and surfaces the result either way —
  success validates the ADR-0016 hypothesis; OOM escalates to ADR-0018. The
  smoke's BBox workaround is NOT re-applied.

## What this ADR does NOT close

- Whether Step 4 actually recovers the smoke's alignment loss (empirical, T3).
- Full attribution of the ~60% alignment loss (multi-cause; separate work).
- The ADR-0016 `buildDem` extent question (resolved by the T3 dense run, not by
  this wiring).
- Logan vendoring (deferred; fallback is documented).

## Sources

- Agisoft Metashape Professional Python API 2.3.1 reference, `Chunk.analyzeImages`
  docstring (verified on installed build 22446): "Cameras with quality less
  than 0.5 are considered blurred and we recommend to disable them."
- Toth et al. 2025 Supplementary Material Table S2 Steps 4 and 14.
- [ADR-0010](0010-adopt-toth-usgs-metashape-workflow.md) (parameter source;
  Toth DSM = 1 cm, Logan REQUIRED).
- [ADR-0015](0015-headless-step13-engineered-departure.md) (the confidence
  filter now wired into production).
- [ADR-0016](0016-builddem-extent-beyond-pcextent-smoke-bbox-clip.md) (the
  buildDem extent question this wiring makes testable).
- Smoke v-series logs `/data/edr_work/logs/smoke_*.log` (129/325 alignment,
  both arms identical).

#tags: metashape-api, esm-step-4, image-quality, analyzeImages, alignment, run-pipeline, production-wiring, step-13, dsm-resolution, stage-model, chat5
