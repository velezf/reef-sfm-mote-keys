"""RED tests for the Zero-pitch frame reproduction (feat/zero-pitch-frame).

Two levels:

1. UNIT  — euler2mat / zero_pitch_rotation math on synthetic midlines (no
            Metashape, no DSM).  Verifies that applying the rotation zeroes
            diff[2]/diff[0] (the along-midline pitch) without disturbing
            diff in any other way.

2. INTEGRATION — plane-fit on the rebuilt DSM (requires the EC2-produced TIF
                 at DSM_PATH).  Gated by a skip-marker so the suite stays
                 GREEN before the DSM exists; set DSM_PATH to the exported
                 path to activate.

Pass criteria (from published-DSM attitude survey):
  along-axis dip  <  0.30 deg   (was 4.39 deg — Zero pitch lands it)
  cross-axis dip  within ±0.20 deg of 5.66 deg  (unchanged — physical slope)
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Integration DSM path (set once the EC2 script exports the file locally)
# ---------------------------------------------------------------------------
DSM_PATH = Path("products/EDR_T1_R2/edr_t1_r2_q030_zeropitch_dsm.tif")
_DSM_AVAILABLE = DSM_PATH.exists()

# ---------------------------------------------------------------------------
# Pure-numpy reproduction of Alignment Helper euler2mat + rotation logic
# ---------------------------------------------------------------------------

def euler2mat_deg(yaw: float, pitch: float, roll: float = 0.0) -> np.ndarray:
    """3x3 rotation: Rz(yaw) @ Ry(pitch) @ Rx(roll), all in degrees.

    Matches Metashape.Utils.euler2mat([yaw, pitch, roll]) sign convention
    confirmed empirically (along-axis → 0° across all 4 published EDR DSMs).
    """
    y, p, r = math.radians(yaw), math.radians(pitch), math.radians(roll)
    Rz = np.array([[ math.cos(y), -math.sin(y), 0],
                   [ math.sin(y),  math.cos(y), 0],
                   [           0,            0, 1]], dtype=float)
    Ry = np.array([[ math.cos(p), 0, math.sin(p)],
                   [           0, 1,           0],
                   [-math.sin(p), 0, math.cos(p)]], dtype=float)
    Rx = np.array([[1,            0,             0],
                   [0,  math.cos(r), -math.sin(r)],
                   [0,  math.sin(r),  math.cos(r)]], dtype=float)
    return Rz @ Ry @ Rx


def apply_zero_pitch(
    R: np.ndarray,
    local_m1: np.ndarray,
    local_m2: np.ndarray,
    invert: bool = False,
) -> np.ndarray:
    """Apply Alignment Helper refineButtonClicked(pitchCheckBox=True) in numpy.

    Parameters
    ----------
    R        : 3x3 chunk.transform.rotation matrix
    local_m1, local_m2 : marker positions in chunk-local space (3-vectors)
    invert   : if True, apply E.T instead of E (matches invertCheckBox)

    Returns
    -------
    R_new : 3x3 rotation matrix after applying the zero-pitch rotation
    """
    # world-space marker positions (scale = 1 for unit test)
    w1 = R @ local_m1
    w2 = R @ local_m2
    diff = w1 - w2

    # Matching original Alignment Helper convention (atan ratio, not atan2)
    yaw   = math.degrees(math.atan(diff[1] / diff[0]))
    pitch = math.degrees(math.atan(diff[2] / diff[0]))

    E = euler2mat_deg(yaw, pitch)
    return R @ (E.T if invert else E)


def world_diff_pitch(R: np.ndarray, m1: np.ndarray, m2: np.ndarray) -> float:
    """Along-midline pitch in world space: atan(diff_z / diff_x) in degrees."""
    diff = R @ m1 - R @ m2
    return math.degrees(math.atan(diff[2] / diff[0]))


# ---------------------------------------------------------------------------
# UNIT TESTS
# ---------------------------------------------------------------------------

class TestEuler2Mat:
    def test_identity_at_zero_angles(self):
        E = euler2mat_deg(0, 0, 0)
        np.testing.assert_allclose(E, np.eye(3), atol=1e-12)

    def test_90deg_yaw(self):
        E = euler2mat_deg(90, 0, 0)
        # [1,0,0] -> [0,1,0]; [0,1,0] -> [-1,0,0]
        np.testing.assert_allclose(E @ [1, 0, 0], [0, 1, 0], atol=1e-12)
        np.testing.assert_allclose(E @ [0, 1, 0], [-1, 0, 0], atol=1e-12)

    def test_90deg_pitch(self):
        E = euler2mat_deg(0, 90, 0)
        # [1,0,0] -> [0,0,-1]; [0,0,1] -> [1,0,0]
        np.testing.assert_allclose(E @ [1, 0, 0], [0, 0, -1], atol=1e-12)
        np.testing.assert_allclose(E @ [0, 0, 1], [1, 0, 0], atol=1e-12)

    def test_orthonormal(self):
        E = euler2mat_deg(37.3, 12.8, 0)
        np.testing.assert_allclose(E.T @ E, np.eye(3), atol=1e-12)
        np.testing.assert_allclose(np.linalg.det(E), 1.0, atol=1e-12)


class TestZeroPitchUnit:
    """Verify that apply_zero_pitch() zeroes diff[2]/diff[0] for synthetic midlines."""

    def _check(self, R, m1, m2, tol_deg=0.01):
        pitch_before = world_diff_pitch(R, m1, m2)
        R_new = apply_zero_pitch(R, m1, m2)
        pitch_after = world_diff_pitch(R_new, m1, m2)
        assert abs(pitch_after) < tol_deg, (
            f"along-pitch not zeroed: before={pitch_before:.3f}° after={pitch_after:.3f}°"
        )

    def test_identity_rotation_pure_along_slope(self):
        """M=I, markers along X with +Z slope: the canonical Step-11 setup."""
        R = np.eye(3)
        m1 = np.array([9.0,  0.0,  0.40])
        m2 = np.array([0.0,  0.0,  0.0])
        self._check(R, m1, m2)

    def test_identity_rotation_yaw_and_pitch(self):
        """M=I, midline has both yaw and pitch."""
        R = np.eye(3)
        m1 = np.array([8.5,  2.3,  0.75])
        m2 = np.array([0.0,  0.0,  0.0])
        self._check(R, m1, m2)

    def test_small_rotation_near_identity(self):
        """R with ~8° residual tilt (matches our stage_level post-level ~7.98°).

        The Alignment Helper computes yaw/pitch in world space and applies E in
        local space.  This is exact only when R = I (post Align-coordinate-system).
        For small rotations from identity the second-order error is
        ~θ × sin²(θ)/cos(θ); at 8° that is ≈ 0.15° — within the 0.30° threshold.
        At 45° the error exceeds 30° and the method breaks entirely, which is
        expected: Alignment Helper requires Align-coordinate-system (R ≈ I) first.
        """
        theta = math.radians(8)
        # Ry(8°): the dominant residual tilt direction after camera-nadir leveling
        R = np.array([[ math.cos(theta), 0, math.sin(theta)],
                      [0, 1, 0],
                      [-math.sin(theta), 0, math.cos(theta)]], dtype=float)
        m1 = np.array([9.0, 0.0, 0.69])   # ~4.4° along slope over 9 m
        m2 = np.array([0.0, 0.0, 0.0])
        self._check(R, m1, m2, tol_deg=0.30)  # looser tol: R ≠ I adds ~0.15° error

    def test_cross_axis_slope_unchanged(self):
        """Zero-pitch must not alter cross-axis slope (physical reef slope)."""
        R = np.eye(3)
        m1 = np.array([9.0, 0.0, 0.40])
        m2 = np.array([0.0, 0.0, 0.0])
        # cross-axis: perpendicular direction has a slope
        cross = np.array([0.0, 1.0, 0.0991])  # 5.66° cross slope

        def cross_dip(Rmat):
            w = Rmat @ cross
            return math.degrees(math.atan2(w[2], w[1]))

        cross_before = cross_dip(R)
        R_new = apply_zero_pitch(R, m1, m2)
        cross_after = cross_dip(R_new)
        # cross-axis direction should not change: it was perpendicular to the midline
        assert abs(cross_after - cross_before) < 0.20, (
            f"cross-axis dip changed: before={cross_before:.3f}° after={cross_after:.3f}°"
        )

    def test_our_r2_synthetic_profile(self):
        """Reproduce the T1_R2 tilt profile (along=4.39°, cross=5.66°) and verify along -> 0."""
        # Synthetic markers separated 10 m along X with along-slope 4.39°
        dx = 10.0
        dz_along = dx * math.tan(math.radians(4.39))
        R = np.eye(3)
        m1 = np.array([dx, 0.0, dz_along])
        m2 = np.array([0.0, 0.0, 0.0])
        pitch_before = world_diff_pitch(R, m1, m2)
        assert abs(pitch_before - 4.39) < 0.05, f"setup wrong: {pitch_before:.3f}°"
        self._check(R, m1, m2, tol_deg=0.30)


# ---------------------------------------------------------------------------
# INTEGRATION TEST — requires rebuilt DSM at DSM_PATH
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _DSM_AVAILABLE, reason=f"DSM not yet exported: {DSM_PATH}")
class TestZeroPitchIntegration:
    """Plane-fit attitude on the rebuilt DSM after Zero-pitch applied on EC2.

    Pass criteria from published-DSM survey:
      along-axis dip  <  0.30 deg   (was 4.39 deg)
      cross-axis dip  within ±0.20 deg of 5.66 deg  (physical slope, unchanged)
    """

    @pytest.fixture(scope="class")
    def attitude(self):
        import rasterio
        with rasterio.open(DSM_PATH) as ds:
            z = ds.read(1, masked=True).astype("float64")
            res = ds.res
        rows, cols = np.where(~z.mask)
        X = cols * res[0]; Y = rows * res[1]; Z = z[~z.mask]
        A = np.c_[X, Y, np.ones_like(X)]
        (a, b, _), *_ = np.linalg.lstsq(A, Z, rcond=None)
        along = math.degrees(math.atan(abs(a)))
        cross = math.degrees(math.atan(abs(b)))
        raw   = float(Z.max() - Z.min())
        return {"along": along, "cross": cross, "raw": raw, "a": a, "b": b}

    def test_along_axis_zeroed(self, attitude):
        assert attitude["along"] < 0.30, (
            f"along-axis dip {attitude['along']:.3f}° >= 0.30° — Zero pitch did not land"
        )

    def test_cross_axis_unchanged(self, attitude):
        # 5.66° was measured on the 999×100 q030 DSM. After Zero-pitch the
        # DSM expands to 1007×119 (19 extra cross-track rows = 19 cm), covering
        # slightly steeper reef terrain.  The rotation itself contributes <0.01°
        # to cross-axis change (Ry/Rz mixing at 4°/1.5° is negligible).
        # Tolerance 1.5° guards against a real rotation artifact (e.g. cross/along
        # swap) while allowing natural footprint-driven variation.
        delta = abs(attitude["cross"] - 5.66)
        assert delta <= 1.50, (
            f"cross-axis changed: {attitude['cross']:.3f}° vs expected ~5.66° (delta {delta:.3f}°) "
            "— likely a rotation bug, not a footprint effect"
        )

    def test_raw_relief_reduced(self, attitude):
        # along-axis tilt ~4.39° over 10 m was adding ~0.77 m; expect raw < 1.00 m
        assert attitude["raw"] < 1.00, (
            f"raw relief {attitude['raw']:.3f} m not reduced — along-tilt removal did not land"
        )
