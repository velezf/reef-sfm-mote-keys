"""Phase 1 (RED): captured-threshold audit stubs.

All tests that call classify() must fail with NotImplementedError.

NOTE — fixture values vs. prompt spec:
The provenance gap fix commit (0c65e2b) updated esm_gate_pass.json and
esm_gate_fail_2_7.json to add "tol"/evr_min/aspect_min threshold keys, and
esm_markers_headless_pass.json to add worst_resid_px.  Those fixtures now
produce AuditTargets with threshold ≠ None (check 5, check 6) and
observed ≠ threshold (gate B).  Using the fixture parse path for the three
liability cases would RED for assertion errors, not for NotImplementedError.

Resolution: the three liability cases use hand-built AuditTargets representing
the pre-fix values that motivated each liability.  The RETIRED case and the
from_gate_check / from_qc_criterion converter tests use the real fixture path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reef_sfm_provenance.capture_audit import (
    AuditTarget,
    CaptureAuditReport,
    GateAuditResult,
    Liability,
    audit_run,
    classify,
    from_gate_check,
    from_qc_criterion,
)
from reef_sfm_provenance.manifest.schema import ProcessingManifest
from reef_sfm_provenance.qc.validator import QCValidator

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# UNTETHERED_THRESHOLD — check 5 (pre-fix: threshold=None)
# Using hand-built target because the fixture was updated to add "tol": 1e-6.
# ---------------------------------------------------------------------------

def test_check5_untethered_threshold():
    """5_coreg_dx_dy_m with threshold=None (pre-fix state) must flag UNTETHERED_THRESHOLD.

    Guard: these are the values the pipeline wrote before the gap fix.
    """
    t = AuditTarget(
        id="5_coreg_dx_dy_m",
        observed=[0.0, 0.0],
        threshold=None,
        passed=True,
        advisory=False,
        characterized=False,
        source=None,
        origin="gate_check",
    )
    assert t.observed == [0.0, 0.0]
    assert t.threshold is None

    liabilities = classify(t)            # NotImplementedError expected
    assert Liability.UNTETHERED_THRESHOLD in liabilities
    assert Liability.SELF_CONFIRMING not in liabilities


# ---------------------------------------------------------------------------
# UNTETHERED_THRESHOLD — check 6 (pre-fix: threshold=None)
# Using hand-built target because the fixture was updated to add evr_min/aspect_min.
# ---------------------------------------------------------------------------

def test_check6_untethered_threshold():
    """6_footprint with threshold=None (pre-fix state) must flag UNTETHERED_THRESHOLD.

    Guard: these are the values the pipeline wrote before the gap fix.
    """
    t = AuditTarget(
        id="6_footprint",
        observed={"evr": 0.991, "aspect": 11.2},
        threshold=None,
        passed=True,
        advisory=False,
        characterized=False,
        source=None,
        origin="gate_check",
    )
    assert t.observed == {"evr": 0.991, "aspect": 11.2}
    assert t.threshold is None

    liabilities = classify(t)            # NotImplementedError expected
    assert Liability.UNTETHERED_THRESHOLD in liabilities


# ---------------------------------------------------------------------------
# SELF_CONFIRMING — gate B (pre-fix: observed == ceiling_px == threshold)
# Using hand-built QC criterion target because the fixture was updated to
# add worst_resid_px; the criterion now has observed=0.35 != threshold=2.0.
# ---------------------------------------------------------------------------

def test_gate_b_self_confirming():
    """markers_gate_b_coherence with observed==threshold (pre-fix tautology)
    must flag SELF_CONFIRMING.

    Guard: these are the values the QCReport held before worst_resid_px was wired.
    """
    t = AuditTarget(
        id="markers_gate_b_coherence",
        observed=2.0,
        threshold=2.0,
        passed=True,
        advisory=False,
        characterized=False,
        source="stage_markers (ADR-0022)",
        origin="qc_criterion",
    )
    assert t.observed == 2.0
    assert t.threshold == 2.0
    assert t.observed == t.threshold     # the tautology

    liabilities = classify(t)            # NotImplementedError expected
    assert Liability.SELF_CONFIRMING in liabilities


# ---------------------------------------------------------------------------
# RETIRED — check 1 from real fixture (non-None threshold, observed != threshold)
# Uses the existing fixture parse path; 1_long_tilt_deg has not changed.
# ---------------------------------------------------------------------------

def test_check1_retired_via_fixture():
    """1_long_tilt_deg from esm_gate_pass.json: well-formed, no liabilities expected.

    Loads through the real parse path to document actual field values.
    """
    gate = ProcessingManifest.from_esm_gate(_load("esm_gate_pass.json"))
    gc = next(c for c in gate.checks if c.check_id == "1_long_tilt_deg")

    # Guard — document the real values flowing through from_gate_check.
    assert gc.observed == pytest.approx(0.086)
    assert gc.threshold == pytest.approx(0.5)
    assert gc.passed is True
    assert gc.advisory is False

    t = from_gate_check(gc)
    assert t.id == "1_long_tilt_deg"
    assert t.origin == "gate_check"
    assert t.threshold == pytest.approx(0.5)
    assert t.observed == pytest.approx(0.086)
    assert t.observed != t.threshold     # not self-confirming

    liabilities = classify(t)            # NotImplementedError expected
    assert liabilities == []


# ---------------------------------------------------------------------------
# Advisory exemption — threshold=None but advisory=True → NOT UNTETHERED
# Hand-built target; pure classifier unit test (prompt: "OK here").
# ---------------------------------------------------------------------------

def test_advisory_exempts_untethered_threshold():
    """An advisory check with threshold=None must NOT be flagged UNTETHERED_THRESHOLD.

    The advisory flag signals the check is informational; thresholds may be
    deliberately absent (e.g. check 8 reference-roughness).
    """
    t = AuditTarget(
        id="8_reference_dem_advisory",
        observed={"available": False, "flag": None},
        threshold=None,
        passed=None,
        advisory=True,
        characterized=False,
        source=None,
        origin="gate_check",
    )
    assert t.advisory is True
    assert t.threshold is None

    liabilities = classify(t)            # NotImplementedError expected
    assert Liability.UNTETHERED_THRESHOLD not in liabilities


# ---------------------------------------------------------------------------
# Characterized exemption — threshold=None but characterized=True → NOT UNTETHERED
# Hand-built target; pure classifier unit test (prompt: "OK here").
# ---------------------------------------------------------------------------

def test_characterized_bare_flag_not_exempt():
    """characterized=True with note=None is a bare flag — NOT a valid exemption.

    A bare flag provides no rationale; UNTETHERED_THRESHOLD must still fire.
    This replaces the prior 'bare characterized exempts' test, which was too
    permissive.
    """
    t = AuditTarget(
        id="2_total_tilt_deg",
        observed=8.71,
        threshold=None,
        passed=False,
        advisory=False,
        characterized=True,
        note=None,
        source=None,
        origin="gate_check",
    )
    assert t.characterized is True
    assert t.note is None
    assert t.threshold is None

    liabilities = classify(t)
    assert Liability.UNTETHERED_THRESHOLD in liabilities     # bare flag = no exemption


def test_characterized_with_note_exempts_untethered_threshold():
    """characterized=True WITH a non-empty note is an honest characterization.

    The note captures the rationale; UNTETHERED_THRESHOLD must NOT fire.
    """
    t = AuditTarget(
        id="2_total_tilt_deg",
        observed=8.71,
        threshold=None,
        passed=False,
        advisory=False,
        characterized=True,
        note="reef-wall cross-axis slope documented in ADR-0031; "
             "6.0° threshold sized for flat-belt, not topo transects",
        source=None,
        origin="gate_check",
    )
    assert t.characterized is True
    assert t.note is not None

    liabilities = classify(t)
    assert Liability.UNTETHERED_THRESHOLD not in liabilities  # honest characterization


# ===========================================================================
# Phase 3 — CaptureAuditReport aggregation (audit_run)
# ===========================================================================

def _gate_only_manifest(fixture_name: str, fixtures_root: Path = FIXTURES) -> ProcessingManifest:
    """Build a ProcessingManifest with only a GateBlock populated."""
    raw = json.loads((fixtures_root / fixture_name).read_text())
    manifest = ProcessingManifest()
    manifest.gate = ProcessingManifest.from_esm_gate(raw)
    return manifest


# ---------------------------------------------------------------------------
# a) Live regression guard — post-fix shared fixture (esm_gate_pass.json)
#
# FINDING: check 7 (7_orientation_plus_x) has threshold=None in both pre- and
# post-fix fixtures.  Boolean gates carry no configurable threshold and no
# "characterized" flag — classify() fires UNTETHERED_THRESHOLD.  The 0c65e2b
# fix addressed checks 5 and 6 only; check 7 is the remaining gap.
#
# This test therefore asserts:
#   - checks 5 and 6 are RETIRED (the 0c65e2b fixes hold)
#   - check 7 is UNTETHERED_THRESHOLD (the remaining gap)
#   - overall_conformant is False (truthful: at least one gap remains)
# ---------------------------------------------------------------------------

def test_audit_run_post_fix_checks5_and_6_are_retired():
    """Regression guard: 0c65e2b fixes hold — checks 5/6 are RETIRED post-fix.

    Loads esm_gate_pass.json through the real parse path. check 7 is still
    UNTETHERED_THRESHOLD (boolean gate, no threshold key). overall_conformant
    is False while check 7 is unresolved.
    """
    manifest = _gate_only_manifest("esm_gate_pass.json")
    qc_report = QCValidator().validate_full(manifest)
    report = audit_run(manifest, qc_report)

    by_id = {r.target.id: r for r in report.results}

    # Guard — verify the parse path populates what we expect.
    assert by_id["5_coreg_dx_dy_m"].target.threshold == pytest.approx(1e-6)
    assert by_id["6_footprint"].target.threshold == {"evr_min": pytest.approx(0.95),
                                                     "aspect_min": pytest.approx(5.0)}
    assert by_id["7_orientation_plus_x"].target.threshold is None

    # Regression: checks 5 and 6 fixed by 0c65e2b.
    assert by_id["5_coreg_dx_dy_m"].status is Liability.RETIRED
    assert by_id["6_footprint"].status is Liability.RETIRED

    # Remaining gap: check 7 boolean gate has no threshold key.
    assert Liability.UNTETHERED_THRESHOLD in by_id["7_orientation_plus_x"].liabilities

    # Truthful overall verdict while check 7 is unresolved.
    assert report.overall_conformant is False


# ---------------------------------------------------------------------------
# b) Pre-fix evidence — frozen pre-0c65e2b fixture through real parse path
#    Proves audit_run detects the historical gaps (checks 5 and 6) when
#    reading old-format pipeline output.
# ---------------------------------------------------------------------------

def test_audit_run_pre_fix_gate_flags_checks5_and_6_untethered():
    """Pre-0c65e2b fixture: checks 5 and 6 must be UNTETHERED_THRESHOLD.

    The frozen fixture lacks 'tol'/'evr_min'/'aspect_min' keys — current
    schema.py parses them with threshold=None, triggering UNTETHERED_THRESHOLD.
    """
    CAPTURE_FIXTURES = FIXTURES / "capture_audit"
    manifest = _gate_only_manifest("esm_gate_pass_pre_0c65e2b.json",
                                   fixtures_root=CAPTURE_FIXTURES)
    qc_report = QCValidator().validate_full(manifest)
    report = audit_run(manifest, qc_report)

    by_id = {r.target.id: r for r in report.results}

    # Guard — verify threshold=None for both checks in pre-fix parse.
    assert by_id["5_coreg_dx_dy_m"].target.threshold is None
    assert by_id["6_footprint"].target.threshold is None

    # Both must be flagged.
    assert Liability.UNTETHERED_THRESHOLD in by_id["5_coreg_dx_dy_m"].liabilities
    assert Liability.UNTETHERED_THRESHOLD in by_id["6_footprint"].liabilities

    assert report.overall_conformant is False
