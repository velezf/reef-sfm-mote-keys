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

## Current state / resume pointer (2026-06-04)

EDR_T3 shipped + gate-passing. **EDR_T1:** import/step4 done; the first detached
align run was lost to the stale-lock/read-only bug above, then recovered (lock
cleared) and the launcher+pipeline hardened (commit `a076af0`). The lost in-memory
align was excellent (99.6% / 10.67M tie points / RMS 0.2322) so params are sound.
**Resume point:** kick off the hardened `align → markers` detached (tmux `t1align`
→ `run_t1_align_markers.sh`), expect ≈99.6%, STOP at the pre-dense stop, and report
**belt-or-not** (gate #6 aspect), **marker IDs + 0.25 m scale-bar pairs**, and
align quality. Then: Part-B robustness/spot layer is still to build (surface the
dense on-demand-vs-spot tradeoff and stop for a call). Full handoff +
exact commands: `docs/session-log-2026-06-04.md` (CLOSE-OUT block at top).
