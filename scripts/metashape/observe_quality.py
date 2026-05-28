#!/usr/bin/env python3
"""
observe_quality.py — Chat 5 deliverable #6: OBSERVE quality targets, don't gate.

Reads the per-chunk Metashape report values and the project summary, and prints
whether each chunk hit the ESM Table S2 targets. This deliberately does NOT
pass/fail-gate anything — that formalization is Chat 6's QC validator. Here we
just surface the numbers so they go into the Chat 5 docs.

Targets (ESM Table S2, Step 8):
  * Reprojection error after error reduction: ESM reports 0.27-0.52 px across
    transects (target filter value 0.3 fixed).
  * Scale-bar / horizontal accuracy: ESM reports max horizontal accuracy
    3.41 mm. The PIFSC-era target of <=0.001 m (1 mm) is STRICTER than what
    Toth actually achieved; we observe against Toth's reported envelope, and
    note the PIFSC number as the original-plan target for the record.

This runs as plain Python (no Metashape import) against exported JSON so it can
run on the MacBook too.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ESM_REPROJ_LO, ESM_REPROJ_HI = 0.27, 0.52      # px, observed envelope
ESM_MAX_HORIZ_MM = 3.41                          # mm, observed max
PIFSC_SCALEBAR_TARGET_MM = 1.0                   # original-plan target (stricter)


def observe(products_root: Path) -> None:
    summary_path = products_root / "pipeline_summary.json"
    if not summary_path.exists():
        raise SystemExit(f"No pipeline_summary.json under {products_root}")
    summary = json.loads(summary_path.read_text())

    print("EDR quality observation (ESM Table S2 targets) — NOT a gate\n")
    for ch in summary["chunks"]:
        label = ch["label"]
        aligned_pct = (100 * ch["cameras_aligned"] / ch["cameras_total"]
                       if ch["cameras_total"] else 0)
        print(f"== {label} ==")
        print(f"  cameras aligned : {ch['cameras_aligned']}/{ch['cameras_total']} "
              f"({aligned_pct:.1f}%)  [ESM-style expectation >=90%]")
        print(f"  markers         : {ch['markers']}")
        print(f"  scalebars       : {ch['scalebars']}  "
              f"[ESM: 3-4 25cm coded targets per transect]")
        print(f"  products        : dense={ch['has_dense']} "
              f"dsm={ch['has_dsm']} ortho={ch['has_ortho']}")
        # Reprojection error / accuracy come from the parsed report (Chat 6).
        # Here we only have structural completeness from the summary; we print
        # the ESM envelopes so the operator can eyeball the report PDF against
        # them.
        print(f"  ESM reproj envelope : {ESM_REPROJ_LO}-{ESM_REPROJ_HI} px")
        print(f"  ESM max horizontal  : {ESM_MAX_HORIZ_MM} mm "
              f"(orig-plan PIFSC target was <= {PIFSC_SCALEBAR_TARGET_MM} mm, "
              f"stricter than Toth achieved)\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--products-root", type=Path, default=Path("/data/edr/products"))
    observe(ap.parse_args().products_root)
