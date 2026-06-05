#!/usr/bin/env python3
"""
test_marker_validation.py — unit tests for the headless marker-layer validation
gates (ADR-0022) that stage_markers uses to decide whether an auto-detected
coded-target layer is good enough to scale headless.

The three gates and the aggregator (validate_markers) are PURE — they take plain
per-marker records (the dicts _extract_marker_records builds from a chunk) and
return a structured verdict, touching no Metashape API. That is deliberate: it is
the highest-stakes branch in this chat (it decides whether a 24-48 h run scales on
a trustworthy layer), so it is unit-tested off-instance against synthetic fixtures
the same way smoke_test._decide_focal is.

run_pipeline imports Metashape at module load and builds two enum-keyed dicts
(_DEPTH/_BLEND) at import time, so we inject a stub Metashape exposing just those
names before importing it. The functions under test never touch Metashape.

Fixtures are calibrated to the real probe findings (session-log 2026-06-05):
  * T3 (known-good): 8 markers, 4 bars, resid <=0.38 px, inter-bar ratio 1.091 -> PASS
  * T1 (incoherent): ids {13,15,16,19,20,24,26} -> orphans {13,24,26}, odd 7 -> FAIL(a)

Run:  python3 -m pytest scripts/metashape/test_marker_validation.py -v
  or: python3 scripts/metashape/test_marker_validation.py
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def _load_run_pipeline_with_stubbed_metashape():
    """Import run_pipeline.py with a dummy Metashape module in place. The stub
    only needs the enum names referenced at module load (_DEPTH/_BLEND)."""
    if "Metashape" not in sys.modules:
        ms = types.ModuleType("Metashape")
        for name in ("MildFiltering", "ModerateFiltering",
                     "AggressiveFiltering", "MosaicBlending"):
            setattr(ms, name, object())
        sys.modules["Metashape"] = ms
    spec = importlib.util.spec_from_file_location(
        "run_pipeline_under_test",
        Path(__file__).with_name("run_pipeline.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    # Register before exec: the frozen ESMParameters dataclass decorator looks the
    # module up in sys.modules by name while processing the class.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


rp = _load_run_pipeline_with_stubbed_metashape()


# --------------------------------------------------------------------------- #
# Record factory — mirrors the shape _extract_marker_records emits.
# A bar of local length L is two markers placed L apart along +x.
# --------------------------------------------------------------------------- #


def _rec(mid, resid=0.2, pos=None, reconstructed=True, n_proj=12):
    return {
        "id": mid,
        "label": f"marker {mid}",
        "reconstructed": reconstructed,
        "projection_count": n_proj,
        "resid_px_median": resid,
        "resid_px_max": resid,
        "pos_local": pos if pos is not None else [float(mid), 0.0, 0.0],
        "images": [f"img_{mid}_{k}" for k in range(n_proj)],
    }


def _bar(a, b, x0, length, resid=0.2):
    """Two records forming one bar of local `length` along +x from x0."""
    return [_rec(a, resid=resid, pos=[x0, 0.0, 0.0]),
            _rec(b, resid=resid, pos=[x0 + length, 0.0, 0.0])]


def _clean_t3_like():
    """8 markers, 4 consecutive-ID bars, lengths 1.0/1.0/1.0/1.09 (ratio 1.09),
    resid 0.10-0.38 px — the T3 known-good shape."""
    recs = []
    recs += _bar(13, 14, x0=0.0, length=1.00, resid=0.10)
    recs += _bar(15, 16, x0=3.0, length=1.00, resid=0.20)
    recs += _bar(19, 20, x0=6.0, length=1.00, resid=0.30)
    recs += _bar(25, 26, x0=9.0, length=1.09, resid=0.38)
    return recs


CEIL = rp.GATE_MARKER_RESID_CEILING_PX        # 2.0
RATIO = rp.GATE_INTERBAR_RATIO_MAX            # 1.25


def _validate(recs):
    return rp.validate_markers(recs, resid_ceiling=CEIL, interbar_ratio_max=RATIO)


# --------------------------------------------------------------------------- #
# _propose_bars_by_adjacency — the pairing primitive
# --------------------------------------------------------------------------- #


def test_pairing_clean_even_set():
    pairs, orphans = rp._propose_bars_by_adjacency([13, 14, 15, 16, 19, 20, 25, 26])
    assert pairs == [(13, 14), (15, 16), (19, 20), (25, 26)]
    assert orphans == []


def test_pairing_t1_orphans_match_probe():
    # The real T1 detected-ID set; orphans/odd are the documented FAIL.
    pairs, orphans = rp._propose_bars_by_adjacency([13, 15, 16, 19, 20, 24, 26])
    assert pairs == [(15, 16), (19, 20)]
    assert orphans == [13, 24, 26]


def test_pairing_ignores_none_and_dedupes():
    pairs, orphans = rp._propose_bars_by_adjacency([14, 13, 13, None, 16, 15])
    assert pairs == [(13, 14), (15, 16)]
    assert orphans == []


# --------------------------------------------------------------------------- #
# Gate (a) — parity / orphans
# --------------------------------------------------------------------------- #


def test_gate_a_clean_passes():
    ga = rp.gate_parity(_clean_t3_like())
    assert ga["ok"] is True
    assert ga["orphans"] == []
    assert ga["odd_count"] is False
    assert ga["proposed_pairs"] == [[13, 14], [15, 16], [19, 20], [25, 26]]


def test_gate_a_t1_orphans_fail():
    recs = [_rec(i) for i in (13, 15, 16, 19, 20, 24, 26)]
    ga = rp.gate_parity(recs)
    assert ga["ok"] is False
    assert ga["orphans"] == [13, 24, 26]
    assert ga["odd_count"] is True


def test_gate_a_even_but_nonconsecutive_fails():
    # Even count but a gap -> orphans, still a fail (count-evenness alone is not it).
    ga = rp.gate_parity([_rec(13), _rec(14), _rec(20), _rec(25)])
    assert ga["ok"] is False
    assert ga["orphans"] == [20, 25]


def test_gate_a_unreconstructed_excluded():
    recs = _clean_t3_like()
    recs.append(_rec(99, reconstructed=False))   # ghost w/o position -> ignored
    ga = rp.gate_parity(recs)
    assert ga["ok"] is True
    assert 99 not in ga["orphans"]


# --------------------------------------------------------------------------- #
# Gate (b) — reprojection coherence
# --------------------------------------------------------------------------- #


def test_gate_b_clean_passes():
    recs = _clean_t3_like()
    pairs = [tuple(p) for p in rp.gate_parity(recs)["proposed_pairs"]]
    gb = rp.gate_coherence(recs, pairs, CEIL)
    assert gb["ok"] is True
    assert gb["load_bearing_flagged"] == []


def test_gate_b_incoherent_load_bearing_fails():
    # Bar 13-14 with marker 14 reprojecting to garbage -> load-bearing -> FAIL.
    recs = _bar(13, 14, 0.0, 1.0, resid=0.2) + _bar(15, 16, 3.0, 1.0, resid=0.2)
    for r in recs:
        if r["id"] == 14:
            r["resid_px_median"] = 5000.0
    pairs = [tuple(p) for p in rp.gate_parity(recs)["proposed_pairs"]]
    gb = rp.gate_coherence(recs, pairs, CEIL)
    assert gb["ok"] is False
    assert gb["load_bearing_flagged"] == [14]


def test_gate_b_t1_all_markers_blow_past_ceiling():
    # The whole T1 layer reprojects to thousands of px; every load-bearing marker
    # on the two proposable bars is flagged.
    recs = _bar(15, 16, 0.0, 1.0, resid=2246.0) + _bar(19, 20, 3.0, 1.3, resid=4.7e10)
    pairs = [tuple(p) for p in rp.gate_parity(recs)["proposed_pairs"]]
    gb = rp.gate_coherence(recs, pairs, CEIL)
    assert gb["ok"] is False
    assert gb["load_bearing_flagged"] == [15, 16, 19, 20]


def test_gate_b_flagged_orphan_not_double_counted():
    # A high-resid ORPHAN is flagged but is NOT load-bearing (gate (a) owns it),
    # so gate (b) does not independently fail on it.
    recs = [_rec(13, resid=0.2, pos=[0, 0, 0]), _rec(14, resid=0.2, pos=[1, 0, 0]),
            _rec(40, resid=9999.0, pos=[5, 0, 0])]   # orphan, garbage resid
    pairs = [tuple(p) for p in rp.gate_parity(recs)["proposed_pairs"]]
    gb = rp.gate_coherence(recs, pairs, CEIL)
    assert gb["ok"] is True
    assert 40 in {f["id"] for f in gb["flagged"]}
    assert gb["load_bearing_flagged"] == []


def test_gate_b_missing_residual_is_flagged():
    recs = _bar(13, 14, 0.0, 1.0, resid=0.2)
    for r in recs:
        if r["id"] == 14:
            r["resid_px_median"] = None        # never reconstructed a residual
    pairs = [tuple(p) for p in rp.gate_parity(recs)["proposed_pairs"]]
    gb = rp.gate_coherence(recs, pairs, CEIL)
    assert gb["ok"] is False
    assert gb["load_bearing_flagged"] == [14]


# --------------------------------------------------------------------------- #
# Gate (c) — inter-bar consistency
# --------------------------------------------------------------------------- #


def test_gate_c_clean_ratio_passes():
    gc = rp.gate_consistency([1.0, 1.0, 1.0, 1.09], RATIO)
    assert gc["ok"] is True
    assert gc["ratio"] == round(1.09 / 1.0, 4)


def test_gate_c_t1_ratio_fails():
    # The real T1 ID-adjacent bars: 31.88 vs 43.09 -> 1.352 > 1.25.
    gc = rp.gate_consistency([31.88, 43.09], RATIO)
    assert gc["ok"] is False
    assert gc["ratio"] == round(43.09 / 31.88, 4)


def test_gate_c_abstains_with_fewer_than_two_bars():
    gc = rp.gate_consistency([1.0], RATIO)
    assert gc["ok"] is True
    assert gc["abstained"] is True


def test_gate_c_at_threshold_passes():
    gc = rp.gate_consistency([1.0, 1.25], RATIO)   # exactly the tolerance
    assert gc["ok"] is True


# --------------------------------------------------------------------------- #
# validate_markers — the aggregate verdict
# --------------------------------------------------------------------------- #


def test_validate_clean_passes_all_three():
    v = _validate(_clean_t3_like())
    assert v["passed"] is True
    assert all(g["ok"] for g in v["gates"].values())
    assert len(v["candidate_bars"]) == 4
    assert v["suspect_ids"] == []


def test_validate_aggregates_all_findings_not_short_circuit():
    # A layer that fails (a) AND (c): every gate still ran and reported.
    recs = (_bar(15, 16, 0.0, 1.00, resid=0.2)
            + _bar(19, 20, 3.0, 1.40, resid=0.2)   # ratio 1.4 -> (c) fail
            + [_rec(13), _rec(24), _rec(26)])       # orphans -> (a) fail
    v = _validate(recs)
    assert v["passed"] is False
    assert v["gates"]["a_parity"]["ok"] is False
    assert v["gates"]["c_consistency"]["ok"] is False
    assert v["gates"]["a_parity"]["orphans"] == [13, 24, 26]


def test_validate_t1_like_escalates_on_a_and_c():
    # T1 shape: orphans {13,24,26} (a) and bars 31.88/43.09 (c).
    recs = (_bar(15, 16, 0.0, 31.88, resid=2246.0)
            + _bar(19, 20, 100.0, 43.09, resid=2246.0)
            + [_rec(13, resid=2246.0), _rec(24, resid=2246.0), _rec(26, resid=2246.0)])
    v = _validate(recs)
    assert v["passed"] is False
    failed = [g for g, r in v["gates"].items() if not r["ok"]]
    assert "a_parity" in failed and "c_consistency" in failed
    # gate (b) also fails: the load-bearing 15/16/19/20 are all incoherent.
    assert "b_coherence" in failed
    assert set(v["suspect_ids"]) >= {13, 24, 26}


def test_validate_single_gate_b_failure_escalates():
    recs = _clean_t3_like()
    for r in recs:
        if r["id"] == 16:
            r["resid_px_median"] = 3000.0
    v = _validate(recs)
    assert v["passed"] is False
    assert v["gates"]["a_parity"]["ok"] is True
    assert v["gates"]["c_consistency"]["ok"] is True
    assert v["gates"]["b_coherence"]["ok"] is False
    assert 16 in v["suspect_ids"]


def test_validate_thresholds_recorded():
    v = _validate(_clean_t3_like())
    assert v["thresholds"]["resid_ceiling_px"] == CEIL
    assert v["thresholds"]["interbar_ratio_max"] == RATIO


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
