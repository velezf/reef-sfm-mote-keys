# ADR 0005 — Four severity levels (`ok` / `warn` / `fail` / `unverified`)

Status: Accepted
Date: 2026-05-27
Chat: 4

## Context

The QC validator produces structured findings.  The obvious shape is
pass/fail, sometimes with a warn tier — the typical lint/CI model.

We have a complication: some checks (XMP AttributionURL, IPTC Credit)
require `exiftool` to read.  When `exiftool` is not on PATH, the data
might be perfectly fine — we just can't verify it from this host.

Treating that as `fail` would mean every QC report from a machine
without exiftool fails.  That would either (a) train operators to ignore
fails, or (b) push operators to install exiftool even when it's
inappropriate (e.g. running the validator from a CI image).  Neither is
right.

Treating it as `pass` is worse: we'd be claiming we checked something
when we didn't.

## Decision

Findings carry one of four severities:

- **`ok`** — the rule ran and the data matched expectations.
- **`warn`** — the rule ran and found something worth a human look,
  but it doesn't block downstream work.
- **`fail`** — the rule ran and the data does not match expectations.
  Blocking; should be triaged before Chat 5.
- **`unverified`** — the rule didn't run (tooling absent, data
  unavailable).  Not blocking, not green.

`overall_severity` aggregates by taking the max severity present, where
the ordering is `ok < warn = unverified < fail`.  `unverified` is
treated as no-worse-than-warn for aggregation but is reported distinctly
in the rollup table.

## Consequences

**Positive.**

- Honest reporting.  "We didn't check" never silently becomes "checked
  and passed".
- Operators see exactly which gaps are data quality and which are
  tooling.  Installing exiftool is a different fix from chasing a real
  EXIF mismatch.
- The QC report's color-coded rollup table communicates this at a
  glance — the `unverified` column is a separate count, not lost.

**Negative / costs.**

- Every consumer of `Finding` has to handle four cases.  In practice
  only `intake_report.py` does (and via the `SEVERITY_ORDER` map).
- Mildly nonstandard.  A reviewer familiar with binary lint output may
  need a beat to absorb it.  Mitigated by the doc table in
  `04-data-acquisition.md` that maps every rule to its severity.

#tags: validation, severity, qc, exiftool, reporting
