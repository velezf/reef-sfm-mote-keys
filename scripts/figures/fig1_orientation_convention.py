"""Figure 1 — orientation convention: camera-nadir vs zero-pitch DSM.

Shows the along-axis tilt (~4.39°) in the camera-nadir DSM and its removal
in the canonical zero-pitch DSM (ADR-0036). Two elevation panels on a shared
colour scale + one along-axis mean-elevation profile overlay.

Reads (read-only):
  products/EDR_T1_R2/edr_t1_r2_q030_dsm_20260616.tif       (camera-nadir)
  products/EDR_T1_R2/edr_t1_r2_q030_zeropitch_10x1_dsm.tif (canonical)

Honesty constraint (annotated on figure):
  The along-axis tilt is the resolved effect shown here. The cross-axis
  residual (reconstruction 6.39° vs published ~1°) is UNRESOLVED — annotated
  explicitly; do not infer cross-axis agreement from these panels.
"""

from __future__ import annotations

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import rasterio
from pathlib import Path

ROOT    = Path(__file__).resolve().parent.parent.parent
FIGURES = ROOT / "figures"
FIGURES.mkdir(exist_ok=True)

NADIR_PATH = ROOT / "products" / "EDR_T1_R2" / "edr_t1_r2_q030_dsm_20260616.tif"
ZP_PATH    = ROOT / "products" / "EDR_T1_R2" / "edr_t1_r2_q030_zeropitch_10x1_dsm.tif"


def read_dsm(path: Path) -> tuple[np.ndarray, float, float]:
    """Return (data_2d_float32, along_track_len_m, cross_track_len_m)."""
    with rasterio.open(path) as ds:
        data = ds.read(1).astype(np.float32)
        if ds.nodata is not None:
            data[data == ds.nodata] = np.nan
        b = ds.bounds
        x_len = abs(b.right - b.left)
        y_len = abs(b.top  - b.bottom)
    return data, x_len, y_len


def along_profile(data: np.ndarray, x_len_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Mean Z per column (nanmean across cross-track rows). X in metres from 0."""
    prof = np.nanmean(data, axis=0)           # shape: (ncols,)
    x    = np.linspace(0.0, x_len_m, data.shape[1])
    return x, prof


def fit_tilt_deg(x: np.ndarray, profile: np.ndarray) -> float:
    """Linear-fit slope → angle in degrees. Returns nan if < 2 finite points."""
    mask = np.isfinite(profile)
    if mask.sum() < 2:
        return float("nan")
    slope, _ = np.polyfit(x[mask], profile[mask], 1)
    return float(np.degrees(np.arctan(slope)))


# ── Load data ─────────────────────────────────────────────────────────────────
nadir_data, nadir_x_len, nadir_y_len = read_dsm(NADIR_PATH)
zp_data,    zp_x_len,    zp_y_len    = read_dsm(ZP_PATH)

# Shared colour scale: robust 2–98th percentile of all finite values
all_vals = np.concatenate([nadir_data[np.isfinite(nadir_data)],
                            zp_data[np.isfinite(zp_data)]])
vmin, vmax = float(np.nanpercentile(all_vals, 2)), float(np.nanpercentile(all_vals, 98))

# Along-axis profiles
nadir_x, nadir_prof = along_profile(nadir_data, nadir_x_len)
zp_x,    zp_prof    = along_profile(zp_data,    zp_x_len)

# Tilt angles
nadir_tilt = fit_tilt_deg(nadir_x, nadir_prof)
zp_tilt    = fit_tilt_deg(zp_x,    zp_prof)

# ── Layout ────────────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(14, 10))
gs  = gridspec.GridSpec(3, 1, figure=fig, hspace=0.55,
                        height_ratios=[1, 1, 1.5])

ax_nadir   = fig.add_subplot(gs[0])
ax_zp      = fig.add_subplot(gs[1])
ax_profile = fig.add_subplot(gs[2])

CMAP = "RdYlBu_r"

# ── Panel 1: camera-nadir ──────────────────────────────────────────────────────
# extent=[x_left, x_right, y_bottom, y_top]; origin='upper' → row 0 at y_top
im = ax_nadir.imshow(
    nadir_data,
    cmap=CMAP, vmin=vmin, vmax=vmax,
    extent=[0, nadir_x_len, 0, nadir_y_len],
    aspect="auto", interpolation="nearest",
)
ax_nadir.set_title(
    f"Camera-nadir DSM  |  along-axis tilt ≈ {nadir_tilt:+.2f}°",
    fontsize=10, fontweight="bold",
)
ax_nadir.set_ylabel("Cross-track (m)", fontsize=8)
ax_nadir.set_xlabel("Along-track (m)", fontsize=8)
ax_nadir.tick_params(labelsize=8)

# ── Panel 2: zero-pitch ───────────────────────────────────────────────────────
ax_zp.imshow(
    zp_data,
    cmap=CMAP, vmin=vmin, vmax=vmax,
    extent=[0, zp_x_len, 0, zp_y_len],
    aspect="auto", interpolation="nearest",
)
ax_zp.set_title(
    f"Zero-pitch DSM  [CANONICAL, sha dcec116b]  |  along-axis tilt ≈ {zp_tilt:+.2f}°",
    fontsize=10, fontweight="bold",
)
ax_zp.set_ylabel("Cross-track (m)", fontsize=8)
ax_zp.set_xlabel("Along-track (m)", fontsize=8)
ax_zp.tick_params(labelsize=8)

# Shared colorbar spanning both DSM panels
fig.colorbar(im, ax=[ax_nadir, ax_zp],
             label="Elevation (m, LOCAL_CS — leveled frame)",
             fraction=0.015, pad=0.02)

# ── Panel 3: profile overlay ──────────────────────────────────────────────────
COL_NADIR = "#d62728"
COL_ZP    = "#1f77b4"

ax_profile.plot(nadir_x, nadir_prof, color=COL_NADIR, linewidth=1.5, alpha=0.8,
                label=f"Camera-nadir  (slope ≈ {nadir_tilt:+.2f}°)")
ax_profile.plot(zp_x,    zp_prof,    color=COL_ZP,    linewidth=1.5, alpha=0.8,
                label=f"Zero-pitch    (slope ≈ {zp_tilt:+.2f}°)")

# Linear-trend overlays
for x_arr, prof, col in [(nadir_x, nadir_prof, COL_NADIR),
                          (zp_x,    zp_prof,    COL_ZP)]:
    mask = np.isfinite(prof)
    c    = np.polyfit(x_arr[mask], prof[mask], 1)
    ax_profile.plot(x_arr, np.polyval(c, x_arr),
                    color=col, linewidth=0.9, linestyle="--", alpha=0.55)

ax_profile.set_xlabel("Along-track distance (m)", fontsize=9)
ax_profile.set_ylabel("Mean elevation (m)", fontsize=9)
ax_profile.set_title("Along-axis mean-elevation profile  (cross-track mean per column)",
                      fontsize=10, fontweight="bold")
ax_profile.legend(fontsize=9, loc="upper left")
ax_profile.grid(True, alpha=0.3)
ax_profile.tick_params(labelsize=8)

# ── Honesty annotation ────────────────────────────────────────────────────────
honest = (
    "⚠  OPEN ITEM — cross-axis residual UNRESOLVED: reconstruction cross-tilt 6.39° vs published ≈1°.\n"
    "    Survey-unanchorable from available data (no gravity reference; collinear markers; ADR-0037).\n"
    "    This figure shows only the along-axis tilt effect. The mean_elevation gap (+27.7%) reflects\n"
    "    both the unresolved cross-axis convention and any residual along-axis offset after Zero-pitch."
)
fig.text(
    0.01, 0.005, honest,
    fontsize=7.5, color="#555555", va="bottom", style="italic",
    bbox=dict(boxstyle="round,pad=0.4", facecolor="#fffff0", alpha=0.85, edgecolor="#cccc99"),
)

fig.suptitle(
    "Figure 1 — Orientation Convention: Camera-Nadir vs Zero-Pitch DSM\n"
    "EDR T1_R2 single-transect · LOCAL_CS · 1 cm GSD · 272 images (Q030)",
    fontsize=11, y=0.995,
)

out = FIGURES / "fig1_orientation_convention.png"
fig.savefig(out, dpi=200, bbox_inches="tight")
plt.close(fig)
print(f"Saved: {out}  ({out.stat().st_size // 1024} KB)")
