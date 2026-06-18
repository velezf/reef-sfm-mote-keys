"""Round-trip tests: pipeline esm.* wire format → schema parsing → QC criteria.

Fixtures mirror the exact dicts stage_gate and stage_markers write to chunk.meta.
These tests act as a contract: if the pipeline output format changes, these break
before any downstream code silently misbehaves.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reef_sfm_provenance.manifest.schema import (
    GateBlock,
    MarkersGateBlock,
    ProcessingManifest,
)
from reef_sfm_provenance.qc.validator import QCCriterion, QCReport, QCValidator

_FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# from_esm_gate — structural parse
# ---------------------------------------------------------------------------

def test_from_esm_gate_pass_overall():
    gate = ProcessingManifest.from_esm_gate(_load("esm_gate_pass.json"))
    assert gate.passed is True
    assert gate.core_failed == []
    assert gate.chunk_label == "T1_area_survey"


def test_from_esm_gate_fail_two_seven_overall():
    gate = ProcessingManifest.from_esm_gate(_load("esm_gate_fail_2_7.json"))
    assert gate.passed is False
    assert set(gate.core_failed) == {"2_total_tilt_deg", "7_orientation_plus_x"}


def test_from_esm_gate_pass_check_count():
    gate = ProcessingManifest.from_esm_gate(_load("esm_gate_pass.json"))
    assert len(gate.checks) == 8


def test_from_esm_gate_check1_threshold_from_max():
    gate = ProcessingManifest.from_esm_gate(_load("esm_gate_pass.json"))
    chk = next(c for c in gate.checks if c.check_id == "1_long_tilt_deg")
    assert chk.threshold == 0.5
    assert chk.passed is True
    assert chk.observed == pytest.approx(0.086)


def test_from_esm_gate_check3_threshold_from_min():
    gate = ProcessingManifest.from_esm_gate(_load("esm_gate_pass.json"))
    chk = next(c for c in gate.checks if c.check_id == "3_coverage_interp_off")
    assert chk.threshold == 0.95
    assert chk.passed is True


def test_from_esm_gate_check4_threshold_from_target():
    gate = ProcessingManifest.from_esm_gate(_load("esm_gate_pass.json"))
    chk = next(c for c in gate.checks if c.check_id == "4_long_extent_m")
    assert chk.threshold == 10.0
    assert chk.passed is True


def test_from_esm_gate_check5_threshold_none():
    """Check 5 carries no max/min/target key in the pipeline output — threshold=None.

    GATE_COREG_TOL_M = 1e-6 is baked into the pipeline but not written to the check
    dict, so the QCReport for this check has no captured threshold. Known provenance
    gap — documented here as a contract test.
    """
    gate = ProcessingManifest.from_esm_gate(_load("esm_gate_pass.json"))
    chk = next(c for c in gate.checks if c.check_id == "5_coreg_dx_dy_m")
    assert chk.threshold is None
    assert chk.passed is True
    assert chk.observed == [0.0, 0.0]


def test_from_esm_gate_check6_observed_evr_aspect():
    gate = ProcessingManifest.from_esm_gate(_load("esm_gate_pass.json"))
    chk = next(c for c in gate.checks if c.check_id == "6_footprint")
    assert chk.observed == {"evr": pytest.approx(0.991), "aspect": pytest.approx(11.2)}
    assert chk.threshold is None


def test_from_esm_gate_check7_bool_v():
    """Check 7 writes v=bool; observed should be that bool, not None."""
    gate = ProcessingManifest.from_esm_gate(_load("esm_gate_pass.json"))
    chk = next(c for c in gate.checks if c.check_id == "7_orientation_plus_x")
    assert chk.observed is True
    assert chk.passed is True


def test_from_esm_gate_check7_fail():
    gate = ProcessingManifest.from_esm_gate(_load("esm_gate_fail_2_7.json"))
    chk = next(c for c in gate.checks if c.check_id == "7_orientation_plus_x")
    assert chk.observed is False
    assert chk.passed is False


def test_from_esm_gate_check8_advisory_passed_none():
    gate = ProcessingManifest.from_esm_gate(_load("esm_gate_pass.json"))
    chk = next(c for c in gate.checks if c.check_id == "8_reference_dem_advisory")
    assert chk.advisory is True
    assert chk.passed is None
    assert chk.observed == {"available": False, "flag": None}


def test_from_esm_gate_empty_dict_returns_empty_gate_block():
    gate = ProcessingManifest.from_esm_gate({})
    assert isinstance(gate, GateBlock)
    assert gate.checks == []
    assert gate.passed is None


# ---------------------------------------------------------------------------
# from_esm_markers_validation — structural parse
# ---------------------------------------------------------------------------

def test_from_esm_markers_headless_pass_overall():
    mg = ProcessingManifest.from_esm_markers_validation(
        _load("esm_markers_headless_pass.json")
    )
    assert mg.overall_status == "headless-pass"
    assert mg.gate_a_parity is True
    assert mg.gate_b_passed is True
    assert mg.gate_c_passed is True
    assert mg.gate_d_passed is True


def test_from_esm_markers_headless_pass_quantitative_fields():
    mg = ProcessingManifest.from_esm_markers_validation(
        _load("esm_markers_headless_pass.json")
    )
    assert mg.gate_b_coherence_px == pytest.approx(2.0)
    assert mg.gate_c_ratio == pytest.approx(1.018)
    assert mg.gate_d_bars == 3


def test_from_esm_markers_escalated_b_and_d_fail():
    mg = ProcessingManifest.from_esm_markers_validation(
        _load("esm_markers_escalated.json")
    )
    assert mg.overall_status == "escalated"
    assert mg.gate_a_parity is True
    assert mg.gate_b_passed is False
    assert mg.gate_c_passed is True
    assert mg.gate_d_passed is False
    assert mg.gate_d_bars == 2


def test_from_esm_markers_c_abstained_ratio_none():
    """gate_c abstains (<2 bars) — ratio=None, ok=True, abstained=True.
    gate_c_passed must be None (not-evaluable): the check never ran.
    """
    mg = ProcessingManifest.from_esm_markers_validation(
        _load("esm_markers_c_abstained.json")
    )
    assert mg.gate_c_passed is None
    assert mg.gate_c_ratio is None
    assert mg.gate_d_passed is False
    assert mg.gate_d_bars == 1


def test_from_esm_markers_empty_dict():
    mg = ProcessingManifest.from_esm_markers_validation({})
    assert isinstance(mg, MarkersGateBlock)
    assert mg.overall_status is None
    assert mg.gate_a_parity is None


# ---------------------------------------------------------------------------
# validate_full round-trip with realistic pipeline data
# ---------------------------------------------------------------------------

def _make_manifest_with_gate(gate_fixture: str, markers_fixture: str) -> ProcessingManifest:
    m = ProcessingManifest()
    m.gate = ProcessingManifest.from_esm_gate(_load(gate_fixture))
    m.markers_gate = ProcessingManifest.from_esm_markers_validation(_load(markers_fixture))
    return m


def test_validate_full_pass_gate_all_criteria_present():
    manifest = _make_manifest_with_gate("esm_gate_pass.json", "esm_markers_headless_pass.json")
    report = QCValidator().validate_full(manifest)
    names = {c.name for c in report.criteria}
    # All 8 gate checks must appear
    assert "gate_1_long_tilt_deg" in names
    assert "gate_2_total_tilt_deg" in names
    assert "gate_8_reference_dem_advisory" in names
    # All 4 marker gates must appear
    assert "markers_gate_a_parity" in names
    assert "markers_gate_b_coherence" in names
    assert "markers_gate_c_consistency" in names
    assert "markers_gate_d_sufficiency" in names


def test_validate_full_pass_gate_categories():
    manifest = _make_manifest_with_gate("esm_gate_pass.json", "esm_markers_headless_pass.json")
    report = QCValidator().validate_full(manifest)
    pipeline_gate = [c for c in report.criteria if c.category == "pipeline_gate"]
    markers_gate = [c for c in report.criteria if c.category == "markers_gate"]
    assert len(pipeline_gate) == 8
    assert len(markers_gate) == 4


def test_validate_full_fail_2_7_gate_criteria_verdicts():
    """Checks 2 and 7 fail in the pipeline; the QCReport must reflect that."""
    manifest = _make_manifest_with_gate("esm_gate_fail_2_7.json", "esm_markers_headless_pass.json")
    report = QCValidator().validate_full(manifest)
    by_name = {c.name: c for c in report.criteria}
    assert by_name["gate_2_total_tilt_deg"].passed is False
    assert by_name["gate_7_orientation_plus_x"].passed is False
    # Advisory check must remain not-evaluable even in a failing run
    assert by_name["gate_8_reference_dem_advisory"].passed is None
    # The QCReport overall verdict must be False
    assert report.passed is False


def test_validate_full_advisory_does_not_affect_verdict():
    """Advisory check 8 must be None and must not cause overall pass→fail."""
    manifest = _make_manifest_with_gate("esm_gate_pass.json", "esm_markers_headless_pass.json")
    report = QCValidator().validate_full(manifest)
    by_name = {c.name: c for c in report.criteria}
    assert by_name["gate_8_reference_dem_advisory"].passed is None
    # All Toth criteria are not-evaluable (empty ProcessingManifest params/outcome),
    # all gate intrinsic checks pass, markers pass → overall should be True (not None).
    gate_intrinsic = [c for c in report.criteria
                      if c.category == "pipeline_gate" and not c.name.endswith("advisory")]
    assert all(c.passed is True for c in gate_intrinsic)


def test_validate_full_escalated_markers_fail():
    manifest = _make_manifest_with_gate("esm_gate_pass.json", "esm_markers_escalated.json")
    report = QCValidator().validate_full(manifest)
    by_name = {c.name: c for c in report.criteria}
    assert by_name["markers_gate_b_coherence"].passed is False
    assert by_name["markers_gate_d_sufficiency"].passed is False
    assert report.passed is False


def test_validate_full_gate_b_criterion_observed_is_ceiling():
    """Documents known gap: gate B observed = ceiling_px (the threshold), not the
    worst observed residual. The actual worst residual is not in esm.markers_validation.
    A consumer cannot distinguish 'barely passed (1.9 px)' from 'clean pass (0.3 px)'.
    """
    manifest = _make_manifest_with_gate("esm_gate_pass.json", "esm_markers_headless_pass.json")
    report = QCValidator().validate_full(manifest)
    by_name = {c.name: c for c in report.criteria}
    crit = by_name["markers_gate_b_coherence"]
    # observed == threshold — no per-run residual captured
    assert crit.observed == crit.threshold


def test_validate_full_gate_c_abstained_passed_none():
    """gate_c abstained (<2 bars) — pipeline sets ok=True but abstained=True.
    QCReport must show passed=None (not-evaluable) not True — the check never ran.
    """
    manifest = _make_manifest_with_gate("esm_gate_pass.json", "esm_markers_c_abstained.json")
    report = QCValidator().validate_full(manifest)
    by_name = {c.name: c for c in report.criteria}
    assert by_name["markers_gate_c_consistency"].passed is None
    assert by_name["markers_gate_c_consistency"].observed is None


def test_gate_criteria_sentinel_honours_gate_passed():
    """GateBlock(checks=[], passed=True) sentinel must use gate.passed, not hardcoded None."""
    manifest = ProcessingManifest()
    manifest.gate = GateBlock(checks=[], passed=True, core_failed=[])
    report = QCValidator().validate_full(manifest)
    sentinel = next(c for c in report.criteria if c.name == "pipeline_gate_overall")
    assert sentinel.passed is True  # not None


def test_validate_full_log_summary_covers_all_categories(caplog):
    """_log_summary must emit counts for pipeline_gate and markers_gate, not just
    conformance/outcome.
    """
    import logging
    manifest = _make_manifest_with_gate("esm_gate_fail_2_7.json", "esm_markers_headless_pass.json")
    with caplog.at_level(logging.INFO, logger="reef_sfm_provenance.qc.validator"):
        QCValidator().validate_full(manifest)
    summary_lines = [r.message for r in caplog.records if "verdict=" in r.message]
    assert len(summary_lines) == 1, "validate_full must emit exactly one summary log line"
    assert "pipeline_gate" in summary_lines[0]
    assert "markers_gate" in summary_lines[0]


# ---------------------------------------------------------------------------
# from_esm_report gap — gate blocks not populated
# ---------------------------------------------------------------------------

def test_from_esm_report_populates_gate_when_stage_gate_present():
    """from_esm_report now consumes stage_gate and stage_markers_validation when
    present in the summary dict (stage_report embeds both).
    """
    gate_data = _load("esm_gate_fail_2_7.json")
    markers_data = _load("esm_markers_headless_pass.json")
    report_dict = {
        "parameters": {"alignment_accuracy": "Highest"},
        "outcome": {"input_image_count": 272, "registered_image_count": 131},
        "stage_gate": gate_data,
        "stage_markers_validation": markers_data,
    }
    manifest = ProcessingManifest.from_esm_report(report_dict)
    assert manifest.gate.passed is False
    assert set(manifest.gate.core_failed) == {"2_total_tilt_deg", "7_orientation_plus_x"}
    assert manifest.markers_gate.overall_status == "headless-pass"
    assert manifest.markers_gate.gate_a_parity is True


def test_from_esm_report_gate_blocks_empty_without_stage_data():
    """Without stage_gate / stage_markers_validation, gate blocks default to empty."""
    report_dict = {
        "parameters": {"alignment_accuracy": "Highest"},
        "outcome": {"input_image_count": 272, "registered_image_count": 131},
    }
    manifest = ProcessingManifest.from_esm_report(report_dict)
    assert manifest.gate.checks == []
    assert manifest.gate.passed is None
    assert manifest.markers_gate.overall_status is None
