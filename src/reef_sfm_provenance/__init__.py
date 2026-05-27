"""
reef_sfm_provenance — enterprise data management layer for the reef-sfm-mote-keys project.

This package is built incrementally across chats:

  Chat 4  intake validation, USGS acquisition, image inventory, intake QC report
  Chat 6  processing manifest, QC validator, metric reconciliation
  Chat 7  benthic-cover comparison

The Chat-4 surface intentionally stays small. Importing this module must not
require Metashape or any GPU dependency; this is the on-MacBook safe layer.
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("reef-sfm-provenance")
except PackageNotFoundError:  # editable install before metadata is built
    __version__ = "0.0.0+dev"

__all__ = ["__version__"]
