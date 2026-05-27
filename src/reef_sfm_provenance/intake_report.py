"""
Intake QC report writer.

Consumes the inventory (ImageRecord list) and validation Findings and writes
two artifacts side by side:

    intake_qc_report.json   structured, schema-versioned, consumed by Chat 6
    intake_qc_report.md     human-readable, copyable into the Quarto writeup

Both share a stable shape: dataset-level findings first, then per-image
findings rolled up by rule code, then a small "head of failures" section
that names the first ~20 files that failed any rule.  The full per-image
finding list is in the JSON; the Markdown stays scannable.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import platform
from pathlib import Path
from typing import Any

from .inventory import ImageRecord
from .validation import (
    Finding,
    METADATA_LINEAGE,
    SEVERITY_ORDER,
    aggregate_per_image,
    overall_severity,
)
from . import __version__

SEVERITY_BADGES_MD = {
    "ok": "✅ ok",
    "warn": "⚠️ warn",
    "fail": "❌ fail",
    "unverified": "❓ unverified",
}


def build_report(
    *,
    site: str,
    doi: str,
    site_dir: Path,
    inventory: list[ImageRecord],
    dataset_findings: list[Finding],
    per_image_findings: list[Finding],
    extra_context: dict[str, Any] | None = None,
    ids_csv_path: str | None = None,
) -> dict[str, Any]:
    """Build the structured report dict that gets serialized to JSON."""
    severity = overall_severity(dataset_findings + per_image_findings)
    rollup = aggregate_per_image(per_image_findings)

    # Worst severity per image, used to find "files that need a look"
    per_file_severity: dict[str, str] = {}
    for f in per_image_findings:
        if f.scope == "dataset":
            continue
        cur = per_file_severity.get(f.scope, "ok")
        if SEVERITY_ORDER.get(f.severity, 0) > SEVERITY_ORDER.get(cur, 0):
            per_file_severity[f.scope] = f.severity

    failed_files = sorted([name for name, sev in per_file_severity.items() if sev == "fail"])
    warned_files = sorted([name for name, sev in per_file_severity.items() if sev == "warn"])

    csv_matched = sum(1 for r in inventory if r.csv_matched)
    return {
        "schema": "reef-sfm-provenance/intake_qc/v2",
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "package_version": __version__,
        "hostname": platform.node(),
        "site": site,
        "doi": doi,
        "site_dir": str(site_dir),
        "ids_csv_path": ids_csv_path,
        "image_count": len(inventory),
        "csv_join_count": csv_matched,
        "total_bytes": sum(r.size_bytes for r in inventory),
        "overall_severity": severity,
        "metadata_lineage": METADATA_LINEAGE,
        "dataset_findings": [f.to_dict() for f in dataset_findings],
        "per_image_findings_rollup": rollup,
        "per_image_findings": [f.to_dict() for f in per_image_findings],
        "files_with_failures": failed_files,
        "files_with_warnings": warned_files,
        "extra_context": extra_context or {},
    }


def write_report_json(report: dict[str, Any], path: Path) -> Path:
    path.write_text(json.dumps(report, indent=2, sort_keys=True))
    return path


def write_report_markdown(report: dict[str, Any], path: Path) -> Path:
    lines: list[str] = []
    ap = lines.append

    ap(f"# Intake QC Report — {report['site']}")
    ap("")
    ap(f"- **Site:** `{report['site']}`")
    ap(f"- **Data release DOI:** [{report['doi']}](https://doi.org/{report['doi']})")
    ap(f"- **Images:** {report['image_count']:,} ({report.get('csv_join_count', '?'):,} matched in IDS CSV)")
    ap(f"- **Total size:** {report['total_bytes'] / (1<<30):.2f} GiB")
    ap(f"- **IDS CSV:** `{report.get('ids_csv_path') or 'not loaded'}`")
    ap(f"- **Generated:** {report['generated_at_utc']}")
    ap(f"- **Package version:** `{report['package_version']}`")
    ap(f"- **Overall result:** {SEVERITY_BADGES_MD.get(report['overall_severity'], report['overall_severity'])}")
    ap("")

    lineage = report.get("metadata_lineage", {})
    absent = lineage.get("fields_absent_by_design", {})
    if absent:
        ap("## Metadata lineage (ADR-0009)")
        ap("")
        ap(f"> {absent.get('reason', '')}")
        ap("")
        missing = absent.get("missing_exif_tags", [])
        if missing:
            ap(f"Tags absent by design (not failures): `{'`, `'.join(missing)}`")
        ap("")

    ap("## Dataset-level checks")
    ap("")
    ap("| Rule | Result | Detail |")
    ap("|---|---|---|")
    for f in report["dataset_findings"]:
        badge = SEVERITY_BADGES_MD.get(f["severity"], f["severity"])
        msg = f["message"].replace("|", "\\|")
        ap(f"| `{f['code']}` | {badge} | {msg} |")
    ap("")

    ap("## Per-image checks (rolled up)")
    ap("")
    ap("Counts are per image.  A single image can fail multiple rules.")
    ap("")
    ap("| Rule | ✅ ok | ⚠️ warn | ❌ fail | ❓ unverified |")
    ap("|---|--:|--:|--:|--:|")
    for code, counts in sorted(report["per_image_findings_rollup"].items()):
        ap(
            f"| `{code}` | {counts.get('ok', 0):,} | {counts.get('warn', 0):,} "
            f"| {counts.get('fail', 0):,} | {counts.get('unverified', 0):,} |"
        )
    ap("")

    failed = report["files_with_failures"]
    warned = report["files_with_warnings"]
    if failed:
        ap(f"## Files with failures ({len(failed)})")
        ap("")
        preview = failed[:20]
        for name in preview:
            ap(f"- `{name}`")
        if len(failed) > len(preview):
            ap(f"- … {len(failed) - len(preview)} more (see JSON)")
        ap("")
    if warned:
        ap(f"## Files with warnings ({len(warned)})")
        ap("")
        preview = warned[:20]
        for name in preview:
            ap(f"- `{name}`")
        if len(warned) > len(preview):
            ap(f"- … {len(warned) - len(preview)} more (see JSON)")
        ap("")

    if not failed and not warned:
        ap("## Files needing review")
        ap("")
        ap("None.  All images passed every per-image check.")
        ap("")

    ap("---")
    ap("")
    ap(
        "Report generated by `reef_sfm_provenance.intake_report`.  "
        "Validation rules derive from the P1WHKTRD metadata "
        "(Johnson et al. 2025).  See `src/reef_sfm_provenance/validation.py` "
        "for the rule source code."
    )
    path.write_text("\n".join(lines))
    return path


__all__ = ["build_report", "write_report_json", "write_report_markdown"]
