# Architecture Decision Records

This directory holds the Architecture Decision Records (ADRs) for the
reef-sfm-mote-keys project, using Michael Nygard's template (Context,
Decision, Consequences) — light enough to actually keep up to date, with
enough structure to be useful two months later.

## Why we keep these

When a future reviewer (or future me) asks "why did you use raw requests
instead of sciencebasepy?" the answer should not require archaeology
through commit logs or chat transcripts.  It should be `grep -l
sciencebasepy docs/adr/` → one file → 30-second read.

## Conventions

- **One ADR per real decision.**  If we changed our minds, write a new
  ADR with status `Supersedes ADR-NNNN` and update the old one's status to
  `Superseded by ADR-NNNN`.  Don't rewrite history.
- **Filename: `NNNN-kebab-title.md`.**  Zero-padded sequence number so `ls`
  sorts chronologically.  Title summarizes the *decision*, not the topic.
- **Every ADR has Status, Date, Context, Decision, Consequences.**  The
  Consequences section is mandatory: if you can't think of a downside,
  the decision probably wasn't a real choice.
- **Tag footer.**  Last line is `#tags: word1, word2, word3` so
  `grep -l '#tags:.*exif' docs/adr/` finds everything about EXIF.

## Grep recipes

```bash
# All ADRs touching EXIF
grep -lr '#tags:.*exif' docs/adr/

# All currently superseded ADRs
grep -lr '^Status:.*Superseded' docs/adr/

# All ADRs added in Chat 4
grep -lr '^Chat: 4' docs/adr/

# What was decided about ScienceBase?
grep -lri sciencebase docs/adr/
```

## Current index

| # | Title | Status | Chat |
|---|---|---|---|
| [0001](0001-provenance-package-as-installable-module.md) | Provenance code is an installable package, not notebook cells | Accepted | 4 |
| [0002](0002-no-sciencebasepy-dependency.md) | Talk to ScienceBase via raw `requests`, not `sciencebasepy` | Accepted | 4 |
| [0003](0003-sciencebase-api-primary-manifest-csv-fallback.md) | ScienceBase REST is the primary acquisition path; manifest CSV is the fallback | Accepted | 4 |
| [0004](0004-validation-constants-from-metadata-file.md) | Validation constants come from the metadata file, not the papers | Accepted | 4 |
| [0005](0005-four-level-severity-with-unverified.md) | Four severity levels (`ok` / `warn` / `fail` / `unverified`) | Accepted | 4 |
| [0006](0006-exiftool-optional-batched-subprocess.md) | exiftool is an optional batched subprocess, not a hard dep | Accepted | 4 |
| [0007](0007-gps-rule-expects-single-surface-fix.md) | GPS rule expects exactly one surface-station fix per site | Accepted | 4 |
| [0008](0008-ids-viewer-csv-export-primary-acquisition-path.md) | IDS viewer CSV export is the primary acquisition path | Accepted | 4 |
| [0009](0009-exif-csv-and-tiff-encoding-metadata-loss.md) | USGS TIFFs are Photoshop CR2→TIFF re-encodes; capture-time EXIF absent; CSV canonical for surviving metadata | Accepted | 4 |
| [0010](0010-adopt-toth-usgs-metashape-workflow.md) | Adopt Toth et al. 2025 ESM Table S2 as Chat 5 parameter source; PIFSC SOP superseded | Accepted | 4 |
| [0011](0011-validator-hardcoded-now-profile-driven-later.md) | Validator is intentionally EDR-hardcoded in Chat 4; profile-driven generalization deferred to Chat 6 | Accepted | 4 |
| [0012](0012-smoke-ab-rms-in-filter-units-not-pixels.md) | Smoke A/B reprojection RMS is in Metashape filter units, not image pixels | Accepted | 5 |
| [0013](0013-confidence-noise-filter-via-cleanpointcloud.md) | ESM Step 13 confidence filter implemented via Chunk.cleanPointCloud (remove); GUI's classify-and-keep has no Python equivalent in 2.x | Superseded by 0015 | 5 |
| [0014](0014-headless-confidence-filter-via-docpopi-pattern.md) | Headless confidence noise filter uses setConfidenceFilter + cropSelectedPoints (DocPopi pattern); cleanPointCloud is documented-but-non-functional on 2.3.1 build 22446 | Superseded by 0015 | 5 |
| [0015](0015-headless-step13-engineered-departure.md) | Headless ESM Step 13: engineered destructive departure (cleanPointCloud + compactPoints); supersedes 0013 and 0014; reframes choice as departure not reproduction | Accepted | 5 |
| [0016](0016-builddem-extent-beyond-pcextent-smoke-bbox-clip.md) | buildDem extent inference on unscaled chunks: BBox region clip insufficient; full headless smoke of DSM/ortho deferred to scaled production runs (T3 dress rehearsal or v2) | Accepted with caveat (production prediction superseded by 0018) | 5 |
| [0017](0017-esm-step-4-image-quality-and-production-wiring.md) | Wire ESM Step 4 image-quality filter before alignment; wire ADR-0015's confidence filter into the production driver (filter stage between dense and dsm); extend `--stage` rather than add CLI flags; DSM confirmed 1 cm (1 mm was a PIFSC misattribution) | Accepted (reduction-path consequence superseded by 0023) | 5 |
| [0018](0018-builddem-region-clamp-and-dense-aoi-crop.md) | buildDem/buildOrthomosaic OOM caused by a spurious WGS84 CRS on a local no-GPS chunk (degrees/meters mis-scale → ~38,800 km grid); build DSM/ortho with an explicit LOCAL PLANAR projection clamped to the 10×1 m AOI (Toth ESM Step 11/14/15 faithful). Outlier diagnosis + dense crop falsified and removed. Resolves 0016's coordinate-space question. **Final: precise cause = unset `OrthoProjection.crs` → `chunk.crs` WGS84 backfill; per-build fix withdrawn as unverifiable; build moved to GUI (ADR-0019)** | Accepted (API-mechanism record; fix superseded by 0019) | 5 |
| [0019](0019-dem-ortho-build-in-metashape-gui.md) | DEM + Orthomosaic build (ESM Steps 14–15) moved to the Metashape GUI over DCV; rest of pipeline stays headless. GUI handles the local-frame projection transparently → matches Toth ESM Table S2 more faithfully than the self-imposed headless port | Superseded by 0020 | 5 |
| [0020](0020-dem-ortho-headless-via-local-crs-planar.md) | DEM + Orthomosaic (ESM Steps 14–15) run HEADLESS again: the lever is `chunk.crs` → LOCAL_CS (metre), which kills the spurious-WGS84 degree-plane backfill that OOM'd buildDem; identity Planar projection + pre-flight cell tripwire. Supersedes the GUI decision (0019) | Accepted | 5 |
| [0021](0021-headless-stage-level-and-stage-aoi-with-permanent-gate.md) | Headless `stage_level` (ESM Step 11 marker-plane roll+pitch, scale-bar MAD outlier rejection, before dense) + `stage_aoi` (ESM Step 14 footprint-PCA yaw/centroid + camera-track orientation anchor + 10×1×5 m crop, after filter), split by input/phase; permanent 8-check QC gate (tilt/coverage/scale/co-reg/footprint/orientation, +additive reference) that hard-fails a 24° mis-level or a sign-flipped product. Codifies the validated Phase-A re-level; divergence ledger | Accepted | 5 |
| [0022](0022-headless-marker-layer-validation-gate.md) | Headless marker-layer validation gate in `stage_markers` — (a) consecutive-ID parity/orphans, (b) loose post-align reprojection-coherence tripwire (no in-gate optimize), (c) scale-free inter-bar length ratio — calibrated on T3 (PASS) with margin; on FAIL it escalates (structured report + awaiting-manual provenance) BEFORE scale and re-enters after a GUI fix (validates EXISTING markers, no re-detect); dumb `stage_scale` applies the validated set. Falsified the brief's count/residual heuristic → coherence; T1 escalates as the correct outcome. Divergence ledger | Accepted | 5 |
| [0023](0023-vendored-logan-reduce-and-network-health-collapse-guard.md) | Retire the home-grown ESM Step-8 transcription (`_run_builtin_reduction`) — its one-shot hard cut collapsed EDR_T1 on 2026-06-08 (100 % of tie points removed → 86/2422 cameras; scale/level then "succeeded" on the wreckage off stale align meta). Run Step 8 via the **vendored USGS Logan v2.0** capped-iterative routine (DOI 10.5066/P9DGS5B9, import-by-path, no silent fallback). Add a network-health **collapse tripwire** — camera-survival + coarse scale-bar sanity + near-zero tie-point floor — wired 3a (within-reduce per-pass backstop), 3b (success-tied post-condition), 3c (live pre-condition on scale/reduce/level/dense), plus a `stage_level` 50 m marker-extent sanity and scale-bar accuracy 0.001 m weighting. Supersedes ADR-0017's reduction-path consequence (scoped). Divergence ledger: tiepoint_covariance no longer force-set in reduce | Accepted | 5 |
| [0024](0024-local-crs-in-stage-scale-kills-wgs84-optimize-divergence.md) | `stage_scale` sets LOCAL_CS + disables garbage marker/camera reference locations before saving — the fix for optimizeCameras divergence (scale 1.0→823, reproj 0.15→1.3e152) in the Logan reduce path. Root: spurious WGS84 CRS + identity transform → `updateTransform` auto-wrote garbage GCP locations (lat≈-90°, alt≈-6.36e6 m) to all 8 markers with enabled=True. Scale-bar over-constraint hypothesis falsified. Uses same LOCAL_CS WKT as ADR-0020 (one constant). 10 pure-pytest contract tests | Accepted | 6 |
| [0025](0025-camera-nadir-leveling.md) | Camera-nadir UP in `stage_level`; marker plane for heading only — collinear T1 marker layout makes the plane normal ill-defined for roll | Accepted | 5 |
| [0026](0026-t1-aoi-transect-placement.md) | T1 AOI: 10×1 m manual transect placement for an area survey | Superseded by ADR-0028 (Z window) | 5 |
| [0027](0027-t1-dsm-resolution-1cm.md) | T1 DSM resolution: 1 cm | Accepted | 5 |
| [0028](0028-z-window-correction.md) | Corrected T1 AOI Z window [−9.2, +1.8] m, surface-median-anchored — first DSM run falsified ADR-0026's uniform-gradient estimate (surface is trough-to-crest: shoulder ~−2.1 / trough ~−5.2 / crest ~−0.7 m); coverage 16.3% → 97.1%, DSM extent 2.58 m → 10.00 m; supersedes 0026's Z window only | Accepted | 5 |
| [0029](0029-pointcloud-direct-fullarea-ortho.md) | Full-area ortho built PointCloudData-direct — `buildDem` hangs on the 487M-pt cloud in Metashape 2.3.1 (3 confirmed runs); product is portfolio visual only, explicitly NOT ESM Step 15; the transect ortho stays DEM-sourced/compliant | Accepted | 5 |
| [0030](0030-reconciliation-metric-scope.md) | Reconciliation metric scope: pure-Python tier (rugosity, standardized elevation, VRM) TDD'd against analytic fixtures; SAPA/RIE/ASD are explicit MultiscaleDTM stubs, never approximated; all DSMs block-mean resampled to 1 cm (Toth's resolution) before computing; no fractal dimension (plan-prompt guess, not in Toth Fig. S5); P13HMEON untouched in this branch | Accepted | 6 |
| [0031](0031-qc-gate-provenance.md) | QC gates bind to Toth Table S2 (ADR-0010), NOT PIFSC SOP (key-point 60,000 vs 40,000; RU 20–40 vs ≤15); conformance-vs-outcome split, both always evaluated; reconstruction uncertainty is a conformance check on the APPLIED threshold, never an outcome gate; scale-bar threshold parameterized pending residual calibration; not-evaluable ≠ pass | Accepted | 6 |
| [0032](0032-reconciliation-harness.md) | Reconciliation harness + confirmed P13HMEON contract (full_area_rugosity↔rugosity, stand_mean_elev↔mean-elev, vrm_mean↔VRM; `confidence` filter = our ADR-0015). Function validation: rugosity/elevation reproduce MultiscaleDTM to <0.3%, VRM consistently +14% (implementation). Finding: published EDR_T1 is a 9-transect subsite; our area-survey centre-cut (5.5 m relief vs ≤1.4 m) matches none 1:1 — envelope diagnostic only (VRM inside pop, rugosity/elev outside by scale). True 1:1 scoped as Option-2 re-process (imagery separable, ~230–283 img/transect) | Accepted | 6 |
| [0034](0034-frame-retention-qc-criterion.md) | `frame_retention` outcome criterion in `QCValidator`: observed = 1 − (disabled/analyzed), pass if ≥ 0.60 (constructor param). Closes the corpus-blind `ALARM_MAX_DISABLED=200` gap — R2's 51.5% disable rate (140/272) never tripped the absolute alarm. Threshold anchored to ADR-0017 T3 A/B: 0.30-floor retained 99% / 0.50-Toth retained 46–48%. `OutcomeBlock` gains `step4_images_analyzed` + `step4_images_disabled`. | Accepted | 7 |
