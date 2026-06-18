"""Assemble a human-readable Markdown report from manifest + QC + reconciliation."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .models import ReconciliationReport, RunManifest
from .qc.validator import QCReport


def render_markdown(
    manifest: RunManifest,
    qc: Optional[QCReport] = None,
    reconciliation: Optional[ReconciliationReport] = None,
) -> str:
    """Render a Markdown report string from structured run data.

    All three inputs are optional beyond the manifest. Missing QC or
    reconciliation sections are omitted (not replaced with placeholder tables).
    """
    lines: list[str] = []

    # --- header ---
    lines += [f"# Processing Report: {manifest.run_id}", ""]
    lines += [f"**Site:** {manifest.site}  "]
    if manifest.transect:
        lines += [f"**Transect:** {manifest.transect}  "]
    if manifest.code_version:
        lines += [f"**Code version:** `{manifest.code_version}`  "]
    lines.append("")

    # --- processing summary ---
    lines += ["## Processing Summary", ""]
    rows = [
        ("Run ID", manifest.run_id),
        ("Site", manifest.site),
        ("Transect", manifest.transect or "—"),
        ("CRS", manifest.crs or "LOCAL_CS (no geographic reference)"),
        ("Created", manifest.created_at.isoformat()),
    ]
    if manifest.camera_alignment:
        total = manifest.camera_alignment.get("images_total", "—")
        aligned = manifest.camera_alignment.get("images_aligned", "—")
        rows.append(("Camera alignment", f"{aligned} / {total} images"))
    if manifest.error_metrics:
        for k, v in manifest.error_metrics.items():
            rows.append((k.replace("_", " ").title(), str(v)))
    lines += ["| Field | Value |", "| --- | --- |"]
    for label, value in rows:
        lines.append(f"| {label} | {value} |")
    lines.append("")

    # --- environment ---
    if manifest.environment.software or manifest.environment.instance_id:
        lines += ["## Environment", ""]
        if manifest.environment.instance_id:
            lines.append(f"**Instance:** `{manifest.environment.instance_id}`  ")
        if manifest.environment.software:
            for sv in manifest.environment.software:
                ver = sv.version or "unknown"
                lines.append(f"- {sv.name} {ver}")
        lines.append("")

    # --- artifacts ---
    if manifest.artifacts:
        lines += ["## Output Artifacts", ""]
        lines += ["| Kind | Path | SHA-256 | Size |", "| --- | --- | --- | --- |"]
        for art in manifest.artifacts:
            sha = f"`{art.sha256[:12]}…`" if art.sha256 else "—"
            size = f"{art.size_bytes:,} B" if art.size_bytes else "—"
            lines.append(f"| {art.kind.value} | `{art.path}` | {sha} | {size} |")
        lines.append("")

    # --- QC ---
    if qc is not None:
        lines += ["## QC Results", ""]
        n_pass = sum(c.passed is True for c in qc.criteria)
        n_fail = sum(c.passed is False for c in qc.criteria)
        n_ne = sum(c.passed is None for c in qc.criteria)
        if qc.passed is True:
            verdict = "PASS"
        elif qc.passed is False:
            verdict = "FAIL"
        else:
            verdict = "NOT EVALUABLE"
        lines.append(
            f"**Overall:** {verdict}  |  "
            f"pass={n_pass}  fail={n_fail}  not_evaluable={n_ne}"
        )
        lines.append("")
        lines += ["| Check | Category | Status | Expected | Observed |",
                  "| --- | --- | --- | --- | --- |"]
        for c in qc.criteria:
            if c.passed is True:
                status = "**pass**"
            elif c.passed is False:
                status = "**fail**"
            else:
                status = "not_evaluable"
            exp = str(c.threshold) if c.threshold is not None else "—"
            obs = str(c.observed) if c.observed is not None else "—"
            lines.append(f"| {c.name} | {c.category} | {status} | {exp} | {obs} |")
        lines.append("")

    # --- reconciliation ---
    if reconciliation is not None:
        lines += ["## Metric Reconciliation", ""]
        lines.append(f"*{reconciliation.firewall_note}*")
        lines.append("")
        lines += ["| Metric | Local | Published | Δ% | Reproducibility | Explanation |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for r in reconciliation.results:
            local = f"{r.local_value:.4f}" if r.local_value is not None else "—"
            pub = f"{r.published_value:.4f}" if r.published_value is not None else "—"
            pct = f"{r.percent_difference:+.1f}%" if r.percent_difference is not None else "—"
            repro = r.reproducibility.value
            expl = (r.explanation or "").replace("|", "\\|")
            lines.append(f"| {r.metric_name} | {local} | {pub} | {pct} | {repro} | {expl} |")
        lines.append("")

    # --- metrics ---
    if manifest.metrics:
        lines += ["## Computed Metrics", ""]
        lines += ["| Metric | Value | Unit | Window | Implementation |",
                  "| --- | --- | --- | --- | --- |"]
        for m in manifest.metrics:
            lines.append(
                f"| {m.name} | {m.value:.6g} | {m.unit or '—'} | "
                f"{m.window_m or '—'} | {m.implementation or '—'} |"
            )
        lines.append("")

    return "\n".join(lines)


def write_report(text: str, path: str | Path) -> Path:
    """Write *text* to *path*.

    If *path* is a directory, writes ``report.md`` inside it. Returns the file
    path written.
    """
    p = Path(path)
    if p.is_dir():
        p = p / "report.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p
