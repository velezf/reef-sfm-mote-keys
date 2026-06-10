"""aoi_derivation.py — PCA-based oriented bounding box for AOI derivation.

Input: dense-cloud XY coordinates (metres).
Output: OrientedBBox aligned to the major axis of the point cloud.

The box is used to crop the dense cloud before DSM/ortho — the uncropped
T1 region (28.9 × 25.4 m @ 0.001 m) would produce ~734 M cells and OOM.
Call dsm_preflight.check_dsm_size() after deriving the AOI to arm that
tripwire before any buildDem call.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


class DegenerateClusterError(Exception):
    """Raised when the XY cloud has no stable major axis.

    Triggered when the minor/major eigenvalue ratio exceeds
    ``isotropic_threshold``, meaning the cluster is too isotropic for PCA to
    identify a meaningful alignment direction.
    """


@dataclass
class OrientedBBox:
    """Axis-aligned bounding box in the PCA frame of a 2-D point cloud.

    Attributes
    ----------
    center       : world-space OBB centre, shape (2,)
    axes         : shape (2, 2) — rows are [major_axis, minor_axis] unit vectors
    half_extents : shape (2,) — tight half-widths in metres (no margin)
    margin       : padding added to all sides in metres
    """

    center: np.ndarray
    axes: np.ndarray
    half_extents: np.ndarray
    margin: float

    @property
    def padded_extents(self) -> np.ndarray:
        """Full width/height including margin: 2 × (half_extents + margin)."""
        return 2.0 * (self.half_extents + self.margin)

    def contains(self, xy: np.ndarray) -> np.ndarray:
        """Boolean mask (N,): True for each point inside the padded box.

        Projects each point into the OBB frame and checks that every axis
        projection is within [-half_extents[j] - margin, +half_extents[j] + margin].
        """
        proj = (xy - self.center) @ self.axes.T  # (N, 2)
        return np.all(np.abs(proj) <= self.half_extents + self.margin, axis=1)


def derive_aoi(
    xy: np.ndarray,
    margin: float = 0.75,
    isotropic_threshold: float = 0.85,
) -> OrientedBBox:
    """PCA on XY coordinates → oriented bounding box aligned to the major axis.

    Parameters
    ----------
    xy : (N, 2) float array — XY point cloud in metres
    margin : float — padding added to every side of the tight hull (metres)
    isotropic_threshold : float — minor/major eigenvalue ratio above which the
        cluster is considered too isotropic for stable axis recovery.
        ``DegenerateClusterError`` is raised rather than returning a spurious axis.

    Returns
    -------
    OrientedBBox with centre, axes, half-extents, and margin set.

    Raises
    ------
    ValueError — fewer than 2 points
    DegenerateClusterError — all points coincident, or cluster too isotropic
    """
    xy = np.asarray(xy, dtype=float)
    if len(xy) < 2:
        raise ValueError("need at least 2 points")

    centroid = xy.mean(axis=0)
    xy_c = xy - centroid

    cov = (xy_c.T @ xy_c) / len(xy_c)
    eigenvalues, eigenvectors = np.linalg.eigh(cov)

    # eigh returns ascending order; reverse so major axis is first
    eigenvalues = eigenvalues[::-1].copy()
    eigenvectors = eigenvectors[:, ::-1].copy()

    if eigenvalues[0] <= 1e-12:
        raise DegenerateClusterError("all points are nearly coincident")

    ratio = eigenvalues[1] / eigenvalues[0]
    if ratio > isotropic_threshold:
        raise DegenerateClusterError(
            f"cluster too isotropic (minor/major eigenvalue ratio {ratio:.3f} "
            f"> threshold {isotropic_threshold}); major axis is not stable"
        )

    # Project centered points into the PCA frame
    # proj[:, j] = projection of each point onto eigenvectors[:, j]
    proj = xy_c @ eigenvectors  # (N, 2)

    # Tight bounding box in projection space
    proj_min = proj.min(axis=0)  # (2,)
    proj_max = proj.max(axis=0)  # (2,)
    half_extents = (proj_max - proj_min) / 2.0
    proj_box_center = (proj_min + proj_max) / 2.0

    # OBB centre in world space — may differ from centroid for skewed clouds
    # eigenvectors @ proj_box_center reconstructs the world-space offset
    # (eigenvectors is orthogonal: col j = eigenvector j)
    world_center = centroid + eigenvectors @ proj_box_center

    return OrientedBBox(
        center=world_center,
        axes=eigenvectors.T,    # rows = [major, minor] unit vectors
        half_extents=half_extents,
        margin=margin,
    )
