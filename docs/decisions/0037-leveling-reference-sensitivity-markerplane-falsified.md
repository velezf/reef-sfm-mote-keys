# ADR 0037 — Leveling-reference sensitivity: marker-plane hypothesis falsified

Status: Falsified (recorded per practice)
Date: 2026-06-17
Chat: 10
Related: ADR-0021 (headless stage\_level; collinear guard), ADR-0025 (camera-nadir),
ADR-0036 (Zero-pitch; mean\_elevation residual)

## Hypothesis

Marker-plane leveling might be a more accurate vertical reference than camera-nadir
for T1\_R2, given that camera boresights are influenced by the diver's swimming
attitude (not purely gravity-aligned) and the reef has a real cross-axis slope.
If the scale-bar markers lie in the reef plane, rotating so the marker plane is
horizontal should yield a smaller cross-axis dip and a mean\_elevation closer to
the published 0.242 m.

## Method

Transient application on the master's rotation (apply → buildDem → restore in
`finally`), so no permanent copy is dirtied:

1. Pre-flight: verify work copy chunk.zip sha == `43547ec5` (master rotation).
2. Open work copy; verify pre-level along-pitch ~4.11° (sanity guard).
3. Fit best-fit plane to all 6 marker world positions (Jacobi eigensolver from
   `_fit_plane_normal`); report spread\_ratio = eig[1]/eig[0].
4. Apply shortest-arc world rotation (Rodrigues; `_apply_world_rotation`
   LEFT-multiply) so plane normal → +Z.
5. `doc.save()` → `buildDem` from existing filtered cloud → export DSM to `/data/edr_work/`.
6. `finally`: `shutil.copy2(MASTER_CHUNK, WORK_CHUNK)` — restore chunk.zip from
   master (file copy, not Metashape save; avoids re-write of modified state).
7. Post-flight: verify master chunk.zip sha == `43547ec5`; open master read\_only,
   confirm along-pitch ~4.11°.

Master integrity verified: sha `43547ec5` unchanged throughout; pitch 4.1071°
confirmed read\_only; foil `edr_r2.psx` never opened.

Script: `scripts/metashape/sensitivity_markerplane.py`

## Result

### Plane fit diagnostics

```
Plane normal (world): (-0.069206, +0.119183, +0.990457)
Scatter eigenvalues (sorted desc): [98.1743, 0.0831, 0.0015]
Spread ratio (eig[1]/eig[0]):  0.00085   (threshold 0.25)
Collinear guard: FIRES -> _compute_level_up falls back to camera-nadir
Marker-plane tilt from horizontal: 7.92°
```

The 6 scale-bar markers lie almost perfectly on a 1D line along the transect:
the dominant scatter is 98.2 (along-axis), the cross-track scatter is 0.083
(0.085% of the along-axis scatter). The spread ratio (0.00085) is 300× below the
collinear guard threshold (0.25). The Y-component of the plane normal (0.119) is
dominated by incidental Y-drift of the scale bars along the transect, not the true
cross-reef slope.

### Sensitivity table (10×1 clipped DSMs, same 9/9 symmetric trim)

| Leveling reference | along° | cross° | mean\_elev (m) | Δ vs 0.242 | rugosity | Δ vs 1.415 | VRM (Python) | Δ vs 0.076 |
|--------------------|-------:|-------:|:--------------|:----------|:--------|:----------|:------------|:----------|
| camera-nadir + Zero-pitch | 0.09 | 6.39 | 0.309 | +27.7% | 1.372 | −3.0% | 0.065 | −14.1% |
| marker-plane (this ADR) | 0.44 | 12.15 | 0.376 | +55.4% | 1.333 | −5.8% | 0.084 | +10.1% |
| published (target) | ~0 | ~1 | 0.242 | — | 1.415 | — | 0.076 | — |
| gravity (unmeasured) | — | — | — | — | — | — | — | — |

Marker-plane is WORSE on all three metrics. Cross-axis dip worsened from 6.39° to
12.15° because the poorly-constrained Y-component of the collinear plane normal
applied a spurious cross-axis rotation. VRM sign flipped from −14% to +10% (the
12° cross-axis tilt induced by the rotation amplifies slope in Y). Rugosity deficit
deepened from −3.0% to −5.8%.

## Decision

**Hypothesis falsified.** Keep camera-nadir + Zero-pitch as the leveling reference.
It is the trustworthy bound: pipeline's `_compute_level_up` collinear guard would
have blocked marker-plane at spread\_ratio = 0.00085, and bypassing it produced
exactly the regression the guard was designed to prevent (ADR-0021).

The cross-axis reference is unanchorable from the survey controls available in the
T1\_R2 dataset. Neither leveling convention aligns cross-axis to the published value.
The +27.7% mean\_elevation gap (camera-nadir + Zero-pitch) is bounded by the table
above and characterized as a survey-unanchorable cross-convention divergence — not
a fixable processing artifact. It propagates to ADR-0036 as the settled attribution.

**Roadmap note (not in scope here):** exposing `_compute_level_up` diagnostics
(spread\_ratio, method used, nadir\_angle\_deg) in `esm.report` as provenance would
make the leveling-reference choice auditable without re-running Metashape. Recorded
for future work; not codified in this session.
