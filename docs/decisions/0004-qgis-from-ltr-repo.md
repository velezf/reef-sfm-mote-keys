# 0004 — Install QGIS from the official LTR apt repository

- **Status:** Accepted
- **Date:** 2026-05-25
- **Chat:** 3 (EC2 bootstrap)

## Context

QGIS is the GIS tool of record for Chat 7 (annotation, benthic cover
calculation, publication figure export). Two apt sources are available
on Ubuntu 24.04:

1. The `qgis` package in the Ubuntu universe archive. Stable but
   frozen against whatever QGIS release shipped at Ubuntu 24.04's
   freeze date — typically a major version behind upstream.
2. The official QGIS long-term-release apt repository at
   `qgis.org/ubuntu-ltr`. Maintained by the QGIS project, tracks the
   current LTR (released roughly annually, supported for ~12 months).

## Decision

Use the official QGIS LTR repository, gated by GPG key at
`/etc/apt/keyrings/qgis-archive-keyring.gpg`. Install `qgis`,
`qgis-plugin-grass`, and `python3-qgis` to get the desktop, the GRASS
processing toolbox (used for terrain derivatives like slope and
rugosity from the DEM), and the Python bindings (needed for any
PyQGIS-driven automation in Chat 7's stretch goals).

## Consequences

- The LTR repository updates within the same major version line over
  the project's lifetime — patch updates are fine, but the operator
  should not run a blind `apt-get upgrade qgis` after Chat 7 figures
  are exported. Rendering can change subtly between LTR minor
  versions.
- The official repo signs packages with its own GPG key, which is
  imported into a dedicated keyring (not the system root keyring)
  per Ubuntu 22.04+ best practice.
- This choice positions QGIS as the GIS tool for the project even
  though the original PIFSC SOP and Mote workflows use ArcGIS Pro.
  See `docs/07-gis-annotation.md` (Chat 7) for the framing of QGIS
  as a deliberate accessibility choice for restoration programs
  without ArcGIS licenses, rather than a substitute under duress.

## Notebook narrative

> Spatial analysis and figure production use QGIS LTR, installed from
> the official QGIS apt repository rather than the Ubuntu archive.
> The official LTR build is the version tracked in QGIS project
> documentation and bug reports, so any troubleshooting (and any
> reader trying to reproduce the figures) lands on consistent
> documentation. The plugin set includes `qgis-plugin-grass` for the
> GRASS-backed terrain operations used to derive slope and rugosity
> from the DEM. The choice of QGIS over ArcGIS Pro is deliberate and
> elaborated in the Chat 7 GIS annotation methods.
