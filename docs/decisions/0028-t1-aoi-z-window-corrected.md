# ADR-0028 — T1 AOI: corrected Z window, surface-median-anchored

**Status:** ACCEPTED  
**Date:** 2026-06-10  
**Supersedes:** ADR-0026 (Z window [−9.977, −2.977] m)  
**Related:** ADR-0026 (original placement), ADR-0020 (LOCAL-CRS), ADR-0025 (level),
ADR-0027 (DSM 1 cm)

---

## Context

ADR-0026 accepted a Z window of [−9.977, −2.977] m (7 m total) derived from a
**uniform-gradient model**: 14.78 m total reconstruction Z over 27.2 m mean XY extent
→ 0.543 m/m rate × 10 m = 5.4 m estimated local relief + 29% margin.

When `stage_aoi` ran with that window, the DSM covered only **2.58 × 1.00 m** of the
intended 10 × 1 m transect (coverage 16.3%).  The gate correctly caught it via
`4_long_extent_m = 2.580 m`.

---

## Root cause: the model assumption was wrong

The uniform-gradient model assumed the reef surface is a simple slope across the 10 m
long axis.  A read-only Z-profile diagnostic (script
`scripts/metashape/diag_transect_z_profile.py`) sampled all 651 M pre-filter dense
cloud points within the transect XY footprint (±5 m along 135°, ±0.5 m across)
using a ±15 m diagnostic Z range.  Per-slab medians:

| Bin | Along (m from centre) | Median Z (m) | Surface zone |
|-----|----------------------|--------------|--------------|
| 0 | [−5, −4] | −2.142 | fore-reef shoulder |
| 1 | [−4, −3] | −2.022 | fore-reef shoulder |
| 2 | [−3, −2] | −3.885 | trough |
| 3 | [−2, −1] | **−5.204** | trough (deepest) |
| 4 | [−1,  0] | −5.004 | trough |
| 5 | [ 0, +1] | −4.357 | trough |
| 6 | [+1, +2] | −0.960 | reef crest |
| 7 | [+2, +3] | −0.837 | reef crest |
| 8 | [+3, +4] | −0.727 | reef crest |
| 9 | [+4, +5] | **−0.706** | reef crest (shallowest) |

The true surface profile is **trough-to-crest, not a uniform slope**:
- Fore-reef shoulder (bins 0–1, along −5 to −3 m): ~−2.1 m
- Trough (bins 2–5, along −3 to +1 m): −3.9 to −5.2 m — **the ADR-0026 window
  captured only this section** because the 7 m window was centred on the OBB bbox
  centre (Z = −6.477 m), which sat inside the trough at a depth that excluded both
  the fore-reef shoulder and the reef crest
- Reef crest (bins 6–9, along +1 to +5 m): −0.7 to −1.0 m

Raw pre-filter noise floor reaches −11.8 m identically across bins 2–5 (likely a
clip boundary; removed by Step-13 filter at threshold = 2).  The raw max reaches
+3.1 m in bin 0 (above-water noise; also removed by filter).

---

## Decision

**Replace the uniform-gradient-derived Z window with a surface-median-anchored
window with generous margin.**

XY centre and orientation are **unchanged** from ADR-0026.

### Corrected Z window

| parameter | ADR-0026 (v1) | ADR-0028 (corrected) |
|---|---|---|
| centre Z | −6.477 m (OBB bbox centre) | **−3.700 m** (surface-anchored) |
| Z half-extent | 3.500 m | **5.500 m** |
| Z window | [−9.977, −2.977] m | **[−9.200, +1.800] m** |
| Z height | 7.0 m | **11.0 m** |
| derivation | uniform-gradient model | surface-median floor − 4 m; ceiling + 2.5 m |

**Surface-median envelope (noise-removed, post-filter):**  
floor −5.204 m (bin 3) / ceiling −0.706 m (bin 9) / span 4.498 m.

Margins are deliberately generous (11 m window for a 4.5 m surface span):
- Floor margin: 4.0 m below deepest median → −9.2 m (captures any post-filter outliers
  without hitting the pre-filter noise floor of −11.8 m)
- Ceiling margin: 2.5 m above shallowest median → +1.8 m

The AOI call with the corrected window:
```
--aoi-centre=-2.028,3.774,-3.700 --aoi-angle=135 --aoi-height=11.0
```

---

## Outcome

| metric | ADR-0026 v1 (truncated) | ADR-0028 (corrected) |
|--------|------------------------|----------------------|
| in-window pts (filtered cloud) | 3,311,789 | **26,529,942** |
| DSM dimensions | 258 × 100 cells | **1000 × 100 cells** |
| DSM extent | 2.58 × 1.00 m | **10.00 × 1.00 m** ✓ |
| ortho dimensions | 515 × 200 px | **2000 × 200 px** |
| ortho extent | 2.58 × 1.00 m | **10.00 × 1.00 m** ✓ |
| coverage (interp-off) | 16.3% | **97.1%** ✓ |
| long-axis tilt (gate #1) | 29.84° (on 2.58 m slice) | **0.37°** ✓ |
| total tilt (gate #2) | 38.13° | 8.71° (reef-wall cross-slope; threshold TBD in fix/probe-topo-gates) |
| gate failures | 5/7 | **2/7** (checks #2, #7 — both documented) |

Gate check #7 (`orientation_plus_x = False`) is a benign 135°-vs-+X convention
mismatch in `stage_gate`, not a product flip.  Check #2 (`total_tilt = 8.71° > 6.0°`)
reflects physical reef-wall cross-axis slope; the 6.0° threshold was sized for a flat
belt transect and needs recalibration for topo transects (tracked: `fix/probe-topo-gates`).

---

## Limitations

ADR-0026 limitations 1–4 carry forward unchanged.  Additional:

5. **Z window is empirically derived from the pre-filter cloud.** The diagnostic used
   651 M pre-filter points; after Step-13 confidence filter (~25% removed), the
   effective surface bounds are tighter.  The 4.0 m / 2.5 m margins accommodate this.

6. **The trough-to-crest profile implies significant surface complexity.** The 10 m
   transect spans a ~4.5 m Z range (trough depth ~5.2 m, crest depth ~0.7 m).
   Long-axis tilt (0.37°) is negligible; the complexity is topographic, not a
   leveling artefact.

---

## Records

- Truncated-run project archived: `edr_t1_truncated_adr0026v1_20260610T232809Z.{psx,files}`
- Corrected-run EBS snapshot: `snap-034d45019a4e39c43` (tag: `edr_t1_postproducts_20260610T235019Z`)
- Diagnostic script: `scripts/metashape/diag_transect_z_profile.py`
- Stage logs:
  - filter (re-cut): `stage_filter_recut_20260610T233815Z.log`
  - aoi (re-cut): `stage_aoi_recut_20260610T233815Z.log`
  - dsm (re-cut): `stage_dsm_recut_20260610T233905Z.log`
  - ortho (re-cut): `stage_ortho_recut_20260610T233935Z.log`
  - gate (re-cut): `stage_gate_recut_20260610T234105Z.log`
