# ADR-0027 — T1 DSM resolution: 1 cm

**Status:** ACCEPTED  
**Date:** 2026-06-10  
**Supersedes:** none  
**Related:** ADR-0020 (LOCAL-CRS DSM/ortho), ADR-0026 (AOI placement), ADR-0015 (confidence filter)

---

## Context

The filtered point cloud for EDR_T1 has 487.7 M points over a ~735 m² footprint,
giving a mean 2D point spacing of **~1.23 mm** (≈ 664 K pts/m²).

The ESM method (Toth 2025 Table S2 / Combs 2021) uses rugosity metrics computed over
a **5×5 cm focal window** (VRM, RIE, ASD, rugosity ratio).  The DSM resolution must
be fine enough to support the focal-window computation with adequate cell count.

`stage_dsm` in `run_pipeline.py` (line 170) already carries `PARAMS.dsm_resolution_m = 0.01`.
This ADR records the explicit rationale for that value and documents it as a
reconciliation-variance source.

---

## Decision

**DSM resolution = 1 cm (0.01 m)** for the 10×1 m transect AOI.

### Quantitative support

| criterion | value | assessment |
|---|---|---|
| Native point spacing | 1.23 mm | 1 cm = 8.1× spacing |
| pts / DSM cell (1 cm²) | ~66 | well-supported; interpolation stable |
| 5×5 cm focal window | 25 cells | adequate for VRM/RIE/ASD/rugosity |
| 10×1 m transect cells | 100 000 | no memory pressure |
| ESM "default" (~1 mm) | ~1.5× spacing | 664 pts/cell; impractically fine for 488 M-pt cloud |
| PIFSC SOP 0.001 m | parameter-reference only | not binding per standing rule (firewall commit 325dbc7 lineage) |

A resolution of 1 mm (the ESM literal default) would produce a 10 M-cell transect DSM
and require processing 488 M points at sub-native spacing — no accuracy gain, substantial
compute overhead.  8.1× oversampling at 1 cm is well within normal SfM practice and
consistent with the cloud's effective spatial frequency.

### No code change required

`stage_dsm` already uses `PARAMS.dsm_resolution_m = 0.01` (run_pipeline.py:170).
This ADR documents the decision; it does not drive a code change.

---

## Reconciliation-variance record

**1 cm vs Toth 2025 default (~1 mm):** The ESM method specifies DSM resolution as
a tunable parameter with a suggested fine value.  Toth 2025 operations may have used
a different resolution depending on platform GSD and cloud density.  This divergence
is:

- **Justified:** EDR T1 cloud density (664 K pts/m²) does not support sub-mm DSM
  accuracy; 1 cm at 8.1× spacing is the correct operating point.
- **Documented:** effective resolution is recorded in `esm.dsm` provenance metadata
  written by `stage_dsm` at run time.
- **Bounded:** focal-window metrics (VRM etc.) at 5×5 cm are identical in both cases
  because the 5 cm window encompasses 25 cells at 1 cm vs 2 500 cells at 1 mm — the
  metric result converges well before 25 cells.

---

## Scope

This resolution applies to the **10×1 m transect AOI** (ADR-0026).

For a full-area site-overview DSM (non-ESM, optional): 1 cm trips `stage_dsm`'s
inline 5 M-cell guard (7.35 M cells for the 28.92×25.41 m footprint).  A separate
decision is required to raise the guard for a full-area run; the minimum passing
resolution under the current guard is **2 cm** (1.84 M cells).  See ADR-0026 §
"Full-area ortho."

---

## Alternatives considered

| option | disposition |
|---|---|
| 1 mm (ESM literal default) | Rejected — impractically fine on 488 M pts; sub-native accuracy gain; 10 M cell transect DSM |
| 5 mm | Rejected — only 4 cells per 2 cm focal window; undersamples rugosity metrics |
| 2 cm | Acceptable but unnecessary; 66 pts/cell at 1 cm already well-supported; 4× fewer cells at 2 cm does not help transect |
| PIFSC SOP 0.001 m | Identical to 1 mm — rejected on same grounds; SOP is parameter-reference only |
