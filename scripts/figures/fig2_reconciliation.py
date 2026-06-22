"""Figure 2 — reconciliation summary: mine vs published metrics.

Reads ONLY reports/reconcile_edr_t1_r2.json. Published values (Toth et al.
2025 ESM Table S2) enter via that pre-firewalled report; this figure layer
never touches data/comparison-only/P13HMEON/*.csv.

Canonical state: zeropitch_clipped_10x1 (sha dcec116b).
Published reference: Toth et al. 2025 ESM Table S2, survey EDR_T1_R2.

Metrics displayed:
  mean_elevation   — mine: states[canonical].mean_elevation_m
                     pub:  published_reference.mean_elevation_standardized_m
  rugosity         — mine: states[canonical].rugosity
                     pub:  published_reference.rugosity
  vrm              — mine: states[canonical].vrm_python  (Python impl)
                     pub:  published_reference.vrm_multiscaledtm_5x5 (MultiscaleDTM R)
"""

from __future__ import annotations

import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
from pathlib import Path

ROOT    = Path(__file__).resolve().parent.parent.parent
FIGURES = ROOT / "figures"
FIGURES.mkdir(exist_ok=True)

REPORT_PATH = ROOT / "reports" / "reconcile_edr_t1_r2.json"

# ── Load JSON — the ONLY data source for this figure ─────────────────────────
rec   = json.loads(REPORT_PATH.read_text())
pub   = rec["published_reference"]
canon = next(s for s in rec["states"] if s.get("canonical"))

# ── Metric table (pure field-reads from JSON) ──────────────────────────────────
METRICS = [
    {
        "name":       "Mean Elevation\n(standardized, m)",
        "mine":       canon["mean_elevation_m"],
        "published":  pub["mean_elevation_standardized_m"],
        "delta_pct":  canon["mean_elevation_delta_pct"],
        "mine_label": "camera-nadir\n+ zero-pitch",
        "pub_label":  "Toth Table S2",
        "status":     "characterized\n(survey-unanchorable;\nADR-0037)",
        "status_key": "characterized-offset",
    },
    {
        "name":       "Rugosity",
        "mine":       canon["rugosity"],
        "published":  pub["rugosity"],
        "delta_pct":  canon["rugosity_delta_pct"],
        "mine_label": "camera-nadir\n+ zero-pitch",
        "pub_label":  "Toth Table S2",
        "status":     "reproduced\n(Δ −3.0%,\nstable across passes)",
        "status_key": "reproduced",
    },
    {
        "name":       "VRM\n(5×5 focal)",
        "mine":       canon["vrm_python"],
        "published":  pub["vrm_multiscaledtm_5x5"],
        "delta_pct":  canon["vrm_delta_pct"],
        "mine_label": "Python impl",
        "pub_label":  "MultiscaleDTM R",
        "status":     "characterized\n(Python impl bias;\nADR-0032)",
        "status_key": "characterized-offset",
    },
]

STATUS_COLOR = {
    "reproduced":         "#2ca02c",
    "characterized-offset": "#ff7f0e",
    "open":               "#d62728",
}

# ── Layout: 3 bar subplots + 1 table subplot ──────────────────────────────────
fig = plt.figure(figsize=(14, 9))
gs  = gridspec.GridSpec(
    2, 3, figure=fig,
    hspace=0.55, wspace=0.45,
    height_ratios=[2.5, 1],
)

BAR_W   = 0.32
COL_MINE = "#1f77b4"
COL_PUB  = "#ff7f0e"

bar_axes = [fig.add_subplot(gs[0, i]) for i in range(3)]

for ax, m in zip(bar_axes, METRICS):
    mine_v = m["mine"]
    pub_v  = m["published"]
    delta  = m["delta_pct"]
    skey   = m["status_key"]

    x = np.array([0.0, 1.0])
    bars = ax.bar(x, [mine_v, pub_v], width=BAR_W,
                  color=[COL_MINE, COL_PUB], alpha=0.85, zorder=3)

    # Value labels on bars
    for bar, val in zip(bars, [mine_v, pub_v]):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + (pub_v * 0.015),
                f"{val:.4f}", ha="center", va="bottom", fontsize=8)

    # Delta annotation — inside axes (top-right) to avoid title overlap
    delta_col = STATUS_COLOR.get(skey, "#555555")
    ax.text(0.97, 0.94,
            f"Δ = {delta:+.1f}%",
            transform=ax.transAxes,
            ha="right", va="top",
            fontsize=9, fontweight="bold", color=delta_col,
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.75,
                      edgecolor=delta_col, linewidth=0.8))

    # Y limits: tight around values (not from zero — differences are small)
    lo = min(mine_v, pub_v)
    hi = max(mine_v, pub_v)
    span = hi - lo if hi != lo else hi * 0.05
    ax.set_ylim(lo - span * 1.5, hi + span * 2.5)

    ax.set_xticks([0, 1])
    ax.set_xticklabels([m["mine_label"], m["pub_label"]], fontsize=8)
    ax.set_title(m["name"], fontsize=10, fontweight="bold")
    ax.grid(True, axis="y", alpha=0.3, zorder=0)
    ax.tick_params(labelsize=8)

    # Status chip
    ax.text(0.5, -0.28, m["status"],
            transform=ax.transAxes,
            ha="center", va="top",
            fontsize=7.5, color=delta_col,
            bbox=dict(boxstyle="round,pad=0.3",
                      facecolor=delta_col, alpha=0.12,
                      edgecolor=delta_col))

# Y-axis note (not from zero)
for ax in bar_axes:
    ax.annotate("y-axis not from 0", xy=(0.01, 0.01),
                xycoords="axes fraction",
                fontsize=6.5, color="#aaaaaa", style="italic")

# ── Legend ─────────────────────────────────────────────────────────────────────
from matplotlib.patches import Patch
legend_handles = [
    Patch(facecolor=COL_MINE, alpha=0.85, label="This reconstruction (canonical)"),
    Patch(facecolor=COL_PUB,  alpha=0.85, label="Published — Toth et al. 2025 ESM Table S2"),
]
fig.legend(handles=legend_handles, loc="upper right",
           fontsize=9, framealpha=0.9, bbox_to_anchor=(0.99, 0.97))

# ── Summary table ─────────────────────────────────────────────────────────────
# Notes dropped — kept in Status one-liners to avoid cell overflow.
# colWidths fractions sum to 1.0; Status gets the remaining width so long
# strings stay within their cell without bleeding into neighbours.
ax_tbl = fig.add_subplot(gs[1, :])
ax_tbl.axis("off")

STATUS_SHORT = {
    "characterized-offset-elev": "characterized · survey-unanchorable · ADR-0037",
    "reproduced":                 "reproduced · Δ −3.0% · stable across passes",
    "characterized-offset-vrm":  "characterized · Python impl bias (+13%) · ADR-0032",
}
STATUS_SHORT_LIST = [
    STATUS_SHORT["characterized-offset-elev"],
    STATUS_SHORT["reproduced"],
    STATUS_SHORT["characterized-offset-vrm"],
]

col_labels = ["Metric", "Mine", "Published", "Δ%", "Status"]
COL_WIDTHS  = [0.22, 0.10, 0.11, 0.09, 0.48]   # sum = 1.00

table_data = []
for m, stext in zip(METRICS, STATUS_SHORT_LIST):
    table_data.append([
        m["name"].replace("\n", " "),
        f"{m['mine']:.4f}",
        f"{m['published']:.4f}",
        f"{m['delta_pct']:+.1f}%",
        stext,
    ])

tbl = ax_tbl.table(
    cellText=table_data,
    colLabels=col_labels,
    colWidths=COL_WIDTHS,
    cellLoc="left",
    loc="center",
    bbox=[0, 0, 1, 1],
)
tbl.auto_set_font_size(False)
tbl.set_fontsize(7.5)
tbl.scale(1, 1.6)   # taller rows so wrapped text stays within borders
# Header styling
for j in range(len(col_labels)):
    tbl[0, j].set_facecolor("#dddddd")
    tbl[0, j].set_text_props(fontweight="bold")
# Status column colour
for i, m in enumerate(METRICS, start=1):
    col = STATUS_COLOR.get(m["status_key"], "#555555")
    tbl[i, 4].set_facecolor(col)
    tbl[i, 4].set_alpha(0.15)

# ── Provenance note ───────────────────────────────────────────────────────────
fig.text(
    0.01, 0.002,
    "Data source: reports/reconcile_edr_t1_r2.json only. "
    "Published values pre-firewalled via that report. "
    "P13HMEON CSV never opened by this figure layer.",
    fontsize=7, color="#888888", va="bottom", style="italic",
)

fig.suptitle(
    "Figure 2 — Reconciliation: EDR T1_R2 Canonical vs Published (Toth et al. 2025)\n"
    "Canonical DSM: zeropitch_clipped_10x1 · sha dcec116b · ADR-0036/0037",
    fontsize=11, y=0.999,
)

out = FIGURES / "fig2_reconciliation.png"
fig.savefig(out, dpi=200, bbox_inches="tight")
plt.close(fig)
print(f"Saved: {out}  ({out.stat().st_size // 1024} KB)")
