"""Tests for reef_sfm_provenance.qc.structural (artifact presence + disk integrity).

Follows the same contract as test_qc_validator.py: three-state bool | None,
not-evaluable ≠ pass, all checks present, JSON serializable.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from reef_sfm_provenance.models import Artifact, ArtifactKind, Metric, RunManifest
from reef_sfm_provenance.qc import StructuralQCReport, StructuralQCValidator, run_qc
from reef_sfm_provenance.qc.structural import StructuralCriterion


def _make_manifest(**kwargs) -> RunManifest:
    return RunManifest(run_id="EDR_T1_R2_structural", site="EasternDryRocks", **kwargs)


def criteria_by_name(report: StructuralQCReport) -> dict[str, StructuralCriterion]:
    return {c.name: c for c in report.criteria}


# ---------------------------------------------------------------------------
# Artifact presence
# ---------------------------------------------------------------------------

def test_missing_dsm_fails():
    m = _make_manifest()  # no artifacts
    report = StructuralQCValidator().validate(m)
    c = criteria_by_name(report)
    assert c["artifact_digital_surface_model_present"].passed is False


def test_all_three_required_artifacts_present_passes():
    m = _make_manifest(
        artifacts=[
            Artifact(kind=ArtifactKind.DSM, path="dsm.tif"),
            Artifact(kind=ArtifactKind.ORTHOMOSAIC, path="ortho.tif"),
            Artifact(kind=ArtifactKind.DENSE_CLOUD, path="dense.ply"),
        ]
    )
    report = StructuralQCValidator().validate(m)
    c = criteria_by_name(report)
    assert c["artifact_digital_surface_model_present"].passed is True
    assert c["artifact_orthomosaic_present"].passed is True
    assert c["artifact_dense_point_cloud_present"].passed is True


def test_partial_artifacts_partial_pass():
    m = _make_manifest(
        artifacts=[Artifact(kind=ArtifactKind.DSM, path="dsm.tif")]
    )
    report = StructuralQCValidator().validate(m)
    c = criteria_by_name(report)
    assert c["artifact_digital_surface_model_present"].passed is True
    assert c["artifact_orthomosaic_present"].passed is False
    assert report.passed is False


# ---------------------------------------------------------------------------
# Disk integrity
# ---------------------------------------------------------------------------

def test_disk_integrity_not_evaluable_without_root():
    m = _make_manifest(artifacts=[Artifact(kind=ArtifactKind.DSM, path="dsm.tif")])
    report = StructuralQCValidator().validate(m, run_root=None)
    c = criteria_by_name(report)
    assert c["artifact_disk_integrity"].passed is None


def test_disk_integrity_not_evaluable_no_artifacts():
    m = _make_manifest()
    report = StructuralQCValidator().validate(m, run_root=Path("/tmp"))
    c = criteria_by_name(report)
    assert c["artifact_disk_integrity"].passed is None


def test_disk_integrity_ok_with_matching_hash(tmp_path: Path):
    content = b"fake DSM"
    sha = hashlib.sha256(content).hexdigest()
    (tmp_path / "dsm.tif").write_bytes(content)
    m = _make_manifest(artifacts=[Artifact(kind=ArtifactKind.DSM, path="dsm.tif", sha256=sha)])
    report = StructuralQCValidator().validate(m, run_root=tmp_path)
    c = criteria_by_name(report)
    assert c["artifact_disk_integrity"].passed is True


def test_disk_integrity_fails_on_missing_file(tmp_path: Path):
    m = _make_manifest(artifacts=[Artifact(kind=ArtifactKind.DSM, path="missing.tif")])
    report = StructuralQCValidator().validate(m, run_root=tmp_path)
    c = criteria_by_name(report)
    assert c["artifact_disk_integrity"].passed is False
    assert "missing" in c["artifact_disk_integrity"].observed


def test_disk_integrity_fails_on_hash_mismatch(tmp_path: Path):
    (tmp_path / "dsm.tif").write_bytes(b"real content")
    m = _make_manifest(
        artifacts=[Artifact(kind=ArtifactKind.DSM, path="dsm.tif", sha256="00" * 32)]
    )
    report = StructuralQCValidator().validate(m, run_root=tmp_path)
    c = criteria_by_name(report)
    assert c["artifact_disk_integrity"].passed is False
    assert "hash_mismatch" in c["artifact_disk_integrity"].observed


# ---------------------------------------------------------------------------
# Overall verdict
# ---------------------------------------------------------------------------

def test_empty_manifest_has_failures_for_missing_artifacts():
    m = _make_manifest()
    report = StructuralQCValidator().validate(m)
    assert report.passed is False  # all three artifact checks fail


def test_report_serializes_to_json():
    m = _make_manifest()
    report = StructuralQCValidator().validate(m)
    import json
    payload = json.loads(report.to_json())
    assert payload["run_id"] == "EDR_T1_R2_structural"
    assert isinstance(payload["criteria"], list)


# ---------------------------------------------------------------------------
# run_qc convenience wrapper
# ---------------------------------------------------------------------------

def test_run_qc_wrapper_returns_structural_report():
    m = _make_manifest()
    report = run_qc(m)
    assert isinstance(report, StructuralQCReport)
    assert report.run_id == "EDR_T1_R2_structural"


def test_run_qc_with_run_root(tmp_path: Path):
    content = b"dsm"
    sha = hashlib.sha256(content).hexdigest()
    (tmp_path / "dsm.tif").write_bytes(content)
    m = _make_manifest(artifacts=[Artifact(kind=ArtifactKind.DSM, path="dsm.tif", sha256=sha)])
    report = run_qc(m, run_root=tmp_path)
    c = criteria_by_name(report)
    assert c["artifact_disk_integrity"].passed is True


# ---------------------------------------------------------------------------
# Existing Toth validator still importable and functional
# ---------------------------------------------------------------------------

def test_toth_qc_validator_still_importable():
    from reef_sfm_provenance.qc import QCValidator, QCReport
    from reef_sfm_provenance.manifest.schema import ProcessingManifest
    report = QCValidator().validate(ProcessingManifest())
    assert isinstance(report, QCReport)
    # all criteria not-evaluable on empty manifest
    assert all(c.passed is None for c in report.criteria)
