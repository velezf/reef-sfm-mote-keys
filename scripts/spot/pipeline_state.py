#!/usr/bin/env python3
"""pipeline_state.py — HONEST per-stage state, derived from the project on disk.

Part B (spot orchestration), built 2026-06-05. Run under the Metashape Python
(`metashape.sh -platform offscreen -r pipeline_state.py ...`).

WHY THIS EXISTS
The 2026-06-04 incident was a lie: a sentinel said "done" when nothing had
persisted. The spot controller must never repeat that, so it does NOT trust its
own bookkeeping — it reconciles against ground truth. Ground truth = the
project's own `esm.<stage>` meta PLUS the actual Metashape artifact on disk
(tie points, point cloud, DEM, ortho). This script reopens the project
READ-ONLY (no lock — safe even mid-run, like verify_project) and reports, per
stage, one of:
    done          meta present AND (for heavy stages) the artifact is present
    inconsistent  meta present but the artifact is MISSING  <-- the lie class
    missing       no meta yet (stage not run)
plus the next stage to run (first non-`done` stage in pipeline order).

It is read-only and methodology-free: it asserts nothing about parameters, only
about what landed. The controller uses `next_stage` to resume and refuses to
advance past any `inconsistent` stage.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Pipeline stage order — kept in sync with run_pipeline.py STAGES. Each entry:
#   (stage, meta_key, artifact_check_name)
# artifact_check_name is a key into ARTIFACT_CHECKS below; None => meta-only.
STAGE_ORDER = [
    ("import",  "esm.import",  None),
    ("step4",   "esm.step4",   None),
    ("align",   "esm.align",   "tie_points"),
    ("markers", "esm.markers", "markers"),
    ("reduce",  "esm.reduce",  "tie_points"),
    ("level",   "esm.level",   None),
    ("dense",   "esm.dense",   "point_cloud"),
    ("filter",  "esm.filter",  "point_cloud"),
    ("aoi",     "esm.aoi",     None),
    ("dsm",     "esm.dsm",     "elevation"),
    ("ortho",   "esm.ortho",   "orthomosaic"),
    ("gate",    "esm.gate",    None),
    ("report",  "esm.report",  None),  # report writes products, not chunk meta
]


def _meta_get(chunk, key, default=None):
    """Read JSON-encoded meta written by run_pipeline._meta_set (mirror)."""
    raw = chunk.meta[key] if key in chunk.meta else None
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


def _artifact_present(chunk, name: str) -> bool:
    """Does the heavy artifact actually exist on disk? Mirrors verify_project."""
    try:
        if name == "tie_points":
            return chunk.tie_points is not None and len(chunk.tie_points.points) > 0
        if name == "markers":
            return len(chunk.markers) > 0
        if name == "point_cloud":
            return getattr(chunk, "point_cloud", None) is not None
        if name == "elevation":
            return getattr(chunk, "elevation", None) is not None
        if name == "orthomosaic":
            return getattr(chunk, "orthomosaic", None) is not None
    except Exception:  # noqa: BLE001 — any API error => treat as not present
        return False
    return False


def reconcile(project_path: Path) -> dict:
    import Metashape  # imported lazily so `python -m py_compile` works anywhere

    if not project_path.exists():
        return {"project": str(project_path), "error": "project does not exist",
                "chunks": [], "next_stage": None, "any_inconsistent": False}

    doc = Metashape.Document()
    doc.open(str(project_path), read_only=True)  # read-only => no lock taken

    chunks_out = []
    # Per-stage rollup across chunks: a stage is project-"done" only if every
    # chunk reports it done; "inconsistent" if any chunk has meta-without-artifact.
    rollup = {st: {"done": 0, "inconsistent": 0, "missing": 0} for st, _, _ in STAGE_ORDER}

    for chunk in doc.chunks:
        stages = {}
        for stage, meta_key, art in STAGE_ORDER:
            meta = _meta_get(chunk, meta_key)
            has_meta = meta is not None
            if not has_meta:
                status = "missing"
            elif art is None:
                status = "done"  # meta-only stage; meta presence is the signal
            else:
                status = "done" if _artifact_present(chunk, art) else "inconsistent"
            stages[stage] = {"status": status, "has_meta": has_meta,
                             "artifact": art}
            rollup[stage][status] += 1
        chunks_out.append({"label": chunk.label, "stages": stages})

    n = max(1, len(doc.chunks))
    any_inconsistent = any(r["inconsistent"] > 0 for r in rollup.values())
    next_stage = None
    for stage, _, _ in STAGE_ORDER:
        if rollup[stage]["done"] < n:  # not done on every chunk
            next_stage = stage
            break

    return {
        "project": str(project_path),
        "n_chunks": len(doc.chunks),
        "rollup": rollup,
        "chunks": chunks_out,
        "next_stage": next_stage,
        "any_inconsistent": any_inconsistent,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True, type=Path)
    ap.add_argument("--write", type=Path, default=None,
                    help="Also write the JSON state to this path (atomic).")
    args = ap.parse_args()

    state = reconcile(args.project)
    out = json.dumps(state, indent=2, sort_keys=True)
    print(out)
    if args.write:
        tmp = args.write.with_suffix(args.write.suffix + ".tmp")
        tmp.write_text(out)
        tmp.replace(args.write)  # atomic on POSIX
    # Exit 2 if any stage is inconsistent (meta-without-artifact) so callers can
    # hard-stop on the lie class; 0 otherwise.
    return 2 if state.get("any_inconsistent") else 0


if __name__ == "__main__":
    sys.exit(main())
