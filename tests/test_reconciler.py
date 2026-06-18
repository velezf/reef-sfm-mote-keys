"""Tests for reef_sfm_provenance.reconcile.reconciler and metrics_interface.

Uses only in-memory Metric objects — no real DSM files needed. The numerical
metric core (rugosity/VRM etc.) is tested separately in test_reconcile_metrics.py.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from reef_sfm_provenance.exceptions import ReconciliationError
from reef_sfm_provenance.models import (
    Metric,
    ReconciliationReport,
    ReconciliationResult,
    ReproducibilityStatus,
)
from reef_sfm_provenance.reconcile.metrics_interface import REPRODUCIBILITY
from reef_sfm_provenance.reconcile.reconciler import (
    DEFAULT_TOLERANCE,
    FORMULA_SOURCES,
    load_published_metrics,
    reconcile_metrics,
)


# ---------------------------------------------------------------------------
# REPRODUCIBILITY dict
# ---------------------------------------------------------------------------

def test_reproducibility_dict_covers_toth_metrics():
    required = {"rugosity", "mean_elevation", "vrm", "sapa", "rie", "asd"}
    assert required <= set(REPRODUCIBILITY.keys())


def test_rugosity_and_mean_elevation_reproduced():
    assert REPRODUCIBILITY["rugosity"] is ReproducibilityStatus.REPRODUCED
    assert REPRODUCIBILITY["mean_elevation"] is ReproducibilityStatus.REPRODUCED


def test_vrm_approximately_reproduced():
    assert REPRODUCIBILITY["vrm"] is ReproducibilityStatus.APPROXIMATELY_REPRODUCED


# ---------------------------------------------------------------------------
# load_published_metrics
# ---------------------------------------------------------------------------

def _write_csv(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "published.csv"
    with p.open("w", newline="") as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    return p


def test_load_published_metrics_basic(tmp_path: Path):
    p = _write_csv(tmp_path, [
        {"metric": "rugosity", "value": "1.415", "unit": "dimensionless"},
        {"metric": "vrm", "value": "0.076"},
    ])
    metrics = load_published_metrics(p)
    assert len(metrics) == 2
    by_name = {m.name: m for m in metrics}
    assert by_name["rugosity"].value == pytest.approx(1.415)
    assert by_name["rugosity"].source == "published"
    assert by_name["vrm"].unit is None  # not in CSV


def test_load_published_metrics_missing_file(tmp_path: Path):
    with pytest.raises(ReconciliationError, match="not found"):
        load_published_metrics(tmp_path / "nonexistent.csv")


def test_load_published_metrics_missing_columns(tmp_path: Path):
    p = tmp_path / "bad.csv"
    p.write_text("col_a,col_b\n1,2\n")
    with pytest.raises(ReconciliationError, match="metric/name"):
        load_published_metrics(p)


def test_load_published_metrics_skips_non_numeric_values(tmp_path: Path):
    p = _write_csv(tmp_path, [
        {"metric": "rugosity", "value": "1.415"},
        {"metric": "bad_metric", "value": "N/A"},
    ])
    metrics = load_published_metrics(p)
    assert len(metrics) == 1
    assert metrics[0].name == "rugosity"


# ---------------------------------------------------------------------------
# reconcile_metrics
# ---------------------------------------------------------------------------

def _local(*pairs) -> list[Metric]:
    return [Metric(name=n, value=v, source="ours") for n, v in pairs]


def _published(*pairs) -> list[Metric]:
    return [Metric(name=n, value=v, source="published") for n, v in pairs]


def test_reconcile_within_tolerance_grades_reproduced():
    report = reconcile_metrics(
        local=_local(("rugosity", 1.412)),   # 1.415 * 0.998 — within 2%
        published=_published(("rugosity", 1.415)),
        run_id="test",
    )
    r = report.results[0]
    assert r.metric_name == "rugosity"
    assert r.local_value == pytest.approx(1.412)
    assert r.published_value == pytest.approx(1.415)
    assert r.difference == pytest.approx(1.412 - 1.415)
    assert r.percent_difference == pytest.approx((1.412 - 1.415) / 1.415 * 100)
    assert r.reproducibility is ReproducibilityStatus.REPRODUCED


def test_reconcile_outside_tolerance_approximately_reproduced():
    # rugosity is declared REPRODUCED, but VRM is APPROXIMATELY_REPRODUCED by declaration
    report = reconcile_metrics(
        local=_local(("vrm", 0.065)),
        published=_published(("vrm", 0.076)),
        run_id="test",
    )
    r = report.results[0]
    # VRM is declared APPROXIMATELY_REPRODUCED regardless of tolerance
    assert r.reproducibility is ReproducibilityStatus.APPROXIMATELY_REPRODUCED


def test_reconcile_local_only_no_published():
    report = reconcile_metrics(
        local=_local(("rugosity", 1.372)),
        published=[],
        run_id="test",
    )
    r = report.results[0]
    assert r.published_value is None
    assert r.local_value == pytest.approx(1.372)
    assert r.reproducibility is ReproducibilityStatus.REPRODUCED  # declared, no comparison needed
    assert "No published" in r.explanation


def test_reconcile_published_only_not_attempted():
    report = reconcile_metrics(
        local=[],
        published=_published(("rugosity", 1.415)),
        run_id="test",
    )
    r = report.results[0]
    assert r.local_value is None
    assert r.reproducibility is ReproducibilityStatus.NOT_ATTEMPTED


def test_reconcile_firewall_note_present():
    report = reconcile_metrics(local=[], published=[], run_id="test")
    assert "comparison-only" in report.firewall_note


def test_reconcile_formula_sources_populated():
    report = reconcile_metrics(
        local=_local(("rugosity", 1.372)),
        published=_published(("rugosity", 1.415)),
        run_id="test",
    )
    assert "Toth" in report.results[0].formula_source


def test_reconcile_report_json_round_trip():
    report = reconcile_metrics(
        local=_local(("rugosity", 1.372), ("vrm", 0.065)),
        published=_published(("rugosity", 1.415), ("vrm", 0.076)),
        run_id="EDR_T1_R2",
    )
    again = ReconciliationReport.model_validate_json(report.model_dump_json())
    assert again.run_id == "EDR_T1_R2"
    assert len(again.results) == 2
