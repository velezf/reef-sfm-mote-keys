# Session log — 2026-06-05 (Chat-5, mid): `stage_markers` design + gate calibration

**Status: BUILD COMPLETE — STOPPED for review (no commit yet). The on-disk projects
(`edr_t1.psx`, `edr_t3.psx`) are UNTOUCHED — verification was read-only; the stage itself
(which saves/escalates) was NOT run on them. No scale, no dense.**

## ✅ DELIVERED THIS SESSION (the build below was implemented; design notes follow as record)

Gate-(b) decision was settled by the resume directive (median post-align reprojection residual,
loose 2.0 px ceiling, **no in-gate optimize**, count = evidence only) — so I did not re-ask.

- **`scripts/metashape/run_pipeline.py`** (uncommitted):
  - Pure, Metashape-free gates: `_propose_bars_by_adjacency`, `gate_parity` (a),
    `gate_coherence` (b), `gate_consistency` (c), `validate_markers` (aggregate verdict).
  - `_extract_marker_records` (Metashape, RAW residuals, no optimize) feeds the pure gates.
  - `stage_markers` augmented: skip-if-passed → detect-only-if-no-markers (re-entry validates
    EXISTING set, **no re-detect**) → validate → **PASS** `_emit_validated_scalebars`
    (validated_scalebars.json + headless-pass provenance) / **FAIL** `_write_escalation_report`
    (markers_escalation.json: gate findings + count/coherence evidence + which images each
    suspect marker spans) → save → critical alarm HALTS before scale.
  - New dumb **`stage_scale`**: refuses unless status=headless-pass, builds 25 cm bars for the
    validated pairs, reuses GUI-created bars (idempotent). Wired into `STAGES` (after `markers`),
    `main()`, `report` (two new meta keys), CLI (`--marker-resid-ceiling`, `--interbar-ratio-max`).
  - Constants `GATE_MARKER_RESID_CEILING_PX=2.0`, `GATE_INTERBAR_RATIO_MAX=1.25`.
- **`scripts/metashape/test_marker_validation.py`** (NEW): 21 pure unit tests (stub-Metashape
  loader; pairing, each gate, aggregate; clean→pass, orphan→a, 35%-bar→c, incoherent→b). PASS.
- **`scripts/metashape/probes/stage_markers_verify.py`** (NEW): READ-ONLY harness — opens T1/T3
  `read_only=True`, runs the SAME extract+validate, asserts T3 PASS (4 bars, ratio 1.091) / T1
  ESCALATE (orphans [13,24,26], ratio 1.352, load-bearing 15/16/19/20 flagged). **Ran → PASS,
  no project mutated.** T1 residuals 4.7e4–5.1e10 px, proj counts 111–182, "24 ghost" in 111 cams.
- **Docs:** ADR-0022 (new), index row, `05` Step-7 fidelity row + conditional-GUI narrative + run
  commands + 2 divergence-ledger rows (gate-b coherence + GUI-assign→headless). Full suite 114 PASS.

**Next (separate, gated):** review → commit → the actual T1 production `--stage markers` run will
ESCALATE (correct); a human GUI marker fix + re-validate is the real re-entry test. Dense never auto-starts.

## ✅ HARDENING (2026-06-05, second commit — robustness + tests, no production run)

Build committed clean first (`fb9cf8d`), then hardening as a separate commit. All CPU-cheap.

- **Fail-closed gate (d) sufficiency:** a headless PASS now requires **>= 3 VALIDATED bars** (floor 2 so
  gate (c) has two to compare; 3 = EDR norm). Closes the single-surviving-bar gap (ratio vacuously 1.0).
  `--min-validated-bars`. Gate (c) runs over CANDIDATE bars (preserves T1's 1.352 signal); gate (d) over
  VALIDATED (coherent-endpoint) survivors.
- **Fail-closed everywhere:** degenerate (0/1 marker, all-flagged, 0 bars) → escalate, never emit empty;
  malformed (no-3D-position, single-camera `< 2` rays, **NaN/inf** residual — explicit `isfinite`, since
  `NaN > ceiling` is False) → flagged; any exception in extract/validate → `_write_extraction_failure`
  (`failed_gates:["extraction_error"]`) + halt, never pass. Thresholds inclusive at 2.0px / 1.25 / 3 bars.
- **Provenance integrity:** PASS after a prior escalation recorded distinctly (`marker_source:
  human-corrected`, `human_touch: gui-marker-fix`, `prior_escalation` back-ref) vs zero-touch
  (`headless-auto`). Validation deterministic (byte-identical `validated_scalebars.json`).
- **Transferability (test+note only, NOT built):** consecutive-ID pairing is an assumption; gapped/
  too-few conventions fail closed; configurable pairing is a v2 item (ADR-0022 note).
- **Tests:** +25 (now 51 marker tests; full suite **144 green**). **Regression: re-ran
  `stage_markers_verify.py` read-only — T3 still PASS (4 validated bars), T1 still ESCALATE on a/b/c/d
  (0 validated bars). Nothing mutated.** Docs: ADR-0022 gate-(d)/fail-closed/transferability sections.
  T1 NOT tuned to pass — verified it still escalates after every change.

## ✅ TRANSECT-AGNOSTIC REFACTOR (2026-06-05, third commit — pure code, no compute)

Made the PRODUCTION marker-gate code carry **no hardcoded T1/T3/EDR references** (scope: gates,
validate_markers, stage_markers loop, stage_scale, emit/escalation helpers, _extract_marker_records;
tests/probe/docs allowed to keep T1/T3).
- **Audit:** pairs already derive from DETECTED ids (no hardcoded set). Defects found + fixed: the
  `t3_basis` string baked into `validate_markers` output → generic `calibration_note`; the `0.25 m` bar
  length hardcoded via `PARAMS.scalebar_length_m` → new **`--bar-length`** param (default 0.25) threaded
  to `stage_markers`→emit (records `defined_distance_m`) and consumed by `stage_scale` (applies the
  recorded distance). EDR/T1/T3 mentions in docstrings genericized; constant-comment block now flags the
  **coherence ceiling as most site-dependent** and the **inter-bar ratio as scale-free (generalizes
  as-is)**.
- **Gates stay scale-free** → `--bar-length` cannot move PASS/FAIL (only metric scale).
- **Proof:** new pure FOREIGN-transect tests (IDs 200..205, 3 bars, no EDR in path): clean→PASS,
  orphan→a, +35% bar→c, incoherent→b, sub-min→escalate, custom min-bars=2→PASS; + a loop test that a
  0.5 m `--bar-length` flows markers→scalebar distance. **Suite 151 green.**
- **Regression (read-only):** re-ran `stage_markers_verify.py` — T3 still PASS (4 bars), T1 still
  ESCALATE (0 validated bars, ratio 1.3517). Verdicts UNCHANGED by the refactor. Nothing mutated.
- **v2 (flagged, NOT built):** consecutive-ID pairing convention; `CircularTarget12bit` target type.
  Procedure to recalibrate on another program's known-good transect in `docs/05`.

---
## (original mid-session design record below)
**All work so far is read-only probes — the on-disk projects are UNTOUCHED.**

## Task (this chat)
Build a new headless stage **`stage_markers`** between `align` and scale: it owns coded-marker
detection + validation gating; on PASS it emits a validated scale-bar set that a future **dumb
`stage_scale`** consumes (today scale bars are a GUI step between `markers` and `reduce`; neither
`stage_scale` nor a scale-bar artifact exists yet). Detection is UNTRUSTED → validate via 3 gates,
run ALL then halt if any fail, escalate to human (log + console only; email is v2/out-of-scope).
Re-entry validates EXISTING markers (no re-detect/overwrite). Then test + verify on T1/T3, then STOP
(no scale apply, no dense, no downstream).

**HARD CONSTRAINTS:** (1) FIREWALL — never read P13HMEON to resolve a pairing; T1 reaches a valid
result on its own or escalates. (2) Don't defeat the gate — no tolerance-raising-until-T1-passes, no
eyeballing imagery, no hardcoding T1's "correct" markers; a failing T1 that ESCALATES is correct.
(3) No scale/dense/DEM/ortho. (4) Match existing conventions.

## ⛔ RESUME STEP 1 — resolve the open gate-(b) decision with the user FIRST
I was asking the user to confirm the gate-(b) redefinition (below) and they paused before answering.
Re-ask, then build. Options I presented: **(rec) coherence-residual** / keep-count-floor-too /
stick-to-brief-literally.

## Conform findings (conventions `stage_markers`/`stage_scale` must match)
Source: `scripts/metashape/run_pipeline.py` (2088 lines).
- **Stage signature:** `def stage_x(doc: Document, ignore_sanity: bool, ...) -> None`; loops
  `for chunk in doc.chunks`; idempotent skip via `if _meta_get(chunk,"esm.x") is not None: continue`;
  ends with `save(doc)` (verified-persist — raises if save didn't land; the 2026-06-04 read-only incident).
- **Per-stage stats:** `_meta_set(chunk,"esm.markers",dict)` / `_meta_get`; JSON in `chunk.meta`; the
  `report` stage reads `esm.*` back (add `stage_scale` key there too when built).
- **Logging/alarms:** `log(msg)`; `alarm(msg, critical=, ignore=ignore_sanity)` — critical+not-ignore
  raises `PipelineSanityError`. Escalation should AGGREGATE all gate findings then raise once.
- **Existing `stage_markers` (line 818):** already does auto-tolerance detection (start tol 20, +5 to
  100) + `--expected-marker-ids` identity stop + `unexpected_ids` flag. The new gates AUGMENT this; keep
  the detection path, add validation. `_marker_id(label)` → trailing int.
- **MS idioms:** `chunk.detectMarkers(target_type=Metashape.CircularTarget12bit, tolerance=)`;
  `m.position` (internal/pre-scale), `m.projections[cam]` (`.coord`, `.valid`), `cam.project(pos)` →
  2D px (None if behind); `chunk.scalebars`, `sb.point0/point1`, `sb.reference.distance`. To create a
  bar: `chunk.addScalebar(m_a, m_b)` then set `sb.reference.distance = 0.25`. World dist via
  `_world_xyz(T, p)` with `T=chunk.transform.matrix`. No numpy; Jacobi eigensolver already in file.
- **Driver:** `STAGES` list (line 1944) + `main()` dispatch (line 2063). Add `"scale"` after `"markers"`.
  CLI already has `--expected-marker-ids`, `--expected-markers`, `--ignore-sanity`, `--verify`.
- **Provenance:** per-transect `data/provenance/<T>/*.json`; `report` writes `pipeline_summary.json` +
  per-chunk products to `--out-root`. `scalebars.json` schema =
  `[{label, defined_distance_m, accuracy_m}]`.

## Calibration data (from read-only probes — UNCOMMITTED)
Probes: `scripts/metashape/probes/marker_validation_calib.py` (per-marker proj count, robust px
residual min/median/p90/max, internal-unit pairwise + ID-adjacent bar lengths) and
`marker_optimize_experiment.py` (optimize-in-memory, never saves). Run:
`/opt/metashape-pro/metashape.sh -platform offscreen -r <probe>.py /data/edr_work/<proj>.psx`.

- **T3** (`edr_t3.psx`, codified/optimized/scaled): 8 markers, 4 bars {13-14,15-16,19-20,25-26}.
  Proj 5–30. Median resid **0.10–0.38 px** (max 0.62). Bar lengths (internal u): 1.03474 / 1.025705 /
  1.035706 / 1.118892 (25-26 = real-but-noisy +8% bar, the one `stage_level` MAD-excludes). 4-bar
  max/min ratio **1.091**.
- **T1** (`edr_t1.psx`, aligned only; 7 markers {13,15,16,19,20,24,26}; NO scalebars; transform_scale
  null): proj **111–182**. ID-adjacent bars 15-16=31.88, 19-20=43.09 → ratio **1.352**. ALL markers
  reproject to garbage (median **2,246 → 4.7e10 px**); `optimizeCameras` does NOT fix (tie-RMS fine
  0.185; markers aren't constraints w/o scale bars). Whole coded layer is geometrically incoherent.

### ⚠ Key finding — brief's gate-(b) premise is FALSE on this data
"Mis-decodes sit in a handful of cameras at high residual" does not hold: the 24 "ghost" is in **111
cameras** and is one of the **cleanest** T1 markers by residual (5.8k px). Projection count is
non-transferable (T3 5–30 vs T1 111–182 → any fixed floor vacuous). → Gate (b) redefined to
reprojection COHERENCE (transferable, scale-free). DIVERGENCE-LEDGER entry.

## The 3 gates as designed (cheapest-first; run all, aggregate, then halt)
- **(a) parity/orphans:** ID-adjacency proposes bars (consecutive IDs); FAIL on odd count or any
  unpaired marker. T1→FAIL (orphans 13,24,26; odd 7). T3→PASS.
- **(b) detection confidence = reprojection coherence:** robust (median) px residual ≤ ceiling
  **2.0 px** (T3 true-marker max median 0.378 ×~5). Flag markers above; FAIL if a flagged marker is
  load-bearing for a proposed bar. **Projection-count floor DROPPED to evidence-only** (reported in
  escalation, per brief). T3→PASS (all ≤0.38), T1→FAIL (all ≫2). Keeps T3's real-but-sparse #26.
- **(c) inter-bar consistency:** candidate-bar max/min length ratio ≤ **1.25** (T3 1.091 PASS, T1 1.352
  FAIL). Pre-scale, internal units (ratio scale-invariant — do NOT convert to metres).

## On PASS / On FAIL contracts (to implement)
- PASS: emit validated scale-bar set (marker pairs + measured local lengths + metadata) as the artifact
  `stage_scale` applies. Provenance: transect, status=`headless-pass`, detected IDs, proposed pairs, all
  3 gate results w/ values, tolerance + T3 basis, human-touch=none, input project hash, timestamps.
- FAIL: halt before scaling. Structured report (log+console): failed gate(s), all detected IDs,
  candidate bar lengths, inter-bar disagreement, per-marker projection counts, and which images each
  suspect marker appears in (from our own detection). Provenance: status=`escalated/awaiting-manual`,
  same evidence. Re-entry: human fixes markers in GUI + saves → re-run `stage_markers` → gates
  re-validate → on pass the set flows to `stage_scale`.

## Remaining steps
1. Resolve gate-(b) decision with user (above). 2. Build `stage_markers` (augment) + `stage_scale`
(dumb) + wire `STAGES`/`main()`/`report`. 3. pytest synthetic fixtures (clean→pass; orphan→a; 35%
bar→c; incoherent-marker→b) + integration (T3 PASS emits 4-bar set; T1 ESCALATE naming 13/24/26,
24's 111-proj, 15-16 vs 19-20). 4. Short docs/ (likely new ADR-0022 + a section in 05) — contract,
3 gate defs, T3-calibration basis + the falsified-heuristic divergence. Then STOP for review.

## Env reminders
Repo `/data/reef-sfm-mote-keys` (branch main, no push). Work `/data/edr_work`. Metashape headless
`/opt/metashape-pro/metashape.sh -platform offscreen -r ...`; bundled python has NO numpy. Probe
output is block-buffered (won't show until process exits). T1 align+markers already COMPLETE+verified.
