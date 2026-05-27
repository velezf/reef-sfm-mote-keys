# ADR 0009 — USGS data release distributes Photoshop-re-encoded TIFFs derived from CR2 RAW; capture-time EXIF tags are absent but methodologically irrelevant given the team's bundle-adjustment-driven workflow; CSV becomes canonical for metadata that survives

Status: Accepted  
Date: 2026-05-27  
Chat: 4

## Context

During Chat 4 acquisition, `exif_data.csv` from the IDS export (see
[ADR-0008](0008-ids-viewer-csv-export-primary-acquisition-path.md)) and a
downloaded EDR TIFF were inspected to determine whether the CSV could augment
or replace on-disk EXIF reads in `validate-intake`.  Three layered findings,
plus supplementary confirmation from the paper.

**Finding A — `exif_data.csv` is a rights/identity export, not a camera
technical export.**

28 columns × 39,480 rows (all sites).  EDR has 3,271 rows, matching the
download count exactly.  Fields present include: `cammake`, `cammodel`,
`artist`, `copyright`, `dtoriginal` (ISO 8601 with explicit UTC offset,
e.g. `2023-07-12 14:39:55+00:00`), `image_id` (stable integer PK, unique per
row), and per-event `lat` / `lng`.  Fields absent: `ExposureTime`, `FNumber`,
`ISO` / `ISOSpeedRatings`, `FocalLength`, `ExifImageWidth`, `ExifImageHeight`,
`Orientation`.

Six columns are 100% null across all 39,480 rows and carry no information:
`event`, `pid`, `gpsdate`, `gpstime`, `dtdigitized`, `contributor`.  The
`externalmetadata` column contains PIR API URLs pointing to USGS deployment
records (`https://www1.usgs.gov/pir/api/identifiers/USGS:…`).

The `gpsareainformation` field states: *"station coordinates obtained from
handheld GPS; individual images are not georeferenced."*  EDR has 3 unique
station coordinates corresponding to 3 dive events (UUID `80e7c677`: 2,424
images; two smaller events at 522 and 325 images).  This matches Toth et al.
2025 Table 1, which lists EDR with three subsites surveyed in 2023 (EDR\_T1,
EDR\_T3, EDR\_T8 per ESM Table S1).  Independent metadata sources confirm the
same physical reality.

**Finding B — Downloaded TIFFs are Photoshop re-encodes with the Exif sub-IFD
stripped.**

The `Software` EXIF tag reads `Adobe Photoshop 24.6 (Windows)`.  What
survived: rights block, image dimensions (4000 × 3000), `Make`, `Model`,
`Orientation`.  What was stripped: the entire Exif sub-IFD — `DateTimeOriginal`,
`ExposureTime`, `FNumber`, `ISOSpeedRatings`, `FocalLength` are all absent.
The `DateTime` tag that remains reflects the Photoshop save timestamp
(e.g. `2023:07:14 10:37:50` for a file whose filename prefix is `20230711_`),
not the capture time.  Reading `DateTime` from these TIFFs expecting capture
time is wrong by days.

**Finding C — The TIFFs are the team's actual Metashape input files, not a
downstream archival derivative.**

Per Toth et al. 2025 main text (page 9), the S120 was set to RAW capture mode.
Per ESM Table S2 Step 2, the team's documented workflow converts CR2 RAW to
LZW-compressed TIFF via Adobe Photoshop's Image Processor batch tool and feeds
those TIFFs directly into Metashape.  The TIFFs in the data release are those
working files.  The metadata loss is baked into the published methodology, not
introduced by data-release preparation.  Any reproduction of this method on
this dataset should expect, and validate against, the same metadata profile.

**Supplementary: the methodology does not depend on EXIF priors.**

ESM Step 6 documents that the team runs least-squares bundle adjustment for
lens calibration on every transect, scaled by 3–4 coded 25-cm scale bars (ESM
Step 7).  Camera intrinsics are solved from over-constrained imagery geometry.
The pipeline is robust to the metadata absence observed here.

**Open questions.**

1. The `GPSInfo` IFD pointer exists at offset 27002 in the on-disk EXIF but
   was not parsed in the initial inspection.  Almost certainly the same
   station coordinate copied per file; low-priority verification.

2. The IDS export has 3 unique GPS coordinates for EDR (matching 3 dive
   events), while ESM Table S1 distinguishes three named subsites (EDR\_T1,
   EDR\_T3, EDR\_T8).  The UUID → subsite mapping is not directly stated in
   either source; recoverable by inspecting filenames, since the naming
   convention is `YYYYMMDD_EDR_T#_*`.

See also [ADR-0010](0010-adopt-toth-usgs-metashape-workflow.md) for the
decision to adopt Toth et al. 2025's published Metashape workflow and tooling
as the Chat 5 implementation reference, including the parameter table that
supersedes PIFSC SOP values where they conflict.

## Decision

1. **`exif_data.csv` becomes the canonical source within `validate-intake`
   for:** filename ↔ `image_id` mapping, count validation,
   `cammake` / `cammodel` verification, `artist` / `copyright` / rights
   validation, and `dtoriginal` (UTC-clean capture time, joined by
   `image_id`).  This is more efficient than 3,271 individual file opens and
   recovers timestamp information that the on-disk EXIF no longer carries.

2. **On-disk reads remain for:** file existence, file size, SHA-256 hash,
   `ImageWidth` / `ImageLength` cross-check (absent from CSV), `Orientation`,
   verification that the file is a readable TIFF, and the `Software` tag as
   on-disk evidence of the documented RAW→TIFF lineage.

3. **The QC report explicitly surfaces metadata provenance as a documented
   finding**, distinguishing which tags originated in the CR2 capture, which
   were preserved through Photoshop's TIFF export, and which were lost.  This
   is the QC layer functioning correctly to surface provenance-relevant lineage
   from a published methodology that does not itself document its own metadata
   loss.  Captured in the QC report schema as a structured field
   (e.g. `missing_exif_tags: [ExposureTime, FNumber, ISOSpeedRatings,
   FocalLength, DateTimeOriginal]`), not prose.

4. **The `validate-intake` refactor to CSV-primary is deferred to its own
   commit.**  This ADR records the finding and the decision; implementation
   follows separately.

## Consequences

**Positive.**

- Count validation and rights-field validation run without opening any image
  file, using the already-downloaded CSV.
- `dtoriginal` from the CSV is timezone-unambiguous.  The on-disk `DateTime`
  tag is unusable for capture time; without this ADR that would be a silent
  error.
- Structured `missing_exif_tags` in QC output ensures downstream consumers
  see the lineage gap without parsing prose.
- Finding C closes the methodological gap: the TIFFs are not a degraded
  version of the working dataset; they *are* the working dataset.

**Negative / costs.**

- **Chat 5 alignment risk is LOW.**  ESM Steps 5–8 document the
  bundle-adjustment-with-coded-scale-bars approach explicitly.  The pipeline
  does not depend on EXIF focal length.  This project's TIFFs match the
  published methodology's input files.  The optional sensitivity test (align a
  20–30 image subset with and without manual focal length override of 5.2 mm)
  is now strictly academic — interesting for the write-up, not necessary for
  reproduction.  Time-box to ≤30 minutes if pursued.

- **Exposure triangle parameters** (`ExposureTime`, `FNumber`, `ISO`) are
  unused by Metashape for SfM math.  Their absence does not affect
  reconstruction.

- **`DateTime`-as-modification-timestamp is a silent trap.**  Any code that
  reads `DateTime` from these TIFFs expecting capture time will be wrong by
  days.  Canonical rule: always use the CSV's `dtoriginal` for capture time.

- **On-disk file size is larger than the original 5 GB estimate.**  The
  originals were CR2 RAW (typically 10–12 MB per file on the S120); per ESM
  Step 2 the team converts these to LZW-compressed TIFF, which is typically
  5–10 MB per file.  Total EDR volume on disk is likely 20–30 GB rather than
  the ~5 GB initial estimate; verify post-download with
  `du -sh /data/raw/P1WHKTRD/EasternDryRocks/` and record the actual value in
  `docs/04-data-acquisition.md`.

- **Finding generalizes.**  Any future USGS data release using the same
  RAW → Photoshop → LZW-TIFF workflow may exhibit identical metadata loss.
  The reusable provenance package built in Chat 6 should include a documented
  automated check: flag files whose `Software` tag contains `Adobe Photoshop`
  and whose Exif sub-IFD is absent.

## Three-layer metadata picture (added 2026-05-27 after full-dataset run)

Full-dataset validate-intake against 3,271 EDR files refined the original Finding B about
USGS's Photoshop re-encoding behavior.  The metadata loss is not monolithic; it is structured
by metadata-block type:

- **EXIF sub-IFD: stripped.**  `ExposureTime`, `FNumber`, `ISOSpeedRatings`, `FocalLength`,
  `DateTimeOriginal` all absent — confirmed at full-dataset scale.  `DateTime` present but
  reflects the Photoshop save timestamp, not capture time.

- **IPTC Credit: preserved.**  Present on every file with value `'U.S. Geological Survey'`.
  The IPTC block survived USGS's Photoshop re-encoding intact alongside the XMP block.  USGS
  does not include Mote Marine Laboratory in the IPTC Credit even though Toth et al. 2025
  authorship includes both institutions; this is an authorial decision, not a metadata-loss
  artifact.  The previous version of this addendum claimed "IPTC Credit: absent" — that was
  a rule-design artifact (the rule hardcoded `'U.S. Geological Survey, Mote Marine
  Laboratory'` as the expected string); corrected in a subsequent commit.

- **XMP attribution URL: preserved.**  Adobe Photoshop is the canonical XMP implementation
  and preserves XMP blocks by default on TIFF export.  `XMP:AttributionURL`,
  `XMP:ExternalMetadataLink`, and `XMP:UsageTerms` all present — confirmed at full-dataset scale.

- **TIFF baseline tags: preserved.**  `Make`, `Model`, `Artist`, `Copyright`,
  `ImageDescription`, `Orientation`, width, height all survive Photoshop re-encoding
  without modification.

The Photoshop pipeline strips one specific thing — the EXIF sub-IFD — and preserves the IPTC,
XMP, and TIFF baseline blocks intact.  Validators reading future USGS releases produced by
similar pipelines should expect this specific pattern, not generic "metadata loss."

#tags: exif, tiff, photoshop, cr2, raw, metadata-loss, validate-intake, csv, dtoriginal, focal-length, metashape, bundle-adjustment, provenance, lzw
