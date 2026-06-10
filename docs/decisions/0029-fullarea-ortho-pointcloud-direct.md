# ADR-0029 — Full-area ortho built PointCloudData-direct (ESM Step 15 deviation)

**Status:** ACCEPTED  
**Date:** 2026-06-10  
**Deviates from:** ESM Step 15 (Toth 2025 Table S2: DEM → orthomosaic)  
**Related:** ADR-0015 (confidence filter), ADR-0020 (LOCAL-CRS), ADR-0026/0028 (T1 AOI)

---

## Context

The Combs 2021 / Toth 2025 ESM pipeline calls for an orthomosaic built on the
reconstructed DEM surface (Step 15: `buildOrthomosaic(surface_data=ElevationData)`).
For the EDR_T1 **full-area site-overview product** (the 28.92 × 25.41 m footprint,
not the 10×1 m transect), a DEM-sourced ortho requires first building the full-area
DEM via `buildDem`.

**`buildDem` hangs indefinitely on the 487M-pt filtered cloud in Metashape 2.3.1.**
Three independent confirmed runs:
- All three ran to "base level interpolated" (the pyramid stage completes in < 1 s)
  then hung indefinitely — processes killed manually after 1.5–4+ h each
- The hang occurs after the rasterize/pyramid step; Metashape 2.3.1 appears to
  compute expensive per-point statistics post-pyramid on very large clouds

Root cause is not fully diagnosed.  Working hypothesis: a Metashape 2.3.1 regression
in the post-pyramid interpolation pass that is quadratic in point count above some
threshold.  The WGS84 → LOCAL reprojection triggered by `chunk.crs = LOCAL_CS_WKT`
with a loaded dense cloud was ruled out as the primary cause (removing that assignment
did not resolve the hang).

---

## Decision

For the **full-area site-overview product only**, build the ortho from
`PointCloudData` directly rather than `ElevationData`:

```python
chunk.buildOrthomosaic(
    surface_data=Metashape.PointCloudData,   # deviation
    blending_mode=Metashape.MosaicBlending,
    fill_holes=True,
    resolution=0.02,                          # 2 cm; explicit to avoid sub-mm hang
    projection=proj,
)
```

The `chunk.crs` assignment is also omitted (the CRS is already LOCAL, set by
`stage_scale`; reassigning it with the 487M cloud loaded triggers an expensive
reprojection even when the value is unchanged).

Script: `scripts/metashape/build_fullarea_visual.py` — committed off the instrumented
pipeline (direct API, not `--stage`), fully regenerable.

---

## Scope and boundaries

This deviation applies **only to the full-area site-overview product**.  It does NOT
affect the ESM transect products:

| Product | Surface data | Status |
|---------|-------------|--------|
| `edr_t1_fullarea_ortho_<UTC>.tif` | `PointCloudData` | **Deviation (this ADR)** |
| `edr_t1_transect_dsm_<UTC>.tif` | — | DEM (no deviation) |
| `edr_t1_transect_ortho_<UTC>.tif` | `ElevationData` (DEM) | **ESM Step 15 compliant** |

The transect ortho is built via `stage_ortho` in the instrumented pipeline using
`surface_data=Metashape.ElevationData` on the 26.5M-pt cropped cloud (the 10×1×11 m
OBB, ADR-0028).  The DEM build over 26.5M pts completes in < 1 s and does not hang.
The Step 15 deviation is therefore isolated to the site-overview product, which is
not an ESM deliverable.

---

## Impact on product interpretation

- **Geometric fidelity:** A PointCloudData ortho projects each image pixel onto the
  nearest visible point in the dense cloud, rather than onto an interpolated DEM
  surface.  For a smooth carbonate reef at 2 cm resolution, the practical difference
  is sub-pixel.  Occlusions from vertical surfaces are handled identically.
- **Radiometry:** Unchanged — blending mode and hole-fill are the same.
- **Labeling:** The product is labeled `edr_t1_fullarea_ortho_<UTC>.tif` and
  documented in MANIFEST as a non-ESM site-overview product.  It must not be used as
  the ESM Step-15 deliverable.

---

## Open items (out of scope this pass)

- **buildDem root cause:** The Metashape 2.3.1 post-pyramid hang is not fully
  diagnosed.  If a fix or workaround is found (e.g., chunked export + external DEM,
  or a Metashape update), re-running the full-area DEM build would allow replacing the
  PointCloudData ortho with a DEM-sourced one.  This ADR would then be superseded.
- **Full-area DEM as context layer:** A full-area hillshade/topo product is desirable
  for site orientation.  Options if buildDem remains broken: (a) coarse resolution
  (≥ 5 cm) may avoid the hang; (b) external gridding from an exported LAZ subset.

---

## Records

- Product on disk: `artifacts/rasters/edr_t1_fullarea_ortho_20260610T210155Z.tif`
- Dimensions: 1764 × 1383 px at 0.020 m/px
- Footprint (LOCAL_CS): X [−22.783, +12.497] m, Y [−9.540, +18.120] m (35.3 × 27.7 m)
- Source: `build_fullarea_visual.py` run 2026-06-10T21:01:55Z against the
  post-dense, pre-filter 487M-pt cloud (`edr_t1.psx` at that timestamp)
- sha256: `e03dbf7eabc95685bc547c8bceec30d5462567d1f414c5e73b7a6d7192b6453b`
- MANIFEST: `chore/portfolio-artifacts`, commit `a9337f3`
