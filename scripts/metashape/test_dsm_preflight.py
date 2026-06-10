"""test_dsm_preflight.py — TDD for dsm_preflight.check_dsm_size (pure Python).

No Metashape, no GPU. Four contract tests:
  (a) uncropped T1 region (28.9 × 25.4 m @ 0.001 m) → DSMSizeError fires
  (b) tight AOI (~12 × 4 m @ 0.001 m) → passes, returns correct cell count
  (c) custom ceiling is respected
  (d) return value is the integer cell count when under ceiling
"""
from __future__ import annotations

import pytest

from dsm_preflight import DSMSizeError, check_dsm_size


def test_uncropped_t1_trips_guardrail() -> None:
    """28.9 × 25.4 m @ 0.001 m → ~734 M cells → must raise DSMSizeError.

    This is the canonical forgot-to-crop scenario: the full T1 region at
    0.001 m resolution produces 28900 × 25400 = 733,860,000 cells.
    """
    with pytest.raises(DSMSizeError, match="cell count"):
        check_dsm_size(28.9, 25.4, 0.001)


def test_tight_aoi_passes() -> None:
    """12 × 4 m AOI @ 0.001 m → 48 M cells → under the 100 M default ceiling."""
    cells = check_dsm_size(12.0, 4.0, 0.001)
    assert cells == 48_000_000


def test_custom_ceiling_respected() -> None:
    """Explicit ceiling of 1 M cells rejects a 2 M-cell build."""
    with pytest.raises(DSMSizeError):
        check_dsm_size(2.0, 1.0, 0.001, cell_ceiling=1_000_000)


def test_returns_exact_cell_count() -> None:
    """check_dsm_size returns n_cols × n_rows when under the ceiling."""
    cells = check_dsm_size(10.0, 5.0, 0.01)  # 1000 × 500 = 500_000
    assert cells == 500_000
