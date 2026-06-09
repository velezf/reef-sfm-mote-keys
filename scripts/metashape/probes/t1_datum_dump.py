#!/usr/bin/env python3
"""t1_datum_dump.py — READ-ONLY datum/CRS state dump for the post-scale edr_t1.psx.

NO optimize, NO save, NO write. Opens read_only=True.

Dumps verbatim: chunk.crs (full WKT + authority/EPSG), chunk.transform scale,
chunk.region size/center, how many cameras/markers carry reference locations
(+ example values), scale-bar reference data, chunk.reference.enabled.

Usage: metashape.sh -platform offscreen -r t1_datum_dump.py <project.psx>
"""
import math
import sys

import Metashape


def _mat_scale(m):
    """Extract scale from a 4x4 Transform matrix (norm of the first column vector)."""
    try:
        return math.sqrt(m[0, 0] ** 2 + m[1, 0] ** 2 + m[2, 0] ** 2)
    except Exception:
        return None


def main():
    project = sys.argv[-1]
    doc = Metashape.Document()
    doc.open(project, read_only=True)
    assert doc.read_only, "Expected read_only open — aborting before touching anything"

    chunk = doc.chunks[0]
    print(f"project       : {project}")
    print(f"chunk.label   : {chunk.label}")
    print(f"read_only     : {doc.read_only}")
    print(f"cameras total : {len(chunk.cameras)}")
    print(f"markers total : {len(chunk.markers)}")
    print()

    # ── CRS ──────────────────────────────────────────────────────────────────
    crs = chunk.crs
    print("=== chunk.crs ===")
    print(f"  repr      : {crs}")
    print(f"  name      : {crs.name!r}")
    print(f"  authority : {crs.authority!r}")
    try:
        wkt = crs.wkt
        print(f"  wkt       : {wkt!r}")
    except Exception as e:
        print(f"  wkt       : ERROR {e}")
    print()

    # ── TRANSFORM ─────────────────────────────────────────────────────────────
    t = chunk.transform
    print("=== chunk.transform ===")
    try:
        m = t.matrix
        sc = _mat_scale(m)
        print(f"  matrix scale (col-0 norm) : {sc}")
        print(f"  matrix[0]  : {m[0,0]:.6g}  {m[0,1]:.6g}  {m[0,2]:.6g}  {m[0,3]:.6g}")
        print(f"  matrix[1]  : {m[1,0]:.6g}  {m[1,1]:.6g}  {m[1,2]:.6g}  {m[1,3]:.6g}")
        print(f"  matrix[2]  : {m[2,0]:.6g}  {m[2,1]:.6g}  {m[2,2]:.6g}  {m[2,3]:.6g}")
        print(f"  matrix[3]  : {m[3,0]:.6g}  {m[3,1]:.6g}  {m[3,2]:.6g}  {m[3,3]:.6g}")
    except Exception as e:
        print(f"  matrix: ERROR {e}")
    try:
        print(f"  .scale    : {t.scale}")
    except AttributeError:
        print("  .scale    : (no .scale attribute)")
    print()

    # ── REGION ────────────────────────────────────────────────────────────────
    print("=== chunk.region ===")
    try:
        r = chunk.region
        print(f"  center    : {r.center}")
        print(f"  size      : {r.size}")
        print(f"  rot       : {r.rot}")
    except Exception as e:
        print(f"  ERROR: {e}")
    print()

    # ── REFERENCE SETTINGS ───────────────────────────────────────────────────
    print("=== chunk.reference ===")
    try:
        ref = chunk.reference
        print(f"  enabled   : {ref.enabled}")
        try:
            print(f"  accuracy (location) : {ref.accuracy}")
        except Exception:
            pass
        try:
            print(f"  rotation_accuracy   : {ref.rotation_accuracy}")
        except Exception:
            pass
    except Exception as e:
        print(f"  ERROR: {e}")
    print()

    # ── CAMERAS WITH REFERENCE LOCATIONS ────────────────────────────────────
    cams_with_ref = [c for c in chunk.cameras
                     if c.reference is not None and c.reference.location is not None]
    print(f"=== camera.reference.location ===")
    print(f"  cameras with non-None location : {len(cams_with_ref)} / {len(chunk.cameras)}")
    for c in cams_with_ref[:5]:
        loc = c.reference.location
        acc = getattr(c.reference, 'accuracy', None)
        en = getattr(c.reference, 'enabled', None)
        print(f"  {c.label!r:40s}  loc={loc}  acc={acc}  enabled={en}")
    if len(cams_with_ref) > 5:
        print(f"  ... ({len(cams_with_ref) - 5} more)")
    print()

    # ── MARKERS WITH REFERENCE LOCATIONS ────────────────────────────────────
    markers_with_ref = [m for m in chunk.markers
                        if m.reference is not None and m.reference.location is not None]
    print(f"=== marker.reference.location ===")
    print(f"  markers with non-None location : {len(markers_with_ref)} / {len(chunk.markers)}")
    for m in markers_with_ref[:10]:
        loc = m.reference.location
        acc = getattr(m.reference, 'accuracy', None)
        en = getattr(m.reference, 'enabled', None)
        print(f"  {m.label!r:30s}  loc={loc}  acc={acc}  enabled={en}")
    print()

    # ── SCALE BARS ───────────────────────────────────────────────────────────
    print(f"=== scale bars ({len(chunk.scalebars)}) ===")
    for sb in chunk.scalebars:
        ref = sb.reference
        dist = getattr(ref, 'distance', None)
        acc = getattr(ref, 'accuracy', None)
        en = getattr(ref, 'enabled', None)
        print(f"  {sb.label!r:30s}  dist={dist}  acc={acc}  enabled={en}")
    print()

    print("=== END DATUM DUMP ===")
    print("NO optimize was called. Project untouched.")


if __name__ == "__main__":
    main()
