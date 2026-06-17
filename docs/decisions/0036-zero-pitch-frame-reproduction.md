# ADR 0036 — Zero-pitch frame reproduction (Alignment Helper Step 11)

Status: Accepted
Date: 2026-06-17
Chat: 9
Related: ADR-0033 (Option-2 R2 reconstruction), ADR-0025 (camera-nadir leveling),
ADR-0037 (leveling-reference sensitivity — marker-plane falsified)

## Context

After camera-nadir leveling (`stage_level`) and the full T1_R2 pipeline, the
`edr_r2_q030.psx` master has a 4.11° along-midline pitch (Marker 26→16). The
published Toth 2025 workflow (Alignment Helper Step 11) applies a "Zero pitch"
refinement: rotate about the Y-axis so the midline is horizontal, using the
two-marker-midline approach. This ADR records the headless reproduction of that
step, the footprint regression it introduced, and the attribution of the
remaining mean\_elevation gap after clipping.

## Decision

Reproduce Alignment Helper Step 11 headlessly on a permanent WORK copy
(`edr_r2_q030_zeropitch_20260617.psx`); never touch the master (`edr_r2_q030.psx`).

### Implementation details

**Midline selection:** distance > 9 m AND smallest angle to X axis → Marker 26 ↔
Marker 16 (9.805 m, 1.51° to X). Distance threshold 9 m is required to select the
full-transect pair, not mid-transect pairs (~5 m).

**Rotation convention:** `math.atan(diff[z]/diff[x])` and `math.atan(diff[y]/diff[x])`
— ratio form, NOT `math.atan2`. The original Alignment Helper source uses ratio
`atan`, not `atan2`. When the transect runs in the −X direction (`diff[0] < 0`),
`atan2` returns ≈ 180°; `atan` returns the correct small angle. Applied as:

```python
chunk.transform.rotation = chunk.transform.rotation * euler2mat([yaw, pitch, 0])
```

Right-multiply in chunk local space, matching the Alignment Helper's
`refineButtonClicked` logic.

**Verify before save:** post-rotation along-midline pitch must be < 0.30° or abort
without saving.

### Geometry after Zero-pitch (WORK copy)

| axis | before | after |
|------|--------|-------|
| along (Marker 26→16) | 4.11° | 0.086° |
| cross (DSM plane fit) | 6.39° | 6.39° (unchanged — physical slope) |
| raw relief (Z range) | 1.275 m | 0.680 m |

### Footprint regression

The yaw component of the Zero-pitch rotation (−1.51° — the midline is not exactly
parallel to the raster X axis) causes `buildDem` to widen the belt from 1.00 m to
1.18 m (1007×118 instead of 1007×100). This is self-introduced, NOT GATE#6
(the pre-zeropitch q030 DSM was exactly 10×1 m).

**Fix:** symmetric 9/9 trim in Y → clipped 10×1 m DSM (1007×100, sha `dcec116b`).

### Master integrity

`edr_r2_q030.psx` verified CLEAN throughout:
- chunk.zip sha `43547ec5` — unchanged
- Along-pitch 4.1071° (not ~0°) — verified read\_only=True

### Reconcile on clipped 10×1 DSM vs T1\_R2/confidence

| metric | ours | published | Δ |
|--------|------|-----------|---|
| mean\_elevation\_standardized | 0.309 m | 0.242 m | +27.7% |
| rugosity | 1.372 | 1.415 | −3.0% |
| VRM (Python) | 0.065 | 0.076 | −14.1% |

## Attribution of residuals

**mean\_elevation +27.7%:** Attributable to cross-axis divergence (our DSM: 6.39°;
published: unknown but implied ~1° from ADR-0032 survey context). Zero-pitch
removes along-axis tilt but is silent on cross-axis. Cross-axis slope elevates
the mean standardized elevation because the DSM spans more Z range for the same
horizontal footprint: estimated contribution (0.5 m) × tan(6.39°) ≈ 0.056 m;
observed delta 0.067 m.

**This is NOT a fixable leveling-reference artifact.** Marker-plane leveling was
tested (ADR-0037): it made the cross-axis WORSE (6.39° → 12.15°) because the 6
markers are nearly collinear (spread\_ratio 0.00085 ≪ threshold 0.25). The residual
is survey-unanchorable: neither camera-nadir nor marker-plane anchors the cross-axis
from the survey controls available in this dataset. The +27.7% gap is bounded by
the sensitivity table in ADR-0037 and characterized as a genuine cross-convention
divergence, not an artifact of our processing.

**rugosity −3.0%:** Stable across all passes (−3.3% pre-zeropitch, −2.8% full,
−3.0% clipped). Characterized as real: sparse-coverage fidelity deficit (ADR-0032).

**VRM −14.1% (Python):** Python implementation is +13% vs MultiscaleDTM R package
(ADR-0032); real gap ≈ −24% = genuine surface smoothness. Settled.

## Script

`scripts/metashape/apply_zero_pitch.py` — headless, EC2, WORK copy only.
`scripts/metashape/check_master_rotation.py` — read-only master integrity check.
Tests: `tests/test_zero_pitch_frame.py` (12/12 green on `feat/zero-pitch-frame`).
