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

## Working agreement

Gates, TDD and commit format: `~/.claude/CLAUDE.md`. Cross-project conventions
(cite, don't restate; the hollow-check failure class, of which the 2026-06-04
sentinel incident above is an instance): `~/code/CLAUDE.md`. Authorities for
literal values here: `docs/decisions/` (ADRs), `docs/05-metashape-processing.md`
(processing doc, divergence ledger, incident log), `docs/aws-resources.md` (AWS
inventory), `MANIFEST` (artifact sha256s).

**To resume work, read `docs/RESUME.md` first**: current state, T1 and T1_R2
product tables, ADRs in effect, EBS snapshots, local products, open items, and
session state.

## Hard constraints

- `edr_r2.psx` = q050 foil (in EBS snapshot): **NEVER WRITE OR OPEN.**
- `edr_r2_q030.psx` = source (in EBS snapshot): never write.
- **P13HMEON is comparison-only** (firewall `325dbc7`): never a construction input,
  never an AOI. Reference TIFs: `data/comparison-only/P13HMEON/`.
- EC2 is decommissioned (2026-06-23); no live instance. All compute restores from
  EBS snapshots + AMI listed in `docs/RESUME.md` and `docs/aws-resources.md`.
- **Dense runs only on the user's explicit GO.**
- Verify every artifact from disk; agent self-reports are hypotheses.
