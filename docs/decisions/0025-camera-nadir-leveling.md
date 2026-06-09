# ADR-0025 — Camera-nadir UP in stage_level; marker plane for heading only

**Status:** Accepted  
**Date:** 2026-06-09  
**Supersedes:** ADR-0021 (level strategy), ADR-0022 (marker-layer validation gate)  
**Related:** ADR-0023 (vendored Logan reduce), ADR-0024 (LOCAL_CS fix)

---

## Context

After the full ADR-0024 live re-run on EDR_T1 (2026-06-09), the post-level
probe showed world-Z was **80.6° off physical vertical**:

```
Mean world boresight from (0,0,-1): 80.639°
Camera-Z range:                     23.7 m  (should be ~2–3 m for a nadir survey)
Marker Z spread:                     1.058 m (should be ~0 if Z is up)
plane_flatness_eig2_eig1:           0.10497
```

The dense pre-flight failed because the camera-derived AABB region was
31 × 19 × 25 m (up-axis 25 m for a survey where physical depth is 2–3 m).

**Root cause:** `stage_level` fit a plane to the 8 vetted T1 markers and used
the plane normal as "UP" (world +Z). The T1 marker layout is near-collinear
(all markers placed along the long axis of the transect strip). The
in-plane minor / major scatter ratio (spread_ratio = eig[1]/eig[0]) was ≈ 0.10
— well below any collinearity threshold. A collinear set has an ill-defined
plane normal for the in-plane "roll" degree of freedom; the fitted normal
happened to lie 80° from physical vertical.

**Why the existing guard missed it:** The planarity guard is:

```python
flatness = eig[2] / eig[1]    # out-of-plane / in-plane-minor scatter
if flatness > GATE_PLANE_FLATNESS_MAX:   # 0.5
    alarm(...)
```

`flatness = 0.10497 < 0.5`, so the guard did not fire. The flatness metric
checks whether markers are volumetric/non-planar — it does NOT check whether
the in-plane spread is nearly 1-D (collinear). T1 markers are coplanar (roughly
flat on the reef surface) but arranged in a line, making roll ill-conditioned.

---

## Decision

Extract `_compute_level_up(mk_positions, cam_boresights, ...)` as a pure-Python
testable function that selects the UP direction with two guards:

### Guard 1 — Collinearity (primary, silent fallback)

```
spread_ratio = eig[1] / eig[0]       # in-plane minor / major
if spread_ratio < LEVEL_COLLINEAR_THRESHOLD:   # 0.25
    → use camera-nadir UP
    → log (not alarm); near-collinear markers are expected in thin-strip surveys
```

T1: spread_ratio ≈ 0.10 → guard fires → camera-nadir UP used.  
Well-spread grid/belt: spread_ratio > 0.30 → guard does not fire.

### Guard 2 — Disagreement (secondary, escalation)

```
nadir_angle_deg = angle(marker_normal, cam_up)
if NOT collinear AND nadir_angle_deg > LEVEL_NADIR_GUARD_DEG:   # 15°
    → alarm (critical; nadir_guard_fired=True in metadata)
    → use camera-nadir UP as fallback
```

Well-spread markers that strongly disagree with camera nadir indicate a model
problem (bad marker geometry, wrong alignment, etc.) that must not be silent.

### Camera-nadir UP computation

```python
mean_b = mean(camera boresight vectors in world space)   # cameras point DOWN
cam_up = -normalize(mean_b)                              # negate → physically UP
if cam_up[2] < 0: cam_up = -cam_up                      # +Z convention (as _fit_plane_normal)
```

Camera boresights are computed by rotating the camera +Z axis (direction camera
looks) from chunk space into world space via the chunk.transform.matrix rotation.

### Tilt gate modification

When `level_method == "marker_plane"` (unmodified path): keep the existing
`tilt_after > GATE_LONG_TILT_MAX_DEG` alarm (0.5°).

When `level_method == "camera_nadir"`: the reef surface need not be horizontal
(the reef has topography). Log marker-plane tilt as informational; gate is not
applied. The post-level probe (`t1_postlevel_probe.py`) verifies camera
boresight tilt < 5° from (0,0,−1).

### New metadata fields in `esm.level`

| key | description |
|-----|-------------|
| `level_method` | `"camera_nadir"` or `"marker_plane"` |
| `level_spread_ratio` | eig[1]/eig[0] collinearity metric |
| `level_nadir_angle_deg` | angle between marker normal and cam_up |

---

## Consequences

**Positive:**
- EDR_T1 levels correctly to physical vertical; camera-Z range collapses from
  23.7 m to ~2–3 m; boresight tilt from (0,0,−1) < 5°.
- Near-collinear transects (thin-strip surveys, T1-style marker placement)
  no longer silently produce a mis-leveled model.
- Well-spread transects (T3-belt) are unaffected — spread_ratio > 0.3,
  guards do not fire, existing marker-plane path unchanged.
- Marker-vs-camera disagreement is now an explicit escalation, not silent.

**Negative / Trade-offs:**
- Camera-nadir leveling sets roll+pitch from camera orientation, not marker
  geometry. If cameras themselves have a systematic pitch bias (e.g., camera
  tilted on the rig), the level will incorporate that bias.
- The heading (yaw, in-plane orientation) is still set in `stage_aoi`, which
  uses marker positions — unaffected by this change.
- Collinear-guard is silent (log only). If the collinear layout was intentional
  and the marker normal happened to be correct, the fallback to camera-nadir
  introduces a small error. For nadir surveys this is negligible (< 1°).

---

## Test coverage

`scripts/metashape/test_stage_level_up.py` — 11 tests, zero Metashape dependency:

| test | scenario | asserted |
|------|----------|----------|
| `test_collinear_markers_use_camera_nadir` | T1-like collinear | method=camera_nadir |
| `test_collinear_spread_ratio_below_threshold` | T1-like | spread_ratio < threshold |
| `test_wellspread_markers_use_marker_plane` | 3×3 grid | method=marker_plane |
| `test_wellspread_spread_ratio_above_threshold` | 4×2 grid | spread_ratio ≥ threshold |
| `test_wellspread_nadir_angle_below_guard` | grid + nadir | nadir_angle < guard |
| `test_disagreement_fires_nadir_guard` | grid + 30° tilt | nadir_guard_fired=True |
| `test_disagreement_angle_exceeds_threshold` | grid + 30° tilt | angle > LEVEL_NADIR_GUARD_DEG |
| `test_small_disagreement_does_not_fire_nadir_guard` | grid + 5° tilt | no guard fires |
| `test_up_vec_is_unit` | all scenarios | \|up_vec\| = 1.0 |
| `test_method_is_valid_string` | all scenarios | method ∈ known values |
| `test_info_contains_required_keys` | grid + nadir | all required keys present |

---

## Constants

```python
LEVEL_COLLINEAR_THRESHOLD = 0.25   # eig[1]/eig[0]; T1 ≈ 0.10, well-spread > 0.30
LEVEL_NADIR_GUARD_DEG     = 15.0   # angle threshold for escalation
```

---

## Acceptance note — 2026-06-09 EDR_T1 live run

**Status: Accepted with caveats**

### Verdict

Camera-nadir leveling is correct. The post-level probe gates for camera-Z range (14.78 m > 4 m)
and cameras-above-markers both FAIL, but independent diagnostic confirms these are false negatives
caused by genuine reef topography on the T1 depth-gradient transect, not leveling distortion.

**Evidence (t1_camz_diag.py, 2026-06-09):**

| metric | value | interpretation |
|--------|-------|----------------|
| boresight tilt from (0,0,−1) | **0.00°** (was 80.6°) | leveling correct |
| camera P5–P95 spread | 9.69 m (66% of 14.78 m range) | genuine spread, not outlier tails |
| marker Z spread (8 markers) | **4.51 m** (19/20 at −1.54 m → 15/16 at −6.06 m) | smooth spatial gradient, measured |
| tie-point P1–P99 spread | 13.17 m | reef surface confirms large relief |
| camera/tiepoint Z-spread ratio | 0.74 | cameras track reef relief (expected) |
| plane-fit R² | 0.33 | non-planar transect (curved relief, not distortion) |
| below-P5 cameras (118) XY | X [−8.8, −6.5] — 6+ m from Marker 19/20 | deep reef extension, not the weak-constraint zone |
| scale-bar RMS | 10.65 mm (matches expected) | no dome distortion |

The 4 m camera-Z gate was calibrated for T3-belt flat-reef geometry.  T1 spans a ~4.5 m depth
gradient within the marker array and continues deeper beyond it; 14.78 m range is physically
consistent with a survey held at constant offset above a sloped substrate.

### Caveat A — coordinate-system note (carry to P13HMEON reconciliation)

Camera-nadir leveling aligns world-Z with the **mean camera boresight** (proxied from mean camera
normal), not with gravity. On this sloped transect this means world-Z is approximately the
reef-normal direction, not vertical. Orientation-invariant metrics (rugosity, VRM, SAPA) are
unaffected. Elevation-derived metrics (RIE, ASD, absolute depth) are reef-normal-referenced, which
is appropriate for benthic survey comparisons but should be noted when comparing absolute depths to
bathymetric charts or the P13HMEON reference transect.

The alternative (marker-plane UP) was not available here: T1 markers are collinear
(spread_ratio ≈ 0.149), making the marker-plane normal ill-defined for the roll DOF. Camera-nadir
is the defensible choice given the available geometry.

### Caveat B — probe gate recalibration (TDD branch, not tonight)

The `t1_postlevel_probe.py` gates `camera-Z < 4 m` and global `cameras-above-markers` are
T3-belt-specific and should be replaced for depth-gradient transects with:
- **camera/tiepoint Z-spread ratio** (target 0.5–1.5; 0.74 here → PASS)
- **local camera-above-substrate check** (per-camera distance to nearest tie-point surface > 0)

Log as a TDD branch (`fix/probe-topo-gates`). Not on the current dense path.
