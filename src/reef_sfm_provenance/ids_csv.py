"""
Loader for the IDS viewer exif_data.csv (ADR-0009).

The CSV is a rights/identity export from the USGS IDS viewer, not a camera
technical export.  It is the canonical source for: filename ↔ image_id mapping,
cammake/cammodel, artist, copyright, and dtoriginal (UTC-clean ISO 8601).

GPS coordinates in this CSV are station-level (one per dive event), not
per-image.  The gpsareainformation field explicitly documents this.

Six columns are always null across all 39 480 rows and are silently dropped
on load: event, pid, gpsdate, gpstime, dtdigitized, contributor.
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# Path relative to the project root, as tracked in git.
IDS_CSV_DEFAULT = Path("data/reference/ids_export/exif_data.csv")

# Columns that are 100 % null in the full P1WHKTRD export; skip on ingest.
_NULL_COLS = {"event", "pid", "gpsdate", "gpstime", "dtdigitized", "contributor"}


@dataclasses.dataclass(frozen=True)
class IdsRecord:
    """One row of the IDS exif_data.csv, restricted to columns we use."""

    image_id: int
    uuid: str
    cammake: str | None
    cammodel: str | None
    artist: str | None
    copyright: str | None
    dtoriginal: str | None  # ISO 8601 UTC, e.g. "2023-07-12 14:39:55+00:00"
    lat: float | None
    lon: float | None  # CSV column name is "lng"


def _str_or_none(value: object) -> str | None:
    if pd.isna(value):
        return None
    s = str(value).strip()
    return s or None


def _float_or_none(value: object) -> float | None:
    if pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_ids_csv(path: Path) -> dict[str, IdsRecord]:
    """Load exif_data.csv and return {filename_lower: IdsRecord}.

    Keys are lowercased for case-insensitive joins with on-disk filenames.
    Rows missing a preservedfilename are silently skipped.
    """
    usecols = [
        "image_id", "uuid", "preservedfilename",
        "cammake", "cammodel", "artist", "copyright",
        "dtoriginal", "lat", "lng",
    ]
    df = pd.read_csv(path, usecols=usecols, low_memory=False)
    log.info("Loaded IDS CSV: %d rows from %s", len(df), path)

    result: dict[str, IdsRecord] = {}
    for row in df.itertuples(index=False):
        fname = _str_or_none(row.preservedfilename)
        if not fname:
            continue
        key = fname.lower()
        result[key] = IdsRecord(
            image_id=int(row.image_id),
            uuid=_str_or_none(row.uuid) or "",
            cammake=_str_or_none(row.cammake),
            cammodel=_str_or_none(row.cammodel),
            artist=_str_or_none(row.artist),
            copyright=_str_or_none(row.copyright),
            dtoriginal=_str_or_none(row.dtoriginal),
            lat=_float_or_none(row.lat),
            lon=_float_or_none(row.lng),
        )
    log.info("IDS CSV indexed %d unique filenames", len(result))
    return result


__all__ = ["IdsRecord", "IDS_CSV_DEFAULT", "load_ids_csv"]
