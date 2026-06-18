# The provenance, QC, and reconciliation layer

This layer is the differentiator of the project. The reconstruction — aligning
imagery into a dense point cloud, a digital surface model, and an orthomosaic —
is work any competent operator with Agisoft Metashape can do. What this layer
adds is the discipline around it: it turns a reconstruction into an *auditable
scientific data product*.

## What it does, and why each part matters

**The manifest is the contract.** Every run is described by a typed, hashed
`RunManifest`: inputs and their hashes, the software and versions, the
parameters, the compute environment, the output artifacts and their hashes, the
error metrics, and the code version. Reproducibility is not a promise; it is a
recorded fact. The manifest is also verified against the filesystem — a check
whose absence, in this very project, let a Metashape `.psx` pointer file read
"unchanged" while the data it referenced could have moved underneath it.

**QC validates quality, three ways.** Checks return `pass`, `fail`, or
`not_evaluable`. The third state is the point: a reprojection-error check when
alignment never ran is *not evaluable*, not a silent pass and not a fail.
Collapsing that to a binary hides exactly the failures that matter. Quantitative
targets are bound to documented sources (the SOP / Toth ESM Table S2), not magic
numbers.

**Reconciliation validates truth — against the published reference.** This is
the headline. The layer computes the same topographic-complexity metrics Toth et
al. (2025) report — rugosity, mean elevation, vector ruggedness — on our
reconstruction, and compares them to the published USGS values. Crucially, it
does this under a strict **comparison-only firewall**: published values are never
inputs to the pipeline and never used to tune a parameter. Divergence is
*characterized*, never closed by adjustment. And reproducibility is graded
(`reproduced` / `approximately_reproduced` / `not_reproducible` /
`not_attempted`), because honest reconciliation is rarely a clean yes/no — a
metric can match in value but differ in implementation (the python/Sappington vs
MultiscaleDTM VRM offset is a concrete example), or our outputs may not support a
published metric at all.

**PROV exports the story.** The manifest maps to a W3C PROV representation —
entities (the images, the dense point cloud, the DSM, the orthomosaic, the
reports), activities (intake, alignment, DSM/orthomosaic generation, QC,
reconciliation), and agents (the software, the compute instance, the operator,
this package). That is provenance in a standards-compatible, interoperable form,
not an ad-hoc log.

## Why it matters for restoration programs

A restoration program does not just need a reef model; it needs a model it can
*trust, reproduce, and defend* — to funders, to reviewers, to the next analyst.
This layer supplies exactly that: explicit quality targets, captured
reproducibility metadata, and a documented, firewalled comparison to the
published literature. It is enterprise data-management discipline applied to a
marine-science workflow, and it is what distinguishes this work from a generic
photogrammetry demonstration.

## What it deliberately does not do

It does not adjust our results toward the published values; it characterizes the
gap. Where a published metric cannot be reproduced from our outputs, the
reconciliation report says so and says why. Honesty about the limits of the
reconstruction is part of the deliverable, not a footnote to it.
