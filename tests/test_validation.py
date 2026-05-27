"""Tests for `reef_sfm_provenance.validation`.

These exercise the rules in isolation against synthetic ImageRecord fixtures.
The point is to lock in the spec — each rule's pass/fail/warn/unverified
behavior against representative inputs — so future edits to the metadata
expectations are visible as test changes.
"""

from __future__ import annotations

import dataclasses

from reef_sfm_provenance.validation import (
    TOTH_FILENAME_RE,
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
    assert codes == {
        "csv_join", "software_lineage", "filename_pattern",
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
    # CSV values are canonical; must override both CSV and EXIF fields.
    rec = good_record_factory(
        exif_make="NIKON", exif_model="D7000",
        csv_cammake="NIKON CORPORATION", csv_cammodel="D7000",
    )
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["camera_consistency"].is_fail
    assert "NIKON" in findings["camera_consistency"].message


def test_missing_exif_artist_fails(good_record_factory):
    rec = good_record_factory(exif_artist=None, csv_artist=None)
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["exif_artist"].is_fail


def test_wrong_copyright_fails(good_record_factory):
    rec = good_record_factory(
        exif_copyright="© Random Photographer",
        csv_copyright="© Random Photographer",
    )
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["exif_copyright"].is_fail


def test_xmp_unavailable_marks_unverified(good_record_factory):
    rec = good_record_factory(xmp_attribution_url=None, iptc_credit=None)
    findings = {f.code: f for f in validate_image(rec)}
    # xmp_attribution_url: no value means exiftool was absent → unverified.
    assert findings["xmp_attribution_url"].severity == "unverified"
    # iptc_credit: absent credit with EXIF Artist+Copyright present → warn (not fail).
    # Exiftool absence is a tooling gap, not a data quality problem; EXIF rights
    # provide equivalent documentation (ADR-0009 three-layer metadata picture).
    assert findings["iptc_credit"].severity == "warn"


def test_gps_outside_bbox_fails(good_record_factory):
    # CSV coordinates are canonical; must override both CSV and EXIF GPS.
    rec = good_record_factory(
        gps_lat=-0.9, gps_lon=-90.4,
        csv_lat=-0.9, csv_lon=-90.4,
    )
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["gps_present"].is_fail


def test_gps_missing_fails(good_record_factory):
    rec = good_record_factory(
        gps_lat=None, gps_lon=None,
        csv_lat=None, csv_lon=None,
    )
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["gps_present"].is_fail


def test_datetime_outside_window_warns(good_record_factory):
    # Rule now reads csv_dtoriginal_utc (ISO 8601), not exif_datetime_original.
    rec = good_record_factory(csv_dtoriginal_utc="2019-08-01T10:00:00+00:00")
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["datetime_original"].severity == "warn"


def test_unparseable_datetime_warns(good_record_factory):
    rec = good_record_factory(csv_dtoriginal_utc="not-a-date")
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["datetime_original"].severity == "warn"


def test_missing_csv_datetime_unverified(good_record_factory):
    rec = good_record_factory(csv_dtoriginal_utc=None)
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["datetime_original"].severity == "unverified"


def test_unexpected_dimensions_fail(good_record_factory):
    # Dimensions are verifiable on-disk; wrong size is a real failure, not a warning.
    rec = good_record_factory(width=1920, height=1080)
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["dimensions"].is_fail


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


def test_csv_join_missing_fails(good_record_factory):
    rec = good_record_factory(csv_matched=False, image_id=None)
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["csv_join"].is_fail


def test_software_lineage_photoshop_passes(good_record_factory):
    rec = good_record_factory(software="Adobe Photoshop 24.6 (Windows)")
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["software_lineage"].is_pass


def test_software_lineage_wrong_software_fails(good_record_factory):
    rec = good_record_factory(software="GIMP 2.10")
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["software_lineage"].is_fail


def test_software_lineage_missing_fails(good_record_factory):
    rec = good_record_factory(software=None)
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["software_lineage"].is_fail


def test_software_lineage_windows_photo_viewer_warns(good_record_factory):
    rec = good_record_factory(software="Microsoft Windows Photo Viewer 10.0.19041.1")
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["software_lineage"].severity == "warn"
    assert "workflow variation" in findings["software_lineage"].message


def test_software_lineage_unknown_value_fails(good_record_factory):
    rec = good_record_factory(software="IrfanView 4.67")
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["software_lineage"].is_fail
    assert "allowlist" in findings["software_lineage"].message


def test_iptc_credit_present_passes(good_record_factory):
    """Any non-empty IPTC Credit → ok; rule does not assert a specific institution."""
    rec = good_record_factory(iptc_credit="Some Generic Institution Name")
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["iptc_credit"].is_pass
    assert findings["iptc_credit"].details["actual"] == "Some Generic Institution Name"


def test_iptc_credit_absent_with_exif_rights_warns(good_record_factory):
    """IPTC Credit absent but EXIF Artist + Copyright present → warn (EDR pattern)."""
    rec = good_record_factory(iptc_credit=None)
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["iptc_credit"].severity == "warn"
    assert "redundant-field-not-set" in findings["iptc_credit"].message


def test_iptc_credit_absent_without_exif_rights_fails(good_record_factory):
    """IPTC Credit absent AND EXIF Artist absent → fail (no rights docs anywhere)."""
    rec = good_record_factory(
        iptc_credit=None,
        exif_artist=None, csv_artist=None,
    )
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["iptc_credit"].is_fail
    assert "rights documentation cannot be confirmed" in findings["iptc_credit"].message


def test_dataset_passes_with_good_inputs(good_dataset):
    findings = validate_dataset(good_dataset)
    codes = {f.code: f for f in findings}
    assert codes["file_count"].is_pass
    assert codes["dataset_camera_consistency"].is_pass
    assert codes["hash_uniqueness"].is_pass
    assert codes["gps_consistency"].is_pass
    assert codes["size_outliers"].is_pass
    assert codes["csv_coverage"].is_pass
    assert codes["subsite_cross_reference"].is_pass


def test_empty_dataset_fails():
    findings = validate_dataset([])
    assert len(findings) == 1
    assert findings[0].code == "file_count"
    assert findings[0].is_fail


def test_too_few_files_warns(good_dataset):
    # Slice to below EXPECTED_FILE_COUNT_MIN
    findings = {f.code: f for f in validate_dataset(good_dataset[:500])}
    assert findings["file_count"].severity == "warn"


def test_hash_uniqueness_ok(good_record_factory):
    """Three files with distinct hashes → ok, count reported."""
    records = [
        good_record_factory(name=f"20220715_EDR_T1_R1_{i:06d}.tif", sha256=f"{i:064x}")
        for i in range(3)
    ]
    findings = {f.code: f for f in validate_dataset(records)}
    assert findings["hash_uniqueness"].is_pass
    assert "3" in findings["hash_uniqueness"].message


def test_duplicate_hashes_fail(good_dataset):
    # Force two files to share a hash
    poisoned = list(good_dataset)
    poisoned[5] = dataclasses.replace(poisoned[5], sha256=poisoned[10].sha256)
    findings = {f.code: f for f in validate_dataset(poisoned)}
    assert findings["hash_uniqueness"].is_fail
    assert "1 hash collision" in findings["hash_uniqueness"].message


def test_hash_uniqueness_unverified_when_no_hashes(good_record_factory):
    """Defensive: all sha256=None → unverified (should not occur post inventory fix)."""
    records = [
        good_record_factory(name=f"20220715_EDR_T1_R1_{i:06d}.tif", sha256=None)
        for i in range(3)
    ]
    findings = {f.code: f for f in validate_dataset(records)}
    assert findings["hash_uniqueness"].severity == "unverified"


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
    """All images share one station coordinate — expected for a single dive event."""
    findings = {f.code: f for f in validate_dataset(good_dataset)}
    assert findings["gps_consistency"].is_pass


def test_gps_multiple_events_within_bbox_passes(good_dataset):
    """Multiple station fixes within the site bbox are OK (multi-subsite dataset)."""
    poisoned = list(good_dataset)
    # Shift a subset to a second station a few hundred metres away, still in bbox.
    for i in range(200):
        poisoned[i] = dataclasses.replace(
            poisoned[i], csv_lat=24.55, csv_lon=-81.50
        )
    findings = {f.code: f for f in validate_dataset(poisoned)}
    assert findings["gps_consistency"].is_pass
    assert findings["gps_consistency"].details["unique_fixes"] == 2


def test_gps_out_of_bbox_fails(good_dataset):
    """A station fix outside the Lower Florida Keys bbox — directory merge bug."""
    poisoned = list(good_dataset)
    # Miami area — clearly outside the reef site bbox
    for i in range(200):
        poisoned[i] = dataclasses.replace(poisoned[i], csv_lat=25.8, csv_lon=-80.2)
    findings = {f.code: f for f in validate_dataset(poisoned)}
    assert findings["gps_consistency"].is_fail


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def test_aggregate_counts_correctly(good_record_factory):
    findings = []
    for i in range(10):
        findings.extend(validate_image(good_record_factory(name=f"20220715_EDR_T1_R1_{i:06d}.tif")))
    bad = good_record_factory(name=f"20220715_EDR_T1_R1_{10:06d}.tif", exif_artist=None, csv_artist=None)
    findings.extend(validate_image(bad))
    rollup = aggregate_per_image(findings)
    assert rollup["exif_artist"]["ok"] == 10
    assert rollup["exif_artist"]["fail"] == 1


# ---------------------------------------------------------------------------
# Filename pattern rule
# ---------------------------------------------------------------------------


def test_filename_pattern_valid_toth_name(good_record_factory):
    rec = good_record_factory(name="20220715_EDR_T1_R1_000001.tif")
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["filename_pattern"].is_pass
    assert findings["filename_pattern"].details["transect"] == "T1"
    assert findings["filename_pattern"].details["site"] == "EDR"


def test_filename_pattern_non_toth_name_fails(good_record_factory):
    rec = good_record_factory(name="IMG_0001.tif")
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["filename_pattern"].is_fail


def test_filename_pattern_re_matches_variants():
    # T1, T3, T8; R1, R6; 6-digit seq
    assert TOTH_FILENAME_RE.match("20230711_EDR_T8_R6_000300.tif")
    assert TOTH_FILENAME_RE.match("20220715_EDR_T1_R1_000001.TIF")  # uppercase ext
    assert TOTH_FILENAME_RE.match("20230715_EDR_T3_R2_000100.tif")
    assert not TOTH_FILENAME_RE.match("IMG_0001.tif")
    assert not TOTH_FILENAME_RE.match("20220715_EDR_T1_R1_0001.tif")  # only 4 digits in seq


def test_filename_pattern_c_and_r_swath_both_pass(good_record_factory):
    """C# and R# swath designators are both valid per the double-lawnmower pattern."""
    rec_c = good_record_factory(name="20230711_EDR_T1_C2_000000.tif")
    rec_r = good_record_factory(name="20230711_EDR_T1_R2_000000.tif")
    findings_c = {f.code: f for f in validate_image(rec_c)}
    findings_r = {f.code: f for f in validate_image(rec_r)}
    assert findings_c["filename_pattern"].is_pass
    assert findings_c["filename_pattern"].details["swath"] == "C2"
    assert findings_r["filename_pattern"].is_pass
    assert findings_r["filename_pattern"].details["swath"] == "R2"


def test_filename_pattern_invalid_swath_letter_fails(good_record_factory):
    """Any swath letter other than R or C is not a valid Toth convention name."""
    rec = good_record_factory(name="20230711_EDR_T1_X2_000000.tif")
    findings = {f.code: f for f in validate_image(rec)}
    assert findings["filename_pattern"].is_fail


# ---------------------------------------------------------------------------
# Subsite cross-reference rule
# ---------------------------------------------------------------------------


def test_subsite_cross_reference_single_transect_passes(good_dataset):
    # good_dataset: all T1, all same UUID
    findings = {f.code: f for f in validate_dataset(good_dataset)}
    assert findings["subsite_cross_reference"].is_pass
    assert findings["subsite_cross_reference"].details["transects"]["T1"]["uuid_count"] == 1


def test_subsite_cross_reference_multi_transect_passes(good_record_factory):
    """Different T# groups each with their own UUID is expected for a multi-subsite site."""
    records = [
        good_record_factory(
            name=f"20220715_EDR_T1_R1_{i:06d}.tif",
            sha256=f"t1{i:062d}",
            csv_uuid="uuid-t1-aaa",
        )
        for i in range(100)
    ] + [
        good_record_factory(
            name=f"20220715_EDR_T3_R1_{i:06d}.tif",
            sha256=f"t3{i:062d}",
            csv_uuid="uuid-t3-bbb",
        )
        for i in range(100)
    ]
    findings = {f.code: f for f in validate_dataset(records)}
    assert findings["subsite_cross_reference"].is_pass
    tbl = findings["subsite_cross_reference"].details["transects"]
    assert tbl["T1"]["uuid_count"] == 1
    assert tbl["T3"]["uuid_count"] == 1


def test_subsite_cross_reference_mixed_uuid_fails(good_record_factory):
    """T1 images with two different UUIDs → images from two dive events got merged."""
    records = [
        good_record_factory(
            name=f"20220715_EDR_T1_R1_{i:06d}.tif",
            sha256=f"a{i:063d}",
            csv_uuid="uuid-event-aaa" if i < 50 else "uuid-event-bbb",
        )
        for i in range(100)
    ]
    findings = {f.code: f for f in validate_dataset(records)}
    assert findings["subsite_cross_reference"].is_fail
    assert "T1" in findings["subsite_cross_reference"].message


def test_subsite_cross_reference_no_uuid_unverified(good_record_factory):
    """When IDS CSV wasn't loaded, uuid is None → cross-reference is unverified."""
    records = [
        good_record_factory(
            name=f"20220715_EDR_T1_R1_{i:06d}.tif",
            sha256=f"{i:064x}",
            csv_uuid=None,
        )
        for i in range(10)
    ]
    findings = {f.code: f for f in validate_dataset(records)}
    assert findings["subsite_cross_reference"].severity == "unverified"


def test_overall_severity_is_max(good_record_factory):
    rec_good = good_record_factory(name="20220715_EDR_T1_R1_000001.tif")
    rec_warn = good_record_factory(name="20220715_EDR_T1_R1_000002.tif", csv_dtoriginal_utc="2010-01-01T00:00:00+00:00")
    rec_fail = good_record_factory(name="20220715_EDR_T1_R1_000003.tif", exif_artist=None, csv_artist=None)
    findings = (
        validate_image(rec_good)
        + validate_image(rec_warn)
        + validate_image(rec_fail)
    )
    assert overall_severity(findings) == "fail"
    assert overall_severity(validate_image(rec_good)) == "ok"
    assert overall_severity(validate_image(rec_warn)) == "warn"
