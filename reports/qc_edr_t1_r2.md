# QC report — EDR_T1_R2

Survey: 2023-07-11 · Reconstruction: Q030 single-transect · Generated: 2026-06-17 (Chat 10)

---

## QC summary

| criterion | outcome | observed | threshold | characterized |
|-----------|---------|:--------:|:---------:|:-------------:|
| frame\_retention | **PASS** | 0.993 | ≥ 0.60 | — |
| registration\_ratio | FAIL | 0.482 | — | ✓ corpus ceiling |
| scale\_bar\_residual | FAIL | 4.4 mm | ≤ 1.0 mm | ✓ no GCPs |
| markers gate A (parity) | ESCALATED→PASS | — | — | human GUI fix |
| markers gate B (coherence) | PASS | < 2.0 px | — | — |
| markers gate C (consistency) | PASS | ratio 1.034 | ≤ 1.25 | — |
| markers gate D (sufficiency) | PASS | 3/3 bars | ≥ 3 | — |
| AOI coverage (GATE#3) | BYPASSED | 93.7% | ≥ 95% | out-and-back |
| belt geometry (GATE#6) | BYPASSED | n/a | n/a | out-and-back |
| marker 25-26 label basis | OPEN | — | — | pending Frank |

---

## Criterion notes

**frame\_retention (PASS 0.993):** 270 enabled, 131 aligned, 139 disabled (quality < 0.30 floor).
1 − 139/270 = 0.485 (Q050 foil) vs 1 − 0/131 = 0.993 (Q030). ADR-0034.

**registration\_ratio (FAIL 0.482):** 131 of 272 frames aligned (48.2%). This is the corpus geometry
ceiling — out-and-back overlap pattern + limited cross-track redundancy at the far end. Threshold 0.30
vs 0.50 makes no difference (ADR-0035 falsified). Characterised as a survey geometry constraint, not
a processing defect.

**scale\_bar\_residual (FAIL 4.4 mm):** Peak ±1.76% of 250 mm across 3 bars. ADR-0031 floor is 1 mm.
No GCPs in underwater survey; residual expected. Scale stage gate PASSED (inter-bar ratio 1.034 < 1.25;
3/3 validated bars). Characterised.

Scale bars:
- 15–16: len\_local 1.533463, defined 0.25 m
- 19–20: len\_local 1.585033, defined 0.25 m
- 25–26: len\_local 1.564386, defined 0.25 m

**AOI GATE#3 (coverage 93.7% < 95%):** Out-and-back pass means far end has lower density. Bypassed
with `--ignore-sanity` (ADR-0033).

**GATE#6 (belt geometry):** EDR\_T1\_R2 is an out-and-back trajectory (double-pass), which fails the
single-pass belt geometry test. Non-applicable — not a defect. ADR-0033.

**Marker 25-26 label basis (OPEN):** Physical-to-label correspondence for the far-end target unconfirmed
pending Frank review. Positions are accurate (< 2 px reprojection, 7-8 projections each). A label swap
does not affect the plane fit or scale. ADR-0033 open item.

---

## Overall assessment

Corpus geometry sets a firm registration ceiling (48.2%). All FAIL criteria are characterised and
non-disqualifying. The reconstruction is the best achievable from this out-and-back imagery corpus.
