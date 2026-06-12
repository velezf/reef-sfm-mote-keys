# ADR-0032 — Reconciliation harness: confirmed P13HMEON contract, transect-identity finding, function-validation + envelope approach

**Status:** Accepted
**Date:** 2026-06-11
**Related:** ADR-0030 (metric core), ADR-0015 (confidence filter), ADR-0026 (T1 area-survey AOI), ADR-0028 (T1 Z window / relief), P13HMEON firewall (`325dbc7`)

---

## Context

Chat 6's reconciliation layer compares our terrain metrics against the
published P13HMEON values (DOI 10.5066/P13HMEON, Toth and others 2025). This
ADR records what the published release actually contains, the one genuine
blocker to a 1:1 EDR_T1 comparison, and the approach taken given that blocker.

### 1. Confirmed P13HMEON contract (the 94 KB values table)

`Coral_reef_topographic_complexity_data.zip` (94 KB — fetched read-only into
the firewall store, **not** the 5 GB SfM products) carries
`Coral_reef_topographic_complexity_data.csv`: 248 rows × 23 columns, keyed
**Site + Subsite + Transect_ID + Filter**. Verified against the bundled data
dictionary:

| published column | dictionary definition | our metric (ADR-0030) | match |
|---|---|---|---|
| `full_area_rugosity` | 3D surface area ÷ 2D planar area, **whole-model** | `rugosity` (triangulated 3D:2D) | exact (disambiguated from focal `sapa_mean`) |
| `stand_mean_elev` | mean elevation − minimum elevation | `mean_elevation_standardized` | exact |
| `vrm_mean` | Sappington VRM, unit-normal dispersion, **5×5 cm** focal | `vrm` (window=0.05) | same definition; their value via R MultiscaleDTM |
| `sapa_mean`, `rie_mean`, `asd_mean` | MultiscaleDTM focal metrics | Tier-2 stubs | deferred (ADR-0030) |

The metric set confirms ADR-0030 on every count, including **no fractal
dimension**. The `Filter` column has four values; **`confidence`** is defined
as "excludes low-confidence point noise (confidence <2 in Agisoft Metashape)"
— **exactly our ADR-0015 filter**. Our DSMs (confidence-filtered, no class
segmentation) therefore match the published **`confidence`** variant, with no
canopy/outplant offset on the filter axis.

### 2. The transect-identity finding (the blocker)

Published **`EDR_T1` is a Subsite of nine transects** (controls C2–C6,
restored R2–R5), each a separate ~10×2 m model with its own metrics row per
filter. Our "EDR_T1" is a single 10×1 m AOI hand-cut from the *centre* of a
merged 28.92 × 25.41 m area survey (ADR-0026: "area survey, not a belt
transect"; 2,422 images from all nine transects reconstructed together). Our
DSM corresponds to **none** of C2–R5 — it is a centre-cut across a surface
that merges them.

The function-validation and envelope runs (below) confirm this empirically:
our T1 centre-cut has **5.48 m of relief** (min −4.51, max +0.97 m) versus the
published per-transect `elev_range` of 0.50–1.40 m — a ~4× scale mismatch.
There is **no defensible 1:1 match** between our DSM and any single published
EDR_T1 row.

## Decision

1. **Build a reusable harness** (`reconcile/harness.py`): `load_dsm` (GeoTIFF
   → NaN-aware array, square-cell check, resample-to-1 cm guard),
   `load_reference_metrics` (one row keyed Site/Subsite/Transect_ID/Filter,
   **read-only**, raises on zero or non-unique match — never silently picks),
   `compute_metrics` (ADR-0030 functions), `reconcile` → `ReconciliationReport`
   (Pydantic, bundle-node-shaped, per-metric our/published/abs/pct + tier +
   note). Hermetic TDD; rasterio added.

2. **Validate our functions 1:1 on identical surfaces (A):** run our metrics on
   the *published* EDR_T3 C1/R1 confidence DEMs (which we hold locally) and
   compare to their published rows. This isolates implementation deltas from
   data deltas.

3. **Diagnose EDR_T1 as an envelope, not a delta (Option 1):** report where our
   centre-cut lands relative to the published EDR_T1 confidence *population*
   (range + mean of the nine), explicitly NOT a per-transect reconciliation.

4. **Scope a true 1:1 as the strong-claim path (Option 2):** the imagery is
   per-transect separable (filename `YYYYMMDD_EDR_T1_<C#|R#>_<seq>.tif`;
   230–283 images per transect), so a single published transect (e.g. C2) can
   be reconstructed 1:1. That is a re-processing run — explicit dense GO + EC2 —
   not done here.

5. **Firewall reaffirmed:** the table and DEMs are read-only on disk, gitignored
   (`data/comparison-only/`), loaded read-only, and never fed back into the DSM
   or metric path.

## Results (real runs, tuned toward nothing)

**(A) Function validation — our functions vs MultiscaleDTM, identical surface:**

| metric | EDR_T3 C1 Δ | EDR_T3 R1 Δ |
|---|---|---|
| rugosity | +0.2% | +0.2% |
| mean_elevation | −0.2% | +0.2% |
| VRM | **+13.2%** | **+14.7%** |

Rugosity and standardized elevation reproduce MultiscaleDTM to **<0.3%** —
our implementations are validated. VRM reads a **consistent ~+14% high**: same
Sappington definition, different implementation (edge/gradient/normal handling
in MultiscaleDTM's focal routine). This is a quantified implementation offset,
not a data error.

**(Option 1) EDR_T1 centre-cut vs published T1 confidence population (n=9):**

| metric | ours | published range | mean | verdict |
|---|---|---|---|---|
| rugosity | 5.13 | [1.28, 2.74] | 1.55 | OUTSIDE |
| mean_elevation | 3.75 m | [0.18, 0.98] | 0.35 | OUTSIDE |
| VRM | 0.102 | [0.057, 0.105] | 0.072 | INSIDE |

The whole-model metrics (rugosity, mean elevation) blow past the published
envelope because our cut spans a 5.5 m trough-to-crest feature — they scale
with captured relief, and our unit captures ~4× the relief of a published
10×2 m belt. **VRM lands inside the population** because it is a *local* 5×5 cm
focal metric, invariant to the macro-relief our cut captured; even after
removing its ~14% implementation bias (≈0.089) it stays inside the range. This
is the expected signature of a scale mismatch, not a DSM defect.

## Consequences

- (+) Our metric core is now validated against the reference implementation on
  real reef surfaces: rugosity/elevation exact, VRM offset quantified.
- (+) The honest EDR_T1 story is documented: only VRM is meaningfully
  comparable for our centre-cut; rugosity/elevation require a unit-matched
  transect (Option 2).
- (+) The harness is reusable: a future Option-2 1:1 run drops straight in.
- (−) No headline per-transect EDR_T1 delta exists yet; the strong claim waits
  on an Option-2 re-process (dense GO + EC2).
- (−) The ~14% VRM implementation gap means our VRM is not interchangeable with
  published VRM at better than ~15%; report both or recompute via MultiscaleDTM
  (rpy2) if a tighter VRM claim is needed.
- (~) `full_area_rugosity` being whole-model (not detrended) means it is
  inherently relief-scale-dependent; this is a property of the published metric,
  not a choice of ours, and is why the centre-cut cannot be compared on it.

#tags: reconciliation, harness, p13hmeon, rugosity, vrm, multiscaledtm, transect-identity, firewall, function-validation
