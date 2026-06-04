# Session log — 2026-06-04 (Chat 5.7): T3 shipped, T1 align running, spot-instance design

Completion-log + resume file. First-person where it helps; disconnect-safe handoff.

## STATE (what's done)
- **EDR_T3 = SHIPPED.** The day-1 24.26° mis-level is fixed, codified (`stage_level` + `stage_aoi` +
  permanent 8-check gate, ADR-0021), and the working `/data/edr_work/edr_t3.psx` is the **codified
  product** (gate PASS: long 0.39° / total 1.64° / coverage 97.9% / co-reg 0 / scale 10.000 m / roughness
  0.0918 m in the ref 0.08–0.10 band). Exported to `/data/edr_work/products/EDR_T3/`. Commit chain
  `5f23ff5 → 7e2a9af → e104060 → 984acc8 → 789b3a9 → e989337 → 325dbc7 → 3f932fe` (+ `7ddd392` monitor
  fix). Provenance `data/provenance/EDR_T3/manifest.json`. **Snapshot `snap-095e9e1895f967774`** (data vol
  `vol-08bcf0ab11df2c9ed`). **Pristine `ed86a3b4`** preserved in `backups/edr_t3_prepromote_*` + tag
  `chat5-t3-prepromote-20260604T151642Z`; pilot artifact tagged `chat5-day3-stop-20260603`.
- **Reference firewall hardened + audited** (`325dbc7`): P13HMEON is comparison-only — read ONLY by the
  advisory gate #8 + Chat-6 reconciliation, never by any construction stage; store `data/raw/P13HMEON/`
  is `chmod a-w`. Gate hard-fail = reference-free core (checks 1–7); #8 cannot block a ship.
- **EDR_T1 prep:** import + step4 DONE (2422 imported, 2 corrupt LZW files excluded via `--exclude-images`,
  intake QC `a6042ae`; 65 disabled @0.30, distribution T3-like — @0.50 would drop 50.8%). Covariance wired
  (`e989337`), focal mode resolved = `fallback`.

## WHAT'S RUNNING + HOW TO CHECK
- **`align → markers` (discovery) running DETACHED** in tmux session **`t1align`** (tmux server is
  init-parented → survives SSH disconnect). Script: `scripts/ops/run_t1_align_markers.sh` (also at
  `/data/edr_work/run_t1_align_markers.sh`). It runs align → marker-discovery → **EXITS at the pre-dense
  stop; it NEVER starts the dense.**
- Log: **`/data/edr_work/logs/t1_align_markers.log`**. Finished when it contains
  **`T1_ALIGN_MARKERS_COMPLETE`**.
- Resource monitor running separately → `/data/edr_work/logs/{cpumem,gpu}_*.csv` (`scripts/monitor.sh
  summary` for peaks).
- **Read out of the log when done:** (1) `align` alignment rate + tie points; (2) `markers` line —
  the detected coded IDs and the scale-bar pairs; (3) the per-stage `esm.*` meta in `edr_t1.psx`. To see
  the **footprint geometry** (belt-or-not) build a quick interp-OFF DEM of the aligned cloud — but that
  needs the dense; pre-dense, infer extent from the tie-point/camera spread (a wide multi-pass area vs a
  10×1 belt).

## RESUME POINT = the pre-dense STOP (do these, in order)
a. **Read the align footprint → belt-or-not.** T1 is 9 double-lawnmower passes (C2–C6/R2–R5) vs T3's 2 —
   its footprint may NOT be a 10×1 belt. If it is a belt, `stage_aoi` applies unchanged. If it's a wider
   area, gate #6 (aspect ≥5) will reject it — decide a T1 AOI strategy.
b. **Confirm the marker-ID set** from the discovery pass → wire `--expected-marker-ids` (identity
   auto-tolerance). Expect 3–4 scale-bar pairs per ESM.
c. **If non-belt, choose the T1 AOI strategy REFERENCE-FREE** (markers / survey convention / a larger
   bbox) — NEVER P13HMEON. The reference is comparison-only.
d. **Fetch the T1 reference AFTER the AOI is fixed** (so we grab the matching product) — it's inside
   `EasternDryRocks_SfMproducts.zip` at the P13HMEON release; land it read-only in `data/raw/P13HMEON/`,
   wire as advisory gate #8.
e. **Go/no-go for the dense.** Only on explicit go. Then `dense → filter → aoi → dsm → ortho → gate →
   report` with the final config.

## OPEN ITEMS
- T1 belt-or-not (a); `--expected-marker-ids` TBD (b); T1 AOI strategy if non-belt (c); T1 reference
  deferred until AOI fixed (d).
- Snapshot `snap-095e9e1895f967774` completes async — verify it reached `completed`:
  `aws ec2 describe-snapshots --region us-east-1 --snapshot-ids snap-095e9e1895f967774 --query
  'Snapshots[0].State'`.
- Logan error-reduction script still not vendored → `reduce` uses the documented built-in fallback.

## SPOT-INSTANCE USE CASE (forward design — the T1 long run is the driver)
Goal: run the pipeline (esp. the 6–15 h dense) on **interruptible EC2 spot** to cut cost, surviving a
2-minute reclaim notice. What's **already spot-aligned** (this run is the prototype):
- **Stage-level checkpointing:** `run_pipeline.py --stage <s>` opens → runs ONE stage → SAVES the .psx →
  exits. Every stage is **idempotent** (skips if its output/meta exists), so re-entry on a replacement
  instance resumes from the last saved stage for free. No `--start-from` needed.
- **Detached + log-driven:** the tmux/`setsid` + log pattern here is the unattended-run shape; a wrapper
  loops `--stage` and is restartable.
- **Durable state on EBS:** the data volume (`vol-08bcf…`) holds the project; **EBS snapshots are the
  recovery points** (one taken after T3). Re-attach the volume (or restore the snapshot) to a fresh spot
  instance and resume.
What's **needed** to make it fully spot-safe (next build, T1 = the test case):
1. **Spot-interruption handler:** poll IMDS `/latest/meta-data/spot/instance-action` (or the
   rebalance-recommendation); on notice (≤2 min) → `doc.save()` the current project, snapshot the volume,
   write a resume marker, exit cleanly. Re-launch on a new spot instance picks up at the next `--stage`.
2. **Within-stage checkpointing for the dense (the long pole):** `buildDepthMaps` persists depth maps to
   the project incrementally, so a reclaim mid-`buildPointCloud` re-runs only point-cloud assembly, not
   all depth maps — verify and lean on that boundary. Align similarly saves only on completion (a reclaim
   mid-align restarts align — acceptable at ~1–2 h, costly at dense scale, hence #2 matters most there).
3. **Orchestration:** a small controller (systemd unit / launch-template user-data / a poll loop) that
   requests spot, attaches the volume, runs the next `--stage`, snapshots on interruption, and relaunches.
   Use a **persistent EBS data volume that detaches/re-attaches** (not instance-store) so nothing is lost.
4. **Capacity resilience:** `scripts/start-with-retry.sh` already polls `InsufficientInstanceCapacity`
   (built in Chat 5) — extend for spot-capacity + price.
Banked divergence: the pipeline stays the SAME (ESM Table S2); spot is an orchestration layer around the
existing `--stage` entrypoint, not a methodological change — record it that way in the ledger.

## REMINDER
**P13HMEON reference is comparison-only** (firewall `325dbc7`) — never a construction input, never the
T1 AOI. Construction = markers + own footprint + own scale bars + ESM params.

## RESUME COMMANDS (on reconnect)
```bash
ssh reef-ec2                                  # your usual alias to i-06fe7879a0e713c2f
tmux ls                                       # expect: t1align  (attach: tmux attach -t t1align)
tail -n 40 /data/edr_work/logs/t1_align_markers.log
grep -q T1_ALIGN_MARKERS_COMPLETE /data/edr_work/logs/t1_align_markers.log && echo FINISHED || echo RUNNING
cd /data/reef-sfm-mote-keys && git log --oneline -8 && git tag | tail -5
cat docs/session-log-2026-06-04.md           # this file
```
Nothing irreversible runs while away: worst case align + markers finish and the job sits at the pre-dense
stop — **the dense never starts without an explicit go.**
