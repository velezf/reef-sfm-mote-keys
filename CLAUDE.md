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

## Current state / resume pointer (2026-06-10 EOD — Chat 5 COMPLETE)

EDR_T3 shipped. **EDR_T1 products COMPLETE. EC2 instance stopped after Chat 5.**

### T1 product table

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

### ADRs in effect (Chat 5)

| ADR | Decision |
|-----|----------|
| ADR-0023 | Vendored Logan reduce |
| ADR-0024 | LOCAL_CS in stage_scale |
| ADR-0025 | Camera-nadir leveling |
| ADR-0026 | ~~Original T1 AOI Z window~~ **SUPERSEDED by ADR-0028** |
| ADR-0027 | DSM at 1 cm |
| ADR-0028 | Corrected Z window [−9.2, +1.8] m, surface-median-anchored. Surface is trough-to-crest (shoulder ~−2.1 m / trough ~−5.2 m / crest ~−0.7 m), NOT a uniform slope. Prior truncation: 2.58 m → 10.00 m DSM; coverage 16.3% → 97.1%. |
| ADR-0029 | Full-area ortho built PointCloudData-direct (not DEM→ortho). `buildDem` hangs on 487M-pt cloud in Metashape 2.3.1 (3 confirmed runs). Portfolio visual only — NOT the ESM Step-15 product. Transect ortho IS DEM-sourced (compliant). |

### Snapshots on disk (EC2 `/data/edr_work/`)

- `edr_t1_postdense_20260610T181702Z.{psx,files}` — 27 GB; post-dense, pre-filter (pristine)
- `edr_t1_postlevel_adr0025_20260609T220420Z.{psx,files}` — post-level, pre-region (pristine)
- `edr_t1_truncated_adr0026v1_20260610T232809Z.{psx,files}` — post-truncated run (ADR-0026 v1; for ADR supersede record)
- Live project: `edr_t1.psx` — post-products state (aoi/dsm/ortho with corrected Z window)
- **EBS snapshot:** `snap-034d45019a4e39c43` — tag `edr_t1_postproducts_20260610T235019Z`

### Local products (Mac `products/EDR_T1/`, gitignored)

| file | sha256 | MANIFEST |
|------|--------|---------|
| `edr_t1_transect_dsm_20260610T234951Z.tif` | `9cc8eb75…` | `618f325` ✓ |
| `edr_t1_transect_ortho_20260610T234951Z.tif` | `e86deb03…` | `618f325` ✓ |
| `edr_t1_fullarea_ortho_20260610T210155Z.tif` | `e03dbf7e…` | `a9337f3` ✓ |

P13HMEON reference TIFs: `data/comparison-only/P13HMEON/` (firewall — never pipeline input).

---

## Open for Chat 6

**EC2 is STOPPED. Chat 6 runs Mac-local.**

### Blockers (fix before QC/reconcile layer)

**Blocker 1 — stage_report exits-3 false-fail:**
- Missing `esm.report` metadata key in chunk (stage_report reads it but no stage writes it)
- `scale` stage is absent from `spot_controller.sh` PIPELINE_STAGES and `pipeline_state.py` STAGE_ORDER
- Fix: add `_meta_set(chunk, "esm.report", ...)` to whichever stage produces the final report inputs; add `scale` to the controller stage list.

**Blocker 2 — hemisphere flip alarm missing:**
- `stage_level` camera-nadir collinear path has no alarm when the flip angle exceeds 90° (other-transect case).
- Fix: add hemisphere-flip critical alarm in `camera_nadir` collinear path.

### Non-blocking follow-ups

- `fix/probe-topo-gates`: recalibrate `total_tilt` gate threshold for topo transects (8.71° fails a 6.0° threshold sized for flat belts); also recalibrate camera-Z and cameras-above-markers gates.
- `feat/aoi-dsm-postdense`: untethered from production stages; reconcile or retire.
- `buildDem` hang root cause open: full-area DEM never built (3 confirmed hangs). Options: coarser resolution (≥ 5 cm), chunked export + external DEM, or Metashape update.
- Push `docs/aws-resources.md` decision: file is tracked in git and contains EIP, ENI MAC, instance ID — review before push.

### Chat 6 scope

`src/reef_sfm_provenance/` Python package (Mac-local, EC2 stopped):
- **Intake validator** — image manifest + EXIF/CSV cross-check (ESM Steps 1–4)
- **Processing-manifest parser** — reads the Metashape PDF/HTML report + `esm.*` chunk metadata
- **QC validator** — ESM Step 8 targets (reprojection RMS, tie-point count, camera coverage)
- **Metric reconciliation** — rugosity / VRM / mean-elevation on the 1 cm transect DSM vs P13HMEON EDR values (`data/comparison-only/P13HMEON/`; comparison-only, never pipeline input)
- **pytest** + CLI
- Runs Mac-local; EC2 stays stopped unless a re-run is needed.

**FIREWALL P13HMEON comparison-only. Dense runs only on explicit GO.**
