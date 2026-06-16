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
import os
import re
import statistics
import sys
import time
import traceback
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
    scalebar_accuracy_m: float = 0.001         # scale-bar reference accuracy (m) =
                                               # the optimize weight; was unset (None
                                               # = active-but-unweighted) pre-ADR-0023

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
# --------------------------------------------------------------------------- #
# MARKER-LAYER VALIDATION GATES (stage_markers) — the headless go/no-go that
# decides whether the auto-detected coded-target layer is good enough to scale
# headless. The gate CODE is transect-agnostic (pairs derived from detected ids; no
# hardcoded ID set; gate (c) scale-free). These are DEFAULT thresholds, calibrated
# on a known-good reference transect (here EDR_T3) with margin; recalibrate per
# program (procedure in docs/05). All three are CLI-overridable. See ADR-0022.
#  (a) parity/orphans   — every marker must pair with a consecutive-ID neighbour
#                         (the default convention, e.g. 13-14, 15-16); odd / orphan
#                         = FAIL. Pairs come from the DETECTED ids, never a fixed set.
#  (b) coherence        — robust (median) per-marker reprojection residual, RAW
#                         post-align (NO in-gate optimize). A loose tripwire: on the
#                         T3 reference, true markers <=0.38 px while an incoherent
#                         layer is ~1000x past, so 2.0 px clears clean and catches
#                         bad. *** MOST SITE-DEPENDENT *** — imaging conditions /
#                         turbidity differ by program; recalibrate this first.
#  (c) inter-bar ratio  — candidate-bar max/min local-length ratio. Pre-scale,
#                         internal units (scale-invariant -> firewall-safe; never
#                         converted to metres). SCALE-FREE -> generalizes as-is;
#                         T3 reference 1.091 PASS.
GATE_MARKER_RESID_CEILING_PX = 2.0     # gate (b): ~5x the T3 reference 0.378 px
GATE_INTERBAR_RATIO_MAX = 1.25         # gate (c): scale-free; T3 reference 1.091
# gate (d) — sufficiency / fail-closed floor. A headless PASS requires >= this many
# VALIDATED bars (both endpoints coherent). Floor is 2 (so gate (c)'s ratio has two
# bars to compare — with a single surviving bar the ratio is a vacuous 1.0 and the
# layer would scale unchecked); default 3 matches the EDR deployment norm (Toth ESM
# deploys 3-4 scale bars/transect). Zero/one marker, all-flagged, zero proposable
# bars all collapse to < this -> ESCALATE. See ADR-0022.
GATE_MIN_VALIDATED_BARS = 3
# A 3D marker position needs >= 2 camera rays; a marker seen in fewer cameras is
# un-triangulable and is flagged as malformed (structural validity, NOT the
# falsified count-floor heuristic — this is a minimum, not a quality threshold).
GATE_MIN_MARKER_PROJECTIONS = 2
# Planarity guard: out-of-plane vs in-plane-minor scatter eigenvalue ratio
# (eig[2]/eig[1]). A clean (even thin belt) plane is << this; ~1 means the markers
# are collinear / non-planar (roll ill-defined). T3 belt = 0.011; threshold 0.5.
GATE_PLANE_FLATNESS_MAX = 0.5
# Camera-nadir leveling guards (ADR-0025).
# LEVEL_COLLINEAR_THRESHOLD: in-plane minor/major scatter ratio (eig[1]/eig[0]).
# Small → markers near-collinear → plane roll axis ill-defined → use camera-nadir.
# T1 near-collinear = ~0.10 (fires); well-spread grid or belt > 0.30. Threshold 0.25.
LEVEL_COLLINEAR_THRESHOLD = 0.25
# LEVEL_NADIR_GUARD_DEG: max angle (deg) between marker-plane normal and camera-nadir
# UP. When NOT collinear but disagreement exceeds this, escalate and use camera-nadir
# as fallback. A well-leveled nadir survey shows < 5°; 15° is the escalation floor.
LEVEL_NADIR_GUARD_DEG = 15.0
# LOCAL_CS WKT shared by _neutralize_spurious_reference (stage_scale, ADR-0024)
# and _local_planar_projection (stage_dsm / stage_ortho, ADR-0020).  One string
# here ensures both stages always sit in the same local metric frame.
_LOCAL_CS_WKT = (
    'LOCAL_CS["Local Coordinates (m)",LOCAL_DATUM["Local Datum",0],'
    'UNIT["metre",1]]'
)
# --------------------------------------------------------------------------- #
# NETWORK-HEALTH COLLAPSE GUARD (defense in depth; ADR-0023) — HARD tripwires
# that stop a collapsed/blown-up bundle from being written as success or fed to a
# downstream stage. Born from the 2026-06-08 EDR_T1 reduce collapse (a home-grown
# one-shot gradual selection removed 100% of tie points -> 86/2422 cameras; scale
# and level then "succeeded" on the wreckage because their guards read STALE align
# meta, not the live network). These are COARSE collapse tripwires, NOT the fine
# accuracy gates (that is stage_gate). All CLI-overridable; recalibration in docs/05.
#  - camera survival is the PRIMARY discriminator: a clean reduce does NOT de-align
#    cameras. Floor is a fraction of the pre-stage aligned (3b) / enabled (3c) count.
#  - scale-bar sanity is the second PRIMARY: a sane metric model keeps bars near
#    their defined 0.25 m; a collapse blows them to kilometres. COARSE (within Nx),
#    NOT the fine scale gate.
#  - the tie-point check is deliberately a NEAR-ZERO tripwire, not a fraction: a
#    healthy (Logan) reduce legitimately removes a LARGE share of tie points, so a
#    fractional floor would false-fire. It catches only near-total removal.
HEALTH_MIN_ALIGNED_FRAC = 0.90    # aligned cameras must be >= this x baseline
HEALTH_MIN_TIEPOINTS = 1000       # near-zero floor; collapse leaves ~0, healthy ~millions
HEALTH_SCALEBAR_MAX_RATIO = 2.0   # max(|measured/defined|, inverse) must be within this
HEALTH_MAX_PASS_DROP_FRAC = 0.50  # 3a backstop: a single run-once gradual-selection
                                  # filter dropping > this of its input is anomalous
                                  # (Logan's RU/PA cutoff is 0.5, so it never trips)
LEVEL_MAX_EXTENT_M = 50.0         # stage_level sanity: a marker set spanning more than
                                  # this (transect ~10 m) means a collapsed/garbage model
# Per-phase scale-bar-sanity policy (single source of truth; ADR-0023). The metric
# scale is realized by the scale-CONSTRAINED optimize INSIDE `reduce`, so BEFORE it
# the bars are still in internal units and a coarse measured-vs-defined ratio check
# would false-fire (the 2026-06-08 `reduce:pre` false-positive). Phases BEFORE the
# reduce optimize check cameras + tie-points ONLY; phases AFTER it (model is metric)
# additionally check scale-bar sanity. `_check_network_health_or_escalate` derives
# its `check_scalebars` from this map by phase, so a call site cannot pick the wrong
# value. New phases MUST be declared here (KeyError fails closed otherwise).
HEALTH_CHECK_SCALEBARS = {
    "scale:pre":   False,  # pre-scale: bars still in internal units
    "reduce:pre":  False,  # pre-optimize: metric scale NOT yet realized (the fix)
    "reduce:post": True,   # post-optimize: bars must come out ~metric
    "level:pre":   True,   # post-reduce: model is metric
    "dense:pre":   True,
    "dsm:pre":     True,
    "ortho:pre":   True,
}
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


class PipelineSaveError(RuntimeError):
    """Raised when doc.save() does not verifiably persist to disk (the
    2026-06-04 T1 incident: a read-only open let ~2 h of align run, then the
    final save raised in read-only mode and the work was lost). A loud,
    non-zero exit here is the whole point — never let a stage report success
    when its output did not land on disk."""


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


def _metashape_lock_holder_alive() -> bool:
    """True if another LIVE Metashape run_pipeline process exists on this host.

    Metashape's project lock file records host/user (e.g. 'reef-ec2/ubuntu'),
    NOT a pid, so a lock alone cannot tell us whether a holder is still alive.
    We resolve that by scanning /proc for OTHER processes running this pipeline
    under Metashape, excluding our own session (the detached launcher ->
    metashape.sh -> python tree all share one session id via setsid). No such
    process => the lock is orphaned (a crashed/killed run), i.e. stale.

    Conservative by design: any error reading /proc is treated as 'cannot prove
    stale' for that pid and skipped; if we cannot prove a holder is alive we
    report False (stale) only when NO candidate is found."""
    try:
        my_sid = os.getsid(0)
    except OSError:
        my_sid = -1
    me = os.getpid()
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == me:
            continue
        try:
            if my_sid != -1 and os.getsid(pid) == my_sid:
                continue  # part of this run's own process tree
        except (OSError, ProcessLookupError):
            pass  # cannot determine session; fall through to cmdline check
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                cmd = fh.read().replace(b"\0", b" ").decode("utf-8", "replace").lower()
        except (OSError, ValueError):
            continue
        if "metashape" in cmd and "run_pipeline.py" in cmd:
            log(f"Live Metashape holder found: pid {pid} -> {cmd.strip()}")
            return True
    return False


def open_or_create(project_path: Path) -> Metashape.Document:
    doc = Metashape.Document()
    if project_path.exists():
        # --- Stale-lock detection BEFORE open (2026-06-04 T1 incident guard) ---
        # Metashape SILENTLY downgrades to read-only if a lock is present, then a
        # multi-hour stage fails only at the final save. Refuse to gamble on it:
        # if a lock exists, prove there is no live holder, then clear it loudly;
        # if a holder IS alive, abort clearly rather than risk a clobber.
        lock_path = project_path.with_suffix(".files") / "lock"
        if lock_path.exists():
            if _metashape_lock_holder_alive():
                sys.exit(
                    f"ABORT: {lock_path} present AND another live Metashape "
                    f"run_pipeline process exists. Refusing to open — another "
                    f"run is in progress (opening now would either fail or "
                    f"clobber it). Stop the other run, then retry.")
            log(f"WARNING: stale lock {lock_path} present but NO live Metashape "
                f"holder found — removing it (orphaned by a crashed/killed run). "
                f"This is the failure mode that cost ~2 h on 2026-06-04.")
            lock_path.unlink()
        log(f"Opening existing project {project_path}")
        doc.open(str(project_path), read_only=False)
        # --- Read-only fail-fast (the most important guard) ---
        # Even with the lock cleared, if the open still came back read-only
        # (permissions, a race, a lock re-grabbed), ABORT NOW — before any
        # compute — so we fail in ~1 s instead of after a full stage.
        if doc.read_only:
            sys.exit(
                f"ABORT: {project_path} opened READ-ONLY. Refusing to run any "
                f"stage — a read-only save raises only AFTER the compute "
                f"completes (the 2026-06-04 ~2 h loss). Resolve the lock / file "
                f"permissions and retry.")
    else:
        log(f"Creating new project {project_path}")
        project_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(project_path))
    return doc


def _project_state_mtime(project_path: Path) -> float:
    """Newest mtime across the on-disk pieces doc.save() rewrites (the .psx
    pointer and .files/project.zip). Used to PROVE a save actually landed."""
    newest = -1.0
    for p in (project_path, project_path.with_suffix(".files") / "project.zip"):
        try:
            newest = max(newest, p.stat().st_mtime)
        except OSError:
            pass
    return newest


def save(doc: Metashape.Document) -> None:
    """Save AND verify the save persisted: no exception, the project files
    exist, and their mtime advanced. A read-only/failed save must raise loudly
    here, never be swallowed (2026-06-04 T1 incident)."""
    project_path = Path(doc.path)
    before = _project_state_mtime(project_path)
    doc.save()  # raises in read-only mode — that exception MUST propagate
    after = _project_state_mtime(project_path)
    if after < 0:
        raise PipelineSaveError(
            f"doc.save() returned but no project files exist at {project_path} "
            f"(.psx / .files/project.zip missing) — save did NOT persist.")
    if after <= before:
        raise PipelineSaveError(
            f"doc.save() returned but on-disk mtime did not advance for "
            f"{project_path} (before={before}, after={after}) — the save did "
            f"NOT land. Refusing to continue on unsaved state.")
    log(f"Project saved + verified persisted (mtime advanced to {after:.0f}).")


def verify_project(project_path: Path, expect: "set[str]") -> int:
    """Reopen the project READ-ONLY and confirm the requested artifacts are
    persisted on disk. Returns 0 (PASS) / 1 (FAIL). This is the on-disk half of
    the honest completion signal: the launcher writes its COMPLETE sentinel ONLY
    when this passes, so a stage that ran but did not save can never look done.

    expect is a subset of {'aligned', 'markers'}:
      * 'aligned' -> each chunk has esm.align meta AND tie points on disk
      * 'markers' -> each chunk has esm.markers meta AND detected markers
    Opening read-only here takes NO lock, so it is safe to call right after a run."""
    if not project_path.exists():
        log(f"VERIFY FAIL: {project_path} does not exist.")
        return 1
    doc = Metashape.Document()
    try:
        doc.open(str(project_path), read_only=True)
    except Exception as exc:  # noqa: BLE001 — any reopen failure is a verify fail
        log(f"VERIFY FAIL: cannot reopen {project_path}: {exc}")
        return 1
    if not doc.chunks:
        log("VERIFY FAIL: project has no chunks.")
        return 1
    ok = True
    for chunk in doc.chunks:
        if "aligned" in expect:
            align = _meta_get(chunk, "esm.align")
            n_tp = len(chunk.tie_points.points) if chunk.tie_points else 0
            if align is None or n_tp == 0:
                log(f"VERIFY FAIL: {chunk.label}: alignment NOT persisted "
                    f"(esm.align={'present' if align else 'MISSING'}, "
                    f"tie_points={n_tp}).")
                ok = False
            else:
                log(f"VERIFY: {chunk.label}: align persisted "
                    f"({align.get('cameras_aligned')}/{align.get('cameras_enabled')} "
                    f"aligned, {n_tp:,} tie points).")
        if "markers" in expect:
            mk = _meta_get(chunk, "esm.markers")
            n_mk = len(chunk.markers)
            if mk is None or n_mk == 0:
                log(f"VERIFY FAIL: {chunk.label}: markers NOT persisted "
                    f"(esm.markers={'present' if mk else 'MISSING'}, "
                    f"markers={n_mk}).")
                ok = False
            else:
                log(f"VERIFY: {chunk.label}: markers persisted "
                    f"({n_mk} detected, ids={mk.get('detected_ids')}).")
    log("VERIFY PASS: requested artifacts are persisted on disk."
        if ok else "VERIFY FAIL: on-disk state does not match the requested artifacts.")
    return 0 if ok else 1


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
# Stage: markers  (ESM Step 7) — DETECT coded targets, then VALIDATE the layer.
# Runs between align and scale. The validation gates (a/b/c, ADR-0022) are the
# headless go/no-go: PASS emits a validated scale-bar set for the dumb stage_scale
# to apply; FAIL halts BEFORE scale and queues a GUI touchpoint (escalation). The
# human fixes markers/bars in the GUI and saves; re-running this stage validates
# the EXISTING corrected set (no re-detect) and, on PASS, lets stage_scale run.
# --------------------------------------------------------------------------- #


def _marker_id(label: str) -> int | None:
    """Coded-target numeric ID from a Metashape marker label ('marker 13' -> 13)."""
    m = re.findall(r"(\d+)", label)
    return int(m[-1]) if m else None


# --------------------------------------------------------------------------- #
# Marker-layer validation — PURE functions (no Metashape).
#
# These take plain per-marker records (the dicts _extract_marker_records builds)
# and return a structured verdict. Keeping them Metashape-free is deliberate: it
# is the highest-stakes branch added in this chat (it decides whether a layer is
# trustworthy enough to scale a 24-48 h run on), so it is unit-tested off-instance
# against synthetic fixtures the same way smoke_test._decide_focal is. The
# Metashape-touching half is confined to _extract_marker_records.
# --------------------------------------------------------------------------- #


def _num_json_safe(x):
    """Make a number safe to serialize + faithful in the report: non-finite
    residuals (inf/nan from a degenerate solve) become their string form rather
    than the non-standard 'Infinity'/'NaN' JSON tokens."""
    if isinstance(x, float) and not math.isfinite(x):
        return str(x)               # 'inf' / '-inf' / 'nan'
    return x


def _propose_bars_by_adjacency(ids: "list[int]"):
    """Pair coded-target IDs by the consecutive-ID rule: a scale bar joins targets
    whose IDs differ by 1 (e.g. 13-14, 15-16, ...). Pairs are derived purely from
    the DETECTED ids passed in — no ID set is hardcoded. Greedy left-to-right, each
    ID used once. Returns (pairs, orphans). An orphan is a marker with no
    consecutive partner — the signature of a mis-decode / spurious detection / a
    genuinely missing partner, any of which makes headless bar assignment unsafe.

    Consecutive-ID is the documented DEFAULT convention; surveys that pair targets
    by another rule need a configurable pairing strategy (a v2 item, ADR-0022) —
    until then a non-conforming layer fails closed (orphans -> gate (a))."""
    rem = sorted(set(i for i in ids if i is not None))
    pairs, orphans, i = [], [], 0
    while i < len(rem):
        if i + 1 < len(rem) and rem[i + 1] == rem[i] + 1:
            pairs.append((rem[i], rem[i + 1]))
            i += 2
        else:
            orphans.append(rem[i])
            i += 1
    return pairs, orphans


def gate_parity(records: "list[dict]") -> dict:
    """Gate (a): every reconstructed marker must pair with a consecutive-ID
    neighbour, and the count must be even. FAIL on any orphan or an odd count —
    a layer that cannot be cleanly paired cannot be scaled headless."""
    ids = sorted(r["id"] for r in records
                 if r.get("id") is not None and r.get("reconstructed"))
    pairs, orphans = _propose_bars_by_adjacency(ids)
    odd = (len(ids) % 2 == 1)
    return {
        "gate": "a_parity",
        "ok": (not orphans) and (not odd),
        "n_markers": len(ids),
        "odd_count": odd,
        "proposed_pairs": [list(p) for p in pairs],
        "orphans": orphans,
    }


def _bar_lengths(records: "list[dict]", pairs: "list") -> "list[dict]":
    """Local (pre-scale, internal-unit) length of each proposed bar. Scale-free
    so it is firewall-safe — never converted to metres."""
    pos = {r["id"]: r["pos_local"] for r in records
           if r.get("id") is not None and r.get("pos_local")}
    out = []
    for a, b in pairs:
        if a in pos and b in pos:
            pa, pb = pos[a], pos[b]
            d = math.sqrt(sum((pa[i] - pb[i]) ** 2 for i in range(3)))
            out.append({"a": a, "b": b, "len_local": d})
    return out


def _coherence_flag_reason(rec: dict, ceiling_px: float,
                           min_proj: int) -> "str | None":
    """Why this marker is NOT trustworthy for a bar, or None if it is. Fails
    CLOSED: any non-clean state (no position, no/garbage residual, too few camera
    rays, residual over the ceiling) is a flag. Order matters only for the label."""
    if not rec.get("reconstructed") or rec.get("pos_local") is None:
        return "no-3d-position"
    pc = rec.get("projection_count")
    if pc is None or pc < min_proj:
        return f"under-{min_proj}-projections"
    resid = rec.get("resid_px_median")
    if resid is None:
        return "no-residual"
    if not isinstance(resid, (int, float)) or not math.isfinite(resid):
        return "non-finite-residual"
    if resid > ceiling_px:
        return "residual-over-ceiling"
    return None


def gate_coherence(records: "list[dict]", pairs: "list", ceiling_px: float,
                   min_proj: int = GATE_MIN_MARKER_PROJECTIONS) -> dict:
    """Gate (b): each marker must be coherent — a robust reprojection residual
    under a loose ceiling, a real 3D position, and enough camera rays to triangulate.
    A lean tripwire on the RAW post-align layer (no in-gate optimize): true targets
    reproject tightly (a clean reference is well under the ceiling), an incoherent
    layer blows past it by orders of magnitude. FAILS CLOSED — a None / non-finite
    / NaN residual, a missing position, or a single-camera marker is flagged, never
    silently passed (NaN > ceiling is False, so non-finite must be checked
    explicitly). FAIL only if a flagged marker is LOAD-BEARING for a proposed bar
    (a flagged orphan is already gate (a)'s and is reported as evidence, not
    double-counted). The ceiling is the most site-dependent threshold (imaging
    conditions / turbidity vary) — recalibrate it per program."""
    flagged = []
    for r in records:
        reason = _coherence_flag_reason(r, ceiling_px, min_proj)
        if reason is not None:
            flagged.append({"id": r.get("id"),
                            "resid_px_median": _num_json_safe(r.get("resid_px_median")),
                            "projection_count": r.get("projection_count"),
                            "reason": reason})
    flagged_ids = {f["id"] for f in flagged}
    bar_ids = {x for pair in pairs for x in pair}
    load_bearing = sorted(i for i in (flagged_ids & bar_ids) if i is not None)
    return {
        "gate": "b_coherence",
        "ok": not load_bearing,
        "ceiling_px": ceiling_px,
        "min_projections": min_proj,
        "flagged": flagged,
        "flagged_ids": sorted(i for i in flagged_ids if i is not None),
        "load_bearing_flagged": load_bearing,
    }


def gate_sufficiency(validated_bars: "list", min_bars: int) -> dict:
    """Gate (d): a headless PASS needs >= min_bars VALIDATED bars (both endpoints
    coherent). The fail-closed floor: zero/one marker, all-flagged, or a single
    surviving bar (which makes gate (c)'s ratio a vacuous 1.0) all land here and
    ESCALATE rather than scale unchecked."""
    n = len(validated_bars)
    return {"gate": "d_sufficiency", "ok": n >= min_bars,
            "n_validated_bars": n, "min_validated_bars": min_bars}


def gate_consistency(bar_lengths: "list[float]", max_ratio: float) -> dict:
    """Gate (c): the proposed bars are all the same physical length, so their local
    lengths must agree. FAIL if max/min ratio exceeds the tolerance. Compares a
    RATIO, so it is scale-free — it needs no bar-length value and generalizes across
    programs as-is (and never converts to metres -> firewall-safe). Needs >=2 bars
    to compare; with fewer it abstains (gate (d)'s minimum catches a too-thin set)."""
    lens = [b for b in bar_lengths if b and b > 0]
    if len(lens) < 2:
        return {"gate": "c_consistency", "ok": True, "ratio": None,
                "n_bars": len(lens), "abstained": True}
    ratio = max(lens) / min(lens)
    return {"gate": "c_consistency", "ok": ratio <= max_ratio,
            "ratio": round(ratio, 4), "max_ratio": max_ratio,
            "n_bars": len(lens),
            "lengths": [round(x, 6) for x in lens]}


def validate_markers(records: "list[dict]", *, resid_ceiling: float,
                     interbar_ratio_max: float,
                     min_validated_bars: int = GATE_MIN_VALIDATED_BARS,
                     min_projections: int = GATE_MIN_MARKER_PROJECTIONS) -> dict:
    """Run all four gates, aggregate, and return ONE verdict. Every gate always
    runs (findings aggregated, not short-circuited) so the escalation report names
    everything wrong at once. FAILS CLOSED: `passed` is the AND of all gates AND
    requires >= min_validated_bars surviving bars, so a degenerate layer (zero/one
    marker, all-flagged, a single bar) ESCALATES rather than scaling unchecked.

    A VALIDATED bar is a proposed consecutive-ID pair whose BOTH endpoints are
    present and coherent (not flagged by gate (b)). Gate (c)'s ratio and gate (d)'s
    count are computed over those survivors — never over bars that lean on a
    flagged marker. The emitted scale-bar set is exactly the validated bars."""
    ga = gate_parity(records)
    pairs = [tuple(p) for p in ga["proposed_pairs"]]
    candidate = _bar_lengths(records, pairs)
    gb = gate_coherence(records, pairs, resid_ceiling, min_projections)
    flagged_ids = set(gb["flagged_ids"])
    validated = [b for b in candidate
                 if b["a"] not in flagged_ids and b["b"] not in flagged_ids]
    # Gate (c) compares ALL candidate-bar lengths — a wrong length is itself the
    # mispairing signal, so it must see a bar even when an endpoint is also flagged.
    # Gate (d) counts only the VALIDATED survivors (coherent endpoints) — the
    # fail-closed sufficiency floor. On any real PASS no marker is flagged, so
    # validated == candidate.
    gc = gate_consistency([b["len_local"] for b in candidate], interbar_ratio_max)
    gd = gate_sufficiency(validated, min_validated_bars)
    suspect = sorted(set(ga["orphans"]) | set(gb["load_bearing_flagged"]))
    passed = ga["ok"] and gb["ok"] and gc["ok"] and gd["ok"]
    return {
        "passed": passed,
        "gates": {ga["gate"]: ga, gb["gate"]: gb, gc["gate"]: gc, gd["gate"]: gd},
        "proposed_pairs": ga["proposed_pairs"],
        "candidate_bars": [{"a": b["a"], "b": b["b"],
                            "len_local": round(b["len_local"], 6)} for b in candidate],
        "validated_bars": [{"a": b["a"], "b": b["b"],
                            "len_local": round(b["len_local"], 6)} for b in validated],
        "n_markers": ga["n_markers"],
        "suspect_ids": suspect,
        "thresholds": {"resid_ceiling_px": resid_ceiling,
                       "interbar_ratio_max": interbar_ratio_max,
                       "min_validated_bars": min_validated_bars,
                       "min_projections": min_projections,
                       "calibration_note": "Defaults calibrated on a known-good "
                                           "reference transect; recalibrate the "
                                           "coherence ceiling per site (imaging "
                                           "conditions differ). The inter-bar ratio "
                                           "is scale-free and generalizes as-is."},
    }


def _extract_marker_records(chunk: "Metashape.Chunk") -> "list[dict]":
    """Per-marker records the validation gates consume, read from the chunk's
    CURRENT (post-align) solution. For each marker: coded ID, whether it
    reconstructed, projection count, the image labels it was detected in (the
    escalation report's 'which images each suspect marker spans'), the robust
    (median) reprojection residual in PIXELS, and the internal-unit position
    (pre-scale; pairwise norms are the scale-free local bar lengths).

    Residuals are RAW — NO optimizeCameras. The in-memory optimize was a one-off
    diagnostic probe; production gate (b) is a loose tripwire on the as-detected
    layer, not a research instrument (ADR-0022)."""
    recs = []
    for m in chunk.markers:
        pos = m.position
        errs, images = [], []
        if pos is not None:
            for cam in chunk.cameras:
                if not cam.transform:
                    continue
                proj = m.projections[cam]
                if proj is None:
                    continue
                images.append(cam.label)
                predicted = cam.project(pos)      # world point -> image px (2D)
                if predicted is None:
                    continue                       # behind the camera
                c = proj.coord
                errs.append(((c.x - predicted.x) ** 2
                             + (c.y - predicted.y) ** 2) ** 0.5)
        recs.append({
            "id": _marker_id(m.label),
            "label": m.label,
            "reconstructed": pos is not None,
            "projection_count": len(images),
            "resid_px_median": round(_median(errs), 4) if errs else None,
            "resid_px_max": round(max(errs), 4) if errs else None,
            "pos_local": [pos.x, pos.y, pos.z] if pos is not None else None,
            "images": images,
        })
    return recs


def _detect_markers(chunk: "Metashape.Chunk", ignore_sanity: bool,
                    expected_ids: "set[int] | None",
                    expected_markers: int | None) -> None:
    """Detect coded targets headless (ESM Step 7) with AUTO-TOLERANCE — the
    headless form of ESM's manual "start at 20, increase until all detected"
    (start strict, loosen). Writes esm.markers detection stats. Does NOT save —
    the caller saves once after validation.

    ACCEPT BY IDENTITY, not count: because increasing tolerance adds detections
    MONOTONICALLY (including false positives), `count == expected` can stop on a
    wrong mix (7 real + 1 spurious). So:
      * --expected-marker-ids: stop at the LOWEST tolerance where the full expected
        coded-ID set is present; FAIL LOUD at the cap if incomplete; flag any
        unexpected detected IDs as possible false positives.
      * else --expected-markers N: weaker COUNT criterion (stop at >= N), warns.
      * else: plateau (heuristic), warns.
    No per-transect tolerance is pinned. This is detection completeness — a
    SEPARATE, earlier concern than the (a/b/c) geometry validation that follows."""
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
        history.append({"tolerance": tol, "detected": n, "ids": sorted(ids)})
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
    _meta_set(chunk, "esm.markers", {
        "markers_detected": len(chunk.markers),
        "final_tolerance": tol,
        "detected_ids": sorted(detected_ids),
        "expected_ids": sorted(expected_ids) if expected_ids else None,
        "missing_ids": missing,
        "unexpected_ids": unexpected,
        "expected_markers": expected_markers,
        "tolerance_history": history,
        "seconds": round(time.time() - t0, 1),
    })
    log(f"{chunk.label}: detected {len(chunk.markers)} markers (final tolerance "
        f"{tol}); missing={missing} unexpected={unexpected}.")
    if expected_ids is not None and missing:
        alarm(f"{chunk.label}: expected coded targets {missing} NOT detected up "
              f"to tolerance {PARAMS.marker_tolerance_max}. A marker-poor "
              f"transect feeds a weak level plane — refusing to proceed. Check "
              f"target visibility/quality.", critical=True, ignore=ignore_sanity)
    if unexpected:
        alarm(f"{chunk.label}: unexpected coded IDs {unexpected} detected — "
              f"possible FALSE POSITIVES that would corrupt the level-plane fit "
              f"/ scale-bar pairing. Review before scaling.",
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


def _markers_provenance_dir(chunk: "Metashape.Chunk", out_root: Path) -> Path:
    d = out_root / chunk.label
    d.mkdir(parents=True, exist_ok=True)
    return d


def stage_markers(doc: Metashape.Document, ignore_sanity: bool,
                  expected_ids: "set[int] | None",
                  expected_markers: int | None, out_root: Path,
                  resid_ceiling: float, interbar_ratio_max: float,
                  min_validated_bars: int = GATE_MIN_VALIDATED_BARS,
                  bar_length: float = PARAMS.scalebar_length_m) -> None:
    """ESM Step 7 + the headless marker-layer gate (ADR-0022). For each chunk:

      1. If the layer already PASSED validation -> skip (idempotent re-run).
      2. DETECT coded targets, but ONLY when no markers exist yet. On RE-ENTRY the
         human has corrected markers/scale bars in the GUI and saved; we must
         validate the EXISTING set, never re-detect (which would discard the fix).
      3. VALIDATE via gates (a) parity, (b) coherence, (c) inter-bar consistency
         (all run, findings aggregated).
      4. PASS  -> emit a validated scale-bar set (the artifact stage_scale applies)
                  + a headless-pass provenance record. STOP before scale (the
                  scale apply is its own stage; dense never auto-starts).
         FAIL  -> write a structured escalation report + an awaiting-manual
                  provenance record, persist, then HALT (critical alarm) BEFORE
                  scale / optimize / dense, queuing the GUI touchpoint.

    Fails CLOSED throughout: any exception while extracting/validating writes an
    escalation report and halts; it can never fall through to a PASS/scale."""
    for chunk in doc.chunks:
        # Capture the PRIOR validation state BEFORE we overwrite it: a PASS that
        # follows a prior escalation is a human-corrected re-entry, recorded
        # distinctly from a zero-touch headless PASS (provenance integrity).
        prior_val = _meta_get(chunk, "esm.markers_validation")
        if prior_val is not None and prior_val.get("status") == "headless-pass":
            log(f"{chunk.label}: marker layer already validated (headless-pass); "
                f"skipping. Next: --stage scale.")
            continue

        if not chunk.markers:
            _detect_markers(chunk, ignore_sanity, expected_ids, expected_markers)
        else:
            log(f"{chunk.label}: {len(chunk.markers)} markers already present — "
                f"RE-ENTRY path: validating the EXISTING (GUI-corrected) layer, "
                f"no re-detect.")

        try:
            recs = _extract_marker_records(chunk)
            verdict = validate_markers(
                recs, resid_ceiling=resid_ceiling,
                interbar_ratio_max=interbar_ratio_max,
                min_validated_bars=min_validated_bars,
                min_projections=GATE_MIN_MARKER_PROJECTIONS)
        except Exception as exc:                       # fail CLOSED, never pass
            _write_extraction_failure(chunk, out_root, exc)
            save(doc)
            alarm(f"{chunk.label}: marker extraction/validation raised "
                  f"{type(exc).__name__}: {exc}. Halting BEFORE scale (fail-closed) "
                  f"— see the escalation report; resolve and re-run --stage markers.",
                  critical=True, ignore=ignore_sanity)
            continue

        if verdict["passed"]:
            _emit_validated_scalebars(chunk, out_root, recs, verdict, bar_length,
                                      prior_val)
        else:
            _write_escalation_report(chunk, out_root, recs, verdict)

        save(doc)   # persist validation status + (escalation case) the report meta

        if not verdict["passed"]:
            failed = [g for g, r in verdict["gates"].items() if not r["ok"]]
            alarm(f"{chunk.label}: marker layer FAILED headless validation "
                  f"(gates: {', '.join(failed)}). Halting BEFORE scale — fix the "
                  f"markers/scale bars in the GUI per the escalation report, save, "
                  f"then re-run --stage markers to re-validate.",
                  critical=True, ignore=ignore_sanity)


def _emit_validated_scalebars(chunk: "Metashape.Chunk", out_root: Path,
                              recs: "list[dict]", verdict: dict, bar_length: float,
                              prior_val: "dict | None" = None) -> None:
    """On PASS: write the validated scale-bar set (the artifact stage_scale
    consumes) + a headless-pass provenance record, and stamp esm.markers_validation
    status=headless-pass. Emits the SET only — creating the Metashape scalebars is
    stage_scale's job (clean detect/validate vs apply separation). bar_length is the
    physical bar length (m) recorded on each emitted bar.

    PROVENANCE INTEGRITY: a PASS that follows a prior ESCALATION is a human-corrected
    re-entry (marker_source=human-corrected, human_touch=gui-marker-fix, with a
    back-reference to the escalation event) and is recorded DISTINCTLY from a
    zero-touch headless PASS (marker_source=headless-auto), so the manifest can tell
    an auto-validated transect from a human-corrected one."""
    bars = [{
        "a": b["a"], "b": b["b"],
        "label": f"marker {b['a']}_marker {b['b']}",
        "defined_distance_m": bar_length,
        "accuracy_m": None,
        "len_local": b["len_local"],
    } for b in verdict["validated_bars"]]

    human_corrected = bool(prior_val) and prior_val.get("status") == "escalated"
    provenance = {
        "marker_source": "human-corrected" if human_corrected else "headless-auto",
        "human_touch": "gui-marker-fix" if human_corrected else "none",
        "prior_escalation": ({
            "failed_gates": prior_val.get("failed_gates"),
            "suspect_ids": prior_val.get("suspect_ids"),
            "report": prior_val.get("provenance"),
        } if human_corrected else None),
    }

    pdir = _markers_provenance_dir(chunk, out_root)
    (pdir / "validated_scalebars.json").write_text(json.dumps(bars, indent=2))
    record = {
        "transect": chunk.label,
        "status": "headless-pass",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "detected_ids": sorted(r["id"] for r in recs
                               if r["id"] is not None and r["reconstructed"]),
        "projection_counts": {str(r["id"]): r["projection_count"]
                              for r in recs if r["id"] is not None},
        "proposed_pairs": verdict["proposed_pairs"],
        "validated_scalebars": bars,
        "gates": verdict["gates"],
        "thresholds": verdict["thresholds"],
        **provenance,
    }
    (pdir / "markers_validation.json").write_text(json.dumps(record, indent=2))
    _meta_set(chunk, "esm.markers_validation", {
        "status": "headless-pass",
        "proposed_pairs": verdict["proposed_pairs"],
        "validated_scalebars": bars,
        "gates": verdict["gates"],
        "thresholds": verdict["thresholds"],
        "provenance": str(pdir / "markers_validation.json"),
        **provenance,
    })
    log(f"{chunk.label}: marker layer PASSED all gates ({provenance['marker_source']}) "
        f"— {len(bars)} validated scale bar(s) {[(b['a'], b['b']) for b in bars]} "
        f"emitted to {pdir / 'validated_scalebars.json'}. Next: --stage scale.")


def _write_escalation_report(chunk: "Metashape.Chunk", out_root: Path,
                             recs: "list[dict]", verdict: dict) -> None:
    """On FAIL: write the structured escalation report (all gate findings + the
    count/coherence EVIDENCE + which images each suspect marker spans) and an
    awaiting-manual provenance record; stamp esm.markers_validation
    status=escalated. The console gets a readable summary; the JSON is the durable
    artifact the human works from in the GUI. NO scale / optimize / dense runs."""
    suspect = set(verdict["suspect_ids"])
    by_id = {r["id"]: r for r in recs if r["id"] is not None}
    # Which images each SUSPECT marker spans (from our own detection) — capped in
    # the console log, full list in the JSON, so the report is readable but the
    # artifact is complete.
    suspect_images = {
        str(sid): {
            "projection_count": by_id.get(sid, {}).get("projection_count"),
            "resid_px_median": _num_json_safe(by_id.get(sid, {}).get("resid_px_median")),
            "images": by_id.get(sid, {}).get("images", []),
        } for sid in sorted(suspect)
    }
    failed = [g for g, r in verdict["gates"].items() if not r["ok"]]
    report = {
        "transect": chunk.label,
        "status": "escalated",
        "awaiting": "manual-gui-fix",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "failed_gates": failed,
        "gates": verdict["gates"],
        "detected_ids": sorted(r["id"] for r in recs
                               if r["id"] is not None and r["reconstructed"]),
        "candidate_bars": verdict["candidate_bars"],
        "suspect_ids": sorted(suspect),
        # Evidence (per brief: reported, NOT a fail-criterion):
        "evidence": {
            "projection_counts": {str(r["id"]): r["projection_count"]
                                  for r in recs if r["id"] is not None},
            "resid_px_median": {str(r["id"]): _num_json_safe(r["resid_px_median"])
                                for r in recs if r["id"] is not None},
            "suspect_marker_images": suspect_images,
        },
        "thresholds": verdict["thresholds"],
        "re_entry": ("Fix markers/scale bars in the GUI (delete spurious / "
                     "re-pair orphans), save the project, then re-run "
                     "--stage markers. Re-entry validates the EXISTING set "
                     "(no re-detect); on PASS the validated bars flow to "
                     "--stage scale."),
    }
    pdir = _markers_provenance_dir(chunk, out_root)
    (pdir / "markers_escalation.json").write_text(json.dumps(report, indent=2))
    _meta_set(chunk, "esm.markers_validation", {
        "status": "escalated",
        "failed_gates": failed,
        "gates": verdict["gates"],
        "suspect_ids": sorted(suspect),
        "thresholds": verdict["thresholds"],
        "provenance": str(pdir / "markers_escalation.json"),
    })

    # Console summary (the durable detail is in the JSON above).
    log(f"*** {chunk.label}: MARKER VALIDATION ESCALATION — awaiting manual GUI "
        f"fix. Report: {pdir / 'markers_escalation.json'}")
    log(f"    failed gates: {failed}")
    ga = verdict["gates"]["a_parity"]
    log(f"    (a) parity: n={ga['n_markers']} odd={ga['odd_count']} "
        f"orphans={ga['orphans']} pairs={ga['proposed_pairs']}")
    gb = verdict["gates"]["b_coherence"]
    log(f"    (b) coherence: ceiling={gb['ceiling_px']}px "
        f"load-bearing-flagged={gb['load_bearing_flagged']} "
        f"(flagged {len(gb['flagged'])}/{len(recs)} markers)")
    gc = verdict["gates"]["c_consistency"]
    log(f"    (c) inter-bar: ratio={gc.get('ratio')} max={gc.get('max_ratio')} "
        f"lengths={gc.get('lengths')}")
    gd = verdict["gates"]["d_sufficiency"]
    log(f"    (d) sufficiency: {gd['n_validated_bars']} validated bar(s) "
        f"(need >= {gd['min_validated_bars']})")
    for sid in sorted(suspect):
        info = suspect_images[str(sid)]
        imgs = info["images"]
        head = ", ".join(imgs[:6]) + (f", …(+{len(imgs)-6} more)" if len(imgs) > 6 else "")
        log(f"    suspect id {sid}: {info['projection_count']} projections, "
            f"median resid {info['resid_px_median']}px; spans [{head}]")


def _write_extraction_failure(chunk: "Metashape.Chunk", out_root: Path,
                              exc: Exception) -> None:
    """Fail-closed handler: an exception while extracting/validating the marker
    layer is itself an escalation. Write the report + awaiting-manual provenance
    and stamp status=escalated so the layer can NEVER be read as a pass. The
    caller halts before scale."""
    pdir = _markers_provenance_dir(chunk, out_root)
    report = {
        "transect": chunk.label,
        "status": "escalated",
        "awaiting": "manual-gui-fix",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "failed_gates": ["extraction_error"],
        "error": {"type": type(exc).__name__, "message": str(exc),
                  "traceback": traceback.format_exc()},
        "re_entry": ("Marker extraction/validation raised — the marker layer is in "
                     "an unexpected state. Inspect/repair it in the GUI, save, then "
                     "re-run --stage markers."),
    }
    (pdir / "markers_escalation.json").write_text(json.dumps(report, indent=2))
    _meta_set(chunk, "esm.markers_validation", {
        "status": "escalated",
        "failed_gates": ["extraction_error"],
        "error": {"type": type(exc).__name__, "message": str(exc)},
        "provenance": str(pdir / "markers_escalation.json"),
    })
    log(f"*** {chunk.label}: MARKER VALIDATION ESCALATION (extraction/validation "
        f"error: {type(exc).__name__}: {exc}). Report: "
        f"{pdir / 'markers_escalation.json'}")


# --------------------------------------------------------------------------- #
# NETWORK-HEALTH COLLAPSE GUARD (ADR-0023) — ONE reusable check, wired in three
# places: a within-reduce per-pass backstop (3a), a reduce post-condition (3b),
# and a pre-condition at the entry of every alignment-consuming stage (3c). HARD
# tripwire: on failure it writes a structured escalation report (same shape/role
# as the marker gate's) and HALTS, so no stage ever runs on / ships a collapsed
# model. The pure evaluator is unit-tested against synthetic states.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HealthConfig:
    """Coarse collapse-tripwire thresholds (CLI-overridable; ADR-0023)."""
    min_aligned_frac: float = HEALTH_MIN_ALIGNED_FRAC
    min_tiepoints: int = HEALTH_MIN_TIEPOINTS
    scalebar_max_ratio: float = HEALTH_SCALEBAR_MAX_RATIO
    max_pass_drop_frac: float = HEALTH_MAX_PASS_DROP_FRAC
    scalebar_defined_m: float = PARAMS.scalebar_length_m


def evaluate_network_health(state: dict, *, min_aligned: int, min_tiepoints: int,
                            scalebar_max_ratio: float,
                            check_scalebars: bool) -> dict:
    """PURE collapse evaluation (no Metashape) — unit-testable on a synthetic state.

    `state` keys: aligned, enabled, total, tie_points, baseline_aligned,
    scalebars=[{a,b,defined_m,measured_m}]. Returns {ok, failures:[...], metrics}.

    Discriminators, in priority: (1) camera survival — PRIMARY; a clean reduce does
    not de-align cameras. (2) scale-bar sanity — PRIMARY; bars stay ~defined, a
    collapse blows them to km (COARSE within-Nx, NOT the fine gate). (3) tie-point
    NEAR-ZERO tripwire — a healthy reduce legitimately sheds a large share, so this
    fires only on near-total removal, never on a fraction."""
    failures = []
    aligned = state["aligned"]
    if aligned < min_aligned:
        failures.append({"check": "camera_survival", "aligned": aligned,
                         "min_aligned": min_aligned,
                         "baseline": state.get("baseline_aligned")})
    tp = state["tie_points"]
    if tp <= min_tiepoints:
        failures.append({"check": "tiepoint_near_zero", "tie_points": tp,
                         "min_tiepoints": min_tiepoints})
    bar_metrics = []
    if check_scalebars:
        for sb in state.get("scalebars", []):
            m, d = sb.get("measured_m"), sb.get("defined_m")
            if m is None or not d or m <= 0:
                ratio = float("inf")
            else:
                r = m / d
                ratio = max(r, 1.0 / r)
            rec = {"a": sb.get("a"), "b": sb.get("b"), "measured_m": m,
                   "defined_m": d, "ratio": (ratio if math.isfinite(ratio) else None)}
            bar_metrics.append(rec)
            if not math.isfinite(ratio) or ratio > scalebar_max_ratio:
                failures.append({"check": "scalebar_sanity", "max_ratio": scalebar_max_ratio,
                                 **rec})
    return {"ok": not failures, "failures": failures,
            "metrics": {"aligned": aligned, "enabled": state.get("enabled"),
                        "tie_points": tp, "scalebars": bar_metrics}}


def _extract_network_state(chunk: "Metashape.Chunk",
                           scalebar_defined_m: float) -> dict:
    """Metashape-touching read of the collapse-relevant network state."""
    cams = list(chunk.cameras)
    enabled = [c for c in cams if getattr(c, "enabled", True)]
    aligned = sum(1 for c in enabled if c.transform is not None)
    tp = chunk.tie_points
    n_tp = len(tp.points) if tp is not None else 0
    T = chunk.transform.matrix
    bars = []
    for sb in chunk.scalebars:
        a = _marker_id(sb.point0.label) if sb.point0 else None
        b = _marker_id(sb.point1.label) if sb.point1 else None
        d = sb.reference.distance
        d = d if d is not None else scalebar_defined_m
        try:
            wa, wb = T.mulp(sb.point0.position), T.mulp(sb.point1.position)
            measured = math.sqrt((wa.x - wb.x) ** 2 + (wa.y - wb.y) ** 2
                                 + (wa.z - wb.z) ** 2)
        except Exception:
            measured = None
        bars.append({"a": a, "b": b, "defined_m": d, "measured_m": measured})
    return {"aligned": aligned, "enabled": len(enabled), "total": len(cams),
            "tie_points": n_tp, "scalebars": bars}


def _write_health_escalation(chunk: "Metashape.Chunk", out_root: Path, context: str,
                             state: dict, evaluation: dict, min_aligned: int) -> Path:
    """Structured collapse-escalation report (same shape/role as the marker gate's):
    <out_root>/<transect>/network_health_escalation.json + esm.network_health meta."""
    pdir = _markers_provenance_dir(chunk, out_root)
    failed = sorted({f["check"] for f in evaluation["failures"]})
    report = {
        "transect": chunk.label, "status": "escalated",
        "awaiting": "manual-investigation", "context": context,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "failed_checks": failed, "failures": evaluation["failures"],
        "metrics": evaluation["metrics"],
        "thresholds": {"min_aligned": min_aligned,
                       "baseline_aligned": state.get("baseline_aligned"),
                       "min_tiepoints": HEALTH_MIN_TIEPOINTS},
        "note": ("Network-health collapse tripwire (ADR-0023): the bundle is "
                 "collapsed or geometrically degenerate; downstream stages are "
                 "halted. Investigate the reduce step / restore the pre-stage "
                 "backup. HARD collapse guard, NOT the fine accuracy gate."),
    }
    (pdir / "network_health_escalation.json").write_text(json.dumps(report, indent=2))
    _meta_set(chunk, "esm.network_health", {
        "status": "escalated", "context": context, "failed_checks": failed,
        "metrics": evaluation["metrics"],
        "provenance": str(pdir / "network_health_escalation.json")})
    log(f"*** {chunk.label}: NETWORK-HEALTH COLLAPSE ESCALATION [{context}] — "
        f"failed {failed}. Report: {pdir / 'network_health_escalation.json'}")
    for f in evaluation["failures"]:
        log(f"    {f}")
    return pdir / "network_health_escalation.json"


def _check_network_health_or_escalate(chunk, out_root: Path, context: str,
                                      health: "HealthConfig", *,
                                      check_scalebars: "bool | None" = None,
                                      ignore_sanity: bool,
                                      baseline_aligned: "int | None" = None) -> dict:
    """Extract -> evaluate -> on failure write escalation report + critical alarm
    (HALT). baseline_aligned = pre-stage aligned count (3b); if None the chunk's
    enabled-camera count is the baseline (3c pre-conditions).

    `check_scalebars` defaults to the per-phase policy `HEALTH_CHECK_SCALEBARS[context]`
    (so a call site cannot pick the wrong value — the 2026-06-08 `reduce:pre` bug);
    pass an explicit bool only to override (tests). An unknown context KeyErrors —
    fail-closed: a new phase must declare its policy."""
    if check_scalebars is None:
        check_scalebars = HEALTH_CHECK_SCALEBARS[context]
    state = _extract_network_state(chunk, health.scalebar_defined_m)
    baseline = baseline_aligned if baseline_aligned is not None else state["enabled"]
    state["baseline_aligned"] = baseline
    min_aligned = int(math.floor(health.min_aligned_frac * baseline))
    ev = evaluate_network_health(
        state, min_aligned=min_aligned, min_tiepoints=health.min_tiepoints,
        scalebar_max_ratio=health.scalebar_max_ratio, check_scalebars=check_scalebars)
    if not ev["ok"]:
        _write_health_escalation(chunk, out_root, context, state, ev, min_aligned)
        alarm(f"{chunk.label}: network-health collapse guard tripped at [{context}] — "
              f"failed {sorted({f['check'] for f in ev['failures']})}. Halting (see "
              f"network_health_escalation.json; aligned {state['aligned']}/{baseline} "
              f"baseline, {state['tie_points']} tie points).",
              critical=True, ignore=ignore_sanity)
    return ev


# --------------------------------------------------------------------------- #
# Stage: scale  — DUMB applier of the validated scale-bar set (replaces the
# manual GUI scale-bar assignment step). Trusts stage_markers' verdict entirely:
# it only runs when the layer is headless-pass, then creates the Metashape
# scalebars for the validated pairs (skipping any the human already created in the
# GUI on the re-entry path). It makes NO geometric decision.
# --------------------------------------------------------------------------- #


def _neutralize_spurious_reference(chunk) -> dict:
    """Set chunk.crs to a local metric CS and disable every marker + camera
    reference.enabled (ADR-0024).

    Root: Metashape's default CRS for no-GPS captures is WGS84 (EPSG:4326).
    After updateTransform() it projects each marker's internal 3-D position
    through identity×WGS84 and stores the result as marker.reference.location
    (enabled=True).  Those coordinates are geographic garbage (latitude ≈ -90°,
    altitude ≈ -6.36e6 m).  Camera reference.location carries an identical stub
    GPS fix (all cameras at the same point, acc=None).  A subsequent
    optimizeCameras call treats these as live GCP constraints and diverges
    catastrophically (scale 1.0→823, reproj 0.15→1.3e152).

    Scale bars use their own reference.distance / reference.accuracy — not
    marker.reference.location — so they remain untouched and continue to
    constrain the bundle correctly.

    Called by stage_scale immediately after scale-bar weighting, before save.
    Idempotent: re-running on an already-LOCAL chunk is a no-op.
    """
    chunk.crs = Metashape.CoordinateSystem(_LOCAL_CS_WKT)
    n_markers, n_cameras = 0, 0
    for m in chunk.markers:
        if m.reference is not None and m.reference.enabled:
            m.reference.enabled = False
            n_markers += 1
    for c in chunk.cameras:
        if c.reference is not None and c.reference.enabled:
            c.reference.enabled = False
            n_cameras += 1
    log(f"{chunk.label}: CRS set LOCAL metre; disabled {n_markers} marker + "
        f"{n_cameras} camera reference.enabled (spurious WGS84 GCP fix; ADR-0024)")
    return {"n_markers_ref_disabled": n_markers, "n_cameras_ref_disabled": n_cameras}


def stage_scale(doc: Metashape.Document, out_root: Path, ignore_sanity: bool,
                health: "HealthConfig", bar_length: float = PARAMS.scalebar_length_m,
                scalebar_accuracy_m: float = PARAMS.scalebar_accuracy_m) -> None:
    """Apply the scale-bar set stage_markers validated. Requires
    esm.markers_validation status=headless-pass (refuses otherwise — scaling an
    un-validated/escalated layer is exactly what the gate exists to prevent).
    Idempotent: re-pairs only what is missing, so GUI-created bars are reused.
    Each bar's reference distance is the length recorded on that bar in the
    validated set (what stage_markers emitted), falling back to bar_length. Does
    NOT optimize/level/dense — those are downstream stages (dense never auto-starts)."""
    for chunk in doc.chunks:
        val = _meta_get(chunk, "esm.markers_validation")
        status = val.get("status") if val else None
        if status != "headless-pass":
            alarm(f"{chunk.label}: marker layer not validated for headless scaling "
                  f"(status={status}). Run --stage markers to a PASS first; if it "
                  f"escalated, fix the markers in the GUI per the escalation report "
                  f"and re-validate.", critical=True, ignore=ignore_sanity)
            continue
        if _meta_get(chunk, "esm.scale") is not None:
            log(f"{chunk.label}: scale bars already applied; skipping.")
            continue
        # 3c PRE-condition: don't scale a collapsed model. Pre-scale, so the bars
        # are still in internal units (scalebar sanity would false-fire) — check
        # camera survival + tie points only.
        _check_network_health_or_escalate(chunk, out_root, "scale:pre", health,
                                          ignore_sanity=ignore_sanity)  # policy: no bar check pre-scale
        by_id = {_marker_id(m.label): m for m in chunk.markers
                 if m.position is not None}
        existing = {frozenset((sb.point0.label, sb.point1.label))
                    for sb in chunk.scalebars if sb.point0 and sb.point1}
        # Apply exactly the validated set markers emitted (each carries its own
        # defined_distance_m); fall back to bar_length for any bar that lacks it.
        validated = val.get("validated_scalebars") or [
            {"a": p[0], "b": p[1]} for p in val.get("proposed_pairs", [])]
        created, reused, problems, lengths = [], [], [], set()
        for bar in validated:
            a, b = bar["a"], bar["b"]
            dist = bar.get("defined_distance_m")
            if dist is None:
                dist = bar_length
            ma, mb = by_id.get(a), by_id.get(b)
            if ma is None or mb is None:
                problems.append([a, b])
                continue
            key = frozenset((ma.label, mb.label))
            if key in existing:
                reused.append([a, b])
                continue
            sb = chunk.addScalebar(ma, mb)
            sb.reference.distance = dist
            lengths.add(dist)
            created.append([a, b])
        if problems:
            alarm(f"{chunk.label}: validated pair(s) {problems} reference markers "
                  f"absent from the chunk — the layer changed since validation. "
                  f"Re-run --stage markers to re-validate before scaling.",
                  critical=True, ignore=ignore_sanity)
        # Weight every bar (created AND GUI-reused) so the downstream optimize uses
        # the scale bars as ACTIVE constraints at a defined accuracy (ADR-0023; they
        # were `None` = active-but-unweighted on the human-corrected EDR_T1 bars).
        for sb in chunk.scalebars:
            sb.reference.accuracy = scalebar_accuracy_m
        # Neutralise the spurious WGS84 chunk.crs and disable garbage marker/camera
        # reference locations before saving, so the first downstream optimizeCameras
        # (inside Logan reduce) sees a clean local-metric frame, not geographic GCPs
        # that diverge the bundle (scale 1.0->823, ADR-0024).
        ref_info = _neutralize_spurious_reference(chunk)
        _meta_set(chunk, "esm.scale", {
            "bars_created": created,
            "bars_reused_from_gui": reused,
            "scalebar_lengths_m": sorted(lengths),
            "scalebar_accuracy_m": scalebar_accuracy_m,
            "total_scalebars": len(chunk.scalebars),
            "source": "stage_markers headless-pass validated set",
            **ref_info,
        })
        log(f"{chunk.label}: applied scale bars — created {created}, reused "
            f"{reused} (GUI); {len(chunk.scalebars)} scale bar(s) total "
            f"@ {sorted(lengths) or [bar_length]} m. Next: --stage reduce (ESM Step 8).")
        save(doc)


# --------------------------------------------------------------------------- #
# Stage: reduce  (ESM Step 8) — error reduction; runs AFTER scale-bar assignment
# --------------------------------------------------------------------------- #


def stage_reduce(doc: Metashape.Document, out_root: Path, logan_module: "str | None",
                 ignore_sanity: bool, health: "HealthConfig") -> None:
    """ESM Step 8 error reduction via the vendored USGS Logan v2.0 routine (ADR-0023;
    replaces the home-grown one-shot transcription that collapsed EDR_T1). Runs AFTER
    Step 7 scale-bar assignment so the optimize is scale-constrained (Toth's order).

    Guarded by the network-health collapse tripwire on every side: a 3c PRE-condition
    (refuse to run on an already-collapsed model — using the LIVE aligned count, not
    the stale align meta that let the old level stage proceed on wreckage), a 3a
    within-reduce per-pass backstop (inside _run_logan_reduction), and a 3b
    POST-condition that must pass BEFORE esm.reduce success is written or saved."""
    for chunk in doc.chunks:
        if _meta_get(chunk, "esm.reduce") is not None:
            log(f"{chunk.label}: error reduction already done; skipping.")
            continue
        # 3c PRE-condition: never reduce a collapsed model. Scale-bar sanity is NOT
        # checked here — the metric scale is realized by the optimize INSIDE reduce,
        # so pre-reduce the bars are still in internal units (policy reduce:pre=False,
        # cf. scale:pre). The reduce:post check validates they came out metric.
        _check_network_health_or_escalate(chunk, out_root, "reduce:pre", health,
                                          ignore_sanity=ignore_sanity)
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
        aligned_before = sum(1 for c in chunk.cameras
                             if getattr(c, "enabled", True) and c.transform is not None)
        tp_before = _tp_count(chunk)

        path = _run_logan_reduction(chunk, out_root, health, ignore_sanity, logan_module)

        rms_post, _ = _reprojection_rms(chunk)
        # 3b POST-condition (success-tied): assert the network survived BEFORE writing
        # any success meta or saving. Camera-survival is vs the PRE-reduce aligned count.
        _check_network_health_or_escalate(chunk, out_root, "reduce:post", health,
                                          ignore_sanity=ignore_sanity,
                                          baseline_aligned=aligned_before)
        aligned_after = sum(1 for c in chunk.cameras
                            if getattr(c, "enabled", True) and c.transform is not None)
        stats = {
            "reduction_path": path,
            "scalebars_present": n_sb,
            "aligned_before": aligned_before,
            "aligned_after": aligned_after,
            "tie_points_before": tp_before,
            "tie_points_after": _tp_count(chunk),
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
        log(f"{chunk.label}: error reduction via '{path}' with {n_sb} scale bar(s); "
            f"aligned {aligned_before} -> {aligned_after}; tie points {tp_before:,} "
            f"-> {stats['tie_points_after']:,}; RMS(filter units) "
            f"{stats['reproj_rms_pre_filter_units']} -> {stats['reproj_rms_post_filter_units']}")
        save(doc)


def _assert_vendored_logan_identity(src_text: str, path: "Path") -> None:
    """Vendor-time IDENTITY check (ADR-0023): the vendored USGS Logan routine MUST be
    the Metashape-2.0.x port (uses `tie_points`), not the DOI-cited v2.0 *tag* which
    is the 1.6-1.8 / `point_cloud` artifact and crashes on our 2.3.1 build. The first
    vendoring (3ec2789) pinned that mislabeled 1.x file; this guard catches such a
    swap at LOAD time (loud), never during a live reduce. See PROVENANCE.md."""
    problems = []
    if "Metashape.TiePoints.Filter" not in src_text:
        problems.append("missing the 2.x `Metashape.TiePoints.Filter` API")
    if "Metashape.PointCloud.Filter" in src_text or "chunk.point_cloud.points" in src_text:
        problems.append("uses the pre-2.0 `point_cloud` sparse API (1.6-1.8 artifact)")
    if "for Agisoft Metashape 2.0" not in src_text:
        problems.append("header does not declare target 'Agisoft Metashape 2.0'")
    if problems:
        raise RuntimeError(
            f"vendored Logan at {path} failed the 2.x identity check "
            f"({'; '.join(problems)}). This looks like the mislabeled v2.0-TAG "
            f"(Metashape 1.6-1.8) artifact, which crashes on 2.3.1. Re-vendor the "
            f"commit-pinned 2.0.x port per vendor/logan_usgs/PROVENANCE.md. Halting "
            f"rather than running a wrong/incompatible reduce.")


def _vendored_logan_module():
    """Import the pinned USGS Logan v2.0 (Metashape-2.0.x port) module BY FILE PATH
    (no sys.path mutation). Import-safe: every statement in it is under a def/class or
    `if __name__ == '__main__'`, so importing only needs `import Metashape` to resolve
    (true under metashape.sh). Runs a vendor-time identity check first so a mislabeled
    1.x artifact halts loudly here, not mid-reduce. See vendor/logan_usgs/PROVENANCE.md
    (ADR-0023)."""
    import importlib.util
    p = (Path(__file__).resolve().parent / "vendor" / "logan_usgs"
         / "Align_RuPaRe_v2_Metashape.py")
    if not p.exists():
        raise FileNotFoundError(f"vendored Logan module missing at {p}")
    _assert_vendored_logan_identity(p.read_text(), p)
    spec = importlib.util.spec_from_file_location("logan_usgs_align_rupare", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, str(p)


def _logan_cam_opt(params=("f", "cx", "cy", "k1", "k2", "k3", "p1", "p2")) -> dict:
    """The 12-key cal_* dict the Logan filter functions pass to optimizeCameras
    (every key must exist or its lookups KeyError). Default = the ESM/USGS lens
    set (f,cx,cy,k1,k2,k3,p1,p2 on; b1,b2,k4 off)."""
    d = {f"cal_{k}": False for k in
         ("f", "cx", "cy", "b1", "b2", "k1", "k2", "k3", "k4", "p1", "p2")}
    d["fit_corrections"] = False
    for p in params:
        d[f"cal_{p}"] = True
    return d


def _tp_count(chunk) -> int:
    tp = chunk.tie_points
    return len(tp.points) if tp is not None else 0


def _run_logan_reduction(chunk, out_root: Path, health: "HealthConfig",
                         ignore_sanity: bool, logan_module: "str | None") -> str:
    """ESM Step 8 error reduction via the vendored USGS Logan v2.0 routine
    (RU 30 -> PA 3.5 -> RE 0.3): capped per-iteration gradual selection with camera
    optimization between iterations and a final fit-additional-corrections optimize.
    Replaces the removed home-grown _run_builtin_reduction, whose one-shot hard cuts
    collapsed EDR_T1 (ADR-0023). `logan_module` overrides the vendored copy with an
    importable module name (kept for testing / a future re-pin).

    3a WITHIN-REDUCE BACKSTOP: the run-once RU/PA filters cap deletion at *_cutoff
    (0.5); a single such filter dropping > health.max_pass_drop_frac of its input is
    anomalous (Logan never should) -> escalate BEFORE the cloud is destroyed. RE
    iterates by RMSE and may legitimately shed a large CUMULATIVE share, so it is
    NOT fraction-gated here — the 3b post-condition covers it (per the calibration
    that a fractional tie-point floor false-fires on a healthy reduce)."""
    if logan_module:
        import importlib
        mod, src = importlib.import_module(logan_module), logan_module
    else:
        mod, src = _vendored_logan_module()
    orig_label = chunk.label   # Logan appends _Ru/_Pa/_Re<level>; restore after.
    cam_opt = _logan_cam_opt()
    ru, pa, re_ = (PARAMS.reconstruction_uncertainty, PARAMS.projection_accuracy,
                   PARAMS.reprojection_error)
    log(f"{orig_label}: Logan error reduction (vendored {Path(src).name if not logan_module else src}) "
        f"RU={ru} -> PA={pa} -> RE={re_}; per-iteration cutoffs 0.5/0.5/0.1")

    def _capped_pass(name, fn, *args, **kwargs):
        before = _tp_count(chunk)
        fn(*args, **kwargs)
        after = _tp_count(chunk)
        frac = ((before - after) / before) if before else 0.0
        log(f"{orig_label}: Logan {name}: {before:,} -> {after:,} tie points "
            f"(dropped {before - after:,} = {frac * 100:.1f}% of pass input)")
        if frac > health.max_pass_drop_frac:
            chunk.label = orig_label
            state = _extract_network_state(chunk, health.scalebar_defined_m)
            state["baseline_aligned"] = None
            ev = {"ok": False, "metrics": {"tie_points": after},
                  "failures": [{"check": "pass_drop", "pass": name,
                                "dropped_frac": round(frac, 4),
                                "max_pass_drop_frac": health.max_pass_drop_frac,
                                "tie_points_before": before,
                                "tie_points_after": after}]}
            _write_health_escalation(chunk, out_root, f"reduce:pass:{name}",
                                     state, ev, min_aligned=-1)
            alarm(f"{orig_label}: Logan {name} dropped {frac * 100:.1f}% of tie "
                  f"points in one filter (> {health.max_pass_drop_frac * 100:.0f}% "
                  f"backstop) — anomalous; halting before the cloud is destroyed.",
                  critical=True, ignore=ignore_sanity)

    # compute_rmse=False on all three (ADR-0023): the vendored Logan's compute_RMSE
    # calls camera.error(point, proj).norm() unguarded, and on Metashape 2.3.1 that
    # returns None for an aligned camera whose (post-optimize) point no longer
    # reprojects (a 2.0.x->2.3.1 Camera.error gap; hit T1's geometry, not T3's). With
    # compute_rmse=False (a documented Logan mode, lines 980-984) RU/PA skip the
    # diagnostic RMSE only, and RE iterates by the THRESHOLD criterion — deleting
    # until no tie point exceeds RE (0.3 px), i.e. ESM Table S2 "Reprojection Error
    # 0.3". We report the reduce RMSE independently via _reprojection_rms (which reads
    # TiePoints.Filter.values, not camera.error, so it is None-safe).
    # RU / PA: run-once (iterate_to_level=False), 50% cutoff — fraction-gated (3a).
    _capped_pass("RU", mod.reconstruction_uncertainty, chunk, ru, 0.50, 0.1,
                 cam_opt, ru_iterate_to_ru_level=False, compute_rmse=False)
    _capped_pass("PA", mod.projection_accuracy, chunk, pa, 0.50, 0.1,
                 cam_opt, pa_iterate_to_pa_level=False, compute_rmse=False)
    # RE: iterate to the RE-threshold (0.3 px) criterion, 10% cutoff, final optimize
    # with additional corrections. NOT fraction-gated (legitimately sheds a large
    # cumulative share).
    before = _tp_count(chunk)
    mod.reprojection_error(chunk, re_, 0.10, 0.01, cam_opt,
                           PARAMS.fit_additional_after_reduction,
                           final_tie_point_accuracy=re_, compute_rmse=False,
                           early_stop=False)
    after = _tp_count(chunk)
    chunk.label = orig_label
    log(f"{orig_label}: Logan RE: {before:,} -> {after:,} tie points "
        f"(dropped {before - after:,}); final optimize fit_corrections="
        f"{PARAMS.fit_additional_after_reduction}")
    return (f"logan_vendored:{Path(src).name}" if not logan_module
            else f"logan:{src}")


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


def _compute_level_up(
    mk_positions: list[list[float]],
    cam_boresights: list[list[float]],
    collinear_threshold: float = LEVEL_COLLINEAR_THRESHOLD,
    nadir_guard_deg: float = LEVEL_NADIR_GUARD_DEG,
) -> tuple[list[float], str, dict]:
    """Determine the UP direction for leveling (ADR-0025).

    Uses camera-nadir (negated mean camera boresight) when the marker layout is
    near-collinear (spread_ratio < collinear_threshold) OR when the marker-plane
    normal and camera-nadir disagree by > nadir_guard_deg (nadir_guard_fired).
    The nadir_guard case is an escalation condition — callers must alarm on it.
    Otherwise uses the marker-plane normal (normal case: well-spread markers).

    Args:
        mk_positions: world-frame marker positions.
        cam_boresights: world-frame unit camera boresight vectors (camera +Z axis).
        collinear_threshold: spread_ratio floor below which collinear guard fires.
        nadir_guard_deg: maximum acceptable angle between marker normal and cam_up.

    Returns:
        up_vec: unit vector pointing physically UP in the current world frame.
        method: "camera_nadir" or "marker_plane".
        info: diagnostic dict (spread_ratio, nadir_angle_deg, guard flags, eig, …).
    """
    normal, _, eig = _fit_plane_normal(mk_positions)
    # Camera nadir UP: negate the mean boresight (cameras point DOWN → -b = UP).
    n_cams = len(cam_boresights)
    mean_b = [sum(b[i] for b in cam_boresights) / n_cams for i in range(3)]
    bL = math.sqrt(sum(x * x for x in mean_b)) or 1.0
    cam_up = [-mean_b[i] / bL for i in range(3)]
    # Apply same +Z convention as _fit_plane_normal so the angle comparison is valid.
    if cam_up[2] < 0:
        cam_up = [-x for x in cam_up]
    # Collinearity: in-plane minor / major scatter ratio (eig sorted descending).
    spread_ratio = eig[1] / eig[0] if eig[0] > 0 else 0.0
    # Angle between marker-plane normal and camera-nadir UP (both +Z-oriented).
    dot = max(-1.0, min(1.0, sum(normal[i] * cam_up[i] for i in range(3))))
    nadir_angle_deg = math.degrees(math.acos(dot))
    collinear_guard = spread_ratio < collinear_threshold
    # nadir_guard only fires when markers are NOT collinear (else collinear_guard
    # already explains the divergence and is the primary signal).
    nadir_guard = (not collinear_guard) and (nadir_angle_deg > nadir_guard_deg)
    up_vec = cam_up if (collinear_guard or nadir_guard) else normal
    method = "camera_nadir" if (collinear_guard or nadir_guard) else "marker_plane"
    return up_vec, method, {
        "spread_ratio": round(spread_ratio, 5),
        "nadir_angle_deg": round(nadir_angle_deg, 3),
        "collinear_guard_fired": collinear_guard,
        "nadir_guard_fired": nadir_guard,
        "marker_normal": [round(x, 5) for x in normal],
        "cam_up": [round(x, 5) for x in cam_up],
        "eig": eig,
    }


def stage_level(doc: Metashape.Document, out_root: Path, ignore_sanity: bool,
                health: "HealthConfig",
                max_extent_m: float = LEVEL_MAX_EXTENT_M) -> None:
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
        # 3c PRE-condition (ADR-0023): refuse to level a collapsed model. This reads
        # the LIVE aligned-camera count + scale-bar sanity — unlike the legacy guard
        # below, which read the STALE esm.align rate and so happily leveled the
        # 86-camera EDR_T1 wreckage (markers spanning ~3000 km) on 2026-06-08.
        _check_network_health_or_escalate(chunk, out_root, "level:pre", health,
                                          ignore_sanity=ignore_sanity)
        # Legacy pre-level alignment guard (kept; now backed by the live check above).
        align = _meta_get(chunk, "esm.align") or {}
        rate = align.get("alignment_rate")
        if rate is not None and rate < GATE_MIN_ALIGN_RATE_FOR_LEVEL:
            alarm(f"{chunk.label}: alignment rate {rate*100:.1f}% < "
                  f"{GATE_MIN_ALIGN_RATE_FOR_LEVEL*100:.0f}% — too poor to level "
                  f"reliably. Resolve alignment before stage_level.",
                  critical=True, ignore=ignore_sanity)
        T = chunk.transform.matrix
        mk = {m.label: m.position for m in chunk.markers if m.position is not None}
        # Extent sanity: a collapsed/degenerate model spreads its markers over km.
        # Refuse to fit a level plane to a physically impossible marker cloud.
        wpts = [_world_xyz(T, p) for p in mk.values()]
        if wpts:
            extent = max(max(p[i] for p in wpts) - min(p[i] for p in wpts)
                         for i in range(3))
            if extent > max_extent_m:
                alarm(f"{chunk.label}: marker set spans {extent:.1f} m "
                      f"(> {max_extent_m} m plausible transect extent, ~10 m) — the "
                      f"model is collapsed/degenerate; refusing to level.",
                      critical=True, ignore=ignore_sanity)
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
        mk_world = [_world_xyz(T, mk[lab]) for lab in vlist]
        # Camera boresights in world space: used by _compute_level_up (ADR-0025).
        # cam.transform maps camera → chunk; camera +Z is the boresight direction.
        cam_boresights_w: list[list[float]] = []
        for cam in chunk.cameras:
            if cam.transform is None:
                continue
            bc = cam.transform.mulv(Metashape.Vector([0.0, 0.0, 1.0]))
            bw = [T[r, 0] * bc.x + T[r, 1] * bc.y + T[r, 2] * bc.z
                  for r in range(3)]
            bL = math.sqrt(sum(x * x for x in bw)) or 1.0
            cam_boresights_w.append([x / bL for x in bw])
        up_vec, level_method, level_info = _compute_level_up(
            mk_world, cam_boresights_w)
        normal = level_info["marker_normal"]
        eig = level_info["eig"]
        # Planarity guard: catches volumetric/degenerate sets regardless of method.
        flatness = (eig[2] / eig[1]) if eig[1] > 0 else float("inf")
        if flatness > GATE_PLANE_FLATNESS_MAX:
            alarm(f"{chunk.label}: vetted markers are non-planar "
                  f"(eig2/eig1 {flatness:.4f} > {GATE_PLANE_FLATNESS_MAX}) — "
                  f"model is degenerate.",
                  critical=True, ignore=ignore_sanity)
        # nadir_guard: well-spread markers but cameras disagree → escalate.
        if level_info["nadir_guard_fired"]:
            alarm(f"{chunk.label}: marker-plane normal and camera-nadir UP disagree "
                  f"by {level_info['nadir_angle_deg']:.1f}° "
                  f"(> {LEVEL_NADIR_GUARD_DEG}°, spread_ratio="
                  f"{level_info['spread_ratio']:.3f}) — using camera-nadir as "
                  f"fallback; investigate marker geometry.",
                  critical=True, ignore=ignore_sanity)
        if level_info["collinear_guard_fired"]:
            log(f"{chunk.label}: near-collinear markers "
                f"(spread_ratio={level_info['spread_ratio']:.4f} < "
                f"{LEVEL_COLLINEAR_THRESHOLD}) — using camera-nadir UP.")
        tilt_before = _tilt_from_z(up_vec)
        R = _rot_normal_to_z(up_vec)
        _apply_world_rotation(chunk, R)
        # Post-level verification.
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
            "level_method": level_method,
            "level_spread_ratio": level_info["spread_ratio"],
            "level_nadir_angle_deg": level_info["nadir_angle_deg"],
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
            f"(excluded {len(excluded)} bar(s)); method={level_method}; "
            f"tilt {tilt_before:.2f} -> {tilt_after:.3f} deg; "
            f"scale {scale_after:.8g} (preserved={stats['scale_preserved']}).")
        if not stats["scale_preserved"]:
            alarm(f"{chunk.label}: leveling changed transform.scale "
                  f"({scale_before} -> {scale_after}). A pure rotation must "
                  f"preserve scale — fit/rotation bug.",
                  critical=True, ignore=ignore_sanity)
        # Tilt gate: for marker_plane leveling, marker tilt after must be ~0.
        # For camera_nadir leveling, the reef-surface tilt need not be 0 — log only.
        if level_method == "marker_plane" and tilt_after > GATE_LONG_TILT_MAX_DEG:
            alarm(f"{chunk.label}: vetted marker-plane is still tilted "
                  f"{tilt_after:.3f} deg from Z after leveling — R was not applied "
                  f"correctly.", critical=True, ignore=ignore_sanity)
        elif level_method == "camera_nadir":
            log(f"{chunk.label}: marker-plane tilt after camera-nadir leveling: "
                f"{tilt_after:.2f}° (informational — probe verifies camera boresight).")
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


def stage_dense(doc: Metashape.Document, out_root: Path, ignore_sanity: bool,
                health: "HealthConfig") -> None:
    for chunk in doc.chunks:
        if chunk.point_cloud is not None:
            log(f"{chunk.label}: dense cloud exists; skipping.")
            continue
        # 3c PRE-condition (ADR-0023): never build dense on a collapsed model.
        _check_network_health_or_escalate(chunk, out_root, "dense:pre", health,
                                          ignore_sanity=ignore_sanity)
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
    chunk.crs = Metashape.CoordinateSystem(_LOCAL_CS_WKT)
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
        # The hard ship/no-ship decision is the INTRINSIC, reference-free core
        # (checks 1-7). A reference-based hard gate would suppress legitimate
        # divergence (we'd only ship products that already match the published
        # values), making the Chat-6 reconciliation circular. So core_failed
        # NEVER includes check 8.
        core_failed = [k for k, c in checks.items() if not c["pass"]]
        # Check 8 (ADVISORY) — reference-roughness overlap, only where a P13HMEON
        # DEM exists. FIREWALL: the reference is COMPARISON-ONLY — consumed solely
        # here (and the Chat-6 reconciliation), NEVER by any construction stage
        # (level=markers only, aoi=own footprint only, scale=own scale bars only).
        # It REPORTS a flag; it does NOT add to core_failed and cannot block a ship.
        advisory_8 = {"available": reference_dem is not None,
                      "path": str(reference_dem) if reference_dem else None,
                      "advisory": True, "flag": None,   # roughness overlap wired w/ reconciliation
                      "note": "comparison-only; advisory; the hard gate is the "
                              "reference-free core (1-7)."}
        checks["8_reference_dem_advisory"] = advisory_8
        cross_floor = {"cross_tilt_deg": round(cross_t, 3),
                       "note": "cross is the under-constrained DOF (marker Y-spread "
                               "0.85 m floor); within the documented 2-4 deg envelope, "
                               "not gated as a defect (ADR-0021)."}
        verdict = {"chunk": chunk.label, "checks": checks, "cross": cross_floor,
                   "core_failed": core_failed, "PASS": not core_failed,
                   "reference_firewall": "comparison-only; not read by any "
                                         "construction stage; advisory gate #8 only"}
        _meta_set(chunk, "esm.gate", verdict)
        log(f"{chunk.label}: GATE long={long_t:.2f} total={total_t:.2f} "
            f"cov={checks['3_coverage_interp_off']['v']*100:.1f}% "
            f"ext={long_ext:.3f}m coreg=({coreg_dx:.1e},{coreg_dy:.1e}) "
            f"evr={aoi['footprint_explained_var']} +X={aoi['orientation_plus_x_ok']} "
            f"ref8={'present(advisory)' if reference_dem else 'absent'} "
            f"-> {'PASS' if not core_failed else 'FAIL ' + ','.join(core_failed)}")
        save(doc)
        if core_failed:
            alarm(f"{chunk.label}: PERMANENT QC GATE FAILED on {core_failed} "
                  f"(reference-free core). A mis-leveled/clipped/reversed product "
                  f"will NOT ship (ADR-0021). Tilt long={long_t:.2f} "
                  f"total={total_t:.2f} deg.", critical=True, ignore=ignore_sanity)


# --------------------------------------------------------------------------- #
# Stage: dsm  (ESM Step 14) — DSM at 1 cm, headless via the ADR-0020 recipe
# --------------------------------------------------------------------------- #


def stage_dsm(doc: Metashape.Document, out_root: Path, ignore_sanity: bool,
              health: "HealthConfig") -> None:
    for chunk in doc.chunks:
        if chunk.elevation is not None:
            log(f"{chunk.label}: DSM exists; skipping.")
            continue
        # 3c PRE-condition (ADR-0023): never build the DEM on a collapsed model.
        _check_network_health_or_escalate(chunk, out_root, "dsm:pre", health,
                                          ignore_sanity=ignore_sanity)
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


def stage_ortho(doc: Metashape.Document, out_root: Path, ignore_sanity: bool,
                health: "HealthConfig") -> None:
    for chunk in doc.chunks:
        if chunk.orthomosaic is not None:
            log(f"{chunk.label}: orthomosaic exists; skipping.")
            continue
        # 3c PRE-condition (ADR-0023): never build the ortho on a collapsed model.
        _check_network_health_or_escalate(chunk, out_root, "ortho:pre", health,
                                          ignore_sanity=ignore_sanity)
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


def _scalebar_errors_m(chunk: "Metashape.Chunk") -> "list[float] | None":
    """Geometry-derived signed per-bar residuals (measured − defined), metres.

    Uses the same T.mulp() approach as stage_level's health check — no PDF parsing.
    Bars with missing positions or undefined reference distance are skipped silently.
    Returns None when no bars can be evaluated (not an empty list — preserves not-evaluable
    semantics in QCValidator._scalebars).
    """
    T = chunk.transform.matrix if chunk.transform else None
    if T is None:
        return None
    errors = []
    for sb in chunk.scalebars:
        defined = sb.reference.distance if sb.reference else None
        if defined is None or sb.point0 is None or sb.point1 is None:
            continue
        try:
            p0, p1 = sb.point0.position, sb.point1.position
            if p0 is None or p1 is None:
                continue
            w0, w1 = T.mulp(p0), T.mulp(p1)
            measured = math.sqrt(
                (w0.x - w1.x) ** 2 + (w0.y - w1.y) ** 2 + (w0.z - w1.z) ** 2
            )
            errors.append(round(measured - defined, 6))
        except Exception:
            continue
    return errors if errors else None


def _build_esm_report(chunk: "Metashape.Chunk", n_aligned: int) -> dict:
    """Assemble the esm.report dict from existing esm.* chunk meta + live state.

    Written to chunk.meta['esm.report'] by stage_report after all products
    export successfully. Carries the full QC surface for ProcessingManifest.from_esm_report.
    """
    step4 = _meta_get(chunk, "esm.step4") or {}
    reduce_m = _meta_get(chunk, "esm.reduce") or {}
    scale_m = _meta_get(chunk, "esm.scale") or {}
    filter_m = _meta_get(chunk, "esm.filter") or {}
    dsm_m = _meta_get(chunk, "esm.dsm") or {}
    thresholds = reduce_m.get("thresholds") or {}
    return {
        "parameters": {
            "alignment_accuracy": PARAMS.align_accuracy,
            "key_point_limit": PARAMS.keypoint_limit,
            "tie_point_limit": PARAMS.tiepoint_limit,
            "generic_preselection": PARAMS.generic_preselection,
            "exclude_stationary_tie_points": PARAMS.exclude_stationary_tie_points,
            "recon_uncertainty_threshold": thresholds.get("reconstruction_uncertainty"),
            "projection_accuracy_threshold": thresholds.get("projection_accuracy"),
            "reprojection_error_threshold": thresholds.get("reprojection_error"),
            "scale_bar_count": scale_m.get("total_scalebars"),
        },
        "outcome": {
            "input_image_count": step4.get("analyzed"),
            "step4_images_analyzed": step4.get("analyzed"),
            "step4_images_disabled": step4.get("disabled"),
            "registered_image_count": n_aligned,
            "final_reprojection_rms_px": reduce_m.get("reproj_rms_post_filter_units"),
            "per_scalebar_errors_m": _scalebar_errors_m(chunk),
            "dense_point_count": filter_m.get("points_after"),
            "dsm_cells": dsm_m.get("cells"),
            "dsm_resolution_m": dsm_m.get("resolution_m"),
        },
    }


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

        # Write the reconciliation key that pipeline_state.py checks for stage completion.
        # Must come AFTER all product exports so an interrupted run leaves esm.report absent.
        _meta_set(chunk, "esm.report", _build_esm_report(chunk, n_aligned))

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
            "stage_markers_validation": _meta_get(chunk, "esm.markers_validation"),
            "stage_scale": _meta_get(chunk, "esm.scale"),
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
    save(doc)  # persist esm.report chunk.meta — must come last so an aborted run leaves meta absent


def _file_stat(path: Path) -> dict:
    try:
        return {"path": str(path), "bytes": path.stat().st_size}
    except OSError:
        return {"path": str(path), "bytes": None}


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

# Corrected step order (ADR-0017 + fidelity fix): marker detection (Step 7) is
# its own stage BEFORE scale-bar assignment; error reduction (Step 8) runs AFTER
# it. ADR-0022 adds the headless marker-layer gate to `markers` and a dumb
# `scale` applier after it: on a gate PASS scale runs headless; on FAIL markers
# escalates (GUI fix -> re-run markers -> re-validate -> scale). The [GUI] handoff
# is now CONDITIONAL — only entered when validation escalates. ADR-0021 inserts
# level (ESM Step 11, marker-plane, BEFORE dense) and aoi (ESM Step 14 bbox,
# footprint-PCA, AFTER filter) as separate stages, and a permanent gate after
# ortho. Sequence with handoffs:
#   import step4 align markers {escalate?->[GUI: fix markers]->markers} scale
#   reduce [GUI: coord frame] level dense filter aoi dsm ortho gate report
STAGES = ["import", "step4", "align", "markers", "scale", "reduce", "level",
          "dense", "filter", "aoi", "dsm", "ortho", "gate", "report"]


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
    ap.add_argument("--marker-resid-ceiling", type=float,
                    default=GATE_MARKER_RESID_CEILING_PX,
                    help="Marker validation gate (b) ceiling: robust (median) "
                         "per-marker reprojection residual in PIXELS. A loose "
                         "tripwire (default 2.0; T3 max 0.378, T1 ~1000x past). "
                         "Calibrate on a known-good transect with margin — do NOT "
                         "tune to make a bad transect fail (ADR-0022).")
    ap.add_argument("--interbar-ratio-max", type=float,
                    default=GATE_INTERBAR_RATIO_MAX,
                    help="Marker validation gate (c) tolerance: max/min local "
                         "length ratio across the proposed scale bars (default "
                         "1.25; T3 1.091 PASS, T1 1.352 FAIL). Scale-invariant.")
    ap.add_argument("--min-validated-bars", type=int,
                    default=GATE_MIN_VALIDATED_BARS,
                    help="Marker validation gate (d) fail-closed floor: a headless "
                         "PASS requires at least this many VALIDATED bars (default "
                         "3, the EDR deployment norm; floor 2 so gate (c) has two "
                         "bars to compare). Fewer -> ESCALATE.")
    ap.add_argument("--bar-length", type=float, default=PARAMS.scalebar_length_m,
                    help="Physical scale-bar length in metres (default 0.25 = 25 cm "
                         "coded targets). Recorded on each validated bar at the "
                         "markers stage and applied by the scale stage. The gates "
                         "themselves are scale-free, so this does not affect "
                         "PASS/FAIL — only the metric scale.")
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
    # Network-health collapse-guard thresholds (ADR-0023). Config params, not T1
    # literals; recalibration guidance in docs/05.
    ap.add_argument("--health-min-aligned-frac", type=float, default=HEALTH_MIN_ALIGNED_FRAC,
                    help="Collapse guard: aligned cameras must stay >= this fraction "
                         "of the baseline (pre-reduce for 3b; enabled for 3c). PRIMARY "
                         f"discriminator. Default {HEALTH_MIN_ALIGNED_FRAC}.")
    ap.add_argument("--health-min-tiepoints", type=int, default=HEALTH_MIN_TIEPOINTS,
                    help="Collapse guard: NEAR-ZERO tie-point tripwire (not a "
                         "fraction — a healthy reduce sheds a large share). Fires only "
                         f"on near-total removal. Default {HEALTH_MIN_TIEPOINTS}.")
    ap.add_argument("--health-scalebar-max-ratio", type=float,
                    default=HEALTH_SCALEBAR_MAX_RATIO,
                    help="Collapse guard: COARSE scale-bar sanity — measured length "
                         "must be within this factor of defined (catches a model blown "
                         f"up to km; NOT the fine scale gate). Default {HEALTH_SCALEBAR_MAX_RATIO}.")
    ap.add_argument("--reduce-max-pass-drop-frac", type=float,
                    default=HEALTH_MAX_PASS_DROP_FRAC,
                    help="3a within-reduce backstop: a single run-once gradual-"
                         "selection filter dropping > this of its input halts the run "
                         f"(Logan's RU/PA cutoff is 0.5, so it never trips). Default {HEALTH_MAX_PASS_DROP_FRAC}.")
    ap.add_argument("--level-max-extent-m", type=float, default=LEVEL_MAX_EXTENT_M,
                    help="stage_level sanity: refuse to level if the marker set spans "
                         f"more than this (transect ~10 m). Default {LEVEL_MAX_EXTENT_M}.")
    ap.add_argument("--scalebar-accuracy-m", type=float, default=PARAMS.scalebar_accuracy_m,
                    help="Scale-bar reference accuracy (m) set in stage_scale = the "
                         f"optimize weight. Default {PARAMS.scalebar_accuracy_m}.")
    ap.add_argument("--ignore-sanity", action="store_true",
                    help="Downgrade critical sanity alarms from hard-stop to "
                         "loud-warn. Off by default: the pipeline stops on a "
                         "critical alarm so a dev run surfaces and iterates.")
    ap.add_argument("--verify", action="store_true",
                    help="Reopen the project READ-ONLY, confirm the artifacts in "
                         "--verify-expect are persisted on disk, and exit 0/1. "
                         "Runs NO stage and takes NO lock. The launcher gates its "
                         "completion sentinel on this so a stage that ran but did "
                         "not save can never look done (2026-06-04 T1 incident).")
    ap.add_argument("--verify-expect", default="aligned,markers",
                    help="Comma list of artifacts --verify must find: any of "
                         "'aligned','markers'. Default 'aligned,markers'.")
    args = ap.parse_args()

    # Verification mode short-circuits everything else: no GPU, no lock, no stage.
    if args.verify:
        expect = {x.strip() for x in args.verify_expect.split(",") if x.strip()}
        unknown = expect - {"aligned", "markers"}
        if unknown:
            sys.exit(f"--verify-expect: unknown artifact(s) {sorted(unknown)}; "
                     f"allowed: aligned, markers")
        sys.exit(verify_project(args.project, expect))

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

    health = HealthConfig(
        min_aligned_frac=args.health_min_aligned_frac,
        min_tiepoints=args.health_min_tiepoints,
        scalebar_max_ratio=args.health_scalebar_max_ratio,
        max_pass_drop_frac=args.reduce_max_pass_drop_frac,
        scalebar_defined_m=args.bar_length,
    )

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
            stage_markers(doc, args.ignore_sanity, expected_ids,
                          args.expected_markers, args.out_root,
                          args.marker_resid_ceiling, args.interbar_ratio_max,
                          args.min_validated_bars, args.bar_length)
        elif st == "scale":
            stage_scale(doc, args.out_root, args.ignore_sanity, health,
                        args.bar_length, args.scalebar_accuracy_m)
        elif st == "reduce":
            stage_reduce(doc, args.out_root, args.logan_module, args.ignore_sanity, health)
        elif st == "level":
            stage_level(doc, args.out_root, args.ignore_sanity, health,
                        args.level_max_extent_m)
        elif st == "dense":
            stage_dense(doc, args.out_root, args.ignore_sanity, health)
        elif st == "filter":
            stage_filter(doc, args.noise_confidence, args.ignore_sanity)
        elif st == "aoi":
            stage_aoi(doc, args.ignore_sanity)
        elif st == "dsm":
            stage_dsm(doc, args.out_root, args.ignore_sanity, health)
        elif st == "ortho":
            stage_ortho(doc, args.out_root, args.ignore_sanity, health)
        elif st == "gate":
            stage_gate(doc, args.ignore_sanity, args.reference_dem,
                       args.max_total_tilt_deg)
        elif st == "report":
            stage_report(doc, args.out_root, gpu_names)
    log("Pipeline run complete.")


if __name__ == "__main__":
    main()
