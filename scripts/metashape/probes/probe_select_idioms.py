"""Probe v7 — selection idioms that might respect setConfidenceFilter."""
import sys
import Metashape

doc = Metashape.Document()
doc.open("/data/edr_work/smoke/smoke.psx", read_only=True)
chunk = doc.chunk
pc = chunk.point_cloud
START = pc.point_count
print(f"[probe] starting point_count: {START}, "
      f"by_class={pc.point_count_by_class}")
print(f"[probe] chunk.region: center=({chunk.region.center.x:.1f},"
      f"{chunk.region.center.y:.1f},{chunk.region.center.z:.1f}) "
      f"size=({chunk.region.size.x:.1f},{chunk.region.size.y:.1f},"
      f"{chunk.region.size.z:.1f})")

# Construct a huge region that should cover the entire dense cloud incl. outliers
big = Metashape.Region()
big.center = chunk.region.center
big.rot = chunk.region.rot
big.size = Metashape.Vector([1e10, 1e10, 1e10])


def trial(label, setup):
    """Run setup (which leaves a selection), then check assignClassToSelection."""
    print(f"\n[trial] {label}")
    try:
        setup()
    except Exception as exc:
        print(f"   setup FAILED: {type(exc).__name__}: {exc}")
        return
    try:
        pc.assignClassToSelection(target=Metashape.PointClass.LowPoint,
                                  source=Metashape.PointClass.Created)
        print(f"   assignClassToSelection OK; "
              f"by_class={pc.point_count_by_class}")
        n_pre = pc.point_count
        pc.removePoints([Metashape.PointClass.LowPoint])
        n_post = pc.point_count
        print(f"   removePoints: {n_pre} -> {n_post} "
              f"(removed {n_pre - n_post})")
    except Exception as exc:
        print(f"   assignClassToSelection FAILED: "
              f"{type(exc).__name__}: {exc}")
    # Reset everything for next trial
    pc.resetFilters()


trial("setConfidenceFilter(0,1) + invertSelection",
      lambda: (pc.setConfidenceFilter(0, 1), pc.invertSelection()))

trial("setConfidenceFilter(0,1) + selectPointsByRegion(big_region)",
      lambda: (pc.setConfidenceFilter(0, 1), pc.selectPointsByRegion(big)))

trial("invertSelection alone (no filter) — expect select all",
      lambda: pc.invertSelection())

trial("selectPointsByRegion(big) alone (no filter) — expect select all",
      lambda: pc.selectPointsByRegion(big))

trial("setConfidenceFilter(0,2) + selectPointsByRegion(big)",
      lambda: (pc.setConfidenceFilter(0, 2), pc.selectPointsByRegion(big)))

sys.exit(0)
