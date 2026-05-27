"""Tests for the network-free surfaces of `reef_sfm_provenance.acquisition`."""

from __future__ import annotations

from pathlib import Path

import pytest

from reef_sfm_provenance.acquisition import (
    RemoteFile,
    _looks_like_site,
    _normalize_site,
    read_manifest_csv,
)


def test_normalize_site_handles_known_aliases():
    assert _normalize_site("eastern dry rocks") == "EasternDryRocks"
    assert _normalize_site("EASTERN_DRY_ROCKS") == "EasternDryRocks"
    assert _normalize_site("EasternDryRocks") == "EasternDryRocks"
    # Unknown aliases pass through unchanged so the API match step still tries.
    assert _normalize_site("SomeNewSite") == "SomeNewSite"


@pytest.mark.parametrize(
    "child_title, expected",
    [
        ("EasternDryRocks", True),
        ("Eastern Dry Rocks", True),
        ("Site: Eastern_Dry_Rocks Imagery", True),
        ("WesternSambo", False),
        ("Rock Key", False),
    ],
)
def test_looks_like_site(child_title, expected):
    assert _looks_like_site(child_title, "EasternDryRocks") is expected


def test_read_manifest_csv_minimal(tmp_path: Path):
    csv_path = tmp_path / "manifest.csv"
    csv_path.write_text(
        "url,name,size\n"
        "https://example.usgs.gov/a.tif,a.tif,123\n"
        "https://example.usgs.gov/b.tif,b.tif,456\n"
    )
    files = read_manifest_csv(csv_path)
    assert len(files) == 2
    assert files[0] == RemoteFile(
        url="https://example.usgs.gov/a.tif",
        name="a.tif",
        size=123,
        parent_item_id=None,
    )


def test_read_manifest_csv_requires_url_column(tmp_path: Path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("name,size\na.tif,123\n")
    with pytest.raises(ValueError):
        read_manifest_csv(csv_path)


def test_read_manifest_csv_infers_name_from_url(tmp_path: Path):
    csv_path = tmp_path / "manifest.csv"
    csv_path.write_text("url\nhttps://example.usgs.gov/edr_0001.tif\n")
    files = read_manifest_csv(csv_path)
    assert len(files) == 1
    assert files[0].name == "edr_0001.tif"
    assert files[0].size is None
