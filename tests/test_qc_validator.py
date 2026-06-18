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
        step4_images_analyzed=522,
        step4_images_disabled=7,        # ~1.3% — floor-cut level (ADR-0017 T3 q030)
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


# ---------------------------------------------------------------------------
# Frame retention — corpus-relative step4 disable rate (RED: criterion unimplemented)
#
# Threshold basis: ADR-0017 T3 A/B (scripts/metashape/probes/ab_quality_threshold.py)
#   q050 (Toth verbatim) disabled 242/522 = 46.4% → only 26.8% of corpus aligned
#   q030 (floor)         disabled   5/522 =  1.0% → 98.7% of corpus aligned
# The discard band 0.30–0.50 is fully usable (235/237 = 99.2% aligned).
# R2 at q050 disabled 140/272 = 51.5%; never tripped ALARM_MAX_DISABLED=200
# (absolute, tuned to T3's ~522 corpus, blind to corpus size).
#
# Proposed criterion: "frame_retention" (outcome)
#   observed  = 1 − (disabled / analyzed)   [retention rate, 0–1]
#   threshold = frame_retention_min          [constructor param, default 0.60]
#   pass      = observed >= threshold
#   not-eval  = step4_images_analyzed is None or step4_images_disabled is None
#
# Threshold rationale: 0.60 (= fail if >40% disabled) cleanly separates
#   bad  T3 q050 (53.6% retained) and R2 q050 (48.5% retained) from
#   good T3 q030 (99.0% retained) with wide margin for legitimate mid-range loss.
# ---------------------------------------------------------------------------


def test_frame_retention_r2_like_51pct_disabled_fails():
    """140/272 disabled (51.5% — R2 actual) fails the corpus-relative gate."""
    m = make_manifest(outcome=dict(step4_images_analyzed=272, step4_images_disabled=140))
    report = QCValidator().validate(m)
    crit = criteria_by_name(report)["frame_retention"]
    assert crit.category == "outcome"
    assert crit.passed is False
    assert crit.observed == pytest.approx(1 - 140 / 272)   # retention ≈ 0.485


def test_frame_retention_floor_cut_passes():
    """7/522 disabled (~1.3% — near ADR-0017 T3 0.30-floor result) passes."""
    m = make_manifest(outcome=dict(step4_images_analyzed=522, step4_images_disabled=7))
    report = QCValidator().validate(m)
    crit = criteria_by_name(report)["frame_retention"]
    assert crit.category == "outcome"
    assert crit.passed is True
    assert crit.observed == pytest.approx(1 - 7 / 522)     # retention ≈ 0.987


def test_frame_retention_no_step4_stats_not_evaluable():
    """Manifest with no step4 disable stats -> not-evaluable, never a pass."""
    report = QCValidator().validate(
        make_manifest(outcome=dict(step4_images_analyzed=None, step4_images_disabled=None))
    )
    crit = criteria_by_name(report)["frame_retention"]
    assert crit.passed is None
    assert report.passed is not False                       # overall not dragged to False


# ---------------------------------------------------------------------------
# ProcessingManifest.from_esm_report — loader from esm.report chunk meta
#
# esm.report is the dict written to chunk.meta["esm.report"] by stage_report
# after all exports complete. It carries the complete QC surface: parameters
# from PARAMS (frozen dataclass), outcome assembled from esm.step4 / esm.reduce /
# esm.scale / esm.filter / esm.dsm plus geometry-derived per-bar residuals.
#
# Two tests:
#   1. Clean run — all gates pass; verifies the loader maps every field correctly.
#   2. Degraded run — real R2 q050 values; verifies QC catches the bad run via
#      frame_retention AND registration_ratio (both False), not just one.
# ---------------------------------------------------------------------------

_CLEAN_RUN_REPORT = {
    "parameters": {
        "alignment_accuracy": "High",
        "key_point_limit": 60000,
        "tie_point_limit": 0,
        "generic_preselection": True,
        "exclude_stationary_tie_points": True,
        "recon_uncertainty_threshold": 30.0,
        "projection_accuracy_threshold": 3.0,
        "reprojection_error_threshold": 0.3,
        "scale_bar_count": 3,
    },
    "outcome": {
        "input_image_count": 272,
        "step4_images_analyzed": 272,
        "step4_images_disabled": 4,        # 98.5% retained — well above 0.60 floor
        "registered_image_count": 268,     # 268/272 = 98.5% — well above 90%
        "final_reprojection_rms_px": 0.35, # within Toth-derived max 0.52
        "per_scalebar_errors_m": [0.0002, -0.0003, 0.0001],  # max-abs 0.0003 < 0.001
        "dense_point_count": 47_000_000,
        "dsm_cells": 100_000,
        "dsm_resolution_m": 0.01,
    },
}

# Real R2 q050 values (ADR-0033 / ADR-0034):
#   140/272 disabled = 51.5% → frame_retention 0.485 < 0.60 → FAIL
#   131/272 registered overall = 48.2% < 0.90 → registration_ratio FAIL
#   reproj 0.1397 px → passes (< 0.52)
_R2_Q050_REPORT = {
    "parameters": {
        "alignment_accuracy": "High",
        "key_point_limit": 60000,
        "tie_point_limit": 0,
        "generic_preselection": True,
        "exclude_stationary_tie_points": True,
        "recon_uncertainty_threshold": 30.0,
        "projection_accuracy_threshold": 3.0,
        "reprojection_error_threshold": 0.3,
        "scale_bar_count": 3,
    },
    "outcome": {
        "input_image_count": 272,
        "step4_images_analyzed": 272,
        "step4_images_disabled": 140,
        "registered_image_count": 131,
        "final_reprojection_rms_px": 0.1397,
        "per_scalebar_errors_m": [0.0044, 0.0044, -0.0088],  # peak ±1.76% of 0.25 m bar
        "dense_point_count": 47_143_867,
        "dsm_cells": 100_000,
        "dsm_resolution_m": 0.01,
    },
}


def test_manifest_from_esm_report_populates_all_qc_fields():
    """Loader maps every esm.report field to manifest; clean run passes all gates."""
    m = ProcessingManifest.from_esm_report(_CLEAN_RUN_REPORT)

    # Parameters
    assert m.parameters.alignment_accuracy == "High"
    assert m.parameters.key_point_limit == 60000
    assert m.parameters.tie_point_limit == 0
    assert m.parameters.generic_preselection is True
    assert m.parameters.recon_uncertainty_threshold == pytest.approx(30.0)
    assert m.parameters.scale_bar_count == 3
    # Outcome
    assert m.outcome.input_image_count == 272
    assert m.outcome.step4_images_analyzed == 272
    assert m.outcome.step4_images_disabled == 4
    assert m.outcome.registered_image_count == 268
    assert m.outcome.final_reprojection_rms_px == pytest.approx(0.35)
    assert m.outcome.per_scalebar_errors_m == pytest.approx([0.0002, -0.0003, 0.0001])
    assert m.outcome.dense_point_count == 47_000_000
    assert m.outcome.dsm_cells == 100_000
    assert m.outcome.dsm_resolution_m == pytest.approx(0.01)
    # End-to-end QC: all gates pass
    qc = QCValidator(scalebar_max_m=0.001).validate(m)
    assert qc.passed is True, [(c.name, c.passed, c.observed) for c in qc.criteria if c.passed is not True]


def test_qc_flags_degraded_run():
    """Real R2 q050 values: QC catches the bad run via frame_retention + registration_ratio."""
    m = ProcessingManifest.from_esm_report(_R2_Q050_REPORT)
    qc = QCValidator().validate(m)
    crits = criteria_by_name(qc)

    assert qc.passed is False
    assert crits["frame_retention"].passed is False
    assert crits["frame_retention"].observed == pytest.approx(1 - 140 / 272)
    assert crits["registration_ratio"].passed is False
    assert crits["registration_ratio"].observed == pytest.approx(131 / 272)


# ---------------------------------------------------------------------------
# GateBlock + MarkersGateBlock — schema and classmethods
# ---------------------------------------------------------------------------

# Synthetic esm.gate dict matching stage_gate output (T1 shape: 2/7 fail).
_ESM_GATE_T1 = {
    "chunk": "T1",
    "checks": {
        "1_long_tilt_deg":      {"v": 0.37,  "max": 0.5,  "pass": True},
        "2_total_tilt_deg":     {"v": 8.71,  "max": 6.0,  "pass": False},
        "3_coverage_interp_off":{"v": 0.971, "min": 0.95, "pass": True},
        "4_long_extent_m":      {"v": 9.98,  "target": 10.0, "pass": True},
        "5_coreg_dx_dy_m":      {"v": [0.0, 0.0], "pass": True},
        "6_footprint":          {"evr": 0.974, "aspect": 7.2, "pass": True},
        "7_orientation_plus_x": {"v": False, "pass": False},
        "8_reference_dem_advisory": {
            "available": False, "advisory": True,
            "flag": None, "note": "comparison-only",
        },
    },
    "core_failed": ["2_total_tilt_deg", "7_orientation_plus_x"],
    "PASS": False,
    "reference_firewall": "comparison-only",
}

# Synthetic esm.gate dict for a clean run (all 7 core checks pass).
_ESM_GATE_CLEAN = {
    "chunk": "T3",
    "checks": {
        "1_long_tilt_deg":      {"v": 0.10,  "max": 0.5,  "pass": True},
        "2_total_tilt_deg":     {"v": 1.88,  "max": 6.0,  "pass": True},
        "3_coverage_interp_off":{"v": 0.997, "min": 0.95, "pass": True},
        "4_long_extent_m":      {"v": 10.01, "target": 10.0, "pass": True},
        "5_coreg_dx_dy_m":      {"v": [0.0, 0.0], "pass": True},
        "6_footprint":          {"evr": 0.98, "aspect": 8.5, "pass": True},
        "7_orientation_plus_x": {"v": True,  "pass": True},
        "8_reference_dem_advisory": {
            "available": False, "advisory": True, "flag": None,
        },
    },
    "core_failed": [],
    "PASS": True,
}

# Synthetic esm.markers_validation for a headless-pass run.
_ESM_MARKERS_PASS = {
    "status": "headless-pass",
    "gates": {
        "a_parity":    {"gate": "a_parity",    "ok": True,  "n_markers": 8, "odd_count": 0, "orphans": [], "proposed_pairs": [[15, 16], [19, 20], [25, 26], [27, 28]]},
        "b_coherence": {"gate": "b_coherence", "ok": True,  "ceiling_px": 2.0, "flagged": [], "flagged_ids": [], "load_bearing_flagged": []},
        "c_consistency":{"gate": "c_consistency","ok": True, "ratio": 1.034, "max_ratio": 1.25, "lengths": [1.533, 1.585, 1.564, 1.540]},
        "d_sufficiency":{"gate": "d_sufficiency","ok": True, "n_validated_bars": 4, "min_validated_bars": 3},
    },
    "thresholds": {"resid_ceiling_px": 2.0, "interbar_ratio_max": 1.25, "min_validated_bars": 3},
}

# Synthetic esm.markers_validation for a failed run (gate a + d fail).
_ESM_MARKERS_FAIL = {
    "status": "escalated",
    "failed_gates": ["a_parity", "d_sufficiency"],
    "gates": {
        "a_parity":    {"gate": "a_parity",    "ok": False, "n_markers": 3, "odd_count": 1, "orphans": [27], "proposed_pairs": [[15, 16]]},
        "b_coherence": {"gate": "b_coherence", "ok": True,  "ceiling_px": 2.0, "flagged": [], "flagged_ids": [], "load_bearing_flagged": []},
        "c_consistency":{"gate": "c_consistency","ok": True, "ratio": None, "max_ratio": 1.25, "lengths": [1.533]},
        "d_sufficiency":{"gate": "d_sufficiency","ok": False, "n_validated_bars": 1, "min_validated_bars": 3},
    },
    "thresholds": {"resid_ceiling_px": 2.0, "interbar_ratio_max": 1.25, "min_validated_bars": 3},
}


def test_gate_block_from_esm_gate_t1():
    """GateBlock correctly parses the T1 esm.gate dict (2/7 core fail)."""
    gate = ProcessingManifest.from_esm_gate(_ESM_GATE_T1)
    assert gate.chunk_label == "T1"
    assert gate.passed is False
    assert gate.core_failed == ["2_total_tilt_deg", "7_orientation_plus_x"]
    assert len(gate.checks) == 8
    by_id = {c.check_id: c for c in gate.checks}
    assert by_id["1_long_tilt_deg"].passed is True
    assert by_id["2_total_tilt_deg"].passed is False
    assert by_id["8_reference_dem_advisory"].advisory is True
    assert by_id["8_reference_dem_advisory"].passed is None


def test_gate_block_clean_run_passes():
    gate = ProcessingManifest.from_esm_gate(_ESM_GATE_CLEAN)
    assert gate.passed is True
    assert gate.core_failed == []
    by_id = {c.check_id: c for c in gate.checks}
    for check_id in ("1_long_tilt_deg", "2_total_tilt_deg", "3_coverage_interp_off",
                     "4_long_extent_m", "5_coreg_dx_dy_m", "6_footprint", "7_orientation_plus_x"):
        assert by_id[check_id].passed is True, f"{check_id} should pass"


def test_gate_block_empty_dict():
    gate = ProcessingManifest.from_esm_gate({})
    assert gate.passed is None
    assert gate.checks == []


def test_markers_gate_block_from_esm_pass():
    mg = ProcessingManifest.from_esm_markers_validation(_ESM_MARKERS_PASS)
    assert mg.overall_status == "headless-pass"
    assert mg.gate_a_parity is True
    assert mg.gate_b_passed is True
    assert mg.gate_b_coherence_px == pytest.approx(2.0)
    assert mg.gate_c_ratio == pytest.approx(1.034)
    assert mg.gate_c_passed is True
    assert mg.gate_d_bars == 4
    assert mg.gate_d_passed is True


def test_markers_gate_block_from_esm_fail():
    mg = ProcessingManifest.from_esm_markers_validation(_ESM_MARKERS_FAIL)
    assert mg.overall_status == "escalated"
    assert mg.gate_a_parity is False
    assert mg.gate_d_bars == 1
    assert mg.gate_d_passed is False


def test_markers_gate_block_empty():
    mg = ProcessingManifest.from_esm_markers_validation({})
    assert mg.overall_status is None
    assert mg.gate_a_parity is None


# ---------------------------------------------------------------------------
# validate_full — pipeline gate + markers gate + Toth Table S2 in one report
# ---------------------------------------------------------------------------

def test_validate_full_includes_all_three_category_types():
    """validate_full emits conformance + outcome + pipeline_gate + markers_gate criteria."""
    m = make_manifest()
    m.gate = ProcessingManifest.from_esm_gate(_ESM_GATE_CLEAN)
    m.markers_gate = ProcessingManifest.from_esm_markers_validation(_ESM_MARKERS_PASS)
    report = QCValidator(scalebar_max_m=0.002).validate_full(m)
    categories = {c.category for c in report.criteria}
    assert "conformance" in categories
    assert "outcome" in categories
    assert "pipeline_gate" in categories
    assert "markers_gate" in categories


def test_validate_full_clean_run_passes():
    """A fully passing manifest with clean gate/markers data yields passed=True."""
    m = make_manifest()
    m.gate = ProcessingManifest.from_esm_gate(_ESM_GATE_CLEAN)
    m.markers_gate = ProcessingManifest.from_esm_markers_validation(_ESM_MARKERS_PASS)
    report = QCValidator(scalebar_max_m=0.002).validate_full(m)
    crits = criteria_by_name(report)
    assert crits["gate_2_total_tilt_deg"].passed is True
    assert crits["markers_gate_a_parity"].passed is True
    assert crits["markers_gate_d_sufficiency"].passed is True
    assert report.passed is True


def test_validate_full_t1_gate_failures_propagate():
    """T1 gate (2/7 fail) makes the overall report fail even if Toth checks pass."""
    m = make_manifest()
    m.gate = ProcessingManifest.from_esm_gate(_ESM_GATE_T1)
    m.markers_gate = ProcessingManifest.from_esm_markers_validation(_ESM_MARKERS_PASS)
    report = QCValidator(scalebar_max_m=0.002).validate_full(m)
    crits = criteria_by_name(report)
    assert crits["gate_2_total_tilt_deg"].passed is False
    assert crits["gate_7_orientation_plus_x"].passed is False
    assert report.passed is False


def test_validate_full_advisory_gate_8_never_causes_failure():
    """Advisory check 8 has passed=None and does NOT contribute to report failure."""
    m = make_manifest()
    m.gate = ProcessingManifest.from_esm_gate(_ESM_GATE_T1)
    report = QCValidator().validate_full(m)
    crits = criteria_by_name(report)
    # Advisory check must be not-evaluable (None), not False.
    assert crits["gate_8_reference_dem_advisory"].passed is None


def test_validate_full_markers_fail_propagates():
    m = make_manifest()
    m.gate = ProcessingManifest.from_esm_gate(_ESM_GATE_CLEAN)
    m.markers_gate = ProcessingManifest.from_esm_markers_validation(_ESM_MARKERS_FAIL)
    report = QCValidator().validate_full(m)
    crits = criteria_by_name(report)
    assert crits["markers_gate_a_parity"].passed is False
    assert crits["markers_gate_d_sufficiency"].passed is False
    assert report.passed is False


def test_validate_full_empty_gate_blocks_not_evaluable():
    """Empty gate/markers gate blocks yield not-evaluable sentinels, not failures."""
    m = make_manifest()
    # gate and markers_gate fields are default-empty
    report = QCValidator().validate_full(m)
    crits = criteria_by_name(report)
    assert crits["pipeline_gate_overall"].passed is None
    assert crits["markers_gate_overall"].passed is None
    # Toth Table S2 checks are not affected (still evaluable from make_manifest params).
    assert crits["alignment_accuracy"].passed is True


def test_manifest_gate_fields_serialize_round_trip():
    """GateBlock and MarkersGateBlock survive JSON round-trip."""
    m = make_manifest()
    m.gate = ProcessingManifest.from_esm_gate(_ESM_GATE_T1)
    m.markers_gate = ProcessingManifest.from_esm_markers_validation(_ESM_MARKERS_PASS)
    again = ProcessingManifest.model_validate_json(m.model_dump_json())
    assert again.gate.passed == m.gate.passed
    assert again.gate.core_failed == m.gate.core_failed
    assert again.markers_gate.overall_status == "headless-pass"
    assert again.markers_gate.gate_d_bars == 4
