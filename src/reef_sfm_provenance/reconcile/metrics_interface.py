"""Typed interface layer over the metric core.

The numerical implementations live in ``reconcile/metrics.py`` (validated against
published DSMs). This module is the typed surface: each function returns a
:class:`~reef_sfm_provenance.models.Metric` with provenance attributes filled in,
and the dispatch table (:data:`COMPUTERS`) lets the reconciler request metrics by
name uniformly.

The :data:`REPRODUCIBILITY` dict documents which metrics can be reproduced from
a gridded DSM at Toth's 1 cm resolution, and at what fidelity.

References
----------
Toth et al. 2025 (ESM Fig. S5) — metric definitions and 1 cm reporting resolution.
Du Preez 2015 — surface-area-to-planar-area rugosity (3D/2D).
Sappington et al. 2007 — vector ruggedness measure (VRM).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from reef_sfm_provenance.models import Metric, ReproducibilityStatus

logger = logging.getLogger(__name__)

#: Reproducibility status for each Toth Fig. S5 metric from a gridded DSM.
REPRODUCIBILITY: dict[str, ReproducibilityStatus] = {
    "rugosity": ReproducibilityStatus.REPRODUCED,
    "mean_elevation": ReproducibilityStatus.REPRODUCED,
    # VRM: Sappington Python implementation reads ~+13% vs MultiscaleDTM (ADR-0030).
    "vrm": ReproducibilityStatus.APPROXIMATELY_REPRODUCED,
    # SAPA/RIE/ASD: MultiscaleDTM-specific; not reimplemented to avoid silent divergence.
    "sapa": ReproducibilityStatus.APPROXIMATELY_REPRODUCED,
    "rie": ReproducibilityStatus.APPROXIMATELY_REPRODUCED,
    "asd": ReproducibilityStatus.APPROXIMATELY_REPRODUCED,
    "fractal_dimension": ReproducibilityStatus.NOT_ATTEMPTED,
}

#: Default focal window from Toth et al. 2025: 5 × 5 cm.
DEFAULT_WINDOW_M = 0.05


def _read_dsm(path: str | Path):
    try:
        import numpy as np
        import rasterio
    except ImportError as exc:
        raise RuntimeError(
            "rugosity/VRM/mean_elevation require numpy and rasterio; install the "
            "[metrics] extra."
        ) from exc
    with rasterio.open(path) as ds:
        arr = ds.read(1, masked=True)
        xres, _ = ds.res
    return arr, float(xres)


def rugosity(dsm_path: str | Path) -> Metric:
    """Surface rugosity (3D/2D area ratio) wired to the validated metric core."""
    from reef_sfm_provenance.reconcile.metrics import (
        rugosity as _core,
        TOTH_CELL_SIZE_M,
    )
    arr, cell = _read_dsm(dsm_path)
    import numpy as np

    filled = np.ma.filled(arr.astype("float64"), np.nan)
    value = _core(filled, cell)
    return Metric(
        name="rugosity",
        value=value,
        unit="dimensionless",
        implementation="python-du-preez-2015",
        source="ours",
    )


def vrm(dsm_path: str | Path, window_m: float = DEFAULT_WINDOW_M) -> Metric:
    """VRM (Sappington et al. 2007) wired to the validated metric core.

    NOTE: a python/Sappington implementation reads ~+13% vs the MultiscaleDTM
    implementation Toth used (ADR-0030). The ``implementation`` field records this
    so the offset is auditable, not hidden.
    """
    from reef_sfm_provenance.reconcile.metrics import (
        vrm as _core,
        TOTH_CELL_SIZE_M,
    )
    arr, cell = _read_dsm(dsm_path)
    import numpy as np

    filled = np.ma.filled(arr.astype("float64"), np.nan)
    value = _core(filled, cell, window=window_m)
    return Metric(
        name="vrm",
        value=value,
        unit="dimensionless",
        window_m=window_m,
        implementation="python-sappington-2007",
        source="ours",
    )


def mean_elevation(dsm_path: str | Path) -> Metric:
    """Standardized mean elevation (mean − min) wired to the validated metric core."""
    from reef_sfm_provenance.reconcile.metrics import mean_elevation_standardized as _core

    arr, _cell = _read_dsm(dsm_path)
    import numpy as np

    filled = np.ma.filled(arr.astype("float64"), np.nan)
    value = _core(filled)
    return Metric(
        name="mean_elevation",
        value=value,
        unit="m",
        implementation="python-standardized",
        source="ours",
    )


COMPUTERS: dict[str, Callable[..., Metric]] = {
    "rugosity": rugosity,
    "vrm": vrm,
    "mean_elevation": mean_elevation,
}
