"""Captured-threshold audit for QC criterion and gate check objects.

Classifies each AuditTarget against a set of Liability categories that describe
how well the threshold/observed provenance is captured in the run record.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel

from .manifest.schema import GateCheckResult, ProcessingManifest
from .qc.validator import QCCriterion, QCReport


class Liability(str, Enum):
    """Audit verdict for one criterion.

    Severity order (ascending): RETIRED < UNCAPTURED_MEASUREMENT
    < UNTETHERED_THRESHOLD < UNSOURCED_THRESHOLD < SELF_CONFIRMING.
    RETIRED = no liabilities (status sentinel, not a finding in the list).
    """
    RETIRED = "retired"
    UNCAPTURED_MEASUREMENT = "uncaptured_measurement"
    UNTETHERED_THRESHOLD = "untethered_threshold"
    UNSOURCED_THRESHOLD = "unsourced_threshold"
    SELF_CONFIRMING = "self_confirming"


class AuditTarget(BaseModel):
    """Normalised, origin-agnostic view of one QC criterion or gate check."""

    id: str
    observed: Any
    threshold: Any
    passed: bool | None
    advisory: bool = False
    characterized: bool = False
    note: str | None = None
    """Captured rationale for a characterized gap. Required for the characterized
    exemption to apply — a bare characterized=True with note=None is not valid."""
    source: str | None = None
    origin: str


class GateAuditResult(BaseModel):
    """Audit result for one AuditTarget."""

    target: AuditTarget
    liabilities: list[Liability]
    status: Liability
    """RETIRED when liabilities is empty; otherwise the highest-severity liability."""


class CaptureAuditReport(BaseModel):
    """Full audit report for one processing run."""

    run_id: str
    results: list[GateAuditResult]
    summary: dict
    overall_conformant: bool


# ---------------------------------------------------------------------------
# Converters — bind to the REAL field names of each source type.
# ---------------------------------------------------------------------------

def from_gate_check(gc: GateCheckResult) -> AuditTarget:
    """Build an AuditTarget from a GateCheckResult (origin="gate_check").

    GateCheckResult fields: check_id, passed, observed, threshold,
    advisory, characterized, note.  No source field — maps to None.
    """
    return AuditTarget(
        id=gc.check_id,
        observed=gc.observed,
        threshold=gc.threshold,
        passed=gc.passed,
        advisory=gc.advisory,
        characterized=gc.characterized,
        note=gc.note,
        source=None,
        origin="gate_check",
    )


def from_qc_criterion(c: QCCriterion) -> AuditTarget:
    """Build an AuditTarget from a QCCriterion (origin="qc_criterion").

    QCCriterion fields: name, category, passed, observed, threshold, source.
    No advisory or characterized field — maps to False.
    """
    return AuditTarget(
        id=c.name,
        observed=c.observed,
        threshold=c.threshold,
        passed=c.passed,
        advisory=False,
        characterized=False,
        source=c.source,
        origin="qc_criterion",
    )


# ---------------------------------------------------------------------------
# Severity ordering for GateAuditResult.status derivation.
# ---------------------------------------------------------------------------

_SEVERITY: dict[Liability, int] = {
    Liability.RETIRED: 0,
    Liability.UNCAPTURED_MEASUREMENT: 1,
    Liability.UNTETHERED_THRESHOLD: 2,
    Liability.UNSOURCED_THRESHOLD: 3,
    Liability.SELF_CONFIRMING: 4,
}


def worst_liability(liabilities: list[Liability]) -> Liability:
    """Return the highest-severity Liability, or RETIRED when the list is empty."""
    if not liabilities:
        return Liability.RETIRED
    return max(liabilities, key=lambda l: _SEVERITY[l])


# ---------------------------------------------------------------------------
# Classifier.
# ---------------------------------------------------------------------------

def audit_run(
    manifest: "ProcessingManifest",
    qc_report: "QCReport",
    *,
    run_id: str = "",
) -> CaptureAuditReport:
    """Classify every evaluable gate check and QC criterion in one run.

    Traversal:
      1. manifest.gate.checks (list[GateCheckResult]) via from_gate_check —
         each GateCheckResult with passed is not None is a real evaluable check.
         Advisory checks have passed=None and are skipped (they are exempt from
         UNTETHERED_THRESHOLD anyway, and have no meaningful verdict to audit).
      2. qc_report.criteria (list[QCCriterion]) via from_qc_criterion —
         same filter: passed is not None drops the not-evaluable sentinels
         (markers_gate_overall when no markers data, and all Toth conformance /
         outcome criteria whose observed value could not be populated from the
         manifest).

    Both walks are independent; a gate check will appear twice in results —
    once as origin="gate_check" (AuditTarget.id = check_id) and once as
    origin="qc_criterion" (AuditTarget.id = "gate_<check_id>") — auditing
    both the raw pipeline record and the QC criterion derived from it.

    overall_conformant is True only when every result is RETIRED.
    """
    results: list[GateAuditResult] = []

    for gc in manifest.gate.checks:
        if gc.passed is None:
            continue
        t = from_gate_check(gc)
        libs = classify(t)
        results.append(GateAuditResult(
            target=t,
            liabilities=libs,
            status=worst_liability(libs),
        ))

    for c in qc_report.criteria:
        if c.passed is None:
            continue
        t = from_qc_criterion(c)
        libs = classify(t)
        results.append(GateAuditResult(
            target=t,
            liabilities=libs,
            status=worst_liability(libs),
        ))

    status_counts: dict[str, int] = {}
    for r in results:
        status_counts[r.status.value] = status_counts.get(r.status.value, 0) + 1

    return CaptureAuditReport(
        run_id=run_id,
        results=results,
        summary=status_counts,
        overall_conformant=all(r.status is Liability.RETIRED for r in results),
    )


def classify(t: AuditTarget) -> list[Liability]:
    """Return the list of Liabilities for this AuditTarget.

    UNTETHERED_THRESHOLD: threshold is None and not advisory and not characterized.
    UNCAPTURED_MEASUREMENT: observed is None.
    SELF_CONFIRMING: observed == threshold (non-None tautology; mutually exclusive
      with UNCAPTURED_MEASUREMENT — only checked when observed is not None).
    """
    f: list[Liability] = []
    characterized_with_rationale = t.characterized and bool(t.note)
    if t.threshold is None and not t.advisory and not characterized_with_rationale:
        f.append(Liability.UNTETHERED_THRESHOLD)
    if t.observed is None:
        f.append(Liability.UNCAPTURED_MEASUREMENT)
    elif (t.threshold is not None
          # Bool equality is a pass, not a tautology: observed=True, expected=True
          # means the gate fired correctly.  Limitation: int 0/1 passed as threshold
          # escapes this guard (isinstance(True, int) is True in Python), but gate
          # thresholds are either float/int numerics or explicit bool — the pipeline
          # never mixes the two, so the isinstance check is sufficient in practice.
          and not isinstance(t.observed, bool)
          and not isinstance(t.threshold, bool)
          and t.observed == t.threshold):
        f.append(Liability.SELF_CONFIRMING)
    return f
