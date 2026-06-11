# ADR-0031 — QC gates bind to Toth Table S2; conformance/outcome split; RU is conformance, not outcome

**Status:** Accepted
**Date:** 2026-06-11
**Related:** ADR-0010 (Toth ESM Table S2 binding, PIFSC SOP superseded), ADR-0030 (reconciliation metric scope — on `feat/reconcile-metrics`)

**Numbering note:** confirmed against `0000-index.md` — 0028/0029 are
reserved-pending Chat-5 decisions (files on `fix/level-camera-nadir`), 0030 is
taken by the open `feat/reconcile-metrics` branch; 0031 is the next free number.

---

## Context

Chat 6 adds a QC validator that judges a completed Metashape run from its
`ProcessingManifest` (schema landed alongside; population from the real
report/environment is a later branch). The thresholds had to come from
somewhere, and the project has *two* candidate sources that disagree:

| parameter | Toth ESM Table S2 (binding, ADR-0010) | PIFSC SOP (reference only) |
|---|---|---|
| key point limit | **60,000** | 40,000 |
| reconstruction uncertainty | **20–40** (applied window) | ≤ 15 |
| tie point limit | **0** (unlimited) | 4,000 |

ADR-0010 already made Table S2 the parameter source for processing; a QC
gate quietly checking PIFSC numbers would fail every conformant run (or
worse, bless a non-conformant one).

A second confusion the validator must not encode: **reconstruction
uncertainty is not an outcome observable.** ESM Step 8 gradual selection
*applies* an RU threshold and deletes points above it — so the post-filter
maximum RU in the surviving cloud is ≈ the applied threshold by
construction. Treating "RU ≤ 15" as an outcome gate (the PIFSC framing)
would fail every Toth-conformant model that correctly applied a 20–40
window. The only meaningful question is conformance: *was the applied
threshold inside Toth's window?*

## Decision

1. **All QC thresholds derive from Toth Table S2** (ADR-0010 binding);
   PIFSC numbers appear nowhere as defaults. Every threshold is a
   `QCValidator` constructor parameter so a future calibration can move it
   without touching code — but the defaults are Toth's: accuracy `High`,
   key points 60,000, tie points 0, generic preselection on, RU window
   20–40, projection accuracy 3–4, reprojection-error threshold ≈ 0.3.
2. **Criteria are split into `conformance` and `outcome`** and both always
   run. Conformance answers "did we run what Toth ran?" (parameter
   equality/windows); outcome answers "did the run come out well?"
   (registration ratio ≥ 0.90, final reprojection RMS ≤ 0.52 px
   Toth-derived default with a 0.30 px target noted, scale-bar residuals).
   The split matters because the failure responses differ: a conformance
   failure means re-run or write a divergence-ledger entry; an outcome
   failure means investigate the data/network. A non-conformant run still
   gets its outcome evaluated (a divergent run that registered 99% is a
   different conversation than one that fell apart).
3. **Reconstruction uncertainty is a conformance check on the APPLIED
   threshold** (within 20–40), never an outcome gate, for the
   by-construction reason above.
4. **The scale-bar error threshold ships parameterized and unset**
   (`scalebar_max_m=None` → criterion reports not-evaluable). The PIFSC
   0.001 m is not hardcoded; the gate gets a number only after calibration
   against our observed residuals (T3/T1 scale-bar errors).
5. **Not-evaluable ≠ pass.** Unpopulated Optional manifest fields yield
   `passed=None` entries; a report with zero evaluable criteria has no
   overall verdict (`None`), and any single failure makes the overall
   verdict `False`.

## Consequences

- (+) The validator cannot silently drift to PIFSC numbers; the divergent
  values (60,000 vs 40,000; 20–40 vs ≤ 15) are named here and in tests.
- (+) `passed=None` three-state keeps half-populated manifests flowing
  through CI without fake greens, which is what lets the schema land
  branches before the report parser exists.
- (−) Until the parser branch lands, every real-world report is all-None —
  the gate exercises only synthetic fixtures for now.
- (−) The 0.52 px RMS default is Toth-*derived*, not Toth-*stated*; if a
  recomputation of their reported RMS distribution moves it, that's a
  constructor argument today and a default change (with ledger entry)
  later.
- (~) The scale-bar gate stays not-evaluable until someone feeds it a
  calibrated `scalebar_max_m`; that is intentional friction.

#tags: qc, gate, toth, table-s2, pifsc, reconstruction-uncertainty, manifest, provenance
