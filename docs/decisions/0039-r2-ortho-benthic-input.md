# ADR-0039 — R2 orthomosaic built 2026-06-23 as benthic-project input

**Status:** Accepted
**Date:** 2026-06-23
**Extends:** ADR-0033 (Option-2 R2 reconstruction), ADR-0036 (Zero-pitch frame)
**Related:** ADR-0038 (capture-audit; orientation/reversal UNVERIFIED)

---

## Headline: footprint offset

**Ortho footprint (9.99 × 0.995 m) ≠ canonical DSM footprint (10.07 × 1.00 m, sha `dcec116b`).**

~8 cm shorter along-track. ~5 mm narrower cross-track. Both products are
co-registered in the zero-pitch frame (LOCAL\_CS, same coordinate origin) but
are **not pixel-coincident** — different resolutions (5 mm ortho vs 1 cm DSM)
and different extents. Any downstream workflow that overlays cover classifications
from the ortho onto DSM geometry **must resample to a common grid**: snap to the
canonical DSM (`dcec116b`, 1 cm grid, bilinear interpolation for the ortho).

---

## Context

After the T1\_R2 zero-pitch reconstruction (ADR-0036) was settled and the trial
license was still live, the orthomosaic was exported as a captured input for the
planned benthic-cover classification project (`reef_sfm_provenance` ADR-0030 scope
extension). The canonical geometry product is and remains the clipped 10×1 DSM
(`dcec116b`). The ortho is a companion, not a replacement.

The internal DEM Metashape used to project the ortho is the in-project surface at
999×100 @ 1 cm — not the exported canonical DSM. This is why the ortho footprint
and the canonical DSM footprint differ: the canonical DSM was clipped to symmetric
10×1 m; the ortho was projected on the unclipped internal DEM and came out 9.99 m.

---

## Decision

### 1. Ortho is a captured input, not a pipeline product

The ortho was exported during trial availability specifically to preserve it for
downstream use. It is not part of the reconstruction QC pipeline (ADR-0031), does
not get a gate result, and is not included in the reconciliation (ADR-0032).
Its provenance is captured here and in `reports/manifest_edr_t1_r2.yaml`.

### 2. Footprint offset is characterized and documented — not corrected

The 8 cm / 5 mm mismatch between ortho and canonical DSM extents is:
- **Not a registration error.** Both products were exported from the same
  zero-pitch chunk in `edr_r2_q030_zeropitch_20260617.psx`.
- **Not fixable without re-exporting.** The ortho footprint is set by the internal
  DEM extent used during export; the canonical DSM was clipped after export.
- **Characterized and stable.** The sha256 is locked (`32e971d3…`). The offset
  is recorded in the manifest and this ADR.

The correction is downstream: resample, don't re-export.

### 3. Resampling instruction for downstream use

When combining ortho-derived cover with DSM-derived geometry:

```
Reference grid : canonical DSM dcec116be19a5c74d53f45e07454bdb0ee980ba3d40c9a5f142f5bdcfff8f369
  dims         : 1007×100 px
  resolution   : 0.01 m (1 cm)
  CRS          : LOCAL_CS zeropitch frame

Ortho input    : edr_t1_r2_q030_zeropitch_ortho_20260623.tif (sha 32e971d3…)
  dims         : 1998×199 px
  resolution   : 0.005 m (5 mm)
  resampling   : bilinear (continuous RGB; not nearest-neighbor)
```

Output: ortho resampled to 1007×100 at 1 cm, aligned to the canonical DSM origin.
Any pixels in the canonical DSM grid that fall outside the ortho extent (up to ~8
pixels on the along-track edge) will be nodata in the resampled ortho.

### 4. Source lineage

```
edr_t1_r2_q030_zeropitch_ortho_20260623.tif  ← exported (TIFF, 4-band RGBA)
  └─ from edr_r2_q030_zeropitch_20260617.psx  ← WORK COPY, NEVER WRITTEN
       └─ zero-pitch rotation applied (ADR-0036)
            └─ edr_r2_q030.psx  ← master Q030, DO NOT WRITE
                 └─ edr_r2.psx  ← Q050 foil, NEVER OPEN
```

Data EBS snapshot covering the ortho: `snap-01d7a140ed04a151e`
(tag: `edr_r2_zeropitch_ortho_20260623`).

### 5. Build parameters

| Parameter | Value |
|-----------|-------|
| Surface | ElevationData (internal zeropitch DEM, 999×100 @ 1 cm) |
| Blending | MosaicBlending |
| Fill holes | True |
| Cameras | 128 / 83 blended |
| Wall-clock | 16.8 s |
| Output resolution | 0.005 m (5 mm GSD) |
| Bands | 4 (RGBA, uint8) |

### 6. Orientation caveat (ADR-0038)

The T1\_R2 orientation/reversal remains UNVERIFIED (ADR-0038 open item). The
ortho inherits this uncertainty. Frame-robust uses (cover fraction, texture
statistics) are unaffected; directional presentation (along-transect asymmetry,
georeferenced overlay) should not be published until check 7 is resolved.

---

## Consequences

- (+) The orthomosaic is captured with full provenance before the trial expires.
- (+) The footprint mismatch is documented with a concrete resampling prescription,
  so the benthic project does not silently misalign cover on geometry.
- (+) EBS snapshot `snap-01d7a140ed04a151e` provides a recovery point if the ortho
  on the working volume is lost.
- (−) The ortho extent does not exactly match the canonical DSM, requiring a
  resampling step in the benthic pipeline. This cannot be fixed without
  re-exporting under the same or a new trial.
- (−) Orientation/reversal uncertainty inherited from ADR-0038; directional
  analyses remain gated.

#tags: ortho, benthic, footprint-offset, resampling, zero-pitch, ADR-0033, ADR-0036, ADR-0038
