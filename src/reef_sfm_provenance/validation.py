"""
Intake validation rules for the P1WHKTRD image release.

NOTE — EDR-specific values are currently inline (GPS bbox, filename regex,
software allow-list, file-count range, metadata-lineage expectations).
Generalization to a profile-driven architecture is deferred to Chat 6.
See docs/decisions/0011-validator-hardcoded-now-profile-driven-later.md.

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
from collections import defaultdict
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
# S120 per the metadata.  Make/Model survived Photoshop's CR2→TIFF re-encode
# and are present in both on-disk EXIF and the IDS CSV (as cammake/cammodel).
EXPECTED_CAMERA_MAKE_PATTERN = re.compile(r"^Canon$", re.IGNORECASE)
EXPECTED_CAMERA_MODEL_PATTERN = re.compile(r"PowerShot\s*S120", re.IGNORECASE)

# The Toth et al. 2025 RAW→TIFF pipeline uses Adobe Photoshop (ESM Step 2).
# The Software tag is the on-disk evidence of this lineage (ADR-0009 Finding B).
EXPECTED_SOFTWARE_PREFIX = "Adobe Photoshop"

# Windows Imaging Component (WIC) identifiers observed in the full EDR dataset.
# ~48% of the 3,271 EDR files carry one of these tags instead of the Photoshop
# prefix, reflecting workflow variation within the Toth et al. 2025 ESM
# methodology (likely a review or dehaze pass through a Windows utility).
# Files in this set are warn, not fail; they are from the same pipeline.
# New unknown prefixes must be human-reviewed before adding here.
SOFTWARE_WARN_PREFIXES: tuple[str, ...] = (
    "Microsoft Windows Photo Viewer",
)

# The release spans 2022-07-11 to 2023-07-18.  We validate against the IDS
# CSV's dtoriginal (UTC-clean ISO 8601); the on-disk DateTime tag reflects
# the Photoshop save time and must NOT be used for capture-time checks.
EXPECTED_DATE_MIN = datetime(2022, 7, 10)
EXPECTED_DATE_MAX = datetime(2023, 7, 19)

# EXIF sub-IFD tags absent from all Photoshop re-encodes in this release.
# Their absence is expected (ADR-0009 Finding B) and is documented in the
# QC report's metadata_lineage section, NOT surfaced as per-image failures.
METADATA_LINEAGE = {
    "csv_primary_fields": [
        "cammake", "cammodel", "artist", "copyright", "dtoriginal",
    ],
    "on_disk_primary_fields": [
        "width", "height", "sha256", "size_bytes", "software", "orientation",
    ],
    "fields_absent_by_design": {
        "reason": (
            "Photoshop CR2-to-TIFF re-encode per Toth et al. 2025 ESM Table S2 "
            "Step 2; Exif sub-IFD is stripped by Photoshop's TIFF export"
        ),
        "missing_exif_tags": [
            "ExposureTime", "FNumber", "ISOSpeedRatings",
            "FocalLength", "DateTimeOriginal",
        ],
    },
}

# Bounding box from the metadata's Spatial_Domain.  GPS coordinates are
# per-site, not per-image, so all images in EasternDryRocks should share
# one lat/lon pair that falls within this box.
BBOX_WEST, BBOX_EAST = -81.8783, -81.3626
BBOX_SOUTH, BBOX_NORTH = 24.4517, 24.6216

# Canon PowerShot S120 native resolution is 4000×3000 (12 MP).  We accept
# either landscape or portrait orientation since the underwater housing
# allows both.
EXPECTED_DIMS = {(4000, 3000), (3000, 4000)}

# Toth et al. 2025 filename convention: YYYYMMDD_SITE_T#_[RC]#_NNNNNN.tif
# T# = transect/subsite identifier (T1, T3, T8 for EDR)
# [RC]# = swath designator: R# (row-direction) or C# (column-direction),
#          reflecting the double-lawnmower swim pattern in ESM Step 1
# NNNNNN = 6-digit sequential image number
TOTH_FILENAME_RE = re.compile(
    r"^(\d{8})_([A-Za-z0-9]+)_(T\d+)_([RC]\d+)_(\d{6})\.(tif)$",
    re.IGNORECASE,
)

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


def _check_csv_join(rec: ImageRecord) -> Finding:
    """File must be present in the IDS exif_data.csv (ADR-0009)."""
    if rec.csv_matched:
        return Finding("csv_join", "ok",
                       f"Matched in IDS CSV (image_id={rec.image_id})",
                       scope=rec.name, details={"image_id": rec.image_id})
    return Finding("csv_join", "fail",
                   "File not found in IDS exif_data.csv; "
                   "re-run with correct --ids-csv or re-download the IDS export",
                   scope=rec.name)


def _check_software_lineage(rec: ImageRecord) -> Finding:
    """Software tag must confirm Toth et al.'s Adobe Photoshop RAW→TIFF pipeline.

    Three outcomes:
      ok   — starts with "Adobe Photoshop" (ESM Step 2)
      warn — known Windows imaging utility (same dataset, different processing step)
      fail — absent, or an unrecognized value not in SOFTWARE_WARN_PREFIXES
    """
    sw = rec.software
    if sw is None:
        return Finding("software_lineage", "fail",
                       "Software EXIF tag absent (expected Adobe Photoshop prefix)",
                       scope=rec.name)
    if sw.startswith(EXPECTED_SOFTWARE_PREFIX):
        return Finding("software_lineage", "ok",
                       f"Software={sw!r} confirms Toth et al. RAW→TIFF lineage",
                       scope=rec.name, details={"software": sw})
    if any(sw.startswith(p) for p in SOFTWARE_WARN_PREFIXES):
        return Finding(
            "software_lineage", "warn",
            f"Software={sw!r} indicates the file was touched by a Windows imaging "
            "utility in addition to the Photoshop RAW→TIFF conversion; this represents "
            "workflow variation within the Toth et al. 2025 ESM methodology, not a "
            "pipeline mismatch",
            scope=rec.name, details={"software": sw},
        )
    return Finding("software_lineage", "fail",
                   f"Software={sw!r} does not start with {EXPECTED_SOFTWARE_PREFIX!r} "
                   "and is not in the known-workflow allowlist; "
                   "file may not be from the published methodology pipeline",
                   scope=rec.name, details={"software": sw})


def _check_filename_pattern(rec: ImageRecord) -> Finding:
    """Filename must match Toth et al. YYYYMMDD_SITE_T#_[RC]#_NNNNNN.tif convention."""
    m = TOTH_FILENAME_RE.match(rec.name)
    if m:
        transect, swath = m.group(3), m.group(4)
        return Finding(
            "filename_pattern", "ok",
            f"Matches Toth convention (transect={transect}, swath={swath})",
            scope=rec.name,
            details={
                "date": m.group(1), "site": m.group(2),
                "transect": transect, "swath": swath, "seq": m.group(5),
            },
        )
    return Finding(
        "filename_pattern", "fail",
        f"Filename {rec.name!r} does not match YYYYMMDD_SITE_T#_[RC]#_NNNNNN.tif",
        scope=rec.name,
    )


def _check_camera(rec: ImageRecord) -> Finding:
    # CSV values are canonical; fall back to on-disk EXIF when CSV not joined.
    make = rec.csv_cammake or rec.exif_make or ""
    model = rec.csv_cammodel or rec.exif_model or ""
    source = "CSV" if rec.csv_cammake else "EXIF"
    make_ok = bool(EXPECTED_CAMERA_MAKE_PATTERN.search(make))
    model_ok = bool(EXPECTED_CAMERA_MODEL_PATTERN.search(model))
    if make_ok and model_ok:
        return Finding("camera_consistency", "ok",
                       f"{make} {model} (source: {source})", scope=rec.name,
                       details={"make": make, "model": model, "source": source})
    return Finding(
        "camera_consistency", "fail",
        f"Unexpected camera: make={make!r} model={model!r} (source: {source})",
        scope=rec.name, details={"make": make, "model": model, "source": source},
    )


def _check_exif_artist(rec: ImageRecord) -> Finding:
    # CSV artist is canonical; fall back to on-disk EXIF.
    artist = rec.csv_artist or rec.exif_artist
    source = "CSV" if rec.csv_artist else "EXIF"
    if artist == EXPECTED_EXIF_ARTIST:
        return Finding("exif_artist", "ok",
                       f"Artist matches USGS expectation (source: {source})", scope=rec.name)
    return Finding(
        "exif_artist", "fail",
        f"Artist {artist!r} != expected (source: {source})",
        scope=rec.name,
        details={"actual": artist, "expected": EXPECTED_EXIF_ARTIST, "source": source},
    )


def _check_exif_copyright(rec: ImageRecord) -> Finding:
    # CSV copyright is canonical; fall back to on-disk EXIF.
    copyright_ = rec.csv_copyright or rec.exif_copyright
    source = "CSV" if rec.csv_copyright else "EXIF"
    if copyright_ == EXPECTED_EXIF_COPYRIGHT:
        return Finding("exif_copyright", "ok",
                       f"Copyright = Public Domain (source: {source})", scope=rec.name)
    return Finding(
        "exif_copyright", "fail",
        f"Copyright {copyright_!r} != expected (source: {source})",
        scope=rec.name,
        details={"actual": copyright_, "expected": EXPECTED_EXIF_COPYRIGHT, "source": source},
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
    """IPTC Credit check with three outcomes (ADR-0009 three-layer metadata picture).

    ok   — Credit present and matches expected USGS/Mote attribution
    warn — Credit absent but EXIF Artist + Copyright both present (redundant-field-not-set,
           not a missing rights record; confirmed as the EDR dataset pattern)
    fail — Credit absent AND EXIF Artist or Copyright also absent (no rights documentation)
    """
    if rec.iptc_credit is not None:
        if rec.iptc_credit == EXPECTED_IPTC_CREDIT:
            return Finding("iptc_credit", "ok",
                           "IPTC Credit matches USGS/Mote attribution", scope=rec.name)
        return Finding(
            "iptc_credit", "fail",
            f"IPTC:Credit {rec.iptc_credit!r} != expected",
            scope=rec.name,
            details={"actual": rec.iptc_credit, "expected": EXPECTED_IPTC_CREDIT},
        )
    # Credit is absent (field not set, or exiftool unavailable).
    # Fall back to EXIF rights fields as equivalent documentation.
    artist = rec.csv_artist or rec.exif_artist
    copyright_ = rec.csv_copyright or rec.exif_copyright
    if artist and copyright_:
        return Finding(
            "iptc_credit", "warn",
            f"IPTC Credit is absent but EXIF Artist ({artist!r}) and "
            f"Copyright ({copyright_!r}) provide equivalent rights documentation. "
            "This is a redundant-field-not-set pattern, not a missing rights record.",
            scope=rec.name,
            details={"artist": artist, "copyright": copyright_},
        )
    return Finding(
        "iptc_credit", "fail",
        "IPTC Credit is absent AND EXIF Artist/Copyright are not both present; "
        "rights documentation cannot be confirmed from any metadata source.",
        scope=rec.name,
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
    # Fail (not warn): dimensions are verifiable on-disk; unexpected size is
    # a real problem for Metashape alignment, not just a metadata gap.
    return Finding(
        "dimensions", "fail",
        f"Unexpected dimensions {rec.width}×{rec.height} (expected 4000×3000 or 3000×4000)",
        scope=rec.name,
        details={"width": rec.width, "height": rec.height},
    )


def _check_datetime(rec: ImageRecord) -> Finding:
    # CSV dtoriginal is the canonical capture time (ADR-0009).  The on-disk
    # DateTime tag reflects the Photoshop save timestamp, not capture time.
    dto = rec.csv_dtoriginal_utc
    if not dto:
        return Finding("datetime_original", "unverified",
                       "dtoriginal not available (file not in IDS CSV or CSV not loaded)",
                       scope=rec.name)
    try:
        parsed = datetime.fromisoformat(dto)
    except ValueError:
        return Finding(
            "datetime_original", "warn",
            f"CSV dtoriginal {dto!r} did not parse as ISO 8601",
            scope=rec.name,
        )
    naive = parsed.replace(tzinfo=None)
    if EXPECTED_DATE_MIN <= naive <= EXPECTED_DATE_MAX:
        return Finding("datetime_original", "ok",
                       f"{naive.date().isoformat()} in survey window (source: CSV)",
                       scope=rec.name, details={"dtoriginal_utc": dto})
    return Finding(
        "datetime_original", "warn",
        f"CSV dtoriginal {naive.date().isoformat()} outside survey window "
        f"[{EXPECTED_DATE_MIN.date()} – {EXPECTED_DATE_MAX.date()}]",
        scope=rec.name,
        details={"dtoriginal_utc": dto},
    )


def _check_gps(rec: ImageRecord) -> Finding:
    # Prefer CSV station coordinate (canonical per ADR-0009); fall back to EXIF.
    lat = rec.csv_lat if rec.csv_lat is not None else rec.gps_lat
    lon = rec.csv_lon if rec.csv_lon is not None else rec.gps_lon
    source = "CSV" if rec.csv_lat is not None else "EXIF"
    if lat is None or lon is None:
        return Finding("gps_present", "fail",
                       "GPS coordinates missing (not in CSV or EXIF)", scope=rec.name)
    if not (BBOX_SOUTH <= lat <= BBOX_NORTH and BBOX_WEST <= lon <= BBOX_EAST):
        return Finding(
            "gps_present", "fail",
            f"GPS ({lat:.5f}, {lon:.5f}) outside Lower Florida Keys bbox (source: {source})",
            scope=rec.name,
            details={"lat": lat, "lon": lon, "source": source},
        )
    return Finding(
        "gps_present", "ok",
        f"GPS ({lat:.5f}, {lon:.5f}) inside survey bbox (source: {source})",
        scope=rec.name,
        details={"lat": lat, "lon": lon, "source": source},
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
        return findings
    findings.append(_check_csv_join(rec))
    findings.append(_check_software_lineage(rec))
    findings.append(_check_filename_pattern(rec))
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
    """All station GPS fixes must fall within the expected site bounding box.

    GPS does not penetrate seawater; coordinates are per-dive-event, not
    per-image.  EasternDryRocks has 3 legitimate station fixes (3 subsites:
    EDR_T1, EDR_T3, EDR_T8) — the old single-fix expectation was wrong for
    multi-subsite datasets.  The correct check is: every fix within bbox.

    Prefer CSV lat/lon (station-level, authoritative per ADR-0009) over
    on-disk EXIF GPS when available.
    """
    # Use CSV coordinates when available, fall back to on-disk EXIF.
    csv_coords = [(r.csv_lat, r.csv_lon) for r in records
                  if r.csv_lat is not None and r.csv_lon is not None]
    exif_coords = [(r.gps_lat, r.gps_lon) for r in records
                   if r.gps_lat is not None and r.gps_lon is not None]
    coords = csv_coords if csv_coords else exif_coords
    source = "CSV" if csv_coords else "EXIF"

    if not coords:
        return Finding("gps_consistency", "unverified",
                       "No GPS coordinates available (CSV not loaded and no EXIF GPS)")

    unique_fixes = sorted(set(coords))
    n_fixes = len(unique_fixes)

    outside = [
        (lat, lon) for lat, lon in unique_fixes
        if not (BBOX_SOUTH <= lat <= BBOX_NORTH and BBOX_WEST <= lon <= BBOX_EAST)
    ]
    if outside:
        return Finding(
            "gps_consistency", "fail",
            f"{len(outside)} of {n_fixes} station fix(es) outside Lower Florida Keys bbox "
            f"(source: {source}); images from a different site may have been merged in",
            details={"outside_bbox": outside, "all_fixes": unique_fixes[:10], "source": source},
        )

    event_note = f"{n_fixes} dive event(s)" if n_fixes > 1 else "single station"
    return Finding(
        "gps_consistency", "ok",
        f"{n_fixes} station fix(es), all within survey bbox ({event_note}; source: {source})",
        details={"unique_fixes": n_fixes, "fixes": unique_fixes[:10], "source": source},
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


def _check_csv_coverage(records: list[ImageRecord]) -> Finding:
    """Fraction of on-disk files matched in the IDS CSV."""
    total = len(records)
    matched = sum(1 for r in records if r.csv_matched)
    if total == 0:
        return Finding("csv_coverage", "unverified", "No records to check")
    pct = 100.0 * matched / total
    if matched == total:
        return Finding("csv_coverage", "ok",
                       f"All {total} files matched in IDS CSV",
                       details={"matched": matched, "total": total})
    if pct >= 90:
        return Finding("csv_coverage", "warn",
                       f"{matched}/{total} ({pct:.1f}%) matched in IDS CSV",
                       details={"matched": matched, "total": total, "pct": round(pct, 1)})
    return Finding("csv_coverage", "fail",
                   f"{matched}/{total} ({pct:.1f}%) matched in IDS CSV — "
                   "check that --ids-csv points to the correct export",
                   details={"matched": matched, "total": total, "pct": round(pct, 1)})


def _check_subsite_cross_reference(records: list[ImageRecord]) -> Finding:
    """Cross-reference on-disk transect (T#) groups with CSV dive-event UUIDs.

    Each transect should map to exactly one UUID.  Multiple UUIDs within a T#
    group means images from different dive events were merged — a real error
    that would corrupt Metashape alignment (ADR-0009).
    """
    transect_uuids: dict[str, set[str]] = defaultdict(set)
    transect_counts: dict[str, int] = defaultdict(int)
    no_match_count = 0

    for rec in records:
        m = TOTH_FILENAME_RE.match(rec.name)
        if not m:
            no_match_count += 1
            continue
        transect = m.group(3)
        transect_counts[transect] += 1
        if rec.csv_uuid:
            transect_uuids[transect].add(rec.csv_uuid)

    if not transect_counts:
        return Finding(
            "subsite_cross_reference", "unverified",
            "No filenames matched Toth convention; cross-reference not possible",
            details={"no_filename_match_count": no_match_count},
        )

    total_uuid_entries = sum(len(v) for v in transect_uuids.values())
    if total_uuid_entries == 0:
        return Finding(
            "subsite_cross_reference", "unverified",
            "No CSV UUIDs available (IDS CSV not loaded); cross-reference skipped",
            details={
                "no_filename_match_count": no_match_count,
                "transects": {t: {"count": transect_counts[t], "uuids": []}
                              for t in sorted(transect_counts)},
            },
        )

    table: dict[str, dict] = {}
    multi_uuid_transects: list[str] = []
    for transect in sorted(transect_counts):
        uuids = sorted(transect_uuids.get(transect, set()))
        table[transect] = {"count": transect_counts[transect], "uuids": uuids, "uuid_count": len(uuids)}
        if len(uuids) > 1:
            multi_uuid_transects.append(transect)

    details: dict = {"transects": table, "no_filename_match_count": no_match_count}

    if multi_uuid_transects:
        return Finding(
            "subsite_cross_reference", "fail",
            f"{len(multi_uuid_transects)} transect(s) span multiple UUIDs "
            f"({', '.join(multi_uuid_transects)}); images from different dive events may be merged",
            details=details,
        )
    return Finding(
        "subsite_cross_reference", "ok",
        f"{len(transect_counts)} transect(s), each mapping to a single dive-event UUID",
        details=details,
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
        _check_csv_coverage(records),
        _check_subsite_cross_reference(records),
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
    "METADATA_LINEAGE",
    # Constants exposed for tests and external review
    "EXPECTED_EXIF_ARTIST",
    "EXPECTED_EXIF_COPYRIGHT",
    "EXPECTED_IPTC_CREDIT",
    "EXPECTED_XMP_ATTRIBUTION_URL",
    "EXPECTED_CAMERA_MAKE_PATTERN",
    "EXPECTED_CAMERA_MODEL_PATTERN",
    "EXPECTED_SOFTWARE_PREFIX",
    "SOFTWARE_WARN_PREFIXES",
    "EXPECTED_DATE_MIN",
    "EXPECTED_DATE_MAX",
    "BBOX_WEST", "BBOX_EAST", "BBOX_SOUTH", "BBOX_NORTH",
    "TOTH_FILENAME_RE",
]
