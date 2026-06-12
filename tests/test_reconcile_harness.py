"""Tests for `reef_sfm_provenance.reconcile.harness`.

HERMETIC: every fixture is synthetic — a GeoTIFF written to a tmp_path and a
synthetic reference CSV in the pinned P13HMEON schema. No real P13HMEON file
is opened here; the real-data runs live in the headline scripts, not the
test suite. The firewall is asserted as a property of the loader (it opens
the reference read-only and never writes).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402

from reef_sfm_provenance.reconcile.harness import (  # noqa: E402
    ReconciliationReport,
    compute_metrics,
    load_dsm,
    load_reference_metrics,
    reconcile,
)

# Pinned P13HMEON column schema (subset the harness consumes).
_REF_HEADER = (
    "Survey_date,Site,Subsite,Transect_ID,Restored?,Filter,"
    "full_area_rugosity,stand_mean_elev,vrm_mean\n"
)
_REF_ROWS = [
    "7/11/2023,Eastern Dry Rocks,EDR_T3,C1,N,confidence,1.382,0.252,0.067\n",
    "7/11/2023,Eastern Dry Rocks,EDR_T3,R1,Y,confidence,1.385,0.231,0.078\n",
    "7/11/2023,Eastern Dry Rocks,EDR_T3,C1,N,canopy,1.307,0.250,0.059\n",
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def write_tif(path, array, cell_size=0.01, nodata=None):
    array = np.asarray(array, dtype="float32")
    transform = from_origin(0.0, array.shape[0] * cell_size, cell_size, cell_size)
    profile = dict(
        driver="GTiff", height=array.shape[0], width=array.shape[1], count=1,
        dtype="float32", transform=transform, crs="EPSG:32617",
    )
    if nodata is not None:
        profile["nodata"] = nodata
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(array, 1)
    return path


def write_ref(path):
    path.write_text(_REF_HEADER + "".join(_REF_ROWS))
    return path


def ramp_45(nrows=40, ncols=60, cell=0.01):
    _, xx = np.mgrid[0:nrows, 0:ncols]
    return (xx * cell).astype("float32")


# ---------------------------------------------------------------------------
# load_dsm
# ---------------------------------------------------------------------------


def test_load_dsm_reads_array_and_cell_size(tmp_path):
    arr = ramp_45(cell=0.01)
    p = write_tif(tmp_path / "dsm.tif", arr, cell_size=0.01)
    out, cell = load_dsm(p)
    assert cell == pytest.approx(0.01, abs=1e-9)
    assert out.shape == arr.shape
    np.testing.assert_allclose(out, arr, atol=1e-6)


def test_load_dsm_converts_nodata_to_nan(tmp_path):
    arr = np.full((10, 10), -3.5, dtype="float32")
    arr[0, 0] = -9999.0
    p = write_tif(tmp_path / "nd.tif", arr, cell_size=0.01, nodata=-9999.0)
    out, _ = load_dsm(p)
    assert math.isnan(out[0, 0])
    assert np.isfinite(out[5, 5])


def test_load_dsm_resamples_finer_grid_to_cm(tmp_path):
    # 1 mm grid -> loader resamples to 1 cm (resample_to_cm guard).
    arr = ramp_45(nrows=40, ncols=60, cell=0.001)
    p = write_tif(tmp_path / "fine.tif", arr, cell_size=0.001)
    out, cell = load_dsm(p)
    assert cell == pytest.approx(0.01, abs=1e-9)
    assert out.shape == (4, 6)


def test_load_dsm_rejects_non_square_cells(tmp_path):
    arr = np.zeros((8, 8), dtype="float32")
    transform = from_origin(0.0, 8 * 0.01, 0.01, 0.02)  # dx != dy
    with rasterio.open(
        tmp_path / "rect.tif", "w", driver="GTiff", height=8, width=8, count=1,
        dtype="float32", transform=transform, crs="EPSG:32617",
    ) as dst:
        dst.write(arr, 1)
    with pytest.raises(ValueError):
        load_dsm(tmp_path / "rect.tif")


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------


def test_compute_metrics_on_flat_plane():
    m = compute_metrics(np.full((50, 50), -2.0))
    assert m["rugosity"] == pytest.approx(1.0, abs=1e-9)
    assert m["vrm"] == pytest.approx(0.0, abs=1e-9)
    assert m["mean_elevation"] == pytest.approx(0.0, abs=1e-9)


def test_compute_metrics_keys():
    m = compute_metrics(ramp_45())
    assert set(m) == {"rugosity", "vrm", "mean_elevation"}


# ---------------------------------------------------------------------------
# load_reference_metrics — row selection by key, firewall
# ---------------------------------------------------------------------------


def test_reference_row_selection_by_key(tmp_path):
    ref = write_ref(tmp_path / "ref.csv")
    row = load_reference_metrics(
        ref, site="Eastern Dry Rocks", subsite="EDR_T3",
        transect_id="R1", filter="confidence",
    )
    assert row["full_area_rugosity"] == pytest.approx(1.385)
    assert row["stand_mean_elev"] == pytest.approx(0.231)
    assert row["vrm_mean"] == pytest.approx(0.078)


def test_reference_filter_discriminates_rows(tmp_path):
    ref = write_ref(tmp_path / "ref.csv")
    conf = load_reference_metrics(ref, "Eastern Dry Rocks", "EDR_T3", "C1", "confidence")
    canopy = load_reference_metrics(ref, "Eastern Dry Rocks", "EDR_T3", "C1", "canopy")
    assert conf["full_area_rugosity"] != canopy["full_area_rugosity"]


def test_reference_missing_row_raises(tmp_path):
    ref = write_ref(tmp_path / "ref.csv")
    with pytest.raises(LookupError):
        load_reference_metrics(ref, "Eastern Dry Rocks", "EDR_T1", "C2", "confidence")


def test_reference_ambiguous_key_raises(tmp_path):
    # Two rows with the same full key -> refuse to silently pick one.
    dup = tmp_path / "dup.csv"
    dup.write_text(_REF_HEADER + _REF_ROWS[0] + _REF_ROWS[0])
    with pytest.raises(LookupError):
        load_reference_metrics(dup, "Eastern Dry Rocks", "EDR_T3", "C1", "confidence")


def test_reference_opened_read_only_and_not_mutated(tmp_path):
    ref = write_ref(tmp_path / "ref.csv")
    before = ref.read_bytes()
    before_mtime = ref.stat().st_mtime_ns
    load_reference_metrics(ref, "Eastern Dry Rocks", "EDR_T3", "C1", "confidence")
    assert ref.read_bytes() == before  # firewall: harness writes nothing back
    assert ref.stat().st_mtime_ns == before_mtime


# ---------------------------------------------------------------------------
# reconcile — deltas, tiers, report shape
# ---------------------------------------------------------------------------


def test_reconcile_produces_per_metric_deltas(tmp_path):
    ref = write_ref(tmp_path / "ref.csv")
    dsm = write_tif(tmp_path / "dsm.tif", np.full((50, 50), -2.0), cell_size=0.01)
    report = reconcile(
        dsm_path=dsm, reference_path=ref, site="Eastern Dry Rocks",
        subsite="EDR_T3", transect_id="C1", filter="confidence",
    )
    assert isinstance(report, ReconciliationReport)
    recs = {r.metric: r for r in report.metrics}
    assert set(recs) == {"rugosity", "vrm", "mean_elevation"}

    rug = recs["rugosity"]
    # flat plane -> our rugosity 1.0; published 1.382
    assert rug.our_value == pytest.approx(1.0, abs=1e-6)
    assert rug.published_value == pytest.approx(1.382)
    assert rug.abs_delta == pytest.approx(1.0 - 1.382, abs=1e-6)
    assert rug.pct_delta == pytest.approx((1.0 - 1.382) / 1.382 * 100, abs=1e-4)
    assert rug.reproducibility_tier == "pure-python"


def test_reconcile_report_json_round_trip(tmp_path):
    ref = write_ref(tmp_path / "ref.csv")
    dsm = write_tif(tmp_path / "dsm.tif", ramp_45(), cell_size=0.01)
    report = reconcile(
        dsm_path=dsm, reference_path=ref, site="Eastern Dry Rocks",
        subsite="EDR_T3", transect_id="C1", filter="confidence",
    )
    again = ReconciliationReport.model_validate_json(report.model_dump_json())
    assert again.transect_id == report.transect_id
    assert len(again.metrics) == 3


def test_reconcile_carries_interpretation_and_tiers(tmp_path):
    ref = write_ref(tmp_path / "ref.csv")
    dsm = write_tif(tmp_path / "dsm.tif", ramp_45(), cell_size=0.01)
    report = reconcile(
        dsm_path=dsm, reference_path=ref, site="Eastern Dry Rocks",
        subsite="EDR_T3", transect_id="C1", filter="confidence",
    )
    assert report.interpretation  # non-empty caveat text
    vrm = {r.metric: r for r in report.metrics}["vrm"]
    # VRM note must flag the Sappington-vs-MultiscaleDTM implementation gap.
    assert "MultiscaleDTM" in (vrm.note or "") or "MultiscaleDTM" in report.interpretation
    assert all(r.reproducibility_tier == "pure-python" for r in report.metrics)
