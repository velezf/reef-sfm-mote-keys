"""Tests for reef_sfm_provenance.logging_config."""

import logging

from reef_sfm_provenance.logging_config import configure_logging


def test_configure_logging_runs_without_error():
    configure_logging(level=logging.WARNING)


def test_configure_logging_idempotent():
    configure_logging()
    configure_logging()


def test_configure_logging_accepts_debug_level():
    # basicConfig is idempotent; just verify no exception is raised.
    configure_logging(level=logging.DEBUG)
