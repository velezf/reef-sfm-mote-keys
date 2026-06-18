"""Tests for reef_sfm_provenance.models (domain data types)."""

from __future__ import annotations

import pytest

from reef_sfm_provenance.models import (
    Artifact,
    ArtifactKind,
    InputDataset,
    Metric,
    PipelineStep,
    ProcessingEnvironment,
    ReconciliationReport,
    ReconciliationResult,
    ReproducibilityStatus,
    RunManifest,
    SoftwareVersion,
)


# ---------------------------------------------------------------------------
# SoftwareVersion
# ---------------------------------------------------------------------------

def test_software_version_minimal():
    sv = SoftwareVersion(name="Agisoft Metashape Professional")
    assert sv.version is None


def test_software_version_extra_fields_forbidden():
    with pytest.raises(Exception):
        SoftwareVersion(name="x", extra_field="boom")


# ---------------------------------------------------------------------------
# ProcessingEnvironment
# ---------------------------------------------------------------------------

def test_processing_environment_defaults():
    env = ProcessingEnvironment()
    assert env.instance_id is None
    assert env.snapshot_ids == []
    assert env.software == []


def test_processing_environment_with_software():
    env = ProcessingEnvironment(
        instance_id="i-0abc123",
        software=[SoftwareVersion(name="Metashape", version="2.3.1")],
    )
    assert env.software[0].version == "2.3.1"


# ---------------------------------------------------------------------------
# Artifact / ArtifactKind
# ---------------------------------------------------------------------------

def test_artifact_kind_values():
    assert ArtifactKind.DSM == "digital_surface_model"
    assert ArtifactKind.ORTHOMOSAIC == "orthomosaic"
    assert ArtifactKind.DENSE_CLOUD == "dense_point_cloud"


def test_artifact_minimal():
    art = Artifact(kind=ArtifactKind.DSM, path="products/dsm.tif")
    assert art.sha256 is None
    assert art.size_bytes is None


def test_artifact_extra_forbidden():
    with pytest.raises(Exception):
        Artifact(kind=ArtifactKind.DSM, path="p.tif", nope="x")


# ---------------------------------------------------------------------------
# Metric
# ---------------------------------------------------------------------------

def test_metric_source_default():
    m = Metric(name="rugosity", value=1.372)
    assert m.source == "ours"


def test_metric_with_implementation():
    m = Metric(name="vrm", value=0.065, implementation="python-sappington", window_m=0.05)
    assert m.window_m == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# RunManifest
# ---------------------------------------------------------------------------

def test_run_manifest_minimal():
    m = RunManifest(run_id="EDR_T1_R2_test", site="EasternDryRocks")
    assert m.transect is None
    assert m.artifacts == []
    assert m.metrics == []
    assert m.steps == []


def test_run_manifest_extra_forbidden():
    with pytest.raises(Exception):
        RunManifest(run_id="x", site="y", unknown_field=42)


def test_run_manifest_artifact_lookup():
    m = RunManifest(
        run_id="r",
        site="EDR",
        artifacts=[
            Artifact(kind=ArtifactKind.DSM, path="dsm.tif"),
            Artifact(kind=ArtifactKind.ORTHOMOSAIC, path="ortho.tif"),
        ],
    )
    assert m.artifact(ArtifactKind.DSM) is not None
    assert m.artifact(ArtifactKind.DSM).path == "dsm.tif"
    assert m.artifact(ArtifactKind.DENSE_CLOUD) is None


def test_run_manifest_json_round_trip():
    m = RunManifest(
        run_id="EDR_T1_R2",
        site="EasternDryRocks",
        transect="T1_R2",
        camera_alignment={"images_total": 272, "images_aligned": 131},
        error_metrics={"reprojection_error_px": 0.1397},
        artifacts=[Artifact(kind=ArtifactKind.DSM, path="products/dsm.tif", sha256="ab" * 32)],
        metrics=[Metric(name="rugosity", value=1.372, unit="dimensionless")],
    )
    again = RunManifest.model_validate_json(m.model_dump_json())
    assert again.run_id == m.run_id
    assert again.artifacts[0].sha256 == "ab" * 32
    assert again.metrics[0].value == pytest.approx(1.372)


# ---------------------------------------------------------------------------
# ReproducibilityStatus
# ---------------------------------------------------------------------------

def test_reproducibility_status_values():
    assert ReproducibilityStatus.REPRODUCED == "reproduced"
    assert ReproducibilityStatus.APPROXIMATELY_REPRODUCED == "approximately_reproduced"
    assert ReproducibilityStatus.NOT_REPRODUCIBLE == "not_reproducible"
    assert ReproducibilityStatus.NOT_ATTEMPTED == "not_attempted"


# ---------------------------------------------------------------------------
# ReconciliationReport
# ---------------------------------------------------------------------------

def test_reconciliation_report_firewall_note_present():
    r = ReconciliationReport(run_id="EDR_T1_R2")
    assert "comparison-only" in r.firewall_note
    assert "never inputs" in r.firewall_note


def test_reconciliation_result_defaults():
    r = ReconciliationResult(metric_name="rugosity")
    assert r.reproducibility is ReproducibilityStatus.NOT_ATTEMPTED
    assert r.published_value is None
    assert r.local_value is None


def test_reconciliation_report_json_round_trip():
    report = ReconciliationReport(
        run_id="EDR_T1_R2",
        results=[
            ReconciliationResult(
                metric_name="rugosity",
                local_value=1.372,
                published_value=1.415,
                difference=-0.043,
                percent_difference=-3.04,
                reproducibility=ReproducibilityStatus.REPRODUCED,
            )
        ],
    )
    again = ReconciliationReport.model_validate_json(report.model_dump_json())
    assert again.results[0].metric_name == "rugosity"
    assert again.results[0].percent_difference == pytest.approx(-3.04)
