"""Logging configuration helper."""

import logging


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logger. Idempotent — safe to call multiple times."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
