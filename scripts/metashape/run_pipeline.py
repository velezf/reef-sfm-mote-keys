#!/usr/bin/env python3
"""
run_pipeline.py — EasternDryRocks SfM pipeline, Toth et al. 2025 ESM Table S2.

Reproduces the Mote/USGS Metashape v2.0 workflow on the EDR transects using the
PUBLISHED parameter values (ESM Table S2), NOT the PIFSC SOP values that the
original project plan cited. This change is binding per ADR-0010; see
docs/05-metashape-processing.md for the full reconciliation and the per-step
fidelity register (faithful / GUI / engineered-departure).

Design goals
------------
* Headless-first. Runs under `metashape.sh -r run_pipeline.py ...` with no GUI.
  Every stage that CAN be automated through the Python API is automated here.
* Resumable via --stage. Each invocation opens the .psx, runs the requested
  stage(s), and saves. Each stage also checks whether its output already exists
  and skips if so, so an overnight run that dies mid-dense can be resumed, and
  the headless→GUI→headless handoff is just "run the align stages, hand off,
  then run the dense stages." We deliberately did NOT add
  --chunk/--stop-after/--start-from: the --stage model already provides
  resumability and the handoff split (ADR-0017).
* Per-transect chunks. One chunk per transect (EDR_T1, EDR_T3, EDR_T8),
  matching ESM Step 3 ("Create chunk from each subfolder"). --transect scopes
  the IMPORT to a single transect (dataset scoping, distinct from stage
  control) so a dev run on EDR_T3 does not sweep in EDR_T1's 2424 images.
* Faithful, not approximate. Where the Logan error-reduction script defaults to
  percentage-based selection, we drive error reduction in THRESHOLD mode with
  Toth's values. Logan is preferred (ADR-0010); the built-in transcription is a
  hedge and, when used, is recorded as a per-run documented departure.
* Robust + reproducible. Every stage emits sanity checks that SURFACE (loud
  ALARM lines, and a hard stop on critical ones unless --ignore-sanity) rather
  than silently passing, and persists its stats into the chunk's metadata so
  the report stage can assemble one provenance manifest (pipeline_summary.json)
  that Chat 6 parses.

Stages (run in this order for --stage all)
------------------------------------------
    import  — addPhotos, one chunk per transect (ESM Step 3) + image hashes
    step4   — ESM Step 4 image-quality filter: analyzeImages + disable < 0.50
              BEFORE matching (ADR-0017; ~60% smoke alignment-loss lesson)
    align   — match + align + optimize (ESM Steps 5-6)
    reduce  — detect markers (ESM Step 7, detection only) + error reduction
              (ESM Step 8; Logan preferred, built-in fallback)
    dense   — depth maps + dense point cloud (ESM Step 12)
    filter  — ESM Step 13 confidence noise filter (ADR-0015), sequenced
              BETWEEN dense and dsm so the DSM is NEVER built on an
              unfiltered cloud
    dsm     — build DSM at 1 cm (ESM Step 14) — NO smoke region-clip workaround
    ortho   — build orthomosaic (ESM Step 15)
    report  — export products + assemble pipeline_summary.json (ESM Step 16)

Usage
-----
    # T3 dev run, scoped to the 522 EDR_T3 images, headless align portion:
    metashape.sh -platform offscreen -r run_pipeline.py \\
        --project /data/edr_work/edr_t3.psx \\
        --image-root /data/raw/P1WHKTRD/EasternDryRocks \\
        --transect EDR_T3 --focal-mode fallback --stage import
    # ... then --stage step4, --stage align, --stage reduce, hand off to GUI,
    # ... then --stage dense, filter, dsm, ortho, report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

# Make sibling modules (segment_pointcloud.py) importable regardless of the cwd
# metashape.sh -r is launched from. The filter stage imports the ESM Step 13
# routine from segment_pointcloud so the cleanPointCloud+compactPoints idiom has
# a single source of truth.
sys.path.insert(0, str(Path(__file__).resolve().parent))

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
    # Step 4 — Image quality filter (ADR-0017)
    image_quality_threshold: float = 0.50   # Agisoft's own "blurred" cutoff

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

    # Step 13 — Confidence noise filter (ADR-0015)
    noise_confidence_threshold: int = 2     # remove points with confidence < 2

    # Step 14 — DSM
    # 1 cm, NOT 1 mm. ESM Step 14 is silent on the number ("default"); Toth main
    # text and ADR-0010 both say 1 cm; Chat 6 reconciliation needs 1 cm; and
    # 1 cm is ~100x fewer raster cells than 1 mm, materially reducing the
    # buildDem OOM risk that ADR-0016 flags. (ADR-0017 corrects the 1 mm
    # misattribution to ESM Table S2.)
    dsm_resolution_m: float = 0.01

    # Step 15 — Orthomosaic
    ortho_blend: str = "Mosaic"
    ortho_hole_filling: bool = True


PARAMS = ESMParameters()

# Sanity-check thresholds — these SURFACE problems; they do not tune the run.
ALARM_MAX_DISABLED = 200          # of ~522: more than this disabled in Step 4 is suspect
ALARM_MIN_ALIGN_RATE = 0.70       # < 70% aligned of enabled => something beyond Step 4
ALARM_MAX_DSM_CELLS = 100_000_000  # a 10x1 m transect at 1 cm is ~10^5 cells; 10^8 is wrong

# Map our string names to Metashape enums in one place so the dataclass stays
# pure data (and serialisable straight into the provenance manifest).
#
# Note: Metashape 2.x does NOT expose Accuracy/Quality enums (HighAccuracy etc.
# were removed); accuracy and dense-cloud quality are both controlled by the
# `downscale` argument (align downscale=1 == High; dense downscale=2 == High).
# The stages pass those downscale literals directly, so there is no _ACCURACY /
# _QUALITY map. Only depth-filtering and blending are still enum-driven.
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


class PipelineSanityError(RuntimeError):
    """Raised when a critical sanity check fails (unless --ignore-sanity)."""


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


def alarm(msg: str, *, critical: bool, ignore: bool) -> None:
    """Surface a sanity-check failure. Loud always; hard stop if critical.

    critical + not ignore  -> raise PipelineSanityError (stop the run for review)
    otherwise              -> print a loud ALARM line and continue
    """
    line = f"*** ALARM: {msg} ***"
    print(line, flush=True)
    if critical and not ignore:
        raise PipelineSanityError(msg)
    if critical:
        log("(--ignore-sanity set: continuing past a CRITICAL alarm)")


def _meta_set(chunk: "Metashape.Chunk", key: str, obj) -> None:
    """Persist a JSON-able stats blob into chunk metadata (survives in the .psx
    across --stage invocations; the report stage reads these back)."""
    chunk.meta[key] = json.dumps(obj)


def _meta_get(chunk: "Metashape.Chunk", key: str, default=None):
    try:
        raw = chunk.meta[key]
    except (KeyError, RuntimeError):
        return default
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def _reprojection_rms(chunk: "Metashape.Chunk") -> tuple[float | None, int]:
    """RMS of per-tie-point reprojection-error filter values (Metashape filter
    units, NOT pixels — see ADR-0012). Valid for before/after comparison within
    a run; the pixel-calibrated number for the Toth envelope comes from the
    report PDF after scale bars. Mirrors smoke_test.py._reprojection_rms."""
    tp = chunk.tie_points
    if tp is None or not tp.points:
        return None, 0
    f = Metashape.TiePoints.Filter()
    f.init(chunk, criterion=Metashape.TiePoints.Filter.ReprojectionError)
    errs = list(f.values)
    if not errs:
        return None, 0
    rms = (sum(e * e for e in errs) / len(errs)) ** 0.5
    return rms, len(errs)


def gpu_check() -> list[str]:
    """Confirm the L4 is visible and enabled before committing to a long run.
    Returns the list of enumerated device names for the provenance manifest."""
    mask = Metashape.app.gpu_mask
    devices = Metashape.app.enumGPUDevices()
    names = [d.get("name", "unknown") for d in devices]
    if not devices:
        log("WARNING: no GPU devices enumerated. Dense cloud will be CPU-bound "
            "and effectively will not finish in the trial window.")
        return names
    if mask == 0:
        Metashape.app.gpu_mask = (1 << len(devices)) - 1
        log(f"GPU mask was 0; enabled all {len(devices)} device(s).")
    for i, name in enumerate(names):
        log(f"GPU {i}: {name}")
    return names


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


def group_images_by_transect(image_root: Path,
                             transect: str | None) -> dict[str, list[str]]:
    """Return {transect_label: [image_paths]} for the EDR dataset.

    Handles two on-disk layouts transparently:
      * FLAT  — all TIFFs in image_root, transect encoded in the filename
                (the actual P1WHKTRD layout). We parse the EDR_Tn token.
      * FOLDERED — one subdir per transect. We use the subdir names.

    If `transect` is given (e.g. "EDR_T3"), only that transect is returned —
    dataset scoping so a dev run does not import every transect. Flat is grouped
    in memory only — no files are moved or copied, so the per-image provenance
    from Chat 4 stays valid and the ~5 GB isn't duplicated.
    """
    want = transect.upper() if transect else None
    subdirs = [p for p in image_root.iterdir() if p.is_dir()]
    groups: dict[str, list[str]] = {}

    if subdirs:
        for d in sorted(subdirs):
            if want and d.name.upper() != want:
                continue
            imgs = sorted(str(p) for p in
                          list(d.glob("*.tif")) + list(d.glob("*.tiff")))
            if imgs:
                groups[d.name] = imgs
        if groups:
            log(f"Foldered layout: {len(groups)} transect subdir(s)"
                f"{' (filtered to ' + want + ')' if want else ''}.")
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
        if want and label != want:
            continue
        groups.setdefault(label, []).append(str(p))
    for label in groups:
        groups[label].sort()
    log(f"Flat layout: grouped {sum(len(v) for v in groups.values())} images "
        f"into {len(groups)} transect(s)"
        f"{' (filtered to ' + want + ')' if want else ''}: "
        f"{', '.join(f'{k}={len(v)}' for k, v in sorted(groups.items()))}")
    if unmatched and not want:
        log(f"WARNING: {unmatched} file(s) had no EDR_Tn token and were skipped.")
    if not groups:
        sys.exit(f"No transect-matching images found under {image_root}"
                 f"{' for transect ' + want if want else ''}")
    return groups


def _sha256(path: str, _buf: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(_buf), b""):
            h.update(block)
    return h.hexdigest()


def _hash_images(label: str, photos: list[str], project: Path) -> dict:
    """Compute SHA-256 for each imported image and write a sidecar manifest next
    to the project. Returns {count, aggregate_sha256, manifest_path}. The
    aggregate is the sha256 over the sorted 'name:sha' lines — a single value
    that pins the exact input set for the provenance manifest. Done once at
    import (the stage is skipped on resume), so the cost is paid once.
    """
    log(f"{label}: hashing {len(photos)} input images (SHA-256)...")
    t0 = time.time()
    per_image = {}
    for p in photos:
        per_image[Path(p).name] = _sha256(p)
    lines = "\n".join(f"{n}:{per_image[n]}" for n in sorted(per_image))
    aggregate = hashlib.sha256(lines.encode()).hexdigest()
    manifest_path = project.parent / f"{label}_image_hashes.json"
    manifest_path.write_text(json.dumps(
        {"transect": label, "count": len(per_image),
         "aggregate_sha256": aggregate, "images": per_image}, indent=2))
    log(f"{label}: hashed {len(per_image)} images in "
        f"{time.time()-t0:.0f}s; aggregate {aggregate[:12]}...")
    return {"count": len(per_image), "aggregate_sha256": aggregate,
            "manifest_path": str(manifest_path)}


# --------------------------------------------------------------------------- #
# Stage: import  (ESM Step 3) — create one chunk per transect, addPhotos, hash
# --------------------------------------------------------------------------- #


def stage_import(doc: Metashape.Document, image_root: Path,
                 transect: str | None, project: Path) -> None:
    groups = group_images_by_transect(image_root, transect)
    existing = {c.label for c in doc.chunks}
    for label, photos in sorted(groups.items()):
        if label in existing:
            log(f"Chunk {label} exists; skipping import.")
            continue
        chunk = doc.addChunk()
        chunk.label = label
        log(f"{label}: importing {len(photos)} photos")
        t0 = time.time()
        chunk.addPhotos(photos)
        # Single-camera assumption per ESM Step 3 (Canon S120 for all EDR sites).
        hashes = _hash_images(label, photos, project)
        _meta_set(chunk, "esm.import", {
            "images_imported": len(photos),
            "image_hashes": hashes,
            "seconds": round(time.time() - t0, 1),
        })
        save(doc)


# --------------------------------------------------------------------------- #
# Stage: step4  (ESM Step 4) — image-quality filter BEFORE matching (ADR-0017)
# --------------------------------------------------------------------------- #


def filter_low_quality_images(chunk: "Metashape.Chunk",
                              quality_threshold: float = 0.50) -> dict:
    """ESM Step 4: estimate image quality and disable blurred frames.

    Runs chunk.analyzeImages() (stores Image/Quality per camera), parses the
    quality, and disables cameras below `quality_threshold` so they don't enter
    matching. Agisoft's own guidance is that quality < 0.5 is "blurred" — the
    0.50 threshold is the vendor recommendation, pinned to ESM (not stricter).

    Cameras with no quality metadata are left enabled and excluded from the
    disabled tally (we don't disable on missing data). Returns a stats dict.
    """
    regular = [c for c in chunk.cameras
               if getattr(c, "photo", None) is not None]
    log(f"{chunk.label}: ESM Step 4 — analyzeImages on {len(regular)} cameras")
    chunk.analyzeImages(regular)

    qualities: list[float] = []
    disabled = 0
    no_meta = 0
    for cam in regular:
        raw = cam.meta["Image/Quality"] if "Image/Quality" in cam.meta else None
        if not raw:
            no_meta += 1
            continue
        try:
            q = float(raw)
        except (TypeError, ValueError):
            no_meta += 1
            continue
        qualities.append(q)
        if q < quality_threshold:
            cam.enabled = False
            disabled += 1

    stats = {
        "analyzed": len(regular),
        "with_quality": len(qualities),
        "no_metadata": no_meta,
        "disabled": disabled,
        "threshold": quality_threshold,
        "min_quality": round(min(qualities), 4) if qualities else None,
        "max_quality": round(max(qualities), 4) if qualities else None,
        "median_quality": round(statistics.median(qualities), 4) if qualities else None,
    }
    return stats


def stage_step4(doc: Metashape.Document, ignore_sanity: bool) -> None:
    for chunk in doc.chunks:
        if _meta_get(chunk, "esm.step4") is not None:
            log(f"{chunk.label}: ESM Step 4 already done; skipping.")
            continue
        t0 = time.time()
        stats = filter_low_quality_images(chunk, PARAMS.image_quality_threshold)
        stats["seconds"] = round(time.time() - t0, 1)
        _meta_set(chunk, "esm.step4", stats)
        log(f"{chunk.label}: ESM Step 4 analyzed={stats['analyzed']} "
            f"disabled={stats['disabled']} (threshold={stats['threshold']:.2f}, "
            f"median={stats['median_quality']}, "
            f"min={stats['min_quality']}, max={stats['max_quality']})")
        if stats["disabled"] > ALARM_MAX_DISABLED:
            alarm(f"{chunk.label}: ESM Step 4 disabled {stats['disabled']} "
                  f"cameras (> {ALARM_MAX_DISABLED}). Threshold or input quality "
                  f"is suspect — review before aligning.",
                  critical=True, ignore=ignore_sanity)
        save(doc)


# --------------------------------------------------------------------------- #
# Stage: align  (ESM Steps 5-6) — match + align + optimize
# --------------------------------------------------------------------------- #


def stage_align(doc: Metashape.Document, focal_mode: str,
                ignore_sanity: bool) -> None:
    for chunk in doc.chunks:
        if chunk.tie_points is not None and len(chunk.tie_points.points) > 0:
            log(f"{chunk.label}: already aligned; skipping.")
            continue
        n_enabled = sum(1 for c in chunk.cameras if c.enabled)
        log(f"{chunk.label}: matching + aligning {n_enabled} enabled cameras "
            f"(accuracy={PARAMS.align_accuracy}, keypoints={PARAMS.keypoint_limit})")
        apply_focal_mode(chunk, focal_mode)
        t0 = time.time()
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
        rate = n_aligned / n_enabled if n_enabled else 0.0
        rms, n_resid = _reprojection_rms(chunk)
        stats = {
            "cameras_total": len(chunk.cameras),
            "cameras_enabled": n_enabled,
            "cameras_aligned": n_aligned,
            "alignment_rate": round(rate, 4),
            "focal_mode": focal_mode,
            "tie_points": len(chunk.tie_points.points) if chunk.tie_points else 0,
            "reproj_rms_filter_units": round(rms, 4) if rms is not None else None,
            "seconds": round(time.time() - t0, 1),
        }
        _meta_set(chunk, "esm.align", stats)
        log(f"{chunk.label}: aligned {n_aligned}/{n_enabled} enabled "
            f"({rate*100:.1f}%), tie points {stats['tie_points']:,}, "
            f"RMS(filter units)={stats['reproj_rms_filter_units']}")
        save(doc)
        if rate < ALARM_MIN_ALIGN_RATE:
            alarm(f"{chunk.label}: alignment rate {rate*100:.1f}% "
                  f"< {ALARM_MIN_ALIGN_RATE*100:.0f}%. Something is wrong beyond "
                  f"the Step 4 quality filter — review before dense.",
                  critical=True, ignore=ignore_sanity)


# --------------------------------------------------------------------------- #
# Stage: reduce  (ESM Steps 7-8) — marker detection + error reduction
# --------------------------------------------------------------------------- #


def stage_reduce(doc: Metashape.Document, logan_module: str | None,
                 ignore_sanity: bool) -> None:
    """Detect coded markers (detection only — scale-bar assignment is GUI), then
    run error reduction. Logan USGS script preferred (ADR-0010); the built-in
    faithful transcription is the fallback and, when used, is recorded as a
    per-run documented departure (NOT silently preferred)."""
    for chunk in doc.chunks:
        if _meta_get(chunk, "esm.reduce") is not None:
            log(f"{chunk.label}: error reduction already done; skipping.")
            continue
        t0 = time.time()
        log(f"{chunk.label}: detecting {PARAMS.marker_type} markers "
            f"(tolerance={PARAMS.marker_tolerance})")
        chunk.detectMarkers(
            target_type=Metashape.CircularTarget12bit,
            tolerance=PARAMS.marker_tolerance,
        )
        n_markers = len(chunk.markers)
        log(f"{chunk.label}: {n_markers} markers detected")

        rms_pre, _ = _reprojection_rms(chunk)

        # Error reduction. Prefer the Logan USGS script (ADR-0010 REQUIRED);
        # fall back to the faithful built-in transcription if not vendored.
        if logan_module:
            path = _run_logan(chunk, logan_module)
        else:
            log(f"{chunk.label}: Logan module not provided — using the built-in "
                f"faithful transcription. This is a per-run DOCUMENTED departure "
                f"from ADR-0010's preferred Logan path (see docs/05).")
            _run_builtin_reduction(chunk)
            path = "builtin_fallback"

        rms_post, _ = _reprojection_rms(chunk)
        stats = {
            "reduction_path": path,
            "markers_detected": n_markers,
            "reproj_rms_pre_filter_units": round(rms_pre, 4) if rms_pre is not None else None,
            "reproj_rms_post_filter_units": round(rms_post, 4) if rms_post is not None else None,
            "thresholds": {
                "reconstruction_uncertainty": PARAMS.reconstruction_uncertainty,
                "projection_accuracy": PARAMS.projection_accuracy,
                "reprojection_error": PARAMS.reprojection_error,
            },
            "seconds": round(time.time() - t0, 1),
        }
        _meta_set(chunk, "esm.reduce", stats)
        log(f"{chunk.label}: error reduction via '{path}'; "
            f"RMS(filter units) {stats['reproj_rms_pre_filter_units']} -> "
            f"{stats['reproj_rms_post_filter_units']}; markers={n_markers}")
        save(doc)


def _run_logan(chunk: Metashape.Chunk, logan_module: str) -> str:
    """Invoke the vendored Logan error-reduction routine in threshold mode.

    The v2.0 USGS script defaults to PERCENTAGE-based gradual selection. ESM
    Table S2 specifies FIXED THRESHOLDS; we pass Toth's thresholds explicitly so
    the reduction matches the published method. Returns the path label.
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
    return f"logan:{logan_module}"


def _run_builtin_reduction(chunk: Metashape.Chunk) -> None:
    """Fallback: native gradual selection if Logan isn't vendored yet.

    Faithful manual transcription of ESM Step 8's three filters at Toth's
    thresholds, with camera optimization between filters and a final optimize
    with additional corrections.
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
# Stage: dense  (ESM Step 12) — depth maps + dense point cloud
# --------------------------------------------------------------------------- #


def _log_chunk_scale(chunk: "Metashape.Chunk", where: str) -> dict:
    """Log and return transform.scale + region extent. This is the ADR-0016
    evidence: on a scaled chunk these are metric and tractable; if scale is
    None / region is huge, the chunk was not scaled (GUI handoff incomplete)."""
    ts = chunk.transform.scale if chunk.transform else None
    region = chunk.region
    size = [region.size.x, region.size.y, region.size.z]
    center = [region.center.x, region.center.y, region.center.z]
    log(f"{where}: transform.scale={ts} region.size="
        f"({size[0]:.4g}, {size[1]:.4g}, {size[2]:.4g}) "
        f"center=({center[0]:.4g}, {center[1]:.4g}, {center[2]:.4g})")
    return {"transform_scale": ts, "region_size": size, "region_center": center}


def stage_dense(doc: Metashape.Document, ignore_sanity: bool) -> None:
    for chunk in doc.chunks:
        if chunk.point_cloud is not None:
            log(f"{chunk.label}: dense cloud exists; skipping.")
            continue
        scale_info = _log_chunk_scale(chunk, f"{chunk.label} pre-dense")
        if scale_info["transform_scale"] is None:
            alarm(f"{chunk.label}: transform.scale is None at dense stage — the "
                  f"chunk is NOT metrically scaled. Dense/DSM must run AFTER the "
                  f"GUI handoff (scale bars + Jenkins coord frame). See ADR-0016.",
                  critical=True, ignore=ignore_sanity)
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
        n_points = chunk.point_cloud.point_count if chunk.point_cloud else 0
        hours = (time.time() - t0) / 3600
        _meta_set(chunk, "esm.dense", {
            "point_count": n_points,
            "quality": PARAMS.dense_quality,
            "depth_filter": PARAMS.depth_filtering,
            "hours": round(hours, 3),
            **scale_info,
        })
        log(f"{chunk.label}: dense cloud {n_points:,} points in {hours:.1f} h")
        save(doc)


# --------------------------------------------------------------------------- #
# Stage: filter  (ESM Step 13) — confidence noise filter, BEFORE buildDem
# --------------------------------------------------------------------------- #


def stage_filter(doc: Metashape.Document, noise_confidence: float,
                 ignore_sanity: bool) -> None:
    """ESM Step 13 confidence noise filter (ADR-0015), sequenced BETWEEN dense
    and dsm. The DSM must never be built on an unfiltered cloud. Delegates to
    segment_pointcloud.assign_noise_by_confidence (single source of the
    cleanPointCloud + compactPoints idiom; ADR-0015's filter, now wired into the
    production driver — previously it lived only in smoke_test.py)."""
    from segment_pointcloud import assign_noise_by_confidence

    for chunk in doc.chunks:
        if chunk.point_cloud is None:
            alarm(f"{chunk.label}: no dense cloud — cannot run ESM Step 13. "
                  f"Run the dense stage first.",
                  critical=True, ignore=ignore_sanity)
            continue
        if _meta_get(chunk, "esm.filter") is not None:
            log(f"{chunk.label}: ESM Step 13 filter already done; skipping.")
            continue
        t0 = time.time()
        n_before = chunk.point_cloud.point_count
        n_after = assign_noise_by_confidence(chunk, noise_confidence)
        removed = n_before - n_after
        ratio = removed / n_before if n_before else 0.0
        _meta_set(chunk, "esm.filter", {
            "threshold": noise_confidence,
            "points_before": n_before,
            "points_after": n_after,
            "removed": removed,
            "removed_fraction": round(ratio, 4),
            "seconds": round(time.time() - t0, 1),
        })
        log(f"{chunk.label}: ESM Step 13 {n_before:,} -> {n_after:,} "
            f"({removed:,} removed, {ratio*100:.1f}%). "
            f"Smoke on EDR_T8 saw ~24% (30.9M->23.5M).")
        save(doc)


# --------------------------------------------------------------------------- #
# Stage: dsm  (ESM Step 14) — DSM at 1 cm; NO smoke region-clip workaround
# --------------------------------------------------------------------------- #


def stage_dsm(doc: Metashape.Document, ignore_sanity: bool) -> None:
    for chunk in doc.chunks:
        if chunk.elevation is not None:
            log(f"{chunk.label}: DSM exists; skipping.")
            continue
        scale_info = _log_chunk_scale(chunk, f"{chunk.label} pre-buildDem")
        pc = chunk.point_cloud
        if pc is not None:
            log(f"{chunk.label}: dense point_count={pc.point_count:,} "
                f"before buildDem")
        log(f"{chunk.label}: building DSM at {PARAMS.dsm_resolution_m} m "
            f"(NO region clip — ADR-0016 test: does a scaled chunk + 1 cm "
            f"build the DSM WITHOUT the smoke workaround?)")
        t0 = time.time()
        try:
            # No region= argument: let buildDem auto-infer extent. This is the
            # faithful ESM Step 14 call and the explicit ADR-0016 test. We do
            # NOT silently re-apply the smoke's BBox region clip.
            chunk.buildDem(
                source_data=Metashape.PointCloudData,
                interpolation=Metashape.EnabledInterpolation,
                resolution=PARAMS.dsm_resolution_m,
            )
        except (MemoryError, RuntimeError) as exc:
            alarm(f"{chunk.label}: buildDem FAILED on the scaled chunk WITHOUT "
                  f"the region clip ({type(exc).__name__}: {exc}). This is the "
                  f"ADR-0016 failure case (b) — do NOT re-apply the smoke "
                  f"workaround silently. Capture the log and open ADR-0018.",
                  critical=True, ignore=ignore_sanity)
            continue

        dem = chunk.elevation
        dims = [getattr(dem, "width", None), getattr(dem, "height", None)]
        cells = (dims[0] or 0) * (dims[1] or 0)
        stats = {
            "resolution_m": PARAMS.dsm_resolution_m,
            "width": dims[0],
            "height": dims[1],
            "cells": cells,
            "region_clip_workaround_applied": False,
            "seconds": round(time.time() - t0, 1),
            **scale_info,
        }
        _meta_set(chunk, "esm.dsm", stats)
        log(f"{chunk.label}: DSM built {dims[0]}x{dims[1]} = {cells:,} cells "
            f"at {PARAMS.dsm_resolution_m} m (ADR-0016 case (a): succeeded "
            f"without workaround)")
        if cells == 0:
            alarm(f"{chunk.label}: DSM has 0 cells — all-NoData or degenerate. "
                  f"ADR-0016 case (c). Surface and investigate.",
                  critical=True, ignore=ignore_sanity)
        elif cells > ALARM_MAX_DSM_CELLS:
            alarm(f"{chunk.label}: DSM is {cells:,} cells (> "
                  f"{ALARM_MAX_DSM_CELLS:,}). Extent looks wrong for a ~10x1 m "
                  f"transect at 1 cm. ADR-0016 case (c).",
                  critical=True, ignore=ignore_sanity)
        save(doc)


# --------------------------------------------------------------------------- #
# Stage: ortho  (ESM Step 15)
# --------------------------------------------------------------------------- #


def stage_ortho(doc: Metashape.Document, ignore_sanity: bool) -> None:
    for chunk in doc.chunks:
        if chunk.orthomosaic is not None:
            log(f"{chunk.label}: orthomosaic exists; skipping.")
            continue
        if chunk.elevation is None:
            alarm(f"{chunk.label}: no DSM — cannot build orthomosaic on the "
                  f"elevation surface. Run the dsm stage first.",
                  critical=True, ignore=ignore_sanity)
            continue
        log(f"{chunk.label}: building orthomosaic")
        t0 = time.time()
        chunk.buildOrthomosaic(
            surface_data=Metashape.ElevationData,
            blending_mode=_BLEND[PARAMS.ortho_blend],
            fill_holes=PARAMS.ortho_hole_filling,
        )
        ortho = chunk.orthomosaic
        _meta_set(chunk, "esm.ortho", {
            "width": getattr(ortho, "width", None),
            "height": getattr(ortho, "height", None),
            "blend": PARAMS.ortho_blend,
            "seconds": round(time.time() - t0, 1),
        })
        log(f"{chunk.label}: orthomosaic "
            f"{getattr(ortho, 'width', '?')}x{getattr(ortho, 'height', '?')}")
        save(doc)


# --------------------------------------------------------------------------- #
# Stage: report  (ESM Step 16) — export products + assemble provenance manifest
# --------------------------------------------------------------------------- #


def stage_report(doc: Metashape.Document, out_root: Path,
                 gpu_names: list[str]) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    summary = {
        "metashape_version": Metashape.app.version,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "gpu_devices": gpu_names,
        "esm_parameters": asdict(PARAMS),
        "dsm_resolution_note": (
            "1 cm per Toth main text / ADR-0010 / ADR-0017. ESM Step 14 is "
            "silent on the number; the '1 mm' figure is PIFSC, not ESM."),
        "chunks": [],
    }

    for chunk in doc.chunks:
        cdir = out_root / chunk.label
        cdir.mkdir(parents=True, exist_ok=True)
        log(f"{chunk.label}: exporting products to {cdir}")
        products = {}

        # Sparse (tie-point) cloud — ESM Step 16 deliverable list.
        if chunk.tie_points is not None and chunk.tie_points.points:
            sparse = cdir / "sparse.ply"
            chunk.exportPointCloud(
                str(sparse),
                source_data=Metashape.TiePointsData,
            )
            products["sparse_ply"] = _file_stat(sparse)

        # Dense cloud, post-confidence-filter.
        if chunk.point_cloud:
            dense = cdir / "dense.ply"
            chunk.exportPointCloud(
                str(dense),
                source_data=Metashape.PointCloudData,
                save_point_color=True,
                save_point_confidence=True,
            )
            products["dense_ply"] = _file_stat(dense)
        if chunk.elevation:
            dsm = cdir / "dsm.tif"
            chunk.exportRaster(
                str(dsm),
                source_data=Metashape.ElevationData,
                resolution=PARAMS.dsm_resolution_m,
            )
            products["dsm_tif"] = _file_stat(dsm)
        if chunk.orthomosaic:
            ortho = cdir / "ortho.tif"
            chunk.exportRaster(
                str(ortho),
                source_data=Metashape.OrthomosaicData,
            )
            products["ortho_tif"] = _file_stat(ortho)
        # HTML/PDF processing report (human-readable cross-check).
        report = cdir / "processing_report.pdf"
        chunk.exportReport(str(report))
        products["report_pdf"] = _file_stat(report)

        # Camera poses + scale-bar errors as JSON (provenance inputs).
        cam_json = [
            {"label": cam.label, "enabled": cam.enabled,
             "aligned": bool(cam.transform)}
            for cam in chunk.cameras
        ]
        cameras_path = cdir / "cameras.json"
        cameras_path.write_text(json.dumps(cam_json, indent=2))
        products["cameras_json"] = _file_stat(cameras_path)

        scalebars = []
        for sb in chunk.scalebars:
            entry = {"label": sb.label,
                     "defined_distance_m": sb.reference.distance,
                     "accuracy_m": getattr(sb.reference, "accuracy", None)}
            # The measured-vs-defined residual is computed by Metashape after
            # optimization and reported in processing_report.pdf; Chat 6 reads
            # it from there. Here we record the operator-defined inputs.
            scalebars.append(entry)
        scalebars_path = cdir / "scalebars.json"
        scalebars_path.write_text(json.dumps(scalebars, indent=2))
        products["scalebars_json"] = _file_stat(scalebars_path)

        n_enabled = sum(1 for c in chunk.cameras if c.enabled)
        n_aligned = sum(1 for c in chunk.cameras if c.transform)
        ts = chunk.transform.scale if chunk.transform else None
        summary["chunks"].append({
            "label": chunk.label,
            "cameras_total": len(chunk.cameras),
            "cameras_enabled": n_enabled,
            "cameras_aligned": n_aligned,
            "alignment_rate": round(n_aligned / n_enabled, 4) if n_enabled else None,
            "markers": len(chunk.markers),
            "scalebars": len(chunk.scalebars),
            "transform_scale": ts,
            "tie_points": len(chunk.tie_points.points) if chunk.tie_points else 0,
            "dense_point_count": chunk.point_cloud.point_count if chunk.point_cloud else None,
            "has_dense": chunk.point_cloud is not None,
            "has_dsm": chunk.elevation is not None,
            "has_ortho": chunk.orthomosaic is not None,
            # Per-stage stats persisted in chunk.meta across --stage invocations:
            "stage_import": _meta_get(chunk, "esm.import"),
            "stage_step4": _meta_get(chunk, "esm.step4"),
            "stage_align": _meta_get(chunk, "esm.align"),
            "stage_reduce": _meta_get(chunk, "esm.reduce"),
            "stage_dense": _meta_get(chunk, "esm.dense"),
            "stage_filter": _meta_get(chunk, "esm.filter"),
            "stage_dsm": _meta_get(chunk, "esm.dsm"),
            "stage_ortho": _meta_get(chunk, "esm.ortho"),
            "products": products,
        })

    (out_root / "pipeline_summary.json").write_text(json.dumps(summary, indent=2))
    log(f"Wrote pipeline_summary.json with {len(summary['chunks'])} chunk(s).")


def _file_stat(path: Path) -> dict:
    try:
        return {"path": str(path), "bytes": path.stat().st_size}
    except OSError:
        return {"path": str(path), "bytes": None}


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

STAGES = ["import", "step4", "align", "reduce", "dense", "filter",
          "dsm", "ortho", "report"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True, type=Path)
    ap.add_argument("--image-root", type=Path,
                    help="Root containing the transect images (import stage).")
    ap.add_argument("--transect", default=None,
                    help="Scope the IMPORT to one transect token (e.g. EDR_T3). "
                         "Dataset scoping, NOT stage control — every stage then "
                         "operates on whatever chunks the project contains.")
    ap.add_argument("--out-root", type=Path,
                    default=Path("/data/edr_work/products"))
    ap.add_argument("--stage", default="all", choices=STAGES + ["all"])
    ap.add_argument("--noise-confidence", type=float,
                    default=float(PARAMS.noise_confidence_threshold),
                    help="ESM Step 13 confidence threshold (filter stage).")
    ap.add_argument("--logan-module", default=None,
                    help="Importable module name of the vendored Logan script. "
                         "If omitted, the built-in transcription is used and "
                         "recorded as a per-run documented departure.")
    ap.add_argument("--focal-decision", type=Path,
                    default=Path("/data/edr_work/smoke/products/focal_decision.json"),
                    help="Path to the smoke test's focal_decision.json. The "
                         "align stage reads the DECIDED arm from it.")
    ap.add_argument("--focal-mode", default=None, choices=["fallback", "manual"],
                    help="Override the decision artifact with an explicit arm.")
    ap.add_argument("--ignore-sanity", action="store_true",
                    help="Downgrade critical sanity alarms from hard-stop to "
                         "loud-warn. Off by default: the pipeline stops on a "
                         "critical alarm so a dev run surfaces and iterates.")
    args = ap.parse_args()

    gpu_names = gpu_check()
    doc = open_or_create(args.project)

    # Resolve the focal-length mode up front so the run refuses to start on an
    # undecided configuration BEFORE doing any align work.
    focal_mode = None
    if args.stage in ("align", "all"):
        focal_mode = resolve_focal_mode(args.focal_decision, args.focal_mode)

    todo = STAGES if args.stage == "all" else [args.stage]
    for st in todo:
        log(f"=== STAGE: {st} ===")
        if st == "import":
            if not args.image_root:
                sys.exit("--image-root required for the import stage.")
            stage_import(doc, args.image_root, args.transect, args.project)
        elif st == "step4":
            stage_step4(doc, args.ignore_sanity)
        elif st == "align":
            stage_align(doc, focal_mode, args.ignore_sanity)
        elif st == "reduce":
            stage_reduce(doc, args.logan_module, args.ignore_sanity)
        elif st == "dense":
            stage_dense(doc, args.ignore_sanity)
        elif st == "filter":
            stage_filter(doc, args.noise_confidence, args.ignore_sanity)
        elif st == "dsm":
            stage_dsm(doc, args.ignore_sanity)
        elif st == "ortho":
            stage_ortho(doc, args.ignore_sanity)
        elif st == "report":
            stage_report(doc, args.out_root, gpu_names)
    log("Pipeline run complete.")


if __name__ == "__main__":
    main()
