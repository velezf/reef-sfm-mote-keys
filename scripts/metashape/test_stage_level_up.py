#!/usr/bin/env python3
"""test_stage_level_up.py — Unit tests for _compute_level_up (ADR-0025).

Bug fixed: stage_level leveled EDR_T1 to an ill-conditioned plane normal produced
by near-collinear marker positions (eig[1]/eig[0] ≈ 0.10). The existing flatness
guard (eig[2]/eig[1]) only catches volumetric/non-planar sets; it does NOT catch
near-collinear markers where the in-plane minor axis is tiny compared to the major
axis. Result: world-Z ended up 80.6° off physical vertical.

Fix: extract a pure-Python _compute_level_up that uses camera-nadir as the UP
direction when (a) markers are near-collinear, or (b) marker normal and camera
nadir disagree by more than LEVEL_NADIR_GUARD_DEG. In case (b) the disagreement
is escalated (nadir_guard_fired=True in the return value) — never silent.

Three contract tests (RED until _compute_level_up is implemented):
  (a) near-collinear markers → collinear_guard fires → method="camera_nadir"
  (b) well-spread markers, cameras agree → method="marker_plane"
  (c) well-spread markers, cameras disagree >15° → nadir_guard fires (NOT silent)
        → method="camera_nadir"

Run:  python3 -m pytest scripts/metashape/test_stage_level_up.py -v
"""
from __future__ import annotations

import importlib.util
import math
import sys
import types
from pathlib import Path


def _load_run_pipeline():
    ms = sys.modules.get("Metashape")
    if ms is None:
        ms = types.ModuleType("Metashape")
        sys.modules["Metashape"] = ms
    for name in ("MildFiltering", "ModerateFiltering",
                 "AggressiveFiltering", "MosaicBlending"):
        if not hasattr(ms, name):
            setattr(ms, name, object())
    if not hasattr(ms, "CoordinateSystem"):
        class _CS:
            def __init__(self, wkt=""):
                self.wkt = wkt
        ms.CoordinateSystem = _CS
    if not hasattr(ms, "Matrix"):
        class _Matrix:
            def __init__(self, rows):
                self._d = [list(r) for r in rows]
            def __getitem__(self, ij):
                i, j = ij
                return self._d[i][j]
        ms.Matrix = _Matrix
        ms.Matrix.Diag = staticmethod(lambda v: _Matrix(
            [[v[i] if i == j else 0.0 for j in range(len(v))] for i in range(len(v))]))
    if not hasattr(ms, "Vector"):
        class _Vec:
            def __init__(self, v):
                self.x, self.y, self.z = float(v[0]), float(v[1]), float(v[2])
        ms.Vector = _Vec
    spec = importlib.util.spec_from_file_location(
        "run_pipeline_level_under_test", Path(__file__).with_name("run_pipeline.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


rp = _load_run_pipeline()


# --------------------------------------------------------------------------- #
# Helpers to build synthetic marker positions and camera boresights
# --------------------------------------------------------------------------- #

def _unit(v: list[float]) -> list[float]:
    L = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / L for x in v]


def _rot_x(deg: float, v: list[float]) -> list[float]:
    """Rotate v around the X axis by deg degrees."""
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return [v[0], c * v[1] - s * v[2], s * v[1] + c * v[2]]


def _make_grid_markers(nx: int = 3, ny: int = 3,
                       dx: float = 3.0, dy: float = 3.0,
                       z_noise: float = 0.02) -> list[list[float]]:
    """Markers on an nx×ny grid in XY with tiny Z noise — well-spread plane."""
    pts = []
    for i in range(nx):
        for j in range(ny):
            pts.append([i * dx, j * dy, z_noise * (i - nx // 2)])
    return pts


def _make_collinear_markers(n: int = 8,
                             length: float = 6.0) -> list[list[float]]:
    """Markers nearly on a single line (along X axis) with tiny cross scatter."""
    pts = []
    for i in range(n):
        t = i / max(n - 1, 1)
        pts.append([t * length, 0.08 * math.sin(i), 0.05 * (i - n // 2)])
    return pts


def _nadir_boresights(n: int = 200,
                      tilt_deg: float = 0.0) -> list[list[float]]:
    """Camera boresights pointing straight down (0,0,-1) with optional tilt.

    tilt_deg>0 rotates boresights around X so they no longer point straight down.
    """
    b = _unit([0.0, math.sin(math.radians(tilt_deg)), -math.cos(math.radians(tilt_deg))])
    return [b] * n


# --------------------------------------------------------------------------- #
# (a) Near-collinear markers → camera-nadir UP
# --------------------------------------------------------------------------- #

def test_collinear_markers_use_camera_nadir():
    """Markers in a near-line layout (T1-like) must trigger the collinear guard
    and return method='camera_nadir' — the marker plane is ill-defined for roll."""
    mk = _make_collinear_markers(n=8, length=6.0)
    # Camera boresights straight down (0,0,-1): cameras physically nadir
    bs = _nadir_boresights(n=200, tilt_deg=0.0)

    up_vec, method, info = rp._compute_level_up(mk, bs)

    assert info["collinear_guard_fired"] is True, (
        f"collinear guard did not fire; spread_ratio={info['spread_ratio']:.4f}")
    assert method == "camera_nadir", (
        f"expected camera_nadir for collinear markers, got {method!r}")
    # The UP vector must be close to (0,0,1) — nadir cameras agree physical up = +Z
    z_component = up_vec[2]
    assert z_component > 0.9, (
        f"camera_nadir UP should be close to (0,0,1); up_vec={up_vec}")


def test_collinear_spread_ratio_below_threshold():
    """The spread_ratio for near-collinear markers must be below the threshold."""
    mk = _make_collinear_markers(n=8, length=6.0)
    bs = _nadir_boresights(n=50)

    _, _, info = rp._compute_level_up(mk, bs)

    assert info["spread_ratio"] < rp.LEVEL_COLLINEAR_THRESHOLD, (
        f"expected spread_ratio < {rp.LEVEL_COLLINEAR_THRESHOLD}, "
        f"got {info['spread_ratio']:.4f}")


# --------------------------------------------------------------------------- #
# (b) Well-spread markers → marker-plane normal OK
# --------------------------------------------------------------------------- #

def test_wellspread_markers_use_marker_plane():
    """Markers on a grid (well-spread) with nadir cameras agreeing: use marker plane."""
    mk = _make_grid_markers(nx=3, ny=3, dx=3.0, dy=3.0, z_noise=0.02)
    bs = _nadir_boresights(n=200, tilt_deg=0.0)

    up_vec, method, info = rp._compute_level_up(mk, bs)

    assert method == "marker_plane", (
        f"expected marker_plane for well-spread markers, got {method!r}")
    assert info["collinear_guard_fired"] is False
    assert info["nadir_guard_fired"] is False


def test_wellspread_spread_ratio_above_threshold():
    """Well-spread markers must have spread_ratio above the collinearity threshold."""
    mk = _make_grid_markers(nx=4, ny=2, dx=2.5, dy=4.0, z_noise=0.01)
    bs = _nadir_boresights(n=50)

    _, _, info = rp._compute_level_up(mk, bs)

    assert info["spread_ratio"] >= rp.LEVEL_COLLINEAR_THRESHOLD, (
        f"well-spread markers should have spread_ratio >= {rp.LEVEL_COLLINEAR_THRESHOLD}, "
        f"got {info['spread_ratio']:.4f}")


def test_wellspread_nadir_angle_below_guard():
    """Well-spread markers with nadir cameras should have tiny angle disagreement."""
    mk = _make_grid_markers(nx=3, ny=3, dx=3.0, dy=3.0, z_noise=0.01)
    bs = _nadir_boresights(n=100, tilt_deg=0.0)

    _, _, info = rp._compute_level_up(mk, bs)

    assert info["nadir_angle_deg"] < rp.LEVEL_NADIR_GUARD_DEG, (
        f"nadir_angle_deg={info['nadir_angle_deg']:.2f}° should be < "
        f"{rp.LEVEL_NADIR_GUARD_DEG}° for well-spread+nadir cameras")


# --------------------------------------------------------------------------- #
# (c) Disagreement > ~15° → nadir_guard_fired, escalation, NOT silent
# --------------------------------------------------------------------------- #

def test_disagreement_fires_nadir_guard():
    """When well-spread markers and cameras disagree by >15°, nadir_guard fires.

    The caller (stage_level) must alarm on this — it is NOT silently swallowed.
    """
    mk = _make_grid_markers(nx=3, ny=3, dx=3.0, dy=3.0, z_noise=0.01)
    # Cameras tilted 30° from nadir: boresight 30° from (0,0,-1) → 30° from flat
    bs = _nadir_boresights(n=200, tilt_deg=30.0)

    up_vec, method, info = rp._compute_level_up(mk, bs)

    assert info["nadir_guard_fired"] is True, (
        f"nadir_guard should fire for 30° camera tilt; "
        f"nadir_angle_deg={info['nadir_angle_deg']:.2f}°")
    assert method == "camera_nadir", (
        f"fallback to camera_nadir expected on nadir_guard; got {method!r}")
    # collinear guard must NOT be the trigger (markers are well-spread)
    assert info["collinear_guard_fired"] is False, (
        "collinear guard should not fire for well-spread markers")


def test_disagreement_angle_exceeds_threshold():
    """The reported nadir_angle_deg must exceed LEVEL_NADIR_GUARD_DEG."""
    mk = _make_grid_markers(nx=3, ny=3, dx=3.0, dy=3.0, z_noise=0.01)
    bs = _nadir_boresights(n=100, tilt_deg=30.0)

    _, _, info = rp._compute_level_up(mk, bs)

    assert info["nadir_angle_deg"] > rp.LEVEL_NADIR_GUARD_DEG, (
        f"nadir_angle_deg={info['nadir_angle_deg']:.2f}° should exceed "
        f"{rp.LEVEL_NADIR_GUARD_DEG}°")


def test_small_disagreement_does_not_fire_nadir_guard():
    """A small tilt (< guard) on well-spread markers must NOT fire the nadir guard."""
    mk = _make_grid_markers(nx=3, ny=3, dx=3.0, dy=3.0, z_noise=0.01)
    # 5° tilt is within guard tolerance
    bs = _nadir_boresights(n=100, tilt_deg=5.0)

    _, method, info = rp._compute_level_up(mk, bs)

    assert info["nadir_guard_fired"] is False, (
        f"nadir_guard should not fire for 5° tilt; "
        f"nadir_angle_deg={info['nadir_angle_deg']:.2f}°")
    assert method == "marker_plane"


# --------------------------------------------------------------------------- #
# Return-value contracts (always)
# --------------------------------------------------------------------------- #

def test_up_vec_is_unit():
    """_compute_level_up must always return a unit vector."""
    for mk, bs in [
        (_make_collinear_markers(), _nadir_boresights()),
        (_make_grid_markers(), _nadir_boresights()),
        (_make_grid_markers(), _nadir_boresights(tilt_deg=30.0)),
    ]:
        up_vec, _, _ = rp._compute_level_up(mk, bs)
        L = math.sqrt(sum(x * x for x in up_vec))
        assert abs(L - 1.0) < 1e-9, f"up_vec not unit (|L|={L:.6f})"


def test_method_is_valid_string():
    """method must be one of the two known strings."""
    for mk, bs in [
        (_make_collinear_markers(), _nadir_boresights()),
        (_make_grid_markers(), _nadir_boresights()),
    ]:
        _, method, _ = rp._compute_level_up(mk, bs)
        assert method in ("camera_nadir", "marker_plane"), (
            f"unexpected method value {method!r}")


def test_info_contains_required_keys():
    """info dict must contain all diagnostic keys."""
    required = {
        "spread_ratio", "nadir_angle_deg",
        "collinear_guard_fired", "nadir_guard_fired",
        "marker_normal", "cam_up", "eig",
    }
    mk = _make_grid_markers()
    bs = _nadir_boresights()
    _, _, info = rp._compute_level_up(mk, bs)
    missing = required - set(info.keys())
    assert not missing, f"info missing keys: {missing}"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
