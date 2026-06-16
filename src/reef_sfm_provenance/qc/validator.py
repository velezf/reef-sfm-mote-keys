"""QC validator — ProcessingManifest in, QCReport out.

Two categories of criteria (the split matters — see ADR-0031):

  conformance  "did we run what Toth ran?" Parameter equality / windows vs
               Toth et al. 2025 ESM Table S2 (binding per ADR-0010; the
               PIFSC SOP numbers are explicitly NOT the reference).
  outcome      "did the run come out well?" Registration ratio, final
               reprojection RMS, scale-bar residuals (ESM Step 8).

Reconstruction uncertainty is deliberately a *conformance* check on the
APPLIED gradual-selection threshold (Toth window 20–40): after Step 8 the
surviving points sit at ~the applied threshold, so a PIFSC-style "RU <= 15"
outcome gate would fail every Toth-conformant model by construction.

Every threshold is a constructor parameter with a Toth-Table-S2 default.
A criterion whose manifest fields are unpopulated (Optional schema — the
population paths land in later branches) is emitted with ``passed=None``
(not-evaluable), never skipped and never crashed on.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, computed_field

from reef_sfm_provenance.manifest.schema import ProcessingManifest

logger = logging.getLogger(__name__)

TOTH_TABLE_S2 = "Toth et al. 2025 ESM Table S2 (ADR-0010)"
TOTH_STEP_8 = "Toth et al. 2025 ESM Step 8 (ADR-0031)"

Category = Literal["conformance", "outcome"]


class QCCriterion(BaseModel):
    """One QC decision. ``passed=None`` means not-evaluable, not a pass."""

    model_config = ConfigDict(extra="forbid")

    name: str
    category: Category
    passed: bool | None
    observed: Any
    threshold: Any
    source: str


class QCReport(BaseModel):
    """Serializable QC verdict: one entry per criterion + overall roll-up."""

    model_config = ConfigDict(extra="forbid")

    manifest_id: str | None
    criteria: list[QCCriterion]

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


class QCValidator:
    """QC gates with Toth-Table-S2 defaults; every threshold overridable.

    `scalebar_max_m` defaults to None — the scale-bar gate is parameterized
    pending calibration against observed residuals (do NOT assume the PIFSC
    0.001 m); until it is supplied the criterion reports not-evaluable.

    `frame_retention_min` defaults to 0.60 — empirically anchored to ADR-0017's
    T3 A/B: the 0.30 floor cut retained 99.0% of frames and aligned 98.7% of
    the corpus; the 0.50 (Toth verbatim) cut retained only 46–48% and produced
    ≤27% corpus alignment on T3. 0.60 cleanly separates both bad cases from the
    floor-cut good case. Closes the corpus-blind ALARM_MAX_DISABLED=200 gap at
    the QC layer (ADR-0034).
    """

    def __init__(
        self,
        *,
        accuracy_expected: str = "High",
        key_point_limit_expected: int = 60_000,
        tie_point_limit_expected: int = 0,
        generic_preselection_expected: bool = True,
        recon_uncertainty_range: tuple[float, float] = (20.0, 40.0),
        projection_accuracy_range: tuple[float, float] = (3.0, 4.0),
        reprojection_error_expected: float = 0.3,
        reprojection_error_rtol: float = 0.05,
        registration_ratio_min: float = 0.90,
        final_rms_max_px: float = 0.52,
        scalebar_max_m: float | None = None,
        frame_retention_min: float = 0.60,
    ) -> None:
        self.accuracy_expected = accuracy_expected
        self.key_point_limit_expected = key_point_limit_expected
        self.tie_point_limit_expected = tie_point_limit_expected
        self.generic_preselection_expected = generic_preselection_expected
        self.recon_uncertainty_range = recon_uncertainty_range
        self.projection_accuracy_range = projection_accuracy_range
        self.reprojection_error_expected = reprojection_error_expected
        self.reprojection_error_rtol = reprojection_error_rtol
        self.registration_ratio_min = registration_ratio_min
        self.final_rms_max_px = final_rms_max_px
        self.scalebar_max_m = scalebar_max_m
        self.frame_retention_min = frame_retention_min

    # -- criterion builders -------------------------------------------------

    @staticmethod
    def _eq(name: str, observed: Any, expected: Any, source: str = TOTH_TABLE_S2) -> QCCriterion:
        return QCCriterion(
            name=name, category="conformance",
            passed=None if observed is None else observed == expected,
            observed=observed, threshold=expected, source=source,
        )

    @staticmethod
    def _window(name: str, observed: float | None, window: tuple[float, float]) -> QCCriterion:
        lo, hi = window
        return QCCriterion(
            name=name, category="conformance",
            passed=None if observed is None else lo <= observed <= hi,
            observed=observed, threshold=[lo, hi], source=TOTH_TABLE_S2,
        )

    # -- the gate -----------------------------------------------------------

    def validate(self, manifest: ProcessingManifest) -> QCReport:
        p = manifest.parameters
        o = manifest.outcome

        criteria = [
            # Conformance: did we run what Toth ran?
            self._eq("alignment_accuracy", p.alignment_accuracy, self.accuracy_expected),
            self._eq("key_point_limit", p.key_point_limit, self.key_point_limit_expected),
            self._eq("tie_point_limit", p.tie_point_limit, self.tie_point_limit_expected),
            self._eq("generic_preselection", p.generic_preselection,
                     self.generic_preselection_expected),
            self._window("reconstruction_uncertainty_threshold",
                         p.recon_uncertainty_threshold, self.recon_uncertainty_range),
            self._window("projection_accuracy_threshold",
                         p.projection_accuracy_threshold, self.projection_accuracy_range),
            self._reprojection_error_conformance(p.reprojection_error_threshold),
            # Outcome: did the run come out well?
            self._registration_ratio(o.input_image_count, o.registered_image_count),
            self._final_rms(o.final_reprojection_rms_px),
            self._scalebars(o.per_scalebar_errors_m),
            self._frame_retention(o.step4_images_analyzed, o.step4_images_disabled),
        ]

        report = QCReport(manifest_id=manifest.manifest_id, criteria=criteria)
        self._log_summary(report)
        return report

    def _reprojection_error_conformance(self, observed: float | None) -> QCCriterion:
        expected = self.reprojection_error_expected
        tol = abs(expected) * self.reprojection_error_rtol
        return QCCriterion(
            name="reprojection_error_threshold", category="conformance",
            passed=None if observed is None else abs(observed - expected) <= tol,
            observed=observed, threshold=expected, source=TOTH_TABLE_S2,
        )

    def _registration_ratio(self, total: int | None, registered: int | None) -> QCCriterion:
        evaluable = total is not None and registered is not None and total > 0
        ratio = registered / total if evaluable else None
        return QCCriterion(
            name="registration_ratio", category="outcome",
            passed=None if ratio is None else ratio >= self.registration_ratio_min,
            observed=ratio, threshold=self.registration_ratio_min, source=TOTH_STEP_8,
        )

    def _final_rms(self, observed: float | None) -> QCCriterion:
        return QCCriterion(
            name="final_reprojection_rms", category="outcome",
            passed=None if observed is None else observed <= self.final_rms_max_px,
            observed=observed, threshold=self.final_rms_max_px,
            source=f"{TOTH_STEP_8}; Toth-derived max (target 0.30 px)",
        )

    def _scalebars(self, errors_m: list[float] | None) -> QCCriterion:
        worst = max(abs(e) for e in errors_m) if errors_m else None
        evaluable = worst is not None and self.scalebar_max_m is not None
        return QCCriterion(
            name="scale_bar_errors", category="outcome",
            passed=(worst <= self.scalebar_max_m) if evaluable else None,
            observed=worst, threshold=self.scalebar_max_m,
            source="parameterized pending residual calibration (ADR-0031)",
        )

    def _frame_retention(self, analyzed: int | None, disabled: int | None) -> QCCriterion:
        evaluable = (
            analyzed is not None and disabled is not None and analyzed > 0
        )
        retention = (1 - disabled / analyzed) if evaluable else None
        passed = (retention >= self.frame_retention_min) if retention is not None else None
        logger.debug(
            "frame_retention: analyzed=%s disabled=%s retention=%s threshold=%s verdict=%s",
            analyzed, disabled,
            f"{retention:.4f}" if retention is not None else "N/A",
            self.frame_retention_min,
            passed,
        )
        return QCCriterion(
            name="frame_retention", category="outcome",
            passed=passed,
            observed=retention,
            threshold=self.frame_retention_min,
            source="ADR-0017 T3 A/B: 0.30-floor retained 99% / 0.50-Toth retained 46–48% (ADR-0034)",
        )

    @staticmethod
    def _log_summary(report: QCReport) -> None:
        mid = report.manifest_id or "<unidentified>"
        parts = []
        for category in ("conformance", "outcome"):
            crits = [c for c in report.criteria if c.category == category]
            n_pass = sum(c.passed is True for c in crits)
            n_eval = sum(c.passed is not None for c in crits)
            parts.append(f"{category} {n_pass}/{n_eval} passed ({len(crits) - n_eval} not evaluable)")
        logger.info("QC %s: verdict=%s; %s", mid, report.passed, "; ".join(parts))
        failed = [c.name for c in report.criteria if c.passed is False]
        if failed:
            logger.warning("QC %s: failed criteria: %s", mid, ", ".join(failed))
