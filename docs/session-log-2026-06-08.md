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
