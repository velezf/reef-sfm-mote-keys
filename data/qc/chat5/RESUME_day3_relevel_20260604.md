# RESUME — EDR_T3 re-level (Chat 5, day-3 stop @ Phase A PASS)

**Date:** 2026-06-04. **Repo HEAD:** `3776e0b` (ADR-0020 + run_pipeline.py dsm/ortho fix; no push since).
**Stopped at:** end of Phase A (re-level complete + gated PASS). Phases B/C/D PENDING.

## Headline
The day-1 24.26° leveling error is FIXED on a copy. Re-leveled DEM/ortho now gate PASS:
tilt **1.88°** (long +0.40, cross +1.83), coverage interp-OFF **96.7%**, co-reg **dx=dy=0**,
scale 10.00 m exact, roughness 0.092 m ≈ reference raw 0.08–0.10 m, DEM **1000×100** extent
[-5,5]×[-0.5,0.5]. **NOT promoted/exported** — copy only.

## Integrity (verified)
- Pristine `/data/edr_work/edr_t3.psx` sha256 `ed86a3b4…80182f`; `.files` byte-identical to backup
  `edr_t3_20260602T160517Z` (14 files, 1,051,623,966 B). Tag `chat5-day1-stop-20260602`. UNTOUCHED.
- Completed re-level COPY: `/data/edr_work/edr_t3_relevel_final.psx` (the PASS artifact; disposable).
  Intermediate copies `edr_t3_relevel.psx` (leveling-only), `edr_t3_pipevalidate.psx` also exist.

## The validated method (this is what Phase B must codify as stage_level)
Two SEPARATE references — this was the key lesson:
1. **LEVEL PLANE = markers.** Robust plane fit to scale-bar markers with outlier rejection
   (scale-bar residual MAD z>3.5 auto-excludes the 25/26 pair, +15.13 mm/+6%). Rotate plane
   normal → world Z (roll+pitch). Scale preserved. Gives tilt 24.26°→~1.9° (long flat; cross
   ~2° is the marker-Y-spread 0.85 m precision floor — DOCUMENTED, do not chase sub-2°).
2. **AOI PLACEMENT = dense footprint, NOT the markers.** Markers 14/20 sit ~0.52 m off-center
   and ~3° angled vs the reef band, so a marker-placed 10×1 box clips it (was 48% coverage).
   Fix: yaw-align to the dense-footprint PCA major axis (−2.03°, heading +X toward marker 20),
   center on the footprint centroid, then 10×1×5 crop. → 96.7% coverage.
   Footprint is a clean band: explained-var 0.988, aspect 8:1, uniform ~1 m width.

Scripts (in /tmp, ephemeral — recipe above is durable): `relevel_complete.py` (full method, but
its in-script coarse-DEM footprint step needs chunk.crs LOCAL set FIRST or it WGS84-OOMs — bug
hit and worked around), `a2a_rollpitch.py`, `a2b_frame.py`, `gate_relevel_final.py`, `frame.json`.
Footprint measured via a 5 cm interp-OFF coarse DEM (crs LOCAL) → PCA in venv.

## Gate artifacts (data/qc/chat5/)
`edr_t3_relevel_final_gate.json` (PASS), `…_gate.png`, `…_dsm.tif`, `…_ortho_preview.tif`,
`…_dsm_interpOFF.tif`, `…_geo.json`, `edr_t3_relevel_phase1_diagnosis.json`, `edr_t3_tilt_check_*`.
Reference DEMs (GATE only, never leveling input): `data/raw/P13HMEON/20230711_T3_{C1,R1}_DEM_canopy.tif`.

## PENDING (next session) — Phases B/C/D
- **B — codify stage_level** in run_pipeline.py: (a) markers→level plane (robust outlier reject),
  (b) dense-footprint PCA→AOI yaw + centroid→AOI center + 10×1 crop. Wire PERMANENT QC gate
  (long-axis flat; total tilt < gross-mislevel bound but tolerating the Y-spread cross floor;
  coverage ~97%; scale preserved; co-reg dx=dy=0) + reference-patch overlap check where a ref
  exists (gate, never input); core gate self-contained for ref-less sites. Decide insertion point
  (before dsm/ortho; after markers/reduce) and level-before-dense vs after-dense+filter (reason
  from actual run_pipeline.py structure; T3 is dense-first). Commit.
- **C — validate**: pipeline-built == this manual A2b result (bit-identical preferred, report
  max_abs_diff); confirm wired gate WOULD FAIL on the day-1 tilted transform (regression). No re-dense.
- **D — product/export MANDATORY STOP**: on user go, promote edr_t3_relevel_final → working
  (backup+tag first), exports (DSM/ortho TIFF, sparse+dense PLY, camera-poses json, scale-bar list,
  report json+html), provenance manifest, EBS snapshot, docs/05, commit. A3 also wanted a
  reference-patch overlap sanity (same physical reef) — still TODO at the gate.

## Guardrails (unchanged)
Pristine untouched; copy-only; backup+tag before any working write; NO re-dense; reference
gate-only NEVER leveling input; deterministic outlier-rejecting plane fit; preserve 10.00 m scale;
no fabrication. Trial expires 2026-06-26 (ample). "Constructs cleanly ≠ projects correctly."
