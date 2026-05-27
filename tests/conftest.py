"""Shared fixtures for the reef_sfm_provenance test suite."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from reef_sfm_provenance.inventory import ImageRecord
from reef_sfm_provenance.validation import (
    EXPECTED_EXIF_ARTIST,
    EXPECTED_EXIF_COPYRIGHT,
    EXPECTED_IPTC_CREDIT,
    EXPECTED_XMP_ATTRIBUTION_URL,
)


def _good_record(name: str = "IMG_0001.tif", **overrides: Any) -> ImageRecord:
    """An ImageRecord that should pass every per-image rule."""
    base = ImageRecord(
        name=name,
        relpath=f"EasternDryRocks/{name}",
        size_bytes=12_345_678,
        sha256="a" * 64,
        width=4000,
        height=3000,
        exif_make="Canon",
        exif_model="Canon PowerShot S120",
        exif_artist=EXPECTED_EXIF_ARTIST,
        exif_copyright=EXPECTED_EXIF_COPYRIGHT,
        exif_image_description=(
            "https://cmgds.marine.usgs.gov/fan_info.php?fan=2022-324-FA; "
            "Diver-based Structure-from-Motion image data from USGS field activity 2022-324-FA"
        ),
        exif_datetime_original="2022:07:15 14:32:00",
        gps_lat=24.53055,
        gps_lon=-81.48781,
        xmp_attribution_url=EXPECTED_XMP_ATTRIBUTION_URL,
        xmp_external_metadata_link="https://www1.usgs.gov/pir/api/identifiers/USGS:0cb09b6b-7c38-4c6f-a1dc-afc4033ab4be",
        xmp_usage_terms="Unless otherwise stated, all data, metadata and related materials …",
        iptc_credit=EXPECTED_IPTC_CREDIT,
        iptc_contact="gs-g-spcmsc_data_inquiries@usgs.gov",
        # CSV-primary fields (ADR-0009)
        software="Adobe Photoshop 24.6 (Windows)",
        orientation=1,
        csv_matched=True,
        image_id=843464,
        csv_dtoriginal_utc="2022-07-15T14:32:00+00:00",
        csv_cammake="Canon",
        csv_cammodel="Canon PowerShot S120",
        csv_artist=EXPECTED_EXIF_ARTIST,
        csv_copyright=EXPECTED_EXIF_COPYRIGHT,
        csv_lat=24.53055,
        csv_lon=-81.48781,
    )
    return dataclasses.replace(base, **overrides)


@pytest.fixture
def good_record() -> ImageRecord:
    return _good_record()


@pytest.fixture
def good_record_factory():
    return _good_record


@pytest.fixture
def good_dataset() -> list[ImageRecord]:
    """A 1500-image batch of good records, hashes uniquified to pass uniqueness."""
    records: list[ImageRecord] = []
    for i in range(1500):
        rec = _good_record(
            name=f"IMG_{i:04d}.tif",
            sha256=f"{i:064x}",
            size_bytes=10_000_000 + (i * 137 % 5_000_000),
            exif_datetime_original=f"2022:07:15 {(i // 60) % 24:02d}:{i % 60:02d}:00",
            csv_dtoriginal_utc=f"2022-07-15T{(i // 60) % 24:02d}:{i % 60:02d}:00+00:00",
        )
        records.append(rec)
    return records
