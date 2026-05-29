# ADR 0016 — `buildDem` extent inference on unscaled chunks: BBox region clip insufficient; full headless smoke of DSM/ortho deferred to scaled production runs

Status: Accepted with caveat (open question deferred to T3 dress rehearsal / v2)
Date: 2026-05-29
Chat: 5

## Context

In the Chat 5 smoke test (`scripts/metashape/smoke_test.py`), `buildDem`
on EDR_T8's dense cloud OOMs with `std::bad_alloc` regardless of how the
dense cloud is constrained beforehand. Empirical evidence from the smoke
v9 and v10 runs (post-ADR-0015 cleanPointCloud + compactPoints filter):

| Source | Bbox extent (chunk units) |
|---|---|
| `chunk.region` (sparse-tie-point-derived) | 53 × 42 × 16 |
| `pc.extent()` post-filter (23.5M dense points after `cleanPointCloud(Confidence, 2)` + `compactPoints`) | **40.9 × 34.2 × 9.9** |
| My constructed `Metashape.BBox(min=center-size/2, max=center+size/2)` (xy footprint of `chunk.region`) | **~40 × 34** |
| `buildDem` actual DEM extent **without** `region=` clip (v9) | **~27,800,000 × ~19,900,000** |
| `buildDem` actual DEM extent **with** `region=BBox(chunk.region.xy)` clip (v10) | **~5,870,000 × ~4,600,000** |

The BBox region clip helps by ~5×, but `buildDem` still uses an extent
~110,000× larger than the BBox values I pass. Whatever bbox `buildDem`
uses, it is NOT `pc.extent()`, NOT `chunk.region`, and the explicit
`region=BBox(...)` argument is interpreted in some scaled coordinate
space rather than chunk-internal — likely the unscaled chunk's
`chunk.transform.scale` (set to an arbitrary value during bundle
adjustment without metric scale) is being applied to BBox values
internally.

The dense point cloud's confidence filter (ADR-0015) operates on the
point cloud and works correctly — 7.4M low-confidence outliers removed
on EDR_T8 — but doesn't constrain DSM bbox inference. The two are
independent failure modes.

## Decision

For the Chat 5 smoke, **wrap `buildDem` and `buildOrthomosaic` in
try/except for MemoryError** and continue without DSM/ortho if they
fail. The smoke completes with dense.ply, processing report,
focal_decision.json, and bbox_pre_post_filter.json — which are the
artifacts the smoke's actual mandate (validate the focal-length A/B and
the ESM Step 13 confidence filter end-to-end) requires. DSM/ortho API
coverage on an unscaled chunk is deferred to the T3 dress rehearsal or
v2 work, where the bbox inference question can be properly investigated.

Production (`run_pipeline.py`) does NOT need this workaround. The
production pipeline runs after the manual DCV interlude (ESM Step 7
marker detection + scale-bar assignment; ESM Step 11 Jenkins Alignment
Helper coordinate frame placement). On a scaled chunk, `buildDem`'s
auto-inferred extent is in meters and tractable: a 10 × 10 m transect
at 1 cm resolution produces a 1000 × 1000 px DEM.

## Consequences

- Chat 5 smoke's DSM/ortho API coverage is deferred. The smoke validates
  alignment, error reduction, focal-length A/B decision, dense build,
  ESM Step 13 confidence filter, and PLY/report export. It does not
  validate buildDem/buildOrthomosaic/exportRaster on an unscaled chunk
  because those APIs cannot be invoked successfully in that state, and
  the only fix would be either (a) magic-number coarsening of
  smoke_res, (b) a deep dive into the chunk.transform.scale BBox
  interpretation, or (c) running the smoke on a scaled chunk (which
  requires the manual DCV interlude that the smoke is designed to run
  before).
- The MemoryError is logged loudly in the smoke output so the partial
  result is visible to anyone reading the logs.
- Production carries no risk from this: the workaround is `smoke_test.py`-only
  and the production buildDem call in `run_pipeline.py` runs on a
  metric-scaled chunk and was not affected by this issue.
- **Open question for T3 dress rehearsal or v2:** what coordinate space
  does `Metashape.BBox` get interpreted in when passed to `buildDem`?
  Hypothesis: `chunk.transform.scale` is applied. A simple probe at the
  start of the T3 work (or whenever a scaled chunk is first available)
  can verify: print `chunk.transform.scale` on an unscaled chunk, then
  on the same chunk post-scale-bars, and check whether the ratio
  matches the observed 110,000× BBox interpretation factor. If yes,
  the workaround is to divide BBox values by `chunk.transform.scale`
  before passing to `buildDem`. If no, the investigation continues.

## Empirical record

- Smoke v9 (no BBox clip): `buildDem` extent ~27.8M chunk units → OOM.
- Smoke v10 (`region=BBox(chunk.region.xy)` clip): `buildDem` extent
  ~5.87M chunk units (5× reduction, still 110,000× larger than the
  BBox argument I passed) → OOM.
- Smoke v11 (this ADR's decision applied): the MemoryError is caught,
  dense.ply + report + focal_decision.json + bbox_pre_post_filter.json
  are exported. Smoke completes cleanly with partial outputs.

Logs preserved at `/data/edr_work/logs/smoke_v9_*.log` and
`/data/edr_work/logs/smoke_v10_*.log`; bbox JSON at
`/data/edr_work/smoke/products/bbox_pre_post_filter.json`.

#tags: metashape-api, buildDem, dense-cloud, bbox, smoke-test, unscaled-chunk, deferred, t3-dress-rehearsal
