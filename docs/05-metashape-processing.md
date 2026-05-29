# Metashape processing — EasternDryRocks (Layer 5)

This document records the SfM processing layer for `reef-sfm-mote-keys`: running
the three EasternDryRocks transects (EDR_T1, EDR_T3, EDR_T8) through Agisoft
Metashape Professional 2.x on the EC2 g6.4xlarge, following the Toth et al. 2025
published workflow.

This is Layer 5. Layer 4 (data acquisition + intake QC) is done; the validated
EDR imagery is on the data volume. Layer 6 (the provenance/QC/reconciliation
package) parses what this layer produces.

## The parameter-source change (read this first)

The original project plan and this chat's opener both cite the **NOAA PIFSC SOP**
(Torres-Pulliza et al. 2024) as the source of Metashape parameter values, framed
as a "parameter reference, not methodological basis." During Chat 4 we obtained
and read **Toth et al. 2025's Electronic Supplementary Material**, whose Table S2
is a complete, step-by-step Metashape workflow with specific parameter values —
for this exact dataset. **ADR-0010** records the decision to adopt ESM Table S2
as canonical, superseding PIFSC values wherever they conflict. This document
implements that decision; PIFSC is now background context only.

The reason this matters is not pedantry. Chat 6 reconciles this project's
structural-complexity metrics against the published P13HMEON values. That
comparison is only meaningful if the pipeline that produced our numbers matches
the pipeline that produced theirs. Using PIFSC values would yield a legitimate
reconstruction that is *not directly comparable* to the published results —
conflating pipeline difference with operator difference, which is precisely the
failure the longitudinal-comparability framing warns against.

### Toth (binding) vs PIFSC (superseded)

| Parameter | ESM Table S2 — used | PIFSC SOP — superseded | ESM step |
|---|---|---|---|
| Alignment accuracy | High | High (agree) | 5 |
| Generic preselection | Yes | Yes (agree) | 5 |
| Key point limit | **60,000** | 40,000 | 5 |
| Tie point limit | 0 | 0 (agree) | 5 |
| Exclude stationary tie points | **Yes** | not specified | 5 |
| Reconstruction Uncertainty | **20–40** (we use 30) | 10–15 | 8 |
| Projection Accuracy | **3–4** (we use 3.5) | 2–6 | 8 |
| Reprojection Error | **0.3 fixed** | 0.3–0.5 | 8 |
| Final optimize "fit additional" | Yes | yes (agree) | 8 |
| Dense cloud quality | **High** | Medium | 12 |
| Depth filtering | Mild | Mild (agree) | 12 |
| DSM resolution | **1 cm** | 1 mm | 14 |
| Orthomosaic blend | Mosaic + hole-fill | — | 15 |

Where the ESM gives a range, we use the midpoint and record it (RU 30, PA 3.5).
These midpoints are the one genuine operator choice inside the ESM envelope and
are called out as such in the writeup.

## What is automated vs what is manual

The chat opener asks for a clear split. Here it is, after the ADR-0010 changes.

### Automated (Python API, headless — `run_pipeline.py`)

| ESM step | Stage | Notes |
|---|---|---|
| 3 | Import, one chunk per transect | `Create chunk from each subfolder` |
| 5 | Match + align (High, 60k keypoints) | downscale 1 == High accuracy |
| 6 | Optimize cameras (bundle adjustment) | ESM "use defaults" |
| 7 | **Marker detection** (Circular 12-bit, tol 20) | detection only — see below |
| 8 | Error reduction (Logan, threshold mode) | the big automation win |
| 12 | Depth maps + dense cloud (High, Mild) | the long step (24–48 h) |
| 14 | DSM (1 cm) | from dense cloud |
| 15 | Orthomosaic (Mosaic, hole-fill) | from DSM |
| 16 | Export products + report | PLY / TIFF / JSON / PDF |
| 13 (part) | Confidence noise filter | `segment_pointcloud.py`, all transects |

### Manual (GUI via Amazon DCV)

| ESM step | Task | Why it can't be (fully) automated here |
|---|---|---|
| 7 | **Scale-bar assignment** | The API detects coded targets reliably, but pairing the right two markers and setting the 25 cm distance — and confirming the targets weren't mis-detected on reflective sand — is a judgement step. Detection runs first so you start from placed targets. |
| 13 | **Canopy / outplant / reef-base lasso** | Semantic 3D segmentation; no off-the-shelf model. One transect this chat (reference reproduction). |
| — | **Manual QA review** | Eyeball alignment gaps, doming, and marker residuals against the report before committing to the 24–48 h dense run. |

A note for the writeup's "what I learned" section: the original plan listed
"error reduction with Gradual Selection" as a manual GUI step. ADR-0010's
adoption of the Logan script moves it to automated. That is the single biggest
GUI-to-code shift in this layer and the clearest demonstration of the
reproducibility value the project is selling.

## Fidelity register — every ESM Table S2 step, classified

This is the table Francisco reviews to confirm the pipeline is faithful to Toth
et al. 2025 ESM Table S2 except where a departure is deliberate, defensible,
and documented. Each step is classified **Faithful** (reproduces the ESM as
written, headless), **GUI** (done by a human over Amazon DCV because it needs
judgement or has no scriptable equivalent), or **Departure** (a deliberate,
ADR-backed deviation). `run_pipeline.py` stage names are in the last column.
This register supersedes the looser automated/manual split above.

| ESM step | What Table S2 specifies | How we do it | Class | Ref / stage |
|---|---|---|---|---|
| 3 | One chunk per transect subfolder | `addPhotos`, one chunk per transect; `--transect` scopes a dev run to one | Faithful | `import` |
| 4 | Estimate image quality; disable blurred (< 0.5) | `analyzeImages` + disable `Image/Quality < 0.50` before matching | Faithful | `step4` / ADR-0017 |
| 5 | Align: High, 60k keypoints, generic preselection, exclude stationary | `matchPhotos(downscale=1, …)` with Toth's values | Faithful | `align` |
| 6 | Optimize cameras (defaults) | `optimizeCameras()` | Faithful | `align` |
| 7 | Detect coded targets; build 25 cm scale bars | **Detection** headless (`detectMarkers`, Circular 12-bit, tol 20); **scale-bar assignment** in GUI | Faithful (detect) + GUI (assign) | `reduce` + DCV |
| 8 | Gradual selection: RU 20–40, PA 3–4, RE 0.3, re-optimize | Logan script in threshold mode **preferred**; built-in faithful transcription is the fallback (currently used — Logan not yet vendored), logged as a per-run departure | Faithful (values) — see note | `reduce` / ADR-0010 |
| 9 | Color correction (Hatcher) — *optional* | **Skipped** (optional, visualization-only) | Departure (documented) | — / ADR-0010 |
| 10 | Dehaze — *optional* | **Skipped** (optional, visualization-only) | Departure (documented) | — |
| 11 | Jenkins Alignment Helper — local zero-point 1 m grid frame | GUI, over DCV (populates `chunk.transform.scale`) | GUI | DCV / ADR-0010 |
| 12 | Depth maps + dense cloud (High, Mild); resize region to AOI | `buildDepthMaps(downscale=2)` + `buildPointCloud`; region (10×1 m AOI) confirmed/set in GUI at handoff | Faithful | `dense` |
| 13 | Segment into 4 classes (noise/canopy/outplant/base), classify-and-keep via lasso | **Confidence noise filter only**, and **destructive** (`cleanPointCloud(Confidence,2)` + `compactPoints`) not classify-and-keep; 4-class split deferred to v2 | Departure (documented) | `filter` / ADR-0015 |
| 14 | Build DSM from dense cloud | `buildDem` at **1 cm**, no region-clip workaround (ADR-0016 test) | Faithful (1 cm; 1 mm was PIFSC) | `dsm` / ADR-0017 |
| 15 | Build orthomosaic (Mosaic, hole-fill) | `buildOrthomosaic(ElevationData, Mosaic, fill_holes)` | Faithful | `ortho` |
| 16 | Export products | sparse.ply, dense.ply, dsm.tif, ortho.tif, cameras.json, scalebars.json, processing_report.pdf + `pipeline_summary.json`. **No mesh** (ESM has no mesh step; the ortho surface is the DSM) | Faithful (scripted, vs USGS Export Helper) | `report` |

**Headless → GUI → headless split.** The `--stage` model expresses the split by
*which stages run*, not by extra CLI flags (ADR-0017 declined
`--chunk`/`--stop-after`/`--start-from` as redundant):

1. **Headless align portion:** `import` → `step4` → `align` → `reduce`
   (marker *detection* included). Surfaces Step 4 disabled count, alignment
   rate, RMS pre/post, and which error-reduction path ran.
2. **GUI handoff over DCV:** confirm marker detection; assign 25 cm scale bars
   (ESM Step 7); place the Jenkins zero-point coordinate frame (ESM Step 11,
   sets `transform.scale`); resize the region to the ~10×1 m area of interest
   (ESM Step 12); eyeball alignment QA; **File → Save** (not Save As).
3. **Headless dense portion:** `dense` → `filter` → `dsm` → `ortho` → `report`.
   `filter` (ESM Step 13) is sequenced strictly between `dense` and `dsm` so the
   DSM is never built on an unfiltered cloud (ADR-0015 + ADR-0017).

**Note on Step 8 fidelity vs Logan.** The *thresholds* (RU 30, PA 3.5, RE 0.3)
are faithful to Toth either way. ADR-0010 marks the Logan USGS script itself as
the preferred tool because using the exact cited tool is part of the
reproduction claim. As of this T3 dev run the Logan module is **not vendored on
the instance** (`import reduce_error` fails; no clone on disk), so `reduce` runs
the built-in transcription and records `reduction_path = "builtin_fallback"` in
the manifest. This is logged as a per-run documented departure, not silently
preferred. The earlier framing that "Logan lost the smoke A/B" was inaccurate:
the smoke A/B compared focal-length arms, not Logan vs built-in, and Logan was
never actually run because it was never present. Vendoring Logan (clone, verify
the `reduce_error` signature, expose on `PYTHONPATH`) is tracked below and is
the cleanest remaining fidelity upgrade for this layer.

## Logan error-reduction script — integration and verification

ADR-0010 marks the Logan automated alignment/error-reduction script
(DOI 10.5066/P9DGS5B9; Logan, Wernette & Ritchie 2022) as **REQUIRED** and lists
two open questions to resolve before Chat 5 execution. Both are resolved:

**Licensing — clear.** It is a USGS software release authored by USGS staff at
the Pacific Coastal and Marine Science Center. USGS-authored software is a U.S.
Government work and carries no copyright restriction on use or modification
(public domain in the United States). Safe to vendor into `vendor/` and import.
Confirm the bundled `DISCLAIMER`/`LICENSE` text on clone — USGS attaches a
standard liability disclaimer, but it imposes no usage restriction.

**Headless / Pro compatibility — confirmed.** The script drives the Metashape
Python API directly (gradual selection + `optimizeCameras`), which is exactly
the headless-capable surface. It runs the same three filters as ESM Step 8 —
Reconstruction Uncertainty, then Projection Accuracy, then iterative
Reprojection Error — with camera optimization between each and a final optimize
with "fit additional parameters" enabled. The Python API is Pro-only and the
trial exposes it. Runs via `metashape.sh -r` with no display.

**The one subtlety that changes how we call it.** The v2.0 script's *default*
behavior is **percentage-based** gradual selection: each filter deletes a fixed
fraction of points (default 50%), and Reprojection Error iterates down to an RMS
target. ESM Table S2 Step 8 instead specifies **fixed threshold values**
(RU 20–40, PA 3–4, RE 0.3). These are different control modes. The USGS
documentation explicitly notes the script can be driven in threshold mode
("run iteratively to delete points until the required filter level is met") via
command-line arguments or the `defaults` object. So we configure Logan in
**threshold mode with Toth's values** — not the percentage defaults. Running the
defaults would produce a legitimate but non-comparable reconstruction.

**Integration steps (run on the EC2 instance):**

```bash
# 1. Clone into the repo's vendor/ dir (the data volume, where the repo lives)
cd ~/code/reef-sfm-mote-keys/vendor
git clone https://code.usgs.gov/pcmsc/AgisoftAlignmentErrorReduction.git
# Use the v2.0 tag/branch, not the legacy_scripts/ versions.

# 2. Read the bundled README + DISCLAIMER. Confirm: (a) no usage restriction,
#    (b) the exact threshold-mode argument names and the reduce-error entry
#    point. The wrapper in run_pipeline.py calls `mod.reduce_error(chunk, ...)`
#    in threshold mode; reconcile that against the actual function signature and
#    adjust the thin wrapper if the names differ. This is the only place the
#    vendored code's real API needs to be matched by hand.

# 3. Make it importable in the project env:
cd ~/code/reef-sfm-mote-keys
uv add --editable ./vendor/AgisoftAlignmentErrorReduction   # if it's a package
# or expose the script dir on PYTHONPATH if it's a flat script.

# 4. Smoke-test threshold mode on the SMALLEST transect's sparse cloud BEFORE
#    committing to the full run. Confirm RU/PA/RE filters fire with Toth's
#    thresholds and the final optimize runs with fit-additional enabled.
```

Until the clone+verify lands, `run_pipeline.py` falls back to a **faithful
built-in transcription** of ESM Step 8 (`_run_builtin_reduction`) that applies
the same three filters at Toth's thresholds via the native API. This keeps the
pipeline runnable, but the Logan script is the ADR-0010-preferred path because
it is the exact tool the original team cites — using it is itself part of the
reproduction claim.

## Coordinate frame — Jenkins Alignment Helper

ADR-0010 marks the Jenkins & Kupfner Johnson Alignment Helper
(DOI 10.5066/P9YN4KDX) as REQUIRED *if* Chat 6 needs to compare against the
published DSMs in the same per-transect local frame ("zero-point center, 1 m
cell-size grid"). The longitudinal-comparability doc confirms Chat 6
reconciliation validity depends on it, so we treat it as required.

This step (ESM Step 11) is GUI-driven and best done over DCV after alignment and
before DSM build. Open question carried into execution (from ADR-0010): confirm
whether the published EDR DSMs in P13HMEON are actually in this local frame
before designing the Chat 6 comparison. If they are in a different CRS, document
why our frame differs rather than forcing a match. Pre-watch the tool's video
walkthrough (linked in its README) before the DCV session.

## Segmentation decision (ADR-0010 deferred this to Chat 5)

Decision for this chat: **scoped reproduction with one manual reference
transect.**

* **All three transects:** automated confidence-based noise filter (ESM Step 13
  Step 1), via `segment_pointcloud.py`. Deterministic, faithful, no judgement.
* **One transect (operator's choice):** full manual canopy/outplant/reef-base
  lasso in the GUI, reproducing ESM Fig. S4 end to end. This is the reference
  reproduction and the seed label set for any future learned segmentation.
* **The other two transects:** noise-filtered only; "with-everything"
  structural-complexity metrics in Chat 6. The class split is deferred to v2.

Consequence for Chat 6: the "with outplants vs without outplants" comparison
(Toth Fig. 3) is reproducible for the one manually-segmented transect only. For
the other two, reconciliation is against "with-everything" metrics. This is a
deliberate, documented partial reproduction, not an oversight.

Programmatic segmentation of the semantic classes (canopy/outplant/base) was
requested as a possible automation. It is genuinely a research-grade 3D semantic
segmentation problem with no off-the-shelf model for this domain, so it is
flagged as a v2 extension with a concrete technical approach (height +
verticality geometry first, learned sparse-conv model later) in the v2 roadmap
and sketched at the bottom of `segment_pointcloud.py`. The honest framing: this
chat produces the hand-labelled substrate such a model would need, not the model.

## Quality targets — observe, don't gate (deliverable #6)

`observe_quality.py` prints each transect's structural completeness and the ESM
envelopes side by side. It does **not** pass/fail-gate — that is Chat 6's QC
validator. The ESM-reported envelopes to eyeball the report PDF against:

* Reprojection error after error reduction: ESM reports **0.27–0.52 px** across
  transects (RMSE before reduction was 0.55–2.22; ~65% average decrease).
* Max horizontal accuracy: ESM reports **3.41 mm**. Note this is *looser* than
  the original-plan PIFSC-era target of ≤1 mm — i.e. the published method itself
  did not hit 1 mm, so reconciling against the PIFSC target would have been
  reconciling against a number the source paper never achieved. We observe
  against Toth's reported envelope and record the PIFSC number only for the log.
* Registered images: ESM-style expectation ≥90% of input cameras aligned.

## Smoke test — REQUIRED before the full run (gate)

The full dense run is 24–48 h. Failing at hour 23 is the worst outcome in the
project, so the full run is **gated** on `smoke_test.py` passing first. The smoke
test is deliberately slow and robust (real dense cloud, full short transect) —
it is cheap insurance against an expensive night. It exercises the two specific
risks carried forward from Chat 4b, not just generic plumbing.

**Risk 1 — LZW decoder edge case (ADR-0009).** Two files,
`20230711_EDR_T1_C2_000197.tif` and `_000218.tif`, fail PIL's LZW pixel decoder
(`decoder error -2`) although their EXIF reads cleanly. PIL's metadata reader is
more tolerant than its pixel decoder; the open question is whether *Metashape's*
decoder (different, usually more robust) chokes on the same files. The
`preflight` stage loads every subset image plus these two by name and forces a
pixel decode, failing loudly here rather than mid-run. If only the two known-bad
files fail, the decision is re-export-from-source vs exclude (2/3271 is
negligible for SfM coverage) — made before the run, not during it.

**Risk 2 — missing FocalLength (ADR-0009), the bigger one.** Photoshop stripped
the EXIF sub-IFD, so there is no `FocalLength` to seed Metashape's initial
intrinsics; it falls back to bundle-adjustment-derived focal length. The `ab`
stage runs the Chat 4b-prescribed A/B: align the subset twice — once with the
bundle-adjusted fallback, once with a manual S120 calibration — through error
reduction, then **decide programmatically** which arm the full run commits to.

This decision is an *artifact*, not a judgement call left to the operator. The
`ab` stage:

1. Computes reprojection RMS (px) for each arm **directly from the live
   tie-point residuals** via the Metashape API — not by parsing the exported
   report PDF. The PDF reports the same number, but reading it back means
   regex-ing a designed document whose layout drifts across Metashape versions,
   which is precisely the brittle report-coupling the longitudinal doc says the
   provenance layer exists to replace. Source data → number is robust; PDF →
   number is not. (The report PDF is still exported per arm as a human-readable
   cross-check; the pipeline just doesn't depend on parsing it.) Note: the RMS
   read from the filter is in Metashape's normalized internal filter units, NOT
   raw image pixels — see ADR-0012. It is valid for the A/B comparison (both
   arms measured the same way) but is NOT directly comparable to Toth's pixel-
   calibrated 0.27–0.52 px envelope. The pixel-calibrated number comes from the
   full-run report PDF after scale bars and coordinate frame are set, and is
   what Chat 6's reconciliation uses against the Toth envelope.
2. Writes `focal_decision.json` — a structured artifact recording each arm's RMS
   and alignment, the criterion applied (RMS primary, alignment tiebreak, with
   explicit margins), the verdict, the chosen arm, and a rationale string. This
   artifact *is* the justification for the choice, citable in the writeup.
3. Emits a verdict: **DECIDED** (a clear winner) or **NEEDS_REVIEW** (the two
   signals genuinely disagree — e.g. one arm has lower RMS but the other aligns
   materially more cameras; the validator refuses to trade quality against
   coverage on the operator's behalf).

`run_pipeline.py` then reads `focal_decision.json` at the start of its align
stage via `resolve_focal_mode()`:

* **DECIDED** → the full run seeds (or doesn't seed) S120 intrinsics
  automatically per the chosen arm. No human in the loop, no PDF read, no
  hand-edited config.
* **NEEDS_REVIEW or missing artifact** → the full run **refuses to start**
  unless the operator passes `--focal-mode {fallback,manual}` explicitly. The
  night only ever runs on a choice that was either validator-justified or
  consciously made. This guard fires *before* any compute, not 20 minutes in.

The decision criterion is unit-tested (`test_focal_decision.py`, 7 cases, runs
without Metashape) — clear-winner, RMS-tie-to-alignment, genuine-disagreement,
and failed-alignment paths all covered. This is the first concrete instance of
the "measure against a target, emit a structured verdict, feed it forward"
pattern that the Chat 6 provenance package generalizes.

A correction on the manual arm worth recording: the S120 lens is **5.2–26.0 mm
zoom** (5.2 mm is the wide stop), sensor 1/1.7" = 7.44 × 5.58 mm, so pixel pitch
≈ 1.86 µm. The manual arm seeds focal length *and* pixel pitch (Metashape needs
both to derive focal length in pixels). The 5.2 mm value assumes the divers shot
at the wide stop — if they zoomed, that assumption is wrong, and the A/B will
*show* it as worse alignment on the manual arm, which the decision logic then
accounts for. That is a useful finding for the writeup, not a failure.

**What the smoke test does NOT prove.** A subset that runs clean does not
guarantee the full set won't hit disk-full or GPU-OOM at full point count —
those scale with image count, not pipeline correctness. Before launching the
night: check free space on `/data` and `nvidia-smi` memory headroom. The smoke
test validates correctness; those two checks validate capacity.

```bash
# GATE: must pass before the full run. Robust mode, real dense on a full transect.
metashape.sh -r scripts/metashape/smoke_test.py \
    --image-root /data/edr/images --transect EDR_T8 \
    --smoke-project /data/edr/smoke/smoke.psx \
    --out-root /data/edr/smoke/products --stage all
# Read the A/B recommendation, confirm against the report PDFs, then set the
# focal-length arm in run_pipeline.py's config for the full run accordingly.
```

## Running it (the `--stage` model, post-ADR-0017)

Stages are `import, step4, align, reduce, dense, filter, dsm, ortho, report`.
The actual data layout: repo on the data volume at `/data/reef-sfm-mote-keys`;
images flat at `/data/raw/P1WHKTRD/EasternDryRocks`; Metashape working area
`/data/edr_work`; monitor + run logs `/data/edr_work/logs`. Run headless under
`metashape.sh -platform offscreen -r`, inside tmux so it survives SSH drops.

```bash
PROJECT=/data/edr_work/edr_t3.psx
IMGROOT=/data/raw/P1WHKTRD/EasternDryRocks
META="/opt/metashape-pro/metashape.sh -platform offscreen -r scripts/metashape/run_pipeline.py"

# --- Headless align portion (EDR_T3 dev run; --transect scopes the import) ---
$META --project $PROJECT --image-root $IMGROOT --transect EDR_T3 --stage import
$META --project $PROJECT --stage step4
$META --project $PROJECT --stage align  --focal-mode fallback   # smoke decided 'fallback'
$META --project $PROJECT --stage reduce

# --- GUI handoff over DCV (ESM Steps 7/11/12) ---
#   confirm marker detection; assign 25 cm scale bars; Jenkins coord frame
#   (sets transform.scale); resize region to the ~10x1 m AOI; QA; File→Save.

# --- Headless dense portion ---
$META --project $PROJECT --stage dense
$META --project $PROJECT --stage filter     # ESM Step 13, BEFORE dsm
$META --project $PROJECT --stage dsm         # 1 cm, no region workaround (ADR-0016 test)
$META --project $PROJECT --stage ortho
$META --project $PROJECT --stage report      # writes /data/edr_work/products/.../pipeline_summary.json
```

Notes:
- `--focal-mode fallback` is passed explicitly because `focal_decision.json`
  was not committed (regenerable from `smoke_test.py --stage ab`); the smoke
  verdict was `fallback` (both arms aligned identically, prefer no-assumption).
- Critical sanity alarms (Step 4 disabling > 200/522; alignment < 70% of
  enabled; DSM 0 or > 1e8 cells; unscaled chunk at dense) **hard-stop** the run.
  Pass `--ignore-sanity` to downgrade to warn — not recommended for a dev run.
- `--logan-module reduce_error` once Logan is vendored (see above); until then
  the built-in transcription runs and is recorded as `builtin_fallback`.

## Per-run observations — T3 dress rehearsal (2026-05-29)

Recorded as the run progresses; the authoritative machine-readable record is
`/data/edr_work/products/EDR_T3/pipeline_summary.json`.

- **Trial clock:** activated 2026-05-27, expires 2026-06-27 (~29 days at run
  time). Metashape 2.3.1 build 22446.
- **Input:** 522 EDR_T3 C1 frames, SHA-256-pinned at import.
- **ESM Step 4:** _(headless align portion — filled after the run)_
- **Alignment:** _(aligned / enabled, %, RMS filter units)_
- **Error reduction:** _(path: Logan vs builtin_fallback; RMS pre→post)_
- **Confidence filter (Step 13):** _(points before→after, % removed; smoke
  EDR_T8 reference was 30.9M→23.5M, ~24%)_
- **buildDem / ADR-0016:** _(succeeded without region clip? raster dims;
  transform.scale; peak RAM)_
- **Resource peaks:** _(GPU VRAM, RAM, CPU, wall clock per stage — from
  scripts/monitor.sh summary)_

## Trial-clock discipline

The dense reconstruction is the irreversible compute investment and the longest
pole. At ESM "High" quality it is materially slower than the PIFSC "Medium" the
original plan assumed — budget 24–48 h per the ADR, not 6–15 h. Start it first
among the long steps. If it overruns the trial window, the rest of the pipeline
is blocked, so protect that window: do alignment, marker/scale-bar setup, and
the coordinate-frame placement in the early sessions, then hand the dense run the
longest uninterrupted stretch you have. Snapshot the data volume after the dense
stage completes (recovery point) and again after export.
