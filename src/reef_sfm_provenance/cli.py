"""Typer CLI — a thin wrapper over the importable functions. No core logic lives
here; every command calls into a module and prints/writes the result.

Two command surfaces are exposed:

* ``reef-sfm``   : all subcommands (validate-intake, parse-report, qc, reconcile,
                   export-prov, report, acquire, contact-sheet)
* ``reef-audit`` : same app, aliased entry point for QC-focused workflows
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer

from .logging_config import configure_logging
from .metashape_report import parse_report
from .provenance import export_prov
from .reports import render_markdown, write_report
from .run_manifest import load_manifest, write_manifest

app = typer.Typer(
    add_completion=False,
    help="Provenance, QC, and reconciliation for reef SfM runs.",
)


def _console():
    try:
        from rich.console import Console

        return Console()
    except ImportError:
        return None


@app.callback()
def _main(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    configure_logging(level=logging.DEBUG if verbose else logging.INFO)


# ---------------------------------------------------------------------------
# QC-package commands
# ---------------------------------------------------------------------------

@app.command("validate-intake")
def cmd_validate_intake(input_dir: Path) -> None:
    """Validate an imagery intake directory (extension, duplicates, counts, hashes)."""
    from .intake import validate_intake

    report = validate_intake(input_dir)
    typer.echo(report.model_dump_json(indent=2))
    raise typer.Exit(0 if report.ok else 1)


@app.command("parse-report")
def cmd_parse_report(
    report_path: Path,
    run_id: str = typer.Option(..., help="Run identifier, e.g. EDR_T1_20260610"),
    site: str = typer.Option(..., help="Site name, e.g. EasternDryRocks"),
    out: Optional[Path] = typer.Option(None, help="Write run_manifest.json here."),
) -> None:
    """Parse a Metashape processing report into a run manifest."""
    manifest = parse_report(report_path, run_id=run_id, site=site)
    if out:
        path = write_manifest(manifest, out)
        typer.echo(f"wrote {path}")
    else:
        typer.echo(manifest.model_dump_json(indent=2))


@app.command("qc")
def cmd_qc(
    run_dir: Path,
    out: Optional[Path] = typer.Option(None, help="Directory or file for qc_report.json"),
) -> None:
    """Run structural QC against a run manifest (and filesystem if run_dir is a folder)."""
    from .qc.checker import run_qc

    manifest = load_manifest(run_dir)
    root = run_dir if run_dir.is_dir() else None
    report = run_qc(manifest, run_root=root)
    _write_json(report.model_dump_json(indent=2), out or run_dir, "qc_report.json")
    typer.echo(f"QC summary: {report.summary}")
    raise typer.Exit(0 if report.passed else 1)


@app.command("reconcile")
def cmd_reconcile(
    run_dir: Path,
    published: Path = typer.Option(..., "--published", help="Published reference CSV."),
    out: Optional[Path] = typer.Option(None),
) -> None:
    """Reconcile local metrics against published reference values (comparison-only)."""
    from .reconcile.reconciler import load_published_metrics, reconcile_metrics

    manifest = load_manifest(run_dir)
    pub = load_published_metrics(published)
    report = reconcile_metrics(manifest.metrics, pub, run_id=manifest.run_id)
    _write_json(report.model_dump_json(indent=2), out or run_dir, "reconciliation_report.json")
    typer.echo(f"reconciled {len(report.results)} metrics")


@app.command("export-prov")
def cmd_export_prov(
    run_dir: Path,
    out: Optional[Path] = typer.Option(None),
) -> None:
    """Export W3C PROV-JSON for the run."""
    manifest = load_manifest(run_dir)
    path = export_prov(manifest, out or run_dir)
    typer.echo(f"wrote {path}")


@app.command("report")
def cmd_report(
    run_dir: Path,
    out: Optional[Path] = typer.Option(None),
) -> None:
    """Assemble the human-readable Markdown report from manifest + QC + reconciliation."""
    from .models import QCReport, ReconciliationReport

    manifest = load_manifest(run_dir)
    qc = _maybe_load_model(run_dir / "qc_report.json", QCReport)
    rec = _maybe_load_model(run_dir / "reconciliation_report.json", ReconciliationReport)
    text = render_markdown(manifest, qc, rec)
    path = write_report(text, out or run_dir)
    typer.echo(f"wrote {path}")


@app.command("inspect")
def cmd_inspect(run_dir: Path) -> None:
    """Summarize a run manifest (the reef-audit entry point)."""
    manifest = load_manifest(run_dir)
    console = _console()
    summary = {
        "run_id": manifest.run_id,
        "site": manifest.site,
        "transect": manifest.transect,
        "artifacts": [a.kind.value for a in manifest.artifacts],
        "metrics": [m.name for m in manifest.metrics],
    }
    if console:
        console.print_json(data=summary)
    else:
        typer.echo(json.dumps(summary, indent=2))


# ---------------------------------------------------------------------------
# Legacy intake commands (preserve existing behaviour from __main__.py)
# ---------------------------------------------------------------------------

@app.command("acquire")
def cmd_acquire(
    out_dir: str = typer.Option(..., "--out-dir"),
    site: str = typer.Option("P1WHKTRD", "--site"),
    doi: str = typer.Option("", "--doi"),
    manifest_csv: Optional[Path] = typer.Option(None, "--manifest"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    max_workers: int = typer.Option(8, "--max-workers"),
) -> None:
    """Download EasternDryRocks images from a USGS data release."""
    from .acquisition import (
        DEFAULT_SITE,
        DOI_IMAGES,
        ScienceBaseClient,
        download_all,
        enumerate_files_for_site,
        load_provenance,
        read_manifest_csv,
        write_provenance,
    )

    _doi = doi or DOI_IMAGES
    _site = site or DEFAULT_SITE
    out = Path(out_dir).expanduser().resolve()
    site_dir = out / _site
    site_dir.mkdir(parents=True, exist_ok=True)

    if manifest_csv:
        files = read_manifest_csv(manifest_csv)
    else:
        client = ScienceBaseClient()
        files = enumerate_files_for_site(client, site=_site, doi=_doi)

    if not files:
        typer.echo(f"No files found for site {_site!r} at {_doi}", err=True)
        raise typer.Exit(2)

    typer.echo(f"Planned download: {len(files)} files → {site_dir}")
    if dry_run:
        for f in files[:5]:
            typer.echo(f"  {f.name}  ({f.size} bytes)")
        if len(files) > 5:
            typer.echo(f"  … and {len(files) - 5} more")
        return

    existing_hashes: dict[str, str] = {}
    prov_path = site_dir / "_provenance.json"
    if prov_path.exists():
        prior = load_provenance(prov_path)
        existing_hashes = {f["name"]: f["sha256"] for f in prior.get("files", [])}

    results = download_all(files, site_dir, expected_hashes=existing_hashes, max_workers=max_workers)
    write_provenance(results, site_dir, doi=_doi, site=_site)
    typer.echo(f"Done. {len(results)} files in {site_dir}")


@app.command("contact-sheet")
def cmd_contact_sheet(
    site_dir: Path,
    out_dir: Path = typer.Option(..., "--out-dir"),
    cols: int = typer.Option(6),
    rows: int = typer.Option(6),
    tile_w: int = typer.Option(220),
    tile_h: int = typer.Option(165),
) -> None:
    """Render JPEG contact sheets for visual review."""
    from .contact_sheet import generate_contact_sheets
    from .inventory import iter_image_paths

    paths = list(iter_image_paths(site_dir))
    if not paths:
        typer.echo(f"No images under {site_dir}", err=True)
        raise typer.Exit(2)
    written = generate_contact_sheets(paths, out_dir, cols=cols, rows=rows,
                                      tile_w=tile_w, tile_h=tile_h)
    typer.echo(f"Wrote {len(written)} contact sheet(s) to {out_dir}")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_json(payload: str, path: Path, filename: str) -> Path:
    p = (path / filename) if path.is_dir() else path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(payload)
    return p


def _maybe_load_model(path: Path, model_cls):
    if not path.exists():
        return None
    return model_cls.model_validate_json(path.read_text())


if __name__ == "__main__":  # pragma: no cover
    app()
