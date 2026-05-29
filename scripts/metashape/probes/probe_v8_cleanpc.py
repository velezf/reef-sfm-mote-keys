import shutil
from pathlib import Path
import Metashape

SRC = Path("/data/edr_work/smoke/smoke.psx")


def fresh(name):
    DST = Path(f"/tmp/conf_final/{name}.psx")
    DST.parent.mkdir(parents=True, exist_ok=True)
    if DST.exists(): DST.unlink()
    df = DST.with_suffix(".files")
    if df.exists(): shutil.rmtree(df)
    shutil.copy(SRC, DST)
    sf = SRC.with_suffix(".files")
    if sf.exists(): shutil.copytree(sf, df)
    doc = Metashape.Document()
    doc.open(str(DST), read_only=False)
    return doc, doc.chunk.point_cloud


print("=== Test 1: ONLY cleanPointCloud(Confidence, 2) + compactPoints ===")
doc, pc = fresh("test1")
print(f"  fresh: {pc.point_count:,}")
doc.chunk.cleanPointCloud(criterion=Metashape.PointCloud.Criterion.Confidence, threshold=2)
print(f"  after cleanPointCloud(2): {pc.point_count:,} (count is stale)")
pc.compactPoints()
print(f"  after compactPoints: {pc.point_count:,}")
ext = pc.extent()
print(f"  extent: {ext.max.x-ext.min.x:.1f} x {ext.max.y-ext.min.y:.1f} x {ext.max.z-ext.min.z:.1f}")
del doc

print("\n=== Test 2: ONLY DocPopi setConfidenceFilter(0,2)+crop+compact ===")
doc, pc = fresh("test2")
print(f"  fresh: {pc.point_count:,}")
pc.setConfidenceFilter(0, 2)
pc.cropSelectedPoints()
pc.setConfidenceFilter(0, 255)
print(f"  after setFilter+crop (before compact): {pc.point_count:,}")
pc.compactPoints()
print(f"  after compactPoints: {pc.point_count:,}")
del doc

print("\n=== Test 3: cleanPointCloud(2)+compact, then DocPopi crop+compact ===")
doc, pc = fresh("test3")
print(f"  fresh: {pc.point_count:,}")
doc.chunk.cleanPointCloud(criterion=Metashape.PointCloud.Criterion.Confidence, threshold=2)
pc.compactPoints()
print(f"  after cleanPointCloud+compact: {pc.point_count:,}")
pc.setConfidenceFilter(0, 2)
pc.cropSelectedPoints()
pc.setConfidenceFilter(0, 255)
pc.compactPoints()
print(f"  after subsequent setFilter+crop+compact: {pc.point_count:,}")
