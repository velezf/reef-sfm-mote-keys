# ADR 0023 — Retire the home-grown error-reduction transcription for the vendored USGS Logan v2.0 routine; add a network-health collapse tripwire (3a/3b/3c), a `stage_level` marker-extent sanity, and scale-bar accuracy weighting

Status: Accepted
Date: 2026-06-08
Chat: 5 (T1 processing — reduce collapse + recovery)
Related: **supersedes (in part)** ADR-0017 (the "built-in error reduction is the
only path / `reduction_path = builtin_fallback`" consequence); ADR-0010 (ESM Table
S2 binding; Logan REQUIRED); ADR-0021 (`stage_level` + the permanent 8-check gate);
ADR-0022 (marker-layer validation gate + dumb `stage_scale`)

## Context

On 2026-06-08 EDR_T1 reached a clean, human-corrected markers **PASS** (4 bars
13-14/15-16/19-20/25-26 @ 0.25 m, sub-pixel, inter-bar ratio 1.115; ADR-0022) on
**2348/2422 aligned cameras and 10,671,521 tie points**. The next stages —
`scale → reduce → level` — then **destroyed the model**:

- `reduce` ran the home-grown `_run_builtin_reduction`, a faithful-by-thresholds
  transcription of ESM Step 8 that applied RU 30 → PA 3.5 → RE 0.3 as **one-shot
  hard cuts** (select-everything-past-threshold, delete, once). On this network the
  RU cut alone selected essentially the whole cloud: it removed **100 % of tie
  points (10,671,521 → 0)** and de-aligned the cameras to **86/2422**.
- `scale` and `level` then reported **success on the wreckage**. `stage_level` read
  the **stale `esm.align` alignment-rate meta** (still 96.9 % from before reduce),
  passed its only guard, and "leveled" a marker cloud spanning **~3000 km**.

Two root causes, both addressed here:

1. **The reduction algorithm was wrong for our network.** ESM Step 8 is a *capped,
   iterative* gradual selection (delete a bounded fraction per iteration, re-optimize
   between iterations), not a single hard cut. The home-grown transcription matched
   the *thresholds* but not the *control mode*; at a high RU threshold on a dense
   reef network the one-shot cut is unbounded and can take the whole cloud. ADR-0010
   already marks the **USGS Logan script** as the REQUIRED tool precisely because it
   *is* the capped-iterative routine; ADR-0017 had deferred vendoring it and shipped
   the transcription as a stopgap. That stopgap is what collapsed.
2. **No stage verified the live network before trusting it.** Every downstream guard
   keyed off `esm.align` meta written at align time, so a post-align collapse was
   invisible — the guards certified a model that no longer existed.

The pre-collapse 4-bar state was restored from
`backups/edr_t1_4bar_20260608T153213Z` (verified by `probes/t1_postlevel_probe.py`:
2348 aligned / 10.67 M tie points / 8 sub-pixel markers / 4 bars); the collapsed
state is preserved at `backups/edr_t1_collapsed_20260608T160138Z`. **No reference
(P13HMEON) was consulted** in diagnosis or rebuild — the firewall holds.

## Decision

### 1. Retire the home-grown transcription; run ESM Step 8 via the vendored USGS Logan v2.0 routine

`_run_builtin_reduction` (and the older `_run_logan` shim) are **removed**. The
`reduce` stage now runs the real **USGS PCMSC AgisoftAlignmentErrorReduction
`Align_RuPaRe` v2.0** routine, vendored verbatim into
`scripts/metashape/vendor/logan_usgs/` (DOI 10.5066/P9DGS5B9; Logan, Wernette &
Ritchie 2022). The vendored file is third-party and stays byte-for-byte as released;
all EDR orchestration lives in `run_pipeline.py`.

> **Vendored artifact correction (2026-06-08, live STEP-5).** The first vendoring
> (repo commit `3ec2789`) pinned the **DOI-cited v2.0 *tagged* release** (archive
> sha256 `f124418878…`, `.py` `baaa3c91…`). That tag targets **Agisoft Metashape
> 1.6–1.8** and uses the pre-2.0 sparse API (`chunk.point_cloud`), so it **crashed on
> our pinned Metashape 2.3.1** (`AttributeError: 'NoneType' … point_cloud`) on the
> first live reduce — caught before any deletion (model intact). The USGS authors
> ported the **same v2.0 workflow** to the Metashape 2.0 API on `master` but **never
> tagged it**. We verified by download+hash+diff that `master` differs from the v2.0
> tag by **only** the `point_cloud`→`tie_points` accessor rename (20 sites) + the
> header version string — the RU→PA→RE algorithm is **byte-identical** to the cited
> v2.0. So the corrected vendoring pins that 2.0.x port: **commit
> `aaee35f55096f17b612fa616aa8d91c21a05f8bf`** (J. Logan/USGS, 2024-03-20),
> `Align_RuPaRe_v2_Metashape.py` sha256 `69b0972628…`. Reproducibility = the commit
> SHA + file hash (no 2.x tag exists). Full integrity table + the superseded 1.x
> hashes: `vendor/logan_usgs/PROVENANCE.md`. **Version-gap caveat:** the file targets
> Metashape **2.0.x** and we run **2.3.1**; the real-chunk integration smoke
> (`test_logan_real_chunk_smoke`) proves the RU/PA/RE filters execute on a real 2.3.1
> `tie_points` cloud — the gap the fake-module unit tests could not cover.

- **Import by file path, no `sys.path` mutation** (`_vendored_logan_module()` via
  `importlib.util.spec_from_file_location`). The module is import-safe (every
  statement under a `def`/`class` or `if __name__ == '__main__'`), so importing it
  needs only `import Metashape` to resolve (true under `metashape.sh`).
- **Threshold mode with Toth's values, capped per iteration** (`_run_logan_reduction`):
  `reconstruction_uncertainty(chunk, 30, cutoff 0.50, …)` →
  `projection_accuracy(chunk, 3.5, cutoff 0.50, …)` →
  `reprojection_error(chunk, 0.3, cutoff 0.10, …, final fit_additional_corr=True)`,
  `compute_rmse=True`, with camera optimization between iterations. RU/PA run-once;
  RE iterates to the RMSE target. The capped cutoff is the structural fix: no single
  iteration can delete more than its cutoff fraction, so the unbounded one-shot cut
  that collapsed T1 **cannot recur** by construction. Toth's *thresholds* (RU 30 /
  PA 3.5 / RE 0.3) are unchanged — fidelity is preserved; only the control mode is
  corrected to the published capped-iterative form.
- **`compute_rmse=False` on all three filters.** The vendored `compute_RMSE` helper
  calls `camera.error(point, proj).norm()` **unguarded**; on **Metashape 2.3.1** that
  returns `None` for an *aligned* camera whose post-optimize point no longer reprojects
  (a 2.0.x→2.3.1 `Camera.error` behavior gap). It surfaced on the first live T1 reduce
  (RU completed, then `compute_RMSE` crashed; model untouched — crash was before save);
  T3's geometry never produced such a `None`, so the real-chunk smoke passed and missed
  it. `compute_RMSE` is gated entirely by the `compute_rmse` kwarg, and `compute_rmse=
  False` is a **documented Logan mode** (its source, lines 980-984): RU/PA skip only the
  diagnostic RMSE; **RE iterates by the threshold criterion — deleting until no tie
  point exceeds RE (0.3 px)**, which implements ESM Table S2 "Reprojection Error 0.3".
  The vendored file stays byte-for-byte (no fork). `compute_RMSE` is *not* used to
  commit the reduce: the `esm.reduce` RMSE is computed independently by our
  `_reprojection_rms` (reads `TiePoints.Filter.values`, never `camera.error`, so it is
  `None`-safe). A pure-pytest contract test locks `compute_rmse=False` against a
  regression to `True`, and the real-chunk smoke runs the exact production reduce path.
- **No silent fallback + vendor-time identity check.** With the transcription retired
  there is no built-in path to fall back to. A missing/unimportable vendored module
  **raises and halts** (`FileNotFoundError` from `_vendored_logan_module`, or the
  import error from the `--logan-module` override) — `reduce` can never silently skip
  error reduction or quietly run a different algorithm. Additionally,
  `_assert_vendored_logan_identity` checks at load that the file declares **Metashape
  2.0.x** and uses the **`tie_points`** API (rejecting the 1.x `point_cloud`
  artifact) — so the exact mislabel that crashed the first live reduce is caught at
  load, loudly, not mid-run. `--logan-module <name>` still overrides the vendored copy
  with an importable module (kept for testing / a future re-pin); the default is the
  vendored file.
- The `reduction_path` recorded in `esm.reduce` is `logan_vendored:Align_RuPaRe_v2_Metashape.py`
  (or `logan:<mod>` under an override) — the value `builtin_fallback` is **retired**.

### 2. Network-health collapse tripwire — 3a / 3b / 3c (defense in depth)

A coarse, Metashape-free-at-the-core **collapse guard** that no downstream stage can
bypass. The pure evaluator `evaluate_network_health(state, …)` (unit-tested on
synthetic states) returns `{ok, failures, metrics}`; `_extract_network_state` reads
the **live** chunk; `_check_network_health_or_escalate` writes a structured
`network_health_escalation.json` (same shape/role as the marker gate's report) +
stamps `esm.network_health` + raises a critical alarm (HALT) on failure.
`HealthConfig` carries the thresholds (all CLI-overridable).

Three discriminators, in priority:

- **Camera survival (PRIMARY).** A clean reduce does **not** de-align cameras.
  Aligned cameras must be ≥ `HEALTH_MIN_ALIGNED_FRAC` (0.90) × baseline. Baseline =
  the *pre-stage* aligned count (3b) or the live enabled count (3c).
- **Scale-bar sanity (PRIMARY, COARSE).** A sane metric model keeps bars near their
  defined 0.25 m; a collapse blows them to kilometres. `max(measured/defined,
  inverse) ≤ HEALTH_SCALEBAR_MAX_RATIO` (2.0). This is a **coarse within-2× tripwire,
  NOT** the fine scale gate (`stage_gate`). **Only checked at phases where the model
  is already metric** — i.e. *after* the scale-constrained optimize inside `reduce`.
  At the pre-optimize phases (`scale:pre`, `reduce:pre`) the bars are still in
  internal units (transform scale 1.0) and this check is skipped, or it would
  false-fire (it did, on `reduce:pre`, 2026-06-08 — corrected). The per-phase policy
  is the single source of truth `HEALTH_CHECK_SCALEBARS` (False for `scale:pre` /
  `reduce:pre`; True for `reduce:post` / `level:pre` / `dense:pre` / `dsm:pre` /
  `ortho:pre`); `_check_network_health_or_escalate` derives the flag from the phase so
  a call site cannot pick the wrong value.
- **Tie-point NEAR-ZERO tripwire.** `tie_points ≤ HEALTH_MIN_TIEPOINTS` (1000).
  Deliberately **not fractional**: a healthy Logan reduce legitimately sheds a large
  share of tie points, so a fractional floor would false-fire. It catches only
  near-total removal (the T1 collapse left 0). Calibration per the user: this is a
  near-zero floor, not a percentage.

Wired at three points:

- **3a — within-reduce per-pass backstop** (`_capped_pass` inside
  `_run_logan_reduction`). Each **run-once** RU/PA filter is measured; a single pass
  dropping > `HEALTH_MAX_PASS_DROP_FRAC` (0.50) of its input is anomalous (Logan's
  RU/PA cutoff is 0.5, so it never trips in a healthy run) → write escalation +
  HALT, **before the reduction proceeds to the next filter and before any success
  meta or save**. This is the guard most specific to the actual collapse: the
  collapse *was* a single pass taking the whole cloud. RE is **not** fraction-gated
  here — it iterates to an RMSE target and may legitimately shed a large *cumulative*
  share; the 3b post-condition covers it. (Honest limit: Logan's select-and-delete
  is atomic, so 3a cannot un-delete the offending pass's own points — it stops the
  *reduction* at that pass before propagation and commit, and the result is never
  saved as success.)
- **3b — reduce POST-condition** (success-tied). After RU/PA/RE, re-check against the
  **pre-reduce aligned count** *before* `esm.reduce` success is written or the
  project saved. The collapse can never be recorded as success.
- **3c — PRE-condition** at the entry of `scale`, `reduce`, `level` (and `dense` /
  `dsm` / `ortho`). Reads the **live** aligned-camera count (+ tie-points) — this is
  the direct fix for the stale-meta bug: a stage refuses to run *on* an
  already-collapsed model rather than trusting `esm.align`. **Scale-bar sanity is
  applied per the phase policy above**, NOT at every pre-condition: the pre-optimize
  phases (`scale:pre`, `reduce:pre`) check cameras + tie-points only, because the
  metric scale is realized by `reduce`'s optimize and the bars are still internal
  units beforehand (the corrected 2026-06-08 `reduce:pre` false-positive); the
  post-optimize phases also check scale-bar sanity.

`--ignore-sanity` downgrades the HALT to a warning **but still writes the escalation
report** — a forced run can never hide a collapse.

### 3. `stage_level` marker-extent sanity

`stage_level` additionally refuses to fit a level plane when the marker set spans
more than `LEVEL_MAX_EXTENT_M` (50 m) in any axis (a real transect is ~10 m). This
is the specific tripwire for the "leveled markers spanning ~3000 km" failure, on top
of the 3c live pre-condition. The legacy `esm.align`-rate pre-guard is kept but is
now backed by the live check, not relied upon alone.

### 4. Scale-bar accuracy weighting (`stage_scale`)

`stage_scale` sets `sb.reference.accuracy = scalebar_accuracy_m` (PARAMS default
**0.001 m**; `--scalebar-accuracy-m`) on **every** bar — both those it creates and
any the human created in the GUI on the re-entry path (which came in with
`accuracy = None` = active-but-unweighted). This makes the 0.25 m bars **weighted
active constraints** in the downstream Logan final optimize, so the scale-bar
reference distance actually pulls the metric scale. Recorded in `esm.scale`.

## Supersession of ADR-0017 (scoped — read carefully)

ADR-0017 is a **multi-topic** decision (ESM Step 4 image-quality filter, the
confidence `filter` stage between dense and dsm, the `--stage` model, DSM = 1 cm).
**Those decisions remain Accepted and in force.** This ADR supersedes **only one
consequence** of ADR-0017: its "Built-in error reduction is currently the only path"
paragraph — i.e. that `reduce` runs `_run_builtin_reduction` and records
`reduction_path = "builtin_fallback"` because Logan is not yet vendored. That
specific decision is **reversed**: Logan is now vendored and is the path; the
built-in is removed. ADR-0017 carries a "superseded in part" banner pointing here so
the trail is explicit rather than silently contradictory. We deliberately did **not**
flip ADR-0017's status wholesale, because that would falsely retire its still-active
Step-4 / filter-stage / stage-model / DSM-resolution decisions.

## Divergence ledger — tie-point covariance is no longer force-set in `reduce`

The removed `_run_builtin_reduction` force-set `optimizeCameras(tiepoint_covariance=
True)` on its post-reduce optimize. The vendored Logan governs its own optimize calls
(via the `cal_*`/`fit_corrections` dict and a final `fit_additional_corr=True`) and
does **not** set `tiepoint_covariance`. So after a vendored-Logan reduce the
post-reduce tie-point covariance is **not refreshed**.

**Decision: leave it unset in `reduce`; document the divergence.** Rationale:

1. **No downstream consumer reads tie-point covariance.** It is an *uncertainty
   output, not geometry* (docs/05 Step-11 covariance row). The manifest
   (`pipeline_summary.json`), the permanent 8-check QC gate, `stage_level`, the
   confidence `filter` (which uses *dense-cloud* confidence, not tie-point
   covariance), and the dense build all ignore it. The one `covariance` use in the
   code is an unrelated 2×2 **XY footprint PCA** for AOI yaw.
2. **It is still produced where ESM specifies it** — the align-stage Step-6 optimize
   sets `optimizeCameras(tiepoint_covariance=True)` (line ~842, unchanged). The
   covariance output ESM Table S2 calls for is generated in the pipeline.
3. **Re-imposing it post-Logan would conflict with letting Logan govern the final
   fit.** A trailing `optimizeCameras(tiepoint_covariance=True)` after Logan's
   authoritative final optimize would be an extra, non-Logan bundle adjustment —
   exactly the home-grown departure we are retiring.

Note also that gradual selection *deletes* tie points, so any covariance computed at
align time is stale post-reduce regardless; since nothing consumes it, this is
product-neutral. **v2 flag:** if a future Chat-6 manifest/QC step decides to *export*
or *gate on* tie-point uncertainty, it must add an explicit covariance-refresh
optimize (or thread `tiepoint_covariance` through Logan's final optimize) **at that
point** and re-validate — it must not silently assume a fresh post-reduce covariance
exists today.

## Consequences

- **The T1 collapse cannot recur by construction**: the capped-iterative Logan
  routine bounds per-iteration deletion, and three independent live tripwires
  (per-pass 3a, success-tied post 3b, live pre-condition 3c) plus the `stage_level`
  extent sanity stop a collapsed/blown-up bundle from being saved as success or fed
  downstream. A forced (`--ignore-sanity`) run still leaves the escalation report.
- **`reduce` has no silent failure mode**: a missing/broken vendored module halts
  loudly; there is no built-in to fall back to.
- **Defaults are calibrated coarse, not tuned**: the health thresholds discriminate a
  *collapse* (0 tie points, 86 cameras, km bars) from a *healthy* reduce (millions of
  tie points shed legitimately, cameras intact, bars near 0.25 m) with wide margin —
  they are NOT the fine accuracy gate and never decide a borderline run. Recalibration
  guidance (transect-agnostic) lives in docs/05.
- **Firewall intact**: every guard is reference-free (camera counts, internal-unit /
  coarse-metric scale bars, tie-point counts). P13HMEON is never consulted.
- **Proven on fixtures before any live re-run**: the pure evaluator, the synthetic
  COLLAPSED-chunk escalation (3b), the per-pass >cutoff backstop (3a), the
  loud-failure-on-bad-load, and the "built-in retired" regression are unit-tested in
  `scripts/metashape/test_network_health.py`. The guards are not trusted untested.

## Sources

- Logan, J.B., Wernette, P., & Ritchie, A. (2022). *AgisoftAlignmentErrorReduction*
  (`Align_RuPaRe` v2.0), USGS Pacific Coastal and Marine Science Center.
  DOI 10.5066/P9DGS5B9. Vendored: `scripts/metashape/vendor/logan_usgs/`
  (PROVENANCE.md, integrity hashes).
- Toth et al. 2025 Supplementary Material Table S2, Step 8 (Reconstruction
  Uncertainty / Projection Accuracy / Reprojection Error gradual selection).
- [ADR-0010](0010-adopt-toth-usgs-metashape-workflow.md) (Logan REQUIRED; parameter
  source).
- [ADR-0017](0017-esm-step-4-image-quality-and-production-wiring.md) (the
  built-in-fallback consequence superseded here).
- [ADR-0021](0021-headless-stage-level-and-stage-aoi-with-permanent-gate.md)
  (`stage_level`; the permanent QC gate the health guard sits beside).
- [ADR-0022](0022-headless-marker-layer-validation-gate.md) (the markers PASS that
  preceded the collapse; the escalation-report shape reused here).
- The 2026-06-08 T1 reduce collapse + recovery: `docs/session-log-2026-06-08.md`;
  probe `probes/t1_postlevel_probe.py`; backups `edr_t1_4bar_*` / `edr_t1_collapsed_*`.

#tags: metashape-api, esm-step-8, error-reduction, logan-usgs, vendored, gradual-selection, network-health, collapse-guard, stage-reduce, stage-scale, stage-level, scale-bar-accuracy, tiepoint-covariance, firewall, chat5
