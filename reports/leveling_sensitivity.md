# Leveling-reference sensitivity — EDR_T1_R2

Generated: 2026-06-17 (Chat 10) · ADR-0037

Hypothesis tested: marker-plane leveling is a better vertical reference than camera-nadir
(diver attitude is unstable; scale-bar markers may better represent reef plane).

---

## Sensitivity table

| Reference | along° | cross° | mean\_elev (m) | Δ vs 0.242 | rugosity | Δ vs 1.415 | VRM Python | Δ vs 0.076 |
|-----------|-------:|-------:|:-------------|:----------|:--------|:----------|:----------|:----------|
| camera-nadir + Zero-pitch | 0.09 | 6.39 | 0.309 | +27.7% | 1.372 | −3.0% | 0.065 | −14.1% |
| marker-plane | 0.44 | 12.15 | 0.376 | +55.4% | 1.333 | −5.8% | 0.084 | +10.1% |
| published (target) | ~0 | ~1 | 0.242 | — | 1.415 | — | 0.076 | — |
| gravity (unmeasured) | — | — | — | — | — | — | — | — |

VRM: Python impl throughout (MultiscaleDTM R is +13% higher; see ADR-0032).

---

## Why marker-plane is worse

The 6 scale-bar markers lie almost perfectly along the transect axis (collinear):
- Scatter eigenvalues (sorted): [98.17, 0.083, 0.0015]
- Spread ratio (minor/major): **0.00085** — 300× below the `_compute_level_up` collinear guard (threshold 0.25)
- Plane normal Y-component (0.119) reflects incidental Y-drift of bars along transect, NOT cross-reef slope
- Bypassing the guard: cross dip 6.39° → 12.15°; mean\_elevation +27.7% → +55.4%; VRM sign flipped

The pipeline's collinear guard (ADR-0021) correctly falls back to camera-nadir. This measurement
confirms the guard was right.

## Cross-axis anchor is survey-unanchorable

Neither convention anchors the cross-axis from the survey controls available in T1\_R2.
The +27.7% mean\_elevation gap is bounded by the table above and settled as a cross-convention
divergence. Sensitivity spread: 27.7 ppt (camera-nadir) to 55.4 ppt (marker-plane).
Camera-nadir + Zero-pitch is the trustworthy bound.

## Master integrity

Marker-plane DSM computed with transient apply-restore pattern:
- work copy chunk.zip sha `43547ec5` verified before + after
- master along-pitch 4.1071° confirmed read\_only post-restore
- foil `edr_r2.psx` never opened

## Hypothesis outcome

**FALSIFIED.** Decision: keep camera-nadir + Zero-pitch.
