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

## Current state / resume pointer (2026-06-09)

EDR_T3 shipped + gate-passing. **EDR_T1:** markers PASS → scale applied (mtime
2026-06-08 19:00:00 UTC, backups preserved). **BLOCKER resolved (ADR-0024):**
`optimizeCameras` diverged in the reduce path (scale 1.0→823.77, reproj 0.15→
1.3e152 px) — root: spurious WGS84 CRS + identity transform caused `updateTransform`
to write garbage GCP reference locations to all 8 markers (lat≈-90°, alt≈-6.36e6 m,
enabled=True). Scale-bar hypothesis falsified. **Fix committed** in `stage_scale`:
`_neutralize_spurious_reference` sets LOCAL_CS + disables all marker/camera
reference.enabled (scale bars untouched). Shared `_LOCAL_CS_WKT` constant with
ADR-0020 DEM path. **90 tests green.** A/B confirmed (copies only): Arm A scale
1.0→823.77 / reproj→1.3e152 (blowup); Arm B scale~0.153 / median~0.15 px (holds).

The committed reduce mode is **vendored 2.x Logan + `compute_rmse=False`** (correct +
tested; avoids 2.3.1 camera.error-None crash; ADR-0023).

**Next gated step (on explicit go):** the LIVE model is post-scale WITHOUT the fix
(stage_scale ran before ADR-0024). Must re-run from the pre-scale backup:
```bash
# 1. Restore from edr_t1_preSTEP5_20260608T185845Z (pre-scale checkpoint)
# 2. Re-run: --stage markers (re-validate) → --stage scale (commits LOCAL_CS fix) →
#            --stage reduce (vendored Logan; ~10+ min) → --stage level
# 3. Run probes/t1_postlevel_probe.py and report quality
# 4. STOP before dense
```
Full session log: `docs/session-log-2026-06-09.md`.

**Dense runs only on explicit go. FIREWALL P13HMEON comparison-only.**
