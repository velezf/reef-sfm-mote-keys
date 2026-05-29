"""Confidence distribution probe by destructive sweep (in-memory only).

Open read_only=True so cleanPointCloud's removals don't persist. Run with
progressively higher thresholds; each higher threshold removes a superset of
the previous. Diffs give the per-bucket count.
"""
import sys
import Metashape

doc = Metashape.Document()
doc.open("/data/edr_work/smoke/smoke.psx", read_only=True)
chunk = doc.chunk
pc = chunk.point_cloud
total = pc.point_count
print(f"[probe] dense point_count: {total}")
print(f"[probe] point_count_by_class: {pc.point_count_by_class}")

# Sweep thresholds. Each cleanPointCloud removes points with conf < threshold
# (cumulative). Track point_count after each so we can reverse-map the
# distribution.
thresholds = [1, 2, 3, 5, 10, 20, 50, 100, 200, 256]
prev = total
rows = [(0, total, 0)]
print(f"\n[probe] Sweeping cleanPointCloud(Confidence, threshold=N):")
for t in thresholds:
    chunk.cleanPointCloud(
        criterion=Metashape.PointCloud.Criterion.Confidence,
        threshold=t,
    )
    n = pc.point_count
    removed_this_step = prev - n
    cumulative_removed = total - n
    print(f"   threshold={t:4d}: {prev:>10,} -> {n:>10,} "
          f"(this step: -{removed_this_step:>10,}; "
          f"cumulative: -{cumulative_removed:>10,} = "
          f"{100*cumulative_removed/total:.2f}%)")
    rows.append((t, n, cumulative_removed))
    prev = n

# Reverse-map: at each threshold T, count removed in bucket [prev_T, T)
print(f"\n[probe] Bucketed distribution (count with confidence in [lo, hi)):")
prev_t = 0
prev_n = total
for t, n, _ in rows[1:]:
    in_bucket = prev_n - n
    print(f"   conf in [{prev_t:3d},{t:4d}): {in_bucket:>10,} pts "
          f"({100*in_bucket/total:.2f}%)")
    prev_t = t
    prev_n = n

print(f"\n[probe] Survival summary:")
for t, n, removed in rows:
    print(f"   after cleanPointCloud(< {t:3d}): {n:>10,} survive "
          f"({100*n/total:.2f}%)")

print(f"\n[probe] read_only=True — destructive ops are in-memory only; "
      f"on-disk dense cloud is unchanged.")
sys.exit(0)
