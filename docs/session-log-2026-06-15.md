# Session log — 2026-06-15

## State on exit

**Branch:** `feat/reconcile-r2-transect`  
**Project:** `/data/edr_work/edr_r2.psx`  
**Snapshot:** `snap-0b10abc94d12b78e1` (State=completed, tagged `r2-pre-dense`, taken before dense)

### Stages completed (R2 transect)

| Stage | Status | Key metric |
|-------|--------|-----------|
| import | ✓ | 272 cameras loaded |
| step4 | ✓ | 140/272 disabled (51.5%) — ADR-0033 note (a) |
| align | ✓ | 131/272 aligned |
| markers | ✓ | 6 markers, 4 scale bars |
| scale | ✓ | RMS 0.1397 m (below 0.27-0.52 band) — ADR-0033 note (a); peak residual 1.8% |
| reduce | ✓ | |
| level | ✓ | 7.977° post-level tilt — ADR-0033 note (c) |
| dense | ✓ | 70,351,962 pts, ~5.2 min on 1× L4, High quality Mild filter |
| filter | ✓ | 70,351,962 → 47,137,394 pts (33.0% removed, confidence threshold=2) |
| **aoi** | **BLOCKED** | GATE#6 fired — see below |
| dsm | NOT RUN | stage_aoi failed first |

### GATE#6 failure — decision required

`stage_aoi` ran PCA on the 47M-pt confidence-filtered cloud and found:

- **EVR = 0.877** (threshold: ≥ 0.95)
- **Aspect = 2.671** (threshold: ≥ 5.0)
- **coverage_interp_off = 93.7%** (shell gate: ≥ 95%; would have also failed)

Root cause: R2 out-and-back geometry — two passes slightly laterally offset create a footprint that is
~2.7:1 (length:width) rather than the ≥5:1 expected for a single-pass lawnmower belt. The GATE#6
thresholds were calibrated for T3 belt geometry.

**Coverage improvement confirmed:** diagnostic used camera-centroid centering → 68.2%. stage_aoi used
PCA point-cloud-centroid centering → 93.7%. PCA centering works; the gate thresholds are the issue.

Log: `/data/edr_work/logs/r2_aoi_dsm_20260615T185404Z.log`  
Error line: `PipelineSanityError: EDR_T1_R2: GATE#6 footprint not belt-shaped (evr=0.877 < 0.95 or aspect=2.671 < 5.0)`

### Decision options (A-vs-B)

**A — Override GATE#6 for this run using `feat/aoi-manual-override` stash:**
```bash
git checkout feat/aoi-manual-override
git stash pop   # stash@{0} = gate footprint-override in run_pipeline.py
# then re-run stage_aoi + stage_dsm
```
The stash only modifies `scripts/metashape/run_pipeline.py`. Inspect what the override does before applying.

**B — Recalibrate GATE#6 thresholds for out-and-back geometry:**
Lower EVR threshold (e.g. ≥ 0.80) and/or aspect threshold (e.g. ≥ 2.5) for single-transect out-and-back
projects, or add a `--transect-type out-and-back` flag that relaxes the gate. Document in ADR-0033.

**Preferred:** discuss with Frank before acting (prove-before-fix working style).

### ADR-0033 divergence notes (written to disk)

- **(a)** RMS 0.1397 m below 0.27-0.52 calibrated band → step4 disabled 51.5% of frames
- **(b)** 1.8% peak scale residual: dist(15,16)=0.2456 m, dist(19,20)=0.2539 m, dist(25,26)=0.2504 m
- **(c)** 7.977° post-level tilt = reef slope; ~1.28 m drop over 9.25 m; feeds elevation reconcile
- **(d)** Far bar 25-26 per consecutive-ID protocol [Frank to confirm]

File: `/data/reef-sfm-mote-keys/docs/decisions/0033-option2-r2-single-transect-reconstruction.md`

### Git state on exit

Branch `feat/reconcile-r2-transect` — **committed + pushed** (or pending; check `git status`).  
Commits on this branch beyond `origin/main`:
- `f4494d3` feat(r2): Option-2 R2 single-transect pre-dense setup (ADR-0033)
- (new commit from this session) dense + filter results + GATE#6 findings + ops scripts

### Pending scripts (ready to run after gate decision)

| Script | Location | Purpose |
|--------|----------|---------|
| `run_r2_aoi_dsm.sh` | `scripts/ops/` | Runs stage_aoi + stage_dsm (will re-run after gate fix) |
| `r2_verify_dsm.py` | `/data/edr_work/probes/` | Export dsm.tif + Z profile + slope verification |
| `r2_render_pngs.py` | `/data/edr_work/probes/` | Hillshade + elevation PNGs (needs dsm.tif) |

### Resume checklist

On next session:
1. `git status` in `/data/reef-sfm-mote-keys` — confirm clean
2. Decide A vs B on GATE#6 (see above)
3. If A: inspect `feat/aoi-manual-override` stash diff before applying
4. Re-run `scripts/ops/run_r2_aoi_dsm.sh` (stage_aoi → coverage check → stage_dsm)
5. `r2_verify_dsm.py` → Z profile (expect ~1.0-1.4 m end-to-end drop for 7.977° tilt, NOT 0.25 m)
6. `r2_render_pngs.py` → present hillshade + elevation PNGs to user
7. STOP before reconcile

### Instance / EBS

- Instance: g6.4xlarge, 1× NVIDIA L4 GPU
- EBS volume: `vol-08bcf0ab11df2c9ed`
- Snapshot: `snap-0b10abc94d12b78e1` State=completed (`r2-pre-dense`)
- Metashape trial expires ~2026-06-26/27
