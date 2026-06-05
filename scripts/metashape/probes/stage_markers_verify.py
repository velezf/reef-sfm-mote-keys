#!/usr/bin/env python3
"""stage_markers_verify.py — READ-ONLY verification of the headless marker-layer
gates (ADR-0022) on the real aligned T1/T3 projects.

It exercises the SAME code stage_markers runs — run_pipeline._extract_marker_records
(Metashape extraction) + run_pipeline.validate_markers (the pure a/b/c gates) — but
opens each project read_only=True and runs NO stage, so the on-disk projects are
untouched (the T3 codified product and the T1 aligned project are not mutated). It
prints each verdict and asserts the documented expectation:

  * EDR_T3 (known-good): PASS all three gates, 4 bars, inter-bar ratio ~1.09.
  * EDR_T1 (incoherent): ESCALATE — gate (a) orphans {13,24,26} / odd 7,
    gate (c) ratio ~1.35, gate (b) the load-bearing 15/16/19/20 all blow past the
    ceiling. Evidence: 24 sits in ~100+ cameras and still reprojects to garbage.

This is the read-only build-time check; the stage itself (which saves + escalates)
is NOT run here — that is the gated production run, authorized separately.

Usage:
  /opt/metashape-pro/metashape.sh -platform offscreen -r stage_markers_verify.py
Output is block-buffered under offscreen Metashape — it appears when the process
exits. Exit 0 = both verdicts as expected; non-zero = a mismatch to investigate.
"""
import json
import sys
from pathlib import Path

# Import the production module (Metashape is real under metashape.sh). run_pipeline
# guards main() behind __main__, so importing it runs no pipeline.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import run_pipeline as rp          # noqa: E402
import Metashape                   # noqa: E402

T1 = "/data/edr_work/edr_t1.psx"
T3 = "/data/edr_work/edr_t3.psx"


def _verdict_for(project):
    doc = Metashape.Document()
    doc.open(project, read_only=True)        # NO lock, NO mutation
    ch = doc.chunks[0]
    recs = rp._extract_marker_records(ch)
    verdict = rp.validate_markers(
        recs,
        resid_ceiling=rp.GATE_MARKER_RESID_CEILING_PX,
        interbar_ratio_max=rp.GATE_INTERBAR_RATIO_MAX,
    )
    return ch.label, recs, verdict


def _summary(label, recs, verdict):
    g = verdict["gates"]
    return {
        "transect": label,
        "passed": verdict["passed"],
        "n_markers": verdict["n_markers"],
        "detected_ids": sorted(r["id"] for r in recs
                               if r["id"] is not None and r["reconstructed"]),
        "proposed_pairs": verdict["proposed_pairs"],
        "candidate_bars": verdict["candidate_bars"],
        "gate_a": {"ok": g["a_parity"]["ok"], "orphans": g["a_parity"]["orphans"],
                   "odd": g["a_parity"]["odd_count"]},
        "gate_b": {"ok": g["b_coherence"]["ok"],
                   "load_bearing_flagged": g["b_coherence"]["load_bearing_flagged"]},
        "gate_c": {"ok": g["c_consistency"]["ok"],
                   "ratio": g["c_consistency"].get("ratio")},
        "resid_px_median_by_id": {r["id"]: r["resid_px_median"]
                                  for r in recs if r["id"] is not None},
        "projection_count_by_id": {r["id"]: r["projection_count"]
                                   for r in recs if r["id"] is not None},
        "suspect_ids": verdict["suspect_ids"],
    }


def main():
    failures = []

    for project, expect_pass in ((T3, True), (T1, False)):
        if not Path(project).exists():
            print(f"SKIP: {project} not present.")
            continue
        label, recs, verdict = _verdict_for(project)
        s = _summary(label, recs, verdict)
        print(f"VERIFY_JSON_BEGIN {label}")
        print(json.dumps(s, indent=2))
        print(f"VERIFY_JSON_END {label}")

        # --- assertions against the documented expectation ---
        if verdict["passed"] is not expect_pass:
            failures.append(f"{label}: passed={verdict['passed']} "
                            f"expected {expect_pass}")
        if expect_pass:
            if len(verdict["candidate_bars"]) != 4:
                failures.append(f"{label}: expected 4 bars, "
                                f"got {len(verdict['candidate_bars'])}")
            if not s["gate_a"]["ok"] or not s["gate_b"]["ok"] or not s["gate_c"]["ok"]:
                failures.append(f"{label}: a known-good transect failed a gate "
                                f"{s['gate_a']},{s['gate_b']},{s['gate_c']}")
        else:
            # T1: assert it escalates on (a) AND (c), with the documented orphans.
            if s["gate_a"]["ok"]:
                failures.append(f"{label}: gate (a) unexpectedly passed")
            if set(s["gate_a"]["orphans"]) != {13, 24, 26}:
                failures.append(f"{label}: orphans {s['gate_a']['orphans']} "
                                f"!= expected [13,24,26]")
            if s["gate_c"]["ok"]:
                failures.append(f"{label}: gate (c) unexpectedly passed "
                                f"(ratio {s['gate_c']['ratio']})")

    if failures:
        print("VERIFY RESULT: FAIL")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("VERIFY RESULT: PASS — T3 gates green, T1 escalates as documented. "
          "No project mutated (read_only).")


if __name__ == "__main__":
    main()
