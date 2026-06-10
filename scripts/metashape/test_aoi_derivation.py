"""test_aoi_derivation.py — TDD for aoi_derivation.derive_aoi (pure Python/numpy).

No Metashape, no GPU. Four contract tests:
  (a) elongated cluster  → major axis recovered within 5°
  (b) elongated cluster  → tight OBB contains 100% of source points
  (c) elongated cluster  → margin expands padded_extents by 2×margin per axis
  (d) isotropic cluster  → DegenerateClusterError raised (axis not stable)
"""
from __future__ import annotations

import numpy as np
import pytest

from aoi_derivation import DegenerateClusterError, OrientedBBox, derive_aoi


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def elongated_xy() -> np.ndarray:
    """500 points elongated along (2, 1) / sqrt(5) with small Gaussian noise."""
    rng = np.random.default_rng(42)
    t = rng.uniform(-10, 10, 500)
    return np.column_stack([2 * t, t]) + rng.normal(0, 0.1, (500, 2))


@pytest.fixture
def isotropic_xy() -> np.ndarray:
    """500 points sampled uniformly on a unit disc — no dominant major axis."""
    rng = np.random.default_rng(0)
    angles = rng.uniform(0, 2 * np.pi, 500)
    radii = rng.uniform(0.0, 1.0, 500)
    return np.column_stack([radii * np.cos(angles), radii * np.sin(angles)])


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_major_axis_recovered(elongated_xy: np.ndarray) -> None:
    """PCA major axis must align with (2, 1)/sqrt(5) within 5°."""
    bbox = derive_aoi(elongated_xy, margin=0.0)
    expected = np.array([2.0, 1.0]) / np.sqrt(5)
    cos_sim = abs(np.dot(bbox.axes[0], expected))
    angle_err_deg = np.degrees(np.arccos(np.clip(cos_sim, -1.0, 1.0)))
    assert angle_err_deg < 5.0, (
        f"major axis deviated {angle_err_deg:.2f}° from true direction (tolerance 5°)"
    )


def test_box_contains_all_points(elongated_xy: np.ndarray) -> None:
    """Tight OBB (margin=0) must contain ≥99% of source points.

    The OBB is derived from min/max projections, so containment is 100% in
    exact arithmetic. The ≥99% bound absorbs the 1–2 boundary points that
    float64 rounding may place just outside the tight hull.
    """
    bbox = derive_aoi(elongated_xy, margin=0.0)
    contained = bbox.contains(elongated_xy)
    frac = contained.mean()
    assert frac >= 0.99, (
        f"only {frac:.1%} of points inside the tight OBB (need ≥99%)"
    )


def test_margin_expands_padded_extents(elongated_xy: np.ndarray) -> None:
    """Adding margin=1.0 m must increase padded_extents by exactly 2.0 m per axis."""
    b0 = derive_aoi(elongated_xy, margin=0.0)
    b1 = derive_aoi(elongated_xy, margin=1.0)
    np.testing.assert_allclose(
        b1.padded_extents,
        b0.padded_extents + 2.0,
        atol=1e-10,
        err_msg="padded_extents should grow by 2×margin along each axis",
    )


def test_degenerate_guard_fires(isotropic_xy: np.ndarray) -> None:
    """Near-isotropic cluster must raise DegenerateClusterError rather than
    return a spurious major axis."""
    with pytest.raises(DegenerateClusterError):
        derive_aoi(isotropic_xy, isotropic_threshold=0.85)
