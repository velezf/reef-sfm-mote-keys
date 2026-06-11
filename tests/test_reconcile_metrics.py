"""Tests for `reef_sfm_provenance.reconcile.metrics`.

Pure-Python reconciliation metrics exercised against analytic fixtures —
surfaces whose rugosity / VRM / standardized elevation have exact closed-form
answers. No real DSM is loaded anywhere in this module (the P13HMEON firewall
holds: comparison data enters only in the later reconciliation branch).

Analytic ground truths used here:

  flat horizontal plane      rugosity = 1            vrm = 0
  plane tilted 45° about y   rugosity = sec(45°) = √2  vrm = 0  (slope-invariance)
  any field                  mean_elevation_standardized = mean(z) − min(z)
  linear ramp                block-mean resampling preserves the slope exactly
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from reef_sfm_provenance.reconcile.metrics import (
    asd,
    mean_elevation_standardized,
    resample_to_cm,
    rie,
    rugosity,
    sapa,
    vrm,
)

TOL = 1e-9


# ---------------------------------------------------------------------------
# Fixtures: analytic surfaces
# ---------------------------------------------------------------------------


def flat_plane(nrows: int = 50, ncols: int = 80, z: float = -3.7) -> np.ndarray:
    return np.full((nrows, ncols), z, dtype=float)


def ramp_45deg(nrows: int = 50, ncols: int = 80, cell_size: float = 0.01) -> np.ndarray:
    """z = x: rises one cell_size per column → 45° tilt about the row axis."""
    _, xx = np.mgrid[0:nrows, 0:ncols]
    return xx * cell_size


# ---------------------------------------------------------------------------
# rugosity — 3D triangulated surface area / 2D planar area
# ---------------------------------------------------------------------------


def test_rugosity_flat_plane_is_one():
    assert rugosity(flat_plane(), cell_size=0.01) == pytest.approx(1.0, abs=TOL)


def test_rugosity_45deg_ramp_is_sqrt2():
    dsm = ramp_45deg(cell_size=0.01)
    assert rugosity(dsm, cell_size=0.01) == pytest.approx(math.sqrt(2.0), abs=TOL)


def test_rugosity_flat_plane_with_nan_hole_is_one():
    dsm = flat_plane()
    dsm[10:14, 20:25] = np.nan
    assert rugosity(dsm, cell_size=0.01) == pytest.approx(1.0, abs=TOL)


def test_rugosity_rough_surface_exceeds_one():
    # Egg-crate: definitely > 1, no exact closed form needed.
    yy, xx = np.mgrid[0:60, 0:90]
    dsm = 0.05 * np.sin(xx * 0.7) * np.cos(yy * 0.7)
    assert rugosity(dsm, cell_size=0.01) > 1.0 + 1e-3


def test_rugosity_rejects_degenerate_input():
    with pytest.raises(ValueError):
        rugosity(np.zeros((1, 5)), cell_size=0.01)
    with pytest.raises(ValueError):
        rugosity(np.zeros((4, 4)), cell_size=0.0)


# ---------------------------------------------------------------------------
# vrm — Sappington et al. 2007 vector ruggedness measure
# ---------------------------------------------------------------------------


def test_vrm_flat_plane_is_zero():
    assert vrm(flat_plane(), cell_size=0.01) == pytest.approx(0.0, abs=TOL)


def test_vrm_45deg_ramp_is_zero_slope_invariance():
    # All normals on a constant-slope plane are identical → resultant = n → VRM 0.
    dsm = ramp_45deg(cell_size=0.01)
    assert vrm(dsm, cell_size=0.01) == pytest.approx(0.0, abs=TOL)


def test_vrm_rough_surface_is_positive():
    yy, xx = np.mgrid[0:60, 0:90]
    dsm = 0.05 * np.sin(xx * 0.9) * np.cos(yy * 0.9)
    v = vrm(dsm, cell_size=0.01)
    assert 0.0 < v < 1.0


def test_vrm_window_too_small_for_dsm_raises():
    with pytest.raises(ValueError):
        vrm(flat_plane(nrows=3, ncols=3), cell_size=0.01, window=0.05)


# ---------------------------------------------------------------------------
# mean_elevation_standardized — mean(z) − min(z)
# ---------------------------------------------------------------------------


def test_mean_elevation_standardized_known_field():
    dsm = np.array([[0.0, 1.0], [2.0, 3.0]])
    assert mean_elevation_standardized(dsm) == pytest.approx(1.5, abs=TOL)


def test_mean_elevation_standardized_depth_offset_invariant():
    # Standardization kills the arbitrary LOCAL_CS Z offset.
    dsm = np.array([[0.0, 1.0], [2.0, 3.0]])
    assert mean_elevation_standardized(dsm - 6.477) == pytest.approx(1.5, abs=TOL)


def test_mean_elevation_standardized_ignores_nan():
    dsm = np.array([[0.0, 1.0], [2.0, np.nan]])
    assert mean_elevation_standardized(dsm) == pytest.approx(1.0, abs=TOL)


# ---------------------------------------------------------------------------
# resample_to_cm — aggregate to 1 cm to match Toth's reported resolution
# ---------------------------------------------------------------------------


def test_resample_to_cm_from_1mm_ramp_preserves_slope():
    # 1 mm cells, slope dz/dx = 1.0 (z rises 1 mm per 1 mm column).
    dsm = ramp_45deg(nrows=40, ncols=60, cell_size=0.001)
    out, out_cell = resample_to_cm(dsm, cell_size=0.001)
    assert out_cell == pytest.approx(0.01, abs=TOL)
    assert out.shape == (4, 6)
    # Slope across resampled columns must still be exactly 1.0 m/m.
    col_means = out.mean(axis=0)
    slopes = np.diff(col_means) / out_cell
    np.testing.assert_allclose(slopes, 1.0, atol=TOL)


def test_resample_to_cm_noop_when_already_target():
    dsm = flat_plane(nrows=10, ncols=10)
    out, out_cell = resample_to_cm(dsm, cell_size=0.01)
    assert out_cell == pytest.approx(0.01, abs=TOL)
    np.testing.assert_array_equal(out, dsm)


def test_resample_to_cm_rejects_non_integer_factor():
    with pytest.raises(ValueError):
        resample_to_cm(flat_plane(), cell_size=0.003)


def test_resample_to_cm_rejects_upsampling():
    with pytest.raises(ValueError):
        resample_to_cm(flat_plane(), cell_size=0.05)


# ---------------------------------------------------------------------------
# MultiscaleDTM-specific metrics — explicit stubs, not fakes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stub", [sapa, rie, asd])
def test_multiscaledtm_metrics_are_explicit_stubs(stub):
    with pytest.raises(NotImplementedError):
        stub(flat_plane(), cell_size=0.01)
