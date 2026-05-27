# ADR 0003 — ScienceBase REST is the primary acquisition path; manifest CSV is the fallback

Status: Accepted
Date: 2026-05-27
Chat: 4

## Context

USGS publishes the EasternDryRocks imagery in two ways:

1. The ScienceBase REST API at `sciencebase.gov/catalog/...`, which
   serves a hierarchical item-and-files tree as JSON.
2. The IDS viewer at `cmgds.marine.usgs.gov/idsviewer/data_release/...`,
   a JavaScript app fronting the same data with site filters, a "download
   cart" UI, and the ability to export a CSV of selected file URLs.
   `robots.txt` blocks scraping the viewer itself.

We need a "give me EasternDryRocks" interface, and we need it to keep
working if USGS reorganizes the layout.

Two failure modes worry me:

- **The API walk breaks.**  ScienceBase changes its parent/child layout
  (e.g. one parent per field activity instead of one per site), and the
  `_looks_like_site` filter stops matching the right children.
- **Site naming changes.**  A future release uses `Eastern_Dry_Rocks`
  with no normalization in the title, or splits one site into multiple
  child items.

If either happens, the project plan's "don't burn the trial clock"
discipline says we must not block on debugging the walk.

## Decision

The acquisition module supports two enumeration paths:

- **Primary (`enumerate_files_for_site`).** Walk ScienceBase from the
  DOI down.  This is the default; it is fully automated and produces
  the same provenance regardless of whether the operator ran it locally
  or in a CI job.
- **Fallback (`read_manifest_csv`).** Accept any CSV with at minimum a
  `url` column, optionally `name`, `size`, and `parent_item_id`.  This
  matches the shape of the IDS viewer's download-cart export, and is
  also trivial to hand-author.  Pass `--manifest path.csv` on the CLI
  to use it.

Both paths hand back the same `list[RemoteFile]` and feed the same
`download_all` step.

## Consequences

**Positive.**

- The download pipeline never blocks on a ScienceBase API regression.
  If the walk returns zero matches, the operator drops to the manifest
  path in minutes.
- Other restoration programs whose data lives somewhere else (CRF, a
  TNC release, a local dive log) can drive `download_all` from a
  manifest without changing any code.
- Tests cover the manifest path with no network access; the API path
  is covered separately by a planned integration test on EC2.

**Negative / costs.**

- Two code paths to keep working.  We accept this; the manifest path is
  ~20 lines and rarely changes.
- The fallback adds a step ("export from IDS viewer, scp to EC2") that's
  manual and slightly off-script.  Mitigated by documenting it in
  `docs/04-data-acquisition.md`.

#tags: sciencebase, acquisition, fallback, manifest, csv, ids-viewer
