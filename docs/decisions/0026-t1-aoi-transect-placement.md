# ADR-0026 — T1 AOI: 10×1 m transect placement for an area survey

**Status:** SUPERSEDED by ADR-0028 (Z window corrected 2026-06-10)  
**Date:** 2026-06-10  
**Supersedes:** none  
**Related:** ADR-0020 (LOCAL-CRS DSM/ortho), ADR-0023 (reduce), ADR-0024 (LOCAL-CRS scale),
ADR-0025 (camera-nadir level), ADR-0027 (DSM resolution)

---

## Context

EDR_T1 is an **area survey**, not a belt transect.  The reconstruction bbox is
28.92 × 25.41 × 15.33 m (scale 0.15246 m/unit, LOCAL_CS, ADR-0024).  The camera
flight principal axis is at **135°/315° in the chunk XY frame** (PCA of 2 348 camera
positions, σ_major = 7.98 m, σ_minor = 3.85 m, spread ratio 2.07:1).

The ESM analysis unit (Combs 2021 + Toth 2025 Table S2) is a **10×1 m transect**.
`stage_aoi` auto-gates on aspect ≥ 5:1; T1's bbox aspect is 28.92/25.41 = 1.14:1,
so the gate correctly halts — the transect window cannot be derived automatically
from the flight footprint.

P13HMEON comparison data (firewall: commit 325dbc7) uses the same 10×1 m unit;
comparability requires matching the analysis window to that convention.

The filtered cloud has a mean 2D point spacing of ~1.2 mm (487.7 M pts,
≈ 664 K pts/m²), giving ~6.6 M pts in the 10×1 m footprint — sufficient density for
1 cm DSM (ADR-0027).

---

## Decision

**The AOI for T1 is a single 10×1 m transect**, centred on the region centre
(densest camera coverage), oriented along the 135° principal flight axis.

### Computed AOI box (chunk CRS, LOCAL_CS, metres from chunk origin)

| parameter | value |
|---|---|
| centre | (−2.028, 3.774, −6.477) m |
| long axis (10 m) | (−0.7071, 0.7071, 0) — bearing 135° in chunk XY |
| short axis (1 m) | (−0.7071, −0.7071, 0) — bearing 225° in chunk XY |
| vertical axis | (0, 0, 1) — chunk Z (leveled, ADR-0025) |
| half-extents | (5.000, 0.500, 3.500) m |
| full box | 10 m × 1 m × 7 m |

**XY corners (chunk CRS metres):**

| corner | X | Y |
|---|---|---|
| long+ / short+ | −5.917 | 6.956 |
| long+ / short− | −5.210 | 7.663 |
| long− / short− | 1.861 | 0.592 |
| long− / short+ | 1.154 | −0.115 |

**Z window:** [−9.977, −2.977] m — 7.0 m total.  
Derived from uniform-gradient model: 14.78 m total Z over 27.2 m mean XY extent →
0.543 m/m rate × 10 m = 5.4 m estimated local relief; 7.0 m window adds 29% margin.
Actual local range to be confirmed from first DSM run; update this ADR if the Z
window requires adjustment.

**Rationale for placement:**
- Region centre is the densest camera-overlap zone for an area survey.
- 135° orientation follows the principal flight axis; placing the long dimension
  along-track maximises within-window multi-view consistency in the dense cloud.
- P13HMEON comparability requires the same window geometry and orientation convention.
- The auto-gate halt is correct behaviour: area surveys require deliberate placement.

---

## Full-area ortho (optional, non-standard visualisation product)

A full-area orthomosaic of the 28.92 × 25.41 m footprint may be produced as a
**non-standard site-overview product** — useful for site context, flight-plan QC,
and outreach — but is **not an ESM deliverable** and must not be used as the
analysis AOI.

**DSM resolution constraint for full-area products:**  
`stage_dsm` has an inline 5 M-cell guard.  Full-area cell counts:

| resolution | cells | guard |
|---|---|---|
| 1 cm (ESM standard) | 7 348 572 | **TRIP** |
| 2 cm | 1 836 420 | PASS |
| 3 cm | 816 508 | PASS |
| 5 cm | 293 624 | PASS |

A full-area visualisation DSM/ortho would need resolution ≥ 2 cm (raise or bypass the
guard).  This is a separate deliberate decision; the 1 cm standard applies only to
the 10×1 m transect.

The `stage_ortho` already uses `resolution=0` (native GSD); for a full-area run this
is fine — the ortho step does not hit the DSM cell limit.  The constraining step is
`stage_dsm` for the hillshade/topo context layer.

Label any full-area product clearly as **"EDR_T1 site overview — non-ESM"** to avoid
confusion with the 10×1 m reconciliation product.

---

## Limitations

1. **Single transect from an area survey.** The 10×1 m window is ~1.4 % of the
   735 m² footprint.  Placement affects which portion of the reef is analysed; the
   exact coordinates above and the rationale (region centre, along-track) must be
   reproduced in the processing report.

2. **Placement is not automated.** Without a survey stake or target organism to
   anchor the window, placement is operator-defined.  Reproducibility requires that
   the exact chunk-CRS coordinates in this ADR are the ones written to `stage_aoi`
   without modification.

3. **Z window is model-estimated.** The 7 m Z window is derived from a
   uniform-gradient model, not from a direct point-cloud query.  It is conservative
   (29% margin over the 5.4 m estimate) but should be verified against the first DSM
   and updated if the actual local relief falls outside the window.

4. **No cross-validation against T3 belt.** T3 is a standard 10×1 m belt transect;
   T1's transect is extracted from an area survey.  Any cross-transect species-count
   comparison must acknowledge this distinction.

---

## Alternatives considered

| Option | Disposition |
|---|---|
| Use full 28.92 × 25.41 m bbox as AOI | Rejected — not an ESM unit; 7.3 M cells trips guard at 1 cm; P13HMEON comparison undefined |
| Multiple non-overlapping 10×1 m windows | Out of scope; revisit in follow-on ADR if replicate analysis needed |
| Let stage_aoi auto-derive from DEM footprint | Not applicable — auto-gate correctly halts on aspect < 5:1 |
| Orient transect cross-track (45° / 225°) | Not chosen — along-track aligns with flight pattern and maximises multi-view coverage density within the window |
