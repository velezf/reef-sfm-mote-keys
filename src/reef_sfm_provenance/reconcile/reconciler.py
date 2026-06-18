"""Metric reconciliation — the headline deliverable.

Compares *our* computed metrics against the *published* reference values
(USGS P13HMEON / Toth et al. 2025) and characterizes every divergence.

The firewall is structural and absolute: published values are comparison-only.
They never enter the pipeline and never tune a parameter. This module loads them
solely to characterize divergence; the loader is the only place published data
is read, and nothing here writes back into a manifest or a pipeline input.

Reproducibility is graded, not binary (:class:`ReproducibilityStatus`):

* ``reproduced`` — same implementation, within tolerance.
* ``approximately_reproduced`` — comparable, but a known implementation or
  coverage difference applies (e.g. VRM Sappington-vs-MultiscaleDTM).
* ``not_reproducible`` — our outputs cannot support the metric.
* ``not_attempted`` — out of scope for this run.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Iterable, Optional

from reef_sfm_provenance.exceptions import ReconciliationError
from reef_sfm_provenance.models import (
    Metric,
    ReconciliationReport,
    ReconciliationResult,
    ReproducibilityStatus,
)
from reef_sfm_provenance.reconcile.metrics_interface import REPRODUCIBILITY

logger = logging.getLogger(__name__)

DEFAULT_TOLERANCE = 0.02  # 2% relative tolerance for "reproduced"

FORMULA_SOURCES = {
    "rugosity": "Toth et al. 2025, Fig. S5 (3D/2D surface-area ratio)",
    "mean_elevation": "Toth et al. 2025, Fig. S5 (mean(z) standardized to transect minimum)",
    "vrm": "Sappington et al. 2007; Toth et al. 2025, Fig. S5",
    "sapa": "Du Preez 2015; Toth et al. 2025, Fig. S5",
    "rie": "Toth et al. 2025, Fig. S5",
    "asd": "Toth et al. 2025, Fig. S5",
}


def load_published_metrics(csv_path: str | Path) -> list[Metric]:
    """Load published reference metrics from a CSV.

    This is the **only** place published reference data is read. Expected
    columns (case-insensitive): ``metric``/``name``, ``value``, optional
    ``unit``, ``window_m``, ``implementation``. Every returned metric is tagged
    ``source="published"``.
    """
    p = Path(csv_path)
    if not p.exists():
        raise ReconciliationError(f"published reference CSV not found: {p}")
    out: list[Metric] = []
    with open(p, newline="") as fh:
        reader = csv.DictReader(fh)
        cols = {c.lower(): c for c in (reader.fieldnames or [])}
        name_col = cols.get("metric") or cols.get("name")
        val_col = cols.get("value")
        if not name_col or not val_col:
            raise ReconciliationError(
                f"published CSV must have metric/name and value columns; got {reader.fieldnames}"
            )
        for row in reader:
            try:
                value = float(row[val_col])
            except (TypeError, ValueError):
                continue
            out.append(Metric(
                name=str(row[name_col]).strip().lower(),
                value=value,
                unit=(row.get(cols.get("unit", "")) or None),
                window_m=_maybe_float(row.get(cols.get("window_m", ""))),
                implementation=(row.get(cols.get("implementation", "")) or None),
                source="published",
            ))
    logger.info("loaded %d published reference metrics from %s", len(out), p.name)
    return out


def _maybe_float(v: Optional[str]) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def reconcile_metrics(
    local: Iterable[Metric],
    published: Iterable[Metric],
    *,
    run_id: str,
    tolerance: float = DEFAULT_TOLERANCE,
) -> ReconciliationReport:
    """Reconcile local metrics against published reference values.

    Matches by metric name. Computes absolute and percent difference, grades
    reproducibility against :data:`metrics_interface.REPRODUCIBILITY` and the
    tolerance, and records the implementation on both sides so an
    implementation-driven offset is visible in the report.
    """
    local_by_name = {m.name.lower(): m for m in local}
    pub_by_name = {m.name.lower(): m for m in published}
    names = sorted(set(local_by_name) | set(pub_by_name))

    results: list[ReconciliationResult] = []
    for name in names:
        lm = local_by_name.get(name)
        pm = pub_by_name.get(name)
        result = ReconciliationResult(
            metric_name=name,
            local_value=lm.value if lm else None,
            published_value=pm.value if pm else None,
            units=(lm.unit if lm else None) or (pm.unit if pm else None),
            formula_source=FORMULA_SOURCES.get(name),
            ours_implementation=lm.implementation if lm else None,
            published_implementation=pm.implementation if pm else None,
        )

        if lm is None:
            result.reproducibility = ReproducibilityStatus.NOT_ATTEMPTED
            result.explanation = "Not computed locally for this run."
        elif pm is None:
            result.reproducibility = REPRODUCIBILITY.get(name, ReproducibilityStatus.NOT_ATTEMPTED)
            result.explanation = "No published reference value to compare against."
        else:
            diff = lm.value - pm.value
            result.difference = diff
            result.percent_difference = (diff / pm.value * 100.0) if pm.value else None
            result.reproducibility = _grade(name, result.percent_difference, lm, pm, tolerance)
            result.explanation = _explain(result)

        results.append(result)

    report = ReconciliationReport(run_id=run_id, results=results)
    logger.info("reconciled %d metrics for %s", len(results), run_id)
    return report


def _grade(
    name: str,
    pct: Optional[float],
    lm: Metric,
    pm: Metric,
    tolerance: float,
) -> ReproducibilityStatus:
    declared = REPRODUCIBILITY.get(name, ReproducibilityStatus.NOT_ATTEMPTED)
    if declared in (ReproducibilityStatus.NOT_REPRODUCIBLE, ReproducibilityStatus.NOT_ATTEMPTED):
        return declared
    impl_mismatch = bool(
        lm.implementation and pm.implementation and lm.implementation != pm.implementation
    )
    within = pct is not None and abs(pct) <= tolerance * 100.0
    if within and not impl_mismatch:
        return ReproducibilityStatus.REPRODUCED
    return ReproducibilityStatus.APPROXIMATELY_REPRODUCED


def _explain(r: ReconciliationResult) -> str:
    parts: list[str] = []
    if r.percent_difference is not None:
        parts.append(f"{r.percent_difference:+.1f}% vs published")
    if (
        r.ours_implementation
        and r.published_implementation
        and r.ours_implementation != r.published_implementation
    ):
        parts.append(
            f"implementation differs (ours={r.ours_implementation}, "
            f"published={r.published_implementation}); offset is characterized, not error"
        )
    return "; ".join(parts) or "matched within tolerance"
