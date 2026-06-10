"""dsm_preflight.py — DSM raster-size sanity check.

Computes the projected cell count for a DSM build and raises DSMSizeError if
it exceeds a configurable ceiling.

The ceiling is a resource tripwire to catch forgot-to-crop scenarios, NOT an
OOM guarantee. The canonical case: the uncropped T1 region (28.9 × 25.4 m)
at 0.001 m resolution → 28900 × 25400 = 733,860,000 cells. The real OOM
class (WGS84 geographic-plane reprojection) is already fixed separately.

Call this before any buildDem invocation. If it raises, crop the AOI first
via aoi_derivation.derive_aoi, then re-check with the cropped extents.
"""
from __future__ import annotations


class DSMSizeError(Exception):
    """Raised when a projected DSM would exceed the cell-count ceiling."""


def check_dsm_size(
    width_m: float,
    height_m: float,
    resolution_m: float,
    cell_ceiling: int = 100_000_000,
) -> int:
    """Compute raster cell count for a DSM build; raise if above ceiling.

    Parameters
    ----------
    width_m : AOI width in metres
    height_m : AOI height in metres
    resolution_m : DSM ground sample distance in metres
    cell_ceiling : maximum allowed cell count (default 100 M).
        Document this as a tripwire, not an OOM guarantee.

    Returns
    -------
    int — total cell count (n_cols × n_rows) when under ceiling

    Raises
    ------
    DSMSizeError — when cell count exceeds ceiling
    """
    n_cols = int(width_m / resolution_m)
    n_rows = int(height_m / resolution_m)
    total = n_cols * n_rows
    if total > cell_ceiling:
        raise DSMSizeError(
            f"DSM cell count {total:,} exceeds ceiling {cell_ceiling:,} "
            f"({width_m} m × {height_m} m @ {resolution_m} m/px → "
            f"{n_cols} cols × {n_rows} rows). Crop the AOI before buildDem."
        )
    return total
