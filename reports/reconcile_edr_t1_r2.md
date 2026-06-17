# Reconciliation report — EDR_T1_R2

Survey: 2023-07-11 · Reconstruction: Q030 single-transect · Generated: 2026-06-17 (Chat 10)

Published reference: Toth et al. 2025 ESM Table S2
`mean_elevation = 0.242 m · rugosity = 1.415 · vrm (MultiscaleDTM) = 0.076`

---

## All footprint + frame states

| state | DSM sha | dims | leveling | mean\_elev | Δ | rugosity | Δ | VRM (Python) | Δ |
|-------|---------|------|----------|:----------:|:-:|:-------:|:-:|:------------:|:-:|
| pre-zeropitch | `50d1f143` | 999×100 | camera-nadir | — | +144.2% | — | −3.3% | — | −13.2% |
| zeropitch full | `2c04b8a2` | 1007×118 | camera-nadir + ZP | — | +32.3% | — | −2.8% | — | −13.9% |
| **zeropitch 10×1** | **`dcec116b`** | **1007×100** | **camera-nadir + ZP** | **0.309 m** | **+27.7%** | **1.372** | **−3.0%** | **0.065** | **−14.1%** |
| marker-plane 10×1 † | `8db23560` | 1005×100 | marker-plane | 0.376 m | +55.4% | 1.333 | −5.8% | 0.084 | +10.1% |

**Bold row = canonical reconcile basis.** Pre-zeropitch and zeropitch-full absolute values not measured directly; Δ from those passes.

† Marker-plane is a sensitivity measurement only — hypothesis falsified (ADR-0037).

---

## Residual attribution

**mean\_elevation +27.7%** — Cross-axis slope: our DSM carries 6.39° cross-axis dip; the published DSM carries ~1°.
Estimated cross-slope contribution: (0.5 m) × tan(6.39°) ≈ 0.056 m; observed delta 0.067 m.
This is **survey-unanchorable**: neither camera-nadir nor marker-plane can anchor the cross-axis from the
available survey controls (6 collinear scale-bar markers, spread\_ratio 0.00085). ADR-0037 falsified the
marker-plane alternative — it made the cross worse (12.15°). NOT a processing artifact. NOT GATE#6.

**rugosity −3.0%** — Stable across all states (−3.3 pre / −2.8 full / −3.0 clipped). Characterized as
sparse-coverage fidelity deficit (ADR-0032); no redo warranted.

**VRM −14.1% (Python)** — Python implementation is +13% vs MultiscaleDTM R package (ADR-0032); real
gap ≈ −24% = genuine surface smoothness relative to published. Slope-invariant; stable across all states.
Settled.

---

## Scripts

- `scripts/metashape/apply_zero_pitch.py` — Zero-pitch frame
- `scripts/metashape/sensitivity_markerplane.py` — marker-plane sensitivity (transient)
- `scripts/metashape/check_master_rotation.py` — master integrity check

## ADR refs

ADR-0033 · ADR-0036 · ADR-0037
