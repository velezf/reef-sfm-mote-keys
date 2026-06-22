# ADR-0038 — Captured-threshold audit: record defensibility is orthogonal to pass/fail

**Status:** Accepted
**Date:** 2026-06-22
**Extends:** ADR-0031 (QC gate provenance; conformance/outcome split)
**Related:** ADR-0021 (permanent 8-check gate), ADR-0022 (marker-layer validation gate)

---

## Context

ADR-0031 established that QC criteria derive from Toth Table S2 and that
not-evaluable ≠ pass.  Chat 6 (pipeline provenance gaps) exposed a second
orthogonal question the QC layer did not answer: **can the run record
reconstruct the verdict for each criterion without re-running the pipeline?**

Three concrete gaps were found:

| check | gap before fix |
|-------|---------------|
| `5_coreg_dx_dy_m` | threshold `GATE_COREG_TOL_M` never written to `esm.gate` |
| `6_footprint` | `GATE_FOOTPRINT_EVR_MIN` / `GATE_FOOTPRINT_ASPECT_MIN` never written |
| gate B coherence | `worst_resid_px` not captured; observed == threshold (ceiling) → tautology |

Check 7 (`7_orientation_plus_x`) was a fourth gap: the expected value `True`
(first-image cameras on the +X half) was never written to `esm.gate`, leaving
`threshold=None`.  An early fix attempt used `characterized=True` to suppress
the UNTETHERED finding.  That was wrong — it claimed the gap was documented
when the threshold was simply absent from the record.

## Decision

### 1. Audit scope

The **capture audit** (`capture_audit.py`) classifies each gate check and QC
criterion by how well its record defends the verdict, independently of whether
the run passed.  A run can fail QC and still have complete provenance; it can
pass QC and still have an undefensible record.

`overall_conformant = True` means every evaluable check has a captured
threshold and a captured measurement.  It does **NOT** mean the run passed.

### 2. Liability taxonomy

| Liability | When it fires |
|-----------|--------------|
| `RETIRED` | No liabilities; status sentinel. |
| `UNCAPTURED_MEASUREMENT` | `observed is None` — the measurement was never written. |
| `UNTETHERED_THRESHOLD` | `threshold is None` and not advisory and not characterized-with-note. |
| `UNSOURCED_THRESHOLD` | Defined in the taxonomy; not yet enforced in code (future). |
| `SELF_CONFIRMING` | `observed == threshold` for numeric types — the measurement is a tautological repeat of the configured ceiling (the pre-fix gate B pattern where observed == ceiling_px). |

Severity order: `RETIRED < UNCAPTURED < UNTETHERED < UNSOURCED < SELF_CONFIRMING`.

### 3. SELF_CONFIRMING fires only for numeric types

A boolean gate where `observed=True` and `threshold=True` means the assertion
fired correctly.  It is a pass, not a tautology.  The classifier suppresses
SELF_CONFIRMING when either `observed` or `threshold` is `bool`:

```python
and not isinstance(t.observed, bool)
and not isinstance(t.threshold, bool)
```

**Limitation:** Python's `isinstance(True, int) is True`, so an integer 0 or 1
passed as a threshold escapes this guard.  Pipeline gate thresholds are either
float/int numerics or explicit Python booleans; the two are never mixed, so the
isinstance check is sufficient in practice.  A future caller that passes int 0/1
as a boolean gate threshold would get a spurious SELF_CONFIRMING finding.

### 4. Characterized exemption requires a captured note

`characterized=True` alone does not suppress UNTETHERED_THRESHOLD.  The
exemption requires `characterized=True AND bool(note)`.  A bare flag provides no
rationale and is itself an undefensible record.  The code enforces presence;
adequacy is a human review control.

### 5. Check 7: retire via captured expectation, not characterization

The correct fix for check 7 is to write the expectation into the record:

```python
"7_orientation_plus_x": {
    "v": aoi["orientation_plus_x_ok"],
    "pass": bool(aoi["orientation_plus_x_ok"]),
    "expected": True,
    "note": "Boolean sign-flip guard (ADR-0021): coverage/co-reg/scale invariant
             under 180° yaw flip — a PCA-sign bug ships a reversed product silently;
             expected orientation_plus_x_ok=True.",
}
```

`schema.py from_esm_gate` recognises `"expected"` as a threshold key alongside
`"max"`, `"min"`, `"target"`, and `"tol"`.

**Live results:**

| run | observed | threshold | audit status |
|-----|----------|-----------|-------------|
| T1 area survey | `True` | `True` | RETIRED (pass — captured correctly) |
| T1_R2 transect | `False` | `True` | RETIRED (captured failure — verdict reconstructable) |

The T1_R2 `passed=False` is preserved and correct.  No `characterized` key is
written.  The failure is **not** accepted or explained away.

---

## ⚠ OPEN OUTCOME ITEM: T1_R2 orientation/reversal UNVERIFIED

The T1_R2 check 7 failure is now provenance-complete (the record can defend the
verdict), but the **substantive question of whether the product is reversed is
not answered**.

CLAUDE.md records "Benign 135°-vs-+X convention mismatch in `stage_gate`. No
product flip. Note it; don't touch it."  This is a bare assertion.  No captured
record shows:

- The actual `firstX` / `lastX` values from the T1_R2 gate run.
- A geometric argument distinguishing a 135° rotation from a 180° flip.
- Independent visual or metric confirmation that the ortho/DSM is correctly oriented.

**Before any claim that the T1_R2 product is correctly oriented:**
1. Re-run `stage_gate` on the T1_R2 project, capture `firstX`/`lastX`.
2. Confirm geometrically that the camera track lands at 135° to +X (not 180°).
3. Add a visual or georeferenced confirmation.

**Exposure:** frame-robust metrics (rugosity, VRM, yaw-invariant mean elevation)
are unaffected by a 180° flip.  Ortho/DSM directional presentation — the
along-transect "left" and "right" assignment, any asymmetry analysis, any
georeferenced overlay — is the exposure.  The orientation question is load-bearing
only when directionality matters in the final data product.

---

## Consequences

**Positive:**
- (+) The audit layer is orthogonal to the QC verdict — a failing run with
  complete provenance (all thresholds captured) yields `overall_conformant=True`,
  which correctly reflects the state of the record, not the state of the reef.
- (+) `SELF_CONFIRMING` now correctly distinguishes a tautological ceiling-repeat
  (the pre-fix gate B pattern) from a boolean gate passing its assertion.
- (+) `characterized=True` without a note is rejected at classification time —
  bare acceptance flags can no longer suppress audit findings.
- (+) Check 7 threshold is now captured in the pipeline output and fixtures;
  `audit_run` over a fresh `stage_gate` output will produce `overall_conformant=True`
  for both passing and failing orientation gates.

**Negative / Open:**
- (−) `UNSOURCED_THRESHOLD` is defined in the taxonomy but not yet enforced in
  code (all current thresholds are either sourced in ADR text or parameterized
  with defaults explained in docstrings).
- (−) `GateCheckResult` has no `source` field — gate checks cannot yet cite their
  ADR or constant origin in the schema record.  Tracked in docs/09-v2-roadmap.md.
- (−) T1_R2 orientation/reversal is unverified (see ⚠ above).
- (~) `SELF_CONFIRMING` isinstance limitation is documented and acceptable for the
  current pipeline but is a known edge case for future callers.

#tags: capture-audit, provenance, threshold, self-confirming, characterized, orientation, check-7, boolean-gate, open-item
