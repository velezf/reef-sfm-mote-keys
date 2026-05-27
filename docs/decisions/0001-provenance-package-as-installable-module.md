# ADR 0001 — Provenance code is an installable package, not notebook cells

Status: Accepted
Date: 2026-05-27
Chat: 4

## Context

The Chat-4 deliverable is the start of the project's "enterprise data
management layer": intake validation, acquisition provenance, and the QC
report generator.  Chats 6 and 7 extend the same package with processing
manifest, QC validator, metric reconciliation, and benthic-cover
comparison.  The same code will be invoked from notebooks, from shell
scripts on EC2, from pytest, and (in Chat 9) potentially from other
restoration programs adopting the pattern.

The path of least resistance was to put the logic in
`notebooks/04_intake_inventory.ipynb` cells and have downstream chats
import from the notebook or copy-paste.

## Decision

Build it as an installable Python package: `src/reef_sfm_provenance/` with
a real `pyproject.toml`, a `reef-sfm` console-script entry point, and
import-able modules.  The Chat-4 notebook calls into the package; the
package does not live inside the notebook.

Package layout:

```
src/reef_sfm_provenance/
├── __init__.py
├── __main__.py           # reef-sfm CLI
├── acquisition.py
├── inventory.py
├── validation.py
├── intake_report.py
└── contact_sheet.py
```

## Consequences

**Positive.**

- One CLI surface (`reef-sfm <subcommand>`) usable from SSH, shell
  scripts, and notebooks alike.  Chat 6's `validate`, `parse-report`,
  `reconcile` subcommands slot in without restructuring.
- Pytest can import the modules directly.  Notebooks can be deleted or
  rewritten without breaking tests.
- The package becomes a citable artifact in the Quarto writeup (Chat 8)
  and a portable resource for other restoration programs (Chat 9's
  v2 roadmap item).
- Type-checked, importable, refactor-safe.

**Negative / costs.**

- Slightly more upfront friction than dropping cells in a notebook —
  `pyproject.toml`, package layout, `uv pip install -e .`.
- Notebook contributors need the package installed in the kernel; can't
  just open the file and run.  Mitigated by Chat 3's bootstrap step that
  registers the kernel against `.venv`.
- Adds the discipline cost of keeping the public surface stable across
  chats.  We accept this; it's the point.

#tags: package, layout, structure, src, pytest, cli
