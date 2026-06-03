# Orphan DEM forensic — 18:57 interrupted build (Chat 5)

**Question answered (bounded):** did the 18:57 orphan blow up from RESOLUTION or from EXTENT?
**Answer: EXTENT blowup — the projection did NOT hold.**

## Evidence
- **Attempted grid dims (Metashape log, prior session transcript):**
  `generating 3880361604x1990188354 dem (10 levels, 0.01 resolution)`
  → **3,880,361,604 × 1,990,188,354 cells** (≈ 7.7×10¹⁸), 10 pyramid levels.
- **Pixel size / resolution param:** 0.01 (as requested). Applied in the projection
  plane's units. At 0.01/cell, 3.88e9 cells ⇒ ~3.9×10⁷-unit extent in X — i.e. the
  whole WGS84 lon/lat plane, not a 10 m transect.
- **Orphan CRS (elevation.dat header):** `GEOGCS["WGS 84" ... UNIT["degree" ...
  AUTHORITY["EPSG","4326"]]` — the spurious WGS84 chunk.crs, **degrees**, NOT a
  local/none planar SRS.
- **Outcome:** `MemoryError: std::bad_alloc` (OOM) — build died mid-allocation,
  leaving a partial artifact: `elevation.dat` (579 B) + `tiles.grp` (1.17 GB).
- **Stored .dat bbox** = [-5,-0.5]…[5,0.5], res 0.01 — written by a *second* ad-hoc
  attempt (region2d, 18:57:02) that overwrote the metadata; the 1.17 GB `tiles.grp`
  is the projonly partial. The orphan is therefore inconsistent (region2d .dat +
  projonly tiles) → garbage, safe to discard.
- Sanity baseline this session: dense world-Z span = 2.98 m; pc world extent
  ~10.4 × 1.4 m. Expected local-planar DEM @0.01 m ≈ 1040 × 141 (~147k cells).
  The build attempted ~5×10¹³× that — not a sub-mm-resolution-on-10×1 m bug.

## Originating command (ad-hoc — this is why ad-hoc is banned here)
`/tmp/build_dsm_projonly.py`, run 18:54 via `/opt/metashape-pro/metashape.sh -r`
(NOT the guarded pipeline, NO log file written):
```python
proj = ms.OrthoProjection()
proj.type   = ms.OrthoProjection.Type.Planar
proj.matrix = chunk.transform.matrix      # proj.crs LEFT UNSET → defaulted to chunk.crs = WGS84
chunk.buildDem(source_data=ms.PointCloudData, interpolation=ms.EnabledInterpolation,
               projection=proj, resolution=0.01)   # no region
```
Followed at 18:57 by `/tmp/build_dsm_region2d.py` (same proj, region=BBox([-5,-0.5],[5,0.5])).

## Conclusion & implication for Step 2
A Planar projection with `matrix=chunk.transform.matrix` but **`proj.crs` left unset
inherits the chunk's WGS84 (degree) CRS** — so buildDem rasterizes the entire
geographic plane → billions of cells → OOM. This "constructs cleanly ≠ projects
correctly" exactly. **Step 2 as written (projection-only, matrix=transform, crs not
explicitly set) would REPRODUCE this blowup**; only the new >5M-cell pre-check would
abort it. The real fix is to set the projection's output CRS to **local/empty**
(no EPSG:4326), so the planar matrix yields a local-metric ~1040×141 grid.
