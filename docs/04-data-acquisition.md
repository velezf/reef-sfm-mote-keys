# 04 — Data acquisition and intake validation

This document explains what Chat 4 added to the project and how to operate
it.  It is written for the next person (probably future me, possibly a
collaborator at Mote or USGS) who needs to reproduce the EasternDryRocks
intake from a fresh EC2 instance.

## What this layer does

It pulls the EasternDryRocks subset of the USGS P1WHKTRD image release
([Johnson et al. 2025](https://doi.org/10.5066/P1WHKTRD)) onto the EC2
secondary data volume, computes per-image SHA-256 hashes during streaming
download, catalogs every image, and emits a structured intake QC report.

The report is the input gate to Chat 5 (Metashape processing).  Anything
that fails here should be triaged before burning Metashape trial days on a
reconstruction.

## Data sources

| Release | DOI | Size | Used for |
|---|---|---:|---|
| P1WHKTRD raw images (Johnson et al. 2025) | `10.5066/P1WHKTRD` | ~5 GB site subset | SfM input |
| P13HMEON SfM products (Toth et al. 2025a) | `10.5066/P13HMEON` | ~5 GB site subset | reconciliation targets (Chat 6) |

Both releases are CC0 licensed.  The image release has 39,840 TIFs across
11 sites; we pull only the EasternDryRocks subset (~1,500–3,000 images).

## How to run it

The expected workflow is from a `tmux` session on the EC2 instance.  The
download happens entirely server-side (ScienceBase → EC2), so SSH drops to
the operator's laptop don't affect it, but `tmux` also keeps the validate
and contact-sheet steps running cleanly across disconnects.

```bash
# On the EC2 instance, in tmux:
cd ~/reef-sfm-mote-keys
./scripts/04_acquire_and_validate.sh /data
```

The script runs three subcommands:

```bash
reef-sfm acquire         --out-dir /data/raw/P1WHKTRD --site EasternDryRocks
reef-sfm validate-intake /data/raw/P1WHKTRD/EasternDryRocks --write-inventory
reef-sfm contact-sheet   /data/raw/P1WHKTRD/EasternDryRocks --out-dir /data/figures/contact_sheets/EasternDryRocks
```

Expected timing (g6.4xlarge, cmgds.marine.usgs.gov as source):

| Step | Time |
|---|---|
| `acquire` (cold, `--max-workers 8`) | 60–90 min |
| `acquire` (cold, `--max-workers 1`) | ~11 hours |
| `acquire` (resume, hashes verified) | 1–2 min |
| `validate-intake` | 3–5 min |
| `contact-sheet` (~2000 images, 6×6 sheets) | 4–7 min |

The bottleneck on cmgds is per-connection latency (~5 files/min serial),
not bandwidth.  Eight concurrent workers give ~40 files/min, which
brings a 3,271-file EasternDryRocks pull to ~80 minutes.  Override the
default with `--max-workers N` or the `MAX_WORKERS` env var in the shell
script.

## Outputs

Everything lands under `/data/raw/P1WHKTRD/EasternDryRocks/`:

| File | What |
|---|---|
| `<n_images>.tif` | the actual TIFFs |
| `_provenance.json` | per-file: URL, SHA-256, byte size, ScienceBase parent item ID, download timestamp |
| `intake_inventory.json` | per-file: dimensions, full EXIF/XMP/IPTC, hash |
| `intake_qc_report.md` | human-readable QC report, copy/pasteable into the Chat-8 writeup |
| `intake_qc_report.json` | structured QC report, consumed by Chat 6's processing manifest |

Contact sheets land under `/data/figures/contact_sheets/EasternDryRocks/`.

## What "valid" looks like

The QC validator checks expectations explicitly stated in the P1WHKTRD
metadata file.  Each rule emits one of four severities:

- **ok** — matches USGS-published expectation
- **warn** — flagged for review but not blocking
- **fail** — blocking; should be triaged before Chat 5
- **unverified** — tooling couldn't check (e.g. `exiftool` not installed,
  so XMP fields can't be read)

### Per-image rules (one finding per image)

| Code | Source | Severity on mismatch |
|---|---|---|
| `camera_consistency` | `EXIF:Make` = `Canon`, `EXIF:Model` ⊇ `PowerShot S120` | fail |
| `dimensions` | 4000×3000 native S120 resolution | warn |
| `exif_artist` | `USGS St. Petersburg Coastal and Marine Science Center` | fail |
| `exif_copyright` | `Public Domain` | fail |
| `datetime_original` | within 2022-07-10 … 2023-07-19 | warn |
| `gps_present` | inside survey bbox (24.45–24.62 N, −81.88–−81.36 W) | fail |
| `xmp_attribution_url` | matches `https://doi.org/10.5066/P1WHKTRD` | fail when read, unverified when not |
| `iptc_credit` | `U.S. Geological Survey, Mote Marine Laboratory` | fail when read, unverified when not |

### Dataset-level rules (one finding per dataset)

| Code | Check |
|---|---|
| `file_count` | 1000–5000 images expected for an offshore site |
| `dataset_camera_consistency` | exactly one (make, model) pair across the site |
| `hash_uniqueness` | no two files share a SHA-256 |
| `gps_consistency` | exactly one surface-station coordinate across the site (GPS does not work underwater) |
| `size_outliers` | flags files below 40% of the median size — usually lens-cap-on transect ends |

## When `validate-intake` reports failures

The Markdown report names the first 20 files that failed each rule; the
JSON report has the complete list.  Common findings and what they mean:

- **`xmp_*` and `iptc_*` unverified, everything else ok.**  `exiftool` isn't
  on PATH.  `apt install libimage-exiftool-perl` and re-run; Pillow alone
  can't read XMP fields.
- **`gps_consistency` warns or fails with multiple distinct fixes.**  All
  images at one site must share *one* surface coordinate — GPS doesn't
  penetrate seawater, so there is no per-image fix, only a per-site one
  written by ExifTool.  A warn means two close fixes (likely a re-survey
  day got its own handheld fix); a fail means clearly different sites got
  merged into one directory.  Inspect `details.fixes` in the JSON.
- **`file_count` warns at <1000.**  IDS viewer subset may have been
  filtered too aggressively (e.g. only one transect selected).  Re-run
  `acquire` with `--site EasternDryRocks` and confirm child item titles.

## Snapshot the data volume

After a clean validation, snapshot the data volume.  This is the recovery
point: a Metashape mis-step in Chat 5 should never force a re-download.

```bash
aws ec2 create-snapshot \
    --volume-id "${DATA_VOLUME_ID}" \
    --description "reef-sfm-mote-keys: post-Chat-4 EasternDryRocks intake QC pass" \
    --tag-specifications 'ResourceType=snapshot,Tags=[{Key=Project,Value=reef-sfm-mote-keys},{Key=Stage,Value=post-intake}]'
```

Record the resulting snapshot ID in the project's provenance log
(`docs/aws-resources.md` — created in Chat 2).  Chat 6's processing manifest
will reference it as the data lineage anchor.

## Why this exists at all

USGS's published pipeline produces the SfM products and the metadata
record, but the *intake validation step is not formalized* — no shipped
checker, no published rule list, no machine-readable QC artifact.  The
expectations are spread across the metadata text file and the
methodological papers.  Encoding them as code does three things:

1. **Catches regression**: if USGS re-releases the dataset with different
   EXIF expectations, our `validation.py` constants will diverge from the
   metadata and the tests will fail loudly.
2. **Generates a citable QC artifact**: the JSON report is fixed-schema
   (`reef-sfm-provenance/intake_qc/v1`), versioned, hostname-stamped,
   and feeds the processing manifest in Chat 6.
3. **Makes the pipeline portable**: any restoration program with a
   ScienceBase-published image release and a similar metadata convention
   can swap in their own expectations.

This is the start of the enterprise data management layer the project is
built around; Chats 5–7 extend it with processing manifest, QC validator,
and metric reconciliation.

## Files added by Chat 4

```
src/reef_sfm_provenance/
├── __init__.py
├── __main__.py            # reef-sfm CLI entry point
├── acquisition.py         # USGS ScienceBase walk + streaming download
├── inventory.py           # EXIF/XMP/IPTC cataloging
├── validation.py          # rule engine (per-image + dataset)
├── intake_report.py       # JSON + Markdown report writer
└── contact_sheet.py       # JPEG contact-sheet generator

tests/
├── conftest.py            # shared fixtures (good_record, good_dataset)
├── test_acquisition.py    # network-free acquisition tests
├── test_inventory.py      # synthesized TIFF round-trip tests
├── test_intake_report.py  # report shape and severity aggregation
└── test_validation.py     # rule engine (36 tests, no network)

notebooks/04_intake_inventory.ipynb
scripts/04_acquire_and_validate.sh
docs/04-data-acquisition.md
```

## References

- Johnson, S. A., L. T. Toth, C. M. Jenkins, E. O. Lyons, 2025, Diver-Based
  Structure-from-Motion imagery from coral reef restoration surveys in the
  Lower Florida Keys: July 2022 and July 2023, U.S. Geological Survey data
  release, <https://doi.org/10.5066/P1WHKTRD>.
- Toth, L. T., et al., 2025a, Carbonate budgets, structure-from-motion
  products, and topographic complexity measurements from restored and
  non-restored areas of coral reefs in the Lower Florida Keys, U.S.
  Geological Survey data release, <https://doi.org/10.5066/P13HMEON>.
- Combs, I. R., et al., 2021, Quantifying impacts of stony coral tissue
  loss disease on corals in Southeast Florida through surveys and 3D
  photogrammetry, PLOS ONE, <https://doi.org/10.1371/journal.pone.0252593>.
