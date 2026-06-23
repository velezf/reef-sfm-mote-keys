# reef_sfm_provenance

A typed Python package for provenance capture, structural QC, metric reconciliation,
and audit-grade record-keeping around Agisoft Metashape SfM pipelines. Built against
the Toth et al. 2025 / Combs et al. 2021 coral-reef workflow, but the schemas are
generic and the gate thresholds are overridable configuration — not Eastern Dry Rocks
constants.

## CLI

The package installs two entry points that resolve to the same Typer application;
`reef-audit` is a name that reads right for the audit-facing subcommands.

```
reef-sfm [OPTIONS] COMMAND [ARGS]...
reef-audit [OPTIONS] COMMAND [ARGS]...

Commands:
  validate-intake   Validate an imagery intake directory (extension, duplicates,
                    counts, hashes).
  parse-report      Parse a Metashape processing report into a run manifest.
  qc                Run structural QC against a run manifest (and filesystem if
                    run_dir is a folder).
  reconcile         Reconcile local metrics against published reference values
                    (comparison-only).
  export-prov       Export W3C PROV-JSON for the run.
  report            Assemble the human-readable Markdown report from manifest +
                    QC + reconciliation.
  inspect           Summarize a run manifest (the reef-audit entry point).
  acquire           Download Eastern Dry Rocks imagery from a USGS data release.
  contact-sheet     Render JPEG contact sheets for visual review.
```

## Data model

All records are Pydantic models. The core types:

**Manifest layer** (`manifest/schema.py`, `models.py`):
- `ProvenanceBlock` — input/output file hashes, EC2 instance id, EBS snapshot ids,
  license fingerprint, processing timestamps, software versions
- `ParametersBlock` — alignment accuracy, key/tie-point limits, filter thresholds
- `OutcomeBlock` — image counts, reprojection RMS, scale-bar errors, dense point
  count, DSM resolution
- `ProcessingManifest` — top-level stage record (gate checks, markers, provenance)
- `RunManifest` — cross-stage run record: site, transect, code version (git sha),
  `InputDataset`, `Artifact` list (path + sha256 + CRS), `Metric` list, `PipelineStep` list

**QC layer** (`qc/validator.py`):
- `QCCriterion` — name, passed (bool | None), threshold, observed, source
- `QCReport` — manifest id + criteria list; all gate thresholds are constructor
  arguments with defaults from Toth 2025 Table S2

**Reconciliation layer** (`models.py`):
- `Metric` — name, value, unit, window\_m, implementation, source (`"ours"` | `"published"`)
- `ReconciliationResult` — metric name, ours vs published, delta, status
- `ReconciliationReport` — full per-metric comparison bundle

**Capture-audit** (`capture_audit.py`):
- `Liability` enum — `RETIRED` | `UNCAPTURED_MEASUREMENT` | `UNTETHERED_THRESHOLD`
  | `UNSOURCED_THRESHOLD` | `SELF_CONFIRMING` (severity ascending)
- `GateAuditResult` — target, liabilities, worst status
- `CaptureAuditReport` — results, summary counts, `overall_conformant`
  (`True` = capture-complete, not all-pass)

## The read-only firewall

Published reference values are loaded by exactly one function (`load_reference_metrics`
in `reconcile/harness.py`). It opens the table read-only, returns a plain dict, and
never writes anything back. The result cannot reach `load_dsm` or `compute_metrics`
by construction — there is no code path from the published dict to the DSM pipeline.

## Install and run

```bash
# development (editable)
uv sync
uv run reef-sfm --help

# example: validate an intake directory
uv run reef-sfm validate-intake data/raw/EDR_T1_R2/

# example: QC a manifest
uv run reef-sfm qc path/to/run_manifest.json

# example: inspect a run (audit entry point)
uv run reef-audit inspect path/to/run_dir/
```

## Generalizability

Gate thresholds (`registration_ratio_min`, `final_rms_max_px`, `frame_retention_min`,
all tilt/coverage/footprint gates) are `QCValidator` constructor arguments with
documented defaults. A restoration program producing Metashape reports at a different
site can instantiate the validator with site-appropriate thresholds and reuse
everything else unchanged.
