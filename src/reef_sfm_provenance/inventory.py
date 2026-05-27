"""
Image inventory for the EasternDryRocks acquisition.

Catalogs every downloaded image and returns one structured row per file:
filename, dimensions, byte size, EXIF tags, XMP tags (when available), and
the SHA-256 we computed at download time.  This is the input to the QC
validator in `validation.py`.

EXIF read paths, in order of preference:

  1.  Pillow's `Image.getexif()` for the bulk (Make, Model, DateTimeOriginal,
      Artist, Copyright, ImageDescription, GPS).  Always available.

  2.  `exiftool` via subprocess for XMP and IPTC fields (`XMP:AttributionURL`,
      `IPTC:Credit`, etc.) that Pillow can't see.  Used when the binary is
      on PATH; otherwise we degrade gracefully and the QC validator marks
      those checks "unverified" rather than "failed".

We intentionally do NOT depend on a marine-science library here.  Everything
in this module should be reusable for any TIFF intake validation, which is
part of the point of the provenance package.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import shutil
import subprocess
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image, UnidentifiedImageError

from .ids_csv import IdsRecord

log = logging.getLogger(__name__)


# Inverted EXIF tag map: Pillow gives us numeric tag IDs; we want names.
_EXIF_TAGS = {v: k for k, v in ExifTags.TAGS.items()}
_GPS_TAGS = ExifTags.GPSTAGS


@dataclasses.dataclass
class ImageRecord:
    """One row of the inventory."""

    name: str
    relpath: str
    size_bytes: int
    sha256: str | None
    width: int | None
    height: int | None
    # Core EXIF fields the USGS metadata explicitly populates
    exif_make: str | None
    exif_model: str | None
    exif_artist: str | None
    exif_copyright: str | None
    exif_image_description: str | None
    exif_datetime_original: str | None
    # GPS from on-disk EXIF (station-level, not per-image)
    gps_lat: float | None
    gps_lon: float | None
    # XMP/IPTC: populated when exiftool is available, else None
    xmp_attribution_url: str | None
    xmp_external_metadata_link: str | None
    xmp_usage_terms: str | None
    iptc_credit: str | None
    iptc_contact: str | None
    # On-disk EXIF: Software tag (Photoshop lineage) and Orientation
    software: str | None = None
    orientation: int | None = None
    # CSV-primary fields (ADR-0009): joined from IDS exif_data.csv by filename
    csv_matched: bool = False
    image_id: int | None = None
    csv_dtoriginal_utc: str | None = None  # UTC ISO 8601 from CSV dtoriginal
    csv_cammake: str | None = None
    csv_cammodel: str | None = None
    csv_artist: str | None = None
    csv_copyright: str | None = None
    csv_lat: float | None = None   # station-level, per dive event
    csv_lon: float | None = None
    csv_uuid: str | None = None    # dive-event UUID from IDS CSV
    # Read-side issues we caught while cataloging this file
    read_errors: list[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Pillow path
# ---------------------------------------------------------------------------


def _coerce_str(value: Any) -> str | None:
    """Decode bytes, strip nulls, return None on empty."""
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — robustness over precision here
            return None
    s = str(value).strip().strip("\x00").strip()
    return s or None


def _rational_to_float(value: Any) -> float | None:
    """Coerce an EXIF rational (or a fraction-of-degrees tuple) to float."""
    try:
        # PIL.TiffImagePlugin.IFDRational supports float()
        return float(value)
    except (TypeError, ValueError):
        return None


def _gps_dms_to_decimal(dms: tuple[Any, Any, Any], ref: str | None) -> float | None:
    """Convert ((deg, min, sec), ref) to signed decimal degrees."""
    if not dms or len(dms) != 3:
        return None
    parts = [_rational_to_float(x) for x in dms]
    if any(p is None for p in parts):
        return None
    d, m, s = parts  # type: ignore[misc]
    decimal = d + m / 60.0 + s / 3600.0
    if ref and ref.upper() in {"S", "W"}:
        decimal = -decimal
    return decimal


def _read_pillow_exif(path: Path) -> tuple[dict[str, Any], list[str]]:
    """Read width/height + EXIF subset from a TIFF using Pillow.

    Returns (record-fragment, errors).  Record fragment fills in the
    Pillow-knowable fields of ImageRecord; the caller merges in SHA,
    relpath, exiftool fields, etc.
    """
    errors: list[str] = []
    out: dict[str, Any] = {
        "width": None, "height": None,
        "exif_make": None, "exif_model": None,
        "exif_artist": None, "exif_copyright": None,
        "exif_image_description": None, "exif_datetime_original": None,
        "gps_lat": None, "gps_lon": None,
        "software": None, "orientation": None,
    }
    try:
        with Image.open(path) as im:
            out["width"], out["height"] = im.size
            exif = im.getexif()

            if not exif:
                errors.append("no_exif")
                return out, errors

            # Tags that survive Photoshop's CR2→TIFF re-encode (ADR-0009 Finding B).
            wanted = {
                "Make": "exif_make",
                "Model": "exif_model",
                "Artist": "exif_artist",
                "Copyright": "exif_copyright",
                "ImageDescription": "exif_image_description",
                "DateTimeOriginal": "exif_datetime_original",
                "Software": "software",
            }
            for tag_name, field in wanted.items():
                tag_id = _EXIF_TAGS.get(tag_name)
                if tag_id is None:
                    continue
                out[field] = _coerce_str(exif.get(tag_id))

            # Orientation is an integer; handle separately from string fields.
            orientation_id = _EXIF_TAGS.get("Orientation")
            if orientation_id and orientation_id in exif:
                try:
                    out["orientation"] = int(exif[orientation_id])
                except (TypeError, ValueError):
                    pass

            # DateTimeOriginal sometimes lives in the EXIF sub-IFD, not the root.
            # get_ifd() seeks the file — must be called while the file is still open.
            if out["exif_datetime_original"] is None:
                ifd = exif.get_ifd(0x8769) if hasattr(exif, "get_ifd") else {}
                if ifd:
                    dto_tag = _EXIF_TAGS.get("DateTimeOriginal")
                    if dto_tag and dto_tag in ifd:
                        out["exif_datetime_original"] = _coerce_str(ifd[dto_tag])

            # GPS lives in a sub-IFD keyed by tag 0x8825.
            # get_ifd() seeks the file — must be called while the file is still open.
            gps_ifd: dict[Any, Any] = {}
            if hasattr(exif, "get_ifd"):
                try:
                    gps_ifd = exif.get_ifd(0x8825) or {}
                except Exception:  # noqa: BLE001
                    gps_ifd = {}
            if gps_ifd:
                # _GPS_TAGS maps numeric→name (GPSLatitude, GPSLatitudeRef, ...)
                named = {_GPS_TAGS.get(k, k): v for k, v in gps_ifd.items()}
                lat = _gps_dms_to_decimal(
                    named.get("GPSLatitude"), _coerce_str(named.get("GPSLatitudeRef"))
                )
                lon = _gps_dms_to_decimal(
                    named.get("GPSLongitude"), _coerce_str(named.get("GPSLongitudeRef"))
                )
                out["gps_lat"] = lat
                out["gps_lon"] = lon

    except UnidentifiedImageError as exc:
        errors.append(f"not_a_valid_image: {exc}")
        return out, errors
    except Exception as exc:  # noqa: BLE001
        errors.append(f"open_failed: {exc.__class__.__name__}: {exc}")
        return out, errors

    return out, errors


# ---------------------------------------------------------------------------
# exiftool path (optional)
# ---------------------------------------------------------------------------


def exiftool_available() -> bool:
    """True if `exiftool` is on PATH."""
    return shutil.which("exiftool") is not None


def _run_exiftool_bulk(paths: list[Path]) -> dict[str, dict[str, Any]]:
    """Run `exiftool -j` over a batch and return {filename: tags}.

    Batching is important: exiftool startup is ~0.5s; per-file invocation
    of 2000 images would take ~17 minutes purely in startup.  Single
    batch call returns one JSON array.
    """
    if not paths:
        return {}
    cmd = [
        "exiftool",
        "-j",                       # JSON output
        "-q",                        # quiet
        "-fast",                     # don't scan past metadata
        "-XMP:AttributionURL",
        "-XMP:ExternalMetadataLink",
        "-XMP:UsageTerms",
        "-IPTC:Credit",
        "-IPTC:Contact",
        *[str(p) for p in paths],
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        log.warning("exiftool batch failed: %s", exc)
        return {}
    if proc.returncode != 0:
        log.warning("exiftool returned %d: %s", proc.returncode, proc.stderr[:500])
    try:
        records = json.loads(proc.stdout) if proc.stdout.strip() else []
    except json.JSONDecodeError as exc:
        log.warning("exiftool JSON parse failed: %s", exc)
        return {}
    out: dict[str, dict[str, Any]] = {}
    for rec in records:
        # exiftool emits absolute SourceFile; we key by basename
        src = rec.get("SourceFile", "")
        name = Path(src).name if src else ""
        out[name] = rec
    return out


def _xmp_fragment(rec: dict[str, Any] | None) -> dict[str, str | None]:
    if not rec:
        return {
            "xmp_attribution_url": None,
            "xmp_external_metadata_link": None,
            "xmp_usage_terms": None,
            "iptc_credit": None,
            "iptc_contact": None,
        }
    return {
        "xmp_attribution_url": _coerce_str(rec.get("AttributionURL")),
        "xmp_external_metadata_link": _coerce_str(rec.get("ExternalMetadataLink")),
        "xmp_usage_terms": _coerce_str(rec.get("UsageTerms")),
        "iptc_credit": _coerce_str(rec.get("Credit")),
        "iptc_contact": _coerce_str(rec.get("Contact")),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def iter_image_paths(site_dir: Path, *, extensions: tuple[str, ...] = (".tif", ".tiff")) -> Iterator[Path]:
    for p in sorted(site_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in extensions:
            yield p


def build_inventory(
    site_dir: Path,
    *,
    hashes_by_name: dict[str, str] | None = None,
    ids_records: dict[str, IdsRecord] | None = None,
    use_exiftool: bool | None = None,
    exiftool_batch_size: int = 200,
) -> list[ImageRecord]:
    """Catalog every image in `site_dir`.

    `hashes_by_name` lets us reuse SHA-256 values from the acquisition
    provenance instead of re-hashing every file.

    `ids_records` is a {filename_lower: IdsRecord} dict from `load_ids_csv`.
    When supplied, CSV-primary fields (image_id, dtoriginal, cammake, …) are
    merged into each ImageRecord.  Per ADR-0009, these fields are canonical;
    on-disk EXIF equivalents remain in the record for reference.

    `use_exiftool=None` (default) auto-detects; True forces it on, False off.
    """
    paths = list(iter_image_paths(site_dir))
    if not paths:
        log.warning("No images found in %s", site_dir)
        return []

    if use_exiftool is None:
        use_exiftool = exiftool_available()
    elif use_exiftool and not exiftool_available():
        log.warning("use_exiftool=True but exiftool not on PATH; falling back to Pillow-only")
        use_exiftool = False

    # Batch exiftool over all images first.
    xmp_by_name: dict[str, dict[str, Any]] = {}
    if use_exiftool:
        log.info("Running exiftool in batches of %d over %d files", exiftool_batch_size, len(paths))
        for i in range(0, len(paths), exiftool_batch_size):
            batch = paths[i : i + exiftool_batch_size]
            xmp_by_name.update(_run_exiftool_bulk(batch))

    records: list[ImageRecord] = []
    hashes_by_name = hashes_by_name or {}
    ids_records = ids_records or {}
    for path in paths:
        rel = path.relative_to(site_dir.parent)
        pillow_frag, errors = _read_pillow_exif(path)
        xmp_frag = _xmp_fragment(xmp_by_name.get(path.name))
        csv_rec: IdsRecord | None = ids_records.get(path.name.lower())
        records.append(
            ImageRecord(
                name=path.name,
                relpath=str(rel),
                size_bytes=path.stat().st_size,
                sha256=hashes_by_name.get(path.name),
                width=pillow_frag["width"],
                height=pillow_frag["height"],
                exif_make=pillow_frag["exif_make"],
                exif_model=pillow_frag["exif_model"],
                exif_artist=pillow_frag["exif_artist"],
                exif_copyright=pillow_frag["exif_copyright"],
                exif_image_description=pillow_frag["exif_image_description"],
                exif_datetime_original=pillow_frag["exif_datetime_original"],
                gps_lat=pillow_frag["gps_lat"],
                gps_lon=pillow_frag["gps_lon"],
                xmp_attribution_url=xmp_frag["xmp_attribution_url"],
                xmp_external_metadata_link=xmp_frag["xmp_external_metadata_link"],
                xmp_usage_terms=xmp_frag["xmp_usage_terms"],
                iptc_credit=xmp_frag["iptc_credit"],
                iptc_contact=xmp_frag["iptc_contact"],
                software=pillow_frag["software"],
                orientation=pillow_frag["orientation"],
                csv_matched=csv_rec is not None,
                image_id=csv_rec.image_id if csv_rec else None,
                csv_dtoriginal_utc=csv_rec.dtoriginal if csv_rec else None,
                csv_cammake=csv_rec.cammake if csv_rec else None,
                csv_cammodel=csv_rec.cammodel if csv_rec else None,
                csv_artist=csv_rec.artist if csv_rec else None,
                csv_copyright=csv_rec.copyright if csv_rec else None,
                csv_lat=csv_rec.lat if csv_rec else None,
                csv_lon=csv_rec.lon if csv_rec else None,
                csv_uuid=csv_rec.uuid if csv_rec else None,
                read_errors=errors,
            )
        )
    return records


def write_inventory_json(records: Iterable[ImageRecord], path: Path) -> Path:
    payload = {
        "schema": "reef-sfm-provenance/inventory/v1",
        "count": 0,
        "records": [],
    }
    rec_list = [r.to_dict() for r in records]
    payload["count"] = len(rec_list)
    payload["records"] = rec_list
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return path


__all__ = [
    "ImageRecord",
    "build_inventory",
    "write_inventory_json",
    "iter_image_paths",
    "exiftool_available",
]
