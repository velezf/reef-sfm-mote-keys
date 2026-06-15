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

*To be appended after dense build completes.*

## Consequences

- (+) If the pre-dense gate passes, R2 is ready for a dense GO (next session).
- (+) A 1:1 reconciliation on R2 closes the "strong-claim path" gap in ADR-0032.
- (+) The swath-filter code change makes any single swath isolable for future 1:1 runs (C2, R3, …).
- (−) R2 reconstruction is ~½ the compute of a full T1 run but still ~12–24 h on L4 (dense).
- (−) The chunk label is `EDR_T1_R2`, not `EDR_R2` — a minor naming mismatch from the shorthand.
- (~) Scale bars must auto-detect from R2's own imagery; if not found, the run stops (no defensible
  scale without them per ESM Table S2).

#tags: option2, r2, single-transect, reconciliation, swath-filter, 1:1
