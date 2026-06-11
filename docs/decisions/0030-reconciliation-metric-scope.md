# ADR-0030 — Reconciliation metric scope: pure-Python core, MultiscaleDTM stubs, 1 cm resample

**Status:** Accepted
**Date:** 2026-06-11
**Related:** ADR-0027 (T1 DSM at 1 cm), ADR-0028 (corrected T1 Z window — file pending, decided Chat 5), P13HMEON firewall (`325dbc7`)

**Numbering note:** 0028 and 0029 are already assigned to Chat-5 decisions
(corrected T1 AOI Z window; PointCloudData-direct full-area ortho) recorded in
CLAUDE.md with files pending on `fix/level-camera-nadir`. This ADR takes the
next genuinely free number, 0030.

---

## Context

Chat 6 builds the metric-reconciliation layer: recompute terrain metrics from
our 1 cm transect DSMs and compare them with the P13HMEON-published EDR values.
Before implementing, the metric list itself needed verification, because the
plan prompt's guesses were partly wrong.

**Actual Toth et al. 2025 metric set (ESM Fig. S5):** surface rugosity
(3D/2D surface-area ratio, Du Preez 2015 SAPA family), standardized mean
elevation (mean − min), vector ruggedness measure (VRM, Sappington et
al. 2007), plus MultiscaleDTM-computed SAPA (slope-corrected), RIE, and ASD.
**There is no fractal-dimension metric** — the plan prompt's inclusion of one
was incorrect and is dropped, not stubbed.

The metrics split into two reproducibility tiers:

1. **Pure-Python reproducible** — exact definitions independent of any
   reference implementation, verifiable against closed-form analytic
   fixtures: **rugosity** (flat plane → 1, 45° plane → √2),
   **standardized mean elevation**, **VRM** (any constant-slope plane → 0).
2. **MultiscaleDTM-specific** — SAPA (planar-detrended), RIE, ASD. Toth
   computes these with the R `MultiscaleDTM` package; a from-scratch Python
   reimplementation could silently diverge from that package's exact focal
   algorithms, and a divergent number is worse than no number in a
   reconciliation context.

Resolution matters: rugosity and VRM are scale-dependent (finer grids resolve
more micro-relief → higher values). Toth computes everything on 1 cm DSMs;
comparing a different grid resolution against published values is a category
error, not a tolerance question.

## Decision

1. **Implement tier 1 in pure Python** (`reef_sfm_provenance.reconcile.metrics`):
   `rugosity` (triangulated 3D/2D area ratio), `mean_elevation_standardized`,
   `vrm` (5×5 cm focal window default). TDD against analytic fixtures with
   tight (1e-9) tolerances; functions take an in-memory numpy DSM + cell size
   and do **no file I/O**.
2. **Stub tier 2 as explicit `NotImplementedError`** (`sapa`, `rie`, `asd`)
   with messages naming MultiscaleDTM as the reason. Do **not** fake or
   approximate them. If they're ever needed, the path is rpy2 against the real
   package or a fixture-verified reimplementation — a separate decision.
3. **Resample every DSM to 1 cm before computing any metric**
   (`resample_to_cm`, block-mean aggregation, NaN-aware). Upsampling and
   non-integer factors are rejected — aggregation only, no fabricated detail.
4. **P13HMEON remains comparison-only** (firewall `325dbc7`) and is **not
   touched in this branch**. This branch ships metric functions and analytic
   tests only; loading real DSMs (ours or P13HMEON's) and running the actual
   reconciliation happen in later branches.

## Consequences

- (+) Tier-1 metrics are verifiable to machine precision against analytic
  surfaces, so a reconciliation mismatch later points at the *data*, not at
  untested metric code.
- (+) The stub pattern makes the tier boundary impossible to miss at call
  time; nobody discovers months later that "our SAPA" wasn't Toth's SAPA.
- (−) The reconciliation table will initially cover only 3 of Toth's 6
  metrics; SAPA/RIE/ASD columns stay empty until the rpy2-or-reimplement
  decision is made.
- (−) Block-mean resampling discards sub-centimetre information from any
  finer source grid; that is the point (match Toth), but it means tier-1
  values are not comparable across resolutions and the cell size must ride
  along with every reported number.
- (~) VRM's focal window must resolve to an odd cell count ≥ 3; on a 1 cm
  grid the 0.05 m default gives the canonical 5×5 Sappington window.

#tags: reconciliation, metrics, rugosity, vrm, multiscaledtm, toth, p13hmeon-firewall
