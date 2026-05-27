# ADR 0008 — IDS viewer CSV export is the primary acquisition path

Status: Accepted  
Supersedes: [ADR-0003](0003-sciencebase-api-primary-manifest-csv-fallback.md) (role assignment only — ADR-0003's code is retained but demoted to dead fallback)  
Date: 2026-05-27  
Chat: 4

## Context

ADR-0003 designated the ScienceBase REST API as the primary acquisition
path and the IDS viewer CSV as a manual fallback.  Two compounding failures
on 2026-05-27 morning made that assignment untenable.

**Failure 1 — API DOI filter is broken for this release.**  
The DOI filter syntax USGS documents at
usgs.gov/sciencebase-instructions-and-documentation/building-search-queries
(`filter=itemIdentifier={type:DOI,key:doi:10.5066/P1WHKTRD}`) returns
HTTP 400 for the EasternDryRocks data release.  The endpoint is
reachable; it simply rejects the query that its own documentation
prescribes for this kind of identifier.

**Failure 2 — sciencebase.gov full outage.**  
On the same morning, sciencebase.gov went completely down.  Both the EC2
build host and the operator's MacBook received empty response bodies for
every sciencebase.gov request.  Requests to google.com from the same
hosts returned HTTP 200, ruling out local network issues.  The outage
was confirmed independently from two separate networks.

Meanwhile, the IDS viewer export worked without interruption.  The
"Download all details" button in the IDS viewer at
`cmgds.marine.usgs.gov/idsviewer/data_release/...` emits a ZIP
containing:

- **`image_data.csv`** — one row per image; the `public_path` column
  holds direct `cmgds.marine.usgs.gov` URLs that do not go through
  ScienceBase at all.
- **`exif_data.csv`** — EXIF metadata for every image in the export,
  usable as a free pre-download validation source without touching any
  USGS API.

`scripts/manifest_from_ids_export.py` reshapes `image_data.csv` into the
`manifest.csv` format that `reef-sfm acquire --manifest` already accepts.

## Decision

The IDS viewer CSV export is now the **primary** (and only tested) acquisition
path.  The operator runs:

```
reef-sfm acquire --manifest path/to/manifest.csv
```

where `manifest.csv` is produced by `scripts/manifest_from_ids_export.py`
from the IDS viewer ZIP export.

The `find_item_by_doi` / `enumerate_files_for_site` code path (ADR-0003
primary path) is retained in `acquisition.py` but is marked deprecated
and is not called by the CLI.  It is not removed because the underlying
`_get` / `fetch_item` plumbing remains useful for ad-hoc inspection.

`exif_data.csv` from the same IDS export is used as a pre-download
validation source: expected GPS bounding box, expected image count, and
expected file sizes are derived from it, so the validation step runs
without downloading any data.

## Consequences

**Positive.**

- The acquisition path no longer touches sciencebase.gov at all.  A
  repeat outage or API change cannot block a download run.
- `exif_data.csv` gives us richer pre-download validation (per-file sizes,
  GPS coordinates) than the ScienceBase item metadata did.
- `scripts/manifest_from_ids_export.py` is a thin, testable transform
  with no network dependency; it can be re-run offline from a cached ZIP.
- The `--manifest` CLI flag already existed (ADR-0003 fallback), so no
  interface changes are needed.

**Negative / costs.**

- One manual step is now required before every fresh acquisition: open the
  IDS viewer, click "Download all details", scp the ZIP to EC2, run the
  reshape script.  This is documented in `docs/04-data-acquisition.md`.
- If USGS restructures the IDS viewer export schema (column renames, ZIP
  layout changes), `manifest_from_ids_export.py` breaks silently unless
  the operator notices mismatched row counts.  Mitigated by the row-count
  assertion in the script.
- The deprecated ScienceBase code path stays in the tree and adds
  maintenance surface.  Accepted: it is clearly marked and small.

#tags: sciencebase, acquisition, ids-viewer, manifest, csv, outage, deprecated
