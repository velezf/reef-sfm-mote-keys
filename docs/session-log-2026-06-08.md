# Session log — 2026-06-08 (Chat-5 processing): T1 markers PASS, reduce collapse + recovery, vendored-Logan rebuild

Disconnect-safe resume file. Nothing irreversible is running. No dense. The working
`edr_t1.psx` is the RESTORED pre-collapse 4-bar state (verified). All code changes below
are ON DISK; commit state noted at the end.

## Where we are (one line)
T1 reached markers-PASS → scale → **reduce COLLAPSED the model** (home-grown one-shot
gradual selection); restored the pre-collapse backup; **rebuilt the reduce step on the
vendored USGS Logan v2.0 + added a network-health collapse guard (ADR-0023 work)**; suite
**161 green** incl. a synthetic-collapse regression test. STOPPED before the live re-run.

## DONE this session
1. **pytest fix** (commit `dd95c9a`): bare `pytest` now collects all 151 (testpaths + order-safe
   Metashape stub).
2. **T1 markers loop, live**: `--stage markers` ESCALATED (correct) → user GUI fix in DCV →
   re-validate **PASS** (human-corrected, 4 bars 13-14/15-16/19-20/25-26 @ 0.25 m, sub-pixel,
   inter-bar ratio 1.115). `validated_scalebars.json` emitted.
3. **scale → reduce → level** ran → **reduce COLLAPSE**: `_run_builtin_reduction` applied ESM
   thresholds (RU 30 → PA 3.5 → RE 0.3) as ONE-SHOT hard cuts, removed 100% of tie points
   (10,671,521) → **86/2422 aligned**; scale/level "succeeded" on wreckage (stage_level read STALE
   align meta, leveled markers spanning ~3000 km). Probe: `/data/edr_work/probes/t1_postlevel_probe.py`.
4. **Recovery (STEP 1, verified)**: restored `backups/edr_t1_4bar_20260608T153213Z` over
   `/data/edr_work/edr_t1.psx`; probe confirms **2348/2422 aligned, 10,671,521 tie pts, 8 markers
   sub-pixel, 4 bars**. Collapsed state preserved: `backups/edr_t1_collapsed_20260608T160138Z`.
5. **STEP 2 — vendored Logan** (DONE, uncommitted): real USGS PCMSC AgisoftAlignmentErrorReduction
   **v2.0** at `scripts/metashape/vendor/logan_usgs/` (Align_RuPaRe_v2_Metashape.py + LICENSE/DISCLAIMER/
   Readme/CHANGELOG/code.json + PROVENANCE.md). DOI 10.5066/P9DGS5B9. zip sha256
   `f124418878c51a0f756b5495d7c4ce76f5645e49f087e5caced2bdb9565db65f`; py sha256
   `baaa3c91a8715f54a144b82e79c252b21f6d1b99afafb4980802ad428231ea1b`. `run_pipeline.py`: removed
   `_run_builtin_reduction` + old `_run_logan`; added `_vendored_logan_module()` (import by file path,
   import-safe), `_logan_cam_opt()`, `_run_logan_reduction()` calling RU(30,cutoff .5)→PA(3.5,.5)→
   RE(0.3,.1) with `compute_rmse=True`, final `fit_additional_corr=True`. `stage_reduce` now uses it
   (Logan is the DEFAULT; `--logan-module` still overrides). Restores chunk.label (Logan appends _Ru/_Pa/_Re).
6. **STEP 3 — collapse guards** (DONE, uncommitted): reusable `evaluate_network_health` (PURE) +
   `_extract_network_state` + `_write_health_escalation` (writes `network_health_escalation.json`, same
   shape as marker gate) + `_check_network_health_or_escalate` + `HealthConfig`. Wired:
   **3a** within-reduce per-pass backstop on RU/PA (run-once; >`max_pass_drop_frac` 0.5 → escalate; RE
   NOT fraction-gated — iterative, covered by 3b); **3b** reduce POST-condition (success-tied, baseline
   = pre-reduce aligned); **3c** PRE-condition at entry of scale/reduce/level/dense/dsm/ortho (live
   aligned count — fixes the stale-meta bug). `stage_level` also gets a marker-extent sanity
   (`--level-max-extent-m` 50 m). Constants HEALTH_MIN_ALIGNED_FRAC 0.90 / HEALTH_MIN_TIEPOINTS 1000 /
   HEALTH_SCALEBAR_MAX_RATIO 2.0 / HEALTH_MAX_PASS_DROP_FRAC 0.50 / LEVEL_MAX_EXTENT_M 50. All CLI-
   overridable (`--health-*`, `--reduce-max-pass-drop-frac`, `--level-max-extent-m`). Tie-point check is a
   NEAR-ZERO tripwire (not fractional) per the user's calibration.
7. **STEP 4 — scale-bar weighting** (DONE, uncommitted): `stage_scale` sets `sb.reference.accuracy =
   scalebar_accuracy_m` (PARAMS default 0.001 m; `--scalebar-accuracy-m`) on ALL bars (created + GUI-
   reused; was `None`). Recorded in esm.scale meta.
8. **Tests** (DONE, uncommitted): new `scripts/metashape/test_network_health.py` (10 tests: pure
   evaluator + synthetic COLLAPSED stub chunk escalates + healthy passes + near-zero-not-fractional +
   ignore-sanity-still-reports). Updated `test_stage_markers_loop.py` (stage_scale new signature; no-op
   the health check in its fixture). **Full suite 161 green.** PROOF GATE met: guard escalates on
   synthetic collapse + all green.

## REMAINING (in order) — pick up here
A. **ADR-0023** (`docs/decisions/0023-…`): built-in → vendored Logan (cite Logan 2022 / DOI / ESM Step 8 /
   the T1 collapse) + the 3a/3b/3c network-health tripwire + stage_level extent sanity + scale-bar
   accuracy 0.001. Note the DIVERGENCE: vendored Logan's final optimize governs fit_corrections; the old
   builtin's `tiepoint_covariance=True` is NO LONGER force-set in reduce — flag/decide if a downstream
   consumer needs it.
B. **docs/05** rows: the reduce change + the health-guard config params with recalibration guidance
   (transect-agnostic rule).
C. **Commit** A+B with the code (code/tests are currently UNCOMMITTED on `main`).
D. **SHOW the user the PROOF GATE** output (161 green + the collapse test) and get the **explicit go**
   for STEP 5 (per their tightening-1: guards proven before the live run).
E. **STEP 5 — live re-run (on go, NO dense)**: `--stage markers` (re-validate → PASS, human-corrected) →
   `scale` (now sets accuracy 0.001) → `reduce` (vendored Logan; expect capped-iterate, cameras SURVIVE,
   tie points shed a large but non-total share, RMS ~0.3-0.5 px) → `level`. Re-run
   `probes/t1_postlevel_probe.py` and report: aligned-camera survival, tie points, post-reduce reproj
   error, per-bar SIGNED scale-bar errors + whether inter-bar spread tightens from 1.115, leveling
   result (long/total tilt). **STOP before dense for the user's go.** Back up before the run
   (the 4bar backup is the clean pre-scale checkpoint; take a fresh one before scale).

## RUN COMMANDS (STEP 5, when greenlit)
```bash
cd /data/reef-sfm-mote-keys
MS="/opt/metashape-pro/metashape.sh -platform offscreen -r scripts/metashape/run_pipeline.py \
    --project /data/edr_work/edr_t1.psx --transect EDR_T1"
$MS --stage markers   # -> PASS (re-validate existing corrected set)
$MS --stage scale     # sets scale-bar accuracy 0.001
$MS --stage reduce    # vendored Logan; ~10+ min (compute_rmse RE loop). Guards halt on collapse.
$MS --stage level
/opt/metashape-pro/metashape.sh -platform offscreen -r /data/edr_work/probes/t1_postlevel_probe.py
# verify lock cleared first: ls /data/edr_work/edr_t1.files/lock  (none) ; project must be CLOSED in GUI.
```

## GUARDRAILS (unchanged)
FIREWALL: P13HMEON comparison-only, never read for reduce/scale fix. NO dense without explicit go. The
gate is BUILT + proven; T1 escalating is correct. Backups preserved (premarkers/postgui/4bar/collapsed).
Repo has a remote `origin` (github velezf) and is even with origin/main — commits ARE pushed (contradicts
old "never push" note; flag if unintended). Reduce wall-clock observed ~10 min (collapsed builtin);
vendored-Logan RE with compute_rmse may differ.

---

## EVENING 2026-06-08 → 06-09 — STEP 5 reduce BLOCKED on optimizeCameras datum divergence

Disconnect-safe. Model NEVER touched: `edr_t1.psx` mtime **19:00** (post-`scale`), 0 SaveProject,
0 esm.reduce, orphaned lock cleaned, all backups preserved. All work below was on scratch COPIES.

### Where we got to
markers (re-validate PASS) + scale (bars @ 0.001, idempotent) re-ran fine. **reduce is blocked.**

### The BLOCKER (proven, bar-independent)
A single `optimizeCameras` on the post-scale T1 model **numerically diverges**:
- reproj **median 0.15 px → 14–19 px**; **max → 1.3e152**; **transform.scale 1.0 → 823.77**.
- The vendored-Logan reduce manifested this as: RU(-11%)+PA(-50%) OK, then RE's threshold search
  hung because ~97% of the post-PA cloud had reproj > 8.9 px (the same degradation), crawling at
  0.01 increments. Stopped it; nothing saved.

### FALSIFIED hypothesis (honest diagnostic note; see ADR addendum)
"Scale-bar over-constraint (1440sigma: bars 1.69 internal vs 0.25 m @ 0.001)". Disproven on scratch
copies via a clean A/B/C (one optimizeCameras each, fresh copy, no save):
| Arm | reproj median | max | scale |
|---|---|---|---|
| BEFORE (all) | 0.14988 | 0.748 | 1.0 |
| 1 bars as-is | 19.19 | 1.3e152 | 823.77 |
| 2 updateTransform→opt | 19.03 | 1.3e152 | 823.77 |
| 3 bars DISABLED (control) | 13.82 | 1.3e152 | 823.77 |
Arm 3 (control) diverged too => **bars are NOT the cause**. Arm 2 falsified candidate-fix #1:
`chunk.updateTransform()` did NOT scale the bars (still ~1.69 m) and pre-optimize reproj stayed
0.15 px (the 823 scale itself is harmless) — the damage is the optimize STEP.

### DATUM DUMP (read-only, the decisive diagnostic — verbatim)
```
chunk.crs        = WGS 84 (EPSG::4326)  -- GEOGRAPHIC, DEGREES (spurious; ADR-0018/0020)
transform.scale attr = None ; matrix col0 norm = 1.0 ; matrix = identity
region.size   = (311.5, 204.9, 178.2)   region.center = (-15.45, 23.44, -33.60)
chunk.marker_crs = None ; chunk.camera_crs = None
cameras: 2422/2422 have reference.location, ALL = (-81.84433, 24.4591, 0.0)  [lat/lon, single fix]
  camera_location_accuracy = 10 m
markers: 8/8 have reference.location, GARBAGE WGS84 mis-projection, enabled=True, acc=None:
  Marker 20 (73.73, -89.987, -6356740.88)   Marker 19 (74.28, -89.989, -6356740.36)
  Marker 15 (109.61,-89.997, -6356704.58)   Marker 16 (113.41,-89.998, -6356706.09)
  Marker 14 (91.61, -89.986, -6356719.93)   Marker 13 (90.88, -89.984, -6356721.23)
  Marker 25 (14.57, -89.960, -6356747.57)   Marker 26 (15.94, -89.958, -6356747.44)
  (-89.9 deg latitude, Z ~ -6,356,740 m ~ -WGS84 polar radius => pure degree-space garbage)
marker_accuracy = 0.005 m ; scalebar_accuracy = 0.001 ; camera_location_accuracy = 10 m
scalebars: 4 x {dist 0.25, acc 0.001, enabled True}
```

### DIAGNOSIS — fork resolved toward (B) DATUM/CRS
The dump points hard at **fork B**: the chunk is WGS84 (degrees); every camera carries a single-fix
lat/lon reference; every marker carries enabled GARBAGE WGS84 reference coords. `optimizeCameras`
refits the datum to these degree-space references => scale 823.77 (degrees<->metres factor) + bundle
divergence. **Anchor:** Step 6 align optimize held scale 1.0 / 0.15 px with this same chunk because
markers (and their garbage refs) did not exist yet — they were added by stage_markers AFTER align, so
the first optimize to *see* the marker references is reduce's. NOT fork A (params), NOT the scale bars.

### NEXT (next session; short CPU-only burst; NOT yet run)
2-arm A/B on copies, using **Logan's EXACT optimizeCameras call** (extract from the vendored file):
- Arm A: datum as-is (expect diverge, reproduces blocker with the real params).
- Arm B: set a **LOCAL metric CRS (ADR-0020 lever, e.g. LOCAL_CS)** + **clear/disable the camera AND
  marker reference** at chunk level (the garbage marker refs + single-fix cam refs), THEN optimize.
- A blows up + B clean => datum is root; fix = neutralize the datum (local metric CRS + drop the
  spurious references) BEFORE reduce. Both blow up => fall back to fork A (optimize params/divergence).
Likely fix lands in `stage_scale`/pre-reduce: enforce local metric CRS + strip auto-populated WGS84
camera/marker references so the scale-constrained optimize is well-posed. Firewall holds (reference-free).

### STATE
- compute_rmse=False reduce mode **STANDS** (correct + tested; independent of this blocker; committed).
- Model safe (mtime 19:00). Backups: premarkers/postgui/4bar/collapsed/preSTEP5/prereduce.
- COST: datum analysis is off-instance (this text); the A/B optimize-confirm is CPU-bound (no GPU) ->
  short EC2 burst next session. Instance stopped overnight.
