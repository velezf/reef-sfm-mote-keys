"""Tests for reef_sfm_provenance.exceptions."""

from reef_sfm_provenance.exceptions import (
    IntakeError,
    ManifestError,
    PipelineError,
    ReconciliationError,
    ReefSfmError,
)


def test_all_exceptions_are_subclasses_of_base():
    for cls in (ManifestError, IntakeError, ReconciliationError, PipelineError):
        assert issubclass(cls, ReefSfmError)


def test_base_is_exception():
    assert issubclass(ReefSfmError, Exception)


def test_raise_and_catch_by_base():
    with __import__("pytest").raises(ReefSfmError):
        raise ManifestError("manifest not found")


def test_raise_and_catch_by_specific():
    with __import__("pytest").raises(ReconciliationError, match="missing CSV"):
        raise ReconciliationError("missing CSV")
