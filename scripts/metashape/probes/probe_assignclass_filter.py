"""Probe v5 — does setConfidenceFilter scope assignClass?"""
import os
import shutil
import sys
import Metashape

PSX = "/data/edr_work/smoke/smoke.psx"
BAK_PSX = "/data/edr_work/smoke/smoke.psx.bak"
PSX_FILES = "/data/edr_work/smoke/smoke.files"
BAK_FILES = "/data/edr_work/smoke/smoke.files.bak"


def restore():
    if os.path.exists(PSX):
        os.remove(PSX)
    if os.path.exists(PSX_FILES):
        shutil.rmtree(PSX_FILES)
    shutil.copy(BAK_PSX, PSX)
    shutil.copytree(BAK_FILES, PSX_FILES)


def open_rw():
    doc = Metashape.Document()
    doc.open(PSX, read_only=False)
    return doc, doc.chunk, doc.chunk.point_cloud


# TEST A: assignClass(target=LowPoint, source=Created) with NO confidence filter
restore()
doc, chunk, pc = open_rw()
print(f"\n[TEST A] No filter; assignClass(target=LowPoint, source=Created)")
print(f"   before: point_count={pc.point_count}, by_class={pc.point_count_by_class}")
pc.assignClass(target=Metashape.PointClass.LowPoint,
               source=Metashape.PointClass.Created)
print(f"   after assignClass: point_count={pc.point_count}, "
      f"by_class={pc.point_count_by_class}")
n_pre = pc.point_count
pc.removePoints([Metashape.PointClass.LowPoint])
n_post = pc.point_count
print(f"   after removePoints([LowPoint]): "
      f"{n_pre} -> {n_post} (removed {n_pre - n_post})")
print(f"   (If A reclassifies ALL Created to LowPoint, removePoints "
      f"empties the cloud.)")
del doc  # release before restore

# TEST B: setConfidenceFilter(0, 1) + assignClass(target=LowPoint, source=Created)
restore()
doc, chunk, pc = open_rw()
print(f"\n[TEST B] setConfidenceFilter(0, 1) + assignClass(LowPoint, Created)")
print(f"   before: point_count={pc.point_count}, by_class={pc.point_count_by_class}")
pc.setConfidenceFilter(0, 1)
pc.assignClass(target=Metashape.PointClass.LowPoint,
               source=Metashape.PointClass.Created)
pc.resetFilters()
print(f"   after assignClass (with filter): point_count={pc.point_count}, "
      f"by_class={pc.point_count_by_class}")
n_pre = pc.point_count
pc.removePoints([Metashape.PointClass.LowPoint])
n_post = pc.point_count
print(f"   after removePoints([LowPoint]): "
      f"{n_pre} -> {n_post} (removed {n_pre - n_post})")
print(f"   (If B is scoped by filter, only LOW-confidence pts reclassified "
      f"and removed.)")
del doc

# TEST C: setConfidenceFilter(0, 2) — match segment_pointcloud.py default
restore()
doc, chunk, pc = open_rw()
print(f"\n[TEST C] setConfidenceFilter(0, 2) + assignClass(LowPoint, Created)")
print(f"   before: point_count={pc.point_count}, by_class={pc.point_count_by_class}")
pc.setConfidenceFilter(0, 2)
pc.assignClass(target=Metashape.PointClass.LowPoint,
               source=Metashape.PointClass.Created)
pc.resetFilters()
n_pre = pc.point_count
pc.removePoints([Metashape.PointClass.LowPoint])
n_post = pc.point_count
print(f"   after remove: {n_pre} -> {n_post} (removed {n_pre - n_post})")

del doc

# Restore final state for the smoke
restore()
print("\n[probe] Project restored to original v6 state.")
sys.exit(0)
