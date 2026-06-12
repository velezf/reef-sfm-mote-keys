"""Reconciliation harness — DSM + published-table I/O around the ADR-0030 metrics.

Glues three things together:

  * `load_dsm`           read a GeoTIFF DSM to a (NaN-aware) numpy array at 1 cm
  * `load_reference_metrics`  read ONE row from the P13HMEON 94 KB values table,
                          keyed (site, subsite, transect_id, filter) — READ-ONLY,
                          never written, never fed back into the DSM path (firewall
                          `325dbc7`)
  * `compute_metrics` / `reconcile`  our-side metrics + a bundle-node-shaped report

The metric definitions live in `metrics.py` (ADR-0030) and are not duplicated
here. The pinned column mapping (ADR-0032): our `rugosity` ↔ `full_area_rugosity`
(whole-model 3D:2D), `mean_elevation` ↔ `stand_mean_elev` (mean − min), `vrm`
↔ `vrm_mean` (Sappington 5×5 cm). SAPA/RIE/ASD are Tier-2 (not computed here).
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict

from reef_sfm_provenance.reconcile.metrics import (
    TOTH_CELL_SIZE_M,
    mean_elevation_standardized,
    resample_to_cm,
    rugosity,
    vrm,
)

logger = logging.getLogger(__name__)

#: our-metric -> published column (ADR-0032 confirmed mapping)
METRIC_TO_PUBLISHED = {
    "rugosity": "full_area_rugosity",
    "vrm": "vrm_mean",
    "mean_elevation": "stand_mean_elev",
}

_VRM_NOTE = (
    "Our VRM is the Sappington et al. 2007 definition; the published vrm_mean "
    "is computed by R MultiscaleDTM. Identical definition, different "
    "implementation — small deltas on the same surface are expected from the "
    "implementation, not the data."
)
_RUGOSITY_NOTE = (
    "full_area_rugosity is the whole-model 3D:2D area ratio (Du Preez 2015), "
    "matching our rugosity. On a tilted reef surface both inflate with slope; "
    "the published value is undetrended too, so slope is not a delta source."
)


def load_dsm(path: str | Path, target_cell: float = TOTH_CELL_SIZE_M) -> tuple[np.ndarray, float]:
    """Read a single-band GeoTIFF DSM to ``(elevation_array, cell_size_m)``.

    Nodata becomes NaN. Square cells are required (DSMs here are local-planar
    1 cm grids). If the native grid is finer than `target_cell`, the array is
    block-mean resampled up to it (`resample_to_cm`) so every metric runs at
    Toth's reporting resolution.
    """
    import rasterio

    path = Path(path)
    with rasterio.open(path) as src:
        band = src.read(1, masked=True)
        dx, dy = abs(src.transform.a), abs(src.transform.e)
        nodata = src.nodata
    if not np.isclose(dx, dy, rtol=1e-3):
        raise ValueError(f"non-square cells in {path.name}: dx={dx}, dy={dy}")

    arr = np.ma.filled(band.astype("float64"), np.nan)
    if nodata is not None:
        arr = np.where(arr == nodata, np.nan, arr)
    cell = float(dx)

    if cell < target_cell and not np.isclose(cell, target_cell):
        arr, cell = resample_to_cm(arr, cell, target=target_cell)
        logger.info("load_dsm %s: resampled %.4f m -> %.4f m grid", path.name, dx, cell)

    finite = int(np.isfinite(arr).sum())
    logger.info("load_dsm %s: shape=%s cell=%.4f m finite_cells=%d", path.name, arr.shape, cell, finite)
    return arr, cell


def compute_metrics(dsm: np.ndarray, cell_size: float = TOTH_CELL_SIZE_M) -> dict[str, float]:
    """Our-side metrics (ADR-0030 Tier-1) on an in-memory DSM."""
    out = {
        "rugosity": rugosity(dsm, cell_size),
        "vrm": vrm(dsm, cell_size),
        "mean_elevation": mean_elevation_standardized(dsm),
    }
    logger.info("compute_metrics: rugosity=%.4f vrm=%.4f mean_elev=%.4f m",
                out["rugosity"], out["vrm"], out["mean_elevation"])
    return out


def load_reference_metrics(
    path: str | Path, site: str, subsite: str, transect_id: str, filter: str
) -> dict[str, Any]:
    """Read ONE published row, keyed (site, subsite, transect_id, filter).

    READ-ONLY firewall: opens the table for reading only, returns a plain dict,
    and never writes anything back. The result is comparison data — it must
    never flow into `load_dsm` or `compute_metrics`. Raises ``LookupError`` if
    the key matches zero rows or more than one (never silently picks one).
    """
    path = Path(path)
    matches: list[dict[str, str]] = []
    with path.open(newline="") as f:  # read mode only — firewall
        for row in csv.DictReader(f):
            if (row["Site"] == site and row["Subsite"] == subsite
                    and row["Transect_ID"] == transect_id and row["Filter"] == filter):
                matches.append(row)

    key = f"{site}/{subsite}/{transect_id}/{filter}"
    if not matches:
        raise LookupError(f"no published row for {key}")
    if len(matches) > 1:
        raise LookupError(f"{len(matches)} rows match {key}; key is not unique")

    row = matches[0]
    parsed = {col: _maybe_float(row[col]) for col in row}
    logger.info("load_reference_metrics %s: rug=%s vrm=%s stand_mean_elev=%s",
                key, parsed.get("full_area_rugosity"), parsed.get("vrm_mean"),
                parsed.get("stand_mean_elev"))
    return parsed


def _maybe_float(v: str) -> Any:
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


class MetricRecord(BaseModel):
    """One reconciled metric — a leaf in the future provenance bundle."""

    model_config = ConfigDict(extra="forbid")

    metric: str
    our_value: float | None
    published_value: float | None
    abs_delta: float | None
    pct_delta: float | None
    reproducibility_tier: str
    note: str | None = None


class ReconciliationReport(BaseModel):
    """Bundle-node-shaped reconciliation result, JSON-serializable."""

    model_config = ConfigDict(extra="forbid")

    site: str
    subsite: str
    transect_id: str
    filter: str
    dsm_provenance_ref: str | None = None  # placeholder for the run-manifest link
    metrics: list[MetricRecord]
    interpretation: str = ""


def _delta(our: float | None, pub: float | None) -> tuple[float | None, float | None]:
    if our is None or pub is None:
        return None, None
    abs_d = our - pub
    pct_d = (abs_d / pub * 100.0) if pub != 0 else None
    return abs_d, pct_d


def reconcile(
    *,
    dsm_path: str | Path,
    reference_path: str | Path,
    site: str,
    subsite: str,
    transect_id: str,
    filter: str,
    dsm_provenance_ref: str | None = None,
    interpretation: str = "",
) -> ReconciliationReport:
    """Compute our metrics on `dsm_path` and reconcile against ONE published row.

    The published values are loaded read-only and used only to fill the
    comparison columns; they never touch the DSM or the metric computation.
    """
    arr, cell = load_dsm(dsm_path)
    ours = compute_metrics(arr, cell)
    ref = load_reference_metrics(reference_path, site, subsite, transect_id, filter)

    notes = {"rugosity": _RUGOSITY_NOTE, "vrm": _VRM_NOTE}
    records: list[MetricRecord] = []
    for metric, our_value in ours.items():
        published = ref.get(METRIC_TO_PUBLISHED[metric])
        published = published if isinstance(published, (int, float)) else None
        abs_d, pct_d = _delta(our_value, published)
        records.append(MetricRecord(
            metric=metric, our_value=our_value, published_value=published,
            abs_delta=abs_d, pct_delta=pct_d,
            reproducibility_tier="pure-python", note=notes.get(metric),
        ))
        logger.info("reconcile %s/%s/%s [%s] %s: ours=%.4f pub=%s abs=%s pct=%s",
                    site, subsite, transect_id, filter, metric, our_value,
                    published, None if abs_d is None else round(abs_d, 4),
                    None if pct_d is None else round(pct_d, 2))

    if not interpretation:
        interpretation = (
            "Tiers: rugosity / mean_elevation / VRM are pure-Python (ADR-0030); "
            "SAPA / RIE / ASD are Tier-2 MultiscaleDTM, not computed. " + _VRM_NOTE
        )
    return ReconciliationReport(
        site=site, subsite=subsite, transect_id=transect_id, filter=filter,
        dsm_provenance_ref=dsm_provenance_ref, metrics=records,
        interpretation=interpretation,
    )
