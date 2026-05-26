# Standing decisions — pasteable snippets

Two snippets in this file, for two different purposes.

## 1. For project-plan.md and Chat 4+ opening prompts (operator-facing)

Paste this into the "Project context (carried into every chat)" section
of `project-plan.md`, and into the opening prompt of any new chat from
Chat 4 onward, so each new session inherits the constraints.

```
Standing decisions (full ADRs at docs/decisions/):

- DCV: Amazon DCV 2025.0 (formerly NICE DCV — same product, renamed in
  Oct 2024). Server packages still named nice-dcv-*. [ADR-0001]

- Metashape: pinned to Pro 2.3.1 for the duration of the project to
  preserve the PIFSC SOP parameter mapping. Do not bump mid-project.
  [ADR-0002]

- Trial activation: isolated in scripts/bootstrap/04_activate_trial.sh,
  never triggered by other scripts. Activation requires explicit
  operator consent. The activation timestamp is recorded for the Chat 6
  provenance manifest. [ADR-0003]

- QGIS: official LTR apt repo (qgis.org/ubuntu-ltr), not the Ubuntu
  archive package. Do not run blind apt upgrade qgis after Chat 7
  figures are exported — rendering can change between LTR minors.
  [ADR-0004]

- Metashape Python: Chat 5 scripts run against
  /opt/metashape-pro/python/bin/python3 (the bundled interpreter). The
  project uv venv runs everything else. Two interpreters, communicate
  via files on disk. [ADR-0005]
```

Keep this block short. When a new ADR is added, append a one-liner here
and reference the full file.

## 2. For the analysis notebook in Chat 5+ (reviewer-facing)

The notebook should carry the same decisions in prose, in a `## Design
decisions` section that sits above the processing code. Format below.
Each entry is the `Notebook narrative` block from the corresponding
ADR file — keep them in sync.

```markdown
## Design decisions

Brief notes on the non-obvious technical choices made in this project,
in roughly the order they were made. Full architecture decision records
are in `docs/decisions/` in the project repository.

### Remote display

Remote-display work uses Amazon DCV 2025.0 (the AWS-managed remote
display protocol formerly branded NICE DCV; the 2024.0 release renamed
the product without changing the protocol). DCV was chosen over X11
forwarding because the Metashape GUI work in this project involves
dense point cloud rendering and OpenGL views that perform poorly over
X11 even on a low-latency connection. DCV supports GPU-accelerated
remote OpenGL via the `nice-dcv-gl` package, which matters
specifically for Metashape's mesh and dense-cloud views.

### Metashape version

All photogrammetric processing in this project uses Agisoft Metashape
Professional 2.3.1, pinned for the duration of the run. Pinning matters
because the parameter reference used here — the NOAA PIFSC SOP for SfM
coral reef benthic mapping (Torres-Pulliza et al. 2024,
DOI 10.25923/cydj-z260) — specifies Metashape UI values (Gradual
Selection thresholds, depth filter levels, output resolutions in
metres) that are tied to a specific Metashape UI generation. Floating
the version mid-project would mean re-verifying that the same dialogs,
sliders, and units still exist at each upgrade. The PIFSC SOP is
treated here as a parameter reference only; the methodological lineage
of this work is Combs et al. 2021 and Toth et al. 2025 (USGS/Mote),
both of which processed Florida Keys imagery under broadly equivalent
Metashape Pro 2.x settings.

### Trial-window discipline

The processing pipeline ran under a 30-day Agisoft Metashape
Professional trial. The trial clock cannot be paused, and the trial
fingerprint binds to a network-interface MAC, so the project
infrastructure was designed around protecting trial days. In
particular, all system bootstrap (system updates, Python toolchain,
DCV server, QGIS, Metashape binary install) ran to completion and was
independently validated *before* the trial was activated. This
separation is mechanical, not stylistic: the bootstrap orchestrator
and the trial-activation script are different files, and activation
requires explicit operator consent. The activation timestamp is
captured in the project provenance log so the trial window can be
cited precisely against processing timestamps.

### GIS toolchain

Spatial analysis and figure production use QGIS LTR, installed from
the official QGIS apt repository rather than the Ubuntu archive. The
official LTR build is the version tracked in QGIS project
documentation and bug reports, so any troubleshooting (and any reader
trying to reproduce the figures) lands on consistent documentation.
The plugin set includes `qgis-plugin-grass` for the GRASS-backed
terrain operations used to derive slope and rugosity from the DEM. The
choice of QGIS over ArcGIS Pro is deliberate and elaborated in the
GIS annotation methods.

### Python interpreter for Metashape scripting

SfM processing runs against the Python interpreter that ships inside
the Metashape Pro 2.3.1 distribution
(`/opt/metashape-pro/python/bin/python3`), not the project's uv venv.
The Metashape Python module is tightly coupled to the Metashape binary
it ships with, and importing it from an external Python is fragile
across upgrades. The project venv handles everything else — intake
validation, the provenance/QC/reconciliation package, and all
notebooks. The two interpreters communicate via files on disk:
Metashape writes the processing report and output products; the
provenance layer reads them back in. This is the same
artifact-on-disk handoff pattern the provenance manifest is designed
around.
```

## Migration to Quarto at Chat 8

Per the three-stage workflow document, the `## Design decisions`
section migrates into the Quarto page largely intact, but with these
adjustments:

- Convert any prose citations to `[@key]` style for Pandoc.
- The section heading is fine as-is; alternative names like "Design
  rationale" or "Implementation choices" also work.
- Drop the parenthetical references to chat numbers (e.g. "the Chat 6
  provenance manifest" → "the provenance manifest"). The Quarto reader
  has no chat context.
- The "Trial-window discipline" section can stay or be folded into a
  broader "Constraints" subsection — it reads as engineering-discipline
  evidence, which is on-message for the writeup audience.
- The "Remote display" section is the most cuttable for the writeup —
  a Mote/USGS reader doesn't care which remote-display protocol was
  used. Consider moving it to a "Reproducibility appendix" or cutting
  it entirely from the main Quarto page, with the ADR remaining in
  the repo for anyone forking the work.
