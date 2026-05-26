# 0005 — Use bundled Metashape Python for headless processing, not venv import

- **Status:** Accepted
- **Date:** 2026-05-25
- **Chat:** 3 (EC2 bootstrap)

## Context

The Metashape Pro Linux tarball ships its own Python interpreter under
`/opt/metashape-pro/python/`, used by `metashape.sh` directly. The
`Metashape` module can also, in principle, be imported from an
external Python 3 interpreter (e.g. the project's uv venv) by setting
`LD_LIBRARY_PATH` and adding the Metashape site-packages directory
via a `.pth` file. Both approaches are reachable in 2.x.

Three pulls on this decision:

1. The project's "good engineering" instinct says one Python: do all
   analysis in the project venv, including Metashape scripting, so
   the same interpreter that runs the provenance code in Chat 6 also
   runs the SfM scripts in Chat 5. Reproducibility benefit is real.
2. The Metashape Python API is tightly coupled to the Metashape
   binary build. Importing it from an external interpreter works
   right after install but is fragile across Metashape upgrades and
   Python minor-version bumps; threads on the Agisoft forum show
   this breaking subtly when the system Python is upgraded under
   the venv.
3. The bundled interpreter is what Agisoft tests against and what
   Toth et al. 2025's processing scripts (cited in the
   methodological lineage) implicitly assume. Using anything else
   introduces a difference from the published methodology that has
   to be defended.

## Decision

For Chat 5 (Metashape processing) the headless processing scripts run
under `/opt/metashape-pro/python/bin/python3`. The project venv is
used for everything *else* — the provenance/QC/reconciliation package
in Chat 6, the intake validator in Chat 4, the notebooks throughout.

The two interpreters communicate via files on disk, not in-process
imports. The Chat 5 script writes the Metashape processing report and
output products to `/data/...`; the Chat 6 provenance code reads
those artifacts back in via the venv interpreter.

## Consequences

- Two-interpreter setup is slightly more complex to explain in the
  writeup, but the explanation ("Metashape Python is tightly coupled
  to the Metashape binary; everything else uses the project venv")
  is one sentence and reads as engineering discipline rather than
  workaround.
- File-on-disk hand-off between the two interpreters is exactly the
  pattern the Chat 6 provenance layer is designed around — the
  processing manifest captures hashes and timestamps for the
  artifacts produced by the Metashape interpreter and consumed by
  the venv interpreter. So this decision reinforces rather than
  fights the provenance design.
- The `.pth`-based venv-import path is documented as an option in
  the comments of `02_install_metashape.sh` but is not used. If a
  future need requires it (e.g. an interactive Jupyter notebook
  that needs to drive Metashape directly), the comments tell the
  next operator how to set it up.

## Notebook narrative

> SfM processing in Chat 5 runs against the Python interpreter that
> ships inside the Metashape Pro 2.3.1 distribution
> (`/opt/metashape-pro/python/bin/python3`), not the project's uv
> venv. The Metashape Python module is tightly coupled to the
> Metashape binary it ships with, and importing it from an external
> Python is fragile across upgrades. The project venv handles
> everything else — intake validation (Chat 4), the provenance/QC/
> reconciliation package (Chat 6), and all notebooks. The two
> interpreters communicate via files on disk: Metashape writes the
> processing report and output products; the provenance layer reads
> them back in. This is the same artifact-on-disk handoff pattern
> the provenance manifest is designed around.
