# ADR-0029 — Full-area ortho built PointCloudData-direct; portfolio-only, NOT ESM Step 15

**Status:** Accepted
**Date:** 2026-06-10 (decided Chat 5; file backfilled 2026-06-11 from the CLAUDE.md record)
**Supersedes:** none
**Related:** ADR-0020 (headless DEM/ortho via LOCAL_CS), ADR-0027 (DSM 1 cm), ADR-0028 (corrected Z window)

---

## Context

ESM Step 15 builds the orthomosaic **from the DEM surface**. The 10×1 m
**transect** ortho follows that path and is compliant: DSM (ADR-0027/0028)
→ ortho, 2000×200 px @ 5 mm GSD, sha `e86deb03…`.

Separately, a **full-area** ortho of the whole EDR_T1 survey (28.9 × 25.4 m)
was wanted as a portfolio/context visual. The compliant route — full-area
`buildDem` first — **hangs in Metashape 2.3.1 (build 22446) on the
487,749,550-pt filtered cloud: 3 confirmed runs**, no error, no progress, no
completion. Root cause is open (not reproduced on the small transect-window
DEM, which builds fine).

## Decision

Build the full-area ortho **PointCloudData-direct** — `buildOrthomosaic`
surfaced directly on the point cloud instead of a DEM:

- Product: `edr_t1_fullarea_ortho_20260610T210155Z.tif`, 1764×1383 px @ 2 cm,
  sha `e03dbf7e…`, MANIFEST `a9337f3`.
- **Status of the product: portfolio visual only.** It is explicitly **NOT**
  the ESM Step-15 product and must never be cited as one; the divergence is
  recorded here and in the product MANIFEST.
- The **transect ortho is unaffected** — it stays DEM-sourced and
  ESM-compliant.

## Consequences

- (+) A full-area visual exists without blocking Chat-5 closeout on a
  Metashape defect we don't control.
- (−) **No full-area DEM exists.** If one is ever needed (it is not needed
  for reconciliation, which runs on the transect DSM), the open options are:
  coarser resolution (≥ 5 cm), chunked export + external DEM build, or a
  Metashape version update. Tracked as an open follow-up.
- (−) Point-cloud-direct orthorectification uses a different surface model
  than DEM-based; the full-area ortho's geometry is not comparable to the
  transect ortho's and must not be measured from.
- (~) The `buildDem` hang root cause stays open; 3 runs is enough to stop
  retrying the same configuration but not enough to file a confident
  upstream bug report.

#tags: t1, ortho, builddem, hang, pointclouddata, esm-step-15, divergence, portfolio
