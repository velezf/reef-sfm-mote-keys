# v2 Roadmap — open items carried forward

Items that are defined, scoped, and not blocked — but deferred from the current
Chat-6 / Chat-7 scope.  Each entry notes the source context so it can be
resumed without archaeology.

---

## 1. T1_R2 orientation/reversal verification (BLOCKER for directional products)

**Status:** Open — unverified.
**Source:** ADR-0038 ⚠ OPEN OUTCOME ITEM.

Check 7 (`7_orientation_plus_x`) FAILS on T1_R2 (`v=false`).  CLAUDE.md notes
"Benign 135°-vs-+X convention mismatch.  No product flip."  That is a bare
assertion with no backing calculation.

**Required before shipping any directional T1_R2 product:**
1. Re-run `stage_gate` on `edr_r2_q030_zeropitch_20260617.psx`; capture and
   record the `firstX`/`lastX` values from the gate alarm text.
2. Confirm geometrically: is the camera track at ~135° to +X (rotation), or
   at ~180° (flip)?  If 135°: the product is rotated but not reversed.
3. Add a visual or georeferenced confirmation (e.g. compare an identifiable
   feature's along-track position in the ortho against a known survey direction).
4. Write the finding in ADR-0033 (which was referenced but never created as a
   file in `docs/decisions/`).

**Exposure:** rugosity, VRM, yaw-invariant mean elevation are unaffected.
Ortho/DSM directional presentation (left/right assignment, asymmetry analysis,
georeferenced overlay) is the exposure.

---

## 2. ADR-0033 — never written

**Status:** Open.
**Source:** CLAUDE.md ADR table; referenced throughout as the T1_R2
option-2 re-process decision record.

ADR-0033 is cited in CLAUDE.md but the file `docs/decisions/0033-*.md` does not
exist.  The substance is scattered across CLAUDE.md and commit messages.
Write it: option-2 single-transect R2 re-process decision, GATE#6 bypass,
float32 T_z fix, frame_retention result, and the open orientation item (item 1
above, once resolved).

---

## 3. Phase 4 audit-capture CLI + markdown renderer

**Status:** Deferred from Chat 6.
**Source:** Chat 6 scope notes.

`capture_audit.py` produces `CaptureAuditReport` but has no entry point.
Phase 4 items:
- CLI subcommand: `reef-sfm audit <manifest.yaml>` → prints a markdown table of
  liabilities with status, observed, threshold, source.
- Markdown renderer for `CaptureAuditReport` (mirrors `QCReport.to_json`).
- SaaS artifact: the rendered report as a committed markdown file alongside the
  JSON QC report (e.g. `reports/audit_edr_t1_r2.md`).

---

## 4. GateCheckResult has no source field

**Status:** Open — schema gap.
**Source:** ADR-0038 Consequences.

`GateCheckResult` carries `check_id`, `passed`, `observed`, `threshold`,
`advisory`, `characterized`, and `note` — but no `source` field.  Gate checks
cannot cite their ADR or the pipeline constant that set the threshold (e.g.
`GATE_COREG_TOL_M`) in the schema record.  A `source: str | None = None`
field on `GateCheckResult` + a matching key in the pipeline dict would close
this.  The `QCCriterion.source` pattern is already established.

---

## 5. UNSOURCED_THRESHOLD not yet enforced in capture_audit

**Status:** Deferred — defined but unenforced.
**Source:** ADR-0038, Liability taxonomy.

`Liability.UNSOURCED_THRESHOLD` is in the enum and severity ordering but
`classify()` never fires it.  The intent: fire when a threshold is present but
carries no citation (source field empty or None).  Requires GateCheckResult to
have a source field (item 4 above) before this can be wired.

---

## 6. fix/probe-topo-gates — topo-transect gate recalibration

**Status:** Open branch, not merged.
**Source:** CLAUDE.md non-blocking follow-ups; ADR-0025 Caveat B.

Check 2 (`total_tilt_deg` 8.71° > 6.0°) fails on T1_R2 because the 6.0°
threshold was sized for flat-belt geometry, not depth-gradient topo transects.
`footprint_explained_var` None-guard (`0bfb4c3`) is untested — needs a RED test
before merge.  Also: `camera-Z < 4 m` and `cameras-above-markers` gates are
T3-belt-specific and should be replaced for depth-gradient transects.

---

## 7. Blocker 2 — hemisphere flip alarm in stage_level

**Status:** Open blocker.
**Source:** CLAUDE.md Blockers.

`stage_level` camera-nadir collinear path has no alarm when flip angle > 90°.
A model that levels "upside down" (camera boresight pointing up) would pass
the existing collinearity guard and produce a silently inverted reconstruction.

---

## 8. README / CLI entry point pass

**Status:** Deferred from Chat 6.
**Source:** CLAUDE.md NEXT: CLI/README/docs.

The `reef_sfm_provenance` package has no user-facing README beyond the package
docstring.  Minimum: a `README.md` in `src/reef_sfm_provenance/` describing the
three entry points (manifest schema, QC validator, capture audit), the fixture
format, and how to run the test suite.

---

## 9. Close ADR-0033 marker 25–26 label item

**Status:** Pending Frank.
**Source:** CLAUDE.md open items.

Marker pair 25–26 label basis pending Frank's confirmation of physical-to-label
correspondence for the far-end target.  Needed to finalize ADR-0033 (item 2).
