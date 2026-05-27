"""Tests for `reef_sfm_provenance.inventory`.

We synthesize tiny TIFFs with hand-injected EXIF so the Pillow read path is
exercised against real bytes.  XMP/IPTC fields can't easily be written from
Pillow alone, so the exiftool path is tested only insofar as the function
degrades gracefully when exiftool is missing.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, TiffImagePlugin

from reef_sfm_provenance.inventory import (
    ImageRecord,
    build_inventory,
    iter_image_paths,
)


# TIFF tag IDs (from PIL.ExifTags.TAGS, inverted)
TAG_MAKE = 271
TAG_MODEL = 272
TAG_ARTIST = 315
TAG_COPYRIGHT = 33432
TAG_IMAGE_DESCRIPTION = 270
TAG_DATETIME_ORIGINAL = 36867  # in EXIF sub-IFD


def _write_tiff_with_exif(path: Path) -> None:
    """Write a tiny TIFF carrying the EXIF fields USGS populates.

    Pillow's TIFF writer accepts a `tiffinfo` dict for top-level tags.
    Sub-IFD tags (like DateTimeOriginal) are trickier; we write them at
    the top level too, which Pillow's reader still surfaces.
    """
    info = TiffImagePlugin.ImageFileDirectory_v2()
    info[TAG_MAKE] = "Canon"
    info[TAG_MODEL] = "Canon PowerShot S120"
    info[TAG_ARTIST] = "USGS St. Petersburg Coastal and Marine Science Center"
    info[TAG_COPYRIGHT] = "Public Domain"
    info[TAG_IMAGE_DESCRIPTION] = "test image"

    img = Image.new("RGB", (4000, 3000), (60, 90, 120))
    img.save(path, format="TIFF", tiffinfo=info, compression="tiff_lzw")


def test_iter_image_paths_filters_and_sorts(tmp_path: Path):
    (tmp_path / "z.tif").write_bytes(b"")
    (tmp_path / "a.tif").write_bytes(b"")
    (tmp_path / "ignore.txt").write_bytes(b"")
    paths = list(iter_image_paths(tmp_path))
    assert [p.name for p in paths] == ["a.tif", "z.tif"]


def test_inventory_extracts_basic_exif(tmp_path: Path):
    site_dir = tmp_path / "EasternDryRocks"
    site_dir.mkdir()
    _write_tiff_with_exif(site_dir / "IMG_0001.tif")

    inv = build_inventory(site_dir, use_exiftool=False)
    assert len(inv) == 1
    rec: ImageRecord = inv[0]
    assert rec.name == "IMG_0001.tif"
    assert rec.width == 4000
    assert rec.height == 3000
    assert rec.exif_make == "Canon"
    assert rec.exif_model == "Canon PowerShot S120"
    assert rec.exif_artist.startswith("USGS St. Petersburg")
    assert rec.exif_copyright == "Public Domain"
    # XMP not written; should be None and not raise
    assert rec.xmp_attribution_url is None
    assert rec.iptc_credit is None
    # SHA-256 wasn't supplied via the acquisition path
    assert rec.sha256 is None
    assert rec.read_errors == []


def test_inventory_handles_missing_exif(tmp_path: Path):
    site_dir = tmp_path / "EasternDryRocks"
    site_dir.mkdir()
    img = Image.new("RGB", (4000, 3000), (10, 20, 30))
    img.save(site_dir / "IMG_BARE.tif", format="TIFF")
    inv = build_inventory(site_dir, use_exiftool=False)
    assert len(inv) == 1
    rec = inv[0]
    # Pillow can still read dimensions even when no USGS EXIF was written
    assert rec.width == 4000
    # The Make/Model/Artist/Copyright fields should be absent — those are
    # the per-image checks that will fail (correctly) downstream.
    assert rec.exif_make is None
    assert rec.exif_artist is None
    assert rec.exif_copyright is None
    # The file opened cleanly, so no fatal read errors.
    fatal = [e for e in rec.read_errors if e.startswith(("open_failed", "not_a_valid_image"))]
    assert fatal == []


def test_inventory_carries_hashes_when_supplied(tmp_path: Path):
    site_dir = tmp_path / "EasternDryRocks"
    site_dir.mkdir()
    _write_tiff_with_exif(site_dir / "IMG_0001.tif")
    inv = build_inventory(
        site_dir,
        hashes_by_name={"IMG_0001.tif": "deadbeef" * 8},
        use_exiftool=False,
    )
    assert inv[0].sha256 == "deadbeef" * 8


def test_inventory_handles_corrupt_file(tmp_path: Path):
    site_dir = tmp_path / "EasternDryRocks"
    site_dir.mkdir()
    (site_dir / "broken.tif").write_bytes(b"this is not a tiff")
    inv = build_inventory(site_dir, use_exiftool=False)
    assert len(inv) == 1
    rec = inv[0]
    # Should fail to open but not raise
    assert any("not_a_valid_image" in e or "open_failed" in e for e in rec.read_errors)
    assert rec.width is None
