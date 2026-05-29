"""Probe v6 — assignClass positional vs kwargs, and varied source/target."""
import sys
import Metashape

doc = Metashape.Document()
doc.open("/data/edr_work/smoke/smoke.psx", read_only=True)
chunk = doc.chunk
pc = chunk.point_cloud
START = pc.point_count
print(f"[probe] starting point_count: {START}, "
      f"by_class={pc.point_count_by_class}")

# Define candidate calls. read_only=True means changes aren't persisted, but
# in-memory class re-assignment within ONE session is visible. After each
# variant, log point_count_by_class — that's the ground truth.
def show(label):
    print(f"   AFTER {label}: by_class={pc.point_count_by_class}, "
          f"point_count={pc.point_count}")

variants = [
    ("positional assignClass(LowPoint, Created)",
     lambda: pc.assignClass(Metashape.PointClass.LowPoint,
                            Metashape.PointClass.Created)),
    ("positional assignClass(Unclassified, Created)",
     lambda: pc.assignClass(Metashape.PointClass.Unclassified,
                            Metashape.PointClass.Created)),
    ("kwargs assignClass(target=Unclassified, source=Created)",
     lambda: pc.assignClass(target=Metashape.PointClass.Unclassified,
                            source=Metashape.PointClass.Created)),
    ("positional assignClass(LowPoint, [Created])  # source as LIST",
     lambda: pc.assignClass(Metashape.PointClass.LowPoint,
                            [Metashape.PointClass.Created])),
    ("positional assignClass(LowPoint, Unclassified)",
     lambda: pc.assignClass(Metashape.PointClass.LowPoint,
                            Metashape.PointClass.Unclassified)),
]

for label, fn in variants:
    print(f"\n[probe] {label}")
    try:
        fn()
        show(label)
    except Exception as exc:
        print(f"   FAILED: {type(exc).__name__}: {exc}")

print(f"\n[probe] FINAL: by_class={pc.point_count_by_class}, "
      f"point_count={pc.point_count}")
sys.exit(0)
