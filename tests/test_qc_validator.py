"""Tests for `reef_sfm_provenance.qc.validator` (+ the manifest schema it consumes).

All manifests here are synthetic — no real Metashape report is parsed and no
real data is read in this branch. The point is to lock in the QC contract:
which criteria exist, which Toth Table S2 numbers they bind to (ADR-0010 —
NOT the PIFSC SOP), the conformance-vs-outcome split, and graceful handling
of not-yet-populated Optional manifest fields.
"""

from __future__ import annotations

import json

import pytest

from reef_sfm_provenance.manifest.schema import (
    OutcomeBlock,
    ParametersBlock,
    ProcessingManifest,
    ProvenanceBlock,
)
from reef_sfm_provenance.qc.validator import QCReport, QCValidator

# ---------------------------------------------------------------------------
# Synthetic manifest fixtures
# ---------------------------------------------------------------------------


def make_manifest(*, parameters: dict | None = None, outcome: dict | None = None) -> ProcessingManifest:
    """Fully Toth-conformant, fully passing manifest; override per test."""
    params = dict(
        alignment_accuracy="High",
        key_point_limit=60000,
        tie_point_limit=0,
        generic_preselection=True,
        exclude_stationary_tie_points=True,
        recon_uncertainty_threshold=30.0,
        projection_accuracy_threshold=3.0,
        reprojection_error_threshold=0.3,
        scale_bar_count=4,
    )
    params.update(parameters or {})
    out = dict(
        input_image_count=2422,
        registered_image_count=2410,
        final_reprojection_rms_px=0.45,
        per_scalebar_errors_m=[0.0005, -0.0008, 0.0003],
        max_horizontal_accuracy_m=0.02,
    )
    out.update(outcome or {})
    return ProcessingManifest(
        manifest_id="EDR_T1_synthetic",
        parameters=ParametersBlock(**params),
        outcome=OutcomeBlock(**out),
    )


def criteria_by_name(report: QCReport) -> dict:
    return {c.name: c for c in report.criteria}


# ---------------------------------------------------------------------------
# Schema contract
# ---------------------------------------------------------------------------


def test_empty_manifest_constructs():
    # The schema is the contract; population is deferred to a later branch,
    # so every block must be constructible empty.
    m = ProcessingManifest()
    assert m.parameters.key_point_limit is None
    assert m.outcome.final_reprojection_rms_px is None
    assert m.provenance.ec2_instance_id is None


def test_provenance_block_holds_deferred_fields():
    prov = ProvenanceBlock(
        input_file_hashes={"IMG_0001.tif": "ab" * 32},
        ec2_instance_id="i-0123456789abcdef0",
        snapshot_ids=["snap-034d45019a4e39c43"],
        license_fingerprint="redacted-fp",
        software_versions={"metashape": "2.3.1.22446", "python": "3.12"},
    )
    m = ProcessingManifest(provenance=prov)
    assert m.provenance.software_versions["metashape"].startswith("2.3.1")


def test_manifest_json_round_trip():
    m = make_manifest()
    again = ProcessingManifest.model_validate_json(m.model_dump_json())
    assert again == m


# ---------------------------------------------------------------------------
# Fully passing manifest
# ---------------------------------------------------------------------------


def test_fully_passing_manifest():
    report = QCValidator(scalebar_max_m=0.002).validate(make_manifest())
    assert all(c.passed is True for c in report.criteria), [
        (c.name, c.passed) for c in report.criteria if c.passed is not True
    ]
    assert report.passed is True
    assert {c.category for c in report.criteria} == {"conformance", "outcome"}


def test_report_serializes_to_json():
    report = QCValidator(scalebar_max_m=0.002).validate(make_manifest())
    payload = json.loads(report.to_json())
    assert payload["manifest_id"] == "EDR_T1_synthetic"
    entry = payload["criteria"][0]
    assert set(entry) >= {"name", "category", "passed", "observed", "threshold", "source"}


# ---------------------------------------------------------------------------
# Outcome failures
# ---------------------------------------------------------------------------


def test_registration_below_90pct_fails():
    report = QCValidator().validate(
        make_manifest(outcome=dict(registered_image_count=2000))  # 2000/2422 ≈ 0.826
    )
    crit = criteria_by_name(report)["registration_ratio"]
    assert crit.category == "outcome"
    assert crit.passed is False
    assert crit.observed == pytest.approx(2000 / 2422)
    assert report.passed is False


def test_final_rms_above_max_fails():
    report = QCValidator().validate(
        make_manifest(outcome=dict(final_reprojection_rms_px=0.60))
    )
    crit = criteria_by_name(report)["final_reprojection_rms"]
    assert crit.category == "outcome"
    assert crit.passed is False
    assert crit.threshold == pytest.approx(0.52)


def test_rms_max_is_a_constructor_parameter():
    # 0.45 passes the Toth-derived default but fails a stricter 0.30 gate.
    report = QCValidator(final_rms_max_px=0.30).validate(make_manifest())
    assert criteria_by_name(report)["final_reprojection_rms"].passed is False


# ---------------------------------------------------------------------------
# Conformance failures — outcome must still be evaluated
# ---------------------------------------------------------------------------


def test_nonconformant_key_point_limit_fails_conformance_only():
    report = QCValidator().validate(
        make_manifest(parameters=dict(key_point_limit=40000))  # PIFSC value, not Toth
    )
    crits = criteria_by_name(report)
    assert crits["key_point_limit"].category == "conformance"
    assert crits["key_point_limit"].passed is False
    # Outcome checks still ran and still pass.
    assert crits["registration_ratio"].passed is True
    assert crits["final_reprojection_rms"].passed is True
    assert report.passed is False


def test_recon_uncertainty_is_conformance_range_not_outcome_gate():
    # 35 is Toth-conformant (20–40) even though it would fail PIFSC's <=15.
    report = QCValidator().validate(
        make_manifest(parameters=dict(recon_uncertainty_threshold=35.0))
    )
    crit = criteria_by_name(report)["reconstruction_uncertainty_threshold"]
    assert crit.category == "conformance"
    assert crit.passed is True
    # Outside the Toth window fails.
    report2 = QCValidator().validate(
        make_manifest(parameters=dict(recon_uncertainty_threshold=15.0))
    )
    assert criteria_by_name(report2)["reconstruction_uncertainty_threshold"].passed is False


def test_all_table_s2_conformance_criteria_present():
    report = QCValidator(scalebar_max_m=0.002).validate(make_manifest())
    conformance = {c.name for c in report.criteria if c.category == "conformance"}
    assert conformance == {
        "alignment_accuracy",
        "key_point_limit",
        "tie_point_limit",
        "generic_preselection",
        "reconstruction_uncertainty_threshold",
        "projection_accuracy_threshold",
        "reprojection_error_threshold",
    }


# ---------------------------------------------------------------------------
# Scale bars — threshold is a parameter, never a hardcoded 0.001 m
# ---------------------------------------------------------------------------


def test_scalebar_threshold_unset_means_not_evaluable():
    # Default validator: no calibrated threshold yet -> criterion present but
    # not evaluated, even though residuals exist in the manifest.
    report = QCValidator().validate(make_manifest())
    crit = criteria_by_name(report)["scale_bar_errors"]
    assert crit.passed is None
    assert crit.threshold is None


def test_scalebar_errors_checked_against_supplied_threshold():
    report = QCValidator(scalebar_max_m=0.0006).validate(make_manifest())
    crit = criteria_by_name(report)["scale_bar_errors"]
    assert crit.passed is False  # |−0.0008| > 0.0006
    assert crit.observed == pytest.approx(0.0008)


# ---------------------------------------------------------------------------
# Missing Optional fields — graceful, not crashing
# ---------------------------------------------------------------------------


def test_empty_manifest_validates_without_crash():
    report = QCValidator().validate(ProcessingManifest())
    assert all(c.passed is None for c in report.criteria)
    assert report.passed is None  # nothing evaluable -> no verdict, not a pass
    json.loads(report.to_json())  # still serializable


def test_partially_populated_manifest_mixes_evaluated_and_not():
    m = ProcessingManifest(
        parameters=ParametersBlock(key_point_limit=60000),
        outcome=OutcomeBlock(input_image_count=100, registered_image_count=95),
    )
    report = QCValidator().validate(m)
    crits = criteria_by_name(report)
    assert crits["key_point_limit"].passed is True
    assert crits["registration_ratio"].passed is True
    assert crits["alignment_accuracy"].passed is None
    assert crits["final_reprojection_rms"].passed is None


def test_registration_not_evaluable_when_input_count_missing():
    m = ProcessingManifest(outcome=OutcomeBlock(registered_image_count=95))
    crit = criteria_by_name(QCValidator().validate(m))["registration_ratio"]
    assert crit.passed is None
