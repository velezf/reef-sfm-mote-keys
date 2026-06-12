"""Metric-mapping figure: published P13HMEON column -> our metric -> match.

PRESENTATION, not provenance — deliberately outside the `reef_sfm_provenance`
package. The Chat-8 writeup (.qmd) calls `render_metric_mapping_table()` inline
to drop the figure into the document; this module is also runnable as a script
to render a self-contained HTML preview for eyeballing now:

    uv run python scripts/figures/metric_mapping_table.py

The mapping is version-controlled data (`MAPPING_ROWS`) so the figure can't
drift from the contract verified in ADR-0032 — the tests assert each pairing.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from great_tables import GT, md, style, loc

#: The verified mapping (ADR-0032). Definitions are paraphrased from the
#: P13HMEON data dictionary; implementations are our ADR-0030 functions.
MAPPING_ROWS: list[dict[str, str]] = [
    {
        "published_column": "full_area_rugosity",
        "definition": "3D surface area / 2D planar area (whole-model, not focal)",
        "our_metric": "rugosity (triangulated 3D:2D)",
        "match": "exact",
    },
    {
        "published_column": "stand_mean_elev",
        "definition": "mean elevation − minimum elevation",
        "our_metric": "mean_elevation_standardized",
        "match": "exact",
    },
    {
        "published_column": "vrm_mean",
        "definition": "Sappington VRM, unit-normal dispersion, 5×5 cm focal",
        "our_metric": "vrm (window=0.05)",
        "match": "same definition [*]",
        "footnote": "their value computed via R MultiscaleDTM",
    },
    {
        "published_column": "sapa_mean, rie_mean, asd_mean",
        "definition": "MultiscaleDTM focal metrics",
        "our_metric": "Tier-2 stubs",
        "match": "deferred",
    },
]

_COLUMN_LABELS = {
    "published_column": "Published column",
    "definition": "Definition",
    "our_metric": "Our metric",
    "match": "Match",
}

_SOURCE_NOTE = (
    "Definitions verified against the P13HMEON data dictionary; "
    "implementations per ADR-0030."
)
_VRM_FOOTNOTE = "[*] vrm_mean: their value computed via R MultiscaleDTM."


def render_metric_mapping_table() -> GT:
    """Build the metric-mapping table as a great_tables ``GT`` object."""
    df = pd.DataFrame([{k: r[k] for k in _COLUMN_LABELS} for r in MAPPING_ROWS])
    gt = (
        GT(df)
        .cols_label(**_COLUMN_LABELS)
        .tab_header(title="Topographic-complexity metrics: published vs ours")
        .tab_style(  # subtle emphasis on the Match column
            style=style.text(weight="bold"),
            locations=loc.body(columns="match"),
        )
        .tab_source_note(source_note=md(f"{_SOURCE_NOTE}  \n{_VRM_FOOTNOTE}"))
        .cols_align(align="left")
    )
    return gt


def _render_preview() -> Path:
    out = Path(__file__).resolve().parents[2] / "artifacts/figures/metric_mapping_table.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_metric_mapping_table().as_raw_html())
    return out


if __name__ == "__main__":
    path = _render_preview()
    print(f"wrote preview: {path}")
