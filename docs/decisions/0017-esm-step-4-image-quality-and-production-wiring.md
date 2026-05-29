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
   matching (ESM verbatim, line 101–102: *"Image quality was estimated and
   images with image quality <0.50 were disabled."*). The smoke skipped it.
   The smoke A/B separately surfaced a low alignment rate — only **129 of 325
   EDR_T8 cameras aligned (39.7%)**, with both focal arms (bundle-adjusted
   fallback and manual S120 5.2 mm) aligning the *same* 129/325, which rules
   out focal length as the cause. **Step 4 and the T8 alignment loss are kept
   distinct.** Step 4 is image-quality *hygiene* — drop frames the SfM solver
   shouldn't trust — and is wired because the published method specifies it and
   we were not running it. It is **not** claimed here to be the fix for the
   39.7%; the cause of the T8 loss (end-of-transect overlap, the two
   LZW-undecodable frames per ADR-0009, turbidity, or quality) is a separate,
   still-open question. Conflating "we added the quality gate" with "we
   explained the alignment loss" would be the overclaim this ADR avoids.

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

**The 0.50 value is Toth's, verbatim — but it does not transfer cleanly to our
data, and the threshold we actually apply is decided empirically.** ESM Step 4
(line 101–102) and Agisoft's own `analyzeImages` doc both say disable
`< 0.50`. So 0.50 is not invented — it is the published cutoff. But on the
EDR_T3 frames the 0.50 cut disables **242 of 522 cameras (46.4%)**, which the
`step4` stage's sanity alarm (`> 200 of ~522`) correctly flagged and
hard-stopped on. The reason is in the distribution, not the threshold:

```
EDR_T3 Image/Quality (Metashape 2.3.1, our re-encoded TIFFs):
  min 0.000 | p25 0.458 | median 0.507 | p75 0.568 | max 0.698
  < 0.50 = 242 (46.4%)   < 0.40 = 43 (8.2%)   < 0.30 = 5 (1.0%)   ~0.0 = 2
```

The scores form a tight unimodal bell **centered on 0.50** and topping out at
0.70 — nothing scores "good" on Agisoft's scale. Metashape's `Image/Quality` is
a sharpness/contrast metric calibrated for aerial/terrestrial photography;
underwater reef frames (backscatter, low contrast, uniform water column)
systematically score low. A literal 0.50 here bisects a usable transect at its
center of mass rather than separating blurred from sharp.

**Non-transferability is a HYPOTHESIS, not confirmed.** It is supported by (a)
our distribution being centered on 0.50, and (b) the domain-calibration
argument above. It is **not** confirmed against Toth's actual EDR_T3
registered-camera count, because we do not have that number: the ESM contains
no per-transect registration counts (Table S1 is coral-outplant *survival*, not
camera registration — a number that looks tempting and is the wrong column),
and the P13HMEON product release (which would carry the Metashape processing
reports) was never downloaded — its repo directory is empty. Confirming the
hypothesis against Toth's count is deferred to Chat 6, once P13HMEON is
backfilled (see Consequences).

**So the threshold is decided empirically on our own data, via an A/B align**
(`scripts/metashape/probes/ab_quality_threshold.py`):

- **Arm q050** — Toth's verbatim cut, disable `< 0.50` (242 disabled, 280 enabled).
- **Arm q030** — *floor* cut, disable `< 0.30` (5 disabled — the genuine low
  tail, which includes the 2 degenerate ~0.0 frames `EDR_T3_R1_000130/000135`;
  517 enabled).

Both arms run identical alignment (ESM High, 60k). Decision rule: keep whichever
aligns **comparably with more coverage**. If the 0.50 cut yields no alignment
benefit over the floor, that is evidence it over-cuts our re-encoded TIFFs, and
we adopt the floor and document the departure with that A/B evidence. The
A/B result and the chosen threshold are recorded in the Empirical record section
below and in docs/05. `run_pipeline.py` exposes `--quality-threshold` so the
chosen value is explicit and auditable per run; the `> 200` disabled alarm
stays, so any future transect where 0.50 again decimates coverage stops for the
same review rather than silently aligning a halved set.

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

- **Step 4 at Toth's 0.50 made alignment WORSE on our data, not better** — the
  opposite of the naive expectation. The T3 A/B (Empirical record below) shows
  the 0.50 cut aligned only 140/522 (26.8%), below even the smoke's no-filter
  39.7%, because disabling 46% of frames collapsed image-network overlap. The
  floor cut (< 0.30) aligned 515/522 (98.7%). So Step 4 is genuinely
  quality *hygiene* — remove the few unusable frames — and emphatically not an
  alignment booster at the published threshold on this dataset. The cause of
  the smoke's T8 loss remains a separate open question (overlap at transect
  ends, the two LZW-undecodable frames per ADR-0009, turbidity); this ADR does
  not attribute it.
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

## Empirical record — EDR_T3 quality-threshold A/B (2026-05-29)

Decided on our data, not from Toth's count (which we don't have). Artifacts:
`data/qc/chat5/q_ab_results.json` and `data/qc/chat5/q_ab_band_breakdown.json`
(probe: `scripts/metashape/probes/ab_quality_threshold.py`).

**Aggregate (same 522 frames, identical ESM-High alignment):**

| Arm | Disable < | Enabled | Aligned | % of 522 | Tie points |
|---|---|---|---|---|---|
| q050 (Toth verbatim) | 0.50 | 280 | 140 | 26.8% | 659,078 |
| q030 (floor) | 0.30 | 517 | **515** | **98.7%** | 2,441,346 |

**Band breakdown — the mechanism (stronger than the aggregate):**

| Quality band | q050 aligned | q030 aligned |
|---|---|---|
| < 0.30 (disabled both arms) | — (disabled) | — (disabled) |
| 0.30–0.50 (the band 0.50 discards) | 0 / 237 (disabled) | **235 / 237 = 99.2%** |
| ≥ 0.50 | **140 / 280 = 50.0%** | **280 / 280 = 100%** |

Two facts decide it:
1. **The discard band is fully usable.** The 0.30–0.50 frames that Toth's 0.50
   cut throws away register at **99.2%** in the floor arm — as well as the
   ≥0.50 frames.
2. **Including the band RESCUED the good frames (cross-arm, overlap collapse).**
   The *same* ≥0.50 frames aligned only **140/280 (50%)** when the band was
   disabled (q050) but **280/280 (100%)** when it was kept (q030). Removing 46%
   of frames didn't just lose those frames — it fragmented the image network so
   the "good" frames could no longer align. This is why 0.50 collapses to 26.8%.

**Decision: adopt the floor cut, disable < 0.30** (5 frames: the genuine low
tail, including the two degenerate ~0.0 frames `EDR_T3_R1_000130/000135`). The
non-transferability hypothesis is *consistent with* this evidence but still not
*confirmed* against Toth's own EDR_T3 registration count (deferred to Chat 6 /
P13HMEON backfill). The code keeps `image_quality_threshold = 0.50` as the
documented Toth-published value; the applied value is `--quality-threshold 0.30`
and is recorded in the manifest's `stage_step4.threshold`.

## What this ADR does NOT close

- **Confirming the non-transferability hypothesis against Toth's actual EDR_T3
  registered count** (needs the P13HMEON processing reports — not yet
  downloaded; Chat 6).
- Full attribution of the smoke's T8 alignment loss (multi-cause; separate work).
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
