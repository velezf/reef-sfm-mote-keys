"""Pure-Python terrain metrics for DSM reconciliation.

Implements the subset of Toth et al. 2025's reported transect metrics
(Fig. S5 definitions) that can be recomputed exactly from a gridded DSM
without R/MultiscaleDTM:

  * surface rugosity (SAPA-family 3D/2D area ratio; Du Preez 2015)
  * standardized mean elevation (mean − min, metres)
  * vector ruggedness measure (VRM; Sappington et al. 2007)

The MultiscaleDTM-specific metrics Toth reports (SAPA with planar detrending,
RIE, ASD) are declared here as explicit `NotImplementedError` stubs rather
than approximations — see `sapa`, `rie`, `asd`.

Every function takes the DSM as a 2D numpy array of elevations in metres
plus the grid cell size in metres. No file I/O happens in this module; NaN
cells are treated as nodata throughout.

References
----------
Toth et al. 2025 (ESM Fig. S5) — metric definitions and the 1 cm DSM
resolution all reported values are computed at.
Du Preez, C. 2015. "A new arc–chord ratio (ACR) rugosity index for
quantifying three-dimensional landscape structural complexity."
Landscape Ecology 30:181–192 — surface-area-to-planar-area rugosity.
Sappington, J.M., K.M. Longshore, D.B. Thompson. 2007. "Quantifying
landscape ruggedness for animal habitat analysis." J. Wildlife
Management 71(5):1419–1426 — VRM = 1 − |resultant vector| / n.
"""

from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

__all__ = [
    "asd",
    "mean_elevation_standardized",
    "resample_to_cm",
    "rie",
    "rugosity",
    "sapa",
    "vrm",
]

#: Toth et al. 2025 compute all transect metrics on 1 cm DSMs (ESM Fig. S5).
TOTH_CELL_SIZE_M = 0.01


def _validate_dsm(dsm: np.ndarray, cell_size: float, min_dim: int = 2) -> np.ndarray:
    dsm = np.asarray(dsm, dtype=float)
    if dsm.ndim != 2:
        raise ValueError(f"DSM must be 2D, got ndim={dsm.ndim}")
    if min(dsm.shape) < min_dim:
        raise ValueError(f"DSM must be at least {min_dim}x{min_dim}, got {dsm.shape}")
    if not cell_size > 0:
        raise ValueError(f"cell_size must be > 0 m, got {cell_size}")
    return dsm


def rugosity(dsm: np.ndarray, cell_size: float) -> float:
    """Surface rugosity: triangulated 3D surface area / 2D planar area.

    Each grid quad is split into two triangles on its diagonal and the 3D
    triangle areas are summed; the planar denominator is the footprint of
    the same (NaN-free) quads. A flat surface gives exactly 1.0; a plane
    tilted at angle θ gives sec(θ). This is the undetrended 3D/2D area
    ratio of Du Preez 2015 (SAPA family) as reported in Toth et al. 2025
    Fig. S5.

    Quads touching a NaN corner are excluded from both numerator and
    denominator.
    """
    dsm = _validate_dsm(dsm, cell_size)
    h = float(cell_size)

    z00 = dsm[:-1, :-1]
    z01 = dsm[:-1, 1:]
    z10 = dsm[1:, :-1]
    z11 = dsm[1:, 1:]

    valid = np.isfinite(z00) & np.isfinite(z01) & np.isfinite(z10) & np.isfinite(z11)
    if not valid.any():
        raise ValueError("DSM has no NaN-free 2x2 quad; rugosity undefined")

    # Triangle (z00, z01, z10): legs along +x and +y from the z00 corner.
    # area = h/2 * sqrt(dz_x^2 + dz_y^2 + h^2); flat -> h^2/2 per triangle.
    area_lower = 0.5 * h * np.sqrt((z01 - z00) ** 2 + (z10 - z00) ** 2 + h * h)
    # Triangle (z01, z11, z10): legs along -x and -y from the z11 corner.
    area_upper = 0.5 * h * np.sqrt((z11 - z10) ** 2 + (z11 - z01) ** 2 + h * h)

    surface_3d = float(np.sum((area_lower + area_upper)[valid]))
    planar_2d = float(np.count_nonzero(valid)) * h * h
    return surface_3d / planar_2d


def mean_elevation_standardized(dsm: np.ndarray) -> float:
    """Standardized mean elevation: mean(z) − min(z), in metres.

    Toth et al. 2025 (ESM Fig. S5) report transect elevation standardized
    to the DSM minimum, which removes the arbitrary vertical datum of a
    LOCAL_CS chunk. NaN cells are ignored.
    """
    dsm = np.asarray(dsm, dtype=float)
    finite = dsm[np.isfinite(dsm)]
    if finite.size == 0:
        raise ValueError("DSM has no finite cells; elevation undefined")
    return float(finite.mean() - finite.min())


def vrm(dsm: np.ndarray, cell_size: float, window: float = 0.05) -> float:
    """Vector ruggedness measure (Sappington et al. 2007), DSM-mean scalar.

    Per cell, the unit surface normal is decomposed into (x, y, z); within
    each focal window the normals are summed and the local ruggedness is
    ``1 − |resultant| / n``. A flat plane and a constant-slope plane both
    score 0 (all normals parallel — VRM is slope-invariant by construction);
    1 is maximal dispersion. The returned value is the mean over all focal
    windows, matching the transect-level VRM reported in Toth et al. 2025
    Fig. S5.

    `window` is the focal window side in metres (default 0.05 m = 5×5 cells
    on a 1 cm DSM). It must resolve to an odd cell count ≥ 3; resample with
    `resample_to_cm` first if it doesn't.
    """
    dsm = _validate_dsm(dsm, cell_size)
    n_cells = int(round(window / cell_size))
    if n_cells < 3 or n_cells % 2 == 0:
        raise ValueError(
            f"window {window} m / cell_size {cell_size} m -> {n_cells} cells; "
            "need an odd count >= 3 (resample_to_cm first)"
        )
    if min(dsm.shape) < n_cells:
        raise ValueError(f"DSM {dsm.shape} smaller than {n_cells}x{n_cells} focal window")

    dzdy, dzdx = np.gradient(dsm, cell_size)
    norm = np.sqrt(dzdx**2 + dzdy**2 + 1.0)
    nx, ny, nz = -dzdx / norm, -dzdy / norm, 1.0 / norm

    finite = np.isfinite(nx) & np.isfinite(ny) & np.isfinite(nz)
    nx = np.where(finite, nx, 0.0)
    ny = np.where(finite, ny, 0.0)
    nz = np.where(finite, nz, 0.0)

    win = (n_cells, n_cells)
    sum_x = sliding_window_view(nx, win).sum(axis=(2, 3))
    sum_y = sliding_window_view(ny, win).sum(axis=(2, 3))
    sum_z = sliding_window_view(nz, win).sum(axis=(2, 3))
    count = sliding_window_view(finite, win).sum(axis=(2, 3))

    has_data = count > 0
    if not has_data.any():
        raise ValueError("DSM has no finite cells; VRM undefined")
    resultant = np.sqrt(sum_x**2 + sum_y**2 + sum_z**2)
    local_vrm = 1.0 - resultant[has_data] / count[has_data]
    return float(local_vrm.mean())


def resample_to_cm(
    dsm: np.ndarray, cell_size: float, target: float = TOTH_CELL_SIZE_M
) -> tuple[np.ndarray, float]:
    """Block-mean aggregate a DSM to the Toth reporting resolution (1 cm).

    Toth et al. 2025 compute every Fig. S5 metric on 1 cm DSMs; comparing
    against them at a finer grid would inflate rugosity/VRM, so DSMs are
    aggregated to `target` before any metric runs. Returns
    ``(resampled_dsm, target)``.

    `target` must be an integer multiple of `cell_size` (block aggregation
    only — no interpolation); a coarser-than-target input is rejected rather
    than upsampled. Trailing rows/columns that don't fill a block are
    trimmed. Blocks average their finite cells; all-NaN blocks stay NaN.
    """
    dsm = _validate_dsm(dsm, cell_size)
    if not target > 0:
        raise ValueError(f"target must be > 0 m, got {target}")
    if np.isclose(cell_size, target):
        return dsm, float(target)
    if cell_size > target:
        raise ValueError(
            f"cell_size {cell_size} m is coarser than target {target} m; "
            "upsampling would fabricate detail"
        )
    factor_f = target / cell_size
    factor = int(round(factor_f))
    if not np.isclose(factor_f, factor):
        raise ValueError(
            f"target {target} m is not an integer multiple of cell_size "
            f"{cell_size} m (factor {factor_f:.4f})"
        )

    rows = (dsm.shape[0] // factor) * factor
    cols = (dsm.shape[1] // factor) * factor
    if rows == 0 or cols == 0:
        raise ValueError(f"DSM {dsm.shape} smaller than one {factor}x{factor} block")
    blocks = dsm[:rows, :cols].reshape(rows // factor, factor, cols // factor, factor)

    finite = np.isfinite(blocks)
    sums = np.where(finite, blocks, 0.0).sum(axis=(1, 3))
    counts = finite.sum(axis=(1, 3))
    out = np.divide(sums, counts, out=np.full(sums.shape, np.nan), where=counts > 0)
    return out, float(target)


def _multiscaledtm_stub(name: str, detail: str) -> NotImplementedError:
    return NotImplementedError(
        f"{name} is MultiscaleDTM-specific ({detail}); Toth et al. 2025 compute "
        "it with the R MultiscaleDTM package. Reproduce via rpy2 or a verified "
        "reimplementation in a later branch — do not approximate."
    )


def sapa(dsm: np.ndarray, cell_size: float, **kwargs: object) -> float:
    """SAPA with planar detrending (Du Preez 2015 / MultiscaleDTM ``SAPA``).

    Differs from `rugosity` by detrending against the fitted plane; not
    implemented here to avoid silently diverging from MultiscaleDTM's exact
    algorithm.
    """
    raise _multiscaledtm_stub("SAPA", "slope-corrected arc-chord ratio")


def rie(dsm: np.ndarray, cell_size: float, **kwargs: object) -> float:
    """Roughness Index of Elevation (MultiscaleDTM ``RIE``)."""
    raise _multiscaledtm_stub("RIE", "focal elevation roughness index")


def asd(dsm: np.ndarray, cell_size: float, **kwargs: object) -> float:
    """Area-Scale Distribution / fractal-free complexity (MultiscaleDTM)."""
    raise _multiscaledtm_stub("ASD", "multi-scale area-distribution metric")
