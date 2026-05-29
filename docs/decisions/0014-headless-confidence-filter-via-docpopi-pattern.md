# ADR 0014 — Headless confidence noise filter uses setConfidenceFilter + cropSelectedPoints (DocPopi pattern); cleanPointCloud is documented-but-non-functional on 2.3.1 build 22446

Status: **Superseded by [ADR-0015](0015-headless-step13-engineered-departure.md)**
Date: 2026-05-28
Chat: 5

> **Supersession note (2026-05-28):** this ADR concluded that
> `cleanPointCloud(criterion=Confidence)` was non-functional based on a
> destructive probe that reported zero `point_count` delta. The probe
> itself was correct; the conclusion was wrong. `cleanPointCloud` marks
> points for deletion but `point_count` is stale until `compactPoints()`
> materializes the removal — undocumented Metashape behavior. The DocPopi
> probe pattern (`setConfidenceFilter + cropSelectedPoints`) only appeared
> to work because the probe called `compactPoints` after each pattern,
> masking that `cleanPointCloud` was working all along. ADR-0015
> investigates this with isolated probes (`probe_v8_cleanpc.py`) and
> restores `cleanPointCloud + compactPoints` as the API choice. This
> ADR's body is retained unchanged below for historical record.

## Context

[ADR-0013](0013-confidence-noise-filter-via-cleanpointcloud.md) concluded
that `Chunk.cleanPointCloud(criterion=Confidence, threshold=N)` was the only
documented headless API path for ESM Step 13 confidence filtering on
Metashape 2.x, and adopted it for both `scripts/metashape/smoke_test.py` and
`scripts/metashape/segment_pointcloud.py`. That conclusion was reached after
the prior session demonstrated empirically that `setConfidenceFilter` +
`assignClassToSelection` silently no-ops (the filter sets visibility but not
a selection, and the assign requires an actual selection).

On smoke v7, `chunk.cleanPointCloud(criterion=Confidence, threshold=2)`
removed 0 points on a 23.5M-point dense cloud, even though the cloud was
built with `point_confidence=True`. A subsequent threshold sweep from 1 to
256 also removed 0 at every value. The user's hypothesis at that point was
"confidence filtering is non-functional in this build" or "no points have
confidence < 2." A deeper investigation (this ADR) shows both hypotheses
were wrong; the real cause is more subtle.

## Investigation

Per a focused investigation prompt directing us to **distinguish a
generation-side problem (no confidence data stored) from a filter-side
problem (filter API broken)**, we ran two probes:

**1. Non-destructive probe** —
`scripts/metashape/probes/probe_confidence_present.py`. Opens the saved
smoke project read-only, exports an ASCII PLY with `save_point_confidence=True`
via `chunk.exportPointCloud(...)`, and inspects the PLY header.

Findings, on the v7 dense cloud (build Metashape Professional 2.3.1 build 22446):

- `pc.meta['BuildPointCloud/point_confidence'] = 'true'` — the build kwarg
  was honored.
- PLY header includes `property uchar confidence` — confidence data is
  stored per-point.
- `pc.has_point_confidence` attribute **does not exist** on this build (the
  API ref documents it; AttributeError on access). So our prior probe's
  AttributeError on `has_point_confidence` was a documentation gap, NOT
  evidence that confidence was missing.

Conclusion: **confidence data IS present on this dense cloud.** ADR-0013's
"cleanPointCloud is the only API" conclusion was based on assuming the
generation side worked; the generation does work, but `cleanPointCloud`
itself is the broken piece.

**2. Destructive probe** —
`scripts/metashape/probes/probe_confidence_delete.py`. Operates on a COPY
of the project. For each candidate API pattern, copies the .psx + .files,
opens read-write, re-confirms confidence presence via PLY export, runs the
candidate, prints `point_count` before/after, and reports `removed = before
- after`. Loud-fail (exit 2) if every candidate is a no-op.

## Empirical comparison table

Threshold N = 2 (matches ESM Step 13's "confidence < 2"). Source dense
cloud: 23,511,725 points, confidence data present.

| Pattern | Before | After | Removed | Error / Notes |
|---|---:|---:|---:|---|
| A. `setConfidenceFilter(0,2)` + `removeSelectedPoints()` | 23,511,725 | 23,511,725 | **0** | raises `Exception: Null point cloud selection` — `setConfidenceFilter` does not create a selection that `removeSelectedPoints` can act on |
| B. `setConfidenceFilter(0,2)` + `cropSelectedPoints()` (DocPopi literal) | 23,511,725 | 18,999,035 | **4,512,690** | works (19.2% of cloud removed) |
| B2. `setConfidenceFilter(2,255)` + `cropSelectedPoints()` (inverted range) | 23,511,725 | 0 | 23,511,725 | semantic-proof: `cropSelectedPoints` removes the VISIBLE set, not keeps it |
| C. `setConfidenceFilter(0,2)` + `removePoints(list(range(128)))` | 23,511,725 | 18,999,035 | **4,512,690** | works (identical to B) |
| D. `chunk.cleanPointCloud(criterion=Confidence, threshold=2)` | 23,511,725 | 23,511,725 | **0** | documented in API reference but non-functional on this build |

## Semantic clarification

The destructive probe results decode the API's actual semantics, which the
documentation does not state clearly:

- **`setConfidenceFilter(min, max)`** sets *visibility* to points with
  confidence ∈ [min, max]. It does not create a selection in the
  Metashape sense (a selection that `removeSelectedPoints` /
  `assignClassToSelection` can act on).
- **`cropSelectedPoints()`** removes the visible (filtered) set, despite
  the "crop" naming which conventionally implies "keep." Pattern B2 is
  the proof: `setConfidenceFilter(2, 255)` shows essentially all
  points (since confidence ∈ [1, 255] in practice), and
  `cropSelectedPoints()` then removes all 23,511,725.
- **`removePoints(list_of_classes)`** removes points whose class is in the
  list AND that are visible under the active filter. Pattern C with
  `list(range(128))` (all reasonable classes) is therefore equivalent to
  pattern B on a filtered cloud.
- **`cleanPointCloud(criterion=Confidence, threshold=N)`** is documented
  in the Metashape 2.3.1 Python API reference (`/pdf/metashape_python_api_2_3_1.pdf`,
  page 42) as the Chunk-level destructive cleanup for confidence, but
  empirically does nothing on this build/cloud even when confidence is
  verifiably stored. This is the documented-but-broken API.

The pattern came from the Agisoft forum thread "Removing low confidence
dense cloud points"
(<https://www.agisoft.com/forum/index.php?topic=15523.0>); user DocPopi's
example showed `point_cloud.setConfidenceFilter(min, max)` →
`point_cloud.cropSelectedPoints()` → `point_cloud.setConfidenceFilter(0,
255)` (to reset). Pattern C also appears as
`chunk.dense_cloud.setConfidenceFilter(0, 9)` →
`chunk.dense_cloud.removePoints(list(range(128)))` in
<https://www.agisoft.com/forum/index.php?topic=12114.0>.

## Decision

1. **Adopt the DocPopi pattern** for ESM Step 13 confidence filtering in
   both `scripts/metashape/smoke_test.py` and
   `scripts/metashape/segment_pointcloud.py`:

   ```python
   pc.setConfidenceFilter(0, upper)     # upper = max_conf - 1, ESM: conf < 2
   pc.cropSelectedPoints()              # removes the visible (low-conf) pts
   pc.setConfidenceFilter(0, 255)       # reset filter
   ```

   We use pattern B (DocPopi literal) rather than pattern C, because B's
   intent is clearer at the call site (no magic `range(128)`).

2. **Add a loud-fail guard** that exits with a non-zero status if the
   filter removed 0 points. Confidence data presence cannot be cheaply
   checked at runtime (no `has_point_confidence` attribute on this build);
   the only way to verify the filter actually did something is to compare
   `point_count` before and after. A silent no-op was the actual failure
   mode that produced ADR-0013's wrong conclusion — this guard catches it.

3. **Build tested:** Agisoft Metashape Professional 2.3.1 build 22446.
   Per [ADR-0002](0002-metashape-pinned-2-3-1.md), this build is the
   project's pinned version; the decision does not need to track other
   builds. If the project ever bumps Metashape, re-run
   `probes/probe_confidence_delete.py` to re-verify the pattern.

4. **ESM fidelity statement:** the production idiom matches the GUI's
   "remove low-confidence points" *outcome* (a dense cloud with the noise
   gone) rather than the GUI's "classify-and-keep" intermediate state. The
   GUI workflow labels noise as LowPoint and retains it for visualization
   and re-inspection; the headless pipeline removes outright. Downstream
   operations (`buildDem`, `buildOrthomosaic`, structural-complexity
   computation) consume the same minus-noise cloud either way, so the
   end-state for Chat 6's reconciliation is identical. The departure is
   deliberate, scoped, and documented in `segment_pointcloud.py`'s
   docstring.

5. **`cleanPointCloud(criterion=Confidence, threshold=N)` is NOT used.**
   It is documented in the API reference but does not remove points on
   2.3.1 build 22446 even with confidence data present. We do not use it
   anywhere in the codebase; the call appears once each in
   `smoke_test.py` and `segment_pointcloud.py` only in this commit, in
   the form of `# previously used cleanPointCloud — see ADR-0014` style
   archeology (none — both files are fully patched). If a future
   Metashape build fixes `cleanPointCloud`, simplification is a one-line
   diff; until then, the DocPopi pattern is the working path.

## Consequences

**Pro**

- Headless confidence filtering actually works. The smoke gate has a
  functional ESM Step 13, and production (run_pipeline.py → 
  segment_pointcloud.py) ships with a working ESM Step 13 rather than a
  silent no-op that would have invisibly corrupted Chat 6's metrics.
- The loud-fail guard is permanent infrastructure against silent no-ops
  in this region of the API. If a future Metashape upgrade changes filter
  semantics, the guard fires loudly instead of producing wrong numbers.
- The investigation discipline (separate generation-side from filter-side
  failures, verify confidence presence with a PLY export before testing
  filters, only probe destructively on copies) is now codified as
  reusable probe scripts in `scripts/metashape/probes/`. They are
  permanent reference artifacts, not session ephemera.
- The Agisoft forum's DocPopi pattern is now validated against this
  specific build. Anyone forking the project can re-verify in ~5 minutes
  by running `probes/probe_confidence_delete.py`.

**Con**

- The DocPopi pattern relies on Metashape's `cropSelectedPoints` having
  the documented-but-counterintuitive semantic of *removing* the visible
  set rather than keeping it. If a future Metashape build changes this
  to match the conventional "crop = keep" interpretation, our pattern
  becomes the opposite of intended and would remove the *high*-confidence
  points instead of the noise. The loud-fail guard would not catch this
  (it checks "did N change", not "was the correct N changed"). Mitigation:
  pin Metashape per ADR-0002; if a bump is ever proposed, re-run the
  destructive probe to confirm `cropSelectedPoints` still removes visible.
- ADR-0013 documented an empirically-wrong conclusion and is now
  superseded. The superseded ADR is retained for historical record (the
  reproducibility-process credibility this project is selling depends on
  showing what was tried and why it was wrong, not on hiding wrong turns).
- `cleanPointCloud(criterion=Confidence, threshold=N)` is genuinely
  broken on the pinned build and we have no Agisoft support ticket
  filed. That is a known external dependency on a vendor bug that we
  work around silently. If the broken behavior changes in a future
  build, the workaround still functions; the only risk is wasted
  developer time investigating the same bug if Metashape ever fixes
  `cleanPointCloud` and the docs become accurate.

## Notebook narrative

Confidence-based noise filtering of the dense point cloud (ESM Table S2
Step 13) is implemented headlessly in this project via the Agisoft Python
API. The pattern adopted is from the official Agisoft user forum and was
empirically validated on the pinned Metashape build (2.3.1 build 22446)
via a destructive probe on a copy of the project: enable visibility filter
to points with confidence below the threshold, then call the destructive
"crop selected points" method (which despite the name removes the
visible set), then reset the filter. The pinned build's documented
`cleanPointCloud(criterion=Confidence, threshold=N)` API was tried first
but does not remove points even with confidence data verifiably present
in the dense cloud, a finding established by exporting an ASCII PLY with
`save_point_confidence=True` and inspecting the header for a `property
uchar confidence` line. A loud-fail guard in the implementation refuses
to proceed if the filter removes zero points, ensuring that any future
silent no-op (e.g. from a cloud built without confidence enabled) is
caught at the point of failure rather than propagating invisibly into
the structural-complexity metrics. The departure from the GUI's
classify-and-keep workflow (which labels noise as LowPoint and retains
it) to the headless remove workflow is deliberate; the downstream
operations consume the same minus-noise cloud regardless.

#tags: metashape-api, dense-cloud, confidence, segment, smoke-test, esm-step-13, supersedes-0013
