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

EDR_T3 shipped + gate-passing. **EDR_T1: reduce is BLOCKED on an `optimizeCameras`
datum divergence** (full detail + datum dump: `docs/session-log-2026-06-08.md`
EVENING entry; ADR-0023 addendum). State: align → markers PASS (human-corrected, 4
bars) → scale (bars @ 0.001) done; **reduce blocked**. The model is safe on disk
(`edr_t1.psx` mtime **19:00**, 0 SaveProject, 0 esm.reduce); all work since was on
scratch copies.

**The blocker:** one `optimizeCameras` on post-scale T1 **diverges** — reproj median
0.15 → 14–19 px, `transform.scale` 1.0 → **823.77**, max → 1.3e152 — which hangs
Logan's reduce. **Bar-independent** (the scale-bar over-constraint hypothesis was
FALSIFIED: a bars-disabled control diverged too). **Root (per the read-only datum
dump):** the chunk is in a **spurious WGS84/EPSG:4326 (degrees) CRS** (ADR-0018/0020,
here in the *optimize* path) with every camera carrying a single-fix lat/lon
reference and every marker carrying enabled **garbage WGS84 reference coords** (auto-
populated when markers were added to a WGS84 chunk after align); `optimizeCameras`
refits the datum to that degree-space garbage and diverges.

**Resume point (next session, short CPU-only burst):** 2-arm A/B on COPIES with
**Logan's exact `optimizeCameras` call** — Arm A datum as-is (expect diverge) vs Arm
B **local metric CRS (ADR-0020 lever) + camera/marker references cleared** (expect
clean). If B is clean → fix = neutralise the datum (local metric CRS + strip the
spurious WGS84 refs) **before** reduce (likely in `stage_scale`/pre-reduce). The
committed reduce mode is **vendored 2.x Logan + `compute_rmse=False`** (correct +
tested; independent of this blocker). Don't re-run reduce until the datum A/B picks
the root. No dense without explicit GO.
