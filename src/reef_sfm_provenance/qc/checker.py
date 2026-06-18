"""Convenience wrapper: run_qc(manifest, run_root) -> StructuralQCReport.

A thin public entry point over :class:`StructuralQCValidator` so callers can
import ``run_qc`` without knowing the validator class name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from reef_sfm_provenance.models import RunManifest
from reef_sfm_provenance.qc.structural import StructuralQCReport, StructuralQCValidator

_validator = StructuralQCValidator()


def run_qc(manifest: RunManifest, run_root: Optional[str | Path] = None) -> StructuralQCReport:
    """Run all structural QC checks and return a :class:`StructuralQCReport`."""
    return _validator.validate(manifest, run_root=run_root)
