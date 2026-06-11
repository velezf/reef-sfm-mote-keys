"""ProcessingManifest — typed contract for one Metashape processing run.

Three blocks, mirroring the three questions a reviewer asks:

  provenance  what ran, where, on exactly which bytes
  parameters  what was asked of Metashape (Toth et al. 2025 ESM Table S2
              vocabulary; ADR-0010 makes Table S2 binding, not the PIFSC SOP)
  outcome     what came back (ESM Step 8 QC observables)

Every field is Optional by design: this schema is the CONTRACT, and the
population paths (Metashape PDF/HTML report parser, `esm.*` chunk metadata,
EC2 environment capture) land in later branches. A half-populated manifest
must construct, serialize, and flow through QC with the missing criteria
marked not-evaluable — never crash.
"""

from __future__ import annotations

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
    final_reprojection_rms_px: float | None = None
    per_scalebar_errors_m: list[float] | None = None
    """Signed per-bar residuals (estimated − nominal length), metres."""
    max_horizontal_accuracy_m: float | None = None


class ProcessingManifest(BaseModel):
    """One Metashape processing run, end to end."""

    model_config = ConfigDict(extra="forbid")

    manifest_id: str | None = None
    """Human-meaningful run id (e.g. "EDR_T1_20260610"); used in QC logging."""
    provenance: ProvenanceBlock = Field(default_factory=ProvenanceBlock)
    parameters: ParametersBlock = Field(default_factory=ParametersBlock)
    outcome: OutcomeBlock = Field(default_factory=OutcomeBlock)
