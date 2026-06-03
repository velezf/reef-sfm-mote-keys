# ADR 0020 — DEM and Orthomosaic (ESM Steps 14–15) run HEADLESS via a LOCAL chunk.crs + identity Planar projection

Status: Accepted
Date: 2026-06-03
Chat: 5 (T3 production DSM, day 3)
Supersedes: ADR-0019 (DEM/ortho move to the Metashape GUI)

## Context

ADR-0019 routed ESM Steps 14–15 (Build DEM / Build Orthomosaic) to the Metashape
**GUI** on the premise that the headless port was unfixable: ADR-0018 had shown the
proposed per-build `proj.crs = CoordinateSystem()` override to be *unverifiable*
(byte-identical to the default that already triggered the WGS84 backfill), and the
only other lever — a project-wide `chunk.crs` write — was deferred as "runtime
behavior we could not confirm without a build."

On day 2 we **ran that build**, on a disposable copy of the pristine project, and the
premise is now falsified. Steps 14 and 15 **both run cleanly headless.** The working
lever is mutating **`chunk.crs` to a LOCAL coordinate system**, which removes the
spurious-WGS84 source that `buildDem` was backfilling into the projection.

### Crediting the lever honestly

The lever is **`chunk.crs` → `LOCAL_CS` (metre)**, *not* the projection `type`/`matrix`.
The day-2 working hypothesis ("the orphan build set `proj.crs` only, never set
`type`/`matrix`") was **wrong**. The orphan forensic
(`data/qc/chat5/orphan_1857_note.md`) shows the OOM'd 18:54 build had **already set**
`proj.type = Planar` **and** `proj.matrix = chunk.transform.matrix` — and left
**`proj.crs` UNSET**, so it backfilled the chunk's spurious WGS84 (degrees), rasterizing
the whole geographic plane: `generating 3880361604 x 1990188354 dem (0.01 resolution)`
→ ~7.7×10¹⁸ cells → `std::bad_alloc`. So `type`/`matrix` were never the missing piece.
What was missing is a **non-WGS84 output CRS**, and the durable way to guarantee that is
to declare the chunk LOCAL up front; the Planar projection's `crs` then inherits a
local-metric frame and the auto-inferred extent collapses to the point cloud's real
~10×1 m footprint (~1000×100 cells at 1 cm).

The Planar `matrix` is **identity**: for a `LOCAL_CS`, `crs.localframe(origin).rotation()`
is identity, so the top-down planar frame is the identity rotation. Day-2 tested five
`proj.matrix` candidates (identity, `region.rot`, its transpose, `transform.rotation`,
its transpose); **identity is the flattest (24.3°) and the only one that yields the
correct 10×1 m AOI** with relief matching the dense-cloud Z-span. The others give 29–38°
and distort the footprint. "Wrong projection plane" is therefore falsified — the recipe
is correct, and the residual tilt (below) is upstream, not a projection artifact.

## Decision

Build the **DEM (Step 14)** and **Orthomosaic (Step 15)** **headless**, inside the
guarded `run_pipeline.py` entrypoint, with this proven recipe:

```python
# 1) THE LEVER — declare the chunk LOCAL (kills the WGS84 degree-plane backfill → OOM)
chunk.crs = Metashape.CoordinateSystem(
    'LOCAL_CS["Local Coordinates (m)",LOCAL_DATUM["Local Datum",0],UNIT["metre",1]]')
# 2) top-down Planar projection in that local frame (identity for a LOCAL_CS)
top_xy = Metashape.Matrix([[1,0,0],[0,1,0],[0,0,1]])
origin = chunk.transform.matrix.mulp(Metashape.Vector([0,0,0]))
lf     = chunk.crs.localframe(origin)
proj = Metashape.OrthoProjection()
proj.crs    = chunk.crs                          # LOCAL → no WGS84 backfill
proj.type   = Metashape.OrthoProjection.Type.Planar
proj.matrix = Metashape.Matrix.Rotation(top_xy) * Metashape.Matrix.Rotation(lf.rotation())
# 3) Step 14 — DEM, 1 cm (ADR-0017), interpolation ENABLED, from the filtered cloud
chunk.buildDem(source_data=Metashape.PointCloudData,
               interpolation=Metashape.EnabledInterpolation,
               projection=proj, resolution=0.01)
# 4) Step 15 — Orthomosaic on the DEM, SAME proj (co-registers exactly)
chunk.buildOrthomosaic(surface_data=Metashape.ElevationData,
                       blending_mode=Metashape.MosaicBlending,
                       fill_holes=True, projection=proj)   # resolution=0 → image GSD
```

`run_pipeline.py` `stage_dsm` / `stage_ortho` are updated to this recipe, and the
**no-`region=` auto-infer OOM path is removed** — the prior code passed neither a CRS
nor a region and relied on auto-infer over the WGS84 plane (the ADR-0016 "test" that
ADR-0018 confirmed OOMs). A **pre-flight tripwire** (predicted raster cells from the
scaled region; abort if > 5M or any axis > 1M) now hard-guards against any future
projection regression re-triggering the blowup.

## Evidence (proven on a COPY, day 2; gate artifacts in `data/qc/chat5/`)

- **DEM:** `1000 × 100 @ 0.01 m`, extent 10×1 m, origin (−5, 0.5), elevation −1.032 →
  +1.531 m; coverage 98.9% (interp-ON) / 96.94% (interp-OFF, real scattered holes). No
  OOM. Files: `edr_t3_dsm_planartest_interpON.tif` / `…interpOFF.tif`, `…_gate.{png,json}`,
  `…_hillshade*.png`.
- **Ortho:** 144 images blended, peak mem 275 MB; native `2000 × 200 @ 5 mm`, extent
  10×1 m, **co-registered with DEM (dx = dy = 0.0000)**. Files:
  `edr_t3_ortho_planartest_preview.{tif,jpg}`, `…_4xY.jpg`.

Both built on `/data/edr_work/edr_t3_planartest.psx` (a copy), **never saved**; the
pristine `edr_t3.psx` (sha256 `ed86a3b4…80182f`) was untouched.

## Consequences

- **The whole pipeline is headless again**, including Steps 14–15. ADR-0019's manual GUI
  step is removed; batch/v2 re-automation is no longer blocked. Faithfulness to Toth et
  al. 2025 ESM (local planar, top-down, interpolated, 1 cm) is preserved — the GUI's
  transparent local-frame projection is now reproduced explicitly headless.
- **The OOM footgun is closed in code**, not just avoided by convention: the WGS84
  auto-infer path is gone and the tripwire aborts a bad projection before allocation.
- **A residual ~24° plane tilt is inherent to the day-1 Step-11 frame placement**, is
  method-independent (a GUI DEM of the same region reproduces it), and is therefore
  **out of scope for this ADR** (it concerns the *product*, not the build method). It is
  adjudicated separately against the published P13HMEON reference DEM (TILT-NOW); identity
  is already the flattest projection, so a leveling error — if confirmed — must be fixed
  upstream (re-level Step 11), not in the build.
- **ADR-0019 preserved as history**: the GUI decision and its premise remain valuable
  writeup/PFP material alongside the orphan forensic.

## Sources

- ADR-0019 (superseded) — the GUI decision and its (now-falsified) "headless-unfixable"
  premise.
- ADR-0018 — buildDem WGS84-backfill mechanism; the unverifiable per-build `proj.crs` fix.
- `data/qc/chat5/orphan_1857_note.md` — forensic proving the OOM'd build set
  `type=Planar` + `matrix=transform.matrix` with `proj.crs` UNSET (the WGS84 backfill).
- ADR-0017 — DEM resolution 0.01 m.
- ADR-0016 — buildDem extent vs point-cloud extent; the no-region auto-infer risk.
- Toth et al. 2025 ESM Table S2, Steps 11 / 14 / 15.

#tags: metashape-headless, builddem, buildorthomosaic, dsm, ortho, local-crs, planar-projection, wgs84-backfill, oom, step-14, step-15, toth-esm, supersedes-adr-0019, adr-0018-followup, chat5
