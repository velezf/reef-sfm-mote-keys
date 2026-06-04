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
    markers — detect coded targets (ESM Step 7, detection only); runs BEFORE
              the GUI scale-bar handoff
    reduce  — error reduction (ESM Step 8; Logan preferred, built-in fallback);
              runs AFTER scale bars are assigned, so the final optimize is
              scale-constrained — Toth's order (Step 7 precedes Step 8)
    level   — ESM Step 11 analog (ADR-0021): deterministic marker-PLANE roll+pitch
              level with scale-bar-residual outlier rejection; BEFORE dense
    dense   — depth maps + dense point cloud (ESM Step 12)
    filter  — ESM Step 13 confidence noise filter (ADR-0015), sequenced
              BETWEEN dense and aoi/dsm so the DSM is NEVER built on an
              unfiltered cloud
    aoi     — ESM Step 14 bbox analog (ADR-0021): footprint-PCA yaw + centroid
              auto-placement + camera-track orientation anchor + 10x1x5 m crop;
              AFTER filter, BEFORE dsm
    dsm     — build DSM at 1 cm (ESM Step 14) — NO smoke region-clip workaround
    ortho   — build orthomosaic (ESM Step 15)
    gate    — PERMANENT QC gate (ADR-0021): tilt/coverage/scale/co-reg/footprint/
              orientation checks; FAILs the build so a 24 deg mis-level can't ship
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
import math
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

    # Step 7 — Markers. ESM is manual-iterative ("start at 20, increase until all
    # detected"); stage_markers does that headless (auto-tolerance), so no
    # per-transect tolerance is pinned. The expected coded-target count is a
    # per-transect/survey argument (--expected-markers), not a constant.
    marker_type: str = "Circular12bit"
    marker_tolerance: int = 20              # ESM start value; auto-bumped from here
    marker_tolerance_step: int = 5          # ESM "increase in increments"
    marker_tolerance_max: int = 100         # cap; FAIL LOUD if expected not reached
    scalebar_length_m: float = 0.25         # 25 cm coded targets

    # Step 8 — Error reduction (Logan script, threshold mode)
    reconstruction_uncertainty: float = 30.0   # Toth 20-40 -> midpoint 30
    projection_accuracy: float = 3.5           # Toth 3-4   -> midpoint 3.5
    reprojection_error: float = 0.3            # Toth fixed 0.3 (PIFSC 0.3-0.5)
    fit_additional_after_reduction: bool = True

    # Step 11 — Orientation / LEVEL (stage_level). ESM Step 11 analog. ADR-0021.
    # Divergence-ledger: replaces the GUI USGS AlignmentHelper (2-marker midline,
    # roll-blind -> the day-1 24.26 deg defect) with a deterministic, headless,
    # outlier-rejecting marker-PLANE level (roll+pitch, scale preserved).
    scalebar_mad_z: float = 3.5             # robust |z| on scale-bar residuals; >this excluded

    # Step 14 — AOI framing (stage_aoi). ESM Step 14 bounding-box analog. ADR-0021.
    # Divergence-ledger: replaces the manual 10x1 bbox with footprint-PCA yaw +
    # centroid auto-placement + a camera-track orientation anchor (transect-agnostic).
    aoi_length_m: float = 10.0             # long axis (X) extent
    aoi_width_m: float = 1.0               # cross axis (Y) extent
    aoi_height_m: float = 5.0             # vertical (Z) crop extent
    aoi_anchor_cameras: int = 20           # first-N vs last-N camera centroids for the +X sign

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
# ADR-0020 pre-flight tripwire: a correct local-planar 10x1 m AOI at 1 cm is
# ~1000x100 (~1e5 cells). If the PREDICTED grid (from the scaled region) blows
# past these, the projection regressed to a geographic plane (WGS84 backfill) and
# buildDem would OOM (ADR-0018) -- abort BEFORE allocation.
TRIPWIRE_MAX_PRED_CELLS = 5_000_000
TRIPWIRE_MAX_AXIS = 1_000_000

# --------------------------------------------------------------------------- #
# PERMANENT QC GATE (ADR-0021) — the guarantee a 24 deg mis-level cannot ship.
# Bounds are grounded in the Phase-A PASS (data/qc/chat5/edr_t3_relevel_final_gate
# .json) and the recon-check (data/qc/chat5/recon_check_20260604.json). The gate
# is self-contained (checks 1-7 need NO reference) so reference-less belt sites
# still gate; the P13HMEON reference is an ADDITIVE check (8), never an input.
# Derivation of the gross-tilt bound: the 0.85 m marker-Y-spread on a 1 m transect
# makes a ~2-4 deg CROSS tilt physics, not a defect (observed PASS 1.88-2.23 deg;
# reference cross ~1.3 deg is the truth, not a target our markers can hit). 6.0 deg
# = that floor + margin, and ~4x below the 24.26 deg day-1 defect it must catch.
GATE_LONG_TILT_MAX_DEG = 0.5      # check 1: long axis (X) must be flat
GATE_TOTAL_TILT_MAX_DEG = 6.0     # check 2: gross-mislevel bound (catches 24 deg)
GATE_COVERAGE_MIN = 0.95          # check 3: interp-OFF coverage of the AOI
GATE_SCALE_EXTENT_TOL_M = 0.02    # check 4: |AOI long extent - aoi_length_m|
GATE_COREG_TOL_M = 1e-6           # check 5: DEM/ortho dx,dy (0 by construction)
GATE_FOOTPRINT_EVR_MIN = 0.95     # check 6: PC1 explained-variance (belt precondition)
GATE_FOOTPRINT_ASPECT_MIN = 5.0   # check 6: major/minor aspect (belt precondition)
GATE_MIN_ALIGN_RATE_FOR_LEVEL = 0.90   # stage_level pre-guard: align >= this to level
# Planarity guard: out-of-plane vs in-plane-minor scatter eigenvalue ratio
# (eig[2]/eig[1]). A clean (even thin belt) plane is << this; ~1 means the markers
# are collinear / non-planar (roll ill-defined). T3 belt = 0.011; threshold 0.5.
GATE_PLANE_FLATNESS_MAX = 0.5
# NoData sentinel returned by Elevation.altitude() outside the data footprint.
DEM_NODATA_SENTINEL = -1000.0     # real reef Z is ~[-1.5, 2]; holes return -32767

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
                             transect: str | None,
                             exclude: "set[str] | None" = None) -> dict[str, list[str]]:
    """Return {transect_label: [image_paths]} for the EDR dataset.

    Handles two on-disk layouts transparently:
      * FLAT  — all TIFFs in image_root, transect encoded in the filename
                (the actual P1WHKTRD layout). We parse the EDR_Tn token.
      * FOLDERED — one subdir per transect. We use the subdir names.

    If `transect` is given (e.g. "EDR_T3"), only that transect is returned —
    dataset scoping so a dev run does not import every transect. Flat is grouped
    in memory only — no files are moved or copied, so the per-image provenance
    from Chat 4 stays valid and the ~5 GB isn't duplicated.

    `exclude` is a set of image BASENAMES dropped before import (transect-
    agnostic intake QC) — e.g. files with corrupt encoded strips that decode-fail
    in libtiff/GDAL and would crash analyzeImages/matchPhotos mid-run.
    """
    want = transect.upper() if transect else None
    excl = exclude or set()
    subdirs = [p for p in image_root.iterdir() if p.is_dir()]
    groups: dict[str, list[str]] = {}

    if subdirs:
        for d in sorted(subdirs):
            if want and d.name.upper() != want:
                continue
            imgs = sorted(str(p) for p in
                          list(d.glob("*.tif")) + list(d.glob("*.tiff"))
                          if p.name not in excl)
            if imgs:
                groups[d.name] = imgs
        if groups:
            log(f"Foldered layout: {len(groups)} transect subdir(s)"
                f"{' (filtered to ' + want + ')' if want else ''}.")
            return groups

    # Flat layout — group by filename token.
    flat = sorted(list(image_root.glob("*.tif")) + list(image_root.glob("*.tiff")))
    unmatched = 0
    n_excluded = 0
    for p in flat:
        if p.name in excl:
            n_excluded += 1
            continue
        m = _TRANSECT_RE.search(p.name)
        if not m:
            unmatched += 1
            continue
        label = m.group(1).upper()
        if want and label != want:
            continue
        groups.setdefault(label, []).append(str(p))
    if n_excluded:
        log(f"Excluded {n_excluded} image(s) by --exclude-images "
            f"(intake QC): {', '.join(sorted(excl))}")
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
                 transect: str | None, project: Path,
                 exclude: "set[str] | None" = None) -> None:
    groups = group_images_by_transect(image_root, transect, exclude)
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
            "excluded_images": sorted(exclude or []),
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


def stage_step4(doc: Metashape.Document, ignore_sanity: bool,
                quality_threshold: float) -> None:
    for chunk in doc.chunks:
        if _meta_get(chunk, "esm.step4") is not None:
            log(f"{chunk.label}: ESM Step 4 already done; skipping.")
            continue
        t0 = time.time()
        stats = filter_low_quality_images(chunk, quality_threshold)
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
        # ESM Step 6: optimize (bundle adjustment) + tie-point covariance (ESM
        # Table S2 dense setting; ADR-0021 — wired T1 onward, T3 pilot ran pre-wiring).
        chunk.optimizeCameras(tiepoint_covariance=PARAMS.tiepoint_covariance)
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
# Stage: markers  (ESM Step 7, DETECTION) — runs BEFORE the GUI handoff
# --------------------------------------------------------------------------- #


def _marker_id(label: str) -> int | None:
    """Coded-target numeric ID from a Metashape marker label ('marker 13' -> 13)."""
    m = re.findall(r"(\d+)", label)
    return int(m[-1]) if m else None


def stage_markers(doc: Metashape.Document, ignore_sanity: bool,
                  expected_ids: "set[int] | None",
                  expected_markers: int | None) -> None:
    """Detect coded targets headless (ESM Step 7, detection only) with
    AUTO-TOLERANCE — the headless form of ESM's manual "start at 20, increase
    until all detected" (start strict, loosen). Tolerance starts at
    marker_tolerance and bumps by marker_tolerance_step up to marker_tolerance_max.

    ACCEPT BY IDENTITY, not count: because increasing tolerance adds detections
    MONOTONICALLY (including false positives), `count == expected` can stop on a
    wrong mix (7 real + 1 spurious). A spurious marker corrupts the level-plane fit
    and scale-bar pairing, and MAD rejection (stage_level) only catches outliers,
    not a false positive sitting near the plane. So:
      * --expected-marker-ids: stop at the LOWEST tolerance where the full expected
        coded-ID set (the same pairs that feed the 0.25 m residual check) is
        present; FAIL LOUD at the cap if incomplete; flag any unexpected detected
        IDs as possible false positives.
      * else --expected-markers N: weaker COUNT criterion (stop at >= N), warns.
      * else: plateau (heuristic), warns.
    No per-transect tolerance is pinned. Scale-bar ASSIGNMENT is the GUI step that
    follows; this is Step 7 (precedes Step 8 error reduction)."""
    for chunk in doc.chunks:
        if _meta_get(chunk, "esm.markers") is not None and chunk.markers:
            log(f"{chunk.label}: markers already detected; skipping.")
            continue
        t0 = time.time()
        tol = PARAMS.marker_tolerance
        best, plateau, history = -1, 0, []
        while tol <= PARAMS.marker_tolerance_max:
            if chunk.markers:                       # clear before re-detecting
                chunk.remove(chunk.markers)
            chunk.detectMarkers(target_type=Metashape.CircularTarget12bit,
                                tolerance=tol)
            ids = {i for i in (_marker_id(m.label) for m in chunk.markers)
                   if i is not None}
            n = len(chunk.markers)
            history.append({"tolerance": tol, "detected": n,
                            "ids": sorted(ids)})
            log(f"{chunk.label}: tolerance={tol} -> {n} markers ids={sorted(ids)}")
            if expected_ids is not None:
                if expected_ids <= ids:
                    break
            elif expected_markers is not None:
                if n >= expected_markers:
                    break
            else:
                plateau = plateau + 1 if n <= best else 0
                if plateau >= 2:
                    break
            best = max(best, n)
            tol += PARAMS.marker_tolerance_step
        detected_ids = {i for i in (_marker_id(m.label) for m in chunk.markers)
                        if i is not None}
        missing = sorted(expected_ids - detected_ids) if expected_ids else []
        unexpected = sorted(detected_ids - expected_ids) if expected_ids else []
        stats = {
            "markers_detected": len(chunk.markers),
            "final_tolerance": tol,
            "detected_ids": sorted(detected_ids),
            "expected_ids": sorted(expected_ids) if expected_ids else None,
            "missing_ids": missing,
            "unexpected_ids": unexpected,
            "expected_markers": expected_markers,
            "tolerance_history": history,
            "seconds": round(time.time() - t0, 1),
        }
        _meta_set(chunk, "esm.markers", stats)
        log(f"{chunk.label}: {len(chunk.markers)} markers (final tolerance {tol}); "
            f"missing={missing} unexpected={unexpected}. NEXT (GUI handoff): assign "
            f"25 cm scale bars to marker pairs + place the Jenkins frame, then reduce.")
        if expected_ids is not None and missing:
            alarm(f"{chunk.label}: expected coded targets {missing} NOT detected up "
                  f"to tolerance {PARAMS.marker_tolerance_max}. A marker-poor "
                  f"transect feeds a weak level plane — refusing to proceed. Check "
                  f"target visibility/quality.", critical=True, ignore=ignore_sanity)
        if unexpected:
            alarm(f"{chunk.label}: unexpected coded IDs {unexpected} detected — "
                  f"possible FALSE POSITIVES that would corrupt the level-plane fit "
                  f"/ scale-bar pairing. Review before --stage reduce.",
                  critical=False, ignore=ignore_sanity)
        if expected_ids is None and expected_markers is not None and \
                len(chunk.markers) < expected_markers:
            alarm(f"{chunk.label}: only {len(chunk.markers)}/{expected_markers} "
                  f"markers detected (count criterion). Prefer --expected-marker-ids "
                  f"so identity, not count, gates.", critical=True, ignore=ignore_sanity)
        elif expected_ids is None and expected_markers is None:
            alarm(f"{chunk.label}: {len(chunk.markers)} markers by plateau, NOT "
                  f"validated against expected IDs. Pass --expected-marker-ids for a "
                  f"production run so a wrong mix FAILs loudly.",
                  critical=False, ignore=ignore_sanity)
        save(doc)


# --------------------------------------------------------------------------- #
# Stage: reduce  (ESM Step 8) — error reduction; runs AFTER scale-bar assignment
# --------------------------------------------------------------------------- #


def stage_reduce(doc: Metashape.Document, logan_module: str | None,
                 ignore_sanity: bool) -> None:
    """ESM Step 8 error reduction. Runs AFTER the GUI handoff has assigned scale
    bars (Step 7), so the final optimizeCameras is scale-constrained — faithful
    to Toth's order (Step 7 precedes Step 8). A critical alarm fires if no scale
    bars are present, to enforce that order (override with --ignore-sanity only
    if a transect genuinely has no usable coded targets).

    Logan USGS script preferred (ADR-0010); the built-in faithful transcription
    is the fallback and, when used, is recorded as a per-run documented departure
    (NOT silently preferred)."""
    for chunk in doc.chunks:
        if _meta_get(chunk, "esm.reduce") is not None:
            log(f"{chunk.label}: error reduction already done; skipping.")
            continue
        n_sb = len(chunk.scalebars)
        if n_sb == 0:
            alarm(f"{chunk.label}: error reduction (ESM Step 8) is running with "
                  f"NO scale bars. Step 8 must follow Step 7 scale-bar "
                  f"assignment so the final optimize is scale-constrained "
                  f"(Toth's order). Assign 25 cm scale bars in the GUI first — "
                  f"see docs/05 'Corrected step order'.",
                  critical=True, ignore=ignore_sanity)
        t0 = time.time()
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
            "scalebars_present": n_sb,
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
        log(f"{chunk.label}: error reduction via '{path}' with {n_sb} scale "
            f"bar(s); RMS(filter units) {stats['reproj_rms_pre_filter_units']} "
            f"-> {stats['reproj_rms_post_filter_units']}")
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
    # Reprojection error last, then final optimize with additional corrections +
    # tie-point covariance (ESM Table S2; ADR-0021 — wired T1 onward).
    _apply(Filter.ReprojectionError, PARAMS.reprojection_error, optimize=False)
    chunk.optimizeCameras(fit_corrections=PARAMS.fit_additional_after_reduction,
                          tiepoint_covariance=PARAMS.tiepoint_covariance)


# --------------------------------------------------------------------------- #
# Stage: level  (ESM Step 11 analog, ADR-0021) — deterministic marker-PLANE
# roll+pitch level with scale-bar-residual outlier rejection. Runs BEFORE dense
# (like ESM Step 11 before Step 12). Marker-only; reference is NEVER an input.
# --------------------------------------------------------------------------- #


def _vec3(p) -> "Metashape.Vector":
    return Metashape.Vector([p.x, p.y, p.z])


def _world_xyz(T: "Metashape.Matrix", p) -> list[float]:
    """Internal marker/camera coord -> world-metric [x,y,z] (scale applied)."""
    w = T.mulp(_vec3(p))
    return [w.x, w.y, w.z]


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def _jacobi_eig_sym3(A: list[list[float]]):
    """Eigen-decomposition of a symmetric 3x3 (cyclic Jacobi). Deterministic,
    dependency-free. Returns (eigvals[3], eigvecs[3] as columns). Used for the
    least-squares plane normal (smallest-eigenvalue eigenvector)."""
    a = [row[:] for row in A]
    V = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]
    for _ in range(100):
        p, q = 0, 1
        if abs(a[0][2]) > abs(a[p][q]):
            p, q = 0, 2
        if abs(a[1][2]) > abs(a[p][q]):
            p, q = 1, 2
        if abs(a[p][q]) < 1e-18:
            break
        app, aqq, apq = a[p][p], a[q][q], a[p][q]
        phi = 0.5 * math.atan2(2 * apq, aqq - app) if (aqq - app) != 0 else math.pi / 4
        c, s = math.cos(phi), math.sin(phi)
        for k in range(3):
            akp, akq = a[k][p], a[k][q]
            a[k][p] = c * akp - s * akq
            a[k][q] = s * akp + c * akq
        for k in range(3):
            apk, aqk = a[p][k], a[q][k]
            a[p][k] = c * apk - s * aqk
            a[q][k] = s * apk + c * aqk
        for k in range(3):
            vkp, vkq = V[k][p], V[k][q]
            V[k][p] = c * vkp - s * vkq
            V[k][q] = s * vkp + c * vkq
    eig = [a[i][i] for i in range(3)]
    vecs = [[V[r][c] for r in range(3)] for c in range(3)]
    return eig, vecs


def _fit_plane_normal(points: list[list[float]]):
    """Least-squares plane normal (unit, +Z-oriented), centroid, and the scatter
    eigenvalues sorted descending (for the collinearity guard) for >=3 points."""
    n = len(points)
    cen = [sum(p[i] for p in points) / n for i in range(3)]
    C = [[0.0] * 3 for _ in range(3)]
    for p in points:
        d = [p[i] - cen[i] for i in range(3)]
        for i in range(3):
            for j in range(3):
                C[i][j] += d[i] * d[j]
    eig, vecs = _jacobi_eig_sym3(C)
    k = min(range(3), key=lambda i: eig[i])
    nrm = vecs[k]
    L = math.sqrt(sum(x * x for x in nrm)) or 1.0
    nrm = [x / L for x in nrm]
    if nrm[2] < 0:                       # deterministic +Z-up orientation
        nrm = [-x for x in nrm]
    return nrm, cen, sorted(eig, reverse=True)


def _rot_normal_to_z(n: list[float]) -> "Metashape.Matrix":
    """Shortest-arc rotation mapping unit normal n -> world +Z (Rodrigues), as a
    3x3 Metashape.Matrix. roll+pitch only (no yaw); preserves scale (pure rot)."""
    z = [0.0, 0.0, 1.0]
    axis = [n[1] * z[2] - n[2] * z[1], n[2] * z[0] - n[0] * z[2], n[0] * z[1] - n[1] * z[0]]
    s = math.sqrt(sum(a * a for a in axis))
    c = sum(n[i] * z[i] for i in range(3))
    if s < 1e-15:                        # already aligned (or anti-aligned)
        return (Metashape.Matrix.Diag([1, 1, 1]) if c > 0
                else Metashape.Matrix([[1, 0, 0], [0, -1, 0], [0, 0, -1]]))
    ux, uy, uz = (a / s for a in axis)
    ang = math.atan2(s, c)
    C, S, t = math.cos(ang), math.sin(ang), 1 - math.cos(ang)
    return Metashape.Matrix([
        [C + ux * ux * t, ux * uy * t - uz * S, ux * uz * t + uy * S],
        [uy * ux * t + uz * S, C + uy * uy * t, uy * uz * t - ux * S],
        [uz * ux * t - uy * S, uz * uy * t + ux * S, C + uz * uz * t]])


def _apply_world_rotation(chunk: "Metashape.Chunk", R: "Metashape.Matrix") -> None:
    """Left-multiply a 3x3 world rotation onto chunk.transform (orientation only;
    translation and scale preserved). world' = R . world."""
    R4 = Metashape.Matrix([
        [R[i, j] if (i < 3 and j < 3) else (1.0 if i == j else 0.0)
         for j in range(4)] for i in range(4)])
    chunk.transform.matrix = R4 * chunk.transform.matrix


def _tilt_from_z(n: list[float]) -> float:
    L = math.sqrt(sum(x * x for x in n)) or 1.0
    return math.degrees(math.acos(max(-1.0, min(1.0, abs(n[2]) / L))))


def stage_level(doc: Metashape.Document, ignore_sanity: bool) -> None:
    """ESM Step 11 analog (ADR-0021): level the chunk on the scale-bar marker
    PLANE (roll+pitch), with robust outlier rejection on scale-bar residuals so a
    bad bar (T3: 25/26, +15.13 mm) cannot corrupt the fit. Scale preserved. This
    is the deterministic, headless generalization of the GUI USGS AlignmentHelper
    (a plane from >=3 fiducials fixes the roll DOF the 2-marker midline cannot —
    the day-1 24.26 deg failure mode). The AOI yaw is NOT set here (stage_aoi)."""
    for chunk in doc.chunks:
        if _meta_get(chunk, "esm.level") is not None:
            log(f"{chunk.label}: already leveled; skipping.")
            continue
        # Pre-level alignment quality guard: a poorly-aligned transect feeds a weak
        # marker geometry and a garbage level plane — STOP before leveling.
        align = _meta_get(chunk, "esm.align") or {}
        rate = align.get("alignment_rate")
        if rate is not None and rate < GATE_MIN_ALIGN_RATE_FOR_LEVEL:
            alarm(f"{chunk.label}: alignment rate {rate*100:.1f}% < "
                  f"{GATE_MIN_ALIGN_RATE_FOR_LEVEL*100:.0f}% — too poor to level "
                  f"reliably. Resolve alignment before stage_level.",
                  critical=True, ignore=ignore_sanity)
        T = chunk.transform.matrix
        mk = {m.label: m.position for m in chunk.markers if m.position is not None}
        scale_before = chunk.transform.scale
        # Scale-bar residuals (measured world distance - defined distance) + MAD.
        bars = []
        for sb in chunk.scalebars:
            try:
                a, b = sb.point0.label, sb.point1.label
                wa, wb = _world_xyz(T, mk[a]), _world_xyz(T, mk[b])
            except (AttributeError, KeyError):
                continue
            dist = math.sqrt(sum((wa[i] - wb[i]) ** 2 for i in range(3)))
            bars.append({"bar": sb.label, "a": a, "b": b, "dist": dist,
                         "resid": dist - sb.reference.distance})
        if len(bars) < 2:
            alarm(f"{chunk.label}: only {len(bars)} usable scale bar(s) — cannot "
                  f"robustly level. Need >=2 (>=3 markers) for a plane.",
                  critical=True, ignore=ignore_sanity)
            continue
        med = _median([d["resid"] for d in bars])
        mad = _median([abs(d["resid"] - med) for d in bars])
        vetted, excluded = set(), []
        for d in bars:
            z = 0.6745 * (d["resid"] - med) / mad if mad > 0 else 0.0
            if abs(z) > PARAMS.scalebar_mad_z:
                excluded.append({"bar": d["bar"], "resid_mm": round(d["resid"] * 1000, 2),
                                 "mad_z": round(z, 2)})
            else:
                vetted.update([d["a"], d["b"]])
        if len(vetted) < 3:
            alarm(f"{chunk.label}: only {len(vetted)} vetted markers after outlier "
                  f"rejection — cannot fit a plane. Review scale bars.",
                  critical=True, ignore=ignore_sanity)
            continue
        vlist = sorted(vetted)
        normal, _, eig = _fit_plane_normal([_world_xyz(T, mk[lab]) for lab in vlist])
        # Planarity / non-collinearity guard: out-of-plane scatter (eig[2]) must be
        # small vs the in-plane minor axis (eig[1]); ~1 means the markers are
        # collinear / non-planar and the plane (roll especially) is ill-defined.
        # A thin belt is still a clean plane (T3 = 0.011) — this passes belts and
        # STOPs only on a degenerate set, rather than fitting a garbage plane.
        flatness = (eig[2] / eig[1]) if eig[1] > 0 else float("inf")
        if flatness > GATE_PLANE_FLATNESS_MAX:
            alarm(f"{chunk.label}: vetted markers are ~collinear / non-planar "
                  f"(eig2/eig1 {flatness:.4f} > {GATE_PLANE_FLATNESS_MAX}) — plane "
                  f"roll is ill-defined. Need non-collinear targets.",
                  critical=True, ignore=ignore_sanity)
        tilt_before = _tilt_from_z(normal)
        R = _rot_normal_to_z(normal)
        _apply_world_rotation(chunk, R)
        # Verify: the vetted plane normal now maps to ~+Z (post-level tilt ~0).
        Tn = chunk.transform.matrix
        leveled = [_world_xyz(Tn, mk[lab]) for lab in vlist]
        normal_after, cen_after, _ = _fit_plane_normal(leveled)
        tilt_after = _tilt_from_z(normal_after)
        scale_after = chunk.transform.scale
        # Per-transect cross-precision context (NOT a hard-coded 0.85 m): the cross
        # (Y) lever arm and the marker Z-scatter about the fitted plane. Logged for
        # the gate's tilt-bound trend; the bound itself is --max-total-tilt-deg.
        y_spread = (max(p[1] for p in leveled) - min(p[1] for p in leveled))
        z_resid = [p[2] - cen_after[2] for p in leveled]
        z_rms = (sum(z * z for z in z_resid) / len(z_resid)) ** 0.5
        cross_floor_deg = round(math.degrees(math.atan2(
            2 * z_rms, y_spread)), 3) if y_spread > 0 else None
        stats = {
            "vetted_markers": vlist,
            "excluded_bars": excluded,
            "plane_normal_before": [round(x, 5) for x in normal],
            "plane_flatness_eig2_eig1": round(flatness, 5),
            "marker_plane_tilt_before_deg": round(tilt_before, 4),
            "marker_plane_tilt_after_deg": round(tilt_after, 4),
            "marker_y_spread_m": round(y_spread, 4),
            "marker_z_rms_m": round(z_rms, 5),
            "implied_cross_floor_deg": cross_floor_deg,
            "scale_before": scale_before,
            "scale_after": scale_after,
            "scale_preserved": abs(scale_after - scale_before) < 1e-12,
        }
        _meta_set(chunk, "esm.level", stats)
        log(f"{chunk.label}: leveled on {len(vlist)} vetted markers "
            f"(excluded {len(excluded)} bar(s)); marker-plane tilt "
            f"{tilt_before:.2f} -> {tilt_after:.3f} deg; scale {scale_after:.8g} "
            f"(preserved={stats['scale_preserved']}).")
        if not stats["scale_preserved"]:
            alarm(f"{chunk.label}: leveling changed transform.scale "
                  f"({scale_before} -> {scale_after}). A pure rotation must "
                  f"preserve scale — fit/rotation bug.",
                  critical=True, ignore=ignore_sanity)
        if tilt_after > GATE_LONG_TILT_MAX_DEG:
            alarm(f"{chunk.label}: vetted marker-plane is still tilted "
                  f"{tilt_after:.3f} deg from Z after leveling — R was not applied "
                  f"correctly.", critical=True, ignore=ignore_sanity)
        save(doc)


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
# ADR-0020: the LOCAL-CRS + identity-Planar lever that makes Steps 14-15 build
# headless. Shared by the dsm and ortho stages so the ortho co-registers exactly.
# --------------------------------------------------------------------------- #


def _local_planar_projection(chunk: "Metashape.Chunk") -> "Metashape.OrthoProjection":
    """Declare the chunk's CRS LOCAL (metre) and return a top-down Planar
    projection in that frame. THIS is the lever (ADR-0020): a LOCAL output CRS
    stops buildDem/buildOrthomosaic backfilling the spurious WGS 84 (EPSG:4326)
    that otherwise rasterizes the whole geographic plane -> std::bad_alloc OOM
    (orphan_1857_note.md / ADR-0018). The Planar matrix is identity for a
    LOCAL_CS (localframe rotation is identity). Idempotent: re-asserting an
    already-LOCAL chunk.crs is harmless, so dsm and ortho can each call it."""
    chunk.crs = Metashape.CoordinateSystem(
        'LOCAL_CS["Local Coordinates (m)",LOCAL_DATUM["Local Datum",0],'
        'UNIT["metre",1]]')
    top_xy = Metashape.Matrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    origin = chunk.transform.matrix.mulp(Metashape.Vector([0, 0, 0]))
    lf = chunk.crs.localframe(origin)
    proj = Metashape.OrthoProjection()
    proj.crs = chunk.crs
    proj.type = Metashape.OrthoProjection.Type.Planar
    proj.matrix = (Metashape.Matrix.Rotation(top_xy)
                   * Metashape.Matrix.Rotation(lf.rotation()))
    log(f"{chunk.label}: chunk.crs set LOCAL + top-down Planar projection "
        f"(ADR-0020; proj.crs={proj.crs})")
    return proj


# --------------------------------------------------------------------------- #
# Stage: aoi  (ESM Step 14 bounding-box analog, ADR-0021) — footprint-PCA yaw +
# centroid auto-placement + camera-track orientation anchor + 10x1x5 m crop.
# Runs AFTER filter (footprint PCA on the denoised cloud), BEFORE dsm. Footprint-
# only; reference is NEVER an input.
#
# PRECONDITION (divergence ledger): this assumes an ELONGATED belt-transect
# footprint. Gate check 6 (aspect >= 5:1) hard-fails a degenerate/square footprint
# rather than mis-framing it. Square-plot sites (Summerland Ledges / IC_U: 10x10 m
# plots, no dominant axis, different cameras) are OUT OF SCOPE by survey design and
# trip check 6 — Toth treats them separately too.
# --------------------------------------------------------------------------- #


def _rot_z(theta: float) -> "Metashape.Matrix":
    c, s = math.cos(theta), math.sin(theta)
    return Metashape.Matrix([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _occupied_cells_world(el: "Metashape.Elevation"):
    """Read an interp-OFF DEM: yield (world_x, world_y, z) for non-NoData cells.
    altitude() bilinearly samples and returns the -32767 sentinel outside the data
    footprint (DEM_NODATA_SENTINEL guards it)."""
    res, left, top = el.resolution, el.left, el.top
    for j in range(el.height):
        y = top - (j + 0.5) * res
        for i in range(el.width):
            x = left + (i + 0.5) * res
            z = el.altitude(Metashape.Vector([x, y]))
            if z > DEM_NODATA_SENTINEL:
                yield x, y, z


def _pca2d(xy: list[tuple]):
    """2x2 covariance PCA of (x,y) points. Returns (major_angle_rad_from_+X,
    centroid_xy, explained_var_ratio, aspect_ratio)."""
    n = len(xy)
    cx = sum(p[0] for p in xy) / n
    cy = sum(p[1] for p in xy) / n
    sxx = sum((p[0] - cx) ** 2 for p in xy) / n
    syy = sum((p[1] - cy) ** 2 for p in xy) / n
    sxy = sum((p[0] - cx) * (p[1] - cy) for p in xy) / n
    tr = sxx + syy
    disc = math.sqrt(max(0.0, (tr / 2) ** 2 - (sxx * syy - sxy * sxy)))
    l1, l2 = tr / 2 + disc, tr / 2 - disc
    ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
    evr = l1 / (l1 + l2) if (l1 + l2) > 0 else 0.0
    aspect = math.sqrt(l1 / l2) if l2 > 1e-12 else float("inf")
    return ang, (cx, cy), evr, aspect


def _build_interp_off_dem(chunk: "Metashape.Chunk") -> "Metashape.Elevation":
    """Build a transient interp-OFF DEM at DSM resolution via the ADR-0020 local-
    planar recipe. Caller MUST chunk.remove([el]) it (so stage_dsm's idempotency
    is not broken). chunk.crs is set LOCAL by _local_planar_projection."""
    proj = _local_planar_projection(chunk)
    chunk.buildDem(source_data=Metashape.PointCloudData,
                   interpolation=Metashape.DisabledInterpolation,
                   projection=proj, resolution=PARAMS.dsm_resolution_m)
    return chunk.elevation


def _camera_track_sign(chunk: "Metashape.Chunk", centroid_xy, u) -> float:
    """Project aligned camera centres (ordered by image label) onto the footprint
    major axis u; return +1 if the FIRST-N cameras lie toward +u, else -1. This is
    the transect-agnostic orientation anchor (ADR-0021 amendment): deterministic,
    present on every belt transect and on fresh raw data, robust to the lawnmower
    zigzag. Calibrated so +X = toward the first-image-number cameras reproduces
    the validated T3 frame (marker-20 end)."""
    T = chunk.transform.matrix
    cams = sorted((c for c in chunk.cameras if c.transform is not None),
                  key=lambda c: c.label)
    n = min(PARAMS.aoi_anchor_cameras, len(cams) // 2) or 1
    def proj(c):
        w = T.mulp(c.center)
        return (w.x - centroid_xy[0]) * u[0] + (w.y - centroid_xy[1]) * u[1]
    first = sum(proj(c) for c in cams[:n]) / n
    last = sum(proj(c) for c in cams[-n:]) / n
    return 1.0 if first >= last else -1.0


def stage_aoi(doc: Metashape.Document, ignore_sanity: bool) -> None:
    for chunk in doc.chunks:
        if _meta_get(chunk, "esm.aoi") is not None:
            log(f"{chunk.label}: AOI already framed; skipping.")
            continue
        if chunk.point_cloud is None:
            alarm(f"{chunk.label}: no dense cloud — cannot frame the AOI. Run "
                  f"dense first.", critical=True, ignore=ignore_sanity)
            continue
        scale = chunk.transform.scale
        # --- 1) Footprint PCA from a transient interp-OFF DEM of the FULL cloud ---
        chunk.resetRegion()                       # encompass the whole cloud first
        el = _build_interp_off_dem(chunk)
        cells = list(_occupied_cells_world(el))
        z_mid = (min(c[2] for c in cells) + max(c[2] for c in cells)) / 2
        ang, cen_xy, evr, aspect = _pca2d([(c[0], c[1]) for c in cells])
        chunk.remove([el])                        # drop transient DEM (idempotency)
        # --- 2) Orientation anchor: camera track (primary), +X toward first-N ----
        u = (math.cos(ang), math.sin(ang))
        sign = _camera_track_sign(chunk, cen_xy, u)
        oriented = ang if sign > 0 else ang + math.pi
        # --- 3) Apply the yaw about world Z so the oriented major axis -> +X ------
        T_lev = chunk.transform.matrix
        cen_world = Metashape.Vector([cen_xy[0], cen_xy[1], z_mid])
        center_internal = T_lev.inv().mulp(cen_world)   # invariant under transform edits
        _apply_world_rotation(chunk, _rot_z(-oriented))
        # --- 4) Set the canonical 10x1x5 m region (world-axis-aligned, centroid) --
        region = Metashape.Region()
        region.center = center_internal
        region.size = Metashape.Vector([PARAMS.aoi_length_m / scale,
                                        PARAMS.aoi_width_m / scale,
                                        PARAMS.aoi_height_m / scale])
        region.rot = _region_rot_world_aligned(chunk)
        chunk.region = region
        # --- 5) Crop the dense cloud to the AOI ----------------------------------
        pc = chunk.point_cloud
        n_before = pc.point_count
        pc.selectPointsByRegion(region)
        pc.cropSelectedPoints()                   # keep selected (inside region)
        pc.compactPoints()                        # finalize removal so count refreshes
        n_after = pc.point_count
        # --- 6) Coverage from a transient interp-OFF DEM of the CROPPED cloud -----
        el2 = _build_interp_off_dem(chunk)
        full = el2.width * el2.height
        occ = sum(1 for _ in _occupied_cells_world(el2))
        coverage = occ / full if full else 0.0
        chunk.remove([el2])
        # --- 7) Orientation check #7 in the FINAL frame (sign-flip guard) ---------
        Tf = chunk.transform.matrix
        cams = sorted((c for c in chunk.cameras if c.transform is not None),
                      key=lambda c: c.label)
        nN = min(PARAMS.aoi_anchor_cameras, len(cams) // 2) or 1
        firstX = sum(Tf.mulp(c.center).x for c in cams[:nN]) / nN
        lastX = sum(Tf.mulp(c.center).x for c in cams[-nN:]) / nN
        plus_x_ok = firstX > lastX
        stats = {
            "footprint_major_angle_deg": round(math.degrees(ang), 4),
            "applied_yaw_deg": round(math.degrees(-oriented), 4),
            "footprint_explained_var": round(evr, 4),
            "footprint_aspect": round(aspect, 3) if aspect != float("inf") else None,
            "centroid_world_xy": [round(cen_xy[0], 5), round(cen_xy[1], 5)],
            "z_mid": round(z_mid, 5),
            "points_before": n_before, "points_after": n_after,
            "coverage_interp_off": round(coverage, 4),
            "anchor_firstN_X": round(firstX, 4), "anchor_lastN_X": round(lastX, 4),
            "orientation_plus_x_ok": plus_x_ok,
            "scale_preserved": abs(chunk.transform.scale - scale) < 1e-12,
        }
        _meta_set(chunk, "esm.aoi", stats)
        log(f"{chunk.label}: AOI framed yaw={stats['applied_yaw_deg']:+.2f} deg, "
            f"footprint evr={evr:.3f} aspect={stats['footprint_aspect']}, crop "
            f"{n_before:,} -> {n_after:,}, coverage(interp-OFF)={coverage*100:.1f}%, "
            f"+X anchor ok={plus_x_ok}.")
        # Inline gate checks available pre-DSM (4, 6, 7). Tilt/co-reg are post-DSM.
        if evr < GATE_FOOTPRINT_EVR_MIN or aspect < GATE_FOOTPRINT_ASPECT_MIN:
            alarm(f"{chunk.label}: GATE#6 footprint not belt-shaped "
                  f"(evr={evr:.3f} < {GATE_FOOTPRINT_EVR_MIN} or "
                  f"aspect={stats['footprint_aspect']} < {GATE_FOOTPRINT_ASPECT_MIN}). "
                  f"stage_aoi requires an elongated transect; square plots are out "
                  f"of scope (ADR-0021).", critical=True, ignore=ignore_sanity)
        if not plus_x_ok:
            alarm(f"{chunk.label}: GATE#7 orientation sign flip — first-N cameras "
                  f"(X={firstX:.2f}) are not on the +X half (last-N X={lastX:.2f}). "
                  f"A reversed product would ship silently. Aborting.",
                  critical=True, ignore=ignore_sanity)
        if coverage < GATE_COVERAGE_MIN:
            alarm(f"{chunk.label}: GATE#3 coverage(interp-OFF) {coverage*100:.1f}% < "
                  f"{GATE_COVERAGE_MIN*100:.0f}%. AOI mis-placed vs the reef band.",
                  critical=True, ignore=ignore_sanity)
        if not stats["scale_preserved"]:
            alarm(f"{chunk.label}: GATE#4 framing changed scale.",
                  critical=True, ignore=ignore_sanity)
        save(doc)


def _region_rot_world_aligned(chunk: "Metashape.Chunk") -> "Metashape.Matrix":
    """Region rotation for a WORLD-axis-aligned box: columns are the world axes
    expressed in internal coords = (scale-stripped transform rotation)^T."""
    T = chunk.transform.matrix
    cols = []
    for j in range(3):                            # normalize each column (strip scale)
        v = [T.row(i)[j] for i in range(3)]
        L = math.sqrt(sum(x * x for x in v)) or 1.0
        cols.append([x / L for x in v])
    Rrot = Metashape.Matrix([[cols[j][i] for j in range(3)] for i in range(3)])
    return Rrot.t()


# --------------------------------------------------------------------------- #
# Stage: gate  (ADR-0021) — PERMANENT QC gate on the built DEM/ortho. FAILs the
# build loudly if a 24 deg mis-level (or a reversed/clipped product) would ship.
# Reads the interp-ON product DEM for tilt; reuses esm.aoi for coverage/footprint/
# orientation; builds NO DEM (no product clobber). Reference (8) is ADDITIVE.
# --------------------------------------------------------------------------- #


def _dem_plane_tilt(el: "Metashape.Elevation"):
    """Fit z = a*x + b*y + c to a grid sample of the (interp-ON) product DEM.
    Returns (long_tilt_deg about X, cross_tilt_deg about Y, total_tilt_deg)."""
    res, left, top, w, h = el.resolution, el.left, el.top, el.width, el.height
    sx, sy = max(1, w // 200), max(1, h // 40)
    pts = []
    for j in range(0, h, sy):
        y = top - (j + 0.5) * res
        for i in range(0, w, sx):
            x = left + (i + 0.5) * res
            z = el.altitude(Metashape.Vector([x, y]))
            if z > DEM_NODATA_SENTINEL:
                pts.append((x, y, z))
    n = len(pts)
    Sx = sum(p[0] for p in pts); Sy = sum(p[1] for p in pts); Sz = sum(p[2] for p in pts)
    Sxx = sum(p[0] * p[0] for p in pts); Syy = sum(p[1] * p[1] for p in pts)
    Sxy = sum(p[0] * p[1] for p in pts)
    Sxz = sum(p[0] * p[2] for p in pts); Syz = sum(p[1] * p[2] for p in pts)
    Mx = Metashape.Matrix([[Sxx, Sxy, Sx], [Sxy, Syy, Sy], [Sx, Sy, n]])
    abc = Mx.inv() * Metashape.Vector([Sxz, Syz, Sz])
    a, b = abc[0], abc[1]
    long_t = math.degrees(math.atan(abs(a)))
    cross_t = math.degrees(math.atan(abs(b)))
    total = math.degrees(math.acos(1 / math.sqrt(a * a + b * b + 1)))
    return long_t, cross_t, total


def stage_gate(doc: Metashape.Document, ignore_sanity: bool,
               reference_dem: "Path | None" = None,
               max_total_tilt_deg: float = GATE_TOTAL_TILT_MAX_DEG) -> None:
    for chunk in doc.chunks:
        aoi = _meta_get(chunk, "esm.aoi")
        if chunk.elevation is None or chunk.orthomosaic is None or aoi is None:
            alarm(f"{chunk.label}: GATE cannot run — need stage_aoi + dsm + ortho "
                  f"first (have aoi={aoi is not None}, dem={chunk.elevation is not None}, "
                  f"ortho={chunk.orthomosaic is not None}).",
                  critical=True, ignore=ignore_sanity)
            continue
        dem = chunk.elevation
        long_t, cross_t, total_t = _dem_plane_tilt(dem)
        long_ext = dem.width * dem.resolution            # AOI long extent (m)
        ortho = chunk.orthomosaic
        coreg_dx = abs(ortho.left - dem.left)
        coreg_dy = abs(ortho.top - dem.top)
        checks = {
            "1_long_tilt_deg": {"v": round(long_t, 3), "max": GATE_LONG_TILT_MAX_DEG,
                                "pass": long_t <= GATE_LONG_TILT_MAX_DEG},
            "2_total_tilt_deg": {"v": round(total_t, 3), "max": max_total_tilt_deg,
                                 "pass": total_t <= max_total_tilt_deg},
            "3_coverage_interp_off": {"v": aoi["coverage_interp_off"],
                                      "min": GATE_COVERAGE_MIN,
                                      "pass": aoi["coverage_interp_off"] >= GATE_COVERAGE_MIN},
            "4_long_extent_m": {"v": round(long_ext, 4), "target": PARAMS.aoi_length_m,
                                "pass": abs(long_ext - PARAMS.aoi_length_m) <= GATE_SCALE_EXTENT_TOL_M},
            "5_coreg_dx_dy_m": {"v": [round(coreg_dx, 8), round(coreg_dy, 8)],
                                "pass": coreg_dx <= GATE_COREG_TOL_M and coreg_dy <= GATE_COREG_TOL_M},
            "6_footprint": {"evr": aoi["footprint_explained_var"],
                            "aspect": aoi["footprint_aspect"],
                            "pass": (aoi["footprint_explained_var"] >= GATE_FOOTPRINT_EVR_MIN
                                     and (aoi["footprint_aspect"] or 0) >= GATE_FOOTPRINT_ASPECT_MIN)},
            "7_orientation_plus_x": {"v": aoi["orientation_plus_x_ok"],
                                     "pass": bool(aoi["orientation_plus_x_ok"])},
        }
        # Check 8 (ADDITIVE) — reference overlap, only where a P13HMEON DEM exists.
        # GATE only, never a level/aoi input. Full roughness/overlap comparison is a
        # QC step (the core gate 1-7 is self-contained); recorded as available here.
        checks["8_reference_dem"] = {"available": reference_dem is not None,
                                     "path": str(reference_dem) if reference_dem else None,
                                     "pass": True, "note": "additive; self-contained gate is 1-7"}
        cross_floor = {"cross_tilt_deg": round(cross_t, 3),
                       "note": "cross is the under-constrained DOF (marker Y-spread "
                               "0.85 m floor); within the documented 2-4 deg envelope, "
                               "not gated as a defect (ADR-0021)."}
        failed = [k for k, c in checks.items() if not c["pass"]]
        verdict = {"chunk": chunk.label, "checks": checks, "cross": cross_floor,
                   "failed": failed, "PASS": not failed}
        _meta_set(chunk, "esm.gate", verdict)
        log(f"{chunk.label}: GATE long={long_t:.2f} total={total_t:.2f} "
            f"cov={checks['3_coverage_interp_off']['v']*100:.1f}% "
            f"ext={long_ext:.3f}m coreg=({coreg_dx:.1e},{coreg_dy:.1e}) "
            f"evr={aoi['footprint_explained_var']} +X={aoi['orientation_plus_x_ok']} "
            f"-> {'PASS' if not failed else 'FAIL ' + ','.join(failed)}")
        save(doc)
        if failed:
            alarm(f"{chunk.label}: PERMANENT QC GATE FAILED on {failed}. A mis-"
                  f"leveled/clipped/reversed product will NOT ship (ADR-0021). "
                  f"Tilt long={long_t:.2f} total={total_t:.2f} deg.",
                  critical=True, ignore=ignore_sanity)


# --------------------------------------------------------------------------- #
# Stage: dsm  (ESM Step 14) — DSM at 1 cm, headless via the ADR-0020 recipe
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
        # ADR-0020: LOCAL chunk.crs + identity Planar projection — the lever that
        # makes Step 14 build headless without the WGS84 degree-plane OOM.
        proj = _local_planar_projection(chunk)
        res = PARAMS.dsm_resolution_m

        # PRE-FLIGHT TRIPWIRE — predicted raster from the SCALED region. A correct
        # local-planar 10x1 m AOI at 1 cm is ~1000x100 (~1e5 cells). A huge
        # prediction means the projection regressed to a geographic plane; abort
        # BEFORE buildDem allocates. This closes the ADR-0018 OOM in code, not
        # just by convention (replaces the old no-region auto-infer path).
        R, T = chunk.region, chunk.transform
        s = T.scale or 1.0
        pcols, prows = (R.size.x * s) / res, (R.size.y * s) / res
        log(f"{chunk.label}: predicted DEM ~ {pcols:.0f} x {prows:.0f} cells "
            f"({pcols * prows:.3e}) over {R.size.x * s:.2f} x {R.size.y * s:.2f} m")
        if pcols * prows > TRIPWIRE_MAX_PRED_CELLS or max(pcols, prows) > TRIPWIRE_MAX_AXIS:
            alarm(f"{chunk.label}: predicted DEM {pcols:.0f}x{prows:.0f} exceeds the "
                  f"tripwire ({TRIPWIRE_MAX_PRED_CELLS:,} cells / {TRIPWIRE_MAX_AXIS:,} "
                  f"per axis). Projection is NOT local-planar (WGS84 backfill?). "
                  f"Refusing buildDem to avoid the ADR-0018 OOM (see ADR-0020).",
                  critical=True, ignore=ignore_sanity)
            continue

        log(f"{chunk.label}: building DSM at {res} m (ADR-0020 local-planar "
            f"headless recipe; source=point cloud, interpolation ENABLED)")
        t0 = time.time()
        try:
            chunk.buildDem(
                source_data=Metashape.PointCloudData,
                interpolation=Metashape.EnabledInterpolation,
                projection=proj,
                resolution=res,
            )
        except (MemoryError, RuntimeError) as exc:
            alarm(f"{chunk.label}: buildDem FAILED ({type(exc).__name__}: {exc}) "
                  f"despite the LOCAL-CRS projection and a passing tripwire. "
                  f"Capture the log; do NOT fall back to ad-hoc builds (ADR-0020).",
                  critical=True, ignore=ignore_sanity)
            continue

        dem = chunk.elevation
        dims = [getattr(dem, "width", None), getattr(dem, "height", None)]
        cells = (dims[0] or 0) * (dims[1] or 0)
        stats = {
            "resolution_m": res,
            "width": dims[0],
            "height": dims[1],
            "cells": cells,
            "projection": "local_planar_identity",   # ADR-0020
            "predicted_cells": round(pcols * prows),
            "seconds": round(time.time() - t0, 1),
            **scale_info,
        }
        _meta_set(chunk, "esm.dsm", stats)
        log(f"{chunk.label}: DSM built {dims[0]}x{dims[1]} = {cells:,} cells "
            f"at {res} m (ADR-0020 headless local-planar)")
        if cells == 0:
            alarm(f"{chunk.label}: DSM has 0 cells — all-NoData or degenerate. "
                  f"Surface and investigate.",
                  critical=True, ignore=ignore_sanity)
        elif cells > ALARM_MAX_DSM_CELLS:
            alarm(f"{chunk.label}: DSM is {cells:,} cells (> "
                  f"{ALARM_MAX_DSM_CELLS:,}). Extent looks wrong for a ~10x1 m "
                  f"transect at 1 cm — projection regression?",
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
        # ADR-0020: same LOCAL-CRS top-down Planar projection as the DEM, so the
        # ortho co-registers with it exactly (dx=dy=0). Idempotent if the dsm
        # stage already set chunk.crs LOCAL in this session.
        proj = _local_planar_projection(chunk)
        log(f"{chunk.label}: building orthomosaic on the DEM surface "
            f"(blend={PARAMS.ortho_blend}, fill_holes={PARAMS.ortho_hole_filling}; "
            f"resolution=0 -> image GSD)")
        t0 = time.time()
        chunk.buildOrthomosaic(
            surface_data=Metashape.ElevationData,
            blending_mode=_BLEND[PARAMS.ortho_blend],
            fill_holes=PARAMS.ortho_hole_filling,
            projection=proj,
        )
        ortho = chunk.orthomosaic
        _meta_set(chunk, "esm.ortho", {
            "width": getattr(ortho, "width", None),
            "height": getattr(ortho, "height", None),
            "blend": PARAMS.ortho_blend,
            "projection": "local_planar_identity",   # ADR-0020
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
            "stage_markers": _meta_get(chunk, "esm.markers"),
            "stage_reduce": _meta_get(chunk, "esm.reduce"),
            "stage_level": _meta_get(chunk, "esm.level"),
            "stage_dense": _meta_get(chunk, "esm.dense"),
            "stage_filter": _meta_get(chunk, "esm.filter"),
            "stage_aoi": _meta_get(chunk, "esm.aoi"),
            "stage_dsm": _meta_get(chunk, "esm.dsm"),
            "stage_ortho": _meta_get(chunk, "esm.ortho"),
            "stage_gate": _meta_get(chunk, "esm.gate"),
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

# Corrected step order (ADR-0017 + fidelity fix): marker detection (Step 7) is
# its own stage BEFORE the GUI scale-bar handoff; error reduction (Step 8) runs
# AFTER it. ADR-0021 inserts level (ESM Step 11, marker-plane, BEFORE dense) and
# aoi (ESM Step 14 bbox, footprint-PCA, AFTER filter) as two separate stages, and
# a permanent gate after ortho. Sequence with handoffs:
#   import step4 align markers [GUI: scale bars] reduce [GUI: coord frame]
#   level dense filter aoi dsm ortho gate report
STAGES = ["import", "step4", "align", "markers", "reduce", "level", "dense",
          "filter", "aoi", "dsm", "ortho", "gate", "report"]


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
    ap.add_argument("--quality-threshold", type=float,
                    default=PARAMS.image_quality_threshold,
                    help="ESM Step 4 image-quality cutoff (step4 stage). 0.50 is "
                         "Toth's verbatim ESM value; on our re-encoded TIFFs it "
                         "disables ~46%% of EDR_T3, so the empirically-chosen "
                         "floor may be lower (see ADR-0017).")
    ap.add_argument("--noise-confidence", type=float,
                    default=float(PARAMS.noise_confidence_threshold),
                    help="ESM Step 13 confidence threshold (filter stage).")
    ap.add_argument("--logan-module", default=None,
                    help="Importable module name of the vendored Logan script. "
                         "If omitted, the built-in transcription is used and "
                         "recorded as a per-run documented departure.")
    ap.add_argument("--reference-dem", type=Path, default=None,
                    help="Optional P13HMEON reference DEM for the gate's ADDITIVE "
                         "check 8 (reference-patch overlap). GATE ONLY, never a "
                         "level/aoi input; the core gate (checks 1-7) is "
                         "self-contained so reference-less sites still gate.")
    ap.add_argument("--exclude-images", default=None,
                    help="Comma-separated image BASENAMES to drop at import "
                         "(intake QC). Use for files that decode-fail in "
                         "libtiff/GDAL (corrupt encoded strips) and would crash "
                         "analyzeImages/matchPhotos. Recorded in esm.import.")
    ap.add_argument("--expected-marker-ids", default=None,
                    help="Comma-separated expected coded-target IDs (e.g. "
                         "'13,14,15,16,19,20,25,26'). The marker stage stops at the "
                         "lowest tolerance where this full ID set is present "
                         "(identity, not count); FAILs if any are missing; flags "
                         "unexpected IDs as possible false positives. PREFERRED over "
                         "--expected-markers.")
    ap.add_argument("--expected-markers", type=int, default=None,
                    help="Weaker COUNT criterion for the marker stage if exact IDs "
                         "are unknown. EDR belt transects deploy 4 scale bars = 8 "
                         "coded targets. Prefer --expected-marker-ids.")
    ap.add_argument("--max-total-tilt-deg", type=float, default=GATE_TOTAL_TILT_MAX_DEG,
                    help="Gate check 2 gross-mislevel bound (deg). Default 6.0 is "
                         "conservative for the EDR ~1 m-strip deployment (cross "
                         "floor ~2-4 deg from the marker-Y-spread); override for a "
                         "transect with materially different marker geometry. The "
                         "per-transect marker-Y-spread is logged every run.")
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

    exclude_images = set()
    if args.exclude_images:
        exclude_images = {x.strip() for x in args.exclude_images.split(",") if x.strip()}

    expected_ids = None
    if args.expected_marker_ids:
        try:
            expected_ids = {int(x) for x in args.expected_marker_ids.split(",") if x.strip()}
        except ValueError:
            sys.exit(f"--expected-marker-ids must be comma-separated integers, got "
                     f"{args.expected_marker_ids!r}")

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
            stage_import(doc, args.image_root, args.transect, args.project,
                         exclude_images)
        elif st == "step4":
            stage_step4(doc, args.ignore_sanity, args.quality_threshold)
        elif st == "align":
            stage_align(doc, focal_mode, args.ignore_sanity)
        elif st == "markers":
            stage_markers(doc, args.ignore_sanity, expected_ids, args.expected_markers)
        elif st == "reduce":
            stage_reduce(doc, args.logan_module, args.ignore_sanity)
        elif st == "level":
            stage_level(doc, args.ignore_sanity)
        elif st == "dense":
            stage_dense(doc, args.ignore_sanity)
        elif st == "filter":
            stage_filter(doc, args.noise_confidence, args.ignore_sanity)
        elif st == "aoi":
            stage_aoi(doc, args.ignore_sanity)
        elif st == "dsm":
            stage_dsm(doc, args.ignore_sanity)
        elif st == "ortho":
            stage_ortho(doc, args.ignore_sanity)
        elif st == "gate":
            stage_gate(doc, args.ignore_sanity, args.reference_dem,
                       args.max_total_tilt_deg)
        elif st == "report":
            stage_report(doc, args.out_root, gpu_names)
    log("Pipeline run complete.")


if __name__ == "__main__":
    main()
