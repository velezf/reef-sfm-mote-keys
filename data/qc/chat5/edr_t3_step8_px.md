# EDR_T3 — ESM Step 8 error reduction, px QC record

Companion to `edr_t3_step8_px.json` (the machine-readable artifact Chat 6's
provenance layer parses). Status: **post_reduce / final-for-T3**. Measured with
the **fixed** repo probe `scripts/metashape/probes/reprojection_rms_px.py`
(Metashape 2.x: the tie-point `.coord` is a length-4 homogeneous vector and must
be sliced to length-3 before `Matrix.mulp()` — the prior probe crashed on 2.3.1).

## Reprojection RMS (pixels)

| | px | ESM envelope | verdict |
|---|---|---|---|
| Pre-reduce | **0.9361** | 0.55–2.22 (before) | within |
| Post-reduce | **0.3499** | **0.27–0.52 (after)** | **WITHIN** |

~63% decrease (ESM reports ~65% average). The pre-reduce value is preserved here
because it can never be recomputed once reduction ran.

## Tie points (over-thinning check)

`2,441,345 → 822,351` (66.3% removed). By filter: RU>30 −105,839; **PA>3.5
−1,363,893 (dominant cut)**; RE>0.3 −149,262. 822k across 515 cameras is ample to
seed dense; in-envelope RMS + intact camera set indicate a healthy reduction.

## Scale bars (post-reduce, final-for-T3)

| Pair | Residual |
|---|---|
| 25‑26 | **+15.1 mm** (documented worst bar) |
| 13‑14 | −4.8 mm |
| 15‑16 | −6.9 mm |
| 19‑20 | −4.6 mm |

All 4 enabled, ref 0.250 m, `transform.scale` locked at 0.236959.

**Root cause (imagery-limited, not optimize-fixable):** automatic coded-target
detection performed poorly on the grainy diver imagery; markers were placed (and
re-centered) manually — better than auto — but centering is pixel-limited, giving
imagery-limited scale-bar accuracy ~2× the ESM's 3.41 mm. The tie-point px RMS
(0.35 px, in envelope) is **unaffected**: it depends on reconstruction geometry,
not marker centering.

**Decision — Case B hold-out NOT run.** Scale is locked from Update Transform
(`locked=true`, 0.236959), so re-optimizing on the 3 control bars cannot move it,
and the cause is imagery-limited rather than something a re-optimize can fix.
Pair 25‑26 is recorded as the documented worst bar, **not** held out. Scale
refinement (unlock + bundle-refine, or re-place markers) is deferred to
T1/production.
