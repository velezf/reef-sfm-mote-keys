#!/usr/bin/env python3
"""ab_quality_threshold.py — EDR_T3 image-quality threshold A/B (dev investigation).

Decides the ESM Step 4 quality threshold EMPIRICALLY on our data, not from a
number we don't have (Toth's per-transect registered count is not in the ESM —
Table S1 is coral-outplant survival, not registration — and the P13HMEON
products were never downloaded). See ADR-0017 and docs/05.

Two arms on the same 522 EDR_T3 frames, same alignment params (ESM High, 60k):
  q050 — Toth's verbatim ESM Step 4 cut: disable Image/Quality < 0.50
  q030 — floor cut: disable < 0.30 (the genuine low tail incl. the 2 ~0.0 frames)

Reports per arm: disabled / enabled / aligned cameras, alignment rate, tie-point
count, and sparse region extent (coverage). Decision rule (from the operator):
keep whichever aligns comparably with MORE coverage; if 0.50 shows no alignment
benefit over the floor, that is evidence it over-cuts our re-encoded TIFFs.

Read-only w.r.t. the production project: writes its own /data/edr_work/edr_t3_qab.psx.
"""
import glob
import json
import os
import time

import Metashape

IMG = "/data/raw/P1WHKTRD/EasternDryRocks"
PROJECT = "/data/edr_work/edr_t3_qab.psx"
OUT = "/data/edr_work/products/q_ab_results.json"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def quality(cam):
    raw = cam.meta["Image/Quality"] if "Image/Quality" in cam.meta else None
    try:
        return float(raw) if raw else None
    except (TypeError, ValueError):
        return None


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    photos = sorted(p for p in glob.glob(IMG + "/*.tif") if "EDR_T3" in os.path.basename(p))
    log(f"{len(photos)} EDR_T3 photos")

    doc = Metashape.Document()
    doc.save(PROJECT)
    base = doc.addChunk()
    base.label = "base"
    base.addPhotos(photos)
    log("analyzeImages on base (once; arms inherit the scores via copy)...")
    base.analyzeImages([c for c in base.cameras if c.photo is not None])
    doc.save()

    def run_arm(label, thresh):
        ch = base.copy()
        ch.label = label
        cams = [c for c in ch.cameras if c.photo is not None]
        disabled = 0
        for c in cams:
            q = quality(c)
            if q is not None and q < thresh:
                c.enabled = False
                disabled += 1
        enabled = sum(1 for c in ch.cameras if c.enabled)
        log(f"[{label}] disable <{thresh}: disabled={disabled} enabled={enabled}; "
            f"matchPhotos(High) + align + optimize ...")
        t0 = time.time()
        ch.matchPhotos(downscale=1, generic_preselection=True,
                       reference_preselection=False, keypoint_limit=60_000,
                       tiepoint_limit=0, filter_stationary_points=True)
        ch.alignCameras()
        ch.optimizeCameras()
        aligned = sum(1 for c in ch.cameras if c.transform)
        tp = len(ch.tie_points.points) if ch.tie_points else 0
        r = ch.region.size
        res = {
            "arm": label, "threshold": thresh,
            "disabled": disabled, "enabled": enabled, "aligned": aligned,
            "align_rate_of_enabled": round(aligned / enabled, 4) if enabled else None,
            "align_rate_of_522": round(aligned / len(cams), 4) if cams else None,
            "tie_points": tp,
            "region_size": [round(r.x, 4), round(r.y, 4), round(r.z, 4)],
            "minutes": round((time.time() - t0) / 60, 1),
        }
        log(f"[{label}] RESULT {json.dumps(res)}")
        doc.save()
        return res

    results = [run_arm("q050", 0.50), run_arm("q030", 0.30)]
    a, b = results
    log("=== A/B SUMMARY ===")
    for r in results:
        log(json.dumps(r))
    log(f"floor q030 aligned {b['aligned']} vs Toth-cut q050 {a['aligned']} "
        f"(of 522: {b['align_rate_of_522']*100:.1f}% vs {a['align_rate_of_522']*100:.1f}%); "
        f"tie pts {b['tie_points']:,} vs {a['tie_points']:,}; "
        f"enabled {b['enabled']} vs {a['enabled']}.")
    json.dump(results, open(OUT, "w"), indent=2)
    log(f"wrote {OUT}")


if __name__ == "__main__":
    main()
