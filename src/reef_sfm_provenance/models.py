"""Typed domain models for ``reef_sfm_provenance``.

The manifest is the contract; everything else validates against it.

Design commitment: **Reconciliation is metric-vs-published and firewalled.**
Published values are comparison-only; they never enter the pipeline or tune a
parameter. Reproducibility is itself graded (:class:`ReproducibilityStatus`),
because "we computed the same metric" is rarely a clean yes/no.

QC models live in ``qc/validator.py`` (Toth-Table-S2 conformance/outcome gates
with ``bool | None`` three-state). This module holds the domain data types only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Environment / software / inputs
# --------------------------------------------------------------------------- #
class SoftwareVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: Optional[str] = None


class ProcessingEnvironment(BaseModel):
    """Reproducibility metadata. No secrets — fingerprint, not the license key."""

    model_config = ConfigDict(extra="forbid")

    instance_id: Optional[str] = Field(None, description="Compute instance, e.g. EC2 id.")
    snapshot_ids: list[str] = Field(default_factory=list)
    license_fingerprint: Optional[str] = Field(
        None, description="Non-secret license fingerprint/anchor; never the key itself."
    )
    os: Optional[str] = None
    python_version: Optional[str] = None
    software: list[SoftwareVersion] = Field(default_factory=list)


class InputDataset(BaseModel):
    """The source imagery as a hashed, counted, described input."""

    model_config = ConfigDict(extra="forbid")

    path: str
    image_count: Optional[int] = None
    camera_model: Optional[str] = Field(None, description="e.g. 'Canon PowerShot S120'.")
    file_hashes: dict[str, str] = Field(
        default_factory=dict, description="Mapping {filename: sha256} for provenance."
    )


# --------------------------------------------------------------------------- #
# Artifacts, metrics, steps
# --------------------------------------------------------------------------- #
class ArtifactKind(str, Enum):
    """Vocabulary follows the published literature (Combs 2021, Toth 2025)."""

    DSM = "digital_surface_model"
    ORTHOMOSAIC = "orthomosaic"
    DENSE_CLOUD = "dense_point_cloud"
    SPARSE_CLOUD = "sparse_point_cloud"
    MESH = "mesh"
    CAMERA_POSES = "camera_poses"
    SCALEBAR_LIST = "scalebar_list"
    PROCESSING_REPORT = "processing_report"
    OTHER = "other"


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ArtifactKind
    path: str = Field(..., description="Path relative to the run root.")
    sha256: Optional[str] = None
    size_bytes: Optional[int] = None
    crs: Optional[str] = Field(None, description="For raster artifacts (DSM, orthomosaic).")


class Metric(BaseModel):
    """A topographic-complexity metric.

    ``implementation`` is a first-class provenance fact: two faithful
    implementations of the same published formula can differ materially
    (python/Sappington VRM reads ~+13% vs MultiscaleDTM). Reconciliation is only
    valid between metrics that share an implementation.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="rugosity | vrm | mean_elevation | sapa | rie | asd | ...")
    value: float
    unit: Optional[str] = None
    window_m: Optional[float] = Field(None, description="Focal window in metres, e.g. 0.05.")
    implementation: Optional[str] = Field(
        None, description='e.g. "MultiscaleDTM", "python-sappington".'
    )
    source: str = Field("ours", description='"ours" | "published".')


class PipelineStep(BaseModel):
    """A processing step. Maps to a W3C PROV Activity."""

    model_config = ConfigDict(extra="forbid")

    name: str
    software: SoftwareVersion = Field(
        default_factory=lambda: SoftwareVersion(name="Agisoft Metashape Professional")
    )
    parameters: dict = Field(default_factory=dict)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None


# --------------------------------------------------------------------------- #
# The run-level contract
# --------------------------------------------------------------------------- #
class RunManifest(BaseModel):
    """One processing run, end to end.

    Parallel to ``ProcessingManifest`` (the Metashape-internal contract in
    ``manifest/schema.py``) but operates at the run level: it can be
    constructed from any processing path and is the input to the provenance
    export, structural QC checks, and report generation.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    site: str
    transect: Optional[str] = None

    code_version: Optional[str] = Field(None, description="git sha of the pipeline code.")
    pipeline_version: Optional[str] = None

    environment: ProcessingEnvironment = Field(default_factory=ProcessingEnvironment)
    input_dataset: Optional[InputDataset] = None

    crs: Optional[str] = None
    camera_alignment: dict = Field(
        default_factory=dict,
        description="e.g. {'images_total': 272, 'images_aligned': 131}.",
    )
    error_metrics: dict = Field(
        default_factory=dict,
        description="e.g. {'reprojection_error_px': 0.31, 'scalebar_error_m': 0.0017}.",
    )

    steps: list[PipelineStep] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=_utcnow)

    def artifact(self, kind: ArtifactKind) -> Optional[Artifact]:
        """Return the first artifact of *kind*, or None."""
        return next((a for a in self.artifacts if a.kind == kind), None)


# --------------------------------------------------------------------------- #
# Reconciliation — our metric vs published (the differentiator)
# --------------------------------------------------------------------------- #
class ReproducibilityStatus(str, Enum):
    REPRODUCED = "reproduced"
    APPROXIMATELY_REPRODUCED = "approximately_reproduced"
    NOT_REPRODUCIBLE = "not_reproducible"
    NOT_ATTEMPTED = "not_attempted"


class ReconciliationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_name: str
    published_value: Optional[float] = None
    local_value: Optional[float] = None
    difference: Optional[float] = None
    percent_difference: Optional[float] = None
    units: Optional[str] = None
    formula_source: Optional[str] = Field(None, description='e.g. "Toth et al. 2025, Fig. S5".')
    reproducibility: ReproducibilityStatus = ReproducibilityStatus.NOT_ATTEMPTED
    ours_implementation: Optional[str] = None
    published_implementation: Optional[str] = None
    explanation: Optional[str] = Field(
        None, description="Characterized cause of divergence, or why not reproducible."
    )


class ReconciliationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    results: list[ReconciliationResult] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=_utcnow)
    firewall_note: str = (
        "Published reference values are comparison-only. They are never inputs to the "
        "pipeline and were never used to tune parameters."
    )

