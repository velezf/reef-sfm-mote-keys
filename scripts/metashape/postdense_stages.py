"""postdense_stages.py — Typed stubs for post-dense Metashape API stages.

Stage order enforced by the pipeline:
    dense (run_pipeline.py) → filter_confidence → build_dem → build_orthomosaic

These stubs define the interfaces for review. Each raises NotImplementedError
until wired into run_pipeline.py after the dense cloud is available and
validated.

Caller contract before build_dem:
    1. filter_confidence must have run (DSM must not be built on an
       unfiltered cloud — ADR-0015).
    2. dsm_preflight.check_dsm_size must pass for the chosen AOI + resolution
       (tripwire against the uncropped-region OOM scenario).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import Metashape

    from aoi_derivation import OrientedBBox


def filter_confidence(chunk: "Metashape.Chunk", threshold: int = 2) -> int:
    """ESM Step 13: remove dense-cloud points with confidence < threshold.

    Metashape assigns a per-point confidence score during buildPointCloud.
    Scores below ``threshold`` indicate noise (single-view support or weak
    multi-view agreement). Must run BEFORE build_dem — the DSM must never be
    built on an unfiltered cloud (ADR-0015).

    Parameters
    ----------
    chunk     : active chunk with a built dense point cloud
    threshold : points with confidence < threshold classified as noise;
                ESM Step 13 specifies 2

    Returns
    -------
    int — count of points removed (log; sanity-check against expected noise %)
    """
    raise NotImplementedError


def build_dem(
    chunk: "Metashape.Chunk",
    aoi: "OrientedBBox",
    # TODO UNSETTLED: 0.01 m is a placeholder — binding ESM (ADR-0010) defers
    # to Metashape default; PIFSC-SOP 0.001 m is parameter-reference-only.
    # Resolve before implementing; the decision drives the dsm_preflight ceiling.
    resolution_m: float = 0.01,
) -> None:
    """Build DSM from the confidence-filtered dense cloud, clipped to the AOI.

    ESM Step 14. ADR-0010: 1 cm (0.01 m) resolution.

    Prerequisites (caller must enforce):
      - filter_confidence has run on this chunk
      - dsm_preflight.check_dsm_size(aoi.padded_extents[0],
                                      aoi.padded_extents[1],
                                      resolution_m) has passed

    The AOI crop is MANDATORY — the uncropped T1 region (28.9 × 25.4 m) at
    0.001 m produces ~734 M cells and OOMs.

    Parameters
    ----------
    chunk        : chunk after filter_confidence
    aoi          : oriented bounding box from aoi_derivation.derive_aoi;
                   defines the crop footprint and yaw alignment for the DSM
    resolution_m : DSM ground sample distance in metres (ADR-0010 default: 0.01)
    """
    raise NotImplementedError


def build_orthomosaic(chunk: "Metashape.Chunk") -> None:
    """Build orthomosaic from the segmented dense cloud. ESM Step 15.

    Must run after build_dem — the DSM is used for orthorectification.

    Parameters
    ----------
    chunk : chunk with a built DSM
    """
    raise NotImplementedError
