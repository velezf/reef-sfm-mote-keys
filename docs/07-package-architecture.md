# reef_sfm_provenance — architecture

> The manifest is the contract. QC validates quality. Reconciliation validates
> truth against the published reference. PROV exports the story.

A lightweight, domain-specific, auditable provenance/QC/reconciliation layer.
`src/` layout, typed pydantic models, a thin Typer CLI over importable functions.

## Modules

| Module | Responsibility |
|---|---|
| `models.py` | Typed contract: `RunManifest`, `InputDataset`, `Artifact`, `PipelineStep`, `Metric`, `SoftwareVersion`, `ProcessingEnvironment`, QC + reconciliation models. |
| `intake.py` | Validate an imagery directory (extensions, duplicates, counts, hashes, EXIF). |
| `manifest.py` | Read/write `run_manifest.json`; `verify_against_disk()` (the manifest-vs-filesystem integrity check). |
| `metashape_report.py` | Parse a Metashape processing report into a partial manifest (extraction points isolated). |
| `qc.py` | Three-state QC (`pass`/`fail`/`not_evaluable`) against SOP/Toth targets, plus structural + integrity checks. |
| `metrics.py` | Metric definitions (rugosity, VRM, mean elevation, …) with Toth formula references; raster compute marked `# PORT:`. |
| `reconcile.py` | **The differentiator.** Our metrics vs published reference; reproducibility grading; comparison-only firewall. |
| `provenance.py` | W3C PROV export (entities/activities/agents) → `provenance.json`. |
| `reports.py` | Human-readable Markdown from manifest + QC + reconciliation. |
| `cli.py` | `reef-sfm` / `reef-audit` commands; thin wrappers only. |

## Two distinct truth checks, deliberately not conflated

* **Integrity** (`manifest.verify_against_disk`, surfaced as the `artifact_integrity`
  QC check): does the manifest agree with the filesystem — exist, non-empty, hash
  matches? This catches the failure that let a `.psx` pointer read "unchanged"
  while its data could have moved.
* **Reconciliation** (`reconcile.py`): do *our* metrics agree with the *published*
  reference (USGS P13HMEON / Toth 2025)? This is the headline, and it runs under a
  structural firewall — published values are comparison-only, never pipeline inputs,
  never used to tune. Reproducibility is graded, not binary.

## Three-state QC

`PASS` / `FAIL` / `NOT_EVALUABLE`. A check whose precondition is absent
(reprojection error with no alignment) is `NOT_EVALUABLE` with a `skipped_reason`
— never a silent pass or fail. A run `passed` iff it has no `FAIL`s;
`NOT_EVALUABLE` does not pass on your behalf.

## Porting, not rebuilding

The numerical metric computations already exist in the project's metric core and
are validated to <0.1% against published DSMs. `metrics.py` is the typed interface
to them; each heavy computation is marked `# PORT:`. Do not reimplement the
metrics here.

## Run-level files

`run_manifest.json` · `qc_report.json` · `reconciliation_report.json` ·
`provenance.json` · `report.md`

## CLI

```
reef-sfm validate-intake <input-dir>
reef-sfm parse-report <report> --run-id <id> --site <site> [--out <run>]
reef-sfm qc <run>
reef-sfm reconcile <run> --published <published.csv>
reef-sfm export-prov <run>
reef-sfm report <run>
reef-audit inspect <run>          # alias surface
```
