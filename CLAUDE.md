# CLAUDE.md — reef-sfm-mote-keys (always-loaded context; keep distilled)

EasternDryRocks SfM pipeline. Methods = **Combs 2021 + Toth 2025 (ESM Table S2)**;
PIFSC SOP is parameter-reference only. Entry point: `scripts/metashape/run_pipeline.py`
(headless, stage-resumable via `--stage`); T1 launcher `scripts/ops/run_t1_align_markers.sh`.
Full processing doc + divergence ledger + incident log: `docs/05-metashape-processing.md`.

## Operational invariants (lessons learned — now enforced in code; hold them everywhere)

These are enforced for align/markers and **must** be applied to the dense and the
spot layer too (born from the 2026-06-04 T1 incident: a stale lock → silent
read-only open → ~2 h align computed then lost at save → an unconditional sentinel
reported a false "FINISHED"):

1. **Never write a completion/success marker unconditionally.** Tie it to verified
   stage success: `rc==0` AND the on-disk output verified (reopen, expected chunk +
   artifacts present). A sentinel that isn't gated on real state is a lie.
2. **Assert `not doc.read_only` immediately after `Document.open()` and abort
   before any compute.** Metashape silently downgrades to read-only on a present
   lock; a read-only save raises only *after* the work is done.
3. **Detect stale locks** (`<project>.files/lock` with no live Metashape holder —
   the lock has no pid, so scan `/proc`): clean-with-log if orphaned, or abort
   clearly if a holder is alive. Never silently open read-only.
4. **Verify every `doc.save()` persisted** (no exception AND mtime advanced) before
   depending on it; raise loudly otherwise (`PipelineSaveError`).

Other standing rules: **P13HMEON reference is comparison-only** (firewall
`325dbc7`) — never a construction input, never an AOI; if a transect is non-belt,
the AOI must be reference-free (markers / survey convention). **EDR_T3 is shipped**
— don't re-dense or touch the promoted `edr_t3.psx` (pristine copy-only). **Dense
runs only on the user's explicit GO.**

## Current state / resume pointer (2026-06-16 — Chat 7 in progress)

EDR_T3 shipped. EDR_T1 products COMPLETE. **EDR_T1_R2 metric DSM COMPLETE — reconcile is next.**

Active branch: `feat/reconcile-r2-transect` (pushed to origin; EC2 on this branch, local tracking).

### T1 product table (area survey, 2,422 images)

| stage | status | notes |
|-------|--------|-------|
| markers | PASS | |
| scale | PASS | ADR-0024: LOCAL_CS + refs disabled; scale 0.15246 m/unit |
| reduce | PASS | ADR-0023 vendored Logan; 3,568,318 tie pts; sigma0 0.159 |
| level | PASS | ADR-0025 camera-nadir UP (collinear markers); 14.78 m Z = genuine topo |
| region | SET | 28.92 × 25.41 × 15.33 m; coverage 99.82% |
| dense | PASS | 651,419,413 pts; 2.8 h; rc=0 (2026-06-10T13:35Z) |
| filter | PASS | ADR-0015: 651M → 487,749,550 (25.1% removed, threshold=2); rc=0 |
| aoi | PASS | ADR-0028: corrected Z window [−9.2, +1.8] m; 26.5M in-window pts; coverage 97.1% |
| dsm | PASS | ADR-0027: 1000×100 cells @ 1 cm = 10.00×1.00 m; sha `9cc8eb75` |
| ortho | PASS | 2000×200 px @ 5 mm GSD (DEM surface, ESM Step 15); sha `e86deb03` |
| fullarea ortho | PASS | 1764×1383 px @ 2 cm (PointCloudData-direct; ADR-0029 deviation); sha `e03dbf7e` |
| gate | 2/7 FAIL | both non-blockers — see below |

### Gate 2/7 failures — documented non-blockers

- **Check 2 (`total_tilt_deg` 8.71° > 6.0°):** Long-axis tilt is 0.37° (negligible).
  Total tilt is dominated by real reef-wall cross-axis slope. The 6.0° threshold was
  sized for the 24° mis-level incident (ADR-0025 backstory), not for topo transects.
  **Do NOT re-level or move the threshold.** Tracked: `fix/probe-topo-gates`.
- **Check 7 (`orientation_plus_x` False):** Benign 135°-vs-+X convention mismatch
  in `stage_gate`. No product flip. Note it; don't touch it.

### T1_R2 product table (R2 single-transect reconstruction, 272 images — ADR-0033)

| stage | status | notes |
|-------|--------|-------|
| import | PASS | 272 TIFFs (`20230711_EDR_T1_R2_*.tif`); P1WHKTRD imagery only |
| step4 | PASS | 132/272 retained (quality ≥ 0.50); 140 disabled |
| align | PASS | 131/132 aligned (99.2%); pre-reduce RMS 0.1734 px |
| markers | PASS | all 4 sub-gates PASS |
| scale | PASS | 3 bars (pairs 15–16, 19–20, 25–26 × 0.25 m); peak residual ±1.76% |
| reduce | PASS | Logan v2.0.x; 603,314 → 236,860 tie pts; post-reduce RMS 0.1397 px (below S2 band — explained in ADR-0033) |
| level | PASS | camera-nadir UP; pre-level 57.41° → post-level 7.977° |
| dense | PASS | 47,143,867 pts; EBS snapshot `snap-0b10abc94d12b78e1` |
| filter | PASS | moderate confidence; 47.1 M → retained |
| aoi | PASS | manual override (ADR-0033); GATE#6 skipped (out-and-back geometry); GATE#3 93.7% < 95% bypassed (--ignore-sanity); 47.1M → 12,585,711 pts |
| dsm | PASS | 1000×100 cells @ 1 cm; float32 T_z recentered (ADR-0033); interp-ON coverage 99.8%; sha `620bc3bc` (internal tile) |
| ortho | — | not yet built |
| gate | — | not yet run |

**Open item:** marker pair 25–26 label basis pending Frank's confirmation (physical-to-label correspondence for the far-end target).

### ADRs in effect

| ADR | Decision |
|-----|----------|
| ADR-0023 | Vendored Logan reduce |
| ADR-0024 | LOCAL_CS in stage_scale |
| ADR-0025 | Camera-nadir leveling |
| ADR-0026 | ~~Original T1 AOI Z window~~ **SUPERSEDED by ADR-0028** |
| ADR-0027 | DSM at 1 cm |
| ADR-0028 | Corrected Z window [−9.2, +1.8] m, surface-median-anchored. Surface is trough-to-crest (shoulder ~−2.1 m / trough ~−5.2 m / crest ~−0.7 m). Prior truncation: 2.58 m → 10.00 m DSM; coverage 16.3% → 97.1%. |
| ADR-0029 | Full-area ortho built PointCloudData-direct (not DEM→ortho). `buildDem` hangs on 487M-pt cloud in Metashape 2.3.1 (3 confirmed runs). Portfolio visual only — NOT the ESM Step-15 product. Transect ortho IS DEM-sourced (compliant). |
| ADR-0030 | Reconciliation metric core (rugosity, standardized elevation, VRM; SAPA/RIE/ASD = explicit stubs) |
| ADR-0031 | QC gate provenance: Toth Table S2 gates, conformance/outcome split, not-evaluable ≠ pass |
| ADR-0032 | Reconciliation harness + confirmed P13HMEON contract; T1 area-survey is envelope-only (scale mismatch); Option-2 R2 1:1 is the strong-claim path |
| ADR-0033 | Option-2 R2 single-transect reconstruction. GATE#6 bypassed (out-and-back geometry); float32 T_z fix permanently integrated in stage_dsm; frame verified (identity projection = leveled world Z). |

### Snapshots on disk (EC2 `/data/edr_work/`)

- `edr_t1_postdense_20260610T181702Z.{psx,files}` — 27 GB; post-dense, pre-filter (pristine)
- `edr_t1_postlevel_adr0025_20260609T220420Z.{psx,files}` — post-level, pre-region (pristine)
- `edr_t1_truncated_adr0026v1_20260610T232809Z.{psx,files}` — post-truncated run (ADR-0026 v1)
- Live T1 project: `edr_t1.psx` — post-products state
- **T1 EBS snapshot:** `snap-034d45019a4e39c43` — tag `edr_t1_postproducts_20260610T235019Z`
- Live R2 project: `edr_r2.psx` — post-DSM state (`feat/reconcile-r2-transect`)
- **R2 EBS snapshot:** `snap-0b10abc94d12b78e1` — post-dense/filter, pre-AOI/DSM

### Local products (Mac `products/`, gitignored)

| file | sha256 | notes |
|------|--------|-------|
| `EDR_T1/edr_t1_transect_dsm_20260610T234951Z.tif` | `9cc8eb75…` | MANIFEST `618f325` ✓ |
| `EDR_T1/edr_t1_transect_ortho_20260610T234951Z.tif` | `e86deb03…` | MANIFEST `618f325` ✓ |
| `EDR_T1/edr_t1_fullarea_ortho_20260610T210155Z.tif` | `e03dbf7e…` | MANIFEST `a9337f3` ✓ |
| `EDR_T1_R2/metric_dsm_elev_colormap.png` | — | Quarto render |
| `EDR_T1_R2/metric_dsm_hillshade.png` | — | Quarto render |
| `EDR_T1_R2/metric_dsm_z_profile.png` | — | Quarto render |
| `EDR_T1_R2/diag_dsm_recentered.tif` | — | diagnostic (pre-AOI full footprint) |
| `EDR_T1_R2/probe_leveled_dsm.tif` | — | frame-verification probe |
| `EDR_T1_R2/diag_cross_track_coherence.png` | — | two-pass seam check |
| `EDR_T1_R2/diag_footprint_by_pass.png` | — | outbound vs return pass |
| `EDR_T3/dsm.tif` | — | T3 shipped product |
| `EDR_T3/ortho.tif` | — | T3 shipped product |

P13HMEON reference TIFs: `data/comparison-only/P13HMEON/` (firewall — never pipeline input).

---

## Open

### NEXT: 0.30 re-run (GO pending) → reconcile pipeline

Active branch: `main` (267 green). Reconcile branch: `feat/reconcile-r2-transect` (EC2).

- [x] **frame_retention ✓** — `QCValidator` outcome criterion (ADR-0034): observed = 1 − disabled/analyzed, pass ≥ 0.60; closes corpus-blind `ALARM_MAX_DISABLED` gap. Merged to main.
- [x] **Blocker-1 ✓** — `esm.report` written + persisted to chunk.meta after all exports; `scale` tracked in PIPELINE_STAGES + STAGE_ORDER; `ProcessingManifest.from_esm_report()` loader; QC chain proven on real R2 q050 (3 honest failures: frame_retention 0.485, registration 0.482, scale_bar 4.4 mm). Merged to main.
- [ ] **0.30 re-run on R2** — re-run `stage_step4` on `edr_r2.psx` with `--quality-threshold 0.30` (ADR-0017 floor) then re-align; **explicit GO required** (re-align is compute). Expect frame_retention + registration both pass; dense/DSM untouched.
- [ ] **stage_dsm export** — `esm.dsm` already written by stage_dsm; wire sha256 + coverage fields so manifest is fully populated for empirical QC pass.
- [ ] **Empirical pass** — run `QCValidator` against R2 manifest from real 0.30-run `esm.*` meta; confirm all outcome gates pass.
- [ ] **Reconcile + CLI/README/docs** — rugosity, VRM, elev-relative-to-min on R2 metric DSM (`620bc3bc`) vs pinned P13HMEON R2 confidence-filter row (ADR-0015 match); close ADR-0033 marker 25–26 item (pending Frank); CLI entry point + docs pass.

### Blockers (pipeline — remaining)

**Blocker 2 — hemisphere flip alarm missing:**
- `stage_level` camera-nadir collinear path has no alarm when flip angle > 90°.

### Non-blocking follow-ups

- `fix/probe-topo-gates`: recalibrate `total_tilt` (8.71° fails 6.0° flat-belt threshold), camera-Z, and cameras-above-markers gates for topo transects. `footprint_explained_var` None-guard (`0bfb4c3` on `fix/level-camera-nadir`) is untested — split to this branch with a RED test before merging.
- `feat/aoi-dsm-postdense`: untethered from production stages; reconcile or retire.
- `buildDem` hang root cause open for full-area T1 DEM (3 confirmed hangs on 487M pts).
- Suite: 267 green. CLI pending.

**FIREWALL P13HMEON comparison-only. Dense runs only on explicit GO.**
