# ADR 0018 — `buildDem`/`buildOrthomosaic` OOM caused by a spurious WGS84 (EPSG:4326) CRS on a local no-GPS chunk: build the DSM/ortho with an explicit LOCAL PLANAR projection clamped to the 10×1 m AOI; supersedes ADR-0016's coordinate-space open question

Status: Accepted **as the API-mechanism record only**. The per-build projection fix it proposed was investigated and **withdrawn as unverifiable** (see *Final amendment*); DEM/ortho build is moved to the Metashape GUI per **ADR-0019**. The reverted `run_pipeline.py` dsm-stage diff was **not committed**.
Date: 2026-06-02 (final amendment same day, end-of-day close)
Chat: 5 (T3 production DSM)

> **Amendment note (read first):** an earlier draft of this ADR diagnosed the OOM
> as *geometric outlier points ~10⁷ m from origin* and proposed a two-lever fix (a
> `region=` BBox + a destructive dense crop). **That diagnosis was falsified by the
> retry it motivated** and is recorded here honestly, the same way ADR-0016's
> prediction was. The crop (Lever 2) was a **3,294-of-17.5M-point no-op** and is
> removed entirely. The real cause and the corrected fix are below.

> ## Final amendment (end-of-day close, 2026-06-02) — read this before the Decision section
>
> The **Decision** below (a per-build `proj.crs = local ''` projection override) was
> investigated to ground truth and **withdrawn**. Two findings settled it:
>
> 1. **Precise root cause (sharper than "default projection uses the chunk CRS"):**
>    `OrthoProjection.crs` was **left unset**. At build time `buildDem` **backfills the
>    projection's CRS from `chunk.crs`** (the spurious `WGS 84 / EPSG:4326`), then
>    rasterizes the **geographic plane** — `generating 3880361604 x 1990188354 dem
>    (10 levels, 0.01 resolution)`, i.e. ~3.88e9 x 1.99e9 cells, an extent of
>    ~38,800 km (about Earth's circumference) at 0.01 m — to `std::bad_alloc`. The
>    forensic of the interrupted ad-hoc build is in
>    `data/qc/chat5/orphan_1857_note.md`.
> 2. **The proposed surgical fix cannot be verified to work.** Confirmed via 2.3.1
>    `help()`: `Metashape.CoordinateSystem()` is **byte-identical** to the default
>    `OrthoProjection().crs` (`<CoordinateSystem ''>`; `wkt`/`authority`/`name` all
>    empty). The failing ad-hoc build *also* left `proj.crs` at that same empty default,
>    so assigning it empty *explicitly* is indistinguishable from doing nothing — there
>    is no observable signal (repr, wkt, authority) that an explicit assignment sets an
>    internal "was-set" flag suppressing the `chunk.crs` backfill. The only reliably
>    local levers are to **mutate `chunk.crs`** (a project-wide write — the "Alternative
>    considered, not chosen" below) or to build in the **GUI**, which handles the
>    local-frame projection transparently.
>
> **Disposition:** DEM (ESM Step 14) and Orthomosaic (ESM Step 15) move to the
> **Metashape GUI over DCV** per **ADR-0019**. Everything else (alignment, dense cloud,
> error reduction, scaling, frame placement, Step-13 filter, QC, exports, provenance)
> stays headless. ADR-0018 is retained as the **API-mechanism record** — the precise
> reason the headless port of Steps 14–15 failed. The mechanism notes below remain
> accurate; the 2D-BBox region form (`[-5,-0.5]…[5,0.5]`) is the GUI's edge-noise
> bounding box. The reverted `run_pipeline.py` dsm-stage diff was **not committed**.

## Context

T3 post-frame pipeline on the scaled, Alignment-Helper-framed `edr_t3.psx`:
- `dense` (Step 12): 22,683,375 pts. `filter` (Step 13, conf<2): → 17,519,650. Both saved.
- `dsm` (`buildDem` @0.01 m, no projection/region): **`MemoryError: std::bad_alloc`**,
  log line `generating 3880361604x1990188354 dem (… 0.01 resolution)`.

Two attempts were made and both produced evidence, not just outcomes:
1. **Retry A** (region=internal-coord BBox + destructive AOI crop): the crop removed
   **only 3,294 / 17,519,650** points (extent unchanged), and `buildDem(region=BBox)`
   raised **`ValueError: Invalid argument value: region`**.
2. A **read-only probe** then measured the actual coordinate spaces (no build).

## Diagnosis (corrected, evidence-based — supersedes the outlier theory)

The chunk carries a **spurious geographic CRS: `WGS 84 (EPSG:4326)`** — a Metashape
default applied to a no-GPS chunk (this dataset has no capture-time GPS; ADR-0007/0009).
`buildDem`'s default output projection uses that CRS, so a 1 cm resolution over a
~10 m *local* frame is mis-scaled through a degrees↔meters mismatch into a
~38,800 km × ~19,900 km grid → 7.7×10¹⁸ cells → `bad_alloc`.

Probe evidence (read-only, project not modified):

| Quantity | Value |
|---|---|
| `chunk.crs` | **WGS 84 (EPSG:4326)** ← spurious |
| `transform.scale` / rotation / translation | 0.236959 / real Jenkins rotation / [-0.65,-1.01,1.37] m |
| `pc.extent()` **internal** | 12.56 × 37.40 × 21.18 units |
| `pc.extent(transform.matrix)` **world/metric** | **10.39 × 1.41 × 2.97 m** (a clean transect) |
| cells @0.01 from internal extent | 1256 × 3740 (not what happened) |
| cells @0.01 from world-metric extent | 1039 × 141 (the right ballpark) |
| **`buildDem` actually used** | **~3.88e7 × 1.99e7 m** (neither — the WGS84 misprojection) |
| `chunk.region` world AABB | **exactly [-5,-0.5,-2.5] … [5,0.5,2.5] m = 10 × 1 × 5 m, axis-aligned** |

So: (a) there are **no** ~10⁷ m outlier points — `pc.extent()` is a tidy ~10×1.4×3 m;
(b) the crop was a near-no-op because the cloud is already the AOI; (c) the internal
BBox was rejected because `buildDem` wants the region in the **projection's** CRS, not
internal units; (d) the 10⁶× gap is the geographic CRS, exactly ADR-0016's unresolved
"what coordinate space does `buildDem` use?" question — now **resolved: the chunk CRS.**

## Faithfulness to Toth et al. 2025 ESM Table S2

The corrected fix is not just a workaround — it realigns us **with** the published pipeline:
- **Step 11:** models are placed in a user-defined **local** coordinate system (USGS
  Alignment Helper). A local **planar** projection is the faithful target, and is what
  Toth's GUI *Build DEM* defaults to on a local-frame chunk. Our headless build diverged
  by using the chunk's spurious WGS84 CRS.
- **Step 14 (Build DEM):** "Source data: Point cloud, Interpolation: Enable," and
  "Bounding box was set to remove edge noise and only include the 10×1 m area of
  interest." → **region = the 10×1 m AOI is Toth's method** (edge-noise removal), not an
  add-on; the DSM is a top-down x,y,z elevation raster, so the planar plane must look
  straight down the leveled world Z.
- **Step 15 (Build Orthomosaic):** surface = DEM, Mosaic blending, hole filling, same
  local frame → the **same** planar projection on `buildOrthomosaic`.

This matters because Chat 6 reconciles our DEM against Toth's published complexity metrics
(ESM Fig S5: Elevation, Rugosity, SAPA, VRM, RIE, ASD over 5×5 cm focal windows) and the
P13HMEON reference data. A like-for-like comparison requires the DEM be built their way:
**planar, local, 10×1 AOI, interpolated, 1 cm.**

## Decision

Override the projection per-build (surgical, no project-wide write):

- `proj = OrthoProjection(type=Planar, matrix=chunk.transform.matrix, crs=local '')`
  — internal→leveled-world frame; elevation along the leveled world Z (true top-down).
- `buildDem(source_data=PointCloud, interpolation=Enabled, projection=proj,
  region=<world-metric BBox of chunk.region = 10×1×5 m>, resolution=0.01)` (1 cm, ADR-0017).
- `buildOrthomosaic(surface=DEM, projection=proj, region=<same>, blending=Mosaic,
  fill_holes=True)` (ESM Step 15).
- **Crop (Lever 2) removed entirely** — confirmed no-op; the cloud is already the AOI.

**Alternative considered, not chosen:** set `chunk.crs` to a local coordinate system so
the *default* projection is already correct. This is more fundamental but is a project-wide
CRS **write**; the per-build projection override is surgical, reviewable, and avoids
mutating the saved chunk. (Recorded as the option if we later want the GUI/default to behave.)

## Expected result / apply-time guard

The world-frame region is **axis-aligned** (Jenkins placement), so there is **no yaw
widening**: the grid should be **~1000 × 100 (X × Y) at 1 cm** — NOT billions, and NOT
~200. The guard on the next (approved) build is the `generating WxH dem` log line reading
~1000 × ~100. Top-down orientation is corroborated by the region world AABB being exactly
axis-aligned with Z (5 m) as the vertical dimension and the leveling check (tie-point Z is
the smallest extent).

## Consequences

- DSM/ortho build in the faithful local planar frame at 1 cm over the 10×1 AOI — Chat-6
  reconciliation is like-for-like.
- ADR-0016's open question (coordinate space of `buildDem`) is **resolved**: the chunk's
  spurious WGS84 CRS. ADR-0016's production-safety prediction stays superseded.
- The earlier-draft destructive crop is gone; the failed-retry project carries a no-op
  crop (−3,294) + a now-unused `edr.aoi_cropped` meta flag → roll back to the pre-crop
  backup `edr_t3_20260602T160517Z` before the corrected build for a pristine 17,519,650-pt
  cloud.
- **Not yet verified at runtime** (no build performed): that `buildDem`/`buildOrthomosaic`
  *accept* this exact projection/region (any accepted-arg call proceeds to build, which is
  held for review). The validation layer raises *before* `generating WxH`, so acceptance is
  a fast-fail check at the approved run.

## API basis (Metashape Professional 2.3.1 build 22446, bundled `help()`)

- `Chunk.buildDem(source_data, interpolation, [projection: OrthoProjection],
  [region: BBox], resolution[m], …)`; region omitted ⇒ fits to source extent **in the
  projection's CRS**.
- `Chunk.buildOrthomosaic(surface_data, blending_mode, fill_holes, [projection],
  [region], …)` — same projection/region overrides available.
- `OrthoProjection`: `type` (Planar/Cylindrical), `matrix` (4×4), `crs` (default local '');
  default instance is `type=Planar, crs=''`.
- `PointCloud.extent([transform]) -> BBox`; `selectPointsByRegion(Region)` /
  `cropSelectedPoints()` (the crop idiom, now unused).

## Sources

- Bundled Metashape 2.3.1 Python `help()` (buildDem / buildOrthomosaic / OrthoProjection /
  PointCloud signatures) — this session.
- Toth et al. 2025 ESM Table S2, Steps 11 / 14 / 15 (local CRS via Alignment Helper;
  Build DEM point-cloud + interpolation + 10×1 AOI bounding box; Build Orthomosaic).
- Agisoft forum, "resize region (or generate BBox) to/from dense cloud extent?"
  https://www.agisoft.com/forum/index.php?topic=13317.0
- Agisoft forum, "[Updated Solution] Resize bounding box/region to sparse point cloud"
  https://www.agisoft.com/forum/index.php?topic=14034.0
- Agisoft Metashape User Manual 2.3 (local planar projection; Build DEM/Orthomosaic;
  region tools) https://www.agisoft.com/pdf/metashape_2_3_en.pdf

#tags: metashape-api, builddem, buildorthomosaic, dsm, ortho, wgs84-crs, coordinate-space, ortho-projection, planar, local-frame, aoi-region, step-11, step-14, step-15, toth-esm, adr-0016-superseded, adr-0017-resolution, chat5
