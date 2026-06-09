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

## Current state / resume pointer (2026-06-09 EOD)

EDR_T3 shipped + gate-passing. **EDR_T1 FULLY PREPPED FOR DENSE:**

| stage | status | notes |
|-------|--------|-------|
| markers | PASS | |
| scale | PASS | ADR-0024: LOCAL_CS + refs disabled; scale 0.15246 m/unit |
| reduce | PASS | ADR-0023 vendored Logan; 3,568,318 tie pts; sigma0 0.159 |
| level | PASS | ADR-0025 camera-nadir UP (collinear markers); boresight 0.00°; **ACCEPTED — 14.78 m Z range is genuine depth-gradient topography** |
| region | SET | X 28.9 m / Y 25.4 m / Z 15.3 m; coverage 99.82%; deep extension preserved |

**Snapshots on disk (EC2 `/data/edr_work/`):**
- `edr_t1_postlevel_adr0025_20260609T220420Z.{psx,files}` — post-level, pre-region
- `edr_t1_preregion_20260609T220902Z.{psx,files}` — pre-region write guard

**NEXT ACTION (explicit go required):**
```bash
# Dense: High quality / Mild filtering / colors + confidence / ALLOW_DENSE + post-dense HALT
# AOI crop before DSM is MANDATORY — loose region (~29×25×15 m) will OOM without crop
```

**ADRs in effect:** ADR-0023 (Logan reduce), ADR-0024 (LOCAL_CS fix), ADR-0025 (camera-nadir level — accepted)

**Follow-ups (not blocking dense):**
- `fix/probe-topo-gates`: recalibrate camera-Z and cameras-above-markers gates for topo transects
- Push `fix/level-camera-nadir` to remote (Frank's call)
- Merge `fix/level-camera-nadir` → main after dense + products validate full T1 path

**Dense runs only on explicit go. FIREWALL P13HMEON comparison-only.**
