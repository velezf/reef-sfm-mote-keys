#!/usr/bin/env python3
"""
test_focal_decision.py — unit tests for the focal-length decision criterion.

The decision logic in smoke_test._decide_focal is pure (dicts in, dict out) and
is the highest-stakes branch in Chat 5: it determines which focal configuration
a 24-48 h run commits to. Untested decision logic in a provenance-focused
portfolio is a credibility hole, so it is tested here against the criterion:
RMS primary, alignment tiebreak, NEEDS_REVIEW when the two signals genuinely
disagree.

smoke_test imports Metashape at module load, which isn't available off-instance,
so we inject a stub Metashape module before import. The decision function itself
touches no Metashape API.

Run:  python3 -m pytest scripts/metashape/test_focal_decision.py -v
  or: python3 scripts/metashape/test_focal_decision.py
"""
from __future__ import annotations

import sys
import types
import importlib.util
from pathlib import Path


def _load_smoke_with_stubbed_metashape():
    """Import smoke_test.py with a dummy Metashape module in place."""
    if "Metashape" not in sys.modules:
        sys.modules["Metashape"] = types.ModuleType("Metashape")
    spec = importlib.util.spec_from_file_location(
        "smoke_test_under_test",
        Path(__file__).with_name("smoke_test.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


smoke = _load_smoke_with_stubbed_metashape()
decide = smoke._decide_focal


def _arm(name, rms, aligned_pct):
    return {
        "arm": name,
        "reproj_rms_filter_units": rms,
        "aligned_pct": aligned_pct,
        "cameras_total": 100,
        "cameras_aligned": int(aligned_pct),
        "tie_points_after_reduction": 10000,
    }


# --- clear RMS winner ------------------------------------------------------- #

def test_fallback_wins_on_lower_rms():
    d = decide(_arm("fallback", 0.30, 95.0), _arm("manual", 0.45, 95.0))
    assert d["verdict"] == "DECIDED"
    assert d["chosen_arm"] == "fallback"


def test_manual_wins_on_lower_rms():
    d = decide(_arm("fallback", 0.50, 95.0), _arm("manual", 0.31, 95.0))
    assert d["verdict"] == "DECIDED"
    assert d["chosen_arm"] == "manual"


# --- RMS tie -> alignment tiebreak ----------------------------------------- #

def test_rms_tie_breaks_on_alignment():
    # RMS within 0.02 margin -> tie; manual aligns 5% more -> manual wins.
    d = decide(_arm("fallback", 0.300, 90.0), _arm("manual", 0.305, 95.0))
    assert d["verdict"] == "DECIDED"
    assert d["chosen_arm"] == "manual"


def test_full_tie_prefers_fallback():
    # Both within margins -> no-assumption default.
    d = decide(_arm("fallback", 0.300, 95.0), _arm("manual", 0.305, 95.5))
    assert d["verdict"] == "DECIDED"
    assert d["chosen_arm"] == "fallback"


# --- genuine disagreement -> NEEDS_REVIEW ----------------------------------- #

def test_disagreement_escalates():
    # manual has clearly lower RMS, but fallback aligns clearly more cameras.
    d = decide(_arm("fallback", 0.50, 98.0), _arm("manual", 0.30, 90.0))
    assert d["verdict"] == "NEEDS_REVIEW"
    assert d["chosen_arm"] == "NEEDS_REVIEW"


# --- degenerate: an arm failed to align ------------------------------------- #

def test_fallback_failed_alignment():
    d = decide(_arm("fallback", None, 0.0), _arm("manual", 0.35, 95.0))
    assert d["verdict"] == "DECIDED"
    assert d["chosen_arm"] == "manual"


def test_both_failed_alignment():
    d = decide(_arm("fallback", None, 0.0), _arm("manual", None, 0.0))
    assert d["verdict"] == "NEEDS_REVIEW"


if __name__ == "__main__":
    # Minimal runner so the file works without pytest installed.
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed.")
    sys.exit(0 if passed == len(tests) else 1)
