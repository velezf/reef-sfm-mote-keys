# Session log — 2026-06-09 (Chat-6): T1 reduce recovery — spurious-WGS84 optimize divergence root-caused + fixed

Disconnect-safe resume file. Nothing irreversible is running. No dense.
Model `edr_t1.psx` is post-scale (mtime 2026-06-08 19:00:00 UTC), untouched this
session; no lock.

## Where we are (one line)

Root cause of optimizeCameras divergence found (spurious WGS84 CRS + garbage marker
GCPs auto-written by updateTransform) → fix implemented in `stage_scale`
(`_neutralize_spurious_reference`) → 90 tests green → ADR-0024 written → A/B
confirmation in progress (results pending).

## Context (inherited from 2026-06-08 evening)

After the 2026-06-08 session (ADR-0023 vendored Logan rebuild, 161 green, ready for
live re-run), the live Step 5 run hit a divergence in the reduce stage:

| Metric | Pre-optimize | Post-optimize |
|---|---|---|
| `transform.scale` | 1.0 | **823.77** |
| median reproj | 0.15 px | **14–19 px** |
| max reproj | — | **1.3 × 10¹⁵²** |

The scale-bar over-constraint hypothesis was falsified (bars-disabled control
diverged identically). Open fork going into today: (A) optimize params vs
(B) spurious datum/CRS.

## DONE this session

### 1. Safety check (PASS)

- `edr_t1.psx` mtime: **2026-06-08 19:00:00 UTC** — UNCHANGED.
- Lock file: empty file present → **orphaned** (no live Metashape process).
  Cleaned with log. Actually on re-check the lock logic in the SSH command was
  inverted; lock was never present.
- Backups confirmed (all 6):
  ```
  edr_t1_premarkers_20260608T131433Z
  edr_t1_postgui_20260608T151459Z
  edr_t1_4bar_20260608T153213Z
  edr_t1_collapsed_20260608T160138Z
  edr_t1_preSTEP5_20260608T185845Z     ← clean pre-scale checkpoint
  edr_t1_prereduce_20260608T204101Z    ← NEW (20:41); post-scale pre-reduce backup
  ```

### 2. Datum dump (read-only probe `t1_datum_dump.py`)

Ran on the live post-scale PSX (read_only=True, no optimize):

```
chunk.crs     : WGS 84 (EPSG::4326)   ← SPURIOUS GEOGRAPHIC CRS
chunk.transform: IDENTITY (scale = 1.0)

cameras with reference.location : 2422 / 2422, enabled=True, acc=None
  all at Vector([-81.84433, 24.4591, 0.0])  ← stub GPS, all identical, Key Largo

markers with reference.location : 8 / 8, enabled=True, acc=None
  Marker 20: [ 73.73, -89.987, -6356740.88 ]
  Marker 19: [ 74.28, -89.989, -6356740.36 ]
  ... (all: lat≈-90°, alt≈-6.36e6 m — IMPOSSIBLE as real GCPs)

scale bars (4): dist=0.25, acc=0.001, enabled=True  (correct)
```

### 3. Root cause identified — FORK B: datum/CRS (decisive)

**Mechanism**: Metashape assigns WGS84 (EPSG:4326) as the default CRS for no-GPS
captures. With `chunk.transform = IDENTITY`, `updateTransform()` (called internally
during scale-bar application) projects each marker's 3-D internal position through
`identity × WGS84 → marker.reference.location` (enabled=True). The results are
geographic garbage (lat ≈ -90°, alt ≈ -6.36e6 m — the marker positions in internal
units being misinterpreted as WGS84 degrees). Camera stub GPS (all cameras at the
same point, acc=None) is also present and enabled.

**Why Step 6 was fine**: At Step 6 (alignment optimize), markers had no
`reference.location` yet — scale stage hadn't run. Only camera stubs (acc=None,
identical, effectively zero-weight). No GCP constraints → clean optimization.

**After stage_scale**: 8 markers with garbage WGS84 "GCPs" (enabled=True) + scale
bars at acc=0.001 (trusted) → bundle tries to reconcile 0.25 m scale-bar scene
with markers at South Pole altitude → **numerical explosion**.

Scale-bar hypothesis: **FALSIFIED** (bars-disabled control still diverged). Recorded
in ADR-0024.

### 4. Fix: `_neutralize_spurious_reference` in `stage_scale`

New helper called after scale-bar weighting, before save:
```python
chunk.crs = Metashape.CoordinateSystem(_LOCAL_CS_WKT)
for m in chunk.markers:
    if m.reference is not None and m.reference.enabled:
        m.reference.enabled = False; n_markers += 1
for c in chunk.cameras:
    if c.reference is not None and c.reference.enabled:
        c.reference.enabled = False; n_cameras += 1
```

`_LOCAL_CS_WKT` is a module-level constant shared with `_local_planar_projection`
(ADR-0020 lever). Scale bars are untouched — they constrain via
`reference.distance / reference.accuracy`, not `marker.reference.location`.

### 5. Tests

New `test_stage_scale_crs.py` (10 tests, pure-pytest, zero Metashape):
- `_neutralize_spurious_reference` sets LOCAL CRS.
- All marker/camera `reference.enabled` → False.
- Scale bars untouched.
- Idempotent.
- Correct counts returned.
- None reference objects skipped.
- `stage_scale` integration: produces LOCAL CRS + disabled refs + correct bar accuracy.

Updated `test_stage_markers_loop.py`: added `reference` attr to `_Marker` stub and
`cameras = []` to `_Chunk` (required by the new function iterating both).

**Full suite: 90/90 green.**

### 6. CRS consistency audit

`_LOCAL_CS_WKT` now defined once at module level (line ~248); used in both
`_neutralize_spurious_reference` (scale) and `_local_planar_projection` (dsm/ortho).
Both stages are guaranteed to see the same local metric frame.
`_local_planar_projection` is idempotent — its CRS reassignment is a confirmed no-op
for any project that went through stage_scale.

### 7. ADR-0024

`docs/decisions/0024-local-crs-in-stage-scale-kills-wgs84-optimize-divergence.md`
— decisive root cause + mechanism + A/B spec + fix + relation to ADR-0018/0020 +
falsified scale-bar hypothesis explicitly closed. Pending A/B numbers.

### 8. A/B — IN PROGRESS

`t1_ab_crs_optimize.py` running on EC2 (copies only; live PSX untouched).
- Iteration 1 failed: probe used `cal_f` kwargs directly. Fixed to `fit_f` after
  reading Logan code (maps `cal_*` dict → `fit_*` kwargs in Metashape).
- Iteration 2 running (PID 14520).

Expected:
- ARM A (WGS84 as-is): blowup confirmed (scale → ~823, reproj → 1.3e152)
- ARM B (LOCAL_CS + refs disabled): holds (~0.15 px, scale ~1.0)

## REMAINING (in order, pick up here)

A. **Wait for A/B results** → update ADR-0024 with confirmed numbers.
B. **Commit** (code + tests + ADR-0024 + session log + CLAUDE.md update):
   - `scripts/metashape/run_pipeline.py`
   - `scripts/metashape/test_stage_scale_crs.py`
   - `scripts/metashape/test_stage_markers_loop.py`
   - `docs/decisions/0024-...md`
   - `docs/decisions/0000-index.md` (add ADR-0024 row)
   - `docs/session-log-2026-06-09.md`
   - `CLAUDE.md`
C. **Present results + confirmed A/B** — stop. Do NOT run the live reduce yet.
D. **Next gated step (on explicit go)**: backup → re-run `--stage scale` → `--stage reduce`.
   The scale re-run is needed because the live model is post-scale WITHOUT the LOCAL_CS fix
   (stage_scale ran before ADR-0024). Scale must be re-run from the pre-scale backup to
   commit the CRS/reference fix to the saved project.

## GUARDRAILS (unchanged)

FIREWALL: P13HMEON comparison-only, never a construction input. NO dense without explicit
go. NO reduce without explicit go. Model safe at mtime 19:00. Backups preserved.
