"""ProcessingManifest — typed contract for one Metashape processing run.

Four blocks, mirroring the four questions a reviewer asks:

  provenance    what ran, where, on exactly which bytes
  parameters    what was asked of Metashape (Toth et al. 2025 ESM Table S2
                vocabulary; ADR-0010 makes Table S2 binding, not the PIFSC SOP)
  outcome       what came back (ESM Step 8 QC observables)
  gate          the pipeline's own QC verdict (esm.gate; stage_gate checks 1–8)
  markers_gate  the marker-layer validation verdict (esm.markers_validation;
                gates a–d from stage_markers; ADR-0022)

Every field is Optional by design: this schema is the CONTRACT, and the
population paths (Metashape PDF/HTML report parser, `esm.*` chunk metadata,
EC2 environment capture) land in later branches. A half-populated manifest
must construct, serialize, and flow through QC with the missing criteria
marked not-evaluable — never crash.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProvenanceBlock(BaseModel):
    """What ran, where, on which bytes."""

    model_config = ConfigDict(extra="forbid")

    input_file_hashes: dict[str, str] | None = None
    """Filename -> sha256 of every construction input (P13HMEON never appears)."""
    output_file_hashes: dict[str, str] | None = None
    """Filename -> sha256 of exported products (DSM/ortho GeoTIFFs)."""
    ec2_instance_id: str | None = None
    snapshot_ids: list[str] | None = None
    """EBS snapshot ids capturing the project state (e.g. post-products)."""
    license_fingerprint: str | None = None
    processing_timestamps: dict[str, str] | None = None
    """Stage name -> ISO-8601 UTC timestamp (start or completion per stage)."""
    software_versions: dict[str, str] | None = None
    """Component -> version; must include "metashape" when populated."""


class ParametersBlock(BaseModel):
    """What was asked of Metashape — Toth ESM Table S2 vocabulary."""

    model_config = ConfigDict(extra="forbid")

    alignment_accuracy: str | None = None
    key_point_limit: int | None = None
    tie_point_limit: int | None = None
    generic_preselection: bool | None = None
    exclude_stationary_tie_points: bool | None = None
    recon_uncertainty_threshold: float | None = None
    """Reconstruction-uncertainty value APPLIED in gradual selection (Step 8)."""
    projection_accuracy_threshold: float | None = None
    reprojection_error_threshold: float | None = None
    scale_bar_count: int | None = None


class OutcomeBlock(BaseModel):
    """What came back — the ESM Step 8 QC observables."""

    model_config = ConfigDict(extra="forbid")

    input_image_count: int | None = None
    registered_image_count: int | None = None
    step4_images_analyzed: int | None = None
    """Total cameras submitted to analyzeImages() in ESM Step 4."""
    step4_images_disabled: int | None = None
    """Cameras disabled (quality < threshold) by ESM Step 4."""
    final_reprojection_rms_px: float | None = None
    per_scalebar_errors_m: list[float] | None = None
    """Signed per-bar residuals (measured − defined length), metres. Positive = bar longer than defined."""
    max_horizontal_accuracy_m: float | None = None
    dense_point_count: int | None = None
    """Retained point count after ESM Step 13 confidence filter (esm.filter.points_after)."""
    dsm_cells: int | None = None
    """Width × height cell count of the exported DSM (esm.dsm.cells)."""
    dsm_resolution_m: float | None = None
    """DSM cell size in metres (esm.dsm.resolution_m); 0.01 per ADR-0027."""


class GateCheckResult(BaseModel):
    """One pipeline gate check from stage_gate (esm.gate.checks[check_id])."""

    model_config = ConfigDict(extra="forbid")

    check_id: str
    """Key as written by stage_gate (e.g. '1_long_tilt_deg')."""
    passed: bool | None
    """None for advisory-only checks (check 8)."""
    observed: Any
    threshold: Any
    advisory: bool = False
    characterized: bool = False
    note: str | None = None


class GateBlock(BaseModel):
    """Pipeline QC verdict from stage_gate, stored in esm.gate.

    Checks 1–7 are the hard ship/no-ship core (reference-free). Check 8 is
    advisory-only (P13HMEON reference roughness comparison) and never
    contributes to ``core_failed``. See run_pipeline.py GATE_* constants for
    the authoritative threshold values.
    """

    model_config = ConfigDict(extra="forbid")

    chunk_label: str | None = None
    checks: list[GateCheckResult] = Field(default_factory=list)
    core_failed: list[str] = Field(default_factory=list)
    passed: bool | None = None


class MarkersGateBlock(BaseModel):
    """Marker-layer validation verdict from stage_markers (esm.markers_validation).

    Gates a–d (ADR-0022):
      a  parity — every marker has a consecutive-ID partner (no orphans)
      b  coherence — per-marker reprojection residual below ceiling_px
      c  consistency — inter-bar local-length ratio <= max_ratio (scale-free)
      d  sufficiency — validated bar count >= min_validated_bars

    ``overall_status`` is the top-level field: 'headless-pass' | 'escalated'.
    """

    model_config = ConfigDict(extra="forbid")

    overall_status: str | None = None
    gate_a_parity: bool | None = None
    gate_b_coherence_px: float | None = None
    """Ceiling used for gate (b) — not the observed worst residual."""
    gate_b_passed: bool | None = None
    gate_c_ratio: float | None = None
    """Observed inter-bar max/min length ratio (None if < 2 bars)."""
    gate_c_passed: bool | None = None
    gate_d_bars: int | None = None
    """Count of validated bars (both endpoints coherent)."""
    gate_d_passed: bool | None = None


class ProcessingManifest(BaseModel):
    """One Metashape processing run, end to end."""

    model_config = ConfigDict(extra="forbid")

    manifest_id: str | None = None
    """Human-meaningful run id (e.g. "EDR_T1_20260610"); used in QC logging."""
    provenance: ProvenanceBlock = Field(default_factory=ProvenanceBlock)
    parameters: ParametersBlock = Field(default_factory=ParametersBlock)
    outcome: OutcomeBlock = Field(default_factory=OutcomeBlock)
    gate: GateBlock = Field(default_factory=GateBlock)
    markers_gate: MarkersGateBlock = Field(default_factory=MarkersGateBlock)

    @classmethod
    def from_esm_gate(cls, gate_dict: dict[str, Any]) -> "GateBlock":
        """Parse the esm.gate dict written by stage_gate into a GateBlock.

        Can be used standalone to build a GateBlock, or called inside
        ``from_esm_report`` when esm.gate is embedded in the same payload.
        """
        if not gate_dict:
            return GateBlock()
        raw_checks: dict[str, Any] = gate_dict.get("checks") or {}
        checks: list[GateCheckResult] = []
        for check_id, c in raw_checks.items():
            advisory = bool(c.get("advisory", False))
            passed = None if advisory else c.get("pass")
            # Observed value — most checks use 'v', footprint uses evr+aspect,
            # coreg uses 'v' as a list, advisory uses available/flag.
            if check_id.startswith("6_"):
                observed: Any = {"evr": c.get("evr"), "aspect": c.get("aspect")}
            elif advisory:
                observed = {"available": c.get("available"), "flag": c.get("flag")}
            else:
                observed = c.get("v")
            # Threshold — max / min / target depending on check.
            threshold: Any = c.get("max") or c.get("min") or c.get("target")
            checks.append(GateCheckResult(
                check_id=check_id,
                passed=passed,
                observed=observed,
                threshold=threshold,
                advisory=advisory,
                note=c.get("note"),
            ))
        return GateBlock(
            chunk_label=gate_dict.get("chunk"),
            checks=checks,
            core_failed=gate_dict.get("core_failed") or [],
            passed=gate_dict.get("PASS"),
        )

    @classmethod
    def from_esm_markers_validation(cls, val_dict: dict[str, Any]) -> "MarkersGateBlock":
        """Parse the esm.markers_validation dict written by stage_markers."""
        if not val_dict:
            return MarkersGateBlock()
        gates: dict[str, Any] = val_dict.get("gates") or {}
        ga = gates.get("a_parity") or {}
        gb = gates.get("b_coherence") or {}
        gc = gates.get("c_consistency") or {}
        gd = gates.get("d_sufficiency") or {}
        return MarkersGateBlock(
            overall_status=val_dict.get("status"),
            gate_a_parity=ga.get("ok"),
            gate_b_coherence_px=gb.get("ceiling_px"),
            gate_b_passed=gb.get("ok"),
            gate_c_ratio=gc.get("ratio"),
            gate_c_passed=gc.get("ok"),
            gate_d_bars=gd.get("n_validated_bars"),
            gate_d_passed=gd.get("ok"),
        )

    @classmethod
    def from_esm_report(cls, report: dict[str, Any], manifest_id: str | None = None) -> "ProcessingManifest":
        """Construct from the dict written to chunk.meta['esm.report'] by stage_report."""
        p: dict[str, Any] = report.get("parameters") or {}
        o: dict[str, Any] = report.get("outcome") or {}
        return cls(
            manifest_id=manifest_id,
            parameters=ParametersBlock(
                alignment_accuracy=p.get("alignment_accuracy"),
                key_point_limit=p.get("key_point_limit"),
                tie_point_limit=p.get("tie_point_limit"),
                generic_preselection=p.get("generic_preselection"),
                exclude_stationary_tie_points=p.get("exclude_stationary_tie_points"),
                recon_uncertainty_threshold=p.get("recon_uncertainty_threshold"),
                projection_accuracy_threshold=p.get("projection_accuracy_threshold"),
                reprojection_error_threshold=p.get("reprojection_error_threshold"),
                scale_bar_count=p.get("scale_bar_count"),
            ),
            outcome=OutcomeBlock(
                input_image_count=o.get("input_image_count"),
                step4_images_analyzed=o.get("step4_images_analyzed"),
                step4_images_disabled=o.get("step4_images_disabled"),
                registered_image_count=o.get("registered_image_count"),
                final_reprojection_rms_px=o.get("final_reprojection_rms_px"),
                per_scalebar_errors_m=o.get("per_scalebar_errors_m"),
                dense_point_count=o.get("dense_point_count"),
                dsm_cells=o.get("dsm_cells"),
                dsm_resolution_m=o.get("dsm_resolution_m"),
            ),
        )
