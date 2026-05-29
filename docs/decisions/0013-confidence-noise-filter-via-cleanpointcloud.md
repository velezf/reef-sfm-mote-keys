# ADR 0013 — ESM Step 13 confidence filter: Python implementation choice

Status: **Superseded by [ADR-0015](0015-headless-step13-engineered-departure.md)**
Date: 2026-05-28
Chat: 5

> **Supersession note (2026-05-28, revised):** this ADR was originally
> superseded by ADR-0014 on the (incorrect) grounds that
> `cleanPointCloud(Confidence, ...)` was non-functional on Metashape 2.3.1
> build 22446. ADR-0015 supersedes both: `cleanPointCloud` was working all
> along; the "0 removed" reading was an artifact of `point_count` being
> stale until `pc.compactPoints()` materializes the deletion. The
> `cleanPointCloud` API choice this ADR proposed was correct in substance;
> ADR-0015 restores it with the materialization step explicit and reframes
> the whole decision as an engineered destructive departure from Toth's
> classify-and-keep workflow. This ADR's body is retained unchanged below
> for historical record.

## Context

Toth et al. 2025 ESM Table S2 Step 13 describes confidence-filtering the
dense cloud via "assign points with confidence < 2 to noise, exclude from
downstream operations." The published workflow uses Metashape's GUI
Confidence Filter and Classes assignment.

Empirically established that Metashape 2.3.1 Python API exposes
confidence-based point filtering through exactly one documented method:
`Chunk.cleanPointCloud(criterion=Confidence, threshold=N)`, which removes
points outright rather than reclassifying them. The full set of documented
`criterion=`-taking methods (`cleanModel`, `cleanPointCloud`,
`cleanTiePoints`) are all destructive. No documented
`assignClass(criterion=Confidence)` or equivalent exists. The only
classify-and-keep path is manual per-point iteration (slow on 30M+ point
clouds).

## Decision

Use `cleanPointCloud(criterion=Confidence, threshold=2)` for the headless
pipeline. This is a semantic departure from the GUI workflow (remove vs
classify-and-keep) but functionally equivalent for the downstream operations
actually used in this project (`buildDem`, `buildOrthomosaic`, structural
complexity computation), which consume the cloud minus noise — identical
inputs regardless of whether "minus noise" was achieved by deletion or
class-based exclusion.

Empirical confirmation via `/tmp/metashape_api.txt` search (May 28, 2026) and
probe runs on EDR_T8 dense cloud. Threshold value of 2 matches ESM Table S2's
"confidence < 2" specification.

Applied to both `scripts/metashape/smoke_test.py` (Chat 5 gate) and
`scripts/metashape/segment_pointcloud.py` (ESM Step 13 segmentation for the
real pipeline). The latter previously used a `setConfidenceFilter` +
`assignClassToSelection` chain that silently no-ops on this build: the filter
sets visibility but no selection, so `assignClassToSelection` raises
"Null point cloud selection" — or, if wrapped in a try/except as written, was
a no-op the smoke would have caught at run time and the production run would
not. The chain bug was caught by the smoke before it reached T1/T3.

## Consequences

The resulting cloud does not preserve original-vs-noise classification
metadata that the GUI workflow would. If a future analysis needs to inspect
what was filtered, the operation would need to be re-run with manual
per-point iteration (preserving the labelled cloud). For SfM-derived metric
reconciliation (the project's actual purpose), this is irrelevant.

Additional consequences:

- The smoke's DSM/ortho build succeeds — dense-cloud outlier triangulations
  (a side effect of unscaled bundle adjustment, see ADR-0012) are gone, the
  bbox collapses to the real reef footprint, and a plain
  `smoke_res = max(chunk.region.size) / 2000` works without inflation
  factors, explicit region clips, or other heuristics.
- `segment_pointcloud.py` actually does the thing its name implies. The
  prior silent no-op would have been invisible in production: the script
  returns successfully, the downstream metric numbers look plausible, but
  noise is never removed.
- `segment_pointcloud.py` no longer matches ESM Step 13 verbatim. A reviewer
  reading the script alongside Toth's ESM expecting the classify-as-LowPoint
  step will see *removal* instead. The docstring + this ADR + a log line
  referencing ADR-0013 are the mitigations; this divergence is the right
  thing to flag in the writeup under "implementation choices."
- This decision is locked to Metashape 2.x. Metashape 1.x exposed a
  selection→assignClass chain that translated the GUI workflow directly.
  ADR-0002 pins the project to 2.3.1, so no migration concern in scope.

## Notebook narrative

The dense-cloud noise filter for Step 13 of Toth et al. 2025's processing
ESM (Table S2) is implemented in this project via
`Chunk.cleanPointCloud(criterion=Confidence, threshold=2)`. This is the only
criterion-based confidence filter exposed in the Metashape 2.3.1 Python API:
the GUI workflow is *classify and keep* (relabels low-confidence points as
"Low Point (noise)" but retains them in the cloud), whereas `cleanPointCloud`
is *remove*. For the structural-complexity metrics this chat produces, the
two are functionally equivalent — noise points would be excluded from metric
computation under either workflow — but the script implementation departs
from the ESM-GUI semantics by one step. An earlier draft of the script
attempted the literal GUI translation
(`setConfidenceFilter` → `assignClassToSelection`) and silently produced no
classification because the filter sets visibility, not a selection — a bug
caught only because the Chat 5 smoke test ran the same code in a context
where its no-op caused a downstream `std::bad_alloc` in the DSM build. The
project's smoke-test discipline thus directly prevented an invisible
no-op-noise-filter outcome in the production runs.

#tags: metashape-api, dense-cloud, confidence, segment, smoke-test, esm-step-13
