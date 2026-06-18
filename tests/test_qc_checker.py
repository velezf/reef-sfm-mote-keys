"""Tests for qc/checker.py — run_qc over a RunManifest with fixture files.

Uses the StructuralQCReport / StructuralCriterion interface produced by
StructuralQCValidator (via the run_qc convenience wrapper).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from reef_sfm_provenance.models import ArtifactKind, RunManifest
from reef_sfm_provenance.qc.checker import run_qc

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> RunManifest:
    return RunManifest.model_validate_json((FIXTURES / name).read_text())


def criteria_by_name(report) -> dict:
    return {c.name: c for c in report.criteria}


# ---------------------------------------------------------------------------
# Fixture-based tests
# ---------------------------------------------------------------------------

def test_good_run_reprojection_passes():
    """0.35 px is inside the [0.3, 0.5] window."""
    report = run_qc(_load("synthetic_manifest_good.json"))
    by_name = criteria_by_name(report)
    assert by_name["reprojection_error"].passed is True


def test_good_run_scalebar_not_evaluable():
    """scalebar_error_m threshold is None (not calibrated) — always not-evaluable."""
    report = run_qc(_load("synthetic_manifest_good.json"))
    assert criteria_by_name(report)["scalebar_error"].passed is None


def test_good_run_registered_images_fails():
    """131/272 = 48% < 90% — the corpus-ceiling reality should FAIL, honestly."""
    report = run_qc(_load("synthetic_manifest_good.json"))
    assert criteria_by_name(report)["registered_images"].passed is False


def test_fail_run_reprojection_fails():
    """0.8 px > 0.5 px upper bound."""
    report = run_qc(_load("synthetic_manifest_fail.json"))
    assert criteria_by_name(report)["reprojection_error"].passed is False


def test_fail_run_scalebar_not_evaluable():
    """scalebar_error_m threshold is None (not calibrated) — not-evaluable regardless of observed."""
    report = run_qc(_load("synthetic_manifest_fail.json"))
    assert criteria_by_name(report)["scalebar_error"].passed is None


def test_fail_run_overall_fails():
    report = run_qc(_load("synthetic_manifest_fail.json"))
    assert report.passed is False


# ---------------------------------------------------------------------------
# Not-evaluable when fields absent
# ---------------------------------------------------------------------------

def test_bare_manifest_reprojection_not_evaluable():
    """No error_metrics at all → reprojection error is NOT_EVALUABLE, not FAIL."""
    m = RunManifest(run_id="bare", site="X")
    report = run_qc(m)
    by_name = criteria_by_name(report)
    assert by_name["reprojection_error"].passed is None


def test_bare_manifest_fails_on_missing_required_artifacts():
    """A manifest with no artifacts fails structural checks — absent required
    artifact is a FAIL, not not-evaluable. Quantitative checks are not-evaluable."""
    m = RunManifest(run_id="bare", site="X")
    report = run_qc(m)
    # Required artifacts absent → structural FAIL.
    assert report.passed is False
    # But purely quantitative checks are not-evaluable (no data to evaluate).
    by_name = criteria_by_name(report)
    assert by_name["reprojection_error"].passed is None


def test_not_evaluable_does_not_count_as_pass():
    m = RunManifest(run_id="bare", site="X")
    report = run_qc(m)
    # Some criteria must be not-evaluable (e.g. reprojection, scalebar).
    not_eval = [c for c in report.criteria if c.passed is None]
    assert len(not_eval) > 0


# ---------------------------------------------------------------------------
# Disk integrity check
# ---------------------------------------------------------------------------

def test_integrity_detects_missing_and_mismatch(tmp_path: Path):
    good = tmp_path / "products" / "dsm.tif"
    good.parent.mkdir(parents=True)
    good.write_bytes(b"hello")
    good_sha = hashlib.sha256(b"hello").hexdigest()
    mism = tmp_path / "products" / "ortho.tif"
    mism.write_bytes(b"world")  # wrong content

    m = RunManifest(
        run_id="r",
        site="X",
        artifacts=[
            {"kind": "digital_surface_model", "path": "products/dsm.tif", "sha256": good_sha},
            {"kind": "orthomosaic", "path": "products/ortho.tif", "sha256": "0" * 64},
            {"kind": "dense_point_cloud", "path": "products/dense.ply"},
        ],
    )
    report = run_qc(m, run_root=tmp_path)
    integ = next(c for c in report.criteria if c.name == "artifact_disk_integrity")
    assert integ.passed is False
