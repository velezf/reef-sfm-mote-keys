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

## Current state / resume pointer (2026-06-10 EOD)

EDR_T3 shipped + gate-passing. **EDR_T1 post-filter; AOI/DSM/ortho ADRs accepted; ready for products phase.**

| stage | status | notes |
|-------|--------|-------|
| markers | PASS | |
| scale | PASS | ADR-0024: LOCAL_CS + refs disabled; scale 0.15246 m/unit |
| reduce | PASS | ADR-0023 vendored Logan; 3,568,318 tie pts; sigma0 0.159 |
| level | PASS | ADR-0025 camera-nadir UP (collinear markers); 14.78 m Z = genuine topo |
| region | SET | 28.92 × 25.41 × 15.33 m; coverage 99.82% |
| dense | PASS | 651,419,413 pts; 2.8 h; rc=0 (2026-06-10T13:35Z) |
| filter | PASS | ADR-0015: 651M → 488M (25.1% removed, threshold=2); rc=0 |
| aoi | PENDING | ADR-0026 ACCEPTED — box computed; needs wiring into stage_aoi before run |
| dsm | PENDING | ADR-0027 ACCEPTED — 1 cm; no code change needed |
| ortho | PENDING | |

**Snapshots on disk (EC2 `/data/edr_work/`):**
- `edr_t1_postdense_20260610T181702Z.{psx,files}` — 27 GB; post-dense, pre-filter (safety copy)
- `edr_t1_postlevel_adr0025_20260609T220420Z.{psx,files}` — post-level, pre-region
- Live project: `edr_t1.psx` — post-filter state; `next_stage=aoi`

**NEXT ACTION (explicit go required):**
Wire ADR-0026 AOI box into `stage_aoi`, then run `--stage aoi` (and continue through dsm → ortho → gate → report).

**AOI box (ADR-0026 — chunk CRS, LOCAL_CS metres):**
- centre: (−2.028, 3.774, −6.477)
- long axis (10 m): (−0.7071, 0.7071, 0) — 135° bearing
- short axis (1 m): (−0.7071, −0.7071, 0) — 225° bearing
- half-extents: (5.000, 0.500, 3.500) m; full box 10 × 1 × 7 m
- Z window: [−9.977, −2.977] m (7 m, est. 5.4 m local relief + 29% margin)
- `stage_aoi` auto-gate WILL HALT (aspect 1.14:1 < 5:1) — manual override required

**ADRs in effect:** ADR-0023 (Logan reduce), ADR-0024 (LOCAL_CS), ADR-0025 (camera-nadir level),
ADR-0026 (T1 AOI placement — 10×1×7 m manual transect), ADR-0027 (DSM 1 cm — no code change)

**Open follow-ups (not blocking products):**
- `fix/probe-topo-gates`: recalibrate camera-Z, cameras-above-markers, and region-bounds gates for topo transects
- Blocker 1: add `scale` to `spot_controller.sh` PIPELINE_STAGES + `pipeline_state.py` STAGE_ORDER; add `_meta_set(chunk, "esm.report", ...)` to `stage_report`
- Blocker 2: add hemisphere-flip critical alarm in camera_nadir collinear path

**Products run only on explicit go. FIREWALL P13HMEON comparison-only.**
