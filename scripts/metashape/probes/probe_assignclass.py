"""
Probe v3 — assignClass + classifyPoints signature discovery.

Goal: find an idiom that drops point_count by removing low-confidence dense
points without going through a manual selection step.

Strategy: introspect signatures, then try-call assignClass(LowPoint, ...) with
candidate confidence kwargs. Confirm via point_count_by_class and a follow-up
removePoints([LowPoint]) that the count actually changes.
"""
import inspect
import sys
import Metashape

doc = Metashape.Document()
doc.open("/data/edr_work/smoke/smoke.psx", read_only=False)
chunk = doc.chunk
pc = chunk.point_cloud
TOTAL = pc.point_count
print(f"[probe] starting point_count: {TOTAL}")
print(f"[probe] point_count_by_class (initial): "
      f"{getattr(pc, 'point_count_by_class', 'NO_ATTR')}")

# 1. Signatures
for name in ("assignClass", "assignClassToSelection", "classifyPoints",
             "classifyGroundPoints", "classifyOverlapPoints", "removePoints"):
    fn = getattr(pc, name, None)
    if fn is None:
        print(f"[probe] {name}: NOT PRESENT")
        continue
    try:
        sig = inspect.signature(fn)
        print(f"[probe] {name}{sig}")
    except (TypeError, ValueError):
        # C-bound — fall back to docstring
        doc_lines = (fn.__doc__ or "<no doc>").strip().splitlines()
        print(f"[probe] {name}: <C-bound, no introspectable sig>")
        for ln in doc_lines[:8]:
            print(f"   doc: {ln}")

print()

# 2. Try-call assignClass with candidate confidence kwargs
print("[probe] assignClass kwarg trials:")
candidates = [
    {},                                          # bare — assigns ALL points
    {"confidence_max": 2},
    {"confidence_threshold": 2},
    {"max_confidence": 2},
    {"confidence": 2},
    {"min_confidence": 0, "max_confidence": 2},
    {"source_classes": [Metashape.PointClass.Created]},  # known-good shape
]
for kwargs in candidates:
    # Make sure no existing LowPoint exists from prior trials
    try:
        pc.removePoints([Metashape.PointClass.LowPoint])
    except Exception:
        pass
    n_before = pc.point_count
    try:
        pc.assignClass(Metashape.PointClass.LowPoint, **kwargs)
        # Did anything become LowPoint?
        by_class = getattr(pc, "point_count_by_class", {}) or {}
        n_low = by_class.get(Metashape.PointClass.LowPoint, "?")
        # Confirm via removePoints
        n_pre_remove = pc.point_count
        pc.removePoints([Metashape.PointClass.LowPoint])
        n_post_remove = pc.point_count
        removed = n_pre_remove - n_post_remove
        print(f"   assignClass(LowPoint, **{kwargs}): OK; "
              f"LowPoint_count={n_low}; removePoints dropped {removed} pts "
              f"({n_pre_remove} -> {n_post_remove}).")
    except Exception as exc:
        print(f"   assignClass(LowPoint, **{kwargs}): "
              f"{type(exc).__name__}: {exc}")

print()

# 3. classifyPoints kwarg trials — same shape as above but on classifyPoints
print("[probe] classifyPoints kwarg trials:")
for kwargs in candidates:
    try:
        pc.removePoints([Metashape.PointClass.LowPoint])
    except Exception:
        pass
    try:
        pc.classifyPoints(Metashape.PointClass.LowPoint, **kwargs)
        by_class = getattr(pc, "point_count_by_class", {}) or {}
        n_low = by_class.get(Metashape.PointClass.LowPoint, "?")
        n_pre = pc.point_count
        pc.removePoints([Metashape.PointClass.LowPoint])
        n_post = pc.point_count
        removed = n_pre - n_post
        print(f"   classifyPoints(LowPoint, **{kwargs}): OK; "
              f"LowPoint_count={n_low}; removePoints dropped {removed} "
              f"({n_pre} -> {n_post}).")
    except Exception as exc:
        print(f"   classifyPoints(LowPoint, **{kwargs}): "
              f"{type(exc).__name__}: {exc}")

print(f"\n[probe] FINAL point_count: {pc.point_count} (started at {TOTAL})")
sys.exit(0)
