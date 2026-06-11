"""reef_sfm_provenance.qc — QC gates over a ProcessingManifest.

Chat-6 layer: turns a populated (or half-populated) `ProcessingManifest`
into a `QCReport` — one entry per criterion, split into *conformance*
(were Toth ESM Table S2 parameters actually applied; ADR-0010) and
*outcome* (did the run meet the ESM Step 8 quality observables).
"""

from reef_sfm_provenance.qc.validator import QCCriterion, QCReport, QCValidator

__all__ = ["QCCriterion", "QCReport", "QCValidator"]
