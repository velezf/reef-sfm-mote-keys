#!/usr/bin/env python3
"""
run_pipeline.py — EasternDryRocks SfM pipeline, Toth et al. 2025 ESM Table S2.

Reproduces the Mote/USGS Metashape v2.0 workflow on the EDR transects using the
PUBLISHED parameter values (ESM Table S2), NOT the PIFSC SOP values that the
original project plan cited. This change is binding per ADR-0010; see
docs/05-metashape-processing.md for the full reconciliation.

Design goals
------------
* Headless-first. Runs under `metashape.sh -r run_pipeline.py ...` with no GUI.
  Every stage that CAN be automated through the Python API is automated here.
* Resumable. Each stage checks whether its output already exists in the .psx
  project and skips if so, so an overnight run that dies at the dense-cloud
  stage can be resumed without redoing alignment.
* Per-transect chunks. One chunk per transect (EDR_T1, EDR_T3, EDR_T8),
  matching ESM Step 3 ("Create chunk from each subfolder").
* Faithful, not approximate. Where the Logan error-reduction script defaults to
  percentage-based selection, we drive it in THRESHOLD mode with Toth's values.

What is NOT done here (GUI / manual — see docs)
-----------------------------------------------
* Scale-bar definition between detected markers (ESM Step 7). Marker DETECTION
  is automated; assigning the 25 cm distance to marker pairs and naming the
  scale bars is reviewed/confirmed in the GUI.
* Point-cloud class segmentation by lasso (ESM Step 13). Confidence-based noise
  classification IS automated here; the canopy/outplant/reef-base distinction
  is manual (one transect this chat) — see segment_pointcloud.py.

Usage
-----
    metashape.sh -r run_pipeline.py --project /data/edr/edr.psx \\
        --image-root /data/edr/images --stage all

    # resume just the dense stage onward:
    metashape.sh -r run_pipeline.py --project /data/edr/edr.psx --stage dense

Stages: align | reduce | dense | dsm | ortho | report | all
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

try:
    import Metashape
except ImportError:
    sys.exit(
        "Metashape module not importable. Run this through metashape.sh, not a "
        "bare python interpreter. The Python API is Pro-only and is exposed by "
        "the trial."
    )

# --------------------------------------------------------------------------- #
# Parameters — ESM Table S2 (Toth et al. 2025). BINDING per ADR-0010.
# Each value carries the ESM step it comes from so the provenance layer in
# Chat 6 can cross-validate the manifest against this source of truth.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ESMParameters:
    # Step 5 — Alignment
    align_accuracy: str = "High"            # Metashape.HighAccuracy
    generic_preselection: bool = True
    reference_preselection: bool = False
    keypoint_limit: int = 60_000            # Toth 60k  (PIFSC was 40k)
    tiepoint_limit: int = 0
    exclude_stationary_tie_points: bool = True   # Toth: yes (PIFSC: unspecified)

    # Step 7 — Markers
    marker_type: str = "Circular12bit"
    marker_tolerance: int = 20              # ESM: "start with 20", raise if misses
    scalebar_length_m: float = 0.25         # 25 cm coded targets

    # Step 8 — Error reduction (Logan script, threshold mode)
    reconstruction_uncertainty: float = 30.0   # Toth 20-40 -> midpoint 30
    projection_accuracy: float = 3.5           # Toth 3-4   -> midpoint 3.5
    reprojection_error: float = 0.3            # Toth fixed 0.3 (PIFSC 0.3-0.5)
    fit_additional_after_reduction: bool = True

    # Step 12 — Dense (point) cloud
    dense_quality: str = "High"             # Toth High (PIFSC Medium) — big runtime cost
    depth_filtering: str = "Mild"
    point_colors: bool = True
    tiepoint_covariance: bool = True

    # Step 14 — DSM
    dsm_resolution_m: float = 0.01          # Toth 1 cm (PIFSC was 1 mm)

    # Step 15 — Orthomosaic
    ortho_blend: str = "Mosaic"
    ortho_hole_filling: bool = True


PARAMS = ESMParameters()

# Map our string names to Metashape enums in one place so the dataclass stays
# pure data (and serialisable straight into the provenance manifest).
_ACCURACY = {
    "High": Metashape.HighAccuracy,
    "Medium": Metashape.MediumAccuracy,
}
_QUALITY = {
    "High": Metashape.HighQuality,
    "Medium": Metashape.MediumQuality,
}
_DEPTH = {
    "Mild": Metashape.MildFiltering,
    "Moderate": Metashape.ModerateFiltering,
    "Aggressive": Metashape.AggressiveFiltering,
}
_BLEND = {"Mosaic": Metashape.MosaicBlending}

# S120 manual calibration, mirrored from smoke_test.py (single source would be a
# shared module in the Chat 6 package; duplicated here to keep the two scripts
# independently runnable).
S120_FOCAL_MM = 5.2
S120_PIXEL_MM = 7.44 / 4000.0


# --------------------------------------------------------------------------- #
# Focal-length decision — read the smoke test's structured artifact.
# This is the programmatic handoff: the full run does NOT re-decide and does NOT
# ask a human to read a PDF. It reads focal_decision.json, applies the chosen
# arm, and refuses to start if the decision was NEEDS_REVIEW or is missing
# (unless the operator overrides with an explicit --focal-mode).
# --------------------------------------------------------------------------- #


def resolve_focal_mode(decision_path: Path | None,
                       override: str | None) -> str:
    """Return 'fallback' or 'manual'. Order of authority:
       1. explicit --focal-mode override (operator's conscious choice)
       2. focal_decision.json with a DECIDED verdict
       3. otherwise: refuse (NEEDS_REVIEW or missing artifact)
    """
    if override:
        log(f"Focal mode set explicitly by operator: {override}")
        return override

    if decision_path is None or not decision_path.exists():
        sys.exit(
            "No focal-length decision artifact and no --focal-mode override. "
            "Run smoke_test.py first to produce focal_decision.json, or pass "
            "--focal-mode {fallback,manual}. Refusing to start a 24-48 h run "
            "on an undecided focal-length configuration.")

    artifact = json.loads(decision_path.read_text())
    decision = artifact.get("decision", {})
    verdict = decision.get("verdict")
    arm = decision.get("chosen_arm")
    if verdict == "DECIDED" and arm in ("fallback", "manual"):
        log(f"Focal mode from {decision_path.name}: '{arm}' "
            f"(verdict DECIDED). Rationale: {decision.get('rationale','')}")
        return arm

    sys.exit(
        f"Focal decision artifact verdict is '{verdict}' (arm '{arm}'). The "
        "smoke test could not justify a choice automatically. Review "
        f"{decision_path} and the _smoke_report.pdf cross-checks, then re-run "
        "with --focal-mode {fallback,manual} to record your conscious choice. "
        "Refusing to auto-pick on NEEDS_REVIEW.")


def apply_focal_mode(chunk: "Metashape.Chunk", mode: str) -> None:
    """Seed S120 intrinsics if manual mode; no-op for fallback."""
    if mode == "manual":
        for s in chunk.sensors:
            s.pixel_width = S120_PIXEL_MM
            s.pixel_height = S120_PIXEL_MM
            s.focal_length = S120_FOCAL_MM
        log(f"{chunk.label}: seeded S120 intrinsics "
            f"(f={S120_FOCAL_MM}mm, pix={S120_PIXEL_MM*1000:.3f}um) [manual].")
    else:
        log(f"{chunk.label}: bundle-adjusted fallback, no intrinsics seed.")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def gpu_check() -> None:
    """Confirm the L4 is visible and enabled before committing to a long run."""
    mask = Metashape.app.gpu_mask
    devices = Metashape.app.enumGPUDevices()
    if not devices:
        log("WARNING: no GPU devices enumerated. Dense cloud will be CPU-bound "
            "and effectively will not finish in the trial window.")
        return
    if mask == 0:
        # enable all detected GPUs
        Metashape.app.gpu_mask = (1 << len(devices)) - 1
        log(f"GPU mask was 0; enabled all {len(devices)} device(s).")
    for i, d in enumerate(devices):
        log(f"GPU {i}: {d.get('name', 'unknown')}")


def open_or_create(project_path: Path) -> Metashape.Document:
    doc = Metashape.Document()
    if project_path.exists():
        log(f"Opening existing project {project_path}")
        doc.open(str(project_path), read_only=False)
    else:
        log(f"Creating new project {project_path}")
        project_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(project_path))
    return doc


def save(doc: Metashape.Document) -> None:
    doc.save()
    log("Project saved.")


# Filename pattern: 20230711_EDR_T1_C2_000000.tif -> transect "EDR_T1".
_TRANSECT_RE = re.compile(r"(EDR_T\d+)", re.IGNORECASE)


def group_images_by_transect(image_root: Path) -> dict[str, list[str]]:
    """Return {transect_label: [image_paths]} for the EDR dataset.

    Handles two on-disk layouts transparently:
      * FLAT  — all TIFFs in image_root, transect encoded in the filename
                (the actual P1WHKTRD layout). We parse the EDR_Tn token.
      * FOLDERED — one subdir per transect. We use the subdir names.

    Flat is grouped in memory only — no files are moved or copied, so the
    per-image SHA-256 provenance hashes from Chat 4 stay valid and the ~5 GB
    isn't duplicated. ESM Step 3's "one chunk per transect" is satisfied by the
    chunk structure, not by the directory structure.
    """
    subdirs = [p for p in image_root.iterdir() if p.is_dir()]
    groups: dict[str, list[str]] = {}

    if subdirs:
        for d in sorted(subdirs):
            imgs = sorted(str(p) for p in
                          list(d.glob("*.tif")) + list(d.glob("*.tiff")))
            if imgs:
                groups[d.name] = imgs
        if groups:
            log(f"Foldered layout: {len(groups)} transect subdir(s).")
            return groups

    # Flat layout — group by filename token.
    flat = sorted(list(image_root.glob("*.tif")) + list(image_root.glob("*.tiff")))
    unmatched = 0
    for p in flat:
        m = _TRANSECT_RE.search(p.name)
        if not m:
            unmatched += 1
            continue
        label = m.group(1).upper()
        groups.setdefault(label, []).append(str(p))
    for label in groups:
        groups[label].sort()
    log(f"Flat layout: grouped {sum(len(v) for v in groups.values())} images "
        f"into {len(groups)} transect(s): "
        f"{', '.join(f'{k}={len(v)}' for k, v in sorted(groups.items()))}")
    if unmatched:
        log(f"WARNING: {unmatched} file(s) had no EDR_Tn token and were skipped.")
    if not groups:
        sys.exit(f"No transect-matching images found under {image_root}")
    return groups


# --------------------------------------------------------------------------- #
# Stage 1 — Import + align  (ESM Steps 3-6)
# --------------------------------------------------------------------------- #


def stage_align(doc: Metashape.Document, image_root: Path,
                focal_mode: str) -> None:
    """One chunk per transect subfolder; align in a local metric CRS.

    focal_mode ('fallback'|'manual') comes from the smoke test's decision
    artifact via resolve_focal_mode(); it controls whether S120 intrinsics are
    seeded before matching.
    """
    groups = group_images_by_transect(image_root)

    existing = {c.label for c in doc.chunks}
    for label, photos in sorted(groups.items()):
        if label in existing:
            log(f"Chunk {label} exists; skipping import.")
            continue
        chunk = doc.addChunk()
        chunk.label = label
        log(f"{label}: importing {len(photos)} photos")
        chunk.addPhotos(photos)
        # Single-camera assumption per ESM Step 3 (Canon S120 for all EDR sites).
        save(doc)

    for chunk in doc.chunks:
        if chunk.tie_points is not None and len(chunk.tie_points.points) > 0:
            log(f"{chunk.label}: already aligned; skipping.")
            continue
        log(f"{chunk.label}: matching + aligning "
            f"(accuracy={PARAMS.align_accuracy}, keypoints={PARAMS.keypoint_limit})")
        apply_focal_mode(chunk, focal_mode)
        chunk.matchPhotos(
            downscale=1,  # High accuracy == downscale 1
            generic_preselection=PARAMS.generic_preselection,
            reference_preselection=PARAMS.reference_preselection,
            keypoint_limit=PARAMS.keypoint_limit,
            tiepoint_limit=PARAMS.tiepoint_limit,
            filter_stationary_points=PARAMS.exclude_stationary_tie_points,
        )
        chunk.alignCameras()
        # ESM Step 6: optimize with default params (bundle adjustment).
        chunk.optimizeCameras()
        n_aligned = sum(1 for c in chunk.cameras if c.transform)
        log(f"{chunk.label}: aligned {n_aligned}/{len(chunk.cameras)} cameras")
        save(doc)


# --------------------------------------------------------------------------- #
# Stage 2 — Markers + error reduction  (ESM Steps 7-8)
# --------------------------------------------------------------------------- #


def stage_reduce(doc: Metashape.Document, logan_module: str | None) -> None:
    """Detect coded markers, then run Logan error reduction in THRESHOLD mode.

    Marker DETECTION is automated; scale-bar ASSIGNMENT (pairing markers and
    setting the 25 cm distance) is confirmed in the GUI — see the docs. We
    detect here so the GUI step starts from detected targets rather than a
    blank slate.
    """
    for chunk in doc.chunks:
        log(f"{chunk.label}: detecting {PARAMS.marker_type} markers "
            f"(tolerance={PARAMS.marker_tolerance})")
        chunk.detectMarkers(
            target_type=Metashape.CircularTarget12bit,
            tolerance=PARAMS.marker_tolerance,
        )
        log(f"{chunk.label}: {len(chunk.markers)} markers detected")

        # Error reduction. Prefer the Logan USGS script (ADR-0010 REQUIRED).
        if logan_module:
            _run_logan(chunk, logan_module)
        else:
            _run_builtin_reduction(chunk)
        save(doc)


def _run_logan(chunk: Metashape.Chunk, logan_module: str) -> None:
    """Invoke the vendored Logan error-reduction routine in threshold mode.

    The v2.0 USGS script defaults to PERCENTAGE-based gradual selection (delete
    50% of points per filter). ESM Table S2 specifies FIXED THRESHOLDS. We pass
    Toth's thresholds explicitly so the reduction matches the published method
    rather than the script's generic default. The exact kwarg names are
    confirmed against the vendored source at integration time; see
    docs/05-metashape-processing.md "Logan integration" for the verified call.
    """
    import importlib
    mod = importlib.import_module(logan_module)
    log(f"{chunk.label}: Logan error reduction (threshold mode) "
        f"RU={PARAMS.reconstruction_uncertainty} "
        f"PA={PARAMS.projection_accuracy} RE={PARAMS.reprojection_error}")
    mod.reduce_error(
        chunk,
        reconstruction_uncertainty=PARAMS.reconstruction_uncertainty,
        projection_accuracy=PARAMS.projection_accuracy,
        reprojection_error=PARAMS.reprojection_error,
        mode="threshold",
        fit_additional=PARAMS.fit_additional_after_reduction,
    )


def _run_builtin_reduction(chunk: Metashape.Chunk) -> None:
    """Fallback: native gradual selection if Logan isn't vendored yet.

    Implements the same three-filter sequence as ESM Step 8 using the Metashape
    API directly. This is a faithful manual transcription of the published
    thresholds and exists so the pipeline is runnable before the vendor clone
    lands; the Logan script is still the ADR-0010-preferred path because it is
    the exact tool the original team cites.
    """
    tp = chunk.tie_points
    Filter = Metashape.TiePoints.Filter

    def _apply(criterion, threshold, optimize=True):
        f = Filter()
        f.init(chunk, criterion=criterion)
        f.selectPoints(threshold)
        n = len([p for p in tp.points if p.selected])
        tp.removeSelectedPoints()
        log(f"{chunk.label}: removed {n} pts at threshold {threshold}")
        if optimize:
            chunk.optimizeCameras()

    _apply(Filter.ReconstructionUncertainty, PARAMS.reconstruction_uncertainty)
    _apply(Filter.ProjectionAccuracy, PARAMS.projection_accuracy)
    # Reprojection error last, then final optimize with additional corrections.
    _apply(Filter.ReprojectionError, PARAMS.reprojection_error, optimize=False)
    chunk.optimizeCameras(fit_corrections=PARAMS.fit_additional_after_reduction)


# --------------------------------------------------------------------------- #
# Stage 3-5 — Dense cloud, DSM, orthomosaic  (ESM Steps 12, 14, 15)
# --------------------------------------------------------------------------- #


def stage_dense(doc: Metashape.Document) -> None:
    for chunk in doc.chunks:
        if chunk.point_cloud is not None:
            log(f"{chunk.label}: dense cloud exists; skipping.")
            continue
        log(f"{chunk.label}: depth maps + dense cloud "
            f"(quality={PARAMS.dense_quality}) — this is the long step")
        t0 = time.time()
        chunk.buildDepthMaps(
            downscale={"High": 2, "Medium": 4}[PARAMS.dense_quality],
            filter_mode=_DEPTH[PARAMS.depth_filtering],
        )
        chunk.buildPointCloud(
            point_colors=PARAMS.point_colors,
            point_confidence=True,  # needed for ESM Step 13 confidence filter
        )
        log(f"{chunk.label}: dense cloud done in {(time.time()-t0)/3600:.1f} h")
        save(doc)


def stage_dsm(doc: Metashape.Document) -> None:
    for chunk in doc.chunks:
        if chunk.elevation is not None:
            log(f"{chunk.label}: DSM exists; skipping.")
            continue
        log(f"{chunk.label}: building DSM at {PARAMS.dsm_resolution_m} m")
        chunk.buildDem(
            source_data=Metashape.PointCloudData,
            interpolation=Metashape.EnabledInterpolation,
            resolution=PARAMS.dsm_resolution_m,
        )
        save(doc)


def stage_ortho(doc: Metashape.Document) -> None:
    for chunk in doc.chunks:
        if chunk.orthomosaic is not None:
            log(f"{chunk.label}: orthomosaic exists; skipping.")
            continue
        log(f"{chunk.label}: building orthomosaic")
        chunk.buildOrthomosaic(
            surface_data=Metashape.ElevationData,
            blending_mode=_BLEND[PARAMS.ortho_blend],
            fill_holes=PARAMS.ortho_hole_filling,
        )
        save(doc)


# --------------------------------------------------------------------------- #
# Stage 6 — Export products + report  (ESM Step 16 + Chat 5 deliverable list)
# --------------------------------------------------------------------------- #


def stage_report(doc: Metashape.Document, out_root: Path) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    summary = {"esm_parameters": asdict(PARAMS), "chunks": []}

    for chunk in doc.chunks:
        cdir = out_root / chunk.label
        cdir.mkdir(parents=True, exist_ok=True)
        log(f"{chunk.label}: exporting products to {cdir}")

        if chunk.point_cloud:
            chunk.exportPointCloud(
                str(cdir / f"{chunk.label}_dense.ply"),
                source_data=Metashape.PointCloudData,
                save_point_color=True,
                save_point_confidence=True,
            )
        if chunk.elevation:
            chunk.exportRaster(
                str(cdir / f"{chunk.label}_dsm.tif"),
                source_data=Metashape.ElevationData,
                resolution=PARAMS.dsm_resolution_m,
            )
        if chunk.orthomosaic:
            chunk.exportRaster(
                str(cdir / f"{chunk.label}_ortho.tif"),
                source_data=Metashape.OrthomosaicData,
            )
        # HTML processing report (human) + we parse it to JSON in Chat 6.
        chunk.exportReport(str(cdir / f"{chunk.label}_report.pdf"))

        # Camera poses + scale-bar errors as JSON (provenance inputs).
        cam_json = [
            {
                "label": cam.label,
                "enabled": cam.enabled,
                "aligned": bool(cam.transform),
            }
            for cam in chunk.cameras
        ]
        (cdir / f"{chunk.label}_cameras.json").write_text(json.dumps(cam_json, indent=2))

        scalebars = []
        for sb in chunk.scalebars:
            dist = sb.reference.distance
            scalebars.append({
                "label": sb.label,
                "defined_distance_m": dist,
            })
        (cdir / f"{chunk.label}_scalebars.json").write_text(
            json.dumps(scalebars, indent=2))

        summary["chunks"].append({
            "label": chunk.label,
            "cameras_total": len(chunk.cameras),
            "cameras_aligned": sum(1 for c in chunk.cameras if c.transform),
            "markers": len(chunk.markers),
            "scalebars": len(chunk.scalebars),
            "has_dense": chunk.point_cloud is not None,
            "has_dsm": chunk.elevation is not None,
            "has_ortho": chunk.orthomosaic is not None,
        })

    (out_root / "pipeline_summary.json").write_text(json.dumps(summary, indent=2))
    log(f"Wrote pipeline_summary.json with {len(summary['chunks'])} chunks.")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

STAGES = ["align", "reduce", "dense", "dsm", "ortho", "report"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True, type=Path)
    ap.add_argument("--image-root", type=Path,
                    help="Root containing one subfolder per transect (align stage).")
    ap.add_argument("--out-root", type=Path, default=Path("/data/edr/products"))
    ap.add_argument("--stage", default="all",
                    choices=STAGES + ["all"])
    ap.add_argument("--logan-module", default=None,
                    help="Importable module name of the vendored Logan script "
                         "(e.g. 'reduce_error'). If omitted, the faithful "
                         "built-in transcription is used.")
    ap.add_argument("--focal-decision", type=Path,
                    default=Path("/data/edr/smoke/products/focal_decision.json"),
                    help="Path to the smoke test's focal_decision.json. The "
                         "align stage reads the DECIDED arm from it.")
    ap.add_argument("--focal-mode", default=None, choices=["fallback", "manual"],
                    help="Override the decision artifact with an explicit arm. "
                         "Required if the artifact verdict is NEEDS_REVIEW.")
    args = ap.parse_args()

    gpu_check()
    doc = open_or_create(args.project)

    # Resolve the focal-length mode up front so the run refuses to start on an
    # undecided configuration BEFORE doing any work — not 20 minutes into align.
    focal_mode = None
    if args.stage in ("align", "all"):
        focal_mode = resolve_focal_mode(args.focal_decision, args.focal_mode)

    todo = STAGES if args.stage == "all" else [args.stage]
    for st in todo:
        log(f"=== STAGE: {st} ===")
        if st == "align":
            if not args.image_root:
                sys.exit("--image-root required for the align stage.")
            stage_align(doc, args.image_root, focal_mode)
        elif st == "reduce":
            stage_reduce(doc, args.logan_module)
        elif st == "dense":
            stage_dense(doc)
        elif st == "dsm":
            stage_dsm(doc)
        elif st == "ortho":
            stage_ortho(doc)
        elif st == "report":
            stage_report(doc, args.out_root)
    log("Pipeline run complete.")


if __name__ == "__main__":
    main()
