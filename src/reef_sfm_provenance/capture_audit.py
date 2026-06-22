"""Captured-threshold audit for QC criterion and gate check objects.

Classifies each AuditTarget against a set of Liability categories that describe
how well the threshold/observed provenance is captured in the run record.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel

from .manifest.schema import GateCheckResult
from .qc.validator import QCCriterion


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

def classify(t: AuditTarget) -> list[Liability]:
    """Return the list of Liabilities for this AuditTarget.

    UNTETHERED_THRESHOLD: threshold is None and not advisory and not characterized.
    UNCAPTURED_MEASUREMENT: observed is None.
    SELF_CONFIRMING: observed == threshold (non-None tautology; mutually exclusive
      with UNCAPTURED_MEASUREMENT — only checked when observed is not None).
    """
    f: list[Liability] = []
    if t.threshold is None and not t.advisory and not t.characterized:
        f.append(Liability.UNTETHERED_THRESHOLD)
    if t.observed is None:
        f.append(Liability.UNCAPTURED_MEASUREMENT)
    elif t.threshold is not None and t.observed == t.threshold:
        f.append(Liability.SELF_CONFIRMING)
    return f
