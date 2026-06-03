# ADR 0019 — DEM and Orthomosaic build (ESM Steps 14–15) move to the Metashape GUI; the rest of the pipeline stays headless

Status: Superseded by ADR-0020 (2026-06-03)
Date: 2026-06-02
Chat: 5 (T3 production DSM)

> **Superseded.** The premise here — that headless Steps 14–15 were unfixable — was
> falsified on day 2: declaring `chunk.crs` LOCAL removes the WGS84 backfill and both
> steps run cleanly headless. See ADR-0020. This ADR is retained as history (the GUI
> decision and the orphan-forensic counterfactual remain useful writeup/PFP material).

## Context

ADR-0018 established the precise mechanism by which the **headless** port of ESM
Step 14 (Build DEM) failed: `OrthoProjection.crs` left unset → `buildDem` backfills
the projection CRS from the chunk's spurious `WGS 84 / EPSG:4326` → it rasterizes the
geographic plane (`generating 3880361604 x 1990188354 dem`, ~38,800 km ≈ Earth's
circumference at 0.01 m) → `std::bad_alloc`.

The surgical headless fix that ADR-0018 proposed — assign `proj.crs =
Metashape.CoordinateSystem()` (empty/local) per build — was investigated to ground
truth and shown **unverifiable**: via 2.3.1 `help()`, `Metashape.CoordinateSystem()`
is byte-identical to the default `OrthoProjection().crs` that already triggered the
backfill, with no observable signal that an explicit assignment suppresses it. The
only reliably-local headless levers are to mutate `chunk.crs` (a project-wide CRS
write) or to keep poking at undocumented behavior — neither cheap nor faithful.

Meanwhile the **published method we are reproducing is itself a GUI workflow.** Toth
et al. 2025 (ESM Table S2) runs Build DEM and Build Orthomosaic in the Metashape GUI,
where a model placed in a local coordinate frame (Step 11, USGS Alignment Helper) gets
the correct local-planar top-down projection **transparently** — exactly the behavior
the headless port was fighting to reconstruct.

## Decision

Build the **DEM (ESM Step 14)** and **Orthomosaic (ESM Step 15)** in the **Metashape
Professional GUI over DCV**:

- **Step 14 — Build DEM:** Source = Point cloud, Interpolation = Enabled, region set to
  the **10×1 m AOI** (edge-noise trim), resolution = **0.01 m** (ADR-0017), all other
  settings default.
- **Step 15 — Build Orthomosaic:** Surface = DEM, Blending = Mosaic, Enable hole filling.

Everything else **remains headless** and is already done or scripted: image-quality
filter (Step 4), alignment, dense cloud (Step 12), error reduction, scaling, frame
placement (Step 11), the Step-13 confidence filter (ADR-0015), and — after the GUI
build — QC, the product exports, the provenance manifest, and the Chat-6 metric
reconciliation.

**Alternatives considered, not chosen:**
- *Per-build `proj.crs` override* (ADR-0018 Decision): withdrawn — unverifiable (above).
- *Mutate `chunk.crs` to a local CRS so the default projection is correct headless:* a
  project-wide write whose runtime behavior we still could not confirm without a build;
  deferred. May be revisited if Steps 14–15 must be re-automated for batch/v2.

## Consequences

- **Faithfulness improves, not degrades.** The headless port of Steps 14–15 was
  self-imposed; reverting that one piece matches Toth et al. 2025 ESM Table S2 *more*
  closely. The DEM/ortho are produced the published way: local planar, top-down,
  10×1 AOI, interpolated, 1 cm.
- **Manual step in an otherwise automated pipeline.** Steps 14–15 now require a human
  at the GUI; documented in `docs/05-metashape-processing.md` (automated vs GUI-only).
  Acceptable for a single-transect dress rehearsal; a re-automation path is noted above
  if batch processing is needed later.
- **Reproducibility is preserved** by recording exact GUI settings here and in the
  resume doc, plus the headless exports/provenance manifest capturing the resulting
  DEM/ortho parameters.
- **Preserved as evidence / writeup material:** `data/qc/chat5/orphan_1857_note.md`
  (the WGS84-default counterfactual forensic) and ADR-0018 (the API-mechanism record).
  Good content for the Chat-8 writeup and the PFP proposal.

## Sources

- ADR-0018 (this directory) — buildDem WGS84-backfill mechanism + the unverifiable
  per-build fix.
- `data/qc/chat5/orphan_1857_note.md` — forensic of the interrupted ad-hoc build.
- Toth et al. 2025 ESM Table S2, Steps 11 / 14 / 15 — GUI Build DEM / Build Orthomosaic
  on a local-frame chunk.
- ADR-0017 — DEM resolution 0.01 m.
- ADR-0001 — Amazon DCV (the GUI access path).

#tags: metashape-gui, builddem, buildorthomosaic, dsm, ortho, dcv, step-14, step-15, toth-esm, local-frame, wgs84-crs, adr-0018-followup, headless-vs-gui, chat5
