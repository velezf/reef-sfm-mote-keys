"""Probe v4 — targeted test of classifyPoints(source, target, confidence)."""
import sys
import Metashape

doc = Metashape.Document()
# read-only so each run starts from the same v6 state, no persistence side-effects
doc.open("/data/edr_work/smoke/smoke.psx", read_only=True)
chunk = doc.chunk
pc = chunk.point_cloud

print(f"[probe] starting point_count: {pc.point_count}")
print(f"[probe] starting point_count_by_class: "
      f"{getattr(pc, 'point_count_by_class', 'NO_ATTR')}")

# PointClass enum values for reference
print(f"\n[probe] PointClass enum values:")
for name in ("Created", "Unclassified", "Ground", "LowPoint",
             "LowVegetation", "MediumVegetation", "HighVegetation"):
    val = getattr(Metashape.PointClass, name, None)
    print(f"   PointClass.{name} = {val} (int={int(val) if val is not None else 'N/A'})")

# THE CALL: per docstring, classifyPoints(source, target, confidence=0.0)
print(f"\n[probe] Calling: classifyPoints(source=Created, "
      f"target=[LowPoint], confidence=2.0)")
try:
    pc.classifyPoints(source=Metashape.PointClass.Created,
                      target=[Metashape.PointClass.LowPoint],
                      confidence=2.0)
    print("[probe] classifyPoints call: returned without exception.")
except Exception as exc:
    print(f"[probe] classifyPoints FAILED: {type(exc).__name__}: {exc}")
    sys.exit(1)

print(f"\n[probe] point_count after classifyPoints: {pc.point_count} "
      f"(should be unchanged — classify only reclassifies)")
print(f"[probe] point_count_by_class after: "
      f"{getattr(pc, 'point_count_by_class', 'NO_ATTR')}")

# Now removePoints([LowPoint]) and confirm count drops
print(f"\n[probe] Calling: removePoints([LowPoint])")
n_before = pc.point_count
try:
    pc.removePoints([Metashape.PointClass.LowPoint])
    n_after = pc.point_count
    removed = n_before - n_after
    print(f"[probe] removePoints: {n_before} -> {n_after} "
          f"(removed {removed} pts).")
except Exception as exc:
    print(f"[probe] removePoints FAILED: {type(exc).__name__}: {exc}")
    sys.exit(1)

print(f"\n[probe] point_count_by_class after remove: "
      f"{getattr(pc, 'point_count_by_class', 'NO_ATTR')}")
print(f"[probe] FINAL point_count: {pc.point_count}")

# Sanity: is the dense bbox now reasonable?
# (chunk.region is sparse-cloud-derived and doesn't change with dense ops,
# but we can sample a few points to see if outliers are gone)
print(f"\n[probe] chunk.region.size (sparse-derived, unchanged): "
      f"x={chunk.region.size.x:.3f} y={chunk.region.size.y:.3f}")
sys.exit(0)
