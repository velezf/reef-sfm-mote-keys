"""Tests for reports.py — render_markdown and write_report."""

from __future__ import annotations

from pathlib import Path

from reef_sfm_provenance.models import (
    ArtifactKind,
    ReconciliationReport,
    ReconciliationResult,
    RunManifest,
)
from reef_sfm_provenance.qc.validator import QCCriterion, QCReport
from reef_sfm_provenance.reports import render_markdown, write_report


def _simple_manifest() -> RunManifest:
    return RunManifest(run_id="EDR_T1_test", site="EasternDryRocks", transect="T1")


def test_render_markdown_contains_run_id():
    text = render_markdown(_simple_manifest())
    assert "EDR_T1_test" in text


def test_render_markdown_contains_site():
    text = render_markdown(_simple_manifest())
    assert "EasternDryRocks" in text


def test_render_markdown_no_qc_no_section(tmp_path):
    text = render_markdown(_simple_manifest(), qc=None)
    assert "QC Results" not in text


def test_render_markdown_qc_section_appears():
    qc = QCReport(
        manifest_id="EDR_T1_test",
        criteria=[
            QCCriterion(
                name="reprojection_error",
                category="conformance",
                passed=True,
                observed=0.35,
                threshold=0.3,
                source="Toth et al. 2025 ESM Table S2",
            )
        ],
    )
    text = render_markdown(_simple_manifest(), qc=qc)
    assert "QC Results" in text
    assert "reprojection_error" in text
    assert "pass" in text


def test_render_markdown_reconciliation_section():
    rec = ReconciliationReport(
        run_id="EDR_T1_test",
        results=[
            ReconciliationResult(
                metric_name="rugosity",
                local_value=1.372,
                published_value=1.415,
                difference=-0.043,
                percent_difference=-3.04,
            )
        ],
    )
    text = render_markdown(_simple_manifest(), reconciliation=rec)
    assert "Metric Reconciliation" in text
    assert "rugosity" in text


def test_write_report_creates_file(tmp_path):
    text = render_markdown(_simple_manifest())
    path = write_report(text, tmp_path)
    assert path.name == "report.md"
    assert path.exists()
    assert "EDR_T1_test" in path.read_text()


def test_write_report_to_explicit_file(tmp_path):
    text = "# test"
    path = write_report(text, tmp_path / "custom_report.md")
    assert path.name == "custom_report.md"
    assert path.read_text() == "# test"
