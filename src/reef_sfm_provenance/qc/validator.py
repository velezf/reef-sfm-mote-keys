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

from reef_sfm_provenance.manifest.schema import GateBlock, MarkersGateBlock, ProcessingManifest

logger = logging.getLogger(__name__)

TOTH_TABLE_S2 = "Toth et al. 2025 ESM Table S2 (ADR-0010)"
TOTH_STEP_8 = "Toth et al. 2025 ESM Step 8 (ADR-0031)"

Category = Literal["conformance", "outcome", "pipeline_gate", "markers_gate"]


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

    Pipeline gate thresholds (``gate_*``) mirror the ``GATE_*`` constants in
    ``run_pipeline.py`` and are used by ``validate_full()`` to verify the
    ``esm.gate`` verdict matches expected bounds.
    """

    # Pipeline gate defaults — mirror run_pipeline.py GATE_* constants exactly.
    # These are the authoritative calibrated values; do not change without an ADR.
    GATE_LONG_TILT_MAX_DEG: float = 0.5
    GATE_TOTAL_TILT_MAX_DEG: float = 6.0
    GATE_COVERAGE_MIN: float = 0.95
    GATE_SCALE_EXTENT_TOL_M: float = 0.02
    GATE_FOOTPRINT_EVR_MIN: float = 0.95
    GATE_FOOTPRINT_ASPECT_MIN: float = 5.0
    GATE_MARKER_RESID_CEILING_PX: float = 2.0
    GATE_INTERBAR_RATIO_MAX: float = 1.25
    GATE_MIN_VALIDATED_BARS: int = 3

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
        gate_long_tilt_max_deg: float = 0.5,
        gate_total_tilt_max_deg: float = 6.0,
        gate_coverage_min: float = 0.95,
        gate_footprint_evr_min: float = 0.95,
        gate_footprint_aspect_min: float = 5.0,
        gate_marker_resid_ceiling_px: float = 2.0,
        gate_interbar_ratio_max: float = 1.25,
        gate_min_validated_bars: int = 3,
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
        self.gate_long_tilt_max_deg = gate_long_tilt_max_deg
        self.gate_total_tilt_max_deg = gate_total_tilt_max_deg
        self.gate_coverage_min = gate_coverage_min
        self.gate_footprint_evr_min = gate_footprint_evr_min
        self.gate_footprint_aspect_min = gate_footprint_aspect_min
        self.gate_marker_resid_ceiling_px = gate_marker_resid_ceiling_px
        self.gate_interbar_ratio_max = gate_interbar_ratio_max
        self.gate_min_validated_bars = gate_min_validated_bars

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
        report = QCReport(manifest_id=manifest.manifest_id, criteria=self._toth_criteria(manifest))
        self._log_summary(report)
        return report

    def _toth_criteria(self, manifest: ProcessingManifest) -> list[QCCriterion]:
        """Build the 11 Toth Table S2 criteria without logging."""
        p = manifest.parameters
        o = manifest.outcome
        return [
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

    # -- pipeline gate + markers gate criteria --------------------------------

    def validate_full(self, manifest: ProcessingManifest) -> QCReport:
        """Run Toth Table S2 + pipeline gate + markers gate criteria together.

        Uses ``_toth_criteria()`` directly (no intermediate validate() call) so
        only one log line is emitted for the combined report.
        """
        all_criteria = (
            self._toth_criteria(manifest)
            + self._gate_criteria(manifest.gate)
            + self._markers_gate_criteria(manifest.markers_gate)
        )
        report = QCReport(manifest_id=manifest.manifest_id, criteria=all_criteria)
        self._log_summary(report)
        return report

    def _gate_criteria(self, gate: GateBlock) -> list[QCCriterion]:
        """Convert a GateBlock into QCCriterion objects (pipeline_gate category)."""
        _SRC = "run_pipeline.py stage_gate (esm.gate)"
        if not gate.checks:
            # No per-check data — emit a sentinel using the block's own verdict
            # (None when the block is default-empty, True/False when it was
            # constructed from a summary-only payload with no per-check details).
            return [QCCriterion(
                name="pipeline_gate_overall",
                category="pipeline_gate",
                passed=gate.passed,
                observed=None,
                threshold=None,
                source=_SRC,
            )]
        crits: list[QCCriterion] = []
        for chk in gate.checks:
            crits.append(QCCriterion(
                name=f"gate_{chk.check_id}",
                category="pipeline_gate",
                passed=chk.passed,
                observed=chk.observed,
                threshold=chk.threshold,
                source=_SRC + (" (advisory)" if chk.advisory else ""),
            ))
        return crits

    def _markers_gate_criteria(self, mg: MarkersGateBlock) -> list[QCCriterion]:
        """Convert a MarkersGateBlock into QCCriterion objects (markers_gate category)."""
        _SRC = "run_pipeline.py stage_markers (esm.markers_validation; ADR-0022)"

        def _crit(name: str, passed: bool | None, observed: Any, threshold: Any) -> QCCriterion:
            return QCCriterion(
                name=name, category="markers_gate",
                passed=passed, observed=observed, threshold=threshold, source=_SRC,
            )

        if mg.overall_status is None and mg.gate_a_parity is None:
            return [_crit("markers_gate_overall", None, None, None)]

        return [
            _crit("markers_gate_a_parity", mg.gate_a_parity,
                  "ok" if mg.gate_a_parity is True else "orphans-present" if mg.gate_a_parity is False else None,
                  "all markers paired (consecutive IDs)"),
            _crit("markers_gate_b_coherence", mg.gate_b_passed,
                  mg.gate_b_worst_resid_px,
                  mg.gate_b_coherence_px if mg.gate_b_coherence_px is not None
                  else self.gate_marker_resid_ceiling_px),
            _crit("markers_gate_c_consistency", mg.gate_c_passed,
                  mg.gate_c_ratio,
                  self.gate_interbar_ratio_max),
            _crit("markers_gate_d_sufficiency", mg.gate_d_passed,
                  mg.gate_d_bars,
                  self.gate_min_validated_bars),
        ]

    @staticmethod
    def _log_summary(report: QCReport) -> None:
        mid = report.manifest_id or "<unidentified>"
        by_cat: dict[str, list[QCCriterion]] = {}
        for c in report.criteria:
            by_cat.setdefault(c.category, []).append(c)
        parts = []
        for category, crits in by_cat.items():
            n_pass = sum(c.passed is True for c in crits)
            n_eval = sum(c.passed is not None for c in crits)
            parts.append(f"{category} {n_pass}/{n_eval} passed ({len(crits) - n_eval} not evaluable)")
        logger.info("QC %s: verdict=%s; %s", mid, report.passed, "; ".join(parts))
        failed = [c.name for c in report.criteria if c.passed is False]
        if failed:
            logger.warning("QC %s: failed criteria: %s", mid, ", ".join(failed))
