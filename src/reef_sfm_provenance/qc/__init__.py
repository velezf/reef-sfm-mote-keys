"""reef_sfm_provenance.qc — QC gates, two layers.

* ``validator.py``  — ``QCValidator``: Toth ESM Table S2 conformance/outcome
  over a ``ProcessingManifest``; ``bool | None`` three-state; ADR-0010.
* ``structural.py`` — ``StructuralQCValidator``: artifact presence and disk
  integrity over a ``RunManifest``; ``bool | None`` three-state.
* ``checker.py``    — ``run_qc`` convenience wrapper over the structural layer.
"""

from reef_sfm_provenance.qc.checker import run_qc
from reef_sfm_provenance.qc.structural import StructuralQCReport, StructuralQCValidator
from reef_sfm_provenance.qc.validator import QCCriterion, QCReport, QCValidator

__all__ = [
    # Toth Table S2 layer (ProcessingManifest)
    "QCCriterion",
    "QCReport",
    "QCValidator",
    # Structural layer (RunManifest)
    "StructuralQCReport",
    "StructuralQCValidator",
    "run_qc",
]
