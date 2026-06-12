#!/usr/bin/env python3
"""EDR reconciliation driver (Chat 6, ADR-0032).

Two read-only analyses against the P13HMEON comparison-only store (firewall
325dbc7 — these rasters/tables are never a pipeline input):

  (A) FUNCTION VALIDATION — our ADR-0030 metric functions vs the published
      MultiscaleDTM values, computed on the SAME surface: the local published
      EDR_T3 C1 / R1 confidence DEMs. This isolates implementation deltas
      (especially VRM: our Sappington vs their MultiscaleDTM) from data deltas.

  (1) ENVELOPE DIAGNOSTIC — our metrics on our real EDR_T1 area-survey
      center-cut DSM, placed against the published EDR_T1 confidence POPULATION
      (the nine transects). A distribution check, NOT a per-transect delta:
      EDR_T1 is a 9-transect subsite and our DSM matches none of them 1:1
      (ADR-0032).

Run:  uv run python scripts/reconcile/run_edr_reconciliation.py
Reads only; writes nothing.
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

from reef_sfm_provenance.reconcile.harness import compute_metrics, load_dsm

ROOT = Path(__file__).resolve().parents[2]
P13 = ROOT / "data/comparison-only/P13HMEON"
TABLE = P13 / "topographic_complexity/Coral_reef_topographic_complexity_data.csv"
OUR_T1_DSM = ROOT / "products/EDR_T1/edr_t1_transect_dsm_20260610T234951Z.tif"

PUB = {"rugosity": "full_area_rugosity", "vrm": "vrm_mean", "mean_elevation": "stand_mean_elev"}


def published_rows(**filt: str) -> list[dict]:
    rows = []
    with TABLE.open(newline="") as f:  # read-only firewall
        for r in csv.DictReader(f):
            if all(r[k] == v for k, v in filt.items()):
                rows.append(r)
    return rows


def fmt_delta(ours: float, pub: float) -> str:
    d = ours - pub
    return f"{ours:8.4f}  pub={pub:7.4f}  Δ={d:+8.4f}  ({d / pub * 100:+6.1f}%)"


def part_a() -> None:
    print("=" * 78)
    print("(A) FUNCTION VALIDATION — our functions vs MultiscaleDTM, identical surface")
    print("=" * 78)
    for tid in ("C1", "R1"):
        dem = P13 / f"20230711_T3_{tid}_DEM_confidence.tif"
        row = published_rows(Subsite="EDR_T3", Transect_ID=tid, Filter="confidence")[0]
        arr, cell = load_dsm(dem)
        ours = compute_metrics(arr, cell)
        print(f"\nEDR_T3 {tid} (confidence)  cell={cell:.4f} m  shape={arr.shape}")
        for m in ("rugosity", "mean_elevation", "vrm"):
            print(f"  {m:15s} {fmt_delta(ours[m], float(row[PUB[m]]))}")


def option_1() -> None:
    print("\n" + "=" * 78)
    print("(1) ENVELOPE DIAGNOSTIC — our EDR_T1 center-cut vs published T1 population")
    print("=" * 78)
    arr, cell = load_dsm(OUR_T1_DSM)
    ours = compute_metrics(arr, cell)
    import numpy as np
    finite = arr[np.isfinite(arr)]
    print(f"\nour DSM: shape={arr.shape} cell={cell:.4f} m  "
          f"elev_range={finite.max() - finite.min():.3f} m  (min={finite.min():.3f}, max={finite.max():.3f})")

    pop = published_rows(Subsite="EDR_T1", Filter="confidence")
    print(f"published EDR_T1 confidence population: n={len(pop)} transects "
          f"({sorted(r['Transect_ID'] for r in pop)})")
    for m in ("rugosity", "mean_elevation", "vrm"):
        vals = [float(r[PUB[m]]) for r in pop]
        lo, hi, mean = min(vals), max(vals), statistics.mean(vals)
        inside = "INSIDE" if lo <= ours[m] <= hi else "OUTSIDE"
        print(f"\n  {m}: ours={ours[m]:.4f}")
        print(f"     published range [{lo:.4f}, {hi:.4f}]  mean={mean:.4f}  -> ours is {inside} the range")


def option_2_input() -> None:
    print("\n" + "=" * 78)
    print("(OPTION-2 INPUT) imagery separability — reported separately (see notes)")
    print("=" * 78)
    img_root = Path("/data/raw/P1WHKTRD/EasternDryRocks")
    print(f"image_root (per run_config): {img_root}")
    print(f"present locally: {img_root.exists()}  (EC2 path; box stopped — inspected via metadata/provenance)")


if __name__ == "__main__":
    part_a()
    option_1()
    option_2_input()
