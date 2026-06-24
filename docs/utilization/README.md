# EC2 utilization logs — reef-sfm g6.4xlarge (NVIDIA L4, 23 GB VRAM)

## THE GAP — read this first

The T1 dense run (2026-06-10, 2.8 h, 651M points, 2,422 images) — the single
most compute-intensive job in this project — was not instrumented. No monitor
was running. Every VRAM ceiling and RAM peak below comes from transect-scale
dense only. They do not bound the full-site job.

That gap is the honest headline. The sizing call for transect-scale work is
conclusive; for full-site dense it is not.

---

## Logged runs

Three sessions captured at 5-second sampling. Six CSVs: `gpu_*` + `cpumem_*` per session.

| Session | Date | Duration | GPU ops | What ran |
|---------|------|----------|---------|----------|
| T3/R2 transect runs | 2026-05-29 | 12 h 53 min | yes | T3 align + dense; R2 exploration |
| T1 align incident | 2026-06-04 | 6 h 41 min | yes | T1 align, reduce, markers |
| T1 level + reduce | 2026-06-09 | 6 h 15 min | **no** | CPU-only: Logan reduce, leveling |

The Jun 9 session is a useful data point in itself: GPU utilization was 0% across
the entire session. Metashape's reduce (Logan) and leveling stages are entirely
CPU-bound at this scale.

---

## Real peaks (from the CSVs)

| Metric | May 29 | Jun 4 | Jun 9 |
|--------|--------|-------|-------|
| GPU util peak | 99% | 99% | 0% |
| GPU util mean | 0.9% | 6.4% | 0.0% |
| VRAM used peak | 1,636 MB / 23,034 MB (**7.1%**) | 1,516 MB (6.6%) | 780 MB (3.4%) |
| CPU util peak | 0% | 100% | 100% |
| CPU util mean | 0.0% | 20.0% | 24.5% |
| RAM used peak | 8,313 MB / 61,909 MB (**13.4%**) | 10,996 MB (17.8%) | 7,195 MB (11.6%) |
| Swap peak | 0 MB | 0 MB | 0 MB |

**VRAM ceiling across all instrumented runs: 1,636 MB (7.1% of 23 GB).**
**RAM ceiling: 10,996 MB (17.8% of 62 GB).** Zero swap on every run.

Disk at decommission: 265 GB used of 984 GB (719 GB idle).

---

## Sizing call

**Transect-scale (R2/T3, ≤300 images, single transect)** — conclusive from data:
- VRAM: 1.6 GB ceiling → L4 is massively over-provisioned. A **g6.2xlarge**
  (same L4 GPU, 8 vCPU, 32 GB RAM, ~half the cost) is sufficient. Even a T4-class
  instance (g4dn) would likely clear it.
- RAM: 11 GB peak → 32 GB is adequate with headroom.
- Disk: ~265 GB used across the whole project → 400 GB is the right next-time
  allocation (not 1 TB).

**Full-site dense (T1, 2,422 images, 651M pts, 2.8 h)** — not bounded by this data:
- The T1 dense was the only job that could have stressed VRAM meaningfully, and it
  ran uninstrumented. The 1.6 GB ceiling says nothing about it.
- If choosing blind: stay on the L4 (g6.4xlarge). It completed in 2.8 h without
  error, so we know the L4 clears it — we just don't know by how much.
- **Instrument the next large-corpus dense before downsizing.** One monitored run
  will resolve this; guessing will not.
