# ADR 0006 — exiftool is an optional batched subprocess, not a hard dep

Status: Accepted
Date: 2026-05-27
Chat: 4

## Context

The intake validator needs to read three EXIF/XMP/IPTC field families:

1. Core EXIF (`Make`, `Model`, `Artist`, `Copyright`, GPS, etc.).
   Pillow reads these natively.
2. XMP fields (`AttributionURL`, `ExternalMetadataLink`, `UsageTerms`).
   Pillow cannot read these.
3. IPTC fields (`Credit`, `Contact`).  Pillow cannot read these.

Options for the XMP/IPTC reads:

- **Add a Python XMP library** (e.g. `python-xmp-toolkit`).  Requires the
  Exempi C library on the host, which is non-trivial to install on some
  platforms.
- **Roll our own XMP parser.**  XMP is RDF/XML embedded in a TIFF tag.
  Doable but not cheap to make robust.
- **Shell out to `exiftool`.**  Authoritative on EXIF/XMP/IPTC, ships on
  most Linux distros as `libimage-exiftool-perl`, and the USGS lineage
  shows USGS themselves used exiftool to *write* these headers.  Using
  the same tool to read them rules out a class of subtle parser bugs.

The cost of shelling out to a subprocess per image is roughly 0.5s of
exiftool startup * N images.  For 2000 images that's ~17 minutes of pure
overhead.  But exiftool natively accepts many file arguments in one
invocation: `exiftool file1 file2 ... fileN` shares the startup once.

## Decision

`inventory.py` reads core EXIF with Pillow always, and XMP/IPTC with
exiftool when it's on PATH.  When exiftool is absent, the XMP/IPTC
fields are returned as `None` and the corresponding validator rules emit
`unverified` (per ADR-0005).

The exiftool invocation is batched: 200 files per subprocess call by
default.  Single startup cost amortizes across the batch; a 2000-image
site runs ~10 exiftool subprocesses, total wall time ~5 seconds.

Auto-detection (`use_exiftool=None`) is the default; the parameter can
be forced on or off for tests and CI.

## Consequences

**Positive.**

- The package installs without any C dependencies — `pip install -e .`
  on a fresh Ubuntu DLAMI works immediately.
- exiftool is available via `apt install libimage-exiftool-perl` (single
  package, ~5MB) when we want the full XMP/IPTC checks.  Documented in
  `docs/04-data-acquisition.md`.
- Symmetry with USGS: they wrote the headers with exiftool, we read them
  with exiftool.  Eliminates a category of parser-mismatch bug.
- Batched-subprocess design is roughly 100x faster than naive per-image
  invocation.  Not a thing the operator has to think about.

**Negative / costs.**

- Subprocess + JSON parsing is more code than `from xmp_toolkit import
  XMPMeta; XMPMeta().parse_from_str(...)`.  Worth it for the install
  story.
- Failure modes specific to subprocess invocation: PATH not set inside
  a service unit, exiftool segfaulting on a malformed file, etc.  We
  handle PATH absence (graceful degrade), but a crashing exiftool could
  silently drop some records.  Mitigated by capping subprocess timeout
  and logging non-zero exit codes; defense in depth is the `unverified`
  severity surfacing the gap to the operator.

#tags: exiftool, dependencies, subprocess, xmp, iptc, performance
