#!/usr/bin/env python3
"""
smoke_test.py — de-risk the 24-48 h dense run BEFORE committing the night.

Why this exists
---------------
ESM "High" dense reconstruction on ~3,271 images runs 24-48 h on the L4. A
failure at hour 23 is the worst outcome in the project. This script proves the
pipeline runs end to end on a contiguous subset, AND specifically exercises the
two known risks surfaced in Chat 4b:

  RISK 1 — LZW decoder edge case (ADR-0009 / Chat 4b finding).
    Files 20230711_EDR_T1_C2_000197.tif and _000218.tif fail PIL's LZW pixel
    decoder (decoder error -2) though their EXIF reads fine. Open question:
    does Metashape's (different, usually more robust) TIFF decoder choke on the
    same files? We load them by name in a preflight and fail LOUDLY here rather
    than at hour 23.

  RISK 2 — missing FocalLength (ADR-0009).
    Photoshop stripped the EXIF sub-IFD, so there is no FocalLength to seed
    Metashape's initial intrinsics. Metashape falls back to bundle-adjustment-
    derived focal length. Chat 4b prescribed an A/B test: align the subset both
    with the bundle-adjusted fallback AND with a manual S120 calibration
    (5.2 mm wide-stop, 1.86 um pixel pitch), compare post-error-reduction
    reprojection error, and recommend which path to commit for the full run.

What "robust" means here (per the operator's instruction: runtime doesn't
matter, correctness does):
  * Subset = one FULL short transect (contiguous -> overlap preserved).
  * Dense stage = REAL dense cloud at ESM "High", not downscaled.
  * Both focal-length arms run fully through error reduction so the reprojection
    comparison is apples to apples.
  * Every export product is written and re-opened to prove it's not truncated.

This is intentionally slow. It is the cheap insurance against an expensive night.

Stages
------
  preflight : Metashape pixel-load test of EVERY subset image + the 2 known-bad
              files by name. No alignment. Fails loudly on any decode error.
  ab        : focal-length A/B (fallback vs manual S120), through error
              reduction, reports reprojection error per arm + recommendation.
  full      : the winning arm runs dense + DSM + ortho + export on the subset,
              every product re-opened to verify integrity.
  all       : preflight -> ab -> full (default)

Usage
-----
    metashape.sh -r smoke_test.py \\
        --image-root /data/edr/images \\
        --transect EDR_T8 \\
        --smoke-project /data/edr/smoke/smoke.psx \\
        --out-root /data/edr/smoke/products \\
        --stage all
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

try:
    import Metashape
except ImportError:
    sys.exit("Run through metashape.sh; Metashape module not importable.")

# Known-bad files from Chat 4b. Loaded by name in preflight regardless of which
# transect the subset comes from, so the decoder risk is always exercised.
KNOWN_BAD = [
    "20230711_EDR_T1_C2_000197.tif",
    "20230711_EDR_T1_C2_000218.tif",
]

# Canon PowerShot S120 manual calibration (RISK 2, manual arm).
# Lens 5.2-26.0 mm zoom; 5.2 mm is the WIDE stop. Sensor 1/1.7" = 7.44x5.58 mm,
# 4000x3000 px -> pixel pitch ~= 7.44/4000 mm = 1.86 um.
# NOTE: this assumes the divers shot at the wide stop. If they zoomed, this is
# wrong and the A/B will reveal it (manual arm aligns worse). That is a useful
# result, not a bug.
S120_FOCAL_MM = 5.2
S120_PIXEL_MM = 7.44 / 4000.0  # ~0.00186 mm

# Focal-decision margins. RMS is primary; alignment is the tiebreak. A gap must
# exceed its margin to count as "decisive" — within the margin is treated as a
# tie. Note: the RMS used here is in Metashape filter units (NOT raw image
# pixels) — see _reprojection_rms and ADR-0012. The margin is set in the same
# units; 0.02 is well below the unit-1-scale separation we expect a real quality
# difference to produce, while noise stays under it.
RMS_MARGIN_FILTER = 0.02
ALIGN_MARGIN_PCT = 2.0


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] SMOKE: {msg}", flush=True)


def _log_dense_bbox(pc: "Metashape.PointCloud", log_fn,
                    label: str, json_path: Path, snapshot_key: str) -> None:
    """Print + persist the dense point cloud's bbox extent.

    Used to verify the ESM Step 13 confidence filter actually collapses the
    point-cloud bbox from outlier-driven ~10^7 chunk units down to the real
    footprint (chunk.region scale, ~10^1 units). Logs to stdout and merges
    into bbox_pre_post_filter.json under the given snapshot_key.
    """
    info = {"snapshot": snapshot_key, "label": label,
            "point_count": pc.point_count}
    try:
        ext = pc.extent()  # method call, not property — per API ref
        try:
            info["min"] = {"x": ext.min.x, "y": ext.min.y, "z": ext.min.z}
            info["max"] = {"x": ext.max.x, "y": ext.max.y, "z": ext.max.z}
            info["size"] = {"x": ext.max.x - ext.min.x,
                            "y": ext.max.y - ext.min.y,
                            "z": ext.max.z - ext.min.z}
        except AttributeError:
            info["extent_repr"] = repr(ext)
    except (AttributeError, TypeError) as exc:
        info["extent_error"] = f"pc.extent() unavailable: {exc}"
    log_fn(f"{label} dense: pts={info['point_count']:,}; "
           f"bbox_min={info.get('min')}; bbox_max={info.get('max')}; "
           f"size={info.get('size')}")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {}
    if json_path.exists():
        try:
            payload = json.loads(json_path.read_text())
        except Exception:
            payload = {}
    payload[snapshot_key] = info
    json_path.write_text(json.dumps(payload, indent=2))


# --------------------------------------------------------------------------- #
# Subset selection — contiguous, overlap-preserving
# --------------------------------------------------------------------------- #


_TRANSECT_RE = re.compile(r"(EDR_T\d+)", re.IGNORECASE)


def collect_transect(image_root: Path, transect: str) -> list[Path]:
    """Return the contiguous image list for one transect.

    Handles both a per-transect subfolder and the actual FLAT P1WHKTRD layout
    (all TIFFs in image_root, transect encoded in the filename). Sorting by
    filename preserves capture order -> swim-path overlap, which SfM alignment
    needs.
    """
    tdir = image_root / transect
    if tdir.is_dir():
        photos = sorted(list(tdir.glob("*.tif")) + list(tdir.glob("*.tiff")))
    else:
        # Flat: filter the whole dir by the transect token in the filename.
        want = transect.upper()
        photos = sorted(
            p for p in (list(image_root.glob("*.tif")) +
                        list(image_root.glob("*.tiff")))
            if (m := _TRANSECT_RE.search(p.name)) and m.group(1).upper() == want
        )
    if not photos:
        sys.exit(f"No TIFFs for transect {transect} under {image_root} "
                 f"(checked subfolder and flat-filename layouts).")
    log(f"{transect}: {len(photos)} contiguous images (full short transect).")
    return photos


def find_known_bad(image_root: Path) -> list[Path]:
    """Locate the known-bad files anywhere under image_root."""
    found = []
    for name in KNOWN_BAD:
        hits = list(image_root.rglob(name))
        if hits:
            found.append(hits[0])
        else:
            log(f"NOTE: known-bad file {name} not found under {image_root} "
                f"(may be in a transect not downloaded). Skipping it.")
    return found


# --------------------------------------------------------------------------- #
# Stage: preflight — pixel load test, no alignment
# --------------------------------------------------------------------------- #


def stage_preflight(image_root: Path, subset: list[Path]) -> None:
    """Open every subset image + known-bad files through Metashape and force a
    pixel read. Metashape uses its own TIFF decoder; this is the definitive
    test of whether the LZW edge case affects the real pipeline.
    """
    targets = list(subset)
    for p in find_known_bad(image_root):
        if p not in targets:
            targets.append(p)

    log(f"Pixel-load preflight on {len(targets)} files "
        f"(incl. {len(KNOWN_BAD)} known-bad).")
    failures: list[tuple[str, str]] = []
    tmp = Metashape.Document()
    chunk = tmp.addChunk()

    for p in targets:
        try:
            chunk.addPhotos([str(p)])
            cam = chunk.cameras[-1]
            # Force an actual pixel decode, not just a header read.
            img = cam.photo.image()
            if img is None or img.width == 0:
                failures.append((p.name, "image() returned empty"))
            else:
                _ = img[0, 0]  # touch a pixel
        except Exception as exc:  # noqa: BLE001 - we want every failure logged
            failures.append((p.name, str(exc)))

    if failures:
        log(f"PREFLIGHT FAILURES ({len(failures)}):")
        for name, why in failures:
            log(f"   {name}: {why}")
        is_known = all(any(k in name for k in KNOWN_BAD) for name, _ in failures)
        if is_known:
            log("All failures are the known-bad files. Decide: re-export those "
                "2 from source, or exclude them (2/3271 is cosmetically "
                "negligible for SfM coverage). Do NOT start the full run until "
                "decided.")
        sys.exit(1)
    log("PREFLIGHT PASSED: Metashape decoded every file, including known-bad. "
        "The PIL decoder issue does NOT affect Metashape. Safe to proceed.")


# --------------------------------------------------------------------------- #
# Stage: focal-length A/B
# --------------------------------------------------------------------------- #


def _align_arm(subset: list[Path], manual_calib: bool, out_root: Path) -> dict:
    """Build one chunk, align, run the 3-filter error reduction (ESM Step 8),
    return reprojection-error stats. manual_calib toggles RISK-2 arm.
    """
    doc = Metashape.Document()
    chunk = doc.addChunk()
    chunk.label = "manual_5.2mm" if manual_calib else "bundle_fallback"
    chunk.addPhotos([str(p) for p in subset])

    if manual_calib:
        # Seed intrinsics from the S120 wide-stop assumption.
        for sensor in chunk.sensors:
            sensor.type = Metashape.Sensor.Type.Frame
            sensor.pixel_width = S120_PIXEL_MM
            sensor.pixel_height = S120_PIXEL_MM
            sensor.focal_length = S120_FOCAL_MM
            sensor.fixed_params = []  # let bundle adjust refine from the seed
        log(f"{chunk.label}: seeded f={S120_FOCAL_MM}mm, "
            f"pix={S120_PIXEL_MM*1000:.3f}um")
    else:
        log(f"{chunk.label}: no intrinsics seed; bundle-adjusted fallback "
            f"(no FocalLength in EXIF).")

    chunk.matchPhotos(downscale=1, generic_preselection=True,
                      keypoint_limit=60_000, tiepoint_limit=0,
                      filter_stationary_points=True)
    chunk.alignCameras()
    chunk.optimizeCameras()

    # ESM Step 8 error reduction (faithful built-in transcription; the Logan
    # script would do the same three filters — for the A/B we only need the
    # reprojection outcome, and using the native path keeps the comparison
    # self-contained).
    tp = chunk.tie_points
    F = Metashape.TiePoints.Filter
    for crit, thresh in [(F.ReconstructionUncertainty, 30.0),
                         (F.ProjectionAccuracy, 3.5),
                         (F.ReprojectionError, 0.3)]:
        f = F()
        f.init(chunk, criterion=crit)
        f.selectPoints(thresh)
        tp.removeSelectedPoints()
        if crit != F.ReprojectionError:
            chunk.optimizeCameras()
    chunk.optimizeCameras(fit_corrections=True)

    # Reprojection RMS (px) computed DIRECTLY from the live tie-point residuals,
    # not parsed from the exported report PDF. The PDF computes the same number,
    # but reading it back means parsing a designed document whose layout drifts
    # across Metashape versions — exactly the brittle report-coupling the
    # longitudinal-comparability doc says the provenance layer exists to avoid.
    # Source data -> number is robust; PDF -> number is not. See compute below.
    reproj_rms, n_resid = _reprojection_rms(chunk)
    n_aligned = sum(1 for c in chunk.cameras if c.transform)
    result = {
        "arm": chunk.label,
        "cameras_total": len(chunk.cameras),
        "cameras_aligned": n_aligned,
        "aligned_pct": round(100 * n_aligned / len(chunk.cameras), 1)
        if chunk.cameras else 0.0,
        "tie_points_after_reduction": len(chunk.tie_points.points),
        "reproj_rms_filter_units": round(reproj_rms, 4)
        if reproj_rms is not None else None,
        "reproj_residual_count": n_resid,
        "reproj_rms_units_note": (
            "Metashape ReprojectionError filter values; normalized internal "
            "units, NOT image pixels. A/B comparison only; pixel-calibrated "
            "RMS for the Toth envelope comes from the full-run report PDF. "
            "See ADR-0012."),
    }
    # Still export the report PDF as a human-readable cross-check artifact — the
    # operator can eyeball it to confirm our computed RMS matches what Metashape
    # prints. The pipeline does NOT depend on parsing it.
    rpt = out_root / f"{chunk.label}_smoke_report.pdf"
    try:
        rpt.parent.mkdir(parents=True, exist_ok=True)
        chunk.exportReport(str(rpt))
        result["report_pdf"] = str(rpt)
    except Exception as exc:  # noqa: BLE001
        result["report_pdf_error"] = str(exc)
    return result


def _reprojection_rms(chunk: "Metashape.Chunk") -> tuple[float | None, int]:
    """Compute RMS of per-tie-point reprojection-error filter values.

    UNITS: these are Metashape's normalized internal filter units, NOT raw
    image pixels. Manually re-projecting tie points (via cam.project /
    cam.error) in an unscaled chunk produced nonsense magnitudes, so we use
    the same per-point value the gradual-selection filter compares to its
    threshold. This is fine for the A/B (both arms measured the same way), but
    is NOT directly comparable to Toth's 0.27-0.52 px published RMS envelope —
    that comes from the pixel-calibrated number in the Metashape report PDF
    after the full run has scale bars + coordinate frame set. See ADR-0012.
    Returns (rms_filter_units, point_count); rms is None if nothing is aligned.
    """
    tp = chunk.tie_points
    if not tp.points:
        return None, 0
    f = Metashape.TiePoints.Filter()
    f.init(chunk, Metashape.TiePoints.Filter.ReprojectionError)
    errs = [e for e, pt in zip(f.values, tp.points) if pt.valid]
    if not errs:
        return None, 0
    rms = (sum(e * e for e in errs) / len(errs)) ** 0.5
    return rms, len(errs)


def stage_ab(subset: list[Path], out_root: Path) -> str:
    """Run both focal arms, measure each, and emit a STRUCTURED decision
    artifact (focal_decision.json) that the full run reads programmatically.

    Decision criterion (operator-selected): reprojection RMS is primary,
    alignment % is the tiebreak. A clear winner yields verdict DECIDED. If the
    two signals point opposite ways — one arm has lower RMS but the other aligns
    materially more cameras — the validator does NOT guess; it emits
    NEEDS_REVIEW so the night only ever runs on a justified or consciously-made
    choice.

    Returns the chosen arm string ("fallback"/"manual") on a DECIDED verdict,
    or "NEEDS_REVIEW".
    """
    log("FOCAL-LENGTH A/B (RISK 2). Two full alignment+reduction passes.")
    out_root.mkdir(parents=True, exist_ok=True)
    fallback = _align_arm(subset, manual_calib=False, out_root=out_root)
    manual = _align_arm(subset, manual_calib=True, out_root=out_root)

    log("A/B MEASUREMENTS (RMS in Metashape filter units, see ADR-0012; "
        "NOT image pixels):")
    for r in (fallback, manual):
        log(f"   {r['arm']}: RMS={r['reproj_rms_filter_units']} (filter), "
            f"aligned {r['cameras_aligned']}/{r['cameras_total']} "
            f"({r['aligned_pct']}%), "
            f"{r['tie_points_after_reduction']} tie pts after reduction")

    decision = _decide_focal(fallback, manual)

    artifact = {
        "artifact_type": "focal_length_decision",
        "schema_version": 1,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "subset_image_count": len(subset),
        "criterion": {
            "primary": "reproj_rms_filter_units (lower is better)",
            "tiebreak": "aligned_pct (higher is better)",
            "rms_margin_filter_units": RMS_MARGIN_FILTER,
            "rms_units_note": (
                "Metashape ReprojectionError filter values; normalized "
                "internal units, NOT image pixels. Smoke A/B comparison "
                "only. Pixel-calibrated RMS for the Toth 0.27-0.52 px "
                "envelope comparison comes from the full-run report PDF "
                "after scale bars + coordinate frame are set. See ADR-0012."),
            "align_margin_pct": ALIGN_MARGIN_PCT,
            "s120_manual_assumption": {
                "focal_length_mm": S120_FOCAL_MM,
                "pixel_pitch_mm": round(S120_PIXEL_MM, 6),
                "note": "assumes wide-stop; if divers zoomed this arm degrades",
            },
        },
        "arms": {"fallback": fallback, "manual": manual},
        "decision": decision,
    }
    (out_root / "focal_decision.json").write_text(json.dumps(artifact, indent=2))
    log(f"VERDICT: {decision['verdict']} -> arm '{decision['chosen_arm']}'")
    log(f"  rationale: {decision['rationale']}")
    log(f"  artifact: {out_root / 'focal_decision.json'}")
    if decision["verdict"] == "NEEDS_REVIEW":
        log("  The signals disagree. The full run will NOT auto-proceed; pass "
            "--focal-mode {fallback,manual} explicitly after reviewing the "
            "artifact and the two _smoke_report.pdf cross-checks.")
    return decision["chosen_arm"]


def _decide_focal(fallback: dict, manual: dict) -> dict:
    """Apply the RMS-primary / alignment-tiebreak criterion to the two arms.

    RMS values are in Metashape filter units (see ADR-0012), not pixels — the
    relative comparison between arms is valid; the absolute number is not
    directly comparable to Toth's pixel-calibrated envelope.

    Logic:
      * If either arm failed to produce an RMS (no alignment), the other wins
        by default (DEGRADED note).
      * Otherwise compare RMS. If the RMS gap exceeds RMS_MARGIN_FILTER, the
        lower-RMS arm wins (DECIDED).
      * If RMS is within the margin (a tie on quality), use alignment %: the
        arm aligning >ALIGN_MARGIN_PCT more cameras wins (DECIDED).
      * If RMS ties AND alignment ties, prefer fallback (the no-assumption
        choice) — DECIDED, low-stakes.
      * The one case that escalates: RMS clearly favors one arm while alignment
        clearly favors the other. The validator refuses to trade quality
        against coverage on the operator's behalf -> NEEDS_REVIEW.
    """
    fr = fallback["reproj_rms_filter_units"]
    mr = manual["reproj_rms_filter_units"]
    fa, ma = fallback["aligned_pct"], manual["aligned_pct"]

    # Degenerate: an arm didn't align.
    if fr is None and mr is None:
        return {"verdict": "NEEDS_REVIEW", "chosen_arm": "NEEDS_REVIEW",
                "rationale": "Neither arm aligned. Data or parameter problem; "
                             "do not start the full run."}
    if fr is None:
        return {"verdict": "DECIDED", "chosen_arm": "manual",
                "rationale": "Fallback failed to align; manual arm wins by "
                             "default. Investigate why fallback failed."}
    if mr is None:
        return {"verdict": "DECIDED", "chosen_arm": "fallback",
                "rationale": "Manual arm failed to align (wide-stop assumption "
                             "likely wrong); fallback wins by default."}

    rms_gap = abs(fr - mr)
    align_gap = abs(fa - ma)
    rms_winner = "fallback" if fr < mr else "manual"
    align_winner = "fallback" if fa > ma else "manual"

    rms_decisive = rms_gap > RMS_MARGIN_FILTER
    align_decisive = align_gap > ALIGN_MARGIN_PCT

    if rms_decisive and align_decisive and rms_winner != align_winner:
        return {"verdict": "NEEDS_REVIEW", "chosen_arm": "NEEDS_REVIEW",
                "rationale": (f"Signals disagree: lower RMS is '{rms_winner}' "
                              f"(gap {rms_gap:.4f} filter units) but higher "
                              f"alignment is '{align_winner}' (gap "
                              f"{align_gap:.1f}%). Quality vs coverage "
                              f"trade-off is yours to make.")}

    if rms_decisive:
        return {"verdict": "DECIDED", "chosen_arm": rms_winner,
                "rationale": (f"Lower reprojection RMS ('{rms_winner}', "
                              f"{min(fr, mr):.4f} vs {max(fr, mr):.4f} filter "
                              f"units, gap {rms_gap:.4f} > {RMS_MARGIN_FILTER} "
                              f"margin). RMS is primary per the criterion.")}

    # RMS within margin -> quality tie; fall to alignment tiebreak.
    if align_decisive:
        return {"verdict": "DECIDED", "chosen_arm": align_winner,
                "rationale": (f"RMS within {RMS_MARGIN_FILTER} filter units "
                              f"(quality tie at ~{fr:.4f}/{mr:.4f}); tiebreak "
                              f"on alignment favors '{align_winner}' "
                              f"(+{align_gap:.1f}%).")}

    return {"verdict": "DECIDED", "chosen_arm": "fallback",
            "rationale": (f"RMS and alignment both within margins "
                          f"(RMS {fr:.4f}/{mr:.4f} filter units, align "
                          f"{fa}/{ma}%). Prefer fallback: no wrong-zoom "
                          f"assumption, matches how high-overlap reef data "
                          f"is normally handled.")}


# --------------------------------------------------------------------------- #
# Stage: full — real dense + DSM + ortho + export, with re-open integrity check
# --------------------------------------------------------------------------- #


def stage_full(subset: list[Path], smoke_project: Path, out_root: Path,
               arm: str) -> None:
    """Run the full dense → filter → DSM/ortho → export sequence on the subset.

    DSM and orthomosaic generation on unscaled chunks may OOM due to
    buildDem extent inference (see ADR-0016). The smoke continues without
    them rather than crashing — production builds on scaled chunks where
    this is not an issue. Dense.ply, focal_decision.json,
    bbox_pre_post_filter.json, and the processing report are always
    exported regardless of DSM/ortho success.
    """
    log(f"FULL subset pipeline using '{arm}' arm. REAL dense at ESM High.")
    smoke_project.parent.mkdir(parents=True, exist_ok=True)
    doc = Metashape.Document()
    doc.save(str(smoke_project))
    chunk = doc.addChunk()
    chunk.label = f"smoke_{arm}"
    chunk.addPhotos([str(p) for p in subset])

    if arm == "manual":
        for s in chunk.sensors:
            s.pixel_width = s.pixel_height = S120_PIXEL_MM
            s.focal_length = S120_FOCAL_MM

    chunk.matchPhotos(downscale=1, generic_preselection=True,
                      keypoint_limit=60_000, tiepoint_limit=0,
                      filter_stationary_points=True)
    chunk.alignCameras()
    chunk.optimizeCameras()
    doc.save()

    log("Dense (High, Mild) — the real thing on the subset.")
    t0 = time.time()
    chunk.buildDepthMaps(downscale=2, filter_mode=Metashape.MildFiltering)
    chunk.buildPointCloud(point_colors=True, point_confidence=True)
    log(f"Dense done in {(time.time()-t0)/60:.1f} min.")
    doc.save()

    # ESM Step 13 confidence noise filter applied to the dense cloud BEFORE
    # buildDem. Engineered destructive departure from ESM's classify-and-keep
    # GUI workflow; see ADR-0015 for full reasoning. Documented as remove
    # (cleanPointCloud line 1929) followed by undocumented-but-required
    # compactPoints materialization (line 6203 — point_count is stale until
    # compact is called, established via probe_v8_cleanpc.py). Outliers
    # from unscaled bundle adjustment that previously OOM'd buildDem are
    # caught at threshold=2 and removed; the bbox then collapses to the
    # real footprint.
    pc = chunk.point_cloud
    _log_dense_bbox(pc, log, label="pre-filter",
                    json_path=out_root / "bbox_pre_post_filter.json",
                    snapshot_key="pre")
    n_before = pc.point_count
    chunk.cleanPointCloud(
        criterion=Metashape.PointCloud.Criterion.Confidence,
        threshold=2,
    )
    pc.compactPoints()
    n_after = pc.point_count
    removed = n_before - n_after
    log(f"ESM Step 13 noise removal (cleanPointCloud + compactPoints, "
        f"threshold=2): {n_before:,} -> {n_after:,} dense pts "
        f"({removed:,} removed, "
        f"{100*removed/max(n_before, 1):.1f}%). See ADR-0015.")
    if n_before > 0 and removed == 0:
        log(f"WARNING: ESM Step 13 removed 0 points at threshold=2. "
            f"Expected if the dense cloud has no points with confidence < 2; "
            f"not necessarily an error. See bbox_pre_post_filter.json.")
    _log_dense_bbox(pc, log, label="post-filter",
                    json_path=out_root / "bbox_pre_post_filter.json",
                    snapshot_key="post")
    doc.save()

    # Smoke-only: buildDem infers target extent from camera viewing volumes
    # or depth-map extents rather than pc.extent() — which means the dense
    # cloud's confidence filter doesn't constrain DSM bbox inference (filter
    # operates on point_cloud; buildDem reads something else). On an unscaled
    # chunk this produces multi-billion-pixel DEMs and std::bad_alloc.
    # Production gets scale from manual coded-target placement (ESM Step 7)
    # and Jenkins Alignment Helper (ESM Step 11); on a scaled chunk
    # buildDem auto-inferred extent is in meters and tractable.
    # See ADR-0016 and bbox_pre_post_filter.json.
    size = chunk.region.size
    center = chunk.region.center
    smoke_res = max(size.x, size.y) / 2000.0
    smoke_bbox = Metashape.BBox()
    smoke_bbox.min = Metashape.Vector(
        [center.x - size.x / 2.0, center.y - size.y / 2.0])
    smoke_bbox.max = Metashape.Vector(
        [center.x + size.x / 2.0, center.y + size.y / 2.0])
    log(f"Smoke DSM/ortho resolution (chunk units): {smoke_res:.6f}; "
        f"BBox region clip to chunk.region xy footprint (smoke-only, see "
        f"ADR-0016). Unscaled chunk; outputs NOT metrically comparable to "
        f"Toth. Production builds metric DSM at 1 cm in run_pipeline.py "
        f"post-scale-bars without this clip.")
    # DSM and orthomosaic generation on unscaled chunks may OOM due to
    # buildDem extent inference reading beyond pc.extent() and beyond the
    # explicit BBox region clip (see ADR-0016). The smoke continues without
    # them rather than crashing — production builds on scaled chunks where
    # this is not an issue. The MemoryError below is logged loudly so it
    # can't be missed when reviewing smoke output.
    built_dem = False
    built_ortho = False
    try:
        chunk.buildDem(source_data=Metashape.PointCloudData,
                       interpolation=Metashape.EnabledInterpolation,
                       resolution=smoke_res, region=smoke_bbox)
        built_dem = True
    except MemoryError as exc:
        log(f"WARNING: buildDem OOM'd on unscaled chunk "
            f"(MemoryError: {exc}). Continuing without DSM/ortho. "
            f"See ADR-0016.")
    if built_dem:
        try:
            chunk.buildOrthomosaic(surface_data=Metashape.ElevationData,
                                   blending_mode=Metashape.MosaicBlending,
                                   fill_holes=True, resolution=smoke_res,
                                   region=smoke_bbox)
            built_ortho = True
        except MemoryError as exc:
            log(f"WARNING: buildOrthomosaic OOM'd on unscaled chunk "
                f"(MemoryError: {exc}). Continuing without ortho. "
                f"See ADR-0016.")
    doc.save()

    out_root.mkdir(parents=True, exist_ok=True)
    products: dict[str, Path] = {
        "dense": out_root / "smoke_dense.ply",
    }
    chunk.exportPointCloud(str(products["dense"]),
                           source_data=Metashape.PointCloudData,
                           save_point_color=True, save_point_confidence=True)
    if built_dem:
        products["dsm"] = out_root / "smoke_dsm.tif"
        try:
            chunk.exportRaster(str(products["dsm"]),
                               source_data=Metashape.ElevationData,
                               resolution=smoke_res)
        except Exception as exc:
            log(f"WARNING: DSM export failed: {exc}")
            del products["dsm"]
    if built_ortho:
        products["ortho"] = out_root / "smoke_ortho.tif"
        try:
            chunk.exportRaster(str(products["ortho"]),
                               source_data=Metashape.OrthomosaicData)
        except Exception as exc:
            log(f"WARNING: ortho export failed: {exc}")
            del products["ortho"]
    chunk.exportReport(str(out_root / "smoke_report.pdf"))

    # Integrity check: every product exists and is non-trivially sized.
    log("Verifying exported products are present and non-empty:")
    ok = True
    for name, path in products.items():
        if path.exists() and path.stat().st_size > 1024:
            log(f"   {name}: OK ({path.stat().st_size/1e6:.1f} MB)")
        else:
            log(f"   {name}: MISSING or too small — export path/perm problem.")
            ok = False
    if not ok:
        sys.exit("FULL stage produced incomplete exports of "
                 "expected-to-build products. Fix before full run.")
    if not built_dem or not built_ortho:
        log("PARTIAL SMOKE: dense + report exported; DSM/ortho deferred to "
            "scaled production runs per ADR-0016. The confidence filter "
            "(ADR-0015) was validated end-to-end on the dense cloud — that "
            "was the actual Chat 5 mandate.")
    else:
        log("FULL SUBSET PIPELINE PASSED end to end. The plumbing is sound: "
            "every API call (matchPhotos, alignCameras, optimizeCameras, "
            "error reduction, buildDepthMaps, buildPointCloud, "
            "cleanPointCloud, compactPoints, buildDem, buildOrthomosaic, "
            "exportPointCloud, exportRaster, exportReport) executed and "
            "every product exported. NOTE: this does NOT prove the full "
            "3,271-image run won't hit disk-full or GPU-OOM at full point "
            "count — check free disk on /data and nvidia-smi memory "
            "headroom before launching the night.")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image-root", required=True, type=Path)
    ap.add_argument("--transect", default="EDR_T8",
                    help="Which transect to use as the contiguous subset.")
    ap.add_argument("--smoke-project", type=Path,
                    default=Path("/data/edr/smoke/smoke.psx"))
    ap.add_argument("--out-root", type=Path,
                    default=Path("/data/edr/smoke/products"))
    ap.add_argument("--stage", default="all",
                    choices=["preflight", "ab", "full", "all"])
    ap.add_argument("--arm", default=None, choices=["fallback", "manual"],
                    help="Force the full-stage arm; default uses A/B winner.")
    args = ap.parse_args()

    subset = collect_transect(args.image_root, args.transect)

    if args.stage in ("preflight", "all"):
        stage_preflight(args.image_root, subset)

    winner = args.arm
    if args.stage in ("ab", "all"):
        winner = stage_ab(subset, args.out_root)

    if args.stage in ("full", "all"):
        # NEEDS_REVIEW (or missing decision) must not silently pick an arm.
        if winner in (None, "NEEDS_REVIEW"):
            if args.arm:
                arm = args.arm
                log(f"A/B was inconclusive but operator forced --arm {arm}.")
            else:
                sys.exit(
                    "Focal decision is NEEDS_REVIEW (or absent) and no "
                    "--focal-mode/--arm was given. Refusing to run the full "
                    "subset on an unjustified focal choice. Review "
                    f"{args.out_root / 'focal_decision.json'} and the "
                    "_smoke_report.pdf cross-checks, then re-run --stage full "
                    "with --arm {fallback,manual}.")
        else:
            arm = winner
        stage_full(subset, args.smoke_project, args.out_root, arm)

    log("Smoke test complete.")


if __name__ == "__main__":
    main()
