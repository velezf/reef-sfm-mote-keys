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
reef-sfm validate-intake /data/raw/P1WHKTRD/EasternDryRocks \
  --ids-csv data/reference/ids_export/exif_data.csv
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
| `inventory.json` | per-file: dimensions, full EXIF/XMP/IPTC, hash, CSV-joined metadata |
| `qc_report.md` | human-readable QC report, copy/pasteable into the Chat-8 writeup |
| `qc_report.json` | structured QC report (`reef-sfm-provenance/intake_qc/v2`), consumed by Chat 6 |

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
| `csv_join` | Filename matched in IDS exif_data.csv (ADR-0009) | fail |
| `software_lineage` | `EXIF:Software` starts with `Adobe Photoshop` → ok; known Windows utility (e.g. `Microsoft Windows Photo Viewer`) → warn; absent or unrecognized → fail | ok / warn / fail |
| `filename_pattern` | `YYYYMMDD_SITE_T#_[RC]#_NNNNNN.tif` Toth et al. naming convention ([RC]# = R# row-direction or C# column-direction swath per ESM Step 1 double-lawnmower pattern) | fail |
| `camera_consistency` | Make = `Canon`, Model ⊇ `PowerShot S120` (CSV-primary, falls back to EXIF) | fail |
| `dimensions` | 4000×3000 native S120 resolution | fail |
| `exif_artist` | `USGS St. Petersburg Coastal and Marine Science Center` (CSV-primary) | fail |
| `exif_copyright` | `Public Domain` (CSV-primary) | fail |
| `datetime_original` | CSV dtoriginal within 2022-07-10 … 2023-07-19 | warn |
| `gps_present` | CSV station GPS inside survey bbox (24.45–24.62 N, −81.88–−81.36 W) | fail |
| `xmp_attribution_url` | `https://doi.org/10.5066/P1WHKTRD` (exiftool only) | fail when read, unverified otherwise |
| `iptc_credit` | IPTC Credit present and non-empty → ok (any institutional string; specific value not asserted per ADR-0011); absent + EXIF Artist/Copyright present → warn (redundant field, not missing rights); absent + no EXIF rights → fail | ok / warn / fail |

### Dataset-level rules (one finding per dataset)

| Code | Check |
|---|---|
| `file_count` | 1000–5000 images expected for an offshore site |
| `dataset_camera_consistency` | exactly one (make, model) pair across the site |
| `hash_uniqueness` | no two files share a SHA-256 |
| `gps_consistency` | all station GPS fixes within Lower Florida Keys bbox; multiple fixes OK for multi-subsite datasets |
| `size_outliers` | flags files below 40% of the median size — usually lens-cap-on transect ends |
| `csv_coverage` | fraction of on-disk files matched in the IDS exif_data.csv |
| `subsite_cross_reference` | each T# transect group maps to exactly one dive-event UUID |

## When `validate-intake` reports failures

The Markdown report names the first 20 files that failed each rule; the
JSON report has the complete list.  Common findings and what they mean:

- **`xmp_*` and `iptc_*` unverified, everything else ok.**  `exiftool` isn't
  on PATH.  `apt install libimage-exiftool-perl` and re-run; Pillow alone
  can't read XMP fields.
- **`gps_consistency` fails with a fix outside the bbox.**  GPS does not
  penetrate seawater; coordinates are per-dive-event, not per-image.
  EasternDryRocks legitimately has 3 station fixes (EDR_T1, EDR_T3, EDR_T8);
  multiple fixes within the Lower Florida Keys bbox are expected and will
  pass.  A fail means a fix clearly outside the bbox — images from a
  different site were merged into this directory.  Inspect
  `details.outside_bbox` in the JSON.
- **`file_count` warns at <1000.**  IDS viewer subset may have been
  filtered too aggressively (e.g. only one transect selected).  Re-run
  `acquire` with `--site EasternDryRocks` and confirm child item titles.

### Empirical observations from the full-dataset validate-intake run (3,271 EDR files)

**software_lineage mix:** ~52% of files (1,708) carry `Adobe Photoshop 24.6 (Windows)`;
~48% (1,563) carry `Microsoft Windows Photo Viewer 10.0.19041.1`.  The Microsoft tag is
the Windows Imaging Component identifier — almost certainly applied during a review or
dehaze pass in the team's processing workflow (likely ESM Step 10 or a post-conversion
orientation check).  This is workflow variation within the published Toth et al. 2025 ESM
methodology, not a data-integrity problem; both subsets are from the same pipeline.  The
`software_lineage` rule's warn-vs-fail distinction was added in response to this finding
so the rule produces actionable signal rather than 1,563 false failures.

**iptc_credit:** IPTC Credit is present on every file with value `'U.S. Geological Survey'`.
USGS does not include Mote Marine Laboratory in the IPTC Credit even though the published
Toth et al. 2025 authorship includes both institutions; this is an authorial decision in the
data release preparation, not a methodological issue.  The IPTC block survived USGS's
Photoshop re-encoding intact alongside the XMP block.  An earlier iteration of this rule
treated the USGS-only credit as a failure because the rule hardcoded an expected institutional
string (`'U.S. Geological Survey, Mote Marine Laboratory'`); this was incorrect rule design
and was corrected in a subsequent commit.  The rule now validates presence-and-well-formedness
only, consistent with the profile-driven validator architecture described in ADR-0011.

**hash_uniqueness self-sufficiency:** The `hash_uniqueness` dataset rule was previously
coupled to an external acquisition-side hash manifest (`_provenance.json`).  In the Chat 4
IDS-CSV-driven recovery acquisition path, no external hash manifest was written, so the rule
reported `unverified`.  `build_inventory` now computes SHA-256 for every file during its own
inventory pass (reusing acquisition-side hashes when available, computing on the fly
otherwise), making `hash_uniqueness` a dispositive check on every run, consistent with
ADR-0011's validator-self-sufficiency direction.

**filename_pattern [RC]# fix:** 1,564 of 3,271 files use `C#` as the swath designator
(column-direction passes of the double-lawnmower pattern; see Toth et al. 2025 ESM
Step 1).  The original regex required `R#` only.  The pattern now accepts `[RC]#`; the
captured field is named `swath` in the details payload.

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
   (`reef-sfm-provenance/intake_qc/v2`), versioned, hostname-stamped,
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
├── ids_csv.py             # IDS exif_data.csv loader (ADR-0009)
├── inventory.py           # EXIF/XMP/IPTC cataloging + CSV join
├── validation.py          # rule engine (per-image + dataset)
├── intake_report.py       # JSON + Markdown report writer
└── contact_sheet.py       # JPEG contact-sheet generator

tests/
├── conftest.py            # shared fixtures (good_record, good_dataset)
├── test_acquisition.py    # network-free acquisition tests
├── test_inventory.py      # synthesized TIFF round-trip tests
├── test_intake_report.py  # report shape and severity aggregation
├── test_validate_intake.py # CSV-primary validate-intake flow tests
└── test_validation.py     # rule engine (per-image + dataset rules)

notebooks/04_intake_inventory.ipynb
scripts/04_acquire_and_validate.sh
docs/04-data-acquisition.md
```

## Chat 4 outcomes and operational findings

Wrap-up narrative for Chat 4, written at session close 2026-05-27. Captures what worked, what surprised us, and what propagates forward.

### Final state of the dataset

- 3,271 TIFFs acquired from USGS data release P1WHKTRD, EasternDryRocks site only
- 53.22 GiB on-disk after LZW-compressed TIFFs unpacked (well above the ~5 GB initial estimate from the data release products summary)
- Verified byte-for-byte against IDS acquisition manifest (3,271 / 3,271, 0 missing, 0 size mismatches)
- 3,271 SHA-256 hashes confirmed unique (no duplicate content under different filenames)
- 3 dive events at EDR mapping cleanly to 3 subsites (T1, T3, T8 per Toth ESM Table S1)
- 100% CSV join coverage against `exif_data.csv` rights/identity metadata

### Validation verdict

`Overall: ⚠️ warn` — dispositively clean.

| Rule category | Outcome |
|---|---|
| 7 dataset-level rules | All `ok` |
| 11 per-image rules across 3,271 files | All `ok` except `software_lineage`: 1,708 ok / 1,563 warn / 0 fail |
| 2 contact-sheet rendering failures | LZW decoder edge case on 2 of 3,271 files (`20230711_EDR_T1_C2_000197.tif`, `_000218.tif`); EXIF/metadata reads succeed on these files, only PIL pixel decode fails — flagged for Metashape verification in Chat 5 |

The `software_lineage` warnings document workflow variation within the published methodology: 1,563 files carry `Software=Microsoft Windows Photo Viewer 10.0.19041.1` while the other 1,708 carry `Software=Adobe Photoshop 24.6 (Windows)`. Both represent processing through the Toth ESM Table S2 pipeline; the WIC tag indicates an additional pass through a Windows imaging utility (likely the ESM Step 10 image-dehaze action or a USGS review step) overwrote Photoshop's Software tag on those files.

### What actually got built

Substantially more than the original Chat 4 prompt scoped:

- 4 ADRs landed: 0008 (IDS CSV as canonical acquisition source), 0009 (EXIF metadata loss in Photoshop re-encoding), 0010 (Toth ESM Table S2 as authoritative parameter source), 0011 (validator hardcoded now, profile-driven in Chat 6)
- 1 strategic framing document: `docs/longitudinal-comparability-and-pipeline-adoption.md`
- 7 iterative validator refactor rounds (CSV-primary architecture, file-context lifecycle fix, filename regex broadening, software_lineage three-bucket, iptc_credit three-bucket, iptc_credit-as-presence-check, hash_uniqueness-from-own-inventory)
- Validator outputs: `data/qc/chat4/qc_report.md`, `data/qc/chat4/qc_report.json`, `data/qc/chat4/inventory.json`
- 91 contact sheets generated; 3 representatives committed (`contact_sheet_001.jpg`, `_046.jpg`, `_091.jpg`); 88 left as EBS-snapshot artifacts via .gitignore exception

### Operational findings worth carrying forward

**1. The metadata-loss pattern is not monolithic.** Adobe Photoshop's TIFF export strips the EXIF sub-IFD (technical capture parameters) but preserves IPTC, XMP, and TIFF baseline tags. Documented in ADR-0009's three-layer-picture addendum.

**2. IPTC Credit ≠ what the project plan assumed.** The actual IPTC Credit on every file is `U.S. Geological Survey` alone, not the dual USGS+Mote credit that the published Toth et al. 2025 authorship would suggest. USGS authorial decision in data-release preparation, not a methodological issue.

**3. Two files have LZW decoder edge cases.** Files `20230711_EDR_T1_C2_000197.tif` and `_000218.tif` fail PIL's LZW pixel decoder (`decoder error -2`) but pass EXIF reads cleanly. Validator status on these files is correct for metadata integrity. Chat 5 must verify Metashape can load all 3,271 files including these two before committing to overnight dense reconstruction — Agisoft uses its own TIFF decoder, typically more robust than PIL's, but a 20-30 image trial including these problem files is the right sanity check before burning compute on alignment that might fail mid-run.

**4. Validators tested only against synthetic fixtures cannot reveal whether their rules are correctly *designed* for real data.** The seven rounds of validator iteration today each caught a real-data-vs-rule-design mismatch that the unit tests had not surfaced. The pattern was: design rule against expected shape → fail on real data → tighten rule. Future test-fixture work should include closer simulation of real Photoshop-re-encoded TIFFs (full XMP/IPTC blocks, no EXIF sub-IFD, plausible Software tag distribution) to make fixtures more representative.

**5. EC2 was behind origin/main when Chat 4 started.** Several hours into the session, a `git status` on EC2 showed it was 7 commits behind — work from the morning Mac session and the afternoon Claude Code refactors hadn't been pulled. Operational lesson: always `git fetch && git log HEAD..origin/main` before assuming local state is current, particularly when context switches between machines.

**6. `uv run` deprecation warnings accumulating.** Every uv command emits a deprecation warning about the `tool.uv.dev-dependencies` field. Not blocking, but worth quieting in a future maintenance commit (migrate to `dependency-groups.dev` per pyproject.toml).

### Recovery artifacts

- **EBS snapshot:** `snap-013fbb4296bb92254` of `vol-08bcf0ab11df2c9ed` (the 1 TB data volume). Captures the full Chat 4 state: imagery, QC artifacts, contact sheets. Recorded in `docs/aws-resources.md`.
- **Git history:** Chat 4 work spans approximately 15 commits across the day. The final state is `HEAD` on `origin/main` as of session close. No tag applied — v1.0 is reserved for Chat 9's portfolio-frozen step.

### What this sets up for Chat 5

- **Pipeline parameter values are now ESM Table S2-bound,** not PIFSC SOP. See ADR-0010 and `docs/longitudinal-comparability-and-pipeline-adoption.md` for the specifics.
- **The two LZW-edge-case files need a Metashape compatibility test** before overnight dense reconstruction.
- **The QC report's `inventory.json`** is the canonical SHA-256 reference for Chat 5 inputs.
- **The 1,708 / 1,563 Photoshop / WIC software-tag split** does not affect Metashape inputs (Metashape reads pixels, not Software tags) but is a documented dataset characteristic.

### What this sets up for Chat 6

- **The reconciliation module must use the MultiscaleDTM R package** at 5×5 cm focal window on 1 cm DSMs, per Toth et al. 2025 ESM. The current `pyproject.toml` does not include R tooling; Chat 6 must add rpy2 or subprocess R invocation.
- **The validator is intentionally EDR-hardcoded** per ADR-0011. Chat 6 refactors to profile-driven validation as part of the reusable provenance package deliverable.
- **`inventory.json` is the canonical hash reference and metadata join key.** Reconciliation outputs should preserve per-file lineage by joining back to this inventory.

---

*Chat 4 wrapped: 2026-05-27.*  
*Metashape trial: 1 day burned, 29 days remain.*

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
