# Architecture Decision Records

This directory holds the Architecture Decision Records (ADRs) for the
reef-sfm-mote-keys project, using Michael Nygard's template (Context,
Decision, Consequences) — light enough to actually keep up to date, with
enough structure to be useful two months later.

## Why we keep these

When a future reviewer (or future me) asks "why did you use raw requests
instead of sciencebasepy?" the answer should not require archaeology
through commit logs or chat transcripts.  It should be `grep -l
sciencebasepy docs/adr/` → one file → 30-second read.

## Conventions

- **One ADR per real decision.**  If we changed our minds, write a new
  ADR with status `Supersedes ADR-NNNN` and update the old one's status to
  `Superseded by ADR-NNNN`.  Don't rewrite history.
- **Filename: `NNNN-kebab-title.md`.**  Zero-padded sequence number so `ls`
  sorts chronologically.  Title summarizes the *decision*, not the topic.
- **Every ADR has Status, Date, Context, Decision, Consequences.**  The
  Consequences section is mandatory: if you can't think of a downside,
  the decision probably wasn't a real choice.
- **Tag footer.**  Last line is `#tags: word1, word2, word3` so
  `grep -l '#tags:.*exif' docs/adr/` finds everything about EXIF.

## Grep recipes

```bash
# All ADRs touching EXIF
grep -lr '#tags:.*exif' docs/adr/

# All currently superseded ADRs
grep -lr '^Status:.*Superseded' docs/adr/

# All ADRs added in Chat 4
grep -lr '^Chat: 4' docs/adr/

# What was decided about ScienceBase?
grep -lri sciencebase docs/adr/
```

## Current index

| # | Title | Status | Chat |
|---|---|---|---|
| [0001](0001-provenance-package-as-installable-module.md) | Provenance code is an installable package, not notebook cells | Accepted | 4 |
| [0002](0002-no-sciencebasepy-dependency.md) | Talk to ScienceBase via raw `requests`, not `sciencebasepy` | Accepted | 4 |
| [0003](0003-sciencebase-api-primary-manifest-csv-fallback.md) | ScienceBase REST is the primary acquisition path; manifest CSV is the fallback | Accepted | 4 |
| [0004](0004-validation-constants-from-metadata-file.md) | Validation constants come from the metadata file, not the papers | Accepted | 4 |
| [0005](0005-four-level-severity-with-unverified.md) | Four severity levels (`ok` / `warn` / `fail` / `unverified`) | Accepted | 4 |
| [0006](0006-exiftool-optional-batched-subprocess.md) | exiftool is an optional batched subprocess, not a hard dep | Accepted | 4 |
| [0007](0007-gps-rule-expects-single-surface-fix.md) | GPS rule expects exactly one surface-station fix per site | Accepted | 4 |
| [0008](0008-ids-viewer-csv-export-primary-acquisition-path.md) | IDS viewer CSV export is the primary acquisition path | Accepted | 4 |
| [0009](0009-exif-csv-and-tiff-encoding-metadata-loss.md) | USGS TIFFs are Photoshop CR2→TIFF re-encodes; capture-time EXIF absent; CSV canonical for surviving metadata | Accepted | 4 |
| [0010](0010-adopt-toth-usgs-metashape-workflow.md) | Adopt Toth et al. 2025 ESM Table S2 as Chat 5 parameter source; PIFSC SOP superseded | Accepted | 4 |
| [0011](0011-validator-hardcoded-now-profile-driven-later.md) | Validator is intentionally EDR-hardcoded in Chat 4; profile-driven generalization deferred to Chat 6 | Accepted | 4 |
| [0012](0012-smoke-ab-rms-in-filter-units-not-pixels.md) | Smoke A/B reprojection RMS is in Metashape filter units, not image pixels | Accepted | 5 |
| [0013](0013-confidence-noise-filter-via-cleanpointcloud.md) | ESM Step 13 confidence filter implemented via Chunk.cleanPointCloud (remove); GUI's classify-and-keep has no Python equivalent in 2.x | Superseded by 0015 | 5 |
| [0014](0014-headless-confidence-filter-via-docpopi-pattern.md) | Headless confidence noise filter uses setConfidenceFilter + cropSelectedPoints (DocPopi pattern); cleanPointCloud is documented-but-non-functional on 2.3.1 build 22446 | Superseded by 0015 | 5 |
| [0015](0015-headless-step13-engineered-departure.md) | Headless ESM Step 13: engineered destructive departure (cleanPointCloud + compactPoints); supersedes 0013 and 0014; reframes choice as departure not reproduction | Accepted | 5 |
| [0016](0016-builddem-extent-beyond-pcextent-smoke-bbox-clip.md) | buildDem extent inference on unscaled chunks: BBox region clip insufficient; full headless smoke of DSM/ortho deferred to scaled production runs (T3 dress rehearsal or v2) | Accepted with caveat | 5 |
