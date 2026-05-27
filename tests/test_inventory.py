"""Tests for `reef_sfm_provenance.inventory`.

We synthesize tiny TIFFs with hand-injected EXIF so the Pillow read path is
exercised against real bytes.  XMP/IPTC fields can't easily be written from
Pillow alone, so the exiftool path is tested only insofar as the function
degrades gracefully when exiftool is missing.
"""

from __future__ import annotations

import io
import struct
from pathlib import Path

import pytest
from PIL import Image, TiffImagePlugin

from reef_sfm_provenance.inventory import (
    ImageRecord,
    _read_pillow_exif,
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


def _write_tiff_with_exif_subifd(path: Path, datetime_str: str = "2022:07:15 14:32:00") -> None:
    """Write a minimal little-endian grayscale TIFF with a real Exif sub-IFD pointer.

    Structure:
      - IFD0: required TIFF tags for a 1x1 8-bit grayscale image
               + ExifIFD pointer (tag 0x8769) to the sub-IFD
      - Exif sub-IFD: DateTimeOriginal (tag 0x9003, ASCII)
      - 1-byte pixel strip

    PIL's Exif.get_ifd(0x8769) must seek to the sub-IFD offset in the file;
    it cannot be satisfied from bytes already buffered during header parsing.
    This guarantees that calling get_ifd() after the file is closed raises
    ValueError -- reproducing the production crash.
    """
    LE = "<"

    datetime_bytes = datetime_str.encode("ascii") + b"\x00"
    dto_len = len(datetime_bytes)

    exif_ifd_entry_count = 1
    exif_ifd_size = 2 + exif_ifd_entry_count * 12 + 4  # count + entry + next_ptr

    strip_data = bytes([255])  # one white grayscale pixel

    # IFD0 must be sorted by tag ID and must include Compression and
    # PhotometricInterpretation for PIL to recognize the file as a valid TIFF.
    ifd0_entry_count = 9
    ifd0_size = 2 + ifd0_entry_count * 12 + 4

    header_size = 8
    ifd0_offset = header_size
    exif_ifd_offset = ifd0_offset + ifd0_size
    dto_data_offset = exif_ifd_offset + exif_ifd_size
    strip_offset = dto_data_offset + dto_len

    buf = io.BytesIO()

    # TIFF header
    buf.write(b"II")
    buf.write(struct.pack(LE + "H", 42))
    buf.write(struct.pack(LE + "I", ifd0_offset))

    # IFD0 entries sorted by tag ID
    buf.write(struct.pack(LE + "H", ifd0_entry_count))
    for tag, typ, count, value in [
        (256,    3, 1, 1),                # ImageWidth SHORT
        (257,    3, 1, 1),                # ImageLength SHORT
        (258,    3, 1, 8),                # BitsPerSample SHORT
        (259,    3, 1, 1),                # Compression SHORT (none=1)
        (262,    3, 1, 1),                # PhotometricInterpretation SHORT (1=black-is-zero)
        (273,    4, 1, strip_offset),     # StripOffsets LONG
        (278,    3, 1, 1),                # RowsPerStrip SHORT
        (279,    3, 1, 1),                # StripByteCounts SHORT
        (0x8769, 4, 1, exif_ifd_offset),  # ExifIFD LONG
    ]:
        buf.write(struct.pack(LE + "HHI", tag, typ, count))
        if typ == 3:  # SHORT: 2-byte value, zero-padded to 4 bytes
            buf.write(struct.pack(LE + "HH", value, 0))
        else:         # LONG: 4-byte value
            buf.write(struct.pack(LE + "I", value))
    buf.write(struct.pack(LE + "I", 0))  # next IFD ptr

    # Exif sub-IFD: DateTimeOriginal
    buf.write(struct.pack(LE + "H", exif_ifd_entry_count))
    buf.write(struct.pack(LE + "HHI", 0x9003, 2, dto_len))  # tag, ASCII type, count
    buf.write(struct.pack(LE + "I", dto_data_offset))        # value = data offset
    buf.write(struct.pack(LE + "I", 0))                      # next IFD ptr

    buf.write(datetime_bytes)
    buf.write(strip_data)

    path.write_bytes(buf.getvalue())


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
    # The Make/Model/Artist/Copyright fields should be absent -- those are
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


# ---------------------------------------------------------------------------
# Exif sub-IFD lifecycle tests
# ---------------------------------------------------------------------------


def test_exif_get_ifd_fails_after_close(tmp_path: Path):
    """Document PIL's behavior: get_ifd() raises ValueError when file is closed.

    This is the exact failure mode that hit production.  The test should
    remain in the suite as a living specification of the library contract.
    """
    tiff = tmp_path / "subifd.tif"
    _write_tiff_with_exif_subifd(tiff)

    with Image.open(tiff) as im:
        exif = im.getexif()
    # File is now closed.  get_ifd() must seek to the sub-IFD offset.
    with pytest.raises((ValueError, OSError)):
        exif.get_ifd(0x8769)


def test_read_pillow_exif_subifd_lifecycle(tmp_path: Path):
    """_read_pillow_exif extracts DateTimeOriginal from Exif sub-IFD without crash."""
    tiff = tmp_path / "subifd.tif"
    _write_tiff_with_exif_subifd(tiff, datetime_str="2022:07:15 14:32:00")

    frag, errors = _read_pillow_exif(tiff)
    assert errors == [], f"unexpected read errors: {errors}"
    assert frag["exif_datetime_original"] == "2022:07:15 14:32:00"
    assert frag["width"] == 1
    assert frag["height"] == 1
