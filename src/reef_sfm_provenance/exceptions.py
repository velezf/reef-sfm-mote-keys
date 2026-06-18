"""Structured exceptions for reef_sfm_provenance."""


class ReefSfmError(Exception):
    """Base exception for all reef-sfm-provenance errors."""


class ManifestError(ReefSfmError):
    """Raised when a run manifest cannot be loaded, written, or validated."""


class ReconciliationError(ReefSfmError):
    """Raised when metric reconciliation fails (e.g. missing reference CSV)."""


class IntakeError(ReefSfmError):
    """Raised when an imagery intake directory cannot be validated."""


class PipelineError(ReefSfmError):
    """Raised when a pipeline stage fails in an unrecoverable way."""
