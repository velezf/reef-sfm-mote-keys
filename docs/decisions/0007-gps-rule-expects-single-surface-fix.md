# ADR 0007 — GPS rule expects exactly one surface-station fix per site

Status: Accepted
Date: 2026-05-27
Chat: 4

## Context

The first cut of `_check_gps_consistency` (Chat 4 morning) treated the
per-image GPS as if it had real per-image spread.  The rule passed if
the bounding box of all per-image lat/lons was within ~5m, on the
assumption that drift or rounding could explain small spreads.

This is wrong on the underlying physics.  GPS signals do not penetrate
seawater.  A diver at depth has no GPS lock; there is no per-image fix
to drift.  The published USGS workflow takes a single handheld-GPS
reading at the surface above the transect *before the dive*, and
ExifTool stamps that one coordinate pair into every image in
postprocessing.

The expected on-disk state is therefore: **one unique (lat, lon) pair
across every image at a site, full stop.**  Zero spread.

A spread > 0 is not "drift".  It's either:

- a re-survey day where the dive team took a fresh handheld fix (a few
  meters away), and someone merged the two days into one directory —
  worth a `warn`, fixable; or
- two different sites' images mixed into one directory — a real bug,
  fail.

## Decision

`_check_gps_consistency` checks `len(set(coords))`:

- **1 unique fix** → `ok`.  This is the only physically expected state.
  Message names the coordinate and explicitly notes the physics:
  "GPS does not work underwater."
- **2 unique fixes within ~25m of each other** → `warn`.  Re-survey day,
  likely.  The QC report calls out both fixes for review.
- **>2 unique fixes, or any spread >25m** → `fail`.  Looks like a
  directory merge bug; refuse to proceed.

## Consequences

**Positive.**

- The rule's behavior now matches physical reality.  A reviewer at USGS
  or Mote reading the QC report will not have to mentally translate
  "5m spread is fine" into "wait, there's no per-image GPS to spread".
- Catches a real bug class — mixed-site directories — that the loose
  bounding-box version did not flag.
- The `ok` message is now educational: anyone reading the JSON report
  who didn't know GPS doesn't work underwater learns it from the QC
  output.

**Negative / costs.**

- The fixture in `tests/conftest.py` (1500 records all sharing one
  fix) was already correct under the new rule, but new edge-case tests
  had to be added explicitly for the warn and fail branches.
- This rule will be wrong for any future site whose imagery comes from
  a system that *does* have per-image georeferencing (sonar with USBL,
  surface-towed photogrammetry rigs, AUV imagery).  Those will fail
  here.  Acceptable for now — none of the Lower Florida Keys sites
  in P1WHKTRD use such systems — but flag this when Chat 9's v2
  roadmap is drafted, in case multi-program reuse needs a per-platform
  GPS validator.

## Supersedes

The Chat-4-morning version of `_check_gps_consistency`.  No prior ADR
to formally supersede; the change is documented here as the rule's
first ADR.

#tags: gps, validation, physics, underwater, sites, multi-site
