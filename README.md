# reef-sfm-mote-keys

Reproducible reimplementation of the USGS / Mote Marine Laboratory restoration
Structure-from-Motion (SfM) pipeline ([Toth et al. 2025], Scientific Reports
15:28353; data release [P1WHKTRD] and [P13HMEON]) at the Eastern Dry Rocks
site, with an added enterprise data-management layer the upstream workflow
does not currently expose: per-stage provenance capture, quantitative QC
against the published carbonate-budget and structural-complexity targets, and
metric reconciliation between this reimplementation and the values in the
Toth 2025 release.

## Scope

- **Site.** Eastern Dry Rocks (24.459°N, 81.844°W), three subsites,
  *Acropora cervicornis* outplanting 2016–2020; one of eight offshore reefs in
  the Toth 2025 study.
- **Source imagery.** Diver-collected SfM imagery from the July 2022 and July
  2023 surveys, published in USGS data release P1WHKTRD
  ([Johnson et al. 2025]).
- **Pipeline.** Agisoft Metashape Professional, following the supplementary
  workflow in Toth 2025 (Table S2, Fig. S4). The colony-scale Metashape
  approach in [Combs et al. 2021] is a methodological precedent, applied here
  at the transect scale of the Toth study rather than the single-colony scale
  Combs used for SCTLD lesion tracking.
- **Outputs reconstructed.** Sparse and dense point clouds, segmented dense
  clouds, 1-cm DSMs, orthomosaics. Downstream: ReefBudget v2 carbonate-budget
  metrics and rugosity / vector ruggedness / mean elevation, compared against
  Toth 2025's per-transect values.

## What this repository adds beyond the upstream pipeline

The Toth 2025 release publishes inputs and outputs but not a structured record
of the steps and parameter choices that link them. This project instruments
the pipeline with:

1. **Provenance capture.** Each Metashape stage (align, sparse cleanup, dense,
   segmentation, DSM/ortho export) writes a structured manifest: input image
   set hash, Metashape build, parameter dict, GPU device, wall-clock, output
   product hashes. Designed so that two runs can be diffed and a single run is
   self-describing.
2. **Quantitative QC.** Tie-point counts, RMSE on scale bars, dense-cloud
   density, hole statistics on the DSM, and per-transect coverage are checked
   against thresholds derived from Toth 2025 Table S2 / Fig. S4 before a
   product is released for downstream analysis.
3. **Metric reconciliation.** Reimplemented carbonate-budget and complexity
   metrics are compared transect-by-transect against the published values in
   P13HMEON. Discrepancies are surfaced rather than averaged away.

The goal is a pipeline a third party can re-execute and audit, not just a set
of figures.

## Audience

This repository is written for:

- **Mote Marine Laboratory.** Particularly the restoration-monitoring team
  responsible for ongoing SfM data collection at the Lower Keys outplanting
  sites. The provenance and QC layer is intended to be lifted out and reused.
- **USGS SPCMSC.** The carbonate-budget and complexity calculations should
  reconcile transect-by-transect against the values in P13HMEON; the
  reconciliation reports are the primary deliverable for this audience.
- **The wider Florida Keys restoration community.** A worked, citable example
  of an audit-grade restoration-monitoring pipeline.

## Repository layout

```
.
├── data/
│   ├── raw/         # USGS imagery cache (gitignored)
│   └── processed/   # intermediates (gitignored)
├── notebooks/       # analysis notebooks (.ipynb)
├── scripts/         # fetchers and one-off helpers
├── src/reef_sfm_qc/ # provenance + QC + reconciliation package
├── figures/         # generated figures
├── docs/            # design notes, parameter-choice rationale
├── references.bib   # working bibliography (Stage 1 — accumulates freely)
├── project-plan.md  # nine-chat build plan
├── pyproject.toml
└── .python-version
```

## Environment

Local authoring is on macOS (Apple Silicon). The Metashape pipeline runs on a
single AWS `g6.4xlarge` EC2 instance (NVIDIA L4) under Linux; this repo is
the analysis-side companion, not the GPU-side runtime. Python is uv-managed
against the pinned `.python-version`.

```bash
uv sync
uv run python -m ipykernel install --user \
    --name reef-sfm-mote-keys \
    --display-name "Python (reef-sfm-mote-keys)"
```

The kernel registration is required so that Quarto can resolve the kernel at
the Stage 2 site-publication step.

## Stage of the workflow

This repository is at **Stage 1** of the [three-stage portfolio workflow](docs/):
live analysis, lab-notebook polish standard. The public-facing writeup will
live at `velezf.github.io/projects/reef-sfm-mote-keys.html` once the analysis
is settled.

## License

MIT for the code in this repository. USGS data releases retain their original
license terms; see P1WHKTRD and P13HMEON. Toth 2025 is CC-BY 4.0.

## Citations

Primary references are in [`references.bib`](references.bib). The two pillar
sources are Combs et al. 2021 (the colony-scale Metashape precedent) and
Toth et al. 2025 (the reef-scale study being reimplemented).

[Toth et al. 2025]: https://doi.org/10.1038/s41598-025-04818-3
[Combs et al. 2021]: https://doi.org/10.1371/journal.pone.0252593
[Johnson et al. 2025]: https://doi.org/10.5066/P1WHKTRD
[P1WHKTRD]: https://doi.org/10.5066/P1WHKTRD
[P13HMEON]: https://doi.org/10.5066/P13HMEON
