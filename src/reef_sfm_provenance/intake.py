"""Clean typed wrapper over the existing intake validation stack.

``validate_intake(dir)`` is the public surface; it returns an :class:`IntakeReport`
Pydantic model so callers get structured output without needing to know about the
lower-level inventory / validation machinery.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict


class IntakeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_dir: str
    image_count: int
    findings: list[dict]
    overall_severity: str  # "ok" | "warning" | "fail"

    @property
    def ok(self) -> bool:
        return self.overall_severity != "fail"


def validate_intake(site_dir: str | Path) -> IntakeReport:
    """Run the existing intake validation stack and return a typed report.

    ``findings`` is the union of per-image findings and dataset-level findings
    from the existing ``validation`` module. Each finding is a plain dict
    (the existing stack produces dicts); structure is preserved as-is.
    """
    from .inventory import build_inventory
    from .validation import validate_dataset, validate_image

    d = Path(site_dir)
    inv = build_inventory(d)

    per_image_raw = []
    for rec in inv:
        per_image_raw.extend(validate_image(rec))
    dataset_raw = validate_dataset(inv)

    # Finding objects expose .to_dict(); normalise to plain dicts.
    def _to_dict(f) -> dict:
        return f.to_dict() if hasattr(f, "to_dict") else dict(f)

    findings: list[dict] = [_to_dict(f) for f in per_image_raw + dataset_raw]

    severities = {f.get("severity", "ok") for f in findings}
    if "fail" in severities:
        overall = "fail"
    elif "warning" in severities:
        overall = "warning"
    else:
        overall = "ok"

    return IntakeReport(
        site_dir=str(d),
        image_count=len(inv),
        findings=findings,
        overall_severity=overall,
    )
