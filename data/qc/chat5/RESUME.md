# RESUME — EDR_T3 Metashape processing (Chat 5, day-1 stop)

**Stop:** 2026-06-02, end of day (UTC just past midnight into 06-03).
**Tag:** `chat5-day1-stop-20260602`
**Instance:** `i-06fe7879a0e713c2f` (us-east-1).

---

## Current state (verified, pristine)

Project `/data/edr_work/edr_t3.psx` restored from the intact pre-crop backup and
re-verified read-only:

| Check | Value |
|---|---|
| `point_count` | **17,519,650** |
| `chunk.elevation` | **None** (no DEM) |
| `num_orthomosaics` | **0** |
| `chunk.crs` | `WGS 84 (EPSG:4326)` — spurious default on a no-GPS chunk (see ADR-0018) |
| orphan elevation dir / stale lock | **removed** |

- **Pristine backup (do not touch):** `/data/edr_work/backups/edr_t3_20260602T160517Z`
  (17,519,650-pt filtered cloud, no DEM, no crop).
- Done & headless: image-quality filter (Step 4), alignment, dense cloud (Step 12),
  error reduction, scaling, frame placement (Step 11), Step-13 confidence filter
  (ADR-0015). The headless `run_pipeline.py` dsm-stage fix attempt was **reverted**
  (not committed).

## Decision (this stop)

**DEM + Orthomosaic (ESM Steps 14–15) are built in the Metashape GUI over DCV
(ADR-0019).** The headless port failed because `OrthoProjection.crs` left unset makes
`buildDem` backfill the chunk's WGS84 CRS and rasterize the whole geographic plane
(~3.88e9 × 1.99e9 cells → `std::bad_alloc`); the surgical per-build fix was shown
unverifiable (ADR-0018 final amendment). Everything except Steps 14–15 stays headless.

## Next session — concrete steps

a. **SSH in, start DCV**, open `/data/edr_work/edr_t3.psx` in Metashape Pro (GUI).
   Confirm the chunk shows 17,519,650 points and no DEM/ortho before building.
b. **ESM Step 14 — Build DEM:** Source data = **Point cloud**, Interpolation =
   **Enabled**, **region set to the 10×1 m AOI** (edge-noise trim), resolution =
   **0.01 m** (ADR-0017), all other settings default. Expect a sane ~1000×100-ish
   raster — NOT billions of cells.
c. **ESM Step 15 — Build Orthomosaic:** Surface = **DEM**, Blending = **Mosaic**,
   **Enable hole filling**.
d. **Resume headless for exports/provenance:** DSM TIFF, ortho TIFF, sparse + dense
   PLY, camera poses JSON, scale-bar list with errors, HTML processing report +
   report-as-JSON (for Chat-6 provenance). Then take an **EBS data-volume snapshot**.
e. **Update `docs/05-metashape-processing.md`:** what is automated vs GUI-only
   (Steps 14–15 per ADR-0019), referencing Toth et al. 2025 ESM Table S2.

## Pointers

- `docs/decisions/0019-dem-ortho-build-in-metashape-gui.md` — the GUI decision.
- `docs/decisions/0018-builddem-region-clamp-and-dense-aoi-crop.md` — the API mechanism
  record (WGS84 backfill; why the headless fix was withdrawn).
- `data/qc/chat5/orphan_1857_note.md` — forensic of the interrupted ad-hoc build
  (the WGS84-default counterfactual; good Chat-8 / PFP-proposal material).
- This file: `data/qc/chat5/RESUME.md`.

## Trial clock

Metashape trial ends **~2026-06-27** → **~25 days remaining** from this stop
(2026-06-02). Plan GUI Steps 14–15 + exports well inside that window.
