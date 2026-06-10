# Static code review — 2026-06-10

**Reviewer:** Claude (Fable 5), static review only — no code executed, no Metashape, no EC2.
**Base commit:** `773dddd` (branch `fix/level-camera-nadir`), reviewed in worktree branch `review/fable-2026-06-10`.
**Scope:** `scripts/metashape/run_pipeline.py` and stages (markers/scale/reduce/level/region),
provenance + QC modules (`src/`), probes, test suites, spot layer, launchers, ADRs in
`docs/decisions/`. Vendored code (`vendor/logan_usgs`) and raw data excluded per brief.

---

## Summary verdict

The pipeline core is in strong shape: the four operational invariants (gated sentinels,
read-only fail-fast, stale-lock detection, verified saves) are genuinely implemented in
`run_pipeline.py` and the align launcher; the marker/health/level/CRS gates are real,
fail-closed, and well-tested off-instance (188 tests across 11 files, including negative
controls and boundary cases); ESM Table S2 / ADR-0010 parameters are faithful with no
drift found; the P13HMEON firewall is honored in code (reference appears only in advisory
gate #8); no secrets or credentials found anywhere in the tree.

The significant problems are concentrated in two places: **the spot orchestration layer
is desynchronized from the pipeline's stage list** (it predates the `scale` stage and can
neither run it nor ever report the pipeline complete), and **`_compute_level_up` has a
sign-convention edge case that would silently level a >90°-mis-oriented model upside
down**. Neither affects the currently verified T1 state, but both sit on paths this
project will exercise next.

---

## Blockers

### B1. Spot layer omits the `scale` stage and can never verify `report` — orchestration desync

- `scripts/spot/spot_controller.sh:50` — `PIPELINE_STAGES=(import step4 align markers
  reduce level dense filter aoi dsm ortho gate report)`. **`scale` is missing** (the list
  predates ADR-0022's markers/scale split; `run_pipeline.py:3041` has 14 stages, this has 13).
- `scripts/spot/pipeline_state.py:34-48` — `STAGE_ORDER` also omits `scale`/`esm.scale`.

Consequences, all silent at the orchestration level:
1. The reconciler can never report `scale` as `next_stage`, so on a project that is
   markers-passed but unscaled it returns `reduce`; the controller then launches reduce on
   an unscaled chunk. `run_pipeline.py:1814-1820`'s no-scale-bars critical alarm catches it
   (fail-safe), but the controller's promised "resume for free" property is broken for any
   project between markers and scale, and `stage_scale` is unreachable through the
   controller entirely.
2. `pipeline_state.py:47` checks `esm.report`, but `stage_report`
   (`run_pipeline.py:2898-3016`) never writes chunk meta. So `report` is permanently
   `missing`, `next_stage` never becomes `None`, the "pipeline complete" exit at
   `spot_controller.sh:97` is unreachable, and after a successful report stage the
   post-stage verification at `spot_controller.sh:141-143` sees `vnext == "report"` and
   exits 3 with `verify_not_persisted` — **a guaranteed false failure at the end of every
   full controller run**.

**Fix:** add `("scale", "esm.scale", None)` to `STAGE_ORDER` and `scale` to
`PIPELINE_STAGES` (between markers and reduce); either have `stage_report` write an
`esm.report` meta stamp (consistent with every other stage) or change the reconciler's
report check to test for `pipeline_summary.json` on disk. Then add a test that asserts
`pipeline_state.STAGE_ORDER` stage names == `run_pipeline.STAGES` — this desync happened
because two copies of the stage list exist with no cross-check; CLAUDE.md's invariants
explicitly extend to the spot layer.

### B2. `_compute_level_up` forces camera-up into the +Z hemisphere — a >90° mis-oriented model levels exactly upside down, silently

`scripts/metashape/run_pipeline.py:2143-2145`:

```python
# Apply same +Z convention as _fit_plane_normal so the angle comparison is valid.
if cam_up[2] < 0:
    cam_up = [-x for x in cam_up]
```

The camera-nadir up direction is the one quantity here whose sign is *physically
determined* (cameras point down at the reef, so `-mean_boresight` IS up, in whatever frame
the model currently sits). Forcing it into the +Z hemisphere of the *current, possibly
badly mis-oriented* world frame discards that information: if the model's true up has a
negative world-Z component (initial mis-level > 90°), the flip selects the inverted
vector, `stage_level` rotates the model upside down, and nothing downstream catches it —
the marker-plane tilt check at `run_pipeline.py:2322` is skipped for `camera_nadir` (log
only, per ADR-0025), the DEM-tilt gate is insensitive to a 180° Z flip, and the only
check that would catch it (cameras-above-markers) lives in a T1 probe, not the pipeline.

This is not theoretical: ADR-0025's own motivating case measured **80.6°** off vertical —
10° from the flip boundary. The whole point of camera-nadir leveling is rescuing badly
mis-oriented models.

**Fix:** never sign-flip `cam_up`. For the angle comparison, flip the *marker normal*
toward `cam_up` instead (or compare `min(angle, 180° − angle)`); use the raw
`-mean_boresight` as the returned up vector. Add a test: collinear markers + boresights
corresponding to a 120°-mis-leveled frame must still return an up vector that, applied,
puts cameras above the substrate (the current suite's scenarios all start < 90°, so this
case is untested — see N4).

---

## Should-fix

### S1. `--verify` cannot attest dense/level/filter — the honest-completion mechanism stops at markers

`run_pipeline.py:584-633` (`verify_project`) and `run_pipeline.py:3163-3174` accept only
`{'aligned','markers'}`. CLAUDE.md invariant #1 ("never write a completion marker not tied
to verified on-disk output") is explicitly required for the dense stage, which is what
runs next. Today the only on-disk dense verification is the spot reconciler
(`pipeline_state.py:69-70`), which is the component with bug B1; a tmux/manual dense run
(the current mode) has no `--verify-expect dense` to gate a sentinel on.

**Fix:** extend `verify_project` with `'scaled'` (esm.scale + scalebars present),
`'leveled'` (esm.level), `'dense'` (esm.dense + `chunk.point_cloud is not None`), and
`'filtered'`; have the post-dense launcher gate its sentinel on
`--verify --verify-expect dense` exactly as `run_t1_align_markers.sh:37-41` does for align.

### S2. Stale-lock cleanup does not recognize a live **GUI** Metashape session — it will unlink a lock held by an open GUI

`run_pipeline.py:503-510`: a process counts as a live holder only if its cmdline contains
both `"metashape"` **and** `"run_pipeline.py"`. A GUI Metashape session (cmdline
`/opt/metashape-pro/metashape …`, no `run_pipeline.py`) is invisible to this check, so
`open_or_create` (`run_pipeline.py:521-532`) declares its lock orphaned, unlinks it, and
opens read-write. The GUI touchpoint is a *documented* part of this workflow (marker
escalation → human fixes in GUI → re-run `--stage markers`): a human who leaves the
project open in the GUI while re-running the stage gets their lock deleted and two
writers on one project. The post-open `doc.read_only` check does not protect against
this — both sides open read-write.

**Fix:** treat any process whose cmdline contains `metashape` (excluding our own session)
as a live holder; the cost is occasionally refusing on an unrelated Metashape process,
which is the safe direction. Log the holder's cmdline either way (already done).

### S3. `--logan-module` help text describes the retired built-in fallback

`run_pipeline.py:3066-3069`: "If omitted, the built-in transcription is used and recorded
as a per-run documented departure." The built-in was removed by ADR-0023
(`test_network_health.py:343-348` proves `_run_builtin_reduction` is gone); when omitted,
the **vendored Logan** is used. An operator reading `--help` gets exactly the wrong idea
about the most safety-critical stage. **Fix:** reword to "Importable module name that
overrides the vendored USGS Logan copy (testing / re-pin only); default = vendored copy."

### S4. `--ignore-sanity` (and CLI threshold overrides) are not captured in provenance

A run with `--ignore-sanity` bulldozes past CRITICAL alarms (`run_pipeline.py:405-416`)
yet produces a `pipeline_summary.json` indistinguishable from a clean run:
`stage_report` (`run_pipeline.py:2901-2910`) records `asdict(PARAMS)` but not the
invocation. Per-stage metas record *their own* thresholds (good — e.g. markers at
`run_pipeline.py:1115-1123`, reduce at 1846-1850), but `ignore_sanity`, the health
overrides, `--quality-threshold`, and `--max-total-tilt-deg` are nowhere. For a
provenance-first project this is the one integrity gap found. **Fix:** record
`sys.argv` + the resolved args namespace (and a `sanity_alarms_ignored` count per stage)
into the summary; cheapest is one `esm.invocation` meta written per run.

### S5. Probe gates contradict the accepted T1 state — a re-run pre-dense would print "DO NOT launch dense" on a correct model

- `probes/t1_postlevel_probe.py:213-214` — `CAM_Z_RANGE_GATE = 4.0 m` and the
  cameras-above-markers check: both FAIL on the accepted T1 (14.78 m genuine
  depth-gradient relief). ADR-0025's acceptance note declares these false negatives and
  defers to `fix/probe-topo-gates`.
- `probes/t1_region_set_and_preflight.py:37-39` — `LONG_HI=18`, `SHORT_HI=14`,
  `UP_HI=5.0`: all three FAIL on the accepted region (28.9 × 25.4 × 15.3 m). This file is
  **not** covered by the ADR-0025 caveat-B list.

`run_t1_full_sequence.sh:104-106` correctly does *not* gate on the probe's exit code, but
nothing prevents a future launcher (or an operator reading `RESULT: FAILED … DO NOT
launch dense`) from acting on it. **Fix:** fold the region-preflight bounds into the
`fix/probe-topo-gates` recalibration; until then add a banner to both probes stating the
camera-Z/extent gates are T3-belt-calibrated and superseded for T1 by ADR-0025.

### S6. `stage_aoi` has unguarded crash edges on the imminent post-dense path

`run_pipeline.py:2550-2556`: `scale = chunk.transform.scale` can be `None` (division at
2570-2572 → `TypeError`); an all-NoData transient DEM makes `cells` empty →
`min()/max()` `ValueError` at 2555 and `ZeroDivisionError` in `_pca2d`
(`run_pipeline.py:2497-2498`, `n=0`). All produce raw tracebacks instead of the
structured critical alarms every neighboring failure mode gets (and the transient
interp-OFF DEM at 2553 is left attached in-memory, though never saved). **Fix:** guard
both (`transform_scale is None` → alarm like `stage_dense:2361-2365`; `if not cells:`
→ alarm "AOI DEM is all-NoData") before the math.

### S7. `segment_pointcloud.py` standalone entry bypasses the lock/read-only/save invariants

`scripts/metashape/segment_pointcloud.py:111-117`: `doc.open(..., read_only=False)` with
no stale-lock scan, no `doc.read_only` assertion, and a bare `doc.save()` with no
persistence verification — the exact trio of guards `run_pipeline.open_or_create`/`save`
exist to enforce (the production `--stage filter` path is fine; only this `main()` is
exposed). Given the filter stage runs right after the multi-hour dense, an unverified
save here recreates the 2026-06-04 incident shape. **Fix:** import and reuse
`open_or_create`/`save` from `run_pipeline.py` (it already `sys.path`-inserts the
directory in the other direction), or delete `main()` if the standalone path is dead.

---

## Nice-to-have

### N1. `_detect_markers` reports a wrong `final_tolerance` on cap exhaustion
`run_pipeline.py:1218`: if the while loop exhausts (`tol > marker_tolerance_max`), the
recorded `final_tolerance` is `max + step` (105), a tolerance never attempted. Record the
last *attempted* value.

### N2. Transect/dataset literals in production code (transferability notes)
`run_pipeline.py:637` — `_TRANSECT_RE = r"(EDR_T\d+)"` makes the flat-layout import path
EDR-only (foldered layout is generic). `run_pipeline.py:2428` bakes an "EDR_T8 saw ~24%"
comparison into a log line. Defaults at `run_pipeline.py:3055` (`/data/edr_work/products`)
and `:3122` (focal-decision path) are deployment literals. All acceptable for this
program (and the T1/T3 literals are otherwise correctly confined to `probes/` and
`scripts/ops/`), but these are the spots a future site port must touch; consider a
`--transect-regex` arg.

### N3. `esm.scale.scalebar_lengths_m` omits GUI-reused bars
`run_pipeline.py:1755`: `lengths.add(dist)` only on the created path, so a re-entry run
that reuses human-created bars records `scalebar_lengths_m: []` while 4 bars exist.
Collect from `chunk.scalebars` after the loop instead.

### N4. Pure-math geometry helpers are untested off-instance
`_jacobi_eig_sym3`, `_fit_plane_normal`, `_rot_normal_to_z`, `_apply_world_rotation`,
`_pca2d`, `_camera_track_sign` (`run_pipeline.py:2024-2109, 2493-2538`) are all
dependency-free but have no unit tests — notably `_rot_normal_to_z`'s antipodal branch
(`:2086-2088`) and the >90° inversion scenario from B2. The level test suite
(`test_stage_level_up.py`) tests only `_compute_level_up`'s selection logic, not the
rotation that gets applied. Cheap, high-value additions.

### N5. `run_t1_full_sequence.sh` restores over the live project with only a lock-file existence check
`scripts/ops/run_t1_full_sequence.sh:39-53`: `rm -rf` of the live `.files` is gated on a
manual lock check, not the live-holder scan the pipeline itself uses. Acceptable for a
supervised ops script; worth reusing the scan if this template outlives the recovery.

### N6. `_occupied_cells_world` iterates every DEM cell through Python `el.altitude()` calls
`run_pipeline.py:2479-2490`: fine for the 10×1 m AOI (~1e5 cells), but stage_aoi's first
pass runs it on the full-cloud DEM after `resetRegion()` (`:2552-2554`) — on T1's
~29×25 m extent that is ~7e6 sequential API calls. Expect this loop to dominate stage_aoi
wall time; consider sampling (as `_dem_plane_tilt` does at `:2660-2668`) for the PCA pass.

### N7. ADR-0025 internal inconsistency on the T1 spread ratio
`docs/decisions/0025-camera-nadir-leveling.md` states spread_ratio ≈ 0.10 (context, line
~28) and ≈ 0.149 (acceptance caveat A). Both are below the 0.25 threshold so nothing
changes, but the ADR should say which measurement is canonical.

### N8. RED/GREEN discipline is claimed but not auditable from history
Test files document the RED state ("RED until _compute_level_up is implemented",
`test_stage_level_up.py:15`), but tests and fixes land in single commits (e.g.
`08d30d0`), so the failing-first phase can't be verified from `git log`. If the
discipline matters to the portfolio narrative, commit the RED test first or paste the RED
run output into the commit message.

---

## Parameter fidelity — ESM Table S2 / ADR-0010 (no drift found)

| Parameter | Required (Toth ESM / ADR-0010) | Code | Verdict |
|---|---|---|---|
| Align accuracy | High | `downscale=1` (`run_pipeline.py:865`) | ✅ |
| Key point limit | 60,000 | `keypoint_limit=60_000` (`:118`) | ✅ |
| Tie point limit | 0 | `tiepoint_limit=0` (`:119`) | ✅ |
| Stationary tie points | exclude | `filter_stationary_points=True` (`:870`, `:120`) | ✅ |
| Reconstruction Uncertainty | 20–40 → 30 | `30.0` (`:133`) | ✅ |
| Projection Accuracy | 3–4 → 3.5 | `3.5` (`:134`) | ✅ |
| Reprojection Error | 0.3 fixed | `0.3` (`:135`) | ✅ |
| Dense quality | High | `downscale=2` (`:2370`, `:156`) | ✅ |
| Depth filtering | Mild | `MildFiltering` (`:157`, `:313`) | ✅ |
| Confidence filter | < 2 removed | `noise_confidence_threshold=2` (`:162`) | ✅ |
| DSM resolution | 1 cm | `0.01` (`:170`) — 1 mm misattribution corrected per ADR-0017 | ✅ |
| Ortho blend | Mosaic + hole fill | (`:173-174`) | ✅ |

Step-4 quality 0.50 is the ESM verbatim default with the documented per-run override
(`--quality-threshold`, T3 ran 0.30 as a recorded departure) — consistent with ADR-0017.

## Test suite assessment

188 test functions, all runnable off-instance via Metashape stubs. The gates are
*actually* tested, not just smoke-tested: boundary inclusivity at exact thresholds
(`test_marker_validation.py:450-458`), NaN/Inf fail-closed (`:416-434`), negative
controls proving guards are load-bearing (`test_network_health.py:430-448` re-fires the
2026-06-08 false positive with the old flag), production wiring pinned rather than
re-implemented (the phase matrix derives `check_scalebars` from the real
`HEALTH_CHECK_SCALEBARS` map), and transferability tests with foreign marker IDs
(`test_marker_validation.py:510-568`). The known mispairing residual risk is itself
documented as a test (`:488-499`). Provenance suite (`tests/`, 82 tests) exercises the
three-severity logic and dataset rules against a realistic fixture. Gaps: B2's inversion
case, the geometry helpers (N4), and the spot layer has **no tests at all** — which is
exactly where B1 lives.

## Provenance, firewall, secrets

- **Provenance:** input pinning is real (per-image SHA-256 + aggregate at
  `run_pipeline.py:719-740`), per-stage stats persist in chunk meta and assemble into
  `pipeline_summary.json`; human-touch vs headless marker provenance is distinguished
  (`:1352-1361`). Gap: S4 (invocation flags not captured).
- **P13HMEON firewall:** held everywhere I looked — reference enters only `stage_gate`
  check 8, hard-coded advisory (`run_pipeline.py:2720-2736`), never `core_failed`;
  level/aoi/scale take no reference inputs.
- **Secrets:** clean. No keys/tokens/passwords in `scripts/`, `src/`, `docs/`, `tests/`;
  IMDSv2 tokens in `scripts/spot/lib_spot.sh` are ephemeral by design; launch template
  enforces `HttpTokens: required`.

## Suggested order of work

1. **B1** (stage-list sync + reconciler `report` fix + sync test) and **S1**
   (`--verify-expect dense`) — both before trusting any spot-driven or sentinel-gated
   dense/post-dense result.
2. **B2** + its N4 test — before `stage_level` runs on any transect other than the
   already-verified T1.
3. S2–S7 in any order; S5 belongs in the existing `fix/probe-topo-gates` follow-up.
