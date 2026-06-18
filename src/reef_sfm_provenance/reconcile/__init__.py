"""reef_sfm_provenance.reconcile — metric reconciliation against published values.

Chat-6 layer: recompute terrain metrics from our transect DSMs and compare
them with the P13HMEON-published EDR values (comparison-only — the published
rasters are never a pipeline input; firewall `325dbc7`).

This subpackage starts with the pure-Python metric core (`metrics`), which
operates on in-memory numpy DSMs only and performs no file I/O.
"""

from reef_sfm_provenance.reconcile.metrics import (
    asd,
    mean_elevation_standardized,
    resample_to_cm,
    rie,
    rugosity,
    sapa,
    vrm,
)

__all__ = [
    "asd",
    "mean_elevation_standardized",
    "resample_to_cm",
    "rie",
    "rugosity",
    "sapa",
    "vrm",
    # harness (file I/O + reconciliation report)
    "ReconciliationReport",
    "MetricRecord",
    "compute_metrics",
    "load_dsm",
    "load_reference_metrics",
    "reconcile",
]


def __getattr__(name: str):
    # Lazy import: keep `reconcile.metrics` importable without rasterio.
    if name in {
        "ReconciliationReport", "MetricRecord", "compute_metrics",
        "load_dsm", "load_reference_metrics", "reconcile",
    }:
        from reef_sfm_provenance.reconcile import harness

        return getattr(harness, name)
    if name in {"reconcile_metrics", "load_published_metrics"}:
        from reef_sfm_provenance.reconcile import reconciler

        return getattr(reconciler, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
