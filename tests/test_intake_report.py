"""Tests for `reef_sfm_provenance.intake_report`."""

from __future__ import annotations

import json
from pathlib import Path

from reef_sfm_provenance.intake_report import (
    build_report,
    write_report_json,
    write_report_markdown,
)
from reef_sfm_provenance.validation import (
    validate_dataset,
    validate_image,
)


def test_report_shape(good_dataset):
    per_image = []
    for rec in good_dataset:
        per_image.extend(validate_image(rec))
    dataset = validate_dataset(good_dataset)
    report = build_report(
        site="EasternDryRocks",
        doi="10.5066/P1WHKTRD",
        site_dir=Path("/tmp/EasternDryRocks"),
        inventory=good_dataset,
        dataset_findings=dataset,
        per_image_findings=per_image,
    )
    # Stable top-level schema
    assert report["schema"] == "reef-sfm-provenance/intake_qc/v1"
    assert report["site"] == "EasternDryRocks"
    assert report["doi"] == "10.5066/P1WHKTRD"
    assert report["image_count"] == 1500
    assert report["overall_severity"] == "ok"

    # Rollup carries every per-image rule code, with full count
    assert report["per_image_findings_rollup"]["exif_artist"]["ok"] == 1500


def test_report_marks_failures(good_dataset, good_record_factory):
    bad = good_record_factory(name="hard_fail.tif", exif_artist=None, sha256="ff" * 32)
    inv = good_dataset + [bad]
    per_image = []
    for rec in inv:
        per_image.extend(validate_image(rec))
    dataset = validate_dataset(inv)
    report = build_report(
        site="EasternDryRocks",
        doi="10.5066/P1WHKTRD",
        site_dir=Path("/tmp/EasternDryRocks"),
        inventory=inv,
        dataset_findings=dataset,
        per_image_findings=per_image,
    )
    assert report["overall_severity"] == "fail"
    assert "hard_fail.tif" in report["files_with_failures"]


def test_report_round_trips_to_disk(tmp_path: Path, good_dataset):
    per_image = []
    for rec in good_dataset:
        per_image.extend(validate_image(rec))
    dataset = validate_dataset(good_dataset)
    report = build_report(
        site="EasternDryRocks",
        doi="10.5066/P1WHKTRD",
        site_dir=tmp_path,
        inventory=good_dataset,
        dataset_findings=dataset,
        per_image_findings=per_image,
    )
    json_path = write_report_json(report, tmp_path / "report.json")
    md_path = write_report_markdown(report, tmp_path / "report.md")
    assert json.loads(json_path.read_text())["schema"] == "reef-sfm-provenance/intake_qc/v1"
    md = md_path.read_text()
    # Headline facts present
    assert "EasternDryRocks" in md
    assert "1,500" in md  # image count formatted with comma
    assert "## Dataset-level checks" in md
