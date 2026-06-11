# ADR-0028 — Corrected T1 transect Z window [−9.2, +1.8] m, surface-median-anchored

**Status:** Accepted
**Date:** 2026-06-10 (decided Chat 5; file backfilled 2026-06-11 from the CLAUDE.md record)
**Supersedes:** ADR-0026 (Z window only — the 10×1 m placement, centre, and 135° orientation of ADR-0026 stand)
**Related:** ADR-0025 (camera-nadir level), ADR-0027 (DSM 1 cm), ADR-0029 (full-area ortho workaround)

---

## Context

ADR-0026 set the transect AOI Z window to [−9.977, −2.977] m (7 m), derived
from a **uniform-gradient model**: 14.78 m total chunk Z over ~27 m mean XY
extent → 0.543 m/m × 10 m ≈ 5.4 m estimated local relief, plus 29% margin.
ADR-0026 itself flagged this as an estimate to be confirmed against the first
DSM run.

The first DSM run falsified the model. The build "succeeded" (rc=0) but the
DSM covered only **2.58 m of the 10.00 m transect — coverage 16.3%**: the
window had truncated the surface. A read-only Z-profile diagnostic
(`scripts/metashape/diag_transect_z_profile.py`, run against the pristine
post-dense snapshot) showed why: along the long axis the reef surface is
**trough-to-crest, not a uniform slope** — shoulder ~−2.1 m, trough ~−5.2 m,
crest ~−0.7 m. A fixed 7 m band placed by a gradient extrapolation from the
box centre misses the crest end entirely.

A truncated-run snapshot was retained for this supersede record:
`edr_t1_truncated_adr0026v1_20260610T232809Z.{psx,files}` (EC2 `/data/edr_work/`).

## Decision

**Anchor the Z window to the measured surface, not to a slope model:** the
window is centred on the **surface median Z** from the Z-profile diagnostic
and sized to bracket the observed trough-to-crest range with margin —
**[−9.2, +1.8] m** (11 m total) in chunk LOCAL_CS metres.

Re-run `aoi → dsm → ortho` with the corrected window.

## Result

- In-window points: **26.5 M** (from the 487.7 M-pt filtered cloud)
- AOI coverage: **16.3% → 97.1%**
- DSM extent: **2.58 m → 10.00 m** — full 1000×100 cells @ 1 cm
  (10.00 × 1.00 m, ADR-0027), sha `9cc8eb75…`
- Transect ortho rebuilt from the corrected DSM surface (ESM Step 15),
  2000×200 px @ 5 mm GSD, sha `e86deb03…`

## Consequences

- (+) The shipped T1 transect DSM/ortho cover the full analysis unit; the
  reconciliation metrics (ADR-0030) run on a complete surface.
- (+) "Anchor to measured surface median, never to a gradient extrapolation"
  is the rule for every future transect window; the diagnostic script is the
  reusable probe.
- (−) An rc=0 build is not a coverage guarantee — the truncated run passed
  every existing stage check. Coverage belongs in the product gate
  (tracked with the topo-gate recalibration on `fix/probe-topo-gates`).
- (−) The window is wider than the surface strictly needs (margin both
  sides); acceptable because the AOI XY crop and confidence filter already
  bound the point budget.
- (~) ADR-0026 remains authoritative for placement/orientation; only its Z
  window is superseded.

#tags: t1, aoi, z-window, dsm, coverage, truncation, transect, supersede
