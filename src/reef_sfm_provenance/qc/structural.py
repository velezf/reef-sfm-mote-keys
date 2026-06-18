"""Structural QC checks on a RunManifest — artifact presence and disk integrity.

Follows the same pattern as `validator.py`: each check returns a `QCCriterion`
with `passed = True | False | None` (not-evaluable when the manifest has no
artifacts to check). The `StructuralQCValidator` runs all checks and returns a
`QCReport` from this module (distinct from the Toth-Table-S2 `QCReport` in
`validator.py`).

These checks answer "is the run product-complete and on-disk-sound?", while
`QCValidator` answers "did we run what Toth ran and did it come out well?".
The two validators are complementary and are typically run together.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, computed_field

from reef_sfm_provenance.models import ArtifactKind, RunManifest

logger = logging.getLogger(__name__)

_REQUIRED_ARTIFACTS = (ArtifactKind.DSM, ArtifactKind.ORTHOMOSAIC, ArtifactKind.DENSE_CLOUD)
_SOURCE = "reef_sfm_provenance.qc.structural"

# Quantitative targets — sourced, not magic numbers.
_TARGETS: dict[str, Any] = {
    "reprojection_error_px": (0.3, 0.5),
    "scalebar_error_m": 0.001,
    "registered_fraction": 0.90,
    "recon_uncertainty": 15.0,
}


class StructuralCriterion(BaseModel):
    """One structural QC decision. ``passed=None`` means not-evaluable."""

    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool | None
    observed: Any
    threshold: Any
    source: str


class StructuralQCReport(BaseModel):
    """Serializable structural QC verdict."""

    model_config = ConfigDict(extra="forbid")

    run_id: str | None
    criteria: list[StructuralCriterion]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> bool | None:
        """False on any failure; None when nothing was evaluable; else True."""
        verdicts = [c.passed for c in self.criteria]
        if any(v is False for v in verdicts):
            return False
        if any(v is True for v in verdicts):
            return True
        return None

    def to_json(self, **kwargs: Any) -> str:
        return self.model_dump_json(**kwargs)


class StructuralQCValidator:
    """Artifact presence + disk integrity checks on a RunManifest."""

    def validate(self, manifest: RunManifest, run_root: str | Path | None = None) -> StructuralQCReport:
        root = Path(run_root) if run_root is not None else None
        criteria = [
            self._reprojection_error(manifest),
            self._scalebar_error(manifest),
            self._registered_images(manifest),
            self._reconstruction_uncertainty(manifest),
            *[self._artifact_present(manifest, kind) for kind in _REQUIRED_ARTIFACTS],
            self._disk_integrity(manifest, root),
        ]
        report = StructuralQCReport(run_id=manifest.run_id, criteria=criteria)
        self._log_summary(report)
        return report

    @staticmethod
    def _reprojection_error(m: RunManifest) -> StructuralCriterion:
        lo, hi = _TARGETS["reprojection_error_px"]
        val = m.error_metrics.get("reprojection_error_px")
        return StructuralCriterion(
            name="reprojection_error",
            passed=None if val is None else (lo <= val <= hi),
            observed=val,
            threshold=[lo, hi],
            source=_SOURCE,
        )

    @staticmethod
    def _scalebar_error(m: RunManifest) -> StructuralCriterion:
        thr = _TARGETS["scalebar_error_m"]
        val = m.error_metrics.get("scalebar_error_m")
        return StructuralCriterion(
            name="scalebar_error",
            passed=None if val is None else (val <= thr),
            observed=val,
            threshold=thr,
            source=_SOURCE,
        )

    @staticmethod
    def _registered_images(m: RunManifest) -> StructuralCriterion:
        thr = _TARGETS["registered_fraction"]
        total = m.camera_alignment.get("images_total")
        aligned = m.camera_alignment.get("images_aligned")
        if not total or aligned is None:
            frac = None
        else:
            frac = aligned / total
        return StructuralCriterion(
            name="registered_images",
            passed=None if frac is None else (frac >= thr),
            observed=frac,
            threshold=thr,
            source=_SOURCE,
        )

    @staticmethod
    def _reconstruction_uncertainty(m: RunManifest) -> StructuralCriterion:
        thr = _TARGETS["recon_uncertainty"]
        val = m.error_metrics.get("reconstruction_uncertainty")
        return StructuralCriterion(
            name="recon_uncertainty",
            passed=None if val is None else (val <= thr),
            observed=val,
            threshold=thr,
            source=_SOURCE,
        )

    @staticmethod
    def _artifact_present(manifest: RunManifest, kind: ArtifactKind) -> StructuralCriterion:
        art = manifest.artifact(kind)
        return StructuralCriterion(
            name=f"artifact_{kind.value}_present",
            passed=art is not None,
            observed=art.path if art else None,
            threshold="present",
            source=_SOURCE,
        )

    @staticmethod
    def _disk_integrity(manifest: RunManifest, root: Path | None) -> StructuralCriterion:
        if not manifest.artifacts:
            return StructuralCriterion(
                name="artifact_disk_integrity",
                passed=None,
                observed=None,
                threshold="all artifacts on disk with matching hashes",
                source=_SOURCE,
            )
        if root is None:
            return StructuralCriterion(
                name="artifact_disk_integrity",
                passed=None,
                observed=None,
                threshold="all artifacts on disk with matching hashes",
                source=_SOURCE,
            )

        bad: list[str] = []
        checked = 0
        for art in manifest.artifacts:
            full = root / art.path
            if not full.exists():
                bad.append(f"{art.path}:missing")
                continue
            if full.stat().st_size == 0:
                bad.append(f"{art.path}:empty")
                continue
            if art.sha256:
                actual = hashlib.sha256(full.read_bytes()).hexdigest()
                if actual != art.sha256:
                    bad.append(f"{art.path}:hash_mismatch")
                    continue
            checked += 1

        passed = len(bad) == 0
        return StructuralCriterion(
            name="artifact_disk_integrity",
            passed=passed,
            observed=f"{checked}/{len(manifest.artifacts)} ok" if passed else "; ".join(bad),
            threshold="all artifacts on disk with matching hashes",
            source=_SOURCE,
        )

    @staticmethod
    def _log_summary(report: StructuralQCReport) -> None:
        mid = report.run_id or "<unidentified>"
        n_pass = sum(c.passed is True for c in report.criteria)
        n_eval = sum(c.passed is not None for c in report.criteria)
        logger.info(
            "StructuralQC %s: verdict=%s; %d/%d passed (%d not evaluable)",
            mid, report.passed, n_pass, n_eval, len(report.criteria) - n_eval,
        )
        failed = [c.name for c in report.criteria if c.passed is False]
        if failed:
            logger.warning("StructuralQC %s: failed: %s", mid, ", ".join(failed))
