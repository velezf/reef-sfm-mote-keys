"""Tests for the metric-mapping figure generator (presentation, not provenance).

The point is a regression lock: the rendered table must keep pairing each
published P13HMEON column with its correct our-side metric and verified match
status, so the Chat-8 figure can't silently drift from the ADR-0032 mapping.
"""

from __future__ import annotations

import pytest

great_tables = pytest.importorskip("great_tables")

from metric_mapping_table import MAPPING_ROWS, render_metric_mapping_table


# Expected (published column -> our metric, match) per ADR-0032.
EXPECTED = {
    "full_area_rugosity": ("rugosity (triangulated 3D:2D)", "exact"),
    "stand_mean_elev": ("mean_elevation_standardized", "exact"),
    "vrm_mean": ("vrm (window=0.05)", "same definition [*]"),
    "sapa_mean, rie_mean, asd_mean": ("Tier-2 stubs", "deferred"),
}


def test_mapping_rows_pair_columns_with_correct_metric_and_match():
    by_col = {r["published_column"]: r for r in MAPPING_ROWS}
    assert set(by_col) == set(EXPECTED)
    for col, (metric, match) in EXPECTED.items():
        assert by_col[col]["our_metric"] == metric, col
        assert by_col[col]["match"] == match, col


def test_every_row_has_a_definition():
    for r in MAPPING_ROWS:
        assert r["definition"].strip(), r["published_column"]


def test_vrm_row_carries_multiscaledtm_footnote_marker():
    vrm = next(r for r in MAPPING_ROWS if r["published_column"] == "vrm_mean")
    assert "[*]" in vrm["match"] or vrm.get("footnote")


def test_render_returns_great_tables_object():
    gt = render_metric_mapping_table()
    assert isinstance(gt, great_tables.GT)


def test_rendered_html_contains_mapping_text():
    html = render_metric_mapping_table().as_raw_html()
    assert "full_area_rugosity" in html
    assert "mean_elevation_standardized" in html
    assert "MultiscaleDTM" in html  # the [*] footnote
    assert "data dictionary" in html.lower()  # source note
