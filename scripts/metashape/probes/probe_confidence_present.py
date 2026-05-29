#!/usr/bin/env python3
"""
probe_confidence_present.py — non-destructive diagnostic.

Goal: determine, on a given Metashape .psx project containing a dense point
cloud, whether per-point CONFIDENCE DATA was actually stored. This is the
decisive fork for the headless ESM Step 13 confidence-filter investigation:

  * If confidence data IS present → the cleanPointCloud and
    setConfidenceFilter+removeSelectedPoints idioms should both work; any
    failure to remove points is a filter-side bug to investigate.
  * If confidence data is NOT present → no filter API can ever remove points
    by confidence on this cloud, regardless of threshold or idiom; the bug is
    upstream in buildPointCloud (kwarg name, build settings, or version drift).

This probe does NOT delete or modify points. It opens read_only=True, lists
available attributes, and exports a PLY with save_point_confidence=True. The
PLY header is the ground-truth artifact: if there is a `property uchar
confidence` line in the header, confidence is in the cloud. If not, it isn't.

Usage:
    metashape.sh -r scripts/metashape/probes/probe_confidence_present.py \\
        --project /path/to/dense.psx \\
        --ply-out /tmp/confidence_probe.ply

Outputs:
    * Metashape version + build to stdout
    * dir(chunk) tokens matching {point_cloud, dense_cloud, point_clouds}
    * hasattr checks for each candidate cloud object
    * dir(pc) tokens matching {confidence, point_confidence, has_, attribute}
    * exportPoints(save_point_confidence=True) result + PLY header
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import Metashape
except ImportError:
    sys.exit("Run via metashape.sh -r; Metashape module not importable.")


def banner(s: str) -> None:
    print(f"\n=== {s} ===", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True, type=Path)
    ap.add_argument("--ply-out", required=True, type=Path)
    args = ap.parse_args()

    banner("Metashape build")
    print(f"version: {Metashape.app.version}")
    print(f"build  : {Metashape.version}")

    banner("Open project (read-only)")
    doc = Metashape.Document()
    doc.open(str(args.project), read_only=True)
    print(f"opened: {args.project}")
    print(f"chunks: {[c.label for c in doc.chunks]}")
    chunk = doc.chunk
    print(f"active chunk: {chunk.label!r}")

    banner("Candidate cloud attributes on Chunk")
    # The dense cloud was renamed dense_cloud -> point_cloud in 2.0; forum
    # posts and docs mix both. Check every plausible name.
    for name in ("point_cloud", "dense_cloud", "point_clouds", "dense_clouds"):
        has = hasattr(chunk, name)
        val = getattr(chunk, name, None) if has else None
        print(f"   hasattr(chunk, {name!r}) = {has}; value type: {type(val).__name__}")

    banner("dir(chunk) tokens matching cloud/point/dense/asset/depth")
    interest = [m for m in dir(chunk) if not m.startswith("_") and any(
        s in m.lower() for s in ("cloud", "point", "dense", "asset", "depth")
    )]
    for m in sorted(interest):
        print(f"   chunk.{m}")

    pc = chunk.point_cloud
    if pc is None:
        sys.exit("chunk.point_cloud is None — no dense cloud present.")

    banner("Dense cloud basic state")
    print(f"point_count        : {pc.point_count}")
    print(f"point_count_by_class: {pc.point_count_by_class}")

    banner("dir(pc) tokens matching has_/confidence/color/normal/attr")
    pc_attrs = [m for m in dir(pc) if not m.startswith("_") and any(
        s in m.lower() for s in ("has_", "confidence", "color", "normal", "attr")
    )]
    for m in sorted(pc_attrs):
        try:
            val = getattr(pc, m)
            # Only print scalars to avoid huge dumps
            if isinstance(val, (bool, int, float, str)) or val is None:
                print(f"   pc.{m} = {val!r}")
            else:
                print(f"   pc.{m}  (type {type(val).__name__})")
        except Exception as exc:
            print(f"   pc.{m}  -> {type(exc).__name__}: {exc}")

    banner("Full dir(pc) (non-underscore methods/attrs)")
    for m in sorted(m for m in dir(pc) if not m.startswith("_")):
        print(f"   pc.{m}")

    banner("pc.meta (point-cloud metadata that may report confidence presence)")
    try:
        meta = dict(pc.meta) if pc.meta else {}
        for k, v in sorted(meta.items()):
            print(f"   pc.meta[{k!r}] = {v!r}")
        if not meta:
            print("   pc.meta is empty")
    except Exception as exc:
        print(f"   pc.meta read FAILED: {type(exc).__name__}: {exc}")

    banner("Export PLY with save_point_confidence=True via chunk.exportPointCloud")
    args.ply_out.parent.mkdir(parents=True, exist_ok=True)
    try:
        chunk.exportPointCloud(
            path=str(args.ply_out),
            source_data=Metashape.PointCloudData,
            save_point_color=True,
            save_point_confidence=True,
            save_point_classification=True,
            format=Metashape.PointCloudFormat.PointCloudFormatPLY,
            binary=False,  # ASCII PLY so the header is human-readable
        )
        print(f"exported: {args.ply_out} "
              f"({args.ply_out.stat().st_size} bytes)")
    except Exception as exc:
        sys.exit(f"exportPointCloud FAILED: {type(exc).__name__}: {exc}")

    banner("PLY header (ASCII, first 40 lines)")
    with open(args.ply_out, "rb") as fh:
        lines = []
        for _ in range(40):
            ln = fh.readline()
            if not ln:
                break
            lines.append(ln)
            if ln.strip() == b"end_header":
                break
    for ln in lines:
        try:
            print(f"   {ln.decode('utf-8', errors='replace').rstrip()}")
        except Exception:
            print(f"   <non-utf8 line: {ln!r}>")

    banner("DIAGNOSTIC VERDICT")
    header_text = b"".join(lines).decode("utf-8", errors="replace").lower()
    has_conf_in_ply = "confidence" in header_text
    print(f"confidence column in PLY header? {has_conf_in_ply}")
    if has_conf_in_ply:
        print("  -> Confidence data IS stored on this dense cloud.")
        print("  -> setConfidenceFilter / cleanPointCloud should be able to act on it.")
        print("  -> If filter API removes 0 points, the bug is filter-side.")
    else:
        print("  -> Confidence data is NOT in the dense cloud's PLY export.")
        print("  -> The bug is UPSTREAM in buildPointCloud — point_confidence flag")
        print("     either didn't take effect, has a different kwarg name on this")
        print("     build, or the cloud was saved without confidence retained.")

    sys.exit(0)


if __name__ == "__main__":
    main()
