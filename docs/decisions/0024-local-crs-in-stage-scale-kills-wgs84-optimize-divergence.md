# ADR 0024 — Set LOCAL_CS + disable spurious reference locations in `stage_scale` to prevent optimizeCameras divergence in the reduce path

Status: Accepted
Date: 2026-06-09
Chat: 6 (T1 reduce recovery, session-log-2026-06-09)

## Context

With ADR-0023 in place (vendored Logan reduce), the first attempt to run
`stage_reduce` on the post-scale EDR_T1 model diverged catastrophically:

| Metric | Pre-optimize | Post-optimize |
|---|---|---|
| `transform.scale` | 1.0 | **823.77** |
| median reprojection | 0.15 px | **14–19 px** |
| max reprojection | — | **1.3 × 10¹⁵²** (NaN/Inf territory) |

The divergence is **bar-independent**: disabling all four scale bars before
optimizing still blew up. The anchor is that EDR_T1's Step 6 alignment
optimize (`optimizeCameras(tiepoint_covariance=True)`) ran against THIS SAME
model with the same WGS84 datum and held scale=1.0 / 0.15 px.

### Scale-bar over-constraint hypothesis — **FALSIFIED**

The initial hypothesis (bars weighted at 0.001 m accuracy over-constraining
the bundle) was tested by disabling all bars before optimize. The divergence
reproduced identically. This hypothesis is dead; it is recorded here per the
project's "ADRs for wrong turns" practice.

### Datum dump evidence (read-only probe on post-scale edr_t1.psx, 2026-06-09)

A read-only `t1_datum_dump.py` probe produced the definitive state:

```
chunk.crs      : WGS 84 (EPSG::4326)  ← spurious geographic CRS
chunk.transform: IDENTITY (4×4, scale = 1.0)

cameras with reference.location : 2422 / 2422
  all at Vector([-81.84433, 24.4591, 0.0])  acc=None  enabled=True
  (stub GPS, all identical — Key Largo area, altitude 0 m; from EXIF/import)

markers with reference.location : 8 / 8
  Marker 20:  [ 73.73,  -89.987,  -6356740.88 ]  acc=None  enabled=True
  Marker 19:  [ 74.28,  -89.989,  -6356740.36 ]  acc=None  enabled=True
  Marker 15:  [109.61,  -89.997,  -6356704.58 ]  acc=None  enabled=True
  …  (all: latitude ≈ -90°, altitude ≈ -6.36e6 m — IMPOSSIBLE as real GCPs)

scale bars (4) : dist=0.25  acc=0.001  enabled=True  (correct)
```

### Mechanism

1. **WGS 84 is Metashape's default CRS for no-GPS captures** (same root as ADR-0018, where it OOM'd `buildDem` by rasterizing a ~38,800 km grid).

2. **`chunk.transform = IDENTITY`**: this dataset has no real GPS. After align and scale-bar assignment, the internal coordinate frame has no metric world-to-chunk conversion — the identity matrix IS the transform.

3. **`stage_scale` calls `chunk.updateTransform()`** (internally within Metashape when scale-bar distances are applied). With `chunk.crs = WGS84` and `transform = IDENTITY`, Metashape projects each marker's 3-D internal position through `identity × WGS84` and **auto-populates `marker.reference.location`** with the result. The resulting coordinates are geographically garbage: any Cartesian position close to the origin maps to latitude ≈ −90° (pointing toward the Earth's rotation axis), altitude ≈ −6.36 × 10⁶ m (Earth-radius depth). These are stored with `enabled=True`.

4. **At Step 6** (pre-scale alignment optimize), markers had NOT yet been given reference locations — they were placed but the scale stage had not run. Only camera stub GPS was present (acc=None, all identical, effectively zero-weight). The bundle converged at 0.15 px with no GCP constraints.

5. **After stage_scale**, the 8 markers have garbage `reference.location` with `enabled=True`. Camera stub locations are also still there. When Logan's reduce path calls `optimizeCameras(cal_f=True, cal_cx=True, …, fit_corrections=False)`, Metashape treats these as live GCP constraints. The bundle tries to reconcile a 0.25 m scale-bar scene with markers at latitude −90°, altitude −6.36 × 10⁶ m → **numerical explosion**.

### A/B confirmation (on copies, CPU-only, 2026-06-09 — probe `t1_ab_crs_optimize.py`)

| Arm | Setup | `transform.scale` | median reproj | max reproj |
|---|---|---|---|---|
| A (datum as-is) | none | **823.772** | **20.82 px** | **1.34 × 10¹⁵⁴** |
| B (LOCAL_CS + refs disabled) | chunk.crs=LOCAL; marker+camera ref.enabled=False | **0.153** | **0.1499 px** | 0.748 |

Notes on the results:
- ARM A: scale blows up to 823, reproj to 1.34e154 — matches the original divergence exactly.
- ARM B: reproj holds at 0.1499 px (matches pre-optimize 0.149877). `transform.scale`
  moves from 1.0 → 0.153 — this is CORRECT, not a divergence; with a LOCAL_CS and no
  garbage GCPs, the optimizer correctly refits the camera calibration, producing a
  well-conditioned bundle. 0.153 is the proper metric scale factor for this internal frame.
- Copies cleaned after run; live PSX untouched.

Datum/CRS is the root. The optimize params are not the cause.

## Decision

In `stage_scale`, after weighting every scale bar (`sb.reference.accuracy =
0.001`) and before saving, call `_neutralize_spurious_reference(chunk)`:

```python
chunk.crs = Metashape.CoordinateSystem(
    'LOCAL_CS["Local Coordinates (m)",LOCAL_DATUM["Local Datum",0],UNIT["metre",1]]')
for m in chunk.markers:
    if m.reference is not None and m.reference.enabled:
        m.reference.enabled = False
for c in chunk.cameras:
    if c.reference is not None and c.reference.enabled:
        c.reference.enabled = False
```

**Scale bars are untouched.** Scale bars constrain via `reference.distance` /
`reference.accuracy` (a distance measurement between marker pairs), NOT via
`marker.reference.location`. Setting `marker.reference.enabled = False`
removes the garbage GCP constraint without affecting the scale-bar constraint.

The fix is permanent (committed to the saved project), not a session-local
wrapper: any subsequent call to `optimizeCameras` (inside Logan reduce, inside
a future GUI session, inside any downstream `--stage`) will see a clean
local-metric chunk with no spurious GCP constraints.

The LOCAL_CS string is identical to the one already used by
`_local_planar_projection` (ADR-0020 lever for `buildDem`/`buildOrthomosaic`).
This unifies the CRS treatment across the whole pipeline: **after stage_scale,
the chunk is in a local metric frame with no WGS84 anywhere**.

## Contract test (`test_stage_scale_crs.py`)

Ten pure-pytest tests (zero Metashape dependency):

1. `_neutralize_spurious_reference` sets chunk.crs to LOCAL.
2. All marker `reference.enabled` become False.
3. All camera `reference.enabled` become False.
4. Scale bars untouched (accuracy unchanged, reference.enabled still True).
5. Idempotent: second call on already-LOCAL chunk returns counts = 0.
6. Returns correct disabled counts.
7. `None` reference objects are skipped without error.
8–10. `stage_scale` integration: produces LOCAL CRS, disables all refs, leaves scale-bar accuracy intact.

## Relation to prior ADRs

- **ADR-0018**: same spurious WGS84 CRS root. There it caused `buildDem` to
  rasterize a ~38,800 km geographic plane → `std::bad_alloc`. Here it
  populates garbage GCP coordinates → `optimizeCameras` divergence. The root
  is the same; the failure mode differs by call site.
- **ADR-0020**: the lever (`chunk.crs = LOCAL_CS`) is identical. ADR-0020
  applied it per-build for the DEM/ortho stages; this ADR applies it
  persistently at `stage_scale` time so all downstream stages inherit a
  correct CRS automatically.
- **ADR-0023**: the vendored Logan reduce path calls `optimizeCameras`
  internally. Without this fix, every optimize inside the RU/PA/RE passes
  would have diverged. This ADR is a prerequisite for ADR-0023's reduce to
  run correctly on no-GPS captures with scale bars.

## Consequences

- **Reduce path now stable on no-GPS, scale-bar-only captures.** The Logan
  optimize will see only tie-point + scale-bar constraints, not garbage GCPs.
- **DEM/ortho path simplified.** `_local_planar_projection` (ADR-0020) checks
  `chunk.crs` before setting it (idempotent). After stage_scale the chunk is
  already LOCAL, so the DSM/ortho stage's CRS reassignment is a confirmed no-op.
- **Any optimize after stage_scale** (user GUI, future stages, or scripts) will
  not blow up due to this mechanism. The protection is structural, not
  call-site-specific.
- **Marker `reference.location` values are preserved** (the garbage coordinates
  remain in the project file) but `reference.enabled = False` means Metashape's
  optimizer ignores them. This is intentional: the values are not real GCPs and
  should never be used as constraints. Clearing them entirely was considered but
  not chosen — setting `enabled=False` is the standard Metashape idiom for
  "present but not used," and preserving the values leaves the diagnostic
  history readable.

---

## Addendum — 2026-06-15 (EDR_T1_R2; defense-in-depth in `stage_reduce`)

### Trigger

EDR_T1_R2's DCV GUI session (2026-06-15) set three 0.25 m scale bars manually
**without going through `stage_scale`**. On save, Metashape called
`updateTransform()` internally against the existing WGS84 CRS →
`chunk.transform.scale = 1314.24`. All six marker `reference.enabled` remained
`True` with the standard garbage coordinates (latitude ≈ −90°, Z ≈ −6.36 × 10⁶ m).

Confirmed by read-only probe on the saved project:
```
chunk.crs                : WGS 84 (EPSG::4326)
chunk.transform.scale    : 1314.24
cameras location_enabled : True  (real GPS at [-81.84, 24.46, 0.0])
markers reference.enabled: True  (all 6, garbage WGS84)
scalebars (3)            : 0.25 m each — correct
esm.scale                : absent (stage_scale never ran)
```

Had `--stage reduce` run next, Logan's `optimizeCameras` would have diverged
identically to the original T1 incident documented above.

### Fix: `_neutralize_spurious_reference` now called from `stage_reduce` too

`stage_reduce` calls `_neutralize_spurious_reference(chunk)` immediately after
the pre-condition health check and the scalebar-count guard, **before**
`_run_logan_reduction`. `save(doc)` follows only if the call disabled any refs
(prevents a redundant write when stage_scale already neutralised on the normal
pipeline path).

This makes the protection **path-independent**:

| Scale-bar source | CRS at reduce entry | After guard |
|---|---|---|
| `stage_scale` (normal path) | already LOCAL | no-op (zeros returned) |
| GUI / DCV (re-entry path) | WGS84 + refs enabled | neutralised + saved |

### Idempotency confirmation

For the normal pipeline path (stage_scale already neutralised), the
stage_reduce call returns `{"n_markers_ref_disabled": 0,
"n_cameras_ref_disabled": 0}` and no extra `save(doc)` is issued — genuine
no-op.

### Generalisation

This is the standard fix for **every transect on this project**: any no-GPS
capture imported into Metashape will receive the spurious WGS84 CRS and stub
camera GPS from EXIF/defaults. The neutralisation must be in place before the
first `optimizeCameras` call in the reduce path. Placing it in both stage_scale
(as originally) and stage_reduce (defense-in-depth) covers all known paths.

#tags: metashape-api, optimizecameras, wgs84-spurious-crs, local-crs, chunk-crs, reference-location, stage-scale, stage-reduce, logan-reduce, numerical-divergence, adr-0018-related, adr-0020-lever, adr-0023-prereq, chat6, chat7
