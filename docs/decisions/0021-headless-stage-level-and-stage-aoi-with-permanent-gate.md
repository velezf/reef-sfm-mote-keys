# ADR 0021 — Headless `stage_level` + `stage_aoi` (markers-level / footprint-frame split) with a permanent QC gate

Status: Accepted
Date: 2026-06-04
Chat: 5 (EDR_T3 re-level codification, Phase B)
Related: ADR-0020 (LOCAL-CRS + identity Planar DEM/ortho), ADR-0010 (ESM Table S2 binding),
ADR-0017 (DSM 1 cm; Step-4 wiring), ADR-0015 (Step-13 confidence filter)

## Context

The day-1 T3 product carried a **24.26° plane tilt**. Forensics
(`data/qc/chat5/edr_t3_relevel_phase1_diagnosis.json`) traced it to ESM Step 11 run through the GUI
**USGS Metashape AlignmentHelper** (`vendor/usgs/AlignmentHelper_v1.py`, v1.0.1, DOI 10.5066/P9YN4KDX):
its `refine` derives yaw/pitch from a **2-marker midline** and **always sets roll = 0**; a 2-marker line
cannot define roll, so the cross-axis came only from the operator's visual bounding-box orientation —
error-prone for a 1 m-wide underwater strip. A separate failure: a marker-placed 10×1 m AOI clipped the
reef band (48% coverage) because markers 14/20 sit ~0.5 m off-centre and ~3° angled to the band.

Phase A fixed both on a disposable copy (`/data/edr_work/edr_t3_relevel_final.psx`), validated, and
gated PASS (tilt 1.88–2.23°, coverage 96.7%, co-reg dx=dy=0, scale 10.00 m). The Phase-A scripts were
ephemeral (`/tmp`, **unrecoverable**); the recipe survives only as prose, the QC JSONs, and the PASS
artifact's stored transform/region. This ADR **codifies** that validated recipe into the guarded
headless entrypoint `run_pipeline.py` so it is reproducible without the GUI helper and cannot silently
regress.

A read-only recon-check (`data/qc/chat5/recon_check_20260604.json`) reproduced the leveling from the
pristine markers and confirmed: (a) the deterministic vetted-6 plane-fit R matches the stored
leveling-only transform to **0.23°**, residual on the under-constrained cross/roll DOF the diagnosis
flags (0.85 m marker-Y-spread) — non-structural; (b) the AOI **yaw (~2°) is baked into `chunk.transform`
about world Z**, with `region` the axis-aligned 10×1×5 m box.

## Decision

Add **two separate stages** and a **permanent gate** to `run_pipeline.py`, ordered:

```
... reduce → level → dense → filter → aoi → dsm → ortho → gate → report
```

### Why a split (not one combined stage)
The two jobs have **different inputs and different natural phases**:
- **`stage_level` (ESM Step 11 analog)** — input = the **scale-bar markers**; must run **before dense**.
  Robust marker-PLANE level: scale-bar residual MAD (`|z| > 3.5`) auto-excludes the bad bar (T3: 25/26,
  +15.13 mm), least-squares plane (dependency-free Jacobi eigensolver) to the vetted markers, rotate the
  plane normal → world +Z (roll+pitch only, **scale preserved**). A plane from ≥3 fiducials fixes the
  roll DOF the 2-marker midline cannot — the day-1 failure mode. Yaw is **not** set here.
- **`stage_aoi` (ESM Step 14 bbox analog)** — input = the **dense footprint**; must run **after filter**
  (PCA on the denoised cloud). Footprint PCA → major axis → yaw (applied about world Z to
  `chunk.transform`); footprint centroid → AOI centre; 10×1×5 m crop. The yaw-in-transform placement is
  what the recon-check proved the validated artifact uses.

Folding them into one stage would force an awkward single placement (markers want pre-dense; footprint
wants post-dense). The split is cleaner **and** more ESM-faithful (Step 11 → 12 → 14).

### Orientation anchor — camera track, not a named marker (transect-agnostic)
The PCA major axis has a 180° sign ambiguity. The **primary** sign rule is the **camera track**: order
aligned cameras by image label, project the first-N vs last-N camera centroids onto PC1, orient **+X
toward the first-image-number cameras**. This is deterministic, present on **every** belt transect and on
fresh raw data, and robust to the lawnmower zigzag (T3: first-20 cameras mean X = +3.49, last-20 =
−3.57, ~7 m separation; reproduces the validated marker-20-on-+X frame). The named-marker check is kept
as an **additive** cross-check where a designated marker exists, not the rule.

**Precondition (belt transect).** `stage_aoi` assumes an **elongated** footprint. Gate check 6
(aspect ≥ 5:1, explained-var ≥ 0.95) **hard-fails** a degenerate/square footprint rather than
mis-framing it. Square-plot sites (Summerland Ledges / IC_U — 10×10 m plots, no dominant axis, different
cameras) are **out of scope by survey design** and trip check 6; Toth treats them separately too.
Generalizes to EDR T1/T3/T8 and the other offshore belt sites and to fresh belt-transect surveys with
coded scale bars.

### Permanent QC gate (`stage_gate`, after ortho, before report)
Eight checks; any core breach raises `PipelineSanityError` (hard stop unless `--ignore-sanity`). The
core (1–7) is **self-contained** — no reference — so reference-less sites still gate. The P13HMEON
reference is **additive** (8), GATE-only, never a level/aoi input.

1. **Long-axis (X) tilt** ≤ 0.5° (observed 0.38–0.47°).
2. **Total tilt** ≤ **6.0°** — the gross-mislevel bound. **Derivation:** the 0.85 m marker-Y-spread on a
   1 m transect makes a ~2–4° **cross** tilt physics, not a defect (observed PASS 1.88–2.23°; reference
   cross ~1.3° is the truth, not a target our markers can hit). 6.0° = that floor + margin, and ~4×
   below the 24.26° day-1 defect it must catch. Cross tilt is logged every run (manifest trend data) but
   **not** gated as a defect within the envelope.
3. **Coverage (interp-OFF)** ≥ 95% (observed 96.7%).
4. **Scale**: AOI long extent = `aoi_length_m` ± 0.02 m, and level/aoi preserve `transform.scale`.
5. **DEM/ortho co-registration** dx = dy = 0 (same `_local_planar_projection`, by construction).
6. **Footprint** explained-var ≥ 0.95 **and** aspect ≥ 5:1 (the belt precondition; observed 0.988 / ~8–10:1).
7. **Orientation convention** — the camera-track +X anchor lands on the +X half of the framed AOI.
   **This closes a real hole:** coverage, co-reg, and scale are ALL invariant under a 180° yaw flip of a
   centred symmetric AOI, so a PCA-sign bug would ship a reversed product silently and the reference-less
   core would never see it. Check 7 is the only thing between a sign bug and a flipped DEM at a
   reference-less site.
8. **Reference-patch overlap** (ADDITIVE, where a P13HMEON DEM is supplied via `--reference-dem`).

### Footprint/coverage mechanism (implementation constraint)
Metashape 2.3.1's dense `PointCloud` exposes **no per-point coordinate iterator** and there is **no
numpy** in the bundled Python, so an "all-points 2×2 covariance" cannot be computed in-process;
`renderImage` is camera-view only (needs a `Calibration`). The chosen mechanism is a **transient
interp-OFF DEM** (ADR-0020 local-planar recipe, resolution **pinned to the DSM 0.01 m** so it introduces
no new tunable) whose occupied cells (NoData sentinel −32767) feed the PCA and the coverage count; the
transient DEMs are removed before `stage_dsm`, preserving its idempotency. This is **closer to the
validated pilot** (a 5 cm coarse-DEM footprint) than the superseded all-points knob, and keeps the
whole stage in-process (no subprocess, no temp PLY, no `.venv` dependency in the hot path). All math
helpers are dependency-free (Jacobi eigensolver, Rodrigues, analytic 2×2 PCA, normal-equation plane fit)
and were validated against the pilot numbers in the recon/probe runs (tilt 0.38/1.91/1.95 vs pilot
0.40/1.83/1.88; footprint evr 0.990/aspect 10 vs 0.988/8).

## Divergence ledger (this IS the portfolio thesis — every deviation from ESM Table S2)
- **Step 11 orientation:** GUI USGS AlignmentHelper → deterministic outlier-rejecting marker-plane
  `stage_level` (headless, gated, reproducible without the helper). Rationale: the helper's 2-marker
  midline is roll-blind (the 24.26° defect); a ≥3-fiducial plane fixes roll.
- **Step 14 AOI:** manual 10×1 bbox → footprint-PCA + centroid `stage_aoi` with a camera-track
  orientation anchor. Rationale: markers 14/20 are off-centre/angled vs the band (48% coverage); the
  footprint is the robust frame; the camera anchor generalizes the sign rule to any belt transect.
- **Whole pipeline:** GUI Batch Process → headless `run_pipeline.py` (mechanical, not methodological).
- **Footprint mechanism:** all-points 2×2 covariance → interp-OFF DEM occupied-cell PCA, forced by the
  MS 2.3.1 dense-cloud API (no point iterator / no numpy); pinned to the DSM resolution.
- **Provenance:** the Phase-A pilot scripts are unrecoverable (ephemeral `/tmp`); the recipe is codified
  from prose + the QC JSONs + the PASS artifact's stored transform/region. The Phase-C acceptance bar is
  therefore **functional-equivalence** (determinism + gate-vs-P13HMEON), not bit-identity to the manual
  artifact — codified-vs-manual `max_abs_diff` is corroboration (expected ~mm on the cross DOF).
- **Steps 9–10 (colour correction / dehaze):** not applied (optional; not in the validated recipe).

## Generalization (transect-agnostic — no T3-specific constants)

The stages run unchanged on any EDR belt transect (T1/T3/T8 + other offshore belt sites) and on fresh
belt-transect data; they refuse to silently mis-handle anything else. Specifics:

- **Marker detection (ESM Step 7) is AUTO-TOLERANCE by IDENTITY, not count.** Tolerance starts at 20 and
  bumps by 5 to a cap of 100 (ESM-faithful: start strict, loosen). Accept at the LOWEST tolerance where
  the full expected coded-ID set (`--expected-marker-ids`, the same pairs that feed the 0.25 m residual
  check) is present — NOT where the count matches. Rationale: tolerance increases add detections
  monotonically including false positives, so `count == expected` can stop on a wrong mix (7 real + 1
  spurious); a false positive corrupts the level-plane fit and scale-bar pairing, and MAD rejection only
  catches outliers, not a spurious marker near the plane. Unexpected IDs are flagged as possible false
  positives; missing IDs FAIL LOUD at the cap. A weaker `--expected-markers` count criterion and a
  plateau heuristic exist as fallbacks (both warn). No per-transect tolerance is pinned.
- **`stage_level` pre-guards:** alignment rate ≥ 90% (a poorly-aligned transect STOPs before leveling,
  not after); ≥ 2 surviving scale bars / ≥ 3 vetted markers after MAD rejection; and a non-collinearity
  guard (2nd/1st scatter eigenvalue ≥ 0.02) so near-collinear markers STOP instead of fitting a garbage
  roll. MAD rejection stays residual-driven — never a hard-coded "drop 25/26".
- **Orientation sign = camera track**, not a named marker (see above); gate #7 is the camera-track +X
  anchor (self-contained). Named-marker check is additive where one exists.
- **Gate #2 bound is `--max-total-tilt-deg` (default 6.0°), not a buried constant.** The per-transect
  marker-Y-spread, marker Z-rms, and an implied cross floor are logged every run (manifest trend data);
  6.0° is documented conservative for the EDR ~1 m-strip deployment and is overridable for a transect
  with materially different marker geometry.
- **Gate #8 reads the per-transect reference** via `--reference-dem`; no global roughness constant. Core
  gate (#1–#7) stays self-contained for reference-less transects.
- **No hard-coded site/transect/paths** in code: project, transect, image-root, out-root, reference,
  and expected IDs are all arguments (audited 2026-06-04; the only `T3`/`edr_t3` literals are in
  docstrings/comments/help text; two `/data/...` argparse defaults remain, overridable).

**Reference availability (additive check 8 + Chat-6 reconciliation):** T3 has P13HMEON DEMs on disk
(`20230711_T3_{C1,R1}_DEM_{canopy,confidence}.tif`; published tilt C1 0.91° / R1 1.32°). T1 and T8 are
NOT fetched — they exist in the published dataset (DOI 10.5066/P13HMEON, with topographic-complexity
reconciliation targets) but need a targeted fetch like T3's. Until then T1/T8 gate on the self-contained
core (#1–#7); T3 additionally gets check 8 + complexity reconciliation.

**Scope boundary:** general, not gold-plated — no multi-camera handling, no square-plot framing.
Square-plot sites (Summerland Ledges / IC_U) stay out of scope by design; gate #6 hard-fails them.

## Consequences
- The whole pipeline is headless and gated; a 24° mis-level, a clipped AOI, or a reversed (sign-flipped)
  product **cannot ship** — the gate hard-stops before `report`.
- `stage_level`/`stage_aoi` are idempotent (skip on their `esm.*` meta) and resumable, matching the
  existing `--stage` model.
- T3 validation (Phase C) exercises `level → aoi → dsm → ortho → gate` on a preserved-dense copy (no
  re-dense/re-filter, which self-skip). The from-scratch `level → dense → filter → aoi` ordering earns
  its first real exercise on T1, validated against the reference gate — NOT by any A/B against T3.
- Out-of-scope square-plot sites are rejected loudly (check 6), not mis-framed.

## Sources
- `data/qc/chat5/edr_t3_relevel_phase1_diagnosis.json` — day-1 defect mechanism (roll-blind helper).
- `data/qc/chat5/edr_t3_relevel_final_gate.json` — Phase-A PASS metrics (the gate-bound grounding).
- `data/qc/chat5/recon_check_20260604.json` — R-to-0.23°, yaw-in-transform, non-structural regime.
- `data/qc/chat5/GROUND_TRUTH_probe_20260604.md` — pristine vs PASS stored numbers; provenance note.
- `vendor/usgs/AlignmentHelper_v1.py` (+PROVENANCE.md) — the superseded Step-11 tool.
- Toth et al. 2025 ESM Table S2, Steps 11 / 14 / 15. ADR-0020 (DEM/ortho recipe). ADR-0010 (ESM binding).

#tags: stage-level, stage-aoi, permanent-qc-gate, marker-plane-level, footprint-pca, camera-track-anchor,
orientation-convention, belt-transect-precondition, divergence-ledger, headless, toth-esm, step-11,
step-14, adr-0020-followup, chat5
