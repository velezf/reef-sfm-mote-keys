"""Tests for reef_sfm_provenance.intake (typed wrapper over existing intake stack)."""

from __future__ import annotations

from pathlib import Path

from reef_sfm_provenance.intake import IntakeReport, validate_intake


def test_validate_intake_empty_dir(tmp_path: Path):
    # Empty dir: "no images present" is a dataset-level fail — the stack is honest.
    report = validate_intake(tmp_path)
    assert isinstance(report, IntakeReport)
    assert report.image_count == 0
    assert report.overall_severity == "fail"  # no images -> dataset fail
    assert report.site_dir == str(tmp_path)


def test_validate_intake_returns_typed_model(tmp_path: Path):
    report = validate_intake(tmp_path)
    assert hasattr(report, "image_count")
    assert hasattr(report, "findings")
    assert hasattr(report, "overall_severity")


def test_intake_report_ok_property():
    r = IntakeReport(site_dir="/tmp", image_count=0, findings=[], overall_severity="ok")
    assert r.ok is True


def test_intake_report_fail_severity_not_ok():
    r = IntakeReport(site_dir="/tmp", image_count=1, findings=[], overall_severity="fail")
    assert r.ok is False


def test_intake_report_warning_is_ok():
    r = IntakeReport(site_dir="/tmp", image_count=1, findings=[], overall_severity="warning")
    assert r.ok is True


def test_intake_report_extra_fields_forbidden():
    import pytest
    with pytest.raises(Exception):
        IntakeReport(site_dir="/tmp", image_count=0, findings=[], overall_severity="ok",
                     mystery_field="boom")
