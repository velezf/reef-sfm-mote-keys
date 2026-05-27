# IDS Viewer export bundle for USGS data release P1WHKTRD

Source: https://cmgds.marine.usgs.gov/idsviewer/data_release/10.5066-P1WHKTRD
Downloaded: 2026-05-27
Bundle name: ImageryDataSystem_20260527133458

Located under `data/reference/` (tracked) rather than `data/raw/`
(gitignored bulk cache) because the validator depends on this CSV at
clone time. Re-fetchable from the IDS viewer if needed, but treated as
a stable reference asset.

This directory contains the relevant subset of the IDS viewer's "Download all
details" export. The full bundle contained three CSVs:

  - `image_data.csv`  (29 MB, 39,481 rows × 25 cols) — image-level metadata
  - `exif_data.csv`   (48 MB, 39,480 rows × 28 cols) — rights/identity export
  - `keyword_data.csv` (32 MB) — keyword tags

Per ADR-0009 (`docs/decisions/0009-*.md`), `exif_data.csv` is the canonical
source for filename → image_id mapping, cammake/cammodel verification,
artist/copyright validation, and `dtoriginal` (UTC-clean capture time).
The other CSVs from the bundle are not currently consumed by this project
and are excluded to keep repo size manageable.

Schema notes:
  - 6 columns are 100% null across all rows and can be dropped on ingest:
    `event`, `pid`, `gpsdate`, `gpstime`, `dtdigitized`, `contributor`
  - `gpsareainformation` documents: station coordinates per dive event,
    NOT per-image
  - `externalmetadata` contains PIR API URLs to USGS deployment records
