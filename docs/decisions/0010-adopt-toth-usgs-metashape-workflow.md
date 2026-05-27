# ADR 0010 — Adopt Toth et al. 2025 USGS-published Metashape workflow and tooling as the Chat 5 implementation reference, superseding PIFSC SOP parameter values where they conflict

Status: Accepted  
Date: 2026-05-27  
Chat: 4

## Context

The project plan originally identified the NOAA PIFSC SOP (Torres-Pulliza et
al. 2024) as the source of specific Metashape parameter values, framed
explicitly as "parameter reference, not methodological basis."  The
methodological basis was Combs et al. 2021 and Toth et al. 2025, but those
papers' main text does not provide complete parameter tables.

During Chat 4, I obtained and read Toth et al. 2025's Electronic Supplementary
Material (ESM), which includes Table S2: a step-by-step Metashape workflow
with specific parameter values.  The ESM also cites four USGS-released
software tools by DOI:

- **Logan et al. 2022** (DOI: 10.5066/P9DGS5B9) — Automated Image Alignment
  and Error Reduction Python script.  Handles Gradual Selection
  (Reconstruction Uncertainty 20–40, Projection Accuracy 3–4, Reprojection
  Error 0.3) and camera re-optimization after each filter pass.
- **Hatcher et al. 2022** (DOI: 10.5066/P93RIIG9) — Underwater color
  correction MATLAB/Octave script.
- **Jenkins & Kupfner Johnson 2024** (DOI: 10.5066/P9YN4KDX) — Metashape
  Alignment Helper Tool for coordinate system placement (zero-point center,
  1 m cell-size grid).
- **Jenkins & Johnson 2025** (DOI: 10.5066/P1C7KKAP) — Metashape Export
  Helper Tool for batch product export.

**Toth vs. PIFSC parameter comparison.**

Where the two sources specify the same parameter but with different values,
Toth et al. 2025 takes precedence as the method actually used on this dataset:

| Parameter | Toth et al. 2025 (ESM Table S2) | PIFSC SOP |
|---|---|---|
| Key point limit | 60,000 | 40,000 |
| Reconstruction Uncertainty threshold | 20–40 | 10–15 |
| Projection Accuracy threshold | 3–4 | 2–6 |
| Reprojection Error threshold | 0.3 (fixed) | 0.3–0.5 |
| Dense cloud quality | High | Medium |
| DEM resolution | 1 cm (per main text) | 0.001 m (1 mm) |
| Exclude stationary tie points | yes | not specified |

The dense-cloud quality difference (High vs. Medium) is the most operationally
significant: it substantially extends GPU runtime (see Consequences).

**Manual point-cloud segmentation.**

ESM Step 13 and Fig. S4 document manual segmentation of the point cloud into
four classes: low-point noise, canopy, outplants, reef base.  This is done via
the Metashape GUI lasso tool.  Segmentation enables filtered point clouds and
DSMs that exclude outplants, which is the basis for the "with outplants vs.
without outplants" structural complexity comparison in Toth et al. 2025
Fig. 3.  This was not explicitly anticipated in the original Chat 5 plan.

See also [ADR-0009](0009-exif-csv-and-tiff-encoding-metadata-loss.md) for the
finding that these TIFFs are the team's original Metashape input files and that
capture-time EXIF tags are absent but methodologically irrelevant given the
bundle-adjustment-driven calibration workflow.

## Decision

1. **Adopt Toth et al. 2025 ESM Table S2 as the canonical parameter source for
   Chat 5**, superseding PIFSC SOP values wherever they conflict.  PIFSC
   remains a useful background reference but is no longer the operational
   source.  Rationale: the published method on this exact dataset takes
   priority over a parameter reference from a different program (NOAA PIFSC)
   and a different ecosystem (Pacific coral reefs).

2. **Use the four USGS-released tools as follows:**

   - **Logan automated alignment script: REQUIRED.**  Replaces manual
     GUI-bound error reduction with documented, reproducible automation.  The
     single highest-leverage tool adoption.  Integrate via `uv add` from a
     local clone of the USGS repository; verify headless-mode compatibility
     with Metashape Pro 2.x before Chat 5 execution.

   - **Hatcher color correction: OPTIONAL.**  Octave is the free MATLAB
     substitute and is available via `apt`.  Evaluate runtime cost vs. visual
     benefit on a small subset during Chat 5.  If color correction materially
     improves orthomosaic readability, adopt; if marginal, document as a
     deliberate deviation.

   - **Jenkins & Kupfner Johnson alignment helper: REQUIRED** if Chat 6
     reconciliation needs to compare against published DSM products in the same
     coordinate frame.  Otherwise OPTIONAL.

   - **Jenkins & Johnson export helper: OPTIONAL.**  Useful for matching
     exported product structure to USGS conventions; can be replicated in plain
     Python if integration proves awkward.

3. **Segmentation scope is deferred to Chat 5**, not pre-committed here.  Two
   viable paths:

   - (a) **Full reproduction:** manual segmentation of at least one EDR
     transect, enabling the "with outplants" vs. "without outplants" structural
     complexity comparison as shown in Fig. 3.  Several hours of GUI work per
     transect over NICE DCV.

   - (b) **Scoped reproduction:** skip segmentation; perform only the
     "with-everything" complexity metrics.  Reconciliation against published
     values becomes partial but remains tractable.

   Decide in Chat 5 based on actual time budget and trial-clock state.
   Document the choice and its consequences explicitly in Chat 5's docs.

4. **The Chat 5 plan in `project-plan.md` should be updated** to reflect this
   ADR's parameter changes and USGS tool integrations.  That update is a
   separate edit, not part of this ADR commit.

## Consequences

**Positive.**

- Parameter values are now sourced from the paper that used them on this exact
  dataset; PIFSC SOP divergences are explicitly documented rather than
  silently present.
- The Logan script converts the most error-prone step (Gradual Selection) from
  GUI-dependent to automated and reproducible.
- Deferring segmentation scope to Chat 5 avoids over-committing time before
  the trial-clock state is known.

**Negative / costs.**

- **Dense cloud quality "High" significantly extends runtime.**  On a
  g6.4xlarge with L4 GPU and 3,271 images, expect dense reconstruction in the
  24–48 hour range rather than the 8–12 hour range that PIFSC's "Medium" would
  imply.  Schedule dense reconstruction as the first long compute step to
  maximize the window available before the EC2 trial clock expires.  If dense
  reconstruction overruns the trial window, the rest of the pipeline is
  blocked.

- **Logan script is Python but requires verification.**  Confirm licensing
  (expected: USGS public domain) and headless-mode compatibility with
  Metashape Pro 2.x before Chat 5 execution.

- **Hatcher script is MATLAB/Octave.**  If adopted, requires either the MATLAB
  Runtime, Octave, or a Python port.  Octave is the most pragmatic free
  option; document any incompatibilities found during Chat 5 evaluation.

- **Jenkins coordinate-system helper uses a per-transect local CRS**
  (zero-point center, 1 m cell-size grid).  Published DSMs are in this local
  frame, not a global geographic CRS.  Chat 6 reconciliation logic must either
  (a) operate in this local frame, or (b) explicitly document why a different
  frame is used.  Confirm whether published EDR DSMs in data release
  P13HMEON are in this local frame before designing the Chat 6 comparison.

- **PIFSC SOP is now deprecated as Chat 5's parameter source.**  The project
  plan and Chat 5 chat opener should be updated to remove "parameter
  reference" language for PIFSC and replace with citation of Toth et al. 2025
  ESM Table S2 as the authoritative source.

- **The reusable provenance package (Chat 6)** can include a parameter
  cross-validation pattern, demonstrating that QC layers should validate
  against the specific published method being reproduced rather than against
  generic SOPs from adjacent programs.

**Open questions.**

1. Verify Logan et al. 2022 licensing and headless-mode compatibility with
   Metashape Pro 2.x before Chat 5 execution.

2. Determine whether Octave preserves output equivalence with the Hatcher
   MATLAB script.  Side-by-side test on a handful of frames during Chat 5
   evaluation.

3. Pre-watch the Jenkins Alignment Helper Tool video walkthrough referenced in
   its README before Chat 5 to understand the coordinate system placement
   workflow.

4. Confirm whether published EDR DSM products in P13HMEON use the local
   zero-point frame or a different CRS; this directly affects Chat 6
   reconciliation design.

#tags: metashape, workflow, parameters, pifsc, toth, bundle-adjustment, dense-cloud, logan, hatcher, jenkins, usgs-tools, segmentation, chat5
