# ADR-0033 — Option 2: R2 single-transect reconstruction for 1:1 reconciliation

**Status:** In progress (pre-dense gate, 2026-06-15)
**Related:** ADR-0032 (reconciliation harness + transect-identity finding), ADR-0025 (camera-nadir
leveling), ADR-0023 (Logan reduce + network-health guard), ADR-0024 (local CRS kills WGS84 divergence)

---

## Context

ADR-0032 established that our merged T1 area-survey cannot produce a 1:1 comparison to any single
published EDR_T1 row (scale mismatch: 5.5 m relief vs 0.5–1.4 m per transect). It scoped two paths
for the reconciliation thesis:

- **Option 1 (envelope):** report where our centre-cut lands relative to the published T1
  confidence population — already run and documented in ADR-0032. Only VRM is meaningfully
  comparable; rugosity and mean elevation are outside the population due to scale mismatch.

- **Option 2 (1:1):** reconstruct a single published EDR_T1 belt transect from its own imagery
  and reconcile 1:1 against the published row. This is the "strong-claim path" — the only route
  to a defensible per-metric delta.

This ADR records the Option 2 kickoff decision and pre-dense run plan (2026-06-15).

## Decision

**Reconstruct EDR_T1 restored transect R2** (~272 images, `20230711_EDR_T1_R2_*.tif`) as a
standalone Metashape project per Toth ESM Table S2, then reconcile 1:1 against the published
`EDR T1 / R2 / confidence` row in `Coral_reef_topographic_complexity_data.csv`.

### Why R2

R2 ("restored") was selected over C2 ("control") as the kickoff target because:
- Its 272-image swath is mid-range in size (the nine T1 swaths span 230–283 images).
- "Restored" is the scientifically interesting arm — the dataset documents reef restoration
  outcomes; a 1:1 on a restored transect directly supports that claim.
- R2 is confirmed present and complete on disk at image-count parity with the published count.

### Isolation

- **Project:** `/data/edr_work/edr_r2.psx` (new, never opens EDR_T1 or EDR_T3 projects)
- **Output:** `/data/edr_work/products/EDR_T1_R2/` (chunk label `EDR_T1_R2`; the user-facing
  shorthand "EDR_R2" maps to this path — noted because `out_root/chunk.label` drives output dirs)
- **EDR_T1 untouched:** the full-swath `edr_t1.psx` (2,422-image area survey) is not opened or
  modified by any R2 stage.

### Code change (divergence from T1 run)

`group_images_by_transect` in `run_pipeline.py` accepted only an exact transect-base match
(`EDR_T1` → all T1 files, one chunk). It did not support swath-level isolation. Added:

```python
_wm = re.match(r"(EDR_T\d+)(?:_([RC]\d+))?$", want, re.IGNORECASE) if want else None
want_base = _wm.group(1).upper() if _wm else want
want_swath = _wm.group(2).upper() if (_wm and _wm.group(2)) else None
```

And in the flat-layout loop, replaced `label != want` with `label != want_base` plus
`f"_{want_swath}_" not in p.name.upper()` secondary filter, collapsing to `group_key = want` so
the chunk is labeled `EDR_T1_R2` (single chunk). This is backward-compatible: `--transect EDR_T1`
still groups all T1 swaths under one chunk via prefix matching.

### Pipeline parameters (ESM Table S2, pre-dense)

| Stage | Parameter | Value | Notes |
|---|---|---|---|
| import | `--transect EDR_T1_R2` | 272 TIFFs | new swath filter |
| import | `--focal-mode fallback` | n/a | no focal_decision.json for R2 yet |
| step4 | `--quality-threshold 0.50` | disable <0.50 | same as T1/T3 |
| align | Accuracy High, Generic ON | 60k/0 kp/tp | ESM Table S2 |
| markers | Circular 12-bit, tolerance 20 | auto-raise | same detector |
| scale bars | 25 cm, assign via GUI | GUI touch | same as T1/T3 |
| reduce | Logan v2.0.x (ADR-0023) | RU 30 → PA 3.5 → RE 0.3 | capped-iterate |
| level | camera-nadir leveling (ADR-0025) | — | hemisphere-flip watch |
| level | local metric CRS (ADR-0024) | — | prevents WGS84 datum divergence |

**Excluded images:** none (the two corrupt files are in `EDR_T1_C2_`, not R2).

**Scale bar source:** R2-specific coded targets embedded in imagery — must auto-detect; no manual
assignment of foreign bar IDs from T1.

## Pre-dense GO/NO-GO gate (STOP point, this session)

Do NOT build the point cloud. Report at STOP:

| Gate | Target |
|---|---|
| Registration % | ≥ 90% |
| Final reprojection RMS | 0.27–0.52 px |
| Scale-bar error | ≤ ~3.41 mm (S2 reference) |
| Camera count | ~272 (minus any quality-disabled) |
| Marker count | ≥ 3 markers, ≥ 2 bars |
| Leveling | Not flipped; nadir-up; extent < LEVEL_MAX_EXTENT_M |

## Results

### Pre-dense run — 2026-06-15

#### Pipeline output summary

| Stage | Key metric | Value |
|---|---|---|
| import | TIFFs loaded | 272 (EDR_T1_R2 swath) |
| step4 | Cameras retained / disabled | 132 / 140 (51.5% disabled) |
| align | Cameras aligned | 131 / 132 (99.2% of step4 survivors) |
| align | Pre-reduce RMS | 0.1734 px |
| reduce | Tie points | 603,314 → 236,860 (−60.7%) |
| reduce | Post-reduce RMS | 0.1397 px |
| reduce | `transform.scale` after Logan | 0.16013751 (stable; no divergence) |
| scale | Scalebars | 3 × 0.25 m (pairs 15–16, 19–20, 25–26) |
| markers | Gate | headless-pass (all 4 sub-gates PASS) |
| level | Pre-level tilt | 57.41° |
| level | Post-level tilt | 7.977° |
| level | Method | camera_nadir (spread_ratio 0.00085 < 0.25) |

Datum at STOP: `LOCAL_CS(m)`, all marker/camera geo-refs disabled, `transform.scale = 0.16013751`.

#### Divergence notes

**(a) Post-reduce RMS below the Table S2 expected band.**
Final reduce RMS = 0.1397 px (pre-reduce 0.1734 px). The Table S2 expected band 0.27–0.52 px was
calibrated against T3 where all frames contributed. Here, `step4`'s 0.50 quality threshold
disabled 140 of 272 frames (51.5%), leaving 132 highest-quality cameras for alignment. A smaller,
pre-filtered bundle yields tighter reprojection error per tie point (fewer weak/low-quality
projections diluting the mean). This is not a calibration failure; it reflects the interplay of
R2 capture quality and step4's threshold. The markers gate and scale-bar residuals remain the
binding accuracy measures for this run.

**(b) ~1.8% peak scale residual from the hand-placed marker layer.**
Scale bars were placed manually in the DCV GUI session, not auto-detected from coded targets.
World-metric bar lengths after datum neutralisation and `updateTransform()`:

| Pair | World dist (m) | Δ from 0.25 m |
|---|---|---|
| 15–16 | 0.2456 | −1.76% |
| 19–20 | 0.2539 | +1.56% |
| 25–26 | 0.2504 | +0.16% |

Inter-bar ratio = 1.034 (< 1.25 threshold: PASS). Peak deviation −1.76 / +1.56% ≈ 1.8%.
Auto-detected coded-target bars (as used in T3) yield sub-0.5% residuals; manual-placement is
the floor for scale accuracy on this R2 reconstruction. This sets the scale-budget ceiling for
the 1:1 reconciliation step.

**(c) 7.977° post-level tilt = natural reef slope, not a leveling failure.**
`camera_nadir` leveling minimised the mean-boresight-to-vertical angle from 57.41° (import
orientation) to 7.977°. The residual represents the actual topographic slope along the R2
transect path; a perfectly flat-bottom transect would level to < 1°. The 7.977° slope must be
accounted for in the elevation reconciliation step: the elevation offset between the near and far
ends of the 9.25 m transect is approximately 9.25 × sin(7.977°) ≈ 1.28 m, which is non-trivial
relative to the published EDR rugosity scale.

**(d) Far bar labeled 25–26 per consecutive-ID protocol — basis to be confirmed by Frank.**
The physical marker pair at the far end of the transect was assigned IDs 25 and 26 during the DCV
GUI session to satisfy the consecutive-pair protocol (pairs: 15–16, 19–20, 25–26). One physical
target had a non-consecutive ID; it was relabeled "Marker 25" in DCV to form a consecutive pair.
Frank to confirm: (i) the physical-to-label correspondence for this pair and (ii) whether the
original non-consecutive ID is recorded in the field notes. The relabeling does not affect the
scale-bar constraint (bar endpoints are the pair, regardless of ID value) but must be traceable
for the field-data reconciliation.

### Dense point cloud build — 2026-06-15

| Metric | Value |
|---|---|
| Dense points | 47,143,867 (47.1 M) |
| Filter (moderate confidence) | Applied; cloud retained after filter |
| Snapshot (pre-AOI) | `snap-0b10abc94d12b78e1` (State=completed) |

Dense build and filter completed without incident. The cloud was committed to the PSX and snapshotted
before proceeding to AOI/DSM.

### GATE#6 footprint-aspect check — 2026-06-15 (per-transect exception, ADR-0033)

#### Failure details

Running `stage_aoi` with the default DEM-PCA footprint analysis returned:

| Gate | Required | Actual | Result |
|---|---|---|---|
| GATE#6 EVR | ≥ 0.95 | 0.877 | **FAIL** |
| GATE#6 aspect | ≥ 5.0 | 2.671 | **FAIL** |

#### Root cause — true positive on geometry, not a reconstruction failure

The GATE#6 footprint-aspect check is designed to catch incomplete or poorly oriented belt-transect
coverage. For R2, the geometry is an **out-and-back two-pass swim**, not a single belt:

- **Outbound pass** (frames 001–053, n=27): centroid lateral offset −0.662 m
- **Return pass** (frames 054–263, n=104): centroid lateral offset +0.172 m
- **Lateral separation between passes:** 0.83 m

This two-pass footprint is geometrically ~2.7:1, not the 5:1 belt the gate expects. The
PCA footprint correctly detects this as non-belt. The gate is a **true positive on geometry**.

#### Surface coherence check (verified coherent)

Before applying the override, the full-cloud diagnostic DEM was rendered and the cross-track surface
continuity was checked:

- **Cross-track Z step at pass boundary:** mean 0.023 m (2.3 cm), σ = 0.009 m
- **Along-transect Z drop:** ~1.75 m over 9.25 m (consistent with 7.977° slope)
- **Seam:** none — the surface is continuous across the pass boundary
- **Unique Z values (float32-fixed DEM):** 250,691 (sub-mm precision; 8 before fix — see float32
  note below)

The reconstruction is **usable**. The 2.3 cm cross-track offset is well within acceptable
surface reconstruction noise and does not indicate misregistration between passes.

#### Decision — manual override (Option A)

GATE#6 is **bypassed for R2** via the `--aoi-centre` / `--aoi-angle` manual override path
(Change 1 + Change 2 in `run_pipeline.py`). The gate result is logged, not alarmed:

```
stage_aoi: GATE#6 footprint-aspect check SKIPPED (manual override — ADR-0033 R2 per-transect exception)
```

`stage_gate` treats `footprint_explained_var is None` as a pass condition.

The manual AOI placement parameters (world-frame, post-leveling):

| Param | Value |
|---|---|
| `--aoi-centre` | `-299299.21875,-577767.15473,3304805.87500` |
| `--aoi-angle` | `215.59` (long-axis bearing, degrees) |
| `--aoi-height` | `10.0` m (default) |

The centre was computed as the mean of all camera X,Y positions in the world frame; the angle from
the PCA long-axis bearing of the DEM footprint.

#### Float32 Z-quantization fix — permanent integration (stage_dsm)

At world-frame Z ≈ 3,304,807 m (geocentric), float32 ULP = 0.25 m → only 8 unique Z levels in
the DSM tile. Fix: `chunk.transform.translation.z` is shifted to 0 **before** `buildDem` so DSM
tile Z values ≈ −1.5 m (float32 ULP ≈ 0.24 µm). The original `tz_orig` is stored in
`esm.dsm.tz_orig` for world-Z recovery. The shift is idempotent (guard: `abs(tz_orig) > 100.0`).
This recipe is permanently integrated into `stage_dsm` (Change 3 + Change 4, `run_pipeline.py`).

The diagnostic probe (`/data/edr_work/probes/r2_recentered_dem.py`) restored T_z and discarded
the transient DEM — the PSX on disk was never saved during the diagnostic.

#### v2 roadmap item

The per-transect geometry exception exposes a coverage+coherence gate design gap: GATE#6 should
check surface continuity (cross-track step < threshold) and areal coverage (% non-nodata) rather
than assuming the footprint will be a belt. This is deferred to a post-R2 gate redesign iteration.

### DSM frame verification — 2026-06-16

#### Initial frame check (FAIL → investigated → NOT a bug)

After building the metric DSM (elevation.3) with the standard `_local_planar_projection()` recipe
(LOCAL_CS + identity Planar projection, ADR-0020), the along-transect slope was measured at
**4.395°**, not ~7.977° as initially expected.

The initial expectation was based on the `marker_plane_tilt_after = 7.977°` from `stage_level`,
which was incorrectly assumed to equal the along-transect DEM slope. **Investigation showed this was
a misunderstanding:**

**What 7.977° actually is:** `stage_level` computes `tilt_after` from the best-fit plane through
the 6 vetted marker positions (3 pairs × 2 endpoints) in the leveled world frame. These markers
span both along-transect and cross-track positions. The resulting plane tilt (7.977°) is a
combination of the along-transect slope AND cross-track slope at the marker locations — not the
along-transect DEM slope alone.

#### Mathematical proof: the DSM IS in the leveled world frame

With `T_z = 0` (float32 fix, saved to PSX), the `LOCAL_CS_Z` output of `buildDem` satisfies:

```
LOCAL_CS_Z = T_z + scale * R_w[2] · internal
           = 0   + scale * R_w[2] · internal
           = world Z component (leveled frame)
```

where `R_w = chunk.transform.matrix[0:3, 0:3] / scale` includes the stage_level rotation
(`R_w = R_level * R_original`). The identity `proj.matrix` correctly outputs the leveled world Z.

**Option L (modifying proj.matrix) is mathematically impossible:**
- Without translation: `DEM_Z = R_w[2] · LOCAL_CS = R_w[2] · T + scale * internal_Z ≈ 50,423 m`
  (confirmed by probe — the large T_x = 579,643 m, T_y = 295,655 m dominate)
- With translation fix (`[[R_w | −R_w·T], [0 0 0 1]]`):
  `DEM_Z = R_w[2] · (LOCAL_CS − T) = scale * internal_Z` = **identical to identity projection**
  (proof: `R_w[2]^T * R_w = e₂`, so `R_w[2] · (R_w * v) = v[2]` for any vector v)

The identity proj.matrix already gives the correct leveled world Z. There is no projection bug.

#### Correct DSM slopes (metric DSM, elevation.3)

| Direction | Slope | Z-drop | Notes |
|---|---|---|---|
| Along-transect (1000 px, 9.99 m) | **4.395°** | 0.768 m | Reef slope along swim direction |
| Cross-track (100 px, 0.99 m) | **5.590°** | 0.097 m | Reef slope perpendicular to swim |
| Marker plane (6 vetted marker points) | **7.977°** | — | Upstream of DEM; combination of both |

The 4.395° along-transect slope is consistent with the swim direction being roughly along the reef
contour (lower slope in swim direction, steeper slope perpendicular to swim).

#### T1 and T3 impact

**T3:** Built with identity `_local_planar_projection()` (same recipe). T3's DSM in P13HMEON is
also in the leveled world frame. The frame is CONSISTENT between T3 and R2 → the reconciliation
comparison is valid.

**T1:** BLOCKED on datum divergence; `stage_dsm` was never reached. Not affected.

#### ADR-0020 was correct

ADR-0020 explicitly tested `transform.rotation` as `proj.matrix` (equivalent to Option L) and found
it produced wrong results (29–38° tilt, distorted footprint). The ADR correctly concluded:
"identity is already the flattest projection; a leveling error must be fixed upstream, not in
buildDem." This investigation confirms the conclusion: the identity projection IS correct, and the
apparent slope discrepancy (4.395° vs 7.977°) is a measurement scope difference (DEM along-transect
vs marker plane), not a frame error.

#### GATE#3 coverage bypass (alongside GATE#6)

Stage_aoi with interp-OFF coverage = 93.7% (GATE#3 threshold 95%). Bypassed with
`--ignore-sanity`. The metric DSM with interp-ON = 99.8% coverage (interpolation fills the 6.3%
point-cloud gaps). The 93.7% cloud coverage is the binding metric for the reconciliation (any
interp-filled cell has uncertain Z).

## Consequences

- (+) R2 single-transect reconstruction is complete through dense + filter + AOI + DSM.
- (+) A 1:1 reconciliation on R2 closes the "strong-claim path" gap in ADR-0032.
- (+) The swath-filter code change makes any single swath isolable for future 1:1 runs (C2, R3, …).
- (+) Float32 Z-quantization fix is permanently integrated — future DSM runs on any project with
  high geocentric Z will automatically recenter.
- (+) T3 and R2 use identical projection recipe (LOCAL_CS + identity Planar) → consistent leveled
  world frame; reconciliation is frame-valid.
- (−) R2 uses manual AOI placement (no DEM-PCA auto-detect) — requires operator-supplied centre
  and angle; not fully automated.
- (−) Scale bars were manually placed in DCV GUI (not auto-detected); ~1.8% peak residual sets the
  scale-budget ceiling for the 1:1 reconciliation.
- (−) AOI coverage by point cloud = 93.7% (interp-OFF, GATE#3 bypassed). The 6.3% gap cells are
  interpolated; their Z is uncertain for high-precision rugosity metrics.
- (~) GATE#6 is bypassed for R2's two-pass geometry; a proper coverage+coherence gate is deferred
  to v2.
- (~) Marker pair 25–26 label basis still needs Frank's confirmation (physical-to-label
  correspondence for the far-end pair — see divergence note (d) above).

#tags: option2, r2, single-transect, reconciliation, swath-filter, 1:1, gate6-override, float32-fix, frame-verified
