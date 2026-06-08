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
| 7 | **Marker detection** (Circular 12-bit, auto-tolerance by ID) | detection only — see below |
| 8 | Error reduction (Logan, threshold mode) | the big automation win |
| 11 | **Level** (marker-plane roll+pitch) | `stage_level`, ADR-0021 — was a GUI step |
| 12 | Depth maps + dense cloud (High, Mild) | the long step (24–48 h) |
| 13 (part) | Confidence noise filter | `segment_pointcloud.py`, all transects |
| 14 | **AOI framing** (footprint-PCA + crop) + DSM (1 cm) | `stage_aoi` + `dsm`, ADR-0021 — bbox was a GUI step |
| 15 | Orthomosaic (Mosaic, hole-fill) | from DSM, co-registered |
| QC | **Permanent 8-check gate** | `stage_gate`, ADR-0021 — fails a 24° mis-level/sign-flip |
| 16 | Export products + report | PLY / TIFF / JSON / PDF |

### Manual (GUI via Amazon DCV) — now a single touch

| ESM step | Task | Why it can't be (fully) automated here |
|---|---|---|
| 7 | **Scale-bar assignment** | The API detects coded targets reliably (auto-tolerance by identity), but pairing the right two markers and setting the 25 cm distance — and confirming the targets weren't mis-detected on reflective sand — is a judgement step. Detection runs first so you start from placed targets. The **only** remaining GUI touch (the Step-11 coordinate frame + region resize are now headless: `level` + `aoi`, ADR-0021). |
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
| 7 | Detect coded targets; build 25 cm scale bars | **Detection** headless (`detectMarkers`, Circular 12-bit, AUTO-TOLERANCE by identity) **+ a headless validation gate** (ADR-0022): (a) consecutive-ID parity/orphans, (b) loose post-align reprojection-coherence tripwire, (c) scale-free inter-bar length ratio. PASS → dumb **`stage_scale`** builds the 25 cm bars headless; FAIL → escalate (structured report) + GUI fix + re-validate. GUI scale-bar assignment is now the *escalation* path, not the default | Faithful (detect) + headless gate/apply; GUI only on escalation | `markers` + `scale` / ADR-0022, ADR-0021 |
| 8 | Gradual selection: RU 20–40, PA 3–4, RE 0.3, re-optimize | **Vendored USGS Logan v2.0** (`Align_RuPaRe`, DOI 10.5066/P9DGS5B9) in threshold mode at Toth's values, **capped-iterative** (per-pass cutoff 0.5/0.5/0.1, optimize between, final fit-additional). The home-grown one-shot transcription is **retired** (it collapsed T1 — ADR-0023); **no silent fallback** (a bad vendored load HALTS). Runs AFTER scale bars exist (see Corrected step order) | Faithful (values + the published tool) | `reduce` / ADR-0010, ADR-0023 |
| 9 | Color correction (Hatcher) — *optional* | **Skipped** (optional, visualization-only) | Departure (documented) | — / ADR-0010 |
| 10 | Dehaze — *optional* | **Skipped** (optional, visualization-only) | Departure (documented) | — |
| 11 | Jenkins Alignment Helper — local zero-point 1 m grid frame | **`stage_level`** (ADR-0021): deterministic marker-PLANE roll+pitch, headless — robust LS plane to the vetted scale-bar markers (scale-bar-residual MAD outlier rejection), normal→+Z, scale preserved. Runs BEFORE dense (ESM 11<12). Replaces the GUI helper whose 2-marker-midline roll-blindness caused the day-1 24.26° defect. Scale comes from the scale-bar-constrained `reduce`, not a separate frame | Departure (documented) | `level` / ADR-0021 |
| 12 | Depth maps + dense cloud (High, Mild); resize region to AOI | `buildDepthMaps(downscale=2)` + `buildPointCloud`; **the 10×1 m AOI is set headless by `stage_aoi`, not the GUI** (see Step 14) | Faithful | `dense` (+ `aoi`) |
| 13 | Segment into 4 classes (noise/canopy/outplant/base), classify-and-keep via lasso | **Confidence noise filter only**, and **destructive** (`cleanPointCloud(Confidence,2)` + `compactPoints`) not classify-and-keep; 4-class split deferred to v2 | Departure (documented) | `filter` / ADR-0015 |
| 14 | Build DSM from dense cloud (10×1 bounding box) | **`stage_aoi`** (ADR-0021): footprint-PCA yaw (baked into `chunk.transform`) + camera-track +X anchor + footprint-centroid centre + 10×1×5 m crop, AFTER `filter`; then `buildDem` at **1 cm** (ADR-0020 local-planar, no region-clip workaround) | Faithful (1 cm; 1 mm was PIFSC) | `aoi` + `dsm` / ADR-0021, ADR-0017 |
| 15 | Build orthomosaic (Mosaic, hole-fill) | `buildOrthomosaic(ElevationData, Mosaic, fill_holes)`, same local-planar projection as the DSM (co-registers dx=dy=0) | Faithful | `ortho` |
| QC | *(no ESM analog)* | **Permanent 8-check gate** (`stage_gate`, ADR-0021): long-axis flat ≤0.5°, total tilt ≤6.0°, coverage ≥95%, scale/extent, DEM/ortho co-reg=0, footprint evr≥0.95 & aspect≥5, **+X orientation sign-flip guard**; +additive reference check 8. FAILs the build so a 24° mis-level or a reversed product cannot ship | Departure (added safeguard) | `gate` / ADR-0021 |
| 16 | Export products | sparse.ply, dense.ply, dsm.tif, ortho.tif, cameras.json, scalebars.json, processing_report.pdf + `pipeline_summary.json`. **No mesh** (ESM has no mesh step; the ortho surface is the DSM) | Faithful (scripted, vs USGS Export Helper) | `report` |

**Headless → GUI → headless split — the GUI touch is now CONDITIONAL.** ADR-0021
codified ESM Step 11 (orientation) and the Step-14 AOI bounding box as the
headless `level` and `aoi` stages (eliminating the Jenkins-frame GUI touch).
ADR-0022 then made scale-bar assignment headless on the common path: `markers`
detects *and validates* the layer (gates a/b/c) and, on PASS, the dumb `scale`
stage builds the 25 cm bars — **no GUI**. The GUI is entered **only when
validation escalates** (an unpairable or incoherent layer). The full order is
`align → markers → {escalate? → [GUI: fix markers] → markers} → scale → reduce →
level → dense → filter → aoi → dsm → ortho → gate → report`:

1. **Headless align portion:** `import` → `step4` → `align` → `markers`
   (ESM Step 7 *detect + validate*). Surfaces Step 4 disabled count, alignment
   rate, RMS, the detected-marker IDs, and the three gate verdicts.
2. **On PASS (no GUI):** `markers` emits a validated scale-bar set
   (`validated_scalebars.json`) and `scale` applies it headless (25 cm bars).
3. **On FAIL (conditional GUI touch):** `markers` writes a structured escalation
   report (`markers_escalation.json`: every gate finding + count/coherence
   evidence + which images each suspect marker spans) and halts BEFORE scale. The
   human fixes markers/scale bars in the GUI (DCV), **File → Save**, and re-runs
   `--stage markers` — which validates the **EXISTING** corrected set (no
   re-detect) and, on PASS, lets `scale` proceed.
4. **Headless remainder:** `reduce` (ESM Step 8, scale-constrained) → `level`
   (ESM Step 11, marker-plane roll+pitch) → `dense` → `filter` (ESM Step 13,
   strictly between dense and the DSM) → `aoi` (ESM Step 14 bbox, footprint-PCA)
   → `dsm` → `ortho` → `gate` (the permanent QC gate) → `report`.

**Why this order.** Toth's ESM runs Step 7 (scale bars) before Step 8 (error
reduction), so the final `optimizeCameras` inside reduce is scale-constrained —
the `reduce` stage fires a critical alarm if it runs with zero scale bars. The
metric scale therefore comes from the scale-bar-constrained `reduce`, which is
why no separate Jenkins "scale" frame is needed: `level` only sets orientation
(roll+pitch, scale preserved) and `aoi` only sets the datum/centre — both run
*after* `reduce`, pinned to the final post-reduce geometry. `level` runs before
`dense` (ESM 11<12); `aoi` runs after `filter` so the footprint PCA sees the
denoised cloud (ESM 14, after 13).

**Note on Step 8 fidelity vs Logan.** The *thresholds* (RU 30, PA 3.5, RE 0.3)
are faithful to Toth either way. ADR-0010 marks the Logan USGS script itself as
the preferred tool because using the exact cited tool is part of the
reproduction claim. **As of 2026-06-08 Logan is vendored** (USGS PCMSC
`Align_RuPaRe` v2.0, DOI 10.5066/P9DGS5B9, at
`scripts/metashape/vendor/logan_usgs/`) and is the `reduce` path; `esm.reduce`
records `reduction_path = "logan_vendored:Align_RuPaRe_v2_Metashape.py"`. The
home-grown built-in transcription (`_run_builtin_reduction`) is **retired** — it
applied Toth's thresholds as **one-shot hard cuts** and on 2026-06-08 removed
**100 % of EDR_T1's tie points** (10.67 M → 0 → 86/2422 cameras); the published
Logan routine is **capped-iterative** (bounded deletion per pass + optimize
between), which is the structural fix. There is **no fallback path** any more: a
missing/broken vendored module HALTS loudly (`reduce` can never silently skip
error reduction). The earlier framing that "Logan lost the smoke A/B" was
inaccurate: the smoke A/B compared focal-length arms, not Logan vs built-in. See
ADR-0023 for the full reversal + the network-health collapse guard.

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

**As vendored (2026-06-08) — DONE (commit-pinned 2.0.x port).** The v2.0 *workflow*
is pinned verbatim under `scripts/metashape/vendor/logan_usgs/`
(`Align_RuPaRe_v2_Metashape.py` + LICENSE / DISCLAIMER / Readme / CHANGELOG /
code.json / `PROVENANCE.md`), at USGS commit **`aaee35f5`** (J. Logan, 2024-03-20),
module sha256 `69b0972628…`. The `legacy_scripts/` 1.4–1.8 variants are **not**
vendored. Third-party, byte-for-byte; **do not edit** — all EDR orchestration lives
in `run_pipeline.py`. Re-pin via the commit ref + hashes in `PROVENANCE.md` + ADR-0023.

> **The provenance version cross-check earned its keep.** The first vendoring
> (`3ec2789`) pinned the DOI-cited **v2.0 *tag*** (archive `f124418878…`, module
> `baaa3c91…`) — which targets Metashape **1.6–1.8** and uses `chunk.point_cloud`, so
> it crashed on our 2.3.1 at the first live reduce. The 2.0.x port (same v2.0
> algorithm; only `point_cloud`→`tie_points` + the header differ — verified by a
> 2-line normalized diff) lives on USGS `master`, untagged. We re-pinned to commit
> `aaee35f5`. A load-time identity check (`_assert_vendored_logan_identity`) now
> verifies the file declares Metashape 2.0.x + uses `tie_points`, so a future mislabel
> is caught at vendor/load time, not during a live run. **Version-gap caveat:** file
> targets 2.0.x, we run 2.3.1 → covered by the real-chunk integration smoke.

- **Import by file path** — `_vendored_logan_module()` loads it via
  `importlib.util.spec_from_file_location` (no `sys.path` mutation). The module is
  import-safe (every statement under a `def`/`class` or the `__main__` guard), so
  importing needs only `import Metashape` to resolve (true under `metashape.sh`).
- **The wrapper** `_run_logan_reduction` calls the routine's three real functions
  — `reconstruction_uncertainty(chunk, 30, 0.50, …)` →
  `projection_accuracy(chunk, 3.5, 0.50, …)` →
  `reprojection_error(chunk, 0.3, 0.10, …, final fit_additional_corr=True)`,
  `compute_rmse=True` — in threshold mode at Toth's values with the script's
  capped per-pass cutoffs. RU/PA run-once; RE iterates to the RMSE target. (Logan
  appends `_Ru/_Pa/_Re` to the chunk label; the wrapper restores the original.)
- **`--logan-module <name>`** still overrides the vendored copy with an importable
  module name (kept for testing / a future re-pin); default is the vendored file.

**The built-in transcription (`_run_builtin_reduction`) is removed.** There is no
fallback: if the vendored module is missing or fails to import, `reduce` HALTS
loudly rather than silently skipping error reduction or running a different
algorithm. This is the ADR-0023 reversal of ADR-0017's interim "built-in is the
only path" stopgap (which is what collapsed EDR_T1).

## Network-health collapse guard + scale-bar weighting (ADR-0023)

Born from the 2026-06-08 EDR_T1 reduce collapse: the home-grown one-shot reduction
removed 100 % of tie points (→ 86/2422 cameras) and `scale`/`level` then "succeeded"
on the wreckage because they read **stale `esm.align` meta**, not the live network.
Two fixes ship alongside the vendored-Logan reduce.

**Scale-bar accuracy weighting.** `stage_scale` now sets
`sb.reference.accuracy = scalebar_accuracy_m` (`PARAMS.scalebar_accuracy_m`,
default **0.001 m**; `--scalebar-accuracy-m`) on **every** bar — both the ones it
creates and any the human created in the GUI on the re-entry path, which arrived
with `accuracy = None` (active-but-**unweighted**). Weighting makes the 0.25 m bars
real constraints in the Logan final optimize, so the reference distance actually
pulls the metric scale. Recorded in `esm.scale.scalebar_accuracy_m`.

**Collapse tripwire (HARD guard, NOT the fine QC gate).** A coarse, reference-free
check wired at three points: **3a** a within-reduce per-pass backstop (a single
run-once RU/PA filter dropping more than its cutoff is anomalous → HALT before the
next pass/save), **3b** a success-tied post-reduce condition (vs the pre-reduce
aligned count, before `esm.reduce` is written), and **3c** a live pre-condition at
the entry of `scale`/`reduce`/`level`/`dense` (reads the **live** aligned count — the
fix for the stale-meta bug). `--ignore-sanity` downgrades the HALT to a warning but
**still writes** `network_health_escalation.json`.

| Constant (CLI flag) | Default | What it catches | Recalibration rule (transect-agnostic) |
|---|---|---|---|
| `HEALTH_MIN_ALIGNED_FRAC` (`--health-min-aligned-frac`) | 0.90 | Cameras de-aligning during reduce (PRIMARY). Floor = frac × baseline (pre-stage aligned for 3b, live enabled for 3c) | A *fraction of the run's own baseline*, not an absolute count — already program-independent. Lower only if a transect's clean reduce is shown to legitimately drop alignment (it should not); never raise to make a bad run pass. |
| `HEALTH_MIN_TIEPOINTS` (`--health-min-tiepoints`) | 1000 | Near-total tie-point removal (the collapse left 0) | A **near-zero tripwire, NOT a fraction** — a healthy Logan reduce sheds a large share, so a fractional floor false-fires. Keep it orders of magnitude below any plausible healthy post-reduce count (millions); it only needs to separate "≈0" from "millions". |
| `HEALTH_SCALEBAR_MAX_RATIO` (`--health-scalebar-max-ratio`) | 2.0 | Metric scale blown to km (`max(meas/def, inverse) > ratio`) | **Coarse within-N×**, deliberately loose so it never doubles as the fine scale gate (`stage_gate`). Independent of bar length (it is a *ratio* to each bar's own defined distance). Leave at 2.0 unless a program's geometry genuinely produces >2× honest scale error pre-gate. |
| `HEALTH_MAX_PASS_DROP_FRAC` (`--reduce-max-pass-drop-frac`) | 0.50 | A single gradual-selection pass taking too much (3a). Logan's RU/PA cutoff is 0.5, so a healthy pass never trips it | Pin to Logan's run-once cutoff: set ≥ the largest cutoff you pass to a *run-once* (non-iterating) filter. Applies to RU/PA only; RE iterates and is covered by 3b, not this. |
| `LEVEL_MAX_EXTENT_M` (`--level-max-extent-m`) | 50.0 | A collapsed model spreading markers over km (`stage_level` extent sanity) | Set to a few × the real transect extent (EDR ≈10 m → 50 m headroom). It only needs to separate "~10 m" from "thousands of km"; scale to the deployment's transect length, not tuned tight. |

All five are coarse collapse discriminators with wide margin — they separate a
*collapse* (0 tie points / 86 cameras / km bars) from a *healthy* reduce (millions of
tie points shed, cameras intact, bars near 0.25 m), and never decide a borderline
run. The fine accept/reject is `stage_gate` (ADR-0021). Reusing on another program:
the fractional/ratio/near-zero forms are already transect-agnostic; only
`LEVEL_MAX_EXTENT_M` carries a length scale, so adjust it to the deployment's
transect length and leave the rest.

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
* Registered images: a **generic SfM QC target** of ≥90% of cameras aligned —
  this is a rule-of-thumb, **not** a figure Toth's ESM states. The ESM reports
  no per-transect registered-camera count anywhere (Table S1 is coral-outplant
  *survival*, not camera registration), so we have no Toth EDR_T3 number to
  reconcile against yet. The published P13HMEON product release would carry the
  Metashape processing reports with those counts, but it was **never downloaded**
  — `data/raw/P13HMEON/` is an empty stub. **Backfilling P13HMEON is a Chat 4
  gap that Chat 6 reconciliation depends on** (it is also where the Step 4
  threshold non-transferability hypothesis gets confirmed or refuted against
  Toth's actual registration count — see the quality-threshold note below).

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

Stages are `import, step4, align, markers, reduce, dense, filter, dsm, ortho,
report`. The actual data layout: repo on the data volume at
`/data/reef-sfm-mote-keys`; images flat at `/data/raw/P1WHKTRD/EasternDryRocks`;
Metashape working area `/data/edr_work`; monitor + run logs
`/data/edr_work/logs`. Run headless under `metashape.sh -platform offscreen -r`,
inside tmux so it survives SSH drops.

```bash
PROJECT=/data/edr_work/edr_t3.psx
IMGROOT=/data/raw/P1WHKTRD/EasternDryRocks
META="/opt/metashape-pro/metashape.sh -platform offscreen -r scripts/metashape/run_pipeline.py"

# --- Headless align portion (EDR_T3 dev run; --transect scopes the import) ---
$META --project $PROJECT --image-root $IMGROOT --transect EDR_T3 --stage import
$META --project $PROJECT --stage step4 --quality-threshold 0.30   # floor cut (A/B-justified; see below)
$META --project $PROJECT --stage align  --focal-mode fallback     # smoke decided 'fallback'
$META --project $PROJECT --stage markers                          # ESM Step 7 detect + validate (gates a/b/c)

# --- On gate PASS: scale bars are built headless, no GUI ---
$META --project $PROJECT --stage scale                            # dumb applier of the validated 25 cm bars
# --- On gate FAIL (escalation): markers HALTS before scale and writes
#     <out-root>/<transect>/markers_escalation.json. Fix markers/scale bars in
#     the GUI (DCV), File→Save, then re-run `--stage markers` (validates the
#     EXISTING set, no re-detect) and, on PASS, `--stage scale`. ---
$META --project $PROJECT --stage reduce                           # ESM Step 8, scale-constrained
# --- GUI touch 2 (DCV): Jenkins coord frame (sets transform.scale); resize
#     region to ~10x1 m AOI; QA; File→Save ---

# --- Headless dense portion ---
$META --project $PROJECT --stage dense
$META --project $PROJECT --stage filter     # ESM Step 13, BEFORE dsm
$META --project $PROJECT --stage dsm         # 1 cm, no region workaround (ADR-0016 test)
$META --project $PROJECT --stage ortho
$META --project $PROJECT --stage report      # writes /data/edr_work/products/.../pipeline_summary.json
```

Notes:
- `--quality-threshold 0.30` is the **A/B-justified floor** for our re-encoded
  TIFFs; Toth's verbatim 0.50 over-cuts them (see the quality-threshold finding
  below). Omitting it uses the 0.50 default and the `> 200 disabled` alarm
  hard-stops, by design.
- `--focal-mode fallback` is passed explicitly because `focal_decision.json`
  was not committed (regenerable from `smoke_test.py --stage ab`); the smoke
  verdict was `fallback` (both arms aligned identically, prefer no-assumption).
- Critical sanity alarms (Step 4 disabling > 200/522; alignment < 70% of
  enabled; reduce with 0 scale bars; DSM 0 or > 1e8 cells; unscaled chunk at
  dense) **hard-stop** the run. Pass `--ignore-sanity` to downgrade to warn —
  not recommended for a dev run.
- `--logan-module reduce_error` once Logan is vendored (see above); until then
  the built-in transcription runs and is recorded as `builtin_fallback`.

### Reusing the marker gate on another program's data (transect-agnostic)

The `stage_markers` validation gate and `stage_scale` carry **no hardcoded T1/T3/EDR
references** — pairs are derived from the *detected* marker IDs, gate (c) is scale-free,
and every threshold is a parameter. To run it on a different survey:

**What's a parameter (CLI flags on `--stage markers` / `--stage scale`):**

| Flag | Default | Meaning | Site-dependence |
|---|---|---|---|
| `--bar-length` | 0.25 m | physical scale-bar length (recorded on each validated bar, applied by `scale`) | per program; **does not affect PASS/FAIL** (gates are scale-free) — only metric scale |
| `--marker-resid-ceiling` | 2.0 px | gate (b) coherence ceiling (median reprojection residual) | **most site-dependent — recalibrate first** (imaging conditions / turbidity differ) |
| `--interbar-ratio-max` | 1.25 | gate (c) max/min bar-length ratio | **scale-free → generalizes as-is**; rarely needs changing |
| `--min-validated-bars` | 3 | gate (d) fail-closed floor (min coherent bars for a headless PASS) | set to your deployment's bar count (floor 2) |
| `--expected-marker-ids` | none | detection-completeness identity check | your survey's coded-target IDs |

**Recalibration procedure (on your own *known-good* transect, never a bad one):**
1. Pick a transect you trust (clean detection, correct manual scale bars).
2. Run the read-only style of `probes/stage_markers_verify.py` against it (open
   `read_only=True`, `_extract_marker_records` → `validate_markers`) to read its
   per-marker median residuals and inter-bar ratio.
3. Set `--marker-resid-ceiling` to ~3–5× that transect's **max true-marker median**
   residual (margin, not a fit), and `--min-validated-bars` to its bar count. Leave
   `--interbar-ratio-max` at 1.25 unless your bars are genuinely uneven.
4. **Calibrate on the known-good case with margin; never tune a threshold to make a
   suspect transect pass** — a failing transect that escalates is the correct outcome.

**Literals not yet parameterized (v2 items):**
- **Pairing convention.** Gate (a) assumes **consecutive-ID** bars (IDs differ by 1).
  A different convention fails *closed* (orphans → escalate), but a configurable
  pairing strategy is a v2 item (ADR-0022 transferability note).
- **Target type.** Detection is fixed to `CircularTarget12bit` (ADR-0017). A survey
  using a different coded-target family needs that surfaced as a parameter (v2).

### ESM Step 4 quality-threshold finding (the headline T3 result)

Toth's ESM Step 4 disables `Image/Quality < 0.50` (verbatim). On our re-encoded
EDR_T3 TIFFs under Metashape 2.3.1 that disables **242 / 522 (46.4%)** — the
score distribution is a tight bell centered on 0.50 (median 0.507, max 0.698;
the metric is calibrated for aerial/terrestrial imagery and underwater frames
systematically score low). An on-data A/B settled the threshold (artifacts:
`data/qc/chat5/q_ab_results.json`, `q_ab_band_breakdown.json`):

| Arm | Disable < | Enabled | Aligned (of 522) | Tie points |
|---|---|---|---|---|
| Toth verbatim | 0.50 | 280 | 140 (26.8%) | 659k |
| **Floor (adopted)** | **0.30** | **517** | **515 (98.7%)** | **2.44M** |

The mechanism is in the band breakdown: the 0.30–0.50 frames Toth's cut discards
register at **235/237 = 99.2%** in the floor arm, and — the decisive cross-arm
fact — the ≥0.50 frames themselves aligned only **140/280 (50%)** when the band
was disabled but **280/280 (100%)** when it was kept. Removing 46% of frames
*fragmented the image network and broke the good frames' alignment* (overlap
collapse); it did not merely drop weak frames. **Adopted: floor cut < 0.30**
(5 frames incl. 2 degenerate). Non-transferability of the 0.50 number to our
data/version is the most likely reading but remains a **hypothesis** until
confirmed against Toth's own EDR_T3 registered count (P13HMEON backfill, Chat 6).

## Per-run observations — T3 dress rehearsal (2026-05-29)

Recorded as the run progresses; the authoritative machine-readable record is
`/data/edr_work/products/EDR_T3/pipeline_summary.json`.

- **Trial clock:** activated 2026-05-27, expires 2026-06-27 (~29 days at run
  time). Metashape 2.3.1 build 22446.
- **Input:** 522 EDR_T3 frames, SHA-256-pinned at import.
- **ESM Step 4:** `Image/Quality` median 0.507, max 0.698, 242/522 below 0.50.
  Threshold decided by on-data A/B → **floor cut < 0.30** (5 disabled). 0.50
  over-cuts (aligns 26.8% vs 98.7%). See the quality-threshold finding above
  and `data/qc/chat5/q_ab_band_breakdown.json`.
- **Alignment (production, `edr_t3.psx`, floor 0.30):** 515/517 enabled aligned
  (99.6%); 2,441,345 tie points; RMS 0.1888 filter units (pre-reduction).
  Reproduces the A/B q030 arm exactly.
- **Markers (ESM Step 7):** 7 Circular-12-bit coded targets **auto-detected
  headless** at tolerance 20, **plus 1 marker manually placed in DCV** to
  complete the fourth pair → **8 markers total → 4 scale bars**. (The
  `esm.markers` metadata records `markers_detected: 7` — the true count of the
  *detection* step only; the +1 manual placement happens later in the GUI and is
  intentionally not part of that record.) GUI pairing was geometrically
  ambiguous (mutual-NN distances inconsistent — see
  `probes/marker_pairing_geometry.py`), resolved via scale-bar residuals instead.
- **GUI touch 1 — scale bars (done):** 4 scale bars, all **enabled**, each
  **referenced at 0.250 m**; chunk scale set via **Update Transform** and
  **locked at 0.23695916**. NOTE — the earlier "~0.001 m (1 mm) each residual"
  claim was **wrong**: `0.001 m` is the `accuracy_scalebars` **input weight**
  (the assumed measurement accuracy fed to the bundle adjustment), **not** an
  achieved residual. The actual **pre-Step-8 residuals** (post-Update-Transform,
  **before** error reduction; read live from the project 2026-06-02) are:

  | Pair | Reference | Residual |
  |---|---|---|
  | 25‑26 | 0.250 m | **+15.2 mm** (pre-reduction) |
  | 13‑14 | 0.250 m | **−5.2 mm** (pre-reduction) |
  | 15‑16 | 0.250 m | **−6.9 mm** (pre-reduction) |
  | 19‑20 | 0.250 m | **−4.3 mm** (pre-reduction) |
  | **all bars, post-Step-8** | 0.250 m | **25‑26 +15.1 · 13‑14 −4.8 · 15‑16 −6.9 · 19‑20 −4.6 mm** |

  Update Transform fits a single global scale; the per-bar residuals are the
  spread around it. **Post-Step-8 update (reduce run 2026-06-02):** the
  scale-constrained `optimizeCameras` (RU→PA→RE + final fit-additional) **did not
  move the bars** — they stayed at +15.1 / −4.8 / −6.9 / −4.6 mm. Tie-point
  reprojection RMS dropped **0.9361 → 0.3499 px** (within the ESM 0.27–0.52
  envelope; QC artifact `data/qc/chat5/edr_t3_step8_px.json`).

  **Scale-bar decision — Case B hold-out NOT run; 25‑26 recorded as the
  documented worst bar.** Pair 25‑26 stayed a 2–3× outlier (+15.1 mm vs the other
  three at 4.6–6.9 mm). Root cause is **imagery-limited**: automatic coded-target
  detection performed poorly on the grainy diver imagery, so markers were placed
  and re-centered manually — better than auto, but centering is pixel-limited,
  giving scale-bar accuracy ~2× the ESM's 3.41 mm. This is **not** fixable by a
  re-optimize: the chunk scale is **locked** from Update Transform (`locked=true`,
  0.236959), so re-optimizing on the 3 control bars cannot move it, and the error
  is in the imagery, not the bundle. The tie-point px RMS (0.35 px, in envelope)
  is unaffected — it depends on reconstruction geometry, not marker centering.
  Scale refinement (unlock + bundle-refine, or re-place markers) is **deferred to
  T1/production**.

  **Limitation (writeup-ready):** EDR_T3 scale-bar accuracy is imagery-limited at
  ~5–15 mm (worst bar 25‑26 at 15.1 mm, ~2× ESM's reported 3.41 mm) because the
  grainy diver imagery does not support sub-pixel coded-target centering. The
  reconstruction's reprojection accuracy (0.35 px, within the published envelope)
  is independent of this and is unaffected.
- **Error reduction (NEXT — not yet run):** path builtin_fallback (Logan not
  vendored); scale-constrained (4 bars present, so the zero-bar hard-stop
  passes). Run `--stage reduce`, then `probes/reprojection_rms_px.py` for the
  pixel-calibrated RMS vs the ESM 0.27–0.52 px envelope.
- **GUI touch 2 — Jenkins coord frame:** pending (after reduce).
- **Confidence filter (Step 13):** pending (smoke EDR_T8 ref 30.9M→23.5M, ~24%).
- **buildDem / ADR-0016:** pending — the test is whether the scaled chunk + 1 cm
  builds the DSM WITHOUT the smoke region-clip.
- **Resource peaks (align + A/B + handoff gap only; NOT dense):** peak GPU util
  99% (brief, during matching), peak VRAM **1636 MB / 23034 MB (7%)**, peak RAM
  **8313 MB / 61909 MB (13%)**, 0 swap. Logged at
  `data/qc/chat5/t3_monitor_summary.txt`. Dense is the real VRAM/RAM stressor
  and is still to come — restart `scripts/monitor.sh start` before it.

### Session state — RESUME HERE (paused 2026-06-02, hard stop; fresh session next)

Self-contained T3 state — a fresh session can orient from this block alone.

- **Project:** `/data/edr_work/edr_t3.psx` (chunk `EDR_T3`).
- **Pre-reduce rollback:** backup `/data/edr_work/backups/edr_t3_20260602T003736Z`.
- **Trial clock:** Metashape Pro trial activated 2026-05-27, **expires 2026-06-27
  → ~25 days remaining** at this pause. Not a constraint on tomorrow's dense run.

**DONE (committed + saved):**
- `import` → `step4` (0.30 floor, 5 disabled) → `align` (515/517 enabled = 99.6%;
  2,441,345 tie points; focal mode `fallback`).
- `markers`: **8 total** (7 auto-detected headless + 1 placed manually in DCV; all
  manually re-centered) → **4 scale bars @ 0.25 m** → chunk **scale locked
  0.236959** (Update Transform).
- `reduce` complete (ESM Step 8, `builtin_fallback`, RU30 / PA3.5 / RE0.3 + final
  fit-additional): px RMS **0.9361 → 0.3499** (within ESM 0.27–0.52); **822,351**
  tie points surviving (66.3% removed); `esm.reduce` written; **saved 2026-06-02
  01:23:50**. QC: `data/qc/chat5/edr_t3_step8_px.{json,md}`.
- **Scale-bar decision:** Case B hold-out NOT run; pair 25‑26 (+15.1 mm) recorded
  as the documented worst bar — imagery-limited, scale locked, not
  optimize-fixable; scale refinement deferred to T1/production. (See the
  GUI-touch-1 bullet above for the full rationale + writeup-ready limitation.)

The day-2 GUI dense build then surfaced a **24.26° plane tilt** in the T3 product,
traced to the GUI Step-11 frame. Chat 5 resolved it — see the next section.

## Chat 5 — re-level codification: `stage_level` + `stage_aoi` + permanent gate (ADR-0021)

The day-1 24.26° tilt came from ESM Step 11 run through the GUI **USGS
AlignmentHelper** (`vendor/usgs/AlignmentHelper_v1.py`): its refine derives
yaw/pitch from a **2-marker midline** and **always sets roll = 0**; a line cannot
define roll, so the cross-axis came from the operator's visual bounding-box
orientation — unreliable for a 1 m-wide underwater strip. A second defect: a
marker-placed 10×1 box clipped the reef band (48% coverage), because markers
14/20 sit ~0.5 m off-centre and ~3° angled to the band.

**The validated method (two jobs, two references, two stages).** Leveling and
framing have different inputs and different natural phases, so they are **two
separate stages**:

- **`stage_level` (ESM Step 11, before dense).** Robust least-squares plane fit to
  the *scale-bar markers* (input = markers), with scale-bar-residual MAD outlier
  rejection (auto-excludes a bad bar — T3's 25/26, +15.13 mm), then rotate the
  plane normal → world +Z (roll+pitch only; scale preserved). A plane from ≥3
  fiducials fixes the roll DOF the 2-marker midline cannot. Reduced the tilt
  24.26° → ~1.9°; the residual ~2° **cross** tilt is the 0.85 m marker-Y-spread
  precision floor (documented, not chased — the reference cross is ~1.3°).
- **`stage_aoi` (ESM Step 14 bbox, after filter).** PCA on the *dense footprint*
  (input = footprint, via a transient interp-OFF DEM): major axis → AOI yaw (baked
  into `chunk.transform`), footprint centroid → AOI centre, 10×1×5 m crop. The
  orientation sign uses a **camera-track anchor** (first-N vs last-N camera
  centroids on PC1, +X toward the first-image-number cameras) — transect-agnostic
  and present on fresh raw data; the named-marker check is additive.

**Permanent QC gate (`stage_gate`).** Eight checks; the core (1–7) is
self-contained (no reference) so reference-less belt sites still gate: long-axis
flat ≤0.5°, total tilt ≤6.0° (a gross-mislevel bound *above* the 2–4° cross floor
and ~4× below the 24° defect — the bound is `--max-total-tilt-deg` and the
per-transect marker-Y-spread is logged every run), coverage ≥95%, scale/extent,
DEM/ortho co-reg dx=dy=0, footprint evr≥0.95 & aspect≥5 (the belt precondition),
and an **orientation sign-flip guard** (coverage/co-reg/scale are all invariant
under a 180° yaw flip of a centred symmetric AOI — without this a PCA-sign bug
ships a reversed product silently). The gate **FAILs the build** on any breach of
the reference-free core (1–7), so a 24° mis-level or a reversed product cannot
ship.

**P13HMEON reference firewall (comparison-only).** The reference is a
**quality-check / reconciliation input, never a construction input.** All
construction stages — import, step4, align, markers, reduce, **level** (markers
only), dense, filter, **aoi** (own footprint only), dsm, ortho — are fully
independent of it; scale comes from our own scale bars. The reference path
(`--reference-dem`) is consumed **solely** by the advisory gate check 8 and the
Chat-6 reconciliation (audited 2026-06-04: `--reference-dem`/`reference_dem`
appears only in `stage_gate` + the `main()` arg/dispatch; the other "reference"
tokens are `reference_preselection` and the scale-bar's own `sb.reference`). The
fetched products live in a dedicated **read-only** store
(`data/raw/P13HMEON/`, `chmod a-w`), separate from the imagery and the working
project, so no stage can glob or mutate them. **Check 8 is ADVISORY** — it
*reports* the reference-roughness overlap but is excluded from the hard-fail set;
the ship/no-ship decision stays with the intrinsic core (1–7). A reference-based
hard gate would only ever pass products that already match the published values,
making the reconciliation **circular** — keeping #8 advisory is what makes the
T1/T8 reconciliation *evidence* rather than a tautology.

**Generalization (no T3 constants).** Marker detection is auto-tolerance **by
identity** (`--expected-marker-ids`; false positives flagged, missing FAIL loud) —
a count criterion can stop on a wrong mix (7 real + 1 spurious). `stage_level`
pre-guards on alignment ≥90%, ≥2 bars / ≥3 vetted markers, and a planarity check
(`eig2/eig1`, which passes a thin belt but STOPs a collinear set). Runs unchanged
on EDR belt transects (T1/T3/T8 + other offshore belt sites) and fresh
belt-transect data; **square-plot sites (Summerland Ledges / IC_U) are out of
scope by survey design and gate #6 hard-fails them** rather than mis-framing.

**Codified vs manual reconciliation (the product decision).** The codified
pipeline (run via `run_pipeline.py`) was validated on a fresh pristine copy
(`level→aoi→dsm→ortho→gate`, no re-dense): **gate PASS** — long 0.39° / total
1.64° / coverage 97.9% / co-reg (0,0) / scale 10.000 m / evr 0.989 / +X True;
roughness 0.0918 m (reference raw 0.08–0.10 m) and tilt **closer to the reference
(~1.3°) than the hand-made pilot's 1.88°**. Regression confirmed the gate TRIPS on
the day-1 transform (DEM tilt 24.21° → checks 1 & 2 FAIL) and on a forced 180° sign
flip (check 7). The codified DEM differs from the pilot artifact
(`edr_t3_relevel_final`) by a **165.7 mm Z-datum offset + 45 mm RMS horizontal
residual** — this is **benign and non-structural**: absolute Z is arbitrary in a
LOCAL frame (the offset is the 0.23° level-R cross-DOF × the AOI lever arm), and
the 45 mm RMS is the ~3–7 cm centroid/cross-DOF frame difference sampled on a
92 mm-roughness reef; removing the datum + a best-fit plane reveals no shape/tilt
mismatch and no axis error. Because the deliverable is a **reproducible headless
pipeline**, the shipped T3 product is the **codified re-run**, not the hand-made
artifact. `edr_t3_relevel_final` stays tagged `chat5-day3-stop-20260603` as the
validated *pilot* that proved the method; nothing is lost.

**Divergence ledger (every deviation from ESM Table S2, with rationale).**

| # | ESM Table S2 | Pipeline | Class / rationale |
|---|---|---|---|
| 1 | Step 11 GUI AlignmentHelper | `stage_level`: deterministic marker-plane, outlier-rejecting | Methodological — fixes the roll-blind 24° defect; headless & reproducible |
| 2 | Step 14 manual 10×1 bbox | `stage_aoi`: footprint-PCA + camera-track anchor | Methodological — markers off-centre/angled; footprint is the robust frame |
| 3 | GUI Batch Process | headless `run_pipeline.py` | Mechanical |
| 4 | (all-points covariance for footprint) | interp-OFF DEM occupied-cell PCA, pinned to DSM res | Implementation — MS 2.3.1 dense API has no point iterator / no numpy |
| 5 | Step 7 fixed tolerance | auto-tolerance **by marker identity** | Generalization — more faithful to ESM "increase until detected"; rejects false positives |
| 6 | Steps 9–10 colour / dehaze (optional) | **skipped** | Optional, visualization-only; not in the validated recipe |
| 7 | Step 13 classify-and-keep (4-class) | destructive confidence filter only | Departure (ADR-0015); 4-class deferred to v2 |
| 8 | Step 8 Gradual Selection (Logan tool) | Logan preferred; built-in transcription fallback (Logan not yet vendored) | Faithful values; per-run documented departure (ADR-0010) |
| 9 | DSM 1 mm (PIFSC) | **1 cm (ESM)** | Corrected to ESM (ADR-0017) |
| 10 | (no gate in ESM) | permanent 8-check QC gate | Added safeguard (ADR-0021) |
| 12 | Step 7 GUI scale-bar assignment | headless **marker-layer validation gate** (a parity / b coherence / c inter-bar ratio / d sufficiency = fail-closed min-bars) → dumb `stage_scale`; GUI only on escalation | Added safeguard + automation (ADR-0022); replaces the manual assign on the PASS path |
| 13 | (brief: gate-b = mis-decodes in few cameras at high residual) | gate-b = **reprojection COHERENCE** (loose post-align tripwire, no in-gate optimize); projection count is **evidence only** | Heuristic **falsified by the data** (T1 ghost sits in 111 cameras, low residual; count non-transferable T3 5–30 vs T1 111–182) — ADR-0022 |
| 11 | Step 6/12 tie-point covariance: Yes | `optimizeCameras(tiepoint_covariance=True)` at the **align** Step-6 optimize — **wired T1 onward**; the T3 pilot ran pre-wiring (covariance is an uncertainty output, not geometry; T3 already gate-passed, NOT re-run). **Divergence (ADR-0023):** the vendored Logan governs the reduce optimize via `fit_corrections`, so it is **not force-set in `reduce`** — the post-reduce covariance is not refreshed. Product-neutral: no consumer reads tie-point covariance (manifest/QC/level/filter/dense all ignore it; it is still produced at align). v2 flag: a future export/QC of tie-point uncertainty must add an explicit refresh + re-validate | Faithful T1+ (align); documented reduce divergence + T3 gap |
| — | Keypoint 40k / dense Medium (PIFSC SOP) | **60k / High (ESM)** | ESM wins where PIFSC conflicts (ADR-0010) |

### Completion log — Chat 5 (2026-06-04, first person)

I came in to fix a leveling error and leave with a pipeline. The thing that finally
clicked: leveling and framing are *two different problems* — markers tell you which
way is up (the substrate plane), the dense footprint tells you where the reef strip
actually is. Trying to do both from the two scale-bar markers was the original sin
(off-centre, angled, roll-blind). Splitting them, and deriving each from its proper
input, is what made it both correct and general. I'm proud the gate has teeth — it
re-fails the exact 24° defect on demand, and the orientation sign-flip guard closes
a hole I wouldn't have seen (every reference-free metric is blind to a 180° flip).
Open questions I'm carrying forward: (1) headless scale-bar *pairing* is the last
GUI touch — worth closing with `--expected-marker-ids` next; (2) Logan is still not
vendored, so `reduce` runs the faithful transcription; (3) T1/T8 P13HMEON references
aren't fetched, so those transects gate on the self-contained core until I pull
them. The codified-vs-pilot 166 mm datum offset taught me to trust *relative*
product metrics in a local frame and not chase a number that's arbitrary by
construction.

**Forward (T1 production):** the from-scratch ordering `…reduce → level → dense →
filter → aoi → dsm → ortho → gate` gets its first real exercise on T1 (the
preserved-dense T3 validation never ran level-before-dense or the overnight dense).
Surface the T1 run config tracked to ESM Table S2 and the finalized ledger, then
launch only on explicit go.

### Operational incident — 2026-06-04 T1 align lost to a stale lock (postmortem)

**Class: operational, NOT methodological.** The ESM Table S2 recipe is unchanged;
this is an orchestration/discipline failure and its fix is orchestration code.

**What happened.** The first detached T1 `align → markers` run computed a full,
high-quality alignment and then lost all of it at the save:
- A **stale lock** `edr_t1.files/lock` (content `reef-ec2/ubuntu`, mtime 18:22),
  orphaned when the earlier prep/step4 Metashape process exited without releasing
  it, was still present when align opened the project at 18:47.
- Metashape **silently downgraded the open to read-only** (`Document.open(): ...
  opened in read-only mode because it is already in use`).
- Align ran the full **~1 h 56 m** anyway and succeeded in memory, then died at
  the final `doc.save()`: `OSError: Document.save(): editing is disabled in
  read-only mode`. Marker discovery never ran.
- The launcher wrote the completion sentinel **unconditionally**, so the resume
  check (`grep T1_ALIGN_MARKERS_COMPLETE … && echo FINISHED`) reported a
  **false-positive FINISHED** over a failed run.

**Evidence the loss is purely operational (params are sound).** The in-memory
result, before it was lost, was excellent: **aligned 2348/2357 enabled = 99.6%**,
**10,674,149 tie points**, **RMS 0.2322** (filter units). Nothing about the
alignment configuration is in question — only that it was never persisted.
(Incident log preserved: `logs/t1_align_markers.incident-20260604T2043Z.log`;
stale-lock removal recorded in `logs/t1_recovery.log`.)

**Root cause.** Two latent defects compounded: (1) Metashape's silent read-only
downgrade on a stale lock, never asserted against; (2) a success sentinel not
tied to actual stage success or to on-disk state.

**Fix shipped — commit `a076af0`** (each guard independently catches this):
- **Read-only fail-fast** — `open_or_create` asserts `not doc.read_only` right
  after `Document.open()` and aborts in ~1 s, before any compute.
- **Stale-lock detection** — before open, if a lock exists, scan `/proc` for a
  live Metashape `run_pipeline` holder (the lock file carries no pid); abort if
  one is alive, else remove the orphaned lock with a loud log line.
- **Honest completion signal** — `run_t1_align_markers.sh` writes
  `T1_ALIGN_MARKERS_COMPLETE` **only** when align rc==0 AND markers rc==0 AND a
  read-only reopen (`--verify`) confirms align+markers persisted on disk;
  otherwise it writes `T1_ALIGN_MARKERS_FAILED` and exits non-zero.
- **Verified saves** — `save()` confirms `doc.save()` raised no exception AND the
  on-disk mtime advanced, else raises `PipelineSaveError`.

**Carry-forward.** Apply the same discipline to the dense and the Part-B spot
layer: fail-fast preconditions before any long compute, and never a success
marker that isn't tied to verified, on-disk state.

## Trial-clock discipline

The dense reconstruction is the irreversible compute investment and the longest
pole. At ESM "High" quality it is materially slower than the PIFSC "Medium" the
original plan assumed — budget 24–48 h per the ADR, not 6–15 h. Start it first
among the long steps. If it overruns the trial window, the rest of the pipeline
is blocked, so protect that window: do alignment, marker/scale-bar setup, and
the coordinate-frame placement in the early sessions, then hand the dense run the
longest uninterrupted stretch you have. Snapshot the data volume after the dense
stage completes (recovery point) and again after export.
