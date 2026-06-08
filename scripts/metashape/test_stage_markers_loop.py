#!/usr/bin/env python3
"""
test_stage_markers_loop.py — offline integration test of the headless ->
fail-early -> GUI -> re-enter loop (ADR-0022), the actual deliverable.

It drives the real stage_markers / stage_scale control flow against lightweight
fakes for the Metashape chunk/doc, with two seams stubbed:
  * run_pipeline.save        -> no-op (the fake doc has no on-disk .files to mtime)
  * run_pipeline._extract_marker_records -> returns canned per-marker records, so
    the test controls the verdict (the residual/position EXTRACTION is Metashape's
    job and is already covered read-only by probes/stage_markers_verify.py; the
    GATE LOGIC is covered by test_marker_validation.py). What THIS test pins is the
    loop: FAIL escalates + halts before scale, re-entry validates the EXISTING set
    (no re-detect) and on PASS hands a validated set to a dumb stage_scale.

Run:  python3 -m pytest scripts/metashape/test_stage_markers_loop.py -v
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


def _load_run_pipeline():
    # Ensure the enum names run_pipeline references at import (_DEPTH/_BLEND)
    # exist on the Metashape stub even if another test module (collected first)
    # already installed a barer one — otherwise import order decides pass/fail.
    ms = sys.modules.get("Metashape")
    if ms is None:
        ms = types.ModuleType("Metashape")
        sys.modules["Metashape"] = ms
    for name in ("MildFiltering", "ModerateFiltering",
                 "AggressiveFiltering", "MosaicBlending"):
        if not hasattr(ms, name):
            setattr(ms, name, object())
    spec = importlib.util.spec_from_file_location(
        "run_pipeline_loop_under_test", Path(__file__).with_name("run_pipeline.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


rp = _load_run_pipeline()


# --------------------------------------------------------------------------- #
# Minimal Metashape fakes — only what stage_markers / stage_scale touch.
# --------------------------------------------------------------------------- #


class _Ref:
    def __init__(self):
        self.distance = None


class _Scalebar:
    def __init__(self, p0, p1):
        self.point0, self.point1 = p0, p1
        self.label = f"{p0.label}_{p1.label}"
        self.reference = _Ref()


class _Marker:
    def __init__(self, mid, has_pos=True):
        self.label = f"marker {mid}"
        self.position = object() if has_pos else None


class _Chunk:
    def __init__(self, label, markers):
        self.label = label
        self.markers = list(markers)
        self.scalebars = []
        self.meta = {}                       # _meta_get/_meta_set use a dict-like

    def addScalebar(self, a, b):
        sb = _Scalebar(a, b)
        self.scalebars.append(sb)
        return sb


class _Doc:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.path = "/tmp/fake.psx"


def _rec(mid, resid=0.2, pos=None, n_proj=12):
    return {"id": mid, "label": f"marker {mid}", "reconstructed": True,
            "projection_count": n_proj, "resid_px_median": resid,
            "resid_px_max": resid,
            "pos_local": pos if pos is not None else [float(mid), 0.0, 0.0],
            "images": [f"i{mid}_{k}" for k in range(n_proj)]}


def _bar(a, b, x0, length, resid=0.2):
    return [_rec(a, resid=resid, pos=[x0, 0.0, 0.0]),
            _rec(b, resid=resid, pos=[x0 + length, 0.0, 0.0])]


def _t3_records():
    """4 clean consecutive-ID bars, ratio ~1.09, resid <=0.38 -> PASS."""
    recs = []
    for (a, b, x0, ln, res) in [(13, 14, 0.0, 1.00, 0.10), (15, 16, 3.0, 1.00, 0.20),
                                (19, 20, 6.0, 1.00, 0.30), (25, 26, 9.0, 1.09, 0.38)]:
        recs.append({"id": a, "label": f"marker {a}", "reconstructed": True,
                     "projection_count": 12, "resid_px_median": res,
                     "resid_px_max": res, "pos_local": [x0, 0.0, 0.0],
                     "images": [f"i{a}_{k}" for k in range(12)]})
        recs.append({"id": b, "label": f"marker {b}", "reconstructed": True,
                     "projection_count": 12, "resid_px_median": res,
                     "resid_px_max": res, "pos_local": [x0 + ln, 0.0, 0.0],
                     "images": [f"i{b}_{k}" for k in range(12)]})
    return recs


def _t1_records():
    """The incoherent T1 shape: orphans {13,24,26}, bars 31.88/43.09, all resid
    garbage -> FAIL (a)+(b)+(c)."""
    recs = [{"id": 15, "label": "marker 15", "reconstructed": True,
             "projection_count": 143, "resid_px_median": 5.1e10, "resid_px_max": 5.1e10,
             "pos_local": [0.0, 0.0, 0.0], "images": [f"c{k}" for k in range(143)]},
            {"id": 16, "label": "marker 16", "reconstructed": True,
             "projection_count": 150, "resid_px_median": 2.1e6, "resid_px_max": 2.1e6,
             "pos_local": [31.88, 0.0, 0.0], "images": [f"d{k}" for k in range(150)]},
            {"id": 19, "label": "marker 19", "reconstructed": True,
             "projection_count": 156, "resid_px_median": 1.0e4, "resid_px_max": 1.0e4,
             "pos_local": [100.0, 0.0, 0.0], "images": [f"e{k}" for k in range(156)]},
            {"id": 20, "label": "marker 20", "reconstructed": True,
             "projection_count": 128, "resid_px_median": 6.8e5, "resid_px_max": 6.8e5,
             "pos_local": [143.091, 0.0, 0.0], "images": [f"f{k}" for k in range(128)]}]
    for mid, pc in [(13, 182), (24, 111), (26, 132)]:
        recs.append({"id": mid, "label": f"marker {mid}", "reconstructed": True,
                     "projection_count": pc, "resid_px_median": 5000.0,
                     "resid_px_max": 5000.0, "pos_local": [float(mid), 1.0, 0.0],
                     "images": [f"g{mid}_{k}" for k in range(pc)]})
    return recs


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(rp, "save", lambda doc: None)
    # This file pins the marker -> scale LOOP, not the network-health collapse gate
    # (ADR-0023, covered by test_network_health.py). Its stub chunks deliberately do
    # not model the camera/tie-point network, so no-op the 3c pre-condition here.
    monkeypatch.setattr(rp, "_check_network_health_or_escalate",
                        lambda *a, **k: {"ok": True, "failures": []})
    return monkeypatch


def _markers_for(ids):
    return [_Marker(i) for i in ids]


def _run_markers(doc, out_root, ignore_sanity=False):
    rp.stage_markers(doc, ignore_sanity, None, None, out_root,
                     rp.GATE_MARKER_RESID_CEILING_PX, rp.GATE_INTERBAR_RATIO_MAX)


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #


def test_fail_escalates_and_halts_before_scale(patched, tmp_path):
    # T1-like layer (markers already present so detection is skipped).
    chunk = _Chunk("EDR_T1", _markers_for([13, 15, 16, 19, 20, 24, 26]))
    doc = _Doc([chunk])
    patched.setattr(rp, "_extract_marker_records", lambda ch: _t1_records())

    with pytest.raises(rp.PipelineSanityError):
        _run_markers(doc, tmp_path)

    # escalation artifact written, status persisted as escalated
    report = tmp_path / "EDR_T1" / "markers_escalation.json"
    assert report.exists()
    data = json.loads(report.read_text())
    assert data["status"] == "escalated"
    assert set(data["failed_gates"]) >= {"a_parity", "c_consistency", "b_coherence"}
    assert data["gates"]["a_parity"]["orphans"] == [13, 24, 26]
    # which images each suspect spans is recorded
    assert "24" in data["evidence"]["suspect_marker_images"]
    assert data["evidence"]["suspect_marker_images"]["24"]["projection_count"] == 111
    assert data["evidence"]["projection_counts"]["24"] == 111
    val = rp._meta_get(chunk, "esm.markers_validation")
    assert val["status"] == "escalated"
    # CRUCIAL: no scale bars were created (halted BEFORE scale)
    assert chunk.scalebars == []


def test_scale_refuses_an_escalated_layer(patched, tmp_path):
    chunk = _Chunk("EDR_T1", _markers_for([13, 15, 16, 19, 20, 24, 26]))
    doc = _Doc([chunk])
    patched.setattr(rp, "_extract_marker_records", lambda ch: _t1_records())
    with pytest.raises(rp.PipelineSanityError):
        _run_markers(doc, tmp_path)
    # stage_scale must refuse (status != headless-pass) -> critical alarm
    with pytest.raises(rp.PipelineSanityError):
        rp.stage_scale(doc, tmp_path, False, rp.HealthConfig())
    assert rp._meta_get(chunk, "esm.scale") is None


def test_reentry_validates_existing_then_scales(patched, tmp_path):
    # Round 1: escalate on the bad layer.
    chunk = _Chunk("EDR_T1", _markers_for([13, 15, 16, 19, 20, 24, 26]))
    doc = _Doc([chunk])
    patched.setattr(rp, "_extract_marker_records", lambda ch: _t1_records())
    with pytest.raises(rp.PipelineSanityError):
        _run_markers(doc, tmp_path)

    # --- simulate the human GUI fix: the corrected, even, consecutive-ID set ---
    chunk.markers = _markers_for([13, 14, 15, 16, 19, 20, 25, 26])
    patched.setattr(rp, "_extract_marker_records", lambda ch: _t3_records())

    # Round 2 (RE-ENTRY): markers present -> NO re-detect, validate EXISTING set.
    detect_calls = {"n": 0}
    patched.setattr(rp, "_detect_markers",
                    lambda *a, **k: detect_calls.__setitem__("n", detect_calls["n"] + 1))
    _run_markers(doc, tmp_path)              # must NOT raise now
    assert detect_calls["n"] == 0, "re-entry must not re-detect"

    val = rp._meta_get(chunk, "esm.markers_validation")
    assert val["status"] == "headless-pass"
    bars = json.loads((tmp_path / "EDR_T1" / "validated_scalebars.json").read_text())
    assert {(b["a"], b["b"]) for b in bars} == {(13, 14), (15, 16), (19, 20), (25, 26)}
    assert all(b["defined_distance_m"] == 0.25 for b in bars)

    # --- stage_scale: dumb apply of the validated set ---
    rp.stage_scale(doc, tmp_path, False, rp.HealthConfig())
    assert len(chunk.scalebars) == 4
    assert all(sb.reference.distance == 0.25 for sb in chunk.scalebars)
    scale_meta = rp._meta_get(chunk, "esm.scale")
    assert sorted(scale_meta["bars_created"]) == [[13, 14], [15, 16], [19, 20], [25, 26]]
    assert scale_meta["bars_reused_from_gui"] == []


def test_scale_reuses_gui_created_bars(patched, tmp_path):
    # Layer passes; the human ALSO created one bar (13-14) in the GUI -> reused.
    chunk = _Chunk("EDR_T3", _markers_for([13, 14, 15, 16, 19, 20, 25, 26]))
    doc = _Doc([chunk])
    m13 = next(m for m in chunk.markers if m.label == "marker 13")
    m14 = next(m for m in chunk.markers if m.label == "marker 14")
    chunk.addScalebar(m13, m14)              # pre-existing GUI bar
    patched.setattr(rp, "_extract_marker_records", lambda ch: _t3_records())
    _run_markers(doc, tmp_path)
    rp.stage_scale(doc, tmp_path, False, rp.HealthConfig())
    assert len(chunk.scalebars) == 4         # 1 reused + 3 created, not 5
    meta = rp._meta_get(chunk, "esm.scale")
    assert meta["bars_reused_from_gui"] == [[13, 14]]
    assert sorted(meta["bars_created"]) == [[15, 16], [19, 20], [25, 26]]


def test_passed_layer_is_idempotent_on_rerun(patched, tmp_path):
    chunk = _Chunk("EDR_T3", _markers_for([13, 14, 15, 16, 19, 20, 25, 26]))
    doc = _Doc([chunk])
    calls = {"n": 0}

    def _extract(ch):
        calls["n"] += 1
        return _t3_records()
    patched.setattr(rp, "_extract_marker_records", _extract)
    _run_markers(doc, tmp_path)
    assert calls["n"] == 1
    _run_markers(doc, tmp_path)              # already headless-pass -> skip
    assert calls["n"] == 1, "a passed layer must not re-validate"


# --------------------------------------------------------------------------- #
# Re-entry robustness (HARDENING)
# --------------------------------------------------------------------------- #


def _two_bar_records():
    return _bar(13, 14, 0.0, 1.0, resid=0.2) + _bar(15, 16, 3.0, 1.0, resid=0.2)


def _partial_fix_records():
    """4 bars but marker 16 still incoherent (load-bearing) — a half-done GUI fix."""
    recs = _t3_records()
    for r in recs:
        if r["id"] == 16:
            r["resid_px_median"] = 5000.0
    return recs


def test_reentry_still_failing_escalates_again(patched, tmp_path):
    chunk = _Chunk("EDR_T1", _markers_for([13, 15, 16, 19, 20, 24, 26]))
    doc = _Doc([chunk])
    patched.setattr(rp, "_extract_marker_records", lambda ch: _t1_records())
    with pytest.raises(rp.PipelineSanityError):
        _run_markers(doc, tmp_path)
    # "human fix" that is still bad -> ESCALATE again (no infinite loop, no pass)
    with pytest.raises(rp.PipelineSanityError):
        _run_markers(doc, tmp_path)
    assert rp._meta_get(chunk, "esm.markers_validation")["status"] == "escalated"
    assert chunk.scalebars == []


def test_partial_fix_escalates(patched, tmp_path):
    chunk = _Chunk("EDR_T1", _markers_for([13, 15, 16, 19, 20, 24, 26]))
    doc = _Doc([chunk])
    patched.setattr(rp, "_extract_marker_records", lambda ch: _t1_records())
    with pytest.raises(rp.PipelineSanityError):
        _run_markers(doc, tmp_path)
    # corrected set, but one flagged marker remains (16) -> ESCALATE
    chunk.markers = _markers_for([13, 14, 15, 16, 19, 20, 25, 26])
    patched.setattr(rp, "_extract_marker_records", lambda ch: _partial_fix_records())
    with pytest.raises(rp.PipelineSanityError):
        _run_markers(doc, tmp_path)
    rep = json.loads((tmp_path / "EDR_T1" / "markers_escalation.json").read_text())
    assert "b_coherence" in rep["failed_gates"]
    assert 16 in rep["suspect_ids"]


def test_insufficient_bars_escalates_at_stage(patched, tmp_path):
    chunk = _Chunk("EDR_T3", _markers_for([13, 14, 15, 16]))
    doc = _Doc([chunk])
    patched.setattr(rp, "_extract_marker_records", lambda ch: _two_bar_records())
    with pytest.raises(rp.PipelineSanityError):
        _run_markers(doc, tmp_path)
    rep = json.loads((tmp_path / "EDR_T3" / "markers_escalation.json").read_text())
    assert "d_sufficiency" in rep["failed_gates"]
    assert chunk.scalebars == []


# --------------------------------------------------------------------------- #
# Fail-closed on exception (HARDENING)
# --------------------------------------------------------------------------- #


def test_extraction_exception_escalates_never_passes(patched, tmp_path):
    chunk = _Chunk("EDR_T1", _markers_for([13, 14, 15, 16, 19, 20, 25, 26]))
    doc = _Doc([chunk])

    def _boom(ch):
        raise RuntimeError("metashape exploded mid-extract")
    patched.setattr(rp, "_extract_marker_records", _boom)
    with pytest.raises(rp.PipelineSanityError):
        _run_markers(doc, tmp_path)
    rep = json.loads((tmp_path / "EDR_T1" / "markers_escalation.json").read_text())
    assert rep["status"] == "escalated"
    assert rep["failed_gates"] == ["extraction_error"]
    assert rep["error"]["type"] == "RuntimeError"
    val = rp._meta_get(chunk, "esm.markers_validation")
    assert val["status"] == "escalated"
    assert chunk.scalebars == []
    # stage_scale must still refuse
    with pytest.raises(rp.PipelineSanityError):
        rp.stage_scale(doc, tmp_path, False, rp.HealthConfig())


# --------------------------------------------------------------------------- #
# Provenance integrity (HARDENING)
# --------------------------------------------------------------------------- #


def test_zero_touch_pass_recorded_as_headless_auto(patched, tmp_path):
    chunk = _Chunk("EDR_T3", _markers_for([13, 14, 15, 16, 19, 20, 25, 26]))
    doc = _Doc([chunk])
    patched.setattr(rp, "_extract_marker_records", lambda ch: _t3_records())
    _run_markers(doc, tmp_path)
    rec = json.loads((tmp_path / "EDR_T3" / "markers_validation.json").read_text())
    assert rec["marker_source"] == "headless-auto"
    assert rec["human_touch"] == "none"
    assert rec["prior_escalation"] is None


def test_human_corrected_pass_recorded_distinctly(patched, tmp_path):
    chunk = _Chunk("EDR_T1", _markers_for([13, 15, 16, 19, 20, 24, 26]))
    doc = _Doc([chunk])
    patched.setattr(rp, "_extract_marker_records", lambda ch: _t1_records())
    with pytest.raises(rp.PipelineSanityError):
        _run_markers(doc, tmp_path)
    # GUI fix -> re-enter -> PASS
    chunk.markers = _markers_for([13, 14, 15, 16, 19, 20, 25, 26])
    patched.setattr(rp, "_extract_marker_records", lambda ch: _t3_records())
    _run_markers(doc, tmp_path)
    rec = json.loads((tmp_path / "EDR_T1" / "markers_validation.json").read_text())
    assert rec["marker_source"] == "human-corrected"
    assert rec["human_touch"] == "gui-marker-fix"
    assert rec["prior_escalation"] is not None
    assert "a_parity" in rec["prior_escalation"]["failed_gates"]
    # the manifest can now tell T3-zero-touch from T1-corrected-by-human
    assert rec["prior_escalation"]["report"].endswith("markers_escalation.json")


def test_bar_length_param_flows_through(patched, tmp_path):
    # A foreign survey with a 0.5 m bar: markers records it, scale applies it.
    chunk = _Chunk("SITE_X", _markers_for([200, 201, 202, 203, 204, 205]))
    doc = _Doc([chunk])
    foreign = (_bar(200, 201, 0.0, 1.0) + _bar(202, 203, 5.0, 1.0)
               + _bar(204, 205, 10.0, 1.0))
    patched.setattr(rp, "_extract_marker_records", lambda ch: foreign)
    rp.stage_markers(doc, False, None, None, tmp_path,
                     rp.GATE_MARKER_RESID_CEILING_PX, rp.GATE_INTERBAR_RATIO_MAX,
                     rp.GATE_MIN_VALIDATED_BARS, 0.5)
    bars = json.loads((tmp_path / "SITE_X" / "validated_scalebars.json").read_text())
    assert all(b["defined_distance_m"] == 0.5 for b in bars)
    rp.stage_scale(doc, tmp_path, False, rp.HealthConfig(), bar_length=0.5)
    assert len(chunk.scalebars) == 3
    assert all(sb.reference.distance == 0.5 for sb in chunk.scalebars)


def test_validated_scalebars_are_deterministic(patched, tmp_path):
    patched.setattr(rp, "_extract_marker_records", lambda ch: _t3_records())
    out_a, out_b = tmp_path / "a", tmp_path / "b"
    for out in (out_a, out_b):
        chunk = _Chunk("EDR_T3", _markers_for([13, 14, 15, 16, 19, 20, 25, 26]))
        _run_markers(_Doc([chunk]), out)
    a = (out_a / "EDR_T3" / "validated_scalebars.json").read_text()
    b = (out_b / "EDR_T3" / "validated_scalebars.json").read_text()
    assert a == b, "same input must yield byte-identical validated_scalebars.json"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
