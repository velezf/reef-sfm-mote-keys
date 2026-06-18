"""Tests for metashape_report.py — parse_report and from_esm_report."""

from __future__ import annotations

import pytest

from reef_sfm_provenance.metashape_report import from_esm_report, parse_report


def test_parse_report_nonexistent_returns_valid_manifest(tmp_path):
    m = parse_report(tmp_path / "no_such_file.html", run_id="test", site="EDR")
    assert m.run_id == "test"
    assert m.site == "EDR"
    assert m.model_dump_json()  # serializable


def test_parse_report_html_extracts_alignment(tmp_path):
    html = tmp_path / "report.html"
    html.write_text("<html>1234 images were aligned. Reprojection error: 0.31 pix</html>")
    m = parse_report(html, run_id="r1", site="S1")
    assert m.camera_alignment.get("images_aligned") == 1234
    assert m.error_metrics.get("reprojection_error_px") == pytest.approx(0.31)


def test_parse_report_html_extracts_metashape_version(tmp_path):
    html = tmp_path / "report.html"
    html.write_text("<html>Agisoft Metashape Professional 2.3.1</html>")
    m = parse_report(html, run_id="r1", site="S1")
    sw = {sv.name: sv.version for sv in m.environment.software}
    assert sw.get("Agisoft Metashape Professional") == "2.3.1"


def test_parse_report_sets_transect(tmp_path):
    html = tmp_path / "report.html"
    html.write_text("<html></html>")
    m = parse_report(html, run_id="r1", site="S1", transect="T1_R2")
    assert m.transect == "T1_R2"


_ESM_CLEAN = {
    "parameters": {"alignment_accuracy": "High"},
    "outcome": {
        "input_image_count": 272,
        "registered_image_count": 268,
        "final_reprojection_rms_px": 0.35,
        "per_scalebar_errors_m": [0.0002, -0.0003, 0.0001],
    },
}

_ESM_NO_OUTCOME = {"parameters": {"alignment_accuracy": "High"}}


def test_from_esm_report_populates_camera_alignment():
    m = from_esm_report(_ESM_CLEAN, run_id="r1", site="EDR")
    assert m.camera_alignment["images_total"] == 272
    assert m.camera_alignment["images_aligned"] == 268


def test_from_esm_report_populates_error_metrics():
    m = from_esm_report(_ESM_CLEAN, run_id="r1", site="EDR")
    assert m.error_metrics["reprojection_error_px"] == pytest.approx(0.35)
    assert m.error_metrics["scalebar_error_m"] == pytest.approx(0.0003)


def test_from_esm_report_no_outcome_gives_empty_dicts():
    m = from_esm_report(_ESM_NO_OUTCOME, run_id="r2", site="EDR")
    assert m.camera_alignment == {}
    assert m.error_metrics == {}


def test_from_esm_report_always_constructible():
    m = from_esm_report({}, run_id="bare", site="X")
    assert m.run_id == "bare"
    assert m.model_dump_json()  # serializable
