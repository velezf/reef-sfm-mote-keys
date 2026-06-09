#!/usr/bin/env python3
"""test_stage_scale_crs.py — regression-locks the spurious-WGS84 fix (ADR-0024).

Root: Metashape assigns EPSG:4326 (WGS84) as the default CRS for no-GPS
captures.  After scale-bar assignment + updateTransform, marker.reference.location
is auto-populated with garbage WGS84 coordinates (latitude ≈ -90°, altitude
≈ -6.36e6 m) and camera.reference.location carries a stub GPS fix — both with
reference.enabled=True.  A subsequent optimizeCameras (inside Logan reduce)
treats these as live GCPs and diverges catastrophically (scale 1.0→823,
reproj 0.15→1.3e152 px).

_neutralize_spurious_reference is the fix: it sets chunk.crs to LOCAL metre
and disables all marker + camera reference.enabled.  Scale bars are untouched —
they constrain via reference.distance / reference.accuracy, not via location.

Contract tested here (pure pytest, zero Metashape):
  1. _neutralize_spurious_reference sets chunk.crs to LOCAL.
  2. All marker reference.enabled become False.
  3. All camera reference.enabled become False.
  4. Scale bars are untouched (accuracy unchanged).
  5. Idempotent: a second call on an already-LOCAL chunk is a no-op (no error,
     counts are 0).
  6. stage_scale calls _neutralize_spurious_reference before save, so the
     saved state satisfies the above invariants.

Run:  python3 -m pytest scripts/metashape/test_stage_scale_crs.py -v
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_LOCAL_CS_WKT = (  # must match run_pipeline._LOCAL_CS_WKT exactly
    'LOCAL_CS["Local Coordinates (m)",LOCAL_DATUM["Local Datum",0],'
    'UNIT["metre",1]]'
)


def _load_run_pipeline():
    ms = sys.modules.get("Metashape")
    if ms is None:
        ms = types.ModuleType("Metashape")
        sys.modules["Metashape"] = ms
    for name in ("MildFiltering", "ModerateFiltering",
                 "AggressiveFiltering", "MosaicBlending"):
        if not hasattr(ms, name):
            setattr(ms, name, object())
    # CoordinateSystem: return a simple object carrying the WKT so tests can
    # distinguish LOCAL from WGS84 without a real Metashape binary.
    if not hasattr(ms, "CoordinateSystem"):
        class _CS:
            def __init__(self, wkt=""):
                self.wkt = wkt
                self.authority = "LOCAL" if "LOCAL_CS" in wkt else "EPSG::4326"
                self.name = "Local Coordinates (m)" if "LOCAL_CS" in wkt else "WGS 84"
            def __repr__(self):
                return f"<CoordinateSystem {self.name!r}>"
        ms.CoordinateSystem = _CS
    spec = importlib.util.spec_from_file_location(
        "run_pipeline_crs_under_test", Path(__file__).with_name("run_pipeline.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


rp = _load_run_pipeline()


# --------------------------------------------------------------------------- #
# Minimal stubs — only what _neutralize_spurious_reference + stage_scale touch.
# --------------------------------------------------------------------------- #


class _CamRef:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.location = object()  # non-None


class _MarkerRef:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.location = object()  # non-None


class _BarRef:
    def __init__(self, accuracy=None):
        self.distance = 0.25
        self.accuracy = accuracy
        self.enabled = True


class _Camera:
    def __init__(self, enabled_ref=True):
        self.reference = _CamRef(enabled=enabled_ref)


class _Marker:
    def __init__(self, mid, enabled_ref=True):
        self.label = f"marker {mid}"
        self.position = object()
        self.reference = _MarkerRef(enabled=enabled_ref)


class _Scalebar:
    def __init__(self, a, b, accuracy=0.001):
        self.label = f"marker {a}_marker {b}"
        self.point0 = _Marker(a)
        self.point1 = _Marker(b)
        self.reference = _BarRef(accuracy=accuracy)


class _WGS84CS:
    wkt = 'GEOGCS["WGS 84",...,AUTHORITY["EPSG","4326"]]'
    authority = "EPSG::4326"
    name = "WGS 84"
    def __repr__(self):
        return "<CoordinateSystem 'WGS 84'>"


class _Chunk:
    def __init__(self, n_markers=8, n_cameras=10, n_bars=4, crs=None):
        self.label = "EDR_T1"
        self.crs = crs or _WGS84CS()
        self.markers = [_Marker(13 + i) for i in range(n_markers)]
        self.cameras = [_Camera() for _ in range(n_cameras)]
        self.scalebars = [_Scalebar(13 + 2 * i, 14 + 2 * i) for i in range(n_bars)]
        self.meta = {}

    def addScalebar(self, a, b):
        sb = _Scalebar(int(a.label.split()[-1]), int(b.label.split()[-1]))
        self.scalebars.append(sb)
        return sb


def _is_local(crs):
    return "LOCAL_CS" in getattr(crs, "wkt", "")


# --------------------------------------------------------------------------- #
# Tests for _neutralize_spurious_reference (the pure helper).
# --------------------------------------------------------------------------- #


def test_crs_becomes_local():
    chunk = _Chunk()
    assert not _is_local(chunk.crs)
    rp._neutralize_spurious_reference(chunk)
    assert _is_local(chunk.crs), f"expected LOCAL, got {chunk.crs!r}"


def test_all_marker_refs_disabled():
    chunk = _Chunk(n_markers=8)
    rp._neutralize_spurious_reference(chunk)
    for m in chunk.markers:
        assert m.reference.enabled is False, f"{m.label}: reference still enabled"


def test_all_camera_refs_disabled():
    chunk = _Chunk(n_cameras=2422)
    rp._neutralize_spurious_reference(chunk)
    for c in chunk.cameras:
        assert c.reference.enabled is False, "camera reference still enabled"


def test_scalebars_untouched():
    chunk = _Chunk(n_bars=4)
    for sb in chunk.scalebars:
        sb.reference.accuracy = 0.001
    rp._neutralize_spurious_reference(chunk)
    for sb in chunk.scalebars:
        assert sb.reference.accuracy == 0.001, "scale bar accuracy was modified"
        assert sb.reference.enabled is True, "scale bar reference was disabled"


def test_idempotent_second_call_is_noop():
    chunk = _Chunk()
    rp._neutralize_spurious_reference(chunk)
    # second call: crs already LOCAL, refs already disabled -> counts = 0
    result = rp._neutralize_spurious_reference(chunk)
    assert result["n_markers_ref_disabled"] == 0
    assert result["n_cameras_ref_disabled"] == 0
    assert _is_local(chunk.crs)


def test_returns_correct_counts():
    chunk = _Chunk(n_markers=8, n_cameras=5)
    result = rp._neutralize_spurious_reference(chunk)
    assert result["n_markers_ref_disabled"] == 8
    assert result["n_cameras_ref_disabled"] == 5


def test_none_reference_objects_skipped():
    chunk = _Chunk(n_markers=4, n_cameras=3)
    # Null out reference on some objects — must not raise
    for m in chunk.markers[:2]:
        m.reference = None
    for c in chunk.cameras[:1]:
        c.reference = None
    rp._neutralize_spurious_reference(chunk)
    result = rp._neutralize_spurious_reference(chunk)
    assert result["n_markers_ref_disabled"] == 0   # already off from first call
    assert result["n_cameras_ref_disabled"] == 0


# --------------------------------------------------------------------------- #
# Integration: stage_scale calls _neutralize_spurious_reference before save.
# --------------------------------------------------------------------------- #


class _Doc:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.path = "/tmp/fake.psx"


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(rp, "save", lambda doc: None)
    monkeypatch.setattr(rp, "_check_network_health_or_escalate",
                        lambda *a, **k: {"ok": True, "failures": []})
    return monkeypatch


def _pass_chunk():
    chunk = _Chunk(n_markers=8, n_cameras=10, n_bars=0)
    # Inject validated_scalebars meta so stage_scale accepts the chunk
    pairs = [{"a": 13 + 2 * i, "b": 14 + 2 * i, "defined_distance_m": 0.25}
             for i in range(4)]
    rp._meta_set(chunk, "esm.markers_validation", {
        "status": "headless-pass",
        "validated_scalebars": pairs,
    })
    return chunk


def test_stage_scale_produces_local_crs(patched):
    chunk = _pass_chunk()
    doc = _Doc([chunk])
    rp.stage_scale(doc, Path("/tmp"), ignore_sanity=False, health=rp.HealthConfig())
    assert _is_local(chunk.crs), f"expected LOCAL after stage_scale, got {chunk.crs!r}"


def test_stage_scale_disables_all_refs(patched):
    chunk = _pass_chunk()
    doc = _Doc([chunk])
    rp.stage_scale(doc, Path("/tmp"), ignore_sanity=False, health=rp.HealthConfig())
    for m in chunk.markers:
        assert m.reference.enabled is False, f"{m.label}: ref still enabled after scale"
    for c in chunk.cameras:
        assert c.reference.enabled is False, "camera ref still enabled after scale"


def test_stage_scale_scalebars_still_have_accuracy(patched):
    chunk = _pass_chunk()
    doc = _Doc([chunk])
    rp.stage_scale(doc, Path("/tmp"), ignore_sanity=False, health=rp.HealthConfig(),
                   scalebar_accuracy_m=0.001)
    for sb in chunk.scalebars:
        assert sb.reference.accuracy == 0.001, "scale bar accuracy lost"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
