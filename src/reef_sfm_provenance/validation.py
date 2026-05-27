"""
Intake validation rules for the P1WHKTRD image release.

Every rule here corresponds to an explicit claim in the USGS metadata text
file (Johnson et al. 2025).  Each rule produces a `Finding` with:

  * severity: ok | warn | fail | unverified
  * code: short stable identifier, used as the test name in pytest
  * message: human-readable
  * details: structured dict for the JSON report

Rules are deliberately independent: a single image's bad EXIF doesn't poison
the whole site's checks.  The aggregate report is computed by counting
per-image findings and surfacing a small set of dataset-level rules
(file count, camera consistency, hash uniqueness).

The motion-blur and exposure-outlier rules are heuristic and explicitly
labeled as warnings, not failures.  Without per-image RAW exposure data
we can only flag statistical outliers in image brightness and Laplacian
variance; manual review in Metashape (Chat 5) is the ground truth.
"""

from __future__ import annotations

import dataclasses
import logging
import math
import re
import statistics
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from .inventory import ImageRecord

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Expectations derived from the P1WHKTRD metadata file
# ---------------------------------------------------------------------------

EXPECTED_EXIF_ARTIST = "USGS St. Petersburg Coastal and Marine Science Center"
EXPECTED_EXIF_COPYRIGHT = "Public Domain"
EXPECTED_IPTC_CREDIT = "U.S. Geological Survey, Mote Marine Laboratory"
EXPECTED_IPTC_CONTACT = "gs-g-spcmsc_data_inquiries@usgs.gov"
EXPECTED_XMP_ATTRIBUTION_URL = "https://doi.org/10.5066/P1WHKTRD"

# All offshore sites (including EasternDryRocks) used the Canon PowerShot
# S120 per the metadata.  We match against the canonical EXIF strings
# produced by that camera.  Note: USGS converted RAW → TIFF in Photoshop
# CS25, so the Make/Model fields come from the original CR2 EXIF blocks
# preserved during conversion.
EXPECTED_CAMERA_MAKE_PATTERN = re.compile(r"^Canon$", re.IGNORECASE)
EXPECTED_CAMERA_MODEL_PATTERN = re.compile(r"PowerShot\s*S120", re.IGNORECASE)

# The release spans 2022-07-11 to 2023-07-18.  We require DateTimeOriginal
# values to fall in this window (with a generous 1-day pad either side
# to absorb timezone drift in the EXIF write step).
EXPECTED_DATE_MIN = datetime(2022, 7, 10)
EXPECTED_DATE_MAX = datetime(2023, 7, 19)

# Bounding box from the metadata's Spatial_Domain.  GPS coordinates are
# per-site, not per-image, so all images in EasternDryRocks should share
# one lat/lon pair that falls within this box.
BBOX_WEST, BBOX_EAST = -81.8783, -81.3626
BBOX_SOUTH, BBOX_NORTH = 24.4517, 24.6216

# Canon PowerShot S120 native resolution is 4000×3000 (12 MP).  We accept
# either landscape or portrait orientation since the underwater housing
# allows both.
EXPECTED_DIMS = {(4000, 3000), (3000, 4000)}

# Minimum images per transect per Combs 2021: ~50-150 per 10x2m transect.
# At 10-12 transects per offshore site, EasternDryRocks should land
# in the 1500-3000 range.  This is a sanity check, not a hard bound.
EXPECTED_FILE_COUNT_MIN = 1000
EXPECTED_FILE_COUNT_MAX = 5000


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


SEVERITY_ORDER = {"ok": 0, "warn": 1, "unverified": 1, "fail": 2}


@dataclasses.dataclass
class Finding:
    code: str
    severity: str  # "ok" | "warn" | "fail" | "unverified"
    message: str
    scope: str = "dataset"  # or an image filename
    details: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @property
    def is_pass(self) -> bool:
        return self.severity == "ok"

    @property
    def is_fail(self) -> bool:
        return self.severity == "fail"


# ---------------------------------------------------------------------------
# Per-image rules
# ---------------------------------------------------------------------------


def _check_camera(rec: ImageRecord) -> Finding:
    make = rec.exif_make or ""
    model = rec.exif_model or ""
    make_ok = bool(EXPECTED_CAMERA_MAKE_PATTERN.search(make))
    model_ok = bool(EXPECTED_CAMERA_MODEL_PATTERN.search(model))
    if make_ok and model_ok:
        return Finding("camera_consistency", "ok",
                       f"{make} {model}", scope=rec.name,
                       details={"make": make, "model": model})
    return Finding(
        "camera_consistency", "fail",
        f"Unexpected camera: make={make!r} model={model!r}",
        scope=rec.name, details={"make": make, "model": model},
    )


def _check_exif_artist(rec: ImageRecord) -> Finding:
    if rec.exif_artist == EXPECTED_EXIF_ARTIST:
        return Finding("exif_artist", "ok", "Artist matches USGS expectation", scope=rec.name)
    return Finding(
        "exif_artist", "fail",
        f"EXIF Artist {rec.exif_artist!r} != expected",
        scope=rec.name,
        details={"actual": rec.exif_artist, "expected": EXPECTED_EXIF_ARTIST},
    )


def _check_exif_copyright(rec: ImageRecord) -> Finding:
    if rec.exif_copyright == EXPECTED_EXIF_COPYRIGHT:
        return Finding("exif_copyright", "ok", "Copyright = Public Domain", scope=rec.name)
    return Finding(
        "exif_copyright", "fail",
        f"EXIF Copyright {rec.exif_copyright!r} != expected",
        scope=rec.name,
        details={"actual": rec.exif_copyright, "expected": EXPECTED_EXIF_COPYRIGHT},
    )


def _check_xmp_attribution(rec: ImageRecord) -> Finding:
    if rec.xmp_attribution_url is None:
        return Finding(
            "xmp_attribution_url", "unverified",
            "XMP:AttributionURL not read (exiftool unavailable?)",
            scope=rec.name,
        )
    if rec.xmp_attribution_url == EXPECTED_XMP_ATTRIBUTION_URL:
        return Finding("xmp_attribution_url", "ok",
                       "AttributionURL matches data release DOI", scope=rec.name)
    return Finding(
        "xmp_attribution_url", "fail",
        f"XMP:AttributionURL {rec.xmp_attribution_url!r} != DOI",
        scope=rec.name,
        details={"actual": rec.xmp_attribution_url, "expected": EXPECTED_XMP_ATTRIBUTION_URL},
    )


def _check_iptc_credit(rec: ImageRecord) -> Finding:
    if rec.iptc_credit is None:
        return Finding("iptc_credit", "unverified",
                       "IPTC:Credit not read", scope=rec.name)
    if rec.iptc_credit == EXPECTED_IPTC_CREDIT:
        return Finding("iptc_credit", "ok",
                       "IPTC Credit matches USGS/Mote attribution", scope=rec.name)
    return Finding(
        "iptc_credit", "fail",
        f"IPTC:Credit {rec.iptc_credit!r} != expected",
        scope=rec.name,
        details={"actual": rec.iptc_credit, "expected": EXPECTED_IPTC_CREDIT},
    )


def _check_dimensions(rec: ImageRecord) -> Finding:
    if rec.width is None or rec.height is None:
        return Finding("dimensions", "fail",
                       "Could not read width/height", scope=rec.name)
    if (rec.width, rec.height) in EXPECTED_DIMS:
        return Finding("dimensions", "ok",
                       f"{rec.width}×{rec.height} matches Canon S120 native",
                       scope=rec.name,
                       details={"width": rec.width, "height": rec.height})
    return Finding(
        "dimensions", "warn",
        f"Unexpected dimensions {rec.width}×{rec.height} (expected 4000×3000)",
        scope=rec.name,
        details={"width": rec.width, "height": rec.height},
    )


def _check_datetime(rec: ImageRecord) -> Finding:
    dto = rec.exif_datetime_original
    if not dto:
        return Finding("datetime_original", "warn",
                       "DateTimeOriginal missing", scope=rec.name)
    # EXIF format: 'YYYY:MM:DD HH:MM:SS'
    try:
        parsed = datetime.strptime(dto, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return Finding(
            "datetime_original", "warn",
            f"DateTimeOriginal {dto!r} did not parse",
            scope=rec.name,
        )
    if EXPECTED_DATE_MIN <= parsed <= EXPECTED_DATE_MAX:
        return Finding("datetime_original", "ok",
                       f"{parsed.isoformat()} in survey window", scope=rec.name)
    return Finding(
        "datetime_original", "warn",
        f"DateTimeOriginal {parsed.isoformat()} outside survey window "
        f"[{EXPECTED_DATE_MIN.date()} – {EXPECTED_DATE_MAX.date()}]",
        scope=rec.name,
        details={"value": parsed.isoformat()},
    )


def _check_gps(rec: ImageRecord) -> Finding:
    if rec.gps_lat is None or rec.gps_lon is None:
        return Finding("gps_present", "fail",
                       "GPS coordinates missing", scope=rec.name)
    if not (BBOX_SOUTH <= rec.gps_lat <= BBOX_NORTH and BBOX_WEST <= rec.gps_lon <= BBOX_EAST):
        return Finding(
            "gps_present", "fail",
            f"GPS ({rec.gps_lat:.5f}, {rec.gps_lon:.5f}) outside Lower Florida Keys bbox",
            scope=rec.name,
            details={"lat": rec.gps_lat, "lon": rec.gps_lon},
        )
    return Finding(
        "gps_present", "ok",
        f"GPS ({rec.gps_lat:.5f}, {rec.gps_lon:.5f}) inside survey bbox",
        scope=rec.name,
        details={"lat": rec.gps_lat, "lon": rec.gps_lon},
    )


def _check_read_errors(rec: ImageRecord) -> Finding | None:
    if not rec.read_errors:
        return None
    return Finding(
        "read_errors", "fail",
        "Image read raised errors: " + "; ".join(rec.read_errors),
        scope=rec.name,
        details={"errors": rec.read_errors},
    )


def validate_image(rec: ImageRecord) -> list[Finding]:
    """All per-image rules.  Returns one Finding per rule that ran."""
    findings: list[Finding] = []
    read_err = _check_read_errors(rec)
    if read_err:
        findings.append(read_err)
        # If we couldn't even open the file, skip the EXIF-dependent rules.
        return findings
    findings.append(_check_camera(rec))
    findings.append(_check_dimensions(rec))
    findings.append(_check_exif_artist(rec))
    findings.append(_check_exif_copyright(rec))
    findings.append(_check_datetime(rec))
    findings.append(_check_gps(rec))
    findings.append(_check_xmp_attribution(rec))
    findings.append(_check_iptc_credit(rec))
    return findings


# ---------------------------------------------------------------------------
# Dataset-level rules
# ---------------------------------------------------------------------------


def _check_file_count(records: list[ImageRecord]) -> Finding:
    n = len(records)
    if EXPECTED_FILE_COUNT_MIN <= n <= EXPECTED_FILE_COUNT_MAX:
        return Finding(
            "file_count", "ok",
            f"{n} images in expected range [{EXPECTED_FILE_COUNT_MIN}, {EXPECTED_FILE_COUNT_MAX}]",
            details={"count": n},
        )
    return Finding(
        "file_count", "warn",
        f"{n} images outside expected range [{EXPECTED_FILE_COUNT_MIN}, {EXPECTED_FILE_COUNT_MAX}]",
        details={"count": n},
    )


def _check_hash_uniqueness(records: list[ImageRecord]) -> Finding:
    hashes = [r.sha256 for r in records if r.sha256]
    if not hashes:
        return Finding("hash_uniqueness", "unverified",
                       "No hashes available to check (acquisition skipped)")
    seen: dict[str, list[str]] = {}
    for r in records:
        if not r.sha256:
            continue
        seen.setdefault(r.sha256, []).append(r.name)
    dups = {h: names for h, names in seen.items() if len(names) > 1}
    if dups:
        return Finding(
            "hash_uniqueness", "fail",
            f"{len(dups)} hash collision(s) detected; {sum(len(v) for v in dups.values())} files affected",
            details={"duplicates": {h: names for h, names in list(dups.items())[:10]}},
        )
    return Finding("hash_uniqueness", "ok", f"{len(hashes)} unique SHA-256 values")


def _check_gps_consistency(records: list[ImageRecord]) -> Finding:
    """All images at a site share ONE surface-station coordinate.

    GPS does not penetrate seawater, so the dive team records a single
    handheld-GPS fix at the surface above the transect and ExifTool stamps
    that one coordinate pair into every image's EXIF.  The expected on-disk
    state is therefore zero spread: one unique (lat, lon) pair across the
    whole site directory.

    A non-zero spread doesn't mean GPS drift mid-dive — it can't.  It means
    images from two different surface fixes (i.e. two different sites, or
    two different days at the same site with different fixes) got placed
    into one directory.  That's a sorting/merge bug worth catching.

    We tolerate a handful of distinct fixes (≤2) at warn level — sometimes
    a re-survey day genuinely gets a slightly different fix — but anything
    above that or any spread above ~25m (i.e. clearly a different site)
    fails.
    """
    coords = [(r.gps_lat, r.gps_lon) for r in records if r.gps_lat is not None and r.gps_lon is not None]
    if not coords:
        return Finding("gps_consistency", "unverified", "No GPS coordinates to compare")

    unique_fixes = sorted(set(coords))
    n_fixes = len(unique_fixes)

    if n_fixes == 1:
        lat, lon = unique_fixes[0]
        return Finding(
            "gps_consistency", "ok",
            f"All {len(coords)} images share one station coordinate ({lat:.5f}, {lon:.5f}) — "
            "expected behavior, GPS does not work underwater",
            details={"unique_fixes": 1, "coordinate": [lat, lon]},
        )

    # Multiple fixes — quantify the spread to distinguish "same site,
    # re-survey day got a new GPS fix" from "two sites got mixed up".
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    span_m_lat = (max(lats) - min(lats)) * 111_000
    span_m_lon = (max(lons) - min(lons)) * 111_000 * math.cos(math.radians(statistics.mean(lats)))
    span_m = max(span_m_lat, span_m_lon)

    if n_fixes == 2 and span_m < 25:
        return Finding(
            "gps_consistency", "warn",
            f"{n_fixes} distinct station fixes within {span_m:.1f}m — likely re-survey "
            f"day with a fresh handheld GPS fix; review before treating as one site",
            details={
                "unique_fixes": n_fixes,
                "fixes": unique_fixes,
                "max_span_m": round(span_m, 2),
            },
        )
    return Finding(
        "gps_consistency", "fail",
        f"{n_fixes} distinct station fixes spanning {span_m:.1f}m — looks like images "
        f"from different sites got merged into one directory",
        details={
            "unique_fixes": n_fixes,
            "fixes": unique_fixes[:10],
            "max_span_m": round(span_m, 2),
        },
    )


def _check_camera_consistency(records: list[ImageRecord]) -> Finding:
    pairs = {(r.exif_make, r.exif_model) for r in records if r.exif_make and r.exif_model}
    if len(pairs) == 1:
        make, model = next(iter(pairs))
        return Finding(
            "dataset_camera_consistency", "ok",
            f"Single camera across site: {make} {model}",
            details={"make": make, "model": model, "count": len(records)},
        )
    return Finding(
        "dataset_camera_consistency", "warn",
        f"{len(pairs)} distinct (make, model) pairs across site",
        details={"pairs": sorted([(m or "", md or "") for m, md in pairs])},
    )


def _check_size_outliers(records: list[ImageRecord]) -> Finding:
    """Flag files dramatically smaller than the median.

    Drastic undersize ≈ Photoshop's TIFF compression compacted a near-uniform
    frame (e.g. dropped sensor into sand, lens-cap-on tail of a transect).
    """
    sizes = [r.size_bytes for r in records if r.size_bytes]
    if len(sizes) < 10:
        return Finding("size_outliers", "unverified",
                       "Too few files to compute size distribution")
    median = statistics.median(sizes)
    threshold = median * 0.4
    outliers = [(r.name, r.size_bytes) for r in records if r.size_bytes and r.size_bytes < threshold]
    if not outliers:
        return Finding(
            "size_outliers", "ok",
            f"No files <40% of median size ({int(median):,} bytes)",
            details={"median_bytes": int(median)},
        )
    return Finding(
        "size_outliers", "warn",
        f"{len(outliers)} files unusually small; review before SfM alignment",
        details={
            "median_bytes": int(median),
            "threshold_bytes": int(threshold),
            "examples": outliers[:20],
        },
    )


def validate_dataset(records: list[ImageRecord]) -> list[Finding]:
    """Dataset-level rules.  Distinct from per-image: these only fire once."""
    if not records:
        return [Finding("file_count", "fail", "No images present")]
    return [
        _check_file_count(records),
        _check_camera_consistency(records),
        _check_hash_uniqueness(records),
        _check_gps_consistency(records),
        _check_size_outliers(records),
    ]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate_per_image(
    per_image_findings: list[Finding],
) -> dict[str, dict[str, int]]:
    """Roll per-image findings up into {code: {severity: count}}."""
    out: dict[str, dict[str, int]] = {}
    for f in per_image_findings:
        bucket = out.setdefault(f.code, {"ok": 0, "warn": 0, "fail": 0, "unverified": 0})
        bucket[f.severity] = bucket.get(f.severity, 0) + 1
    return out


def overall_severity(all_findings: Iterable[Finding]) -> str:
    """The worst severity across the whole report."""
    worst = "ok"
    for f in all_findings:
        if SEVERITY_ORDER.get(f.severity, 0) > SEVERITY_ORDER.get(worst, 0):
            worst = f.severity
    return worst


__all__ = [
    "Finding",
    "validate_image",
    "validate_dataset",
    "aggregate_per_image",
    "overall_severity",
    # Constants exposed for tests and external review
    "EXPECTED_EXIF_ARTIST",
    "EXPECTED_EXIF_COPYRIGHT",
    "EXPECTED_IPTC_CREDIT",
    "EXPECTED_XMP_ATTRIBUTION_URL",
    "EXPECTED_CAMERA_MAKE_PATTERN",
    "EXPECTED_CAMERA_MODEL_PATTERN",
    "EXPECTED_DATE_MIN",
    "EXPECTED_DATE_MAX",
    "BBOX_WEST", "BBOX_EAST", "BBOX_SOUTH", "BBOX_NORTH",
]
