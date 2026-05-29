"""
Probe the Metashape 2.x dense-cloud confidence-filter idiom.

Reuses the v6 smoke project (dense already built, filter never ran) to test the
filter -> select -> assign -> remove sequence and confirm point_count actually
drops. Prints what works so we know which API call(s) to bake into
smoke_test.py and segment_pointcloud.py.
"""
import sys
import Metashape

PROJECT = "/data/edr_work/smoke/smoke.psx"

doc = Metashape.Document()
doc.open(PROJECT, read_only=True)
chunk = doc.chunk
pc = chunk.point_cloud
print(f"[probe] dense point_count before any action: {pc.point_count}")
print(f"[probe] chunk.region.size: x={chunk.region.size.x:.3f} "
      f"y={chunk.region.size.y:.3f} z={chunk.region.size.z:.3f}")

# Step 1: set visibility filter
pc.setConfidenceFilter(0, 1)
print(f"[probe] after setConfidenceFilter(0,1): point_count={pc.point_count} "
      "(should be unchanged; filter only hides for display)")

# Step 2: try the filter -> selection conversion
try:
    pc.selectMaskedPoints()
    print("[probe] selectMaskedPoints() did not raise.")
except Exception as exc:
    print(f"[probe] selectMaskedPoints() FAILED: {type(exc).__name__}: {exc}")
    # Try alternates
    for name in ("selectVisiblePoints", "selectPointsByMask",
                 "selectAllPoints", "selectByCriterion"):
        if hasattr(pc, name):
            print(f"[probe]   alt available: pc.{name}")

# Step 3: assignClassToSelection — the v6 failure point
try:
    pc.assignClassToSelection(Metashape.PointClass.LowPoint)
    print("[probe] assignClassToSelection(LowPoint) succeeded.")
except Exception as exc:
    print(f"[probe] assignClassToSelection FAILED: "
          f"{type(exc).__name__}: {exc}")

pc.resetFilters()

# Step 4: remove the LowPoint class — does it actually drop point_count?
n_before_remove = pc.point_count
try:
    pc.removePoints([Metashape.PointClass.LowPoint])
    n_after_remove = pc.point_count
    print(f"[probe] removePoints([LowPoint]): "
          f"{n_before_remove} -> {n_after_remove} "
          f"(removed {n_before_remove - n_after_remove}).")
except Exception as exc:
    print(f"[probe] removePoints FAILED: {type(exc).__name__}: {exc}")

# Final state
print(f"[probe] FINAL point_count: {pc.point_count}")
print(f"[probe] FINAL chunk.region.size: x={chunk.region.size.x:.3f} "
      f"y={chunk.region.size.y:.3f}")
print("[probe] (region won't update from removed pts unless resetRegion called)")

# Bonus: list every method on PointCloud with 'select', 'remove', 'mask',
# 'confidence', 'crop', 'class' in its name for reference
candidates = sorted([m for m in dir(pc) if not m.startswith("_") and any(
    s in m.lower() for s in ("select", "remove", "mask", "conf", "crop", "class")
)])
print(f"[probe] PointCloud methods (filter/select/remove/class family):")
for m in candidates:
    print(f"   pc.{m}")
sys.exit(0)
