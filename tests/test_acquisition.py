"""Tests for the network-free surfaces of `reef_sfm_provenance.acquisition`."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from reef_sfm_provenance.acquisition import (
    RemoteFile,
    DownloadResult,
    _looks_like_site,
    _normalize_site,
    download_all,
    read_manifest_csv,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_session(content_map: dict[str, bytes]) -> MagicMock:
    """Return a mock requests.Session that serves canned bytes keyed by URL."""
    sess = MagicMock()

    def _fake_get(url: str, **kwargs: object) -> MagicMock:
        data = content_map[url]
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.iter_content.return_value = iter([data])
        resp.__enter__ = lambda s: resp
        resp.__exit__ = lambda s, *a: False
        return resp

    sess.get.side_effect = _fake_get
    return sess


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


# ---------------------------------------------------------------------------
# download_all — parallel path
# ---------------------------------------------------------------------------


def test_download_all_preserves_input_order(tmp_path: Path):
    """Results must come back in the same order as the input file list."""
    n = 5
    urls = [f"https://example.com/file{i}.tif" for i in range(n)]
    content_map = {url: f"payload{i}".encode() for i, url in enumerate(urls)}
    files = [
        RemoteFile(url=url, name=f"file{i}.tif", size=None, parent_item_id=None)
        for i, url in enumerate(urls)
    ]

    results = download_all(files, tmp_path, session=_mock_session(content_map), max_workers=4)

    assert len(results) == n
    for i, r in enumerate(results):
        assert r.name == f"file{i}.tif"
        assert r.url == urls[i]
        assert r.notes == "downloaded"


def test_download_all_skips_existing_with_matching_hash(tmp_path: Path):
    """A file already on disk with a matching hash must be skipped; session.get not called."""
    content = b"tiff image bytes"
    sha = hashlib.sha256(content).hexdigest()
    remote = RemoteFile(
        url="https://example.com/img.tif",
        name="img.tif",
        size=len(content),
        parent_item_id=None,
    )
    (tmp_path / "img.tif").write_bytes(content)

    sess = _mock_session({})  # empty — any get() call would KeyError
    results = download_all(
        [remote],
        tmp_path,
        expected_hashes={"img.tif": sha},
        session=sess,
    )

    assert len(results) == 1
    assert results[0].notes == "resumed"
    assert results[0].sha256 == sha
    sess.get.assert_not_called()


def test_download_all_max_workers_1_matches_parallel(tmp_path: Path):
    """max_workers=1 (serial) and max_workers=4 must produce identical results."""
    n = 6
    urls = [f"https://example.com/img{i}.tif" for i in range(n)]
    contents = {url: f"bytes{i}".encode() for i, url in enumerate(urls)}
    files = [
        RemoteFile(url=url, name=f"img{i}.tif", size=None, parent_item_id=None)
        for i, url in enumerate(urls)
    ]

    out_serial = tmp_path / "serial"
    out_parallel = tmp_path / "parallel"
    out_serial.mkdir()
    out_parallel.mkdir()

    r_serial = download_all(files, out_serial, session=_mock_session(contents), max_workers=1)
    r_parallel = download_all(files, out_parallel, session=_mock_session(contents), max_workers=4)

    assert [(r.name, r.sha256, r.notes) for r in r_serial] == [
        (r.name, r.sha256, r.notes) for r in r_parallel
    ]
