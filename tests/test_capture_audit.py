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

def test_characterized_exempts_untethered_threshold():
    """A characterized check with threshold=None must NOT be flagged UNTETHERED_THRESHOLD.

    'Characterized' means the gap is documented and intentional (e.g. the topo
    transect total_tilt_deg that exceeds the flat-belt threshold — ADR-0031).
    """
    t = AuditTarget(
        id="2_total_tilt_deg",
        observed=8.71,
        threshold=None,
        passed=False,
        advisory=False,
        characterized=True,
        source=None,
        origin="gate_check",
    )
    assert t.characterized is True
    assert t.threshold is None

    liabilities = classify(t)            # NotImplementedError expected
    assert Liability.UNTETHERED_THRESHOLD not in liabilities
