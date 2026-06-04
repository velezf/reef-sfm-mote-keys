# EDR_T3 re-level — GROUND TRUTH probe (Chat 5.7, 2026-06-04, read-only)

Read-only Metashape inspection of the pristine project and the validated PASS copy, run at the start of
Phase B to ground the `stage_level`/`stage_aoi` codification in actual stored numbers (not the resume
prose). Nothing was mutated; both projects opened `read_only=True`, never saved.

## Integrity (re-verified)
- Pristine `/data/edr_work/edr_t3.psx` sha256 `ed86a3b4…80182f` — UNCHANGED from the recorded value.
- Repo HEAD `3776e0b`. Tag `chat5-day1-stop-20260602` present.
- **Correction to the inbound summary:** the tag `chat5-day3-stop-20260603` did NOT exist on disk and
  the day-3 re-level work (this QC dir + resume doc) was UNTRACKED. This commit lands + tags it.
  Resume doc is `data/qc/chat5/RESUME_day3_relevel_20260604.md` (the summary's `docs/SESSION-RESUME…`
  path was wrong).

## The dense → filter → crop chain (CORRECTED)
A first read of point counts suggested Step-13 was skipped; `chunk.meta` proves otherwise:
- `esm.dense` raw dense = **22,683,375** pts (High, Mild).
- `esm.filter` (confidence < 2) removed 5,163,725 (22.76%) → **17,519,650** pts. This is what the
  pristine copy stores as its `point_cloud` (dense + filter already applied & preserved).
- AOI crop (manual PASS) → **16,110,912** pts (an 8% crop of the post-filter cloud, NOT a re-filter).
- Production chain is therefore `dense → filter → aoi-crop → dsm → ortho`, and the manual PASS followed
  exactly that. A fresh pristine copy already carries the preserved post-filter cloud, so `dense` and
  `filter` self-skip and the T3 validation subset is genuinely `level → aoi → dsm → ortho` (no re-dense,
  no re-filter).

## Stored ground truth
| | pristine `edr_t3.psx` | `edr_t3_relevel_final.psx` (PASS) |
|---|---|---|
| chunk.crs | WGS 84 (EPSG:4326) | LOCAL (m) |
| transform.scale | 0.236959158540559**85** | 0.236959158540559**88** (preserved, Δ ~1e-16) |
| point_cloud | 17,519,650 (post-filter) | 16,110,912 (cropped) |
| DSM / ortho | none | 1000×100 @ 1cm / 1999×200 |
| transform | day-1 AlignmentHelper frame (24.26° tilt) | vetted-6 plane-leveled + framed |
| region.rot | non-identity | non-identity (different) |

- **Marker internal coords are bit-identical** pristine↔PASS (e.g. marker 20 differs only at ~1e-15).
  Leveling/framing changed ONLY `chunk.transform`, `chunk.crs`, `region`, and the dense crop — the
  fit inputs are pristine-preserved and deterministic. This is what makes a deterministic recompute
  feasible.
- Scale bars: 4 pairs `{25/26, 13/14, 15/16, 19/20}`, all 0.25 m. 25/26 is the residual outlier
  (+15.13 mm / +6%) → vetted-6 = `{13,14,15,16,19,20}`.

## Recon-check reference values (from the pilot QC JSONs, durable)
- Vetted-6 LS-plane normal (pristine-world frame): `[-0.19, -0.3302, 0.9246]`, 22.39° off current Z.
- Level method (`relevel_phase1_diagnosis.json`): LS plane to vetted-6 → rotation R mapping normal→Z →
  apply to `chunk.transform` (orientation only); scale preserved; region reset to 10×1×5 m. This is
  exactly the `stage_level` design.
- The DAY-1 FAILED transform (regression-test input) = pristine's current `chunk.transform`
  (`edr_t3_step11_frame_after.json` → identical matrix). Feeding it to the gate must TRIP check #2.
- Validated PASS metrics (`edr_t3_relevel_final_gate.json` → `phaseA2_footprint_framed_result`):
  DEM 1000×100 @ 1cm, coverage interp-OFF 96.7%, tilt interp-OFF long 0.40° / cross 2.19° / total 2.23°
  (interp-ON 1.88°), co-reg dx=dy=0, scale preserved, footprint explained-var 0.988 / aspect ~8:1.

## OPEN question for the recon-check (resolve empirically, do not guess)
relevel_final's `region.rot` is non-identity yet its DSM is a clean axis-aligned 1000×100. So the AOI
yaw may live in `chunk.transform` (then region is an axis-aligned box) OR in `region.rot` (with the
Planar projection picking it up). The read-only recon-check recomputes R (level) and the AOI region from
the markers/footprint and diffs against the STORED transform+region — that diff settles where the yaw
lives and whether the recompute reproduces the artifact (bit / epsilon / structural).

## Provenance note
The pilot scripts (`relevel_complete.py`, `a2a_rollpitch.py`, `a2b_frame.py`, `gate_relevel_final.py`)
were written to `/tmp` and are UNRECOVERABLE (ephemeral; confirmed absent). The recipe survives only as
prose (resume doc), these QC JSONs, and the PASS artifact's stored transform/region. This is why the
Phase-C acceptance bar is functional-equivalence (determinism + gate-vs-P13HMEON), not bit-identity to
the manual artifact. The vendored day-1 tool is `vendor/usgs/AlignmentHelper_v1.py` (Step-11 divergence
ledger source).
