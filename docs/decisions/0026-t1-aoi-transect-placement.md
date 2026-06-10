# ADR-0026 — T1 AOI: 10×1 m transect placement for an area survey

**Status:** DRAFT — coordinates TBD pending visual inspection  
**Date:** 2026-06-10  
**Supersedes:** none  
**Related:** ADR-0020 (LOCAL-CRS DSM/ortho), ADR-0023 (reduce), ADR-0025 (camera-nadir level)

---

## Context

EDR_T1 is an **area survey**, not a belt transect.  The reconstruction bbox is
28.9 × 25.4 × 15.3 m (scale 0.15246 m/unit, LOCAL_CS, ADR-0024).  The camera
flight principal axis is at ~135°/315° in the chunk XY frame (PCA of 2 348 camera
positions, σ_major = 7.98 m, σ_minor = 3.85 m, spread ratio 2.07:1).

The ESM analysis unit (Combs 2021 + Toth 2025 Table S2) is a **10×1 m transect**.
`stage_aoi` auto-gates on aspect ≥ 5:1; T1's bbox aspect is 28.9 / 25.4 = 1.14:1,
so the gate correctly halts — the transect window cannot be derived automatically
from the flight footprint.

P13HMEON comparison data (firewall: ADR-0025 / commit 325dbc7) uses the same
10×1 m unit; comparability requires matching the analysis window to that convention.

The filtered cloud has a mean 2D point spacing of ~1.2 mm (487.7 M pts,
≈ 664 K pts/m²), so a 10×1 m transect contains approximately 6.6 M points —
sufficient density for any reasonable DSM resolution at or above 1 cm.

---

## Decision

**The AOI for T1 is a single 10×1 m transect**, manually sited along the primary
flight axis at the densest coverage zone within the reconstruction.

Rationale:
- ESM Step 14 (Combs 2021) defines the analysis unit as 10×1 m; the method does
  not aggregate the full area survey as one AOI.
- P13HMEON comparability requires the same window geometry.
- The auto-gate halt is correct behaviour: area surveys require deliberate placement.

**Exact world-space coordinates:** TBD — to be determined from visual inspection of
the filtered cloud / pre-DSM coverage map.  Centre the 10×1 m window:
  - along the ~135°/315° principal axis of the camera track, and
  - in the zone of highest camera overlap within the bbox
    (nominally the centre region of the survey at ~X=−13.3, Y=24.8 units from
    origin, scaled to metres).

**Orientation convention:** long axis of the transect = primary flight axis
(135°/315° in chunk frame); short axis = 90° cross-track.

---

## Full-area ortho (optional, non-standard)

A full-area orthomosaic of the 28.9 × 25.4 m footprint may be produced as a
**non-standard visualisation product** — useful for site context, flight-plan QC,
and outreach — but it is not an ESM deliverable and must not be used as the
analysis AOI.  If produced, label clearly as "site overview ortho" to avoid
confusion with the ESM transect product.

---

## Limitations

1. **Single transect from an area survey.** The 10×1 m window represents a
   fraction of the total surveyed area (~1.4 % of the 735 m² footprint).  The
   placement choice affects which portion of the reef is analysed; this choice
   should be recorded and justified in the processing report.

2. **Placement is not automated.** Without a target organism or survey stake
   to anchor the window, placement is operator-defined.  Reproducibility requires
   recording the exact chunk-CRS centre coordinates and bearing in the commit that
   writes them to `stage_aoi`.

3. **No cross-validation against T3 belt.** T3 (EDR_T3) is a standard 10×1 m belt
   transect; T1 is an area survey.  Direct comparison of species-count outputs
   across transects requires acknowledging that T1's transect is extracted from an
   area survey, not flown as a dedicated belt.

---

## Alternatives considered

| Option | Disposition |
|--------|-------------|
| Use full 28.9 × 25.4 m bbox as AOI | Rejected — not an ESM analysis unit; OOM risk at 1 cm; P13HMEON comparison undefined |
| Run multiple non-overlapping 10×1 m windows | Out of scope for this processing run; revisit in a follow-on ADR if replicate analysis is needed |
| Let stage_aoi auto-derive from DEM footprint | Not applicable — auto-gate halts on aspect < 5:1 (correct) |
