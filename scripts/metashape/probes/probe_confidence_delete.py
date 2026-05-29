#!/usr/bin/env python3
"""
probe_confidence_delete.py — destructive test of confidence-deletion idioms.

Operates on a COPY of the project (.psx + .files), NEVER the original. The
session's prior probe lost a dense cloud by running destructive ops in place;
this script enforces the copy invariant.

For each candidate API pattern, opens a fresh copy, runs it, reports:
    point_count before, point_count after, removed = before - after

Patterns tested (per Agisoft forum + API reference):
    A. setConfidenceFilter(0, N) -> removeSelectedPoints()
    B. setConfidenceFilter(0, N) -> cropSelectedPoints() -> reset to (0,255)
    C. setConfidenceFilter(0, N) -> removePoints(list(range(128)))
    D. cleanPointCloud(criterion=Confidence, threshold=N)

Confidence presence is RE-CONFIRMED at the start of every trial via PLY export
header inspection — no test runs against a confidence-less cloud.

If every pattern removes 0 points: EXIT 2 with a loud failure message. We
must not silently report success.

Usage:
    metashape.sh -r scripts/metashape/probes/probe_confidence_delete.py \\
        --project /data/edr_work/smoke/smoke.psx \\
        --workdir /tmp/conf_probe \\
        --threshold 2
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

try:
    import Metashape
except ImportError:
    sys.exit("Run via metashape.sh -r; Metashape module not importable.")


def banner(s: str) -> None:
    print(f"\n=== {s} ===", flush=True)


def fresh_copy(src_psx: Path, dst_psx: Path) -> None:
    """Copy .psx + sibling .files into a clean dst location."""
    if dst_psx.exists():
        dst_psx.unlink()
    dst_files = dst_psx.with_suffix(".files")
    if dst_files.exists():
        shutil.rmtree(dst_files)
    shutil.copy(src_psx, dst_psx)
    src_files = src_psx.with_suffix(".files")
    if src_files.exists():
        shutil.copytree(src_files, dst_files)


def confirm_confidence_in_ply(chunk, ply_path: Path) -> bool:
    """Export an ASCII PLY and verify the header has a confidence column."""
    ply_path.parent.mkdir(parents=True, exist_ok=True)
    if ply_path.exists():
        ply_path.unlink()
    chunk.exportPointCloud(
        path=str(ply_path),
        source_data=Metashape.PointCloudData,
        save_point_color=True,
        save_point_confidence=True,
        format=Metashape.PointCloudFormat.PointCloudFormatPLY,
        binary=False,
    )
    with open(ply_path, "rb") as fh:
        header = b""
        while True:
            ln = fh.readline()
            if not ln:
                break
            header += ln
            if ln.strip() == b"end_header":
                break
    return b"confidence" in header.lower()


def trial(name: str, src_psx: Path, workdir: Path, threshold: int,
          run) -> dict:
    """One destructive trial on a fresh copy. Returns result row."""
    banner(f"TRIAL {name}")
    dst_psx = workdir / f"trial_{name.lower().replace(' ', '_')}.psx"
    fresh_copy(src_psx, dst_psx)
    doc = Metashape.Document()
    doc.open(str(dst_psx), read_only=False)
    chunk = doc.chunk
    pc = chunk.point_cloud
    n_before = pc.point_count
    ply_pre = workdir / f"trial_{name.lower().replace(' ', '_')}_pre.ply"
    has_conf = confirm_confidence_in_ply(chunk, ply_pre)
    print(f"   confidence in PLY header: {has_conf}; "
          f"point_count_before: {n_before}")
    if not has_conf:
        return {"name": name, "before": n_before, "after": n_before,
                "removed": 0, "error": "PLY missing confidence column"}
    try:
        run(chunk, pc, threshold)
    except Exception as exc:
        n_after = pc.point_count
        return {"name": name, "before": n_before, "after": n_after,
                "removed": n_before - n_after,
                "error": f"{type(exc).__name__}: {exc}"}
    # Force any deletion to be materialized
    try:
        pc.compactPoints()
    except Exception:
        pass
    n_after = pc.point_count
    return {"name": name, "before": n_before, "after": n_after,
            "removed": n_before - n_after, "error": None}


# --- Patterns -------------------------------------------------------------- #

def pat_A(chunk, pc, t):
    """setConfidenceFilter(0, N) -> removeSelectedPoints()"""
    pc.setConfidenceFilter(0, t)
    pc.removeSelectedPoints()
    pc.resetFilters()


def pat_B(chunk, pc, t):
    """setConfidenceFilter(0, N) -> cropSelectedPoints() (KEEPS sel, removes rest)
       So this REMOVES HIGH-conf — for our 'remove low-conf' goal we'd want
       to invert the range. We test the literal DocPopi pattern as written."""
    pc.setConfidenceFilter(0, t)
    pc.cropSelectedPoints()
    pc.setConfidenceFilter(0, 255)  # reset


def pat_B2(chunk, pc, t):
    """Inverted-range crop: setConfidenceFilter(N, 255) + cropSelectedPoints
       keeps high-conf, removes low-conf — the semantically correct version
       of B for removing noise."""
    pc.setConfidenceFilter(t, 255)
    pc.cropSelectedPoints()
    pc.setConfidenceFilter(0, 255)  # reset


def pat_C(chunk, pc, t):
    """setConfidenceFilter(0, N) -> removePoints(list(range(128)))"""
    pc.setConfidenceFilter(0, t)
    pc.removePoints(list(range(128)))
    pc.resetFilters()


def pat_D(chunk, pc, t):
    """cleanPointCloud(criterion=Confidence, threshold=N) — Chunk method."""
    chunk.cleanPointCloud(
        criterion=Metashape.PointCloud.Criterion.Confidence,
        threshold=t,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True, type=Path)
    ap.add_argument("--workdir", required=True, type=Path)
    ap.add_argument("--threshold", type=int, default=2,
                    help="Confidence threshold N for low-conf removal.")
    args = ap.parse_args()

    print(f"Metashape version: {Metashape.app.version} "
          f"build {Metashape.version}")
    print(f"Source project: {args.project}")
    print(f"Workdir (copies live here): {args.workdir}")
    print(f"Threshold N: {args.threshold}")
    args.workdir.mkdir(parents=True, exist_ok=True)

    rows = []
    rows.append(trial("A_setFilter_removeSelected",
                      args.project, args.workdir, args.threshold, pat_A))
    rows.append(trial("B_setFilter_cropSelected_literal",
                      args.project, args.workdir, args.threshold, pat_B))
    rows.append(trial("B2_setFilter_cropSelected_inverted_range",
                      args.project, args.workdir, args.threshold, pat_B2))
    rows.append(trial("C_setFilter_removePoints_classRange",
                      args.project, args.workdir, args.threshold, pat_C))
    rows.append(trial("D_cleanPointCloud_Confidence",
                      args.project, args.workdir, args.threshold, pat_D))

    banner("COMPARISON TABLE")
    print(f"{'Pattern':<46} {'Before':>12} {'After':>12} "
          f"{'Removed':>12}  Error")
    print("-" * 100)
    for r in rows:
        print(f"{r['name']:<46} {r['before']:>12,} {r['after']:>12,} "
              f"{r['removed']:>12,}  {r['error'] or ''}")

    any_removed = any(r["removed"] > 0 for r in rows)
    if not any_removed:
        print("\n!!! LOUD FAILURE: every candidate pattern removed 0 points "
              "even though confidence data is present in the PLY header. "
              "This is the worst-case outcome — confidence filtering is "
              "genuinely non-functional on this build for this cloud. Do "
              "NOT report headless confidence cleanup as working.")
        sys.exit(2)
    print("\nAt least one pattern removed points. Pick the highest-removed "
          "with the intended semantics (remove low-confidence).")
    sys.exit(0)


if __name__ == "__main__":
    main()
