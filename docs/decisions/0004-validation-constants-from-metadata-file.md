# ADR 0004 — Validation constants come from the metadata file, not the papers

Status: Accepted
Date: 2026-05-27
Chat: 4

## Context

The intake validator checks each downloaded image against a set of
expected values: EXIF Artist string, Copyright string, IPTC Credit, the
XMP AttributionURL DOI, the bounding box for GPS, the camera model.

These expectations are stated in three different places:

1. **The P1WHKTRD metadata file** (`Chat4_Coral_reef_restoration_imagery_metadata.txt`)
   — the FGDC-CSDGM metadata record published alongside the data
   release.  Contains the literal ExifTool command USGS ran to populate
   the headers, including every tag value as a quoted string.
2. **The Combs et al. 2021 paper** — describes the methodology including
   camera choice ("Canon PowerShot S110") and rough acquisition parameters.
3. **The Toth et al. 2025 paper** — also describes camera and method but
   from a slightly newer survey.

The papers conflict with the metadata in small ways: Combs 2021 used the
Canon S110; this release used the S120.  The metadata file is the source
of truth for *what is actually in these specific bytes on disk*.

## Decision

Every validation constant in `validation.py` comes from the metadata
file, not from the papers.  Examples:

```python
EXPECTED_EXIF_ARTIST = "USGS St. Petersburg Coastal and Marine Science Center"
EXPECTED_EXIF_COPYRIGHT = "Public Domain"
EXPECTED_IPTC_CREDIT = "U.S. Geological Survey, Mote Marine Laboratory"
EXPECTED_XMP_ATTRIBUTION_URL = "https://doi.org/10.5066/P1WHKTRD"
EXPECTED_CAMERA_MODEL_PATTERN = re.compile(r"PowerShot\s*S120", re.IGNORECASE)
```

Each constant is named after the EXIF/XMP/IPTC tag it checks, and the
file header references the metadata file as the source.  When the
papers and metadata disagree, the metadata wins.

## Consequences

**Positive.**

- The validator catches the precise thing it should: drift between
  on-disk bytes and what USGS *published they put there*.  If USGS
  re-runs ExifTool with different tag values, our tests fail loudly.
- Reproducible by anyone with the metadata file — no need to read
  Combs 2021 just to know what Artist string to expect.
- Cleanly separates "did we receive the data as published?" (this
  validator) from "does the data match the methodology?" (Chat 6's
  QC validator, which uses Toth 2025's SOP thresholds).

**Negative / costs.**

- If USGS issues a new release with revised metadata, we have to update
  the constants manually.  Acceptable: the metadata file is short
  enough to re-diff in minutes.
- A reviewer used to "validate against the paper" might be initially
  surprised.  Mitigated by the docstring at the top of `validation.py`
  spelling out the sourcing.

#tags: validation, exif, metadata, constants, sources-of-truth
