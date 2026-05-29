"""Probe v8 dense at setConfidenceFilter(0, 2) + cropSelectedPoints with bbox.

Operates on a COPY of /data/edr_work/smoke/smoke.psx (v8 state).
"""
import shutil
import sys
from pathlib import Path
import Metashape

SRC = Path("/data/edr_work/smoke/smoke.psx")
DST = Path("/tmp/conf_probe_v8/smoke_copy.psx")


def fresh_copy():
    DST.parent.mkdir(parents=True, exist_ok=True)
    if DST.exists():
        DST.unlink()
    dst_files = DST.with_suffix(".files")
    if dst_files.exists():
        shutil.rmtree(dst_files)
    shutil.copy(SRC, DST)
    src_files = SRC.with_suffix(".files")
    if src_files.exists():
        shutil.copytree(src_files, dst_files)


def bbox_info(pc, label):
    print(f"\n--- {label} ---")
    print(f"point_count: {pc.point_count}")
    try:
        ext = pc.extent()  # METHOD call, not attribute
        print(f"pc.extent() returned type: {type(ext).__name__}")
        try:
            print(f"  min: x={ext.min.x:.3f} y={ext.min.y:.3f} z={ext.min.z:.3f}")
            print(f"  max: x={ext.max.x:.3f} y={ext.max.y:.3f} z={ext.max.z:.3f}")
            print(f"  size: x={ext.max.x - ext.min.x:.3f} "
                  f"y={ext.max.y - ext.min.y:.3f} "
                  f"z={ext.max.z - ext.min.z:.3f}")
        except AttributeError as exc:
            print(f"  attribute access failed: {exc}")
            print(f"  raw repr: {ext!r}")
            # Try dict-style access in case it's a different shape
            for attr in ("min", "max", "size", "x", "y", "z"):
                if hasattr(ext, attr):
                    print(f"  ext.{attr} = {getattr(ext, attr)!r}")
    except Exception as exc:
        print(f"pc.extent() FAILED: {type(exc).__name__}: {exc}")


fresh_copy()
doc = Metashape.Document()
doc.open(str(DST), read_only=False)
chunk = doc.chunk
pc = chunk.point_cloud

bbox_info(pc, "PRE-FILTER (v8 fresh dense)")

n_before = pc.point_count
pc.setConfidenceFilter(0, 2)
pc.cropSelectedPoints()
pc.setConfidenceFilter(0, 255)
n_after = pc.point_count
removed = n_before - n_after
print(f"\n=== FILTER RESULT ===")
print(f"setConfidenceFilter(0, 2) + cropSelectedPoints + reset")
print(f"n_before: {n_before:,}")
print(f"n_after : {n_after:,}")
print(f"removed : {removed:,} ({100*removed/max(n_before,1):.2f}%)")

bbox_info(pc, "POST-FILTER")

# Also try chunk.region for comparison (sparse-derived)
print(f"\n--- chunk.region (sparse-tie-point derived, for comparison) ---")
print(f"center: x={chunk.region.center.x:.3f} y={chunk.region.center.y:.3f} "
      f"z={chunk.region.center.z:.3f}")
print(f"size:   x={chunk.region.size.x:.3f} y={chunk.region.size.y:.3f} "
      f"z={chunk.region.size.z:.3f}")

sys.exit(0)
