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

---

## Evening session — full T1 sequence + ADR-0025 + region (2026-06-09 ~19:30–22:15 UTC)

### ADR-0025: camera-nadir leveling fix

**Bug:** `stage_level` used marker-plane normal as UP. T1 markers are near-collinear
(spread_ratio eig[1]/eig[0] ≈ 0.10), giving an ill-defined plane normal → world-Z 80.6°
off vertical, camera-Z range 23.7 m.

**Fix:**
- Extracted `_compute_level_up(mk_positions, cam_boresights, ...)` as pure-Python testable function
- Guard 1 (collinear): spread_ratio < 0.25 → use camera-nadir UP silently
- Guard 2 (disagreement): well-spread markers but angle > 15° → alarm + camera-nadir fallback
- `stage_level` tilt gate skipped when `level_method == "camera_nadir"`
- 11 new tests (RED → GREEN); full suite 198 tests green
- Committed on `fix/level-camera-nadir` (08d30d0)

### Pipeline run: markers → scale → reduce → level

Restored from `edr_t1_preSTEP5_20260608T185845Z` (pre-scale, pre-ADR-0024).

**Failure recovered before this run:** earlier attempt restored from `edr_t1_prereduce_20260608T204101Z`
(which was pre-ADR-0024 — CRS=WGS84, refs enabled). PA `optimizeCameras` diverged → sigma0=14879
→ Logan RE loop ran 42+ min without convergence. Killed, correct starting point used.

**Results (correct run):**
- markers: EXIT 0 (re-entry, already validated)
- scale: EXIT 0 — LOCAL_CS set, 8 marker + 2422 camera reference.enabled disabled (ADR-0024)
- reduce: EXIT 0 — 53 Logan optimizations; 3,568,318 tie pts; sigma0 0.159; RMS 0.1471 filter units; ~100 min total (Logan tail drained slowly to 0 selections at RE 0.3)
- level: EXIT 0 — camera-nadir UP fired (spread_ratio=0.1490); boresight 0.00° from (0,0,-1); scale 0.15246 preserved

**Post-level probe (camera-nadir gates):**
- boresight tilt: **0.00°** [PASS] — was 80.6°
- camera-Z range: 14.78 m [probe FAIL vs 4 m gate — false negative, see below]
- cameras-above-markers: FAIL [false negative]
- scale: 0.152463 [PASS]
- scale-bar RMS: 10.65 mm [matches expected]

### Topography diagnostic (t1_camz_diag.py)

Camera-Z range classified as **genuine reef topography**, not outliers/distortion:
- marker Z spread: 4.51 m (19/20 at −1.54 m → 15/16 at −6.06 m, smooth spatial gradient)
- tie-point P1–P99 spread: 13.17 m (reef surface confirms large relief)
- camera/tiepoint spread ratio: 0.74 (cameras track reef relief)
- P5–P95 = 9.69 m = 66% of 14.78 m range (genuine spread, not outlier tails)
- below-P5 cameras (118) at X [−8.8, −6.5] — 6+ m from weak 19/20 zone
- plane-fit R² = 0.33 (non-planar transect, consistent with curved topography)
- scale-bar RMS 10.65 mm — no dome distortion

ADR-0025 **accepted** with caveats: world-Z = reef-normal reference (not gravity); probe
gates (camera-Z < 4 m, global cameras-above-markers) are T3-belt-specific false negatives
for a depth-gradient transect. Recalibration logged as `fix/probe-topo-gates` (TDD, later).

### Region set (t1_set_region.py)

Derived AABB in leveled world frame from cameras ∪ sparse, Z trim [P0.5, P99.5]:
- X: [−19.4, +9.5] = 28.9 m
- Y: [−8.4, +17.0] = 25.4 m
- Z: [−11.8, +3.5] = 15.3 m  (deep extension preserved; within expected 14–16 m)
- Coverage: 99.82% of trimmed sparse inside [PASS]
- 56 cameras outside (above-P95 shallow cameras; informational)

**WARNING for dense:** region is intentionally loose (survey footprint + margin).
AOI crop before DSM is MANDATORY to avoid DEM OOM on the full 29×25×15 m volume.

### Snapshots
- `edr_t1_postlevel_adr0025_20260609T220420Z.{psx,files}` — post-level, pre-region (12G)
- `edr_t1_preregion_20260609T220902Z.{psx,files}` — pre-region write guard (12G)

### Commits pushed to origin/fix/level-camera-nadir
```
c392c36 chore(CLAUDE.md): update resume pointer — T1 fully prepped for dense
8a181a1 docs(ADR-0025): accept camera-nadir leveling for T1 — topography verdict + caveats; region set
43e5bc3 probe: add ADR-0025 camera-nadir verification section to t1_postlevel_probe
08d30d0 fix: stage_level camera-nadir UP for collinear markers (ADR-0025)
```

### State at close
EC2: no Metashape processes, no lock, no tmux. Live PSX mtime 2026-06-09 22:09:41 UTC.
Branch `fix/level-camera-nadir` pushed. **Ready for AM dense GO.**
