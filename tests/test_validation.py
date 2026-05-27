"""Tests for `reef_sfm_provenance.validation`.

These exercise the rules in isolation against synthetic ImageRecord fixtures.
The point is to lock in the spec — each rule's pass/fail/warn/unverified
behavior against representative inputs — so future edits to the metadata
expectations are visible as test changes.
"""

from __future__ import annotations

import dataclasses

from reef_sfm_provenance.validation import (
    aggregate_per_image,
    overall_severity,
    validate_dataset,
    validate_image,
)


# ---------------------------------------------------------------------------
# Happy path: a fully valid USGS-published image
# ---------------------------------------------------------------------------


def test_good_record_passes_every_rule(good_record):
    findings = validate_image(good_record)
    codes = {f.code for f in findings}
    # We expect each named rule to have run exactly once.
    assert codes == {
        "camera_consistency", "dimensions", "exif_artist",
        "exif_copyright", "datetime_original", "gps_present",
        "xmp_attribution_url", "iptc_credit",
    }
    for f in findings:
        assert f.is_pass, f"{f.code} did not pass for known-good record: {f.message}"


# ---------------------------------------------------------------------------
# Per-image failure modes
# ---------------------------------------------------------------------------


def test_wrong_camera_fails(good_record_factory):
    rec = good_record_factory(exif_make="NIKON", exif_model="D7000")
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["camera_consistency"].is_fail
    assert "NIKON" in findings["camera_consistency"].message


def test_missing_exif_artist_fails(good_record_factory):
    rec = good_record_factory(exif_artist=None)
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["exif_artist"].is_fail


def test_wrong_copyright_fails(good_record_factory):
    rec = good_record_factory(exif_copyright="© Random Photographer")
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["exif_copyright"].is_fail


def test_xmp_unavailable_marks_unverified(good_record_factory):
    rec = good_record_factory(xmp_attribution_url=None, iptc_credit=None)
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["xmp_attribution_url"].severity == "unverified"
    assert findings["iptc_credit"].severity == "unverified"
    # And critically, NOT failures — exiftool absence is a tooling gap,
    # not a data quality problem.


def test_gps_outside_bbox_fails(good_record_factory):
    # Anywhere off Florida — these are roughly the Galapagos
    rec = good_record_factory(gps_lat=-0.9, gps_lon=-90.4)
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["gps_present"].is_fail


def test_gps_missing_fails(good_record_factory):
    rec = good_record_factory(gps_lat=None, gps_lon=None)
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["gps_present"].is_fail


def test_datetime_outside_window_warns(good_record_factory):
    rec = good_record_factory(exif_datetime_original="2019:08:01 10:00:00")
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["datetime_original"].severity == "warn"


def test_unparseable_datetime_warns(good_record_factory):
    rec = good_record_factory(exif_datetime_original="not-a-date")
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["datetime_original"].severity == "warn"


def test_unexpected_dimensions_warn(good_record_factory):
    rec = good_record_factory(width=1920, height=1080)
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["dimensions"].severity == "warn"


def test_read_errors_short_circuit_rules(good_record_factory):
    rec = good_record_factory(read_errors=["not_a_valid_image: truncated"])
    findings = validate_image(rec)
    # When the file couldn't be opened, only the read_errors finding
    # should be emitted — no point checking EXIF on an unreadable file.
    assert len(findings) == 1
    assert findings[0].code == "read_errors"
    assert findings[0].is_fail


# ---------------------------------------------------------------------------
# Dataset-level rules
# ---------------------------------------------------------------------------


def test_dataset_passes_with_good_inputs(good_dataset):
    findings = validate_dataset(good_dataset)
    codes = {f.code: f for f in findings}
    assert codes["file_count"].is_pass
    assert codes["dataset_camera_consistency"].is_pass
    assert codes["hash_uniqueness"].is_pass
    assert codes["gps_consistency"].is_pass
    assert codes["size_outliers"].is_pass


def test_empty_dataset_fails():
    findings = validate_dataset([])
    assert len(findings) == 1
    assert findings[0].code == "file_count"
    assert findings[0].is_fail


def test_too_few_files_warns(good_dataset):
    # Slice to below EXPECTED_FILE_COUNT_MIN
    findings = {f.code: f for f in validate_dataset(good_dataset[:500])}
    assert findings["file_count"].severity == "warn"


def test_duplicate_hashes_fail(good_dataset):
    # Force two files to share a hash
    poisoned = list(good_dataset)
    poisoned[5] = dataclasses.replace(poisoned[5], sha256=poisoned[10].sha256)
    findings = {f.code: f for f in validate_dataset(poisoned)}
    assert findings["hash_uniqueness"].is_fail
    assert "1 hash collision" in findings["hash_uniqueness"].message


def test_mixed_cameras_warn(good_dataset):
    poisoned = list(good_dataset)
    poisoned[42] = dataclasses.replace(poisoned[42], exif_model="EOS R")
    findings = {f.code: f for f in validate_dataset(poisoned)}
    assert findings["dataset_camera_consistency"].severity == "warn"


def test_size_outlier_detection(good_dataset):
    poisoned = list(good_dataset)
    # 30 tiny files — below 40% of median
    for i in range(30):
        poisoned[i] = dataclasses.replace(poisoned[i], size_bytes=100_000)
    findings = {f.code: f for f in validate_dataset(poisoned)}
    assert findings["size_outliers"].severity == "warn"


def test_gps_single_station_passes(good_dataset):
    """All images share the surface station coordinate — the only physical
    possibility, because GPS does not work underwater."""
    findings = {f.code: f for f in validate_dataset(good_dataset)}
    assert findings["gps_consistency"].is_pass
    assert "one station coordinate" in findings["gps_consistency"].message


def test_gps_two_close_fixes_warn(good_dataset):
    """Two surface fixes a few meters apart — re-survey day, worth a warn but
    not a fail."""
    poisoned = list(good_dataset)
    # Shift ~10m east on the second fix (1m ≈ 9e-6 deg lon at this latitude)
    for i in range(20):
        poisoned[i] = dataclasses.replace(poisoned[i], gps_lon=-81.48772)
    findings = {f.code: f for f in validate_dataset(poisoned)}
    assert findings["gps_consistency"].severity == "warn"
    assert findings["gps_consistency"].details["unique_fixes"] == 2


def test_gps_mixed_sites_fails(good_dataset):
    """Two surface fixes from clearly different sites — directory merge bug."""
    poisoned = list(good_dataset)
    # ~2km away — a different reef entirely
    for i in range(200):
        poisoned[i] = dataclasses.replace(poisoned[i], gps_lat=24.55, gps_lon=-81.50)
    findings = {f.code: f for f in validate_dataset(poisoned)}
    assert findings["gps_consistency"].is_fail
    assert "different sites" in findings["gps_consistency"].message


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def test_aggregate_counts_correctly(good_record_factory):
    findings = []
    for i in range(10):
        findings.extend(validate_image(good_record_factory(name=f"good_{i}.tif")))
    bad = good_record_factory(name="bad.tif", exif_artist=None)
    findings.extend(validate_image(bad))
    rollup = aggregate_per_image(findings)
    # 10 + 1 records ran the artist check; 10 pass, 1 fail
    assert rollup["exif_artist"]["ok"] == 10
    assert rollup["exif_artist"]["fail"] == 1


def test_overall_severity_is_max(good_record_factory):
    rec_good = good_record_factory(name="good.tif")
    rec_warn = good_record_factory(name="warn.tif", exif_datetime_original="2010:01:01 00:00:00")
    rec_fail = good_record_factory(name="fail.tif", exif_artist=None)
    findings = (
        validate_image(rec_good)
        + validate_image(rec_warn)
        + validate_image(rec_fail)
    )
    assert overall_severity(findings) == "fail"
    assert overall_severity(validate_image(rec_good)) == "ok"
    assert overall_severity(validate_image(rec_warn)) == "warn"
