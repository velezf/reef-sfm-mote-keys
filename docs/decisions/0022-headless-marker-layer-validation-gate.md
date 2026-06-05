# ADR 0022 — Headless marker-layer validation gate (`stage_markers` a/b/c) + dumb `stage_scale`, with a fail-early → GUI → re-enter loop

Status: Accepted
Date: 2026-06-05
Chat: 5 (mid) — headless marker validation
Related: ADR-0021 (`stage_level`/`stage_aoi` + permanent gate), ADR-0017 (Step-7 marker stage,
auto-tolerance detection), ADR-0010 (ESM Table S2 binding)

## Context

`stage_markers` (ADR-0017) detects coded targets headless with auto-tolerance, but **detection is
untrusted** and the next step — assigning 0.25 m scale bars to marker pairs — was a manual GUI touch.
Scale bars are load-bearing: they fix the metric scale the whole product inherits and feed
`stage_level`'s plane fit. A wrong layer (a mis-decode, a spurious detection, an ID reused across the
belt) silently corrupts scale and level. We need a **headless go/no-go between align and scale**: is the
auto-detected layer good enough to scale without a human? If yes, scale headless; if no, fail early and
queue a GUI touchpoint, then re-enter the headless path after the fix.

Read-only probes on the two real projects (`marker_validation_calib.py`, `marker_optimize_experiment.py`;
session-log 2026-06-05) calibrated this:

- **EDR_T3** (known-good, codified, scaled): 8 markers, 4 consecutive-ID bars {13-14, 15-16, 19-20,
  25-26}, per-marker median reprojection residual **0.10–0.38 px**, projection counts 5–30, inter-bar
  local-length ratio **1.091**.
- **EDR_T1** (aligned only): 7 markers {13, 15, 16, 19, 20, 24, 26}, **no even pairing** (orphans 13, 24,
  26), the two ID-adjacent bars 31.88 vs 43.09 → ratio **1.352**, and **every** marker reprojects to
  garbage (median 5.7e3 – 5.1e10 px). The whole coded-target layer is geometrically incoherent — the same
  ID is decoded at multiple physical points across the 10 m belt (reflective-sand mis-decodes and/or ID
  reuse), each ID landing in **111–182 frames** spanning the transect vs T3's 5–30 tightly clustered.

A premise in the original brief was **falsified by this data**: "mis-decodes sit in a handful of cameras
at high residual." They do not — T1's "24 ghost" sits in **111 cameras** and is one of the *cleanest* T1
markers by residual. **Projection count is non-transferable** (T3 5–30 vs T1 111–182); any fixed count
floor is vacuous. So count is **evidence, not a fail-criterion**.

## Decision

### Three gates on the marker layer (run all, aggregate, then halt)

Pure functions over per-marker records (`validate_markers`), Metashape-free and unit-tested
(`test_marker_validation.py`); the Metashape-touching half is confined to `_extract_marker_records`.

- **(a) parity / orphans.** Pair markers by **consecutive-ID adjacency** (EDR bars join 13-14, 15-16,
  …). FAIL on an odd marker count or any orphan (a marker with no consecutive partner). T1 → FAIL
  (orphans 13/24/26, odd 7). T3 → PASS.
- **(b) reprojection coherence.** Robust (median) per-marker reprojection residual in **pixels**, read
  **RAW from the post-align solution** with a **loose ceiling (2.0 px)**. Flag any marker over the
  ceiling; FAIL only if a flagged marker is **load-bearing** for a proposed bar (a flagged orphan is
  already gate (a)'s, and is reported as evidence, not double-counted). T3 → PASS (max 0.38, ~5× margin);
  T1 → FAIL (load-bearing 15/16/19/20 all ≫ ceiling, ~1000× past).
- **(c) inter-bar consistency.** Candidate-bar **max/min local-length ratio ≤ 1.25**. Computed in
  internal pre-scale units — **scale-invariant, firewall-safe, never converted to metres**. T3 1.091 →
  PASS; T1 1.352 → FAIL. Runs over **all candidate bars** (a wrong length is itself the mispairing
  signal, so it must see a bar even when an endpoint is also coherence-flagged).
- **(d) sufficiency (fail-closed floor).** A headless PASS requires **≥ 3 VALIDATED bars** (a validated
  bar = a proposed pair whose both endpoints are coherent). **Why 3:** the floor must be ≥ 2 so gate (c)
  has two bars to compare — with a single surviving bar the ratio is a vacuous 1.0 and the layer would
  scale unchecked; 3 matches the EDR deployment norm (Toth ESM deploys 3–4 scale bars/transect), leaving
  margin. T3 → PASS (4); T1 → FAIL (0). CLI-overridable via `--min-validated-bars`.

Thresholds are **calibrated on the known-good transect (T3) with margin**; the bad transect (T1) is left
to fall where it falls. **No threshold is tuned to make T1 fail** — it fails decisively on (a) and (c)
(and (b)) on its own.

### Two divergences from the brief (ledger entries)

1. **Gate (b) is coherence, not a projection-count/residual heuristic.** The brief assumed mis-decodes
   are sparse-camera + high-residual; the data shows the opposite (dense-camera, and the ghost is
   *low*-residual relative to its peers). Count is reported as escalation evidence only.
2. **No in-gate `optimizeCameras`.** The in-memory optimize was a one-off **probe** to *prove* the T1
   layer incoherent (it does not fix it — markers aren't bundle constraints without scale bars). In
   production gate (b) is a **lean tripwire on the as-detected layer**, not a research instrument. The
   T3↔T1 gap is ~1000×, so the exact ceiling is not delicate.

### The fail-early → GUI → re-enter loop (the deliverable)

`stage_markers` runs the gates **after detection, before scale**:

- **PASS** → emit a **validated scale-bar set** (`validated_scalebars.json`: the marker pairs + their
  local lengths + 0.25 m) plus a `headless-pass` provenance record (`markers_validation.json`), and stamp
  `esm.markers_validation`. It does **not** create the Metashape scale bars — that is `stage_scale`'s job
  (clean detect/validate vs apply separation). STOP before scale.
- **FAIL** → write a **structured escalation report** (`markers_escalation.json`: every gate finding +
  the count/coherence **evidence** + **which images each suspect marker spans**, from our own detection)
  and an `awaiting-manual` provenance record, persist, then **halt with a critical alarm BEFORE scale /
  optimize / dense**, queuing the GUI touchpoint. Console gets a readable summary; the JSON is durable.
- **Re-entry.** The human fixes markers/scale bars in the GUI and saves; re-running `--stage markers`
  validates the **EXISTING corrected set (no re-detect** — detection runs only when the chunk has no
  markers, so a GUI fix is never discarded). On PASS the validated set flows to `--stage scale`.

`stage_scale` is **dumb**: it refuses unless `esm.markers_validation` is `headless-pass`, then creates a
Metashape scale bar per validated pair at 0.25 m, **reusing** any the human already created in the GUI
(idempotent). It makes no geometric decision. This replaces the manual GUI scale-bar assignment in the
common (PASS) case and confirms it in the re-entry case.

### Stage order

```
… align → markers {escalate? → [GUI: fix markers] → markers} → scale → reduce → …
```

The `[GUI]` handoff is now **conditional** — entered only when validation escalates.

### Fail-closed principle (robustness hardening)

The gate **fails closed**: any state that is not a clean, complete, coherent layer ESCALATES — it never
silently passes and never crashes. Concretely:

- **Degenerate detection** — zero markers, one marker, all markers flagged, or zero proposable bars all
  collapse to fewer than the gate-(d) minimum and escalate; an empty `validated_scalebars.json` is never
  emitted.
- **Malformed marker state** — an un-triangulated marker (no 3D position), a single-camera marker
  (< 2 rays — structurally un-triangulable; this is a **minimum**, distinct from the falsified count-floor
  *quality* heuristic), and a **NaN/inf** residual are each **flagged**. Non-finite is checked explicitly
  because `NaN > ceiling` is `False` in Python — a coherence ceiling alone would let a NaN slip.
- **Threshold boundaries are defined** — gate (b) is inclusive (`resid ≤ ceiling` passes; `> ceiling`
  flags), gate (c) is inclusive (`ratio ≤ max` passes), gate (d) is inclusive (`bars ≥ min` passes). Each
  boundary is unit-tested at the exact value.
- **Any exception** in extract/validate is itself an escalation: the handler writes the report
  (`failed_gates: ["extraction_error"]`, status `escalated`) and halts before scale — it can never fall
  through to a PASS.
- **Provenance integrity** — a re-entry PASS that follows a prior escalation is recorded **distinctly**
  (`marker_source: human-corrected`, `human_touch: gui-marker-fix`, with a back-reference to the
  escalation event) from a zero-touch headless PASS (`marker_source: headless-auto`). The manifest can
  tell "T3 zero-touch" from "T1 corrected-by-human." Validation is **deterministic** — identical input
  yields an identical verdict and byte-identical `validated_scalebars.json`.

### Transferability — consecutive-ID pairing is an assumption (v2 item)

Gate (a) assumes EDR's **consecutive-ID** bar convention (13-14, 15-16, …). A deployment using a
different pairing convention **fails closed** rather than corrupting: a gapped convention (e.g. 10-20,
11-21) produces orphans → gate (a) escalates; a convention that yields too few consistent bars escalates
on gate (d). The one residual risk is an *interleaved* convention whose wrong pairing happens to be
length-consistent **and** yields ≥ `min_validated_bars` bars — gates (c)/(d) cannot see that. This is a
documented limitation: **configurable pairing conventions are a v2 item**; until then the consecutive-ID
assumption is explicit and any violation that is not provably safe escalates. No tuning may relax this to
make a non-conforming layer pass.

## Consequences

- **A geometrically incoherent or unpairable marker layer can no longer be scaled headless** — it
  escalates with a complete, human-actionable report instead of silently corrupting scale/level.
- T1's escalation is the **correct** outcome of this build, not a defect: it reaches a valid result on
  its own or stops. The firewall holds — gate (c) is scale-free, so no reference (P13HMEON) is ever
  consulted to resolve a pairing.
- Thresholds are CLI-overridable (`--marker-resid-ceiling`, `--interbar-ratio-max`,
  `--min-validated-bars`) but default to the T3-calibrated values; the per-marker residuals and
  projection counts are logged every run for trend.
- Verified read-only on both real projects via `probes/stage_markers_verify.py` (T3 PASS with 4 validated
  bars / T1 ESCALATE on all of a/b/c/d, no project mutated) plus pure gate unit tests
  (`test_marker_validation.py`) and offline loop integration tests (`test_stage_markers_loop.py`)
  covering the gates, degenerate/malformed/exception fail-closed paths, threshold boundaries, determinism,
  provenance distinction, and re-entry robustness.
