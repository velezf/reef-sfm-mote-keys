#!/usr/bin/env python3
"""
test_network_health.py — regression-locks the network-health COLLAPSE GUARD
(ADR-0023), the tripwire added after the 2026-06-08 EDR_T1 reduce collapse (a
one-shot gradual selection removed 100% of tie points -> 86/2422 cameras; scale
and level then "succeeded" on the wreckage).

Two layers:
  * evaluate_network_health (PURE) — synthetic states pin the discriminators:
    camera-survival + scale-bar sanity are PRIMARY; the tie-point check is a
    NEAR-ZERO tripwire (a healthy reduce that sheds a large fraction must NOT
    false-fire).
  * _check_network_health_or_escalate (wiring) — a synthetic COLLAPSED stub chunk
    must escalate (write network_health_escalation.json + raise), and a healthy
    one must pass. This is the regression lock the brief asked for.

Run:  python3 -m pytest scripts/metashape/test_network_health.py -v
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


def _load_run_pipeline():
    ms = sys.modules.get("Metashape")
    if ms is None:
        ms = types.ModuleType("Metashape")
        sys.modules["Metashape"] = ms
    for name in ("MildFiltering", "ModerateFiltering",
                 "AggressiveFiltering", "MosaicBlending"):
        if not hasattr(ms, name):
            setattr(ms, name, object())
    spec = importlib.util.spec_from_file_location(
        "run_pipeline_health_under_test", Path(__file__).with_name("run_pipeline.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


rp = _load_run_pipeline()


# --------------------------------------------------------------------------- #
# PURE evaluator (evaluate_network_health) — no Metashape needed.
# --------------------------------------------------------------------------- #


def _state(aligned, enabled, tie_points, bars):
    return {"aligned": aligned, "enabled": enabled, "total": enabled,
            "tie_points": tie_points, "baseline_aligned": enabled,
            "scalebars": bars}


def _bars(measured, defined=0.25, n=4):
    return [{"a": 13 + 2 * i, "b": 14 + 2 * i, "defined_m": defined,
             "measured_m": measured} for i in range(n)]


def test_healthy_network_passes():
    st = _state(aligned=2348, enabled=2357, tie_points=4_000_000,
                bars=_bars(0.25))
    ev = rp.evaluate_network_health(st, min_aligned=2121, min_tiepoints=1000,
                                    scalebar_max_ratio=2.0, check_scalebars=True)
    assert ev["ok"] is True
    assert ev["failures"] == []


def test_collapse_trips_all_three_discriminators():
    # The actual EDR_T1 collapse shape: 86 aligned, 0 tie points, km-scale bars.
    st = _state(aligned=86, enabled=2357, tie_points=0,
                bars=_bars(660617.0))
    ev = rp.evaluate_network_health(st, min_aligned=2121, min_tiepoints=1000,
                                    scalebar_max_ratio=2.0, check_scalebars=True)
    assert ev["ok"] is False
    checks = {f["check"] for f in ev["failures"]}
    assert {"camera_survival", "tiepoint_near_zero", "scalebar_sanity"} <= checks


def test_tiepoint_check_is_near_zero_not_fractional():
    # A healthy Logan reduce legitimately sheds a LARGE share (here ~60%: 10M -> 4M).
    # Camera survival intact + bars sane -> must PASS (no fractional false-fire).
    st = _state(aligned=2348, enabled=2357, tie_points=4_000_000, bars=_bars(0.25))
    ev = rp.evaluate_network_health(st, min_aligned=2121, min_tiepoints=1000,
                                    scalebar_max_ratio=2.0, check_scalebars=True)
    assert ev["ok"] is True
    # Only near-total removal trips it:
    st0 = _state(aligned=2348, enabled=2357, tie_points=0, bars=_bars(0.25))
    ev0 = rp.evaluate_network_health(st0, min_aligned=2121, min_tiepoints=1000,
                                     scalebar_max_ratio=2.0, check_scalebars=True)
    assert ev0["ok"] is False
    assert {f["check"] for f in ev0["failures"]} == {"tiepoint_near_zero"}


def test_camera_survival_is_primary():
    # Tie points + bars fine, but cameras de-aligned -> FAIL on camera_survival.
    st = _state(aligned=1500, enabled=2357, tie_points=3_000_000, bars=_bars(0.25))
    ev = rp.evaluate_network_health(st, min_aligned=2121, min_tiepoints=1000,
                                    scalebar_max_ratio=2.0, check_scalebars=True)
    assert ev["ok"] is False
    assert {f["check"] for f in ev["failures"]} == {"camera_survival"}


def test_scalebar_sanity_is_coarse_within_2x():
    # Within 2x (0.4 m vs 0.25 m -> ratio 1.6) PASSES — coarse, not the fine gate.
    ok = rp.evaluate_network_health(
        _state(2348, 2357, 4_000_000, _bars(0.40)),
        min_aligned=2121, min_tiepoints=1000, scalebar_max_ratio=2.0,
        check_scalebars=True)
    assert ok["ok"] is True
    # Beyond 2x (0.6 m vs 0.25 -> ratio 2.4) trips scalebar_sanity.
    bad = rp.evaluate_network_health(
        _state(2348, 2357, 4_000_000, _bars(0.60)),
        min_aligned=2121, min_tiepoints=1000, scalebar_max_ratio=2.0,
        check_scalebars=True)
    assert {f["check"] for f in bad["failures"]} == {"scalebar_sanity"}


def test_scalebars_not_checked_pre_scale():
    # check_scalebars=False (e.g. scale:pre, model still in internal units) — the
    # internal-unit bar lengths must NOT be evaluated.
    ev = rp.evaluate_network_health(
        _state(2348, 2357, 4_000_000, _bars(1.69)),  # internal units
        min_aligned=2121, min_tiepoints=1000, scalebar_max_ratio=2.0,
        check_scalebars=False)
    assert ev["ok"] is True


def test_unmeasurable_scalebar_is_failed_closed():
    ev = rp.evaluate_network_health(
        _state(2348, 2357, 4_000_000, [{"a": 13, "b": 14, "defined_m": 0.25,
                                        "measured_m": None}]),
        min_aligned=2121, min_tiepoints=1000, scalebar_max_ratio=2.0,
        check_scalebars=True)
    assert {f["check"] for f in ev["failures"]} == {"scalebar_sanity"}


# --------------------------------------------------------------------------- #
# Wiring: _check_network_health_or_escalate against a synthetic COLLAPSED chunk.
# --------------------------------------------------------------------------- #


class _Vec:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Matrix:
    def mulp(self, p):                 # positions are already 'world' here
        return p


class _Transform:
    def __init__(self):
        self.matrix = _Matrix()
        self.scale = 1.0


class _Cam:
    def __init__(self, aligned, enabled=True):
        self.transform = object() if aligned else None
        self.enabled = enabled


class _MRef:
    def __init__(self, dist):
        self.distance = dist
        self.accuracy = None


class _Marker:
    def __init__(self, label, pos):
        self.label, self.position = label, pos


class _Bar:
    def __init__(self, a_id, b_id, sep_m, defined=0.25):
        self.point0 = _Marker(f"marker {a_id}", _Vec(0.0, 0.0, 0.0))
        self.point1 = _Marker(f"marker {b_id}", _Vec(sep_m, 0.0, 0.0))
        self.reference = _MRef(defined)


class _TP:
    def __init__(self, n):
        self.points = [0] * n


class _Chunk:
    def __init__(self, label, n_aligned, n_enabled, n_tp, bar_sep_m):
        self.label = label
        self.cameras = ([_Cam(True) for _ in range(n_aligned)]
                        + [_Cam(False) for _ in range(n_enabled - n_aligned)])
        self.tie_points = _TP(n_tp)
        self.transform = _Transform()
        self.scalebars = [_Bar(13 + 2 * i, 14 + 2 * i, bar_sep_m) for i in range(4)]
        self.meta = {}


def test_collapsed_chunk_escalates_and_halts(tmp_path):
    chunk = _Chunk("EDR_T1", n_aligned=86, n_enabled=2357, n_tp=0,
                   bar_sep_m=660617.0)
    with pytest.raises(rp.PipelineSanityError):
        rp._check_network_health_or_escalate(
            chunk, tmp_path, "reduce:post", rp.HealthConfig(),
            check_scalebars=True, ignore_sanity=False, baseline_aligned=2348)

    report = tmp_path / "EDR_T1" / "network_health_escalation.json"
    assert report.exists(), "collapse must write a structured escalation report"
    data = json.loads(report.read_text())
    assert data["status"] == "escalated"
    assert data["context"] == "reduce:post"
    assert {"camera_survival", "tiepoint_near_zero", "scalebar_sanity"} <= set(
        data["failed_checks"])
    val = rp._meta_get(chunk, "esm.network_health")
    assert val["status"] == "escalated"


def test_healthy_chunk_passes_no_escalation(tmp_path):
    chunk = _Chunk("EDR_T1", n_aligned=2348, n_enabled=2357, n_tp=4_000_000,
                   bar_sep_m=0.25)
    ev = rp._check_network_health_or_escalate(
        chunk, tmp_path, "reduce:post", rp.HealthConfig(),
        check_scalebars=True, ignore_sanity=False, baseline_aligned=2348)
    assert ev["ok"] is True
    assert not (tmp_path / "EDR_T1" / "network_health_escalation.json").exists()


def test_ignore_sanity_downgrades_collapse_to_warn(tmp_path):
    # With --ignore-sanity the alarm is non-fatal, but the report is STILL written
    # (so a forced run never hides the collapse).
    chunk = _Chunk("EDR_T1", n_aligned=86, n_enabled=2357, n_tp=0, bar_sep_m=1.0e6)
    ev = rp._check_network_health_or_escalate(
        chunk, tmp_path, "level:pre", rp.HealthConfig(),
        check_scalebars=True, ignore_sanity=True, baseline_aligned=2348)
    assert ev["ok"] is False
    assert (tmp_path / "EDR_T1" / "network_health_escalation.json").exists()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
