# ADR-0034 — Frame-retention QC criterion closes corpus-blind step4 alarm gap

**Status:** Accepted
**Date:** 2026-06-16
**Related:** ADR-0017 (step4 image-quality filter), ADR-0031 (QC gate provenance)

---

## Context

`run_pipeline.py` guards ESM Step 4 (image-quality disable) with a single absolute alarm:

```python
ALARM_MAX_DISABLED = 200   # of ~522: more than this disabled in Step 4 is suspect
```

This constant was sized against EDR_T3's ~522-image corpus. For EDR_T1_R2 (272 images),
140 cameras were disabled at the 0.50 threshold (51.5% of the corpus) — a rate that should
raise concern — yet `140 < 200` so no alarm fired. The guard is corpus-blind.

ADR-0017's T3 A/B (probe `scripts/metashape/probes/ab_quality_threshold.py`) established
the empirical record:

| Arm | Threshold | Disabled | Retained | Corpus aligned |
|-----|-----------|----------|----------|----------------|
| q050 (Toth verbatim) | 0.50 | 242/522 = 46.4% | 53.6% | 26.8% |
| q030 (floor)         | 0.30 |   5/522 =  1.0% | 99.0% | 98.7% |

The 0.30–0.50 discard band is fully usable (235/237 = 99.2% of those frames aligned
on the floor arm). High disable rates reflect a threshold-calibration problem, not
genuinely bad imagery.

## Decision

Add a `frame_retention` outcome criterion to `QCValidator`:

```
observed  = 1 − (step4_images_disabled / step4_images_analyzed)
threshold = frame_retention_min  [constructor param, default 0.60]
pass      = observed >= threshold
not-eval  = either field is None, or analyzed == 0
```

The 0.60 default (fail if >40% disabled) is anchored to ADR-0017's T3 A/B:

- T3 q050: 53.6% retained → **FAIL** (historically caused ≤27% corpus alignment)
- R2 q050: 48.5% retained → **FAIL** (140/272 disabled; never tripped the absolute alarm)
- T3 q030: 99.0% retained → **PASS** (wide margin from threshold)

The criterion is `"outcome"` (did the run produce a usable model?), consistent with
`registration_ratio` and `final_reprojection_rms`.

Supporting schema additions to `OutcomeBlock`:
- `step4_images_analyzed: int | None` — cameras submitted to `analyzeImages()`
- `step4_images_disabled: int | None` — cameras disabled (quality < threshold)

These fields are populated by the `esm.step4` chunk-metadata block that `stage_step4`
already writes to the PSX.

## Consequences

- (+) `QCValidator` now catches corpus-relative excessive frame loss that `ALARM_MAX_DISABLED`
  cannot — the R2 case (51.5% disabled, alarm silent) would have failed this gate.
- (+) Threshold is a constructor parameter: callers can tighten it for high-quality corpora
  or loosen it for known-turbid surveys without touching the pipeline.
- (+) Three-state semantics preserved: a manifest without step4 stats is not-evaluable,
  never silently passing.
- (~) `ALARM_MAX_DISABLED` in `run_pipeline.py` remains as a runtime alarm (fires during
  processing); this criterion is a post-hoc QC gate on the saved manifest. They are
  complementary, not redundant — fix `ALARM_MAX_DISABLED` to be corpus-relative separately.
