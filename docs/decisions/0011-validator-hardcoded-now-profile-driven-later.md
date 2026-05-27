# ADR 0011 — The validate-intake validator is intentionally hardcoded for EDR in Chat 4; profile-driven generalization is deferred to Chat 6 as part of the reusable provenance package deliverable

Status: Accepted  
Date: 2026-05-27  
Chat: 4

## Context

The validate-intake validator was refactored substantially during Chat 4, in
roughly six iterative rounds:

1. **CSV-primary refactor** — adopted `exif_data.csv` as the canonical metadata
   source (see [ADR-0009](0009-exif-csv-and-tiff-encoding-metadata-loss.md)).
2. **Filename-pattern + subsite cross-reference rules** — added `TOTH_FILENAME_RE`
   and the T#-vs-CSV-UUID grouping rule.
3. **PIL file-context lifecycle bug fix** — exposed by the first full-dataset EC2
   run; `get_ifd()` was called after the `with Image.open()` block closed the file.
4. **Filename regex broadened from `R#` to `[RC]#`** — after the double-lawnmower
   swath designators surfaced in real filenames (1,564 of 3,271 EDR files).
5. **Software-lineage rule softened to ok / warn / fail** — after the
   Photoshop-vs-Microsoft-WIC software-tag split (~52% / ~48%) surfaced at
   full-dataset scale.
6. **IPTC-credit rule corrected** — from hardcoded-institutional-string-match to
   presence-and-well-formedness check after observing that IPTC Credit is absent
   on all 3,271 files while EXIF Artist and Copyright are fully populated.

Each round caught a real-data-vs-rule-design mismatch.  The pattern was consistent:
a rule was designed against the expected shape of the data based on documentation
(Toth et al. 2025 ESM, USGS metadata files, project plan assumptions), then the
rule failed on real data, then the rule was refined to reflect what the data
actually carries.  The rules are correctly calibrated for EDR at the end of Chat 4
because of this iteration, not despite it.

Through this iteration, dataset-specific values became embedded in rule
implementations:

- Filename regex is Toth-convention specific: `YYYYMMDD_SITE_T#_[RC]#_NNNNNN.tif`.
- Software-lineage allow-list is Photoshop-specific with Windows Imaging Component
  (WIC) as a known warn-bucket entry.
- GPS bounding box is EDR-region specific (24.45–24.62 N, −81.88–−81.36 W).
- Subsite cross-reference assumes the Toth UUID-per-dive-event structure.
- Metadata-lineage expectations are Photoshop-pipeline-specific: EXIF sub-IFD
  stripped, XMP preserved, IPTC Credit absent (see ADR-0009 addendum, "Three-layer
  metadata picture").
- File-count expected range is EDR-specific (1000–5000 files).

A reviewer reading the validator code today would correctly observe that it is not
a generic SfM intake validator but a P1WHKTRD-EDR-specific validator.  This is
true.  It is also intentional.

The portfolio framing of the project, including the strategic framing document
`docs/longitudinal-comparability-and-pipeline-adoption.md` (loaded into project
knowledge for Chats 5, 6, 8, 9), commits to a reusable provenance package as a
Chat 6 deliverable.  Reusability of the validator across datasets is therefore a
real eventual goal, and the current hardcoded shape is in tension with it.  This
ADR records the decision to accept that tension now and resolve it in Chat 6.

## Decision

1. **Chat 4 ships the validator in its current EDR-hardcoded form.**  Each rule
   was iteratively refined against real EDR data; the rules are correctly calibrated
   for this dataset.  The validator's outputs — `inventory.json`, `qc_report.json`,
   `qc_report.md` — are valid portfolio artifacts in their current form.  The
   "Overall: warn" verdict (after the `iptc_credit` fix) is the correct end-state
   for the Chat 4 validation pass.

2. **The validator will be refactored to a profile-driven architecture in Chat 6**
   as part of the reusable provenance package work.  The refactor will separate:

   - *Generic rule logic* (in code): "filename matches a configurable regex,"
     "software tag is in the configured allow-list," "GPS coordinates are within a
     configurable bounding box," "IPTC Credit is present and non-empty," etc.
   - *Dataset profile* (in a config file, likely YAML or TOML, at
     `data/reference/profiles/`): the EDR-specific values currently hardcoded —
     filename regex, software allow-list with bucket assignments, GPS bbox, expected
     metadata-lineage profile, file-count range, etc.

   The Chat 6 refactor will preserve current rule behavior bit-for-bit when run
   against EDR with its profile loaded.  The refactor is structural, not behavioral.

3. **The dataset profile schema is itself a Chat 6 design artifact** in scope for
   the structured-provenance work described in
   `docs/longitudinal-comparability-and-pipeline-adoption.md`.  The profile becomes
   the machine-readable, versioned, comparable representation of "what we expect
   this dataset to look like" — what makes longitudinal drift visible across reruns
   of the same validator against future USGS releases.

4. **The current validator's deferred-generalization is visible in the code.**  A
   header comment in `src/reef_sfm_provenance/validation.py` references this ADR
   and notes that EDR-specific values are inline pending the Chat 6 profile refactor.

## Rationale

The progression from "hardcoded EDR validator" to "profile-driven validator with
EDR as one profile" is more than a refactor scheduled for later.  It reflects a
substantive insight about how generic provenance tooling is built.

A profile-driven validator without ground-truth profiles is empty.  The profiles
themselves only exist because someone first ran a hardcoded checker against real
data and observed what the data actually contains.  The six-round iteration of
EDR-specific rules produced empirical observations — Photoshop strips the EXIF
sub-IFD but preserves XMP; software tags split ~52/48 between Photoshop and WIC;
IPTC Credit is absent despite adjacent EXIF rights fields being fully populated;
filenames carry both R# and C# swath designators — that become the EDR profile
when extracted.  Without the hardcoded validator's failure modes surfacing these
observations, a profile-driven validator would have shipped with default-permissive
rules and quietly passed every check, learning nothing about the data.

The relationship is therefore not "hardcoded checker is a stopgap, profile-driven
is the real thing."  It is "hardcoded checker is how you discover the profile;
profile-driven is how you preserve that discovery for reuse."  The two artifacts
are complementary, not substitutionary.  Future restoration programs — Mote Marine
Laboratory researchers, USGS partner organizations, longitudinal resurveys of the
same EDR site — need both: the hardcoded-first iteration to characterize their
data, and the profile-driven framework to record and apply what was learned.

This is a specific instance of the more general pattern the strategic framing
document (`docs/longitudinal-comparability-and-pipeline-adoption.md`) describes
for the broader project: structured data-management artifacts are valuable in
proportion to the empirical observations they encode.  A QC report is valuable
because of the findings it contains, not because of the validator framework that
produced it.  A dataset profile is valuable because of the metadata-lineage shape
it documents, not because of the validator that consumes it.  The validator is
infrastructure; the findings and profiles are the substantive output.

The Chat 4 validator is also structurally similar to what ADR-0010 describes for
the Metashape parameter adoption: dataset-specific parameter values were discovered
by reading the actual methodology documentation (Toth et al. 2025 ESM Table S2)
rather than assumed from generic references (PIFSC SOP).  In both cases the
correct path was to ground the implementation in the specific evidence first, then
abstract the pattern second.  The same approach here: ground the validator in EDR
evidence first (Chat 4), then abstract to a profile schema (Chat 6).

## Consequences

**Positive.**

- **Chat 4 deliverable shape is preserved.**  The `inventory.json`, `qc_report.json`,
  and `qc_report.md` artifacts are valid portfolio evidence in their current form.
  The "Overall: warn" verdict is the correct finding for the EDR dataset as
  characterized.

- **Chat 6 scope is now explicit.**  The reusable provenance package work in Chat 6
  must include: the profile schema design, the rule refactor to consume profiles,
  the EDR profile as the first written instance, and a second profile (drafted, not
  necessarily exhaustive) for at least one other USGS site or hypothetical future
  dataset, to demonstrate that the schema is genuinely generalizable rather than
  EDR-shaped.

- **The EDR profile becomes a first-class portfolio artifact.**  Once the refactor
  lands, the EDR profile is a structured, versioned, declarative record of what the
  EDR dataset looks like — directly comparable across longitudinal reruns and
  directly readable by future researchers.  This is the PFB-style structured-data
  thesis from `docs/longitudinal-comparability-and-pipeline-adoption.md` made
  concrete.

- **Writeup framing for Chat 8 is clarified.**  The Quarto page should not present
  the validator as a finished generic tool.  It should present the hardcoded-first /
  profile-driven-later progression as evidence of methodologically careful
  infrastructure development: design follows empirical observation, not the other
  way around.  This framing distinguishes the project from a tutorial demonstration
  of "here is how to validate SfM data."

**Negative / costs.**

- **The current validator is not reusable without modification.**  A researcher
  applying this code to a non-EDR USGS SfM release would need to edit Python source
  to change GPS bounding boxes, filename regexes, file-count bounds, and the
  software allow-list.  This is accepted debt, not an oversight.

- **Chat 6 carries structural refactor work** in addition to its other planned
  deliverables.  The profile schema design is itself a non-trivial artifact; it
  needs to be general enough to cover at least two distinct datasets without being
  so general that it provides no constraint.

- **The EDR-specific rule calibration embedded in Chat 4 code will diverge from
  reality** if USGS re-releases P1WHKTRD with a different processing pipeline.
  The profile-driven approach resolves this systematically; until Chat 6, it
  requires a manual code update.

## Open questions

1. **Profile schema format** (YAML vs. TOML vs. JSON Schema) is unspecified;
   resolve in Chat 6.

2. **Profile versioning** — whether profiles should be versioned independently of
   validator code (probably yes, analogously to how `qc_report.json` carries a
   `schema` field) — resolve in Chat 6.

3. **Behavior when no profile is loaded** — whether the validator should run with
   default-permissive rules or refuse to run.  Likely the latter; resolve in Chat 6.

4. **Cross-dataset profile distribution** — whether other USGS reef SfM datasets
   (P13HMEON's broader site list, Hatcher et al. 2022's SQUID-5 EDR data at DOI
   10.5066/P93RIIG9) should ship with profiles in this repo or be left to future
   contributors — unspecified; resolve in Chat 6.

See also [ADR-0009](0009-exif-csv-and-tiff-encoding-metadata-loss.md) for the
metadata-loss findings that drove the iterative rule refinements recorded here, and
[ADR-0010](0010-adopt-toth-usgs-metashape-workflow.md) for the structurally similar
pattern of grounding parameter values in dataset-specific evidence before abstracting.

#tags: validator, profile-driven, generalization, provenance, chat-6, refactor, hardcoded, metadata-lineage, edr, reusable-package
