"""
Command-line interface for the reef-sfm-provenance package.

This file establishes the `reef-sfm <subcommand>` surface that Chats 6 and 7
also extend.  Chat 4's subcommands:

    reef-sfm acquire        download EasternDryRocks images from USGS
    reef-sfm validate-intake  walk an on-disk site dir and emit the QC report
    reef-sfm contact-sheet  write JPEG contact sheets for visual review

Each subcommand is also importable from this module as `cmd_<name>`, which
keeps the unit tests honest.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__
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
from .contact_sheet import generate_contact_sheets
from .intake_report import build_report, write_report_json, write_report_markdown
from .inventory import build_inventory, iter_image_paths, write_inventory_json
from .validation import validate_dataset, validate_image


def _configure_logging(verbose: int) -> None:
    level = logging.WARNING - 10 * min(verbose, 2)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# acquire
# ---------------------------------------------------------------------------


def cmd_acquire(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir).expanduser().resolve()
    site_dir = out_dir / args.site
    site_dir.mkdir(parents=True, exist_ok=True)

    # Either enumerate via ScienceBase API, or read a user-supplied manifest.
    if args.manifest:
        files = read_manifest_csv(Path(args.manifest).expanduser())
    else:
        client = ScienceBaseClient()
        files = enumerate_files_for_site(client, site=args.site, doi=args.doi)

    if not files:
        print(f"No files found for site {args.site!r} at {args.doi}", file=sys.stderr)
        return 2

    print(f"Planned download: {len(files)} files → {site_dir}")
    if args.dry_run:
        for f in files[:5]:
            print(f"  {f.name}  ({f.size} bytes)")
        if len(files) > 5:
            print(f"  … and {len(files) - 5} more")
        return 0

    # If a prior provenance JSON exists, pass its hashes so resume can
    # verify-without-redownload.
    existing_hashes: dict[str, str] = {}
    prov_path = site_dir / "_provenance.json"
    if prov_path.exists():
        prior = load_provenance(prov_path)
        existing_hashes = {f["name"]: f["sha256"] for f in prior.get("files", [])}

    results = download_all(
        files,
        site_dir,
        expected_hashes=existing_hashes,
        max_workers=args.max_workers,
    )
    write_provenance(results, site_dir, doi=args.doi, site=args.site)
    print(f"Done. {len(results)} files in {site_dir}")
    return 0


# ---------------------------------------------------------------------------
# validate-intake
# ---------------------------------------------------------------------------


def cmd_validate_intake(args: argparse.Namespace) -> int:
    site_dir = Path(args.site_dir).expanduser().resolve()
    if not site_dir.is_dir():
        print(f"Not a directory: {site_dir}", file=sys.stderr)
        return 2

    # Load hashes from acquisition provenance if available, so the inventory
    # records carry SHA-256s without re-hashing.
    hashes: dict[str, str] = {}
    prov_path = site_dir / "_provenance.json"
    if prov_path.exists():
        prior = load_provenance(prov_path)
        hashes = {f["name"]: f["sha256"] for f in prior.get("files", [])}

    inv = build_inventory(site_dir, hashes_by_name=hashes, use_exiftool=args.use_exiftool)
    print(f"Cataloged {len(inv)} images in {site_dir}")

    per_image_findings = []
    for rec in inv:
        per_image_findings.extend(validate_image(rec))
    dataset_findings = validate_dataset(inv)

    report = build_report(
        site=args.site,
        doi=args.doi,
        site_dir=site_dir,
        inventory=inv,
        dataset_findings=dataset_findings,
        per_image_findings=per_image_findings,
    )

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else site_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.write_inventory:
        inv_path = out_dir / "intake_inventory.json"
        write_inventory_json(inv, inv_path)
        print(f"Inventory:    {inv_path}")

    json_path = out_dir / "intake_qc_report.json"
    md_path = out_dir / "intake_qc_report.md"
    write_report_json(report, json_path)
    write_report_markdown(report, md_path)
    print(f"QC report:    {md_path}")
    print(f"QC report:    {json_path}")
    print(f"Overall:      {report['overall_severity']}")
    return 0 if report["overall_severity"] != "fail" else 1


# ---------------------------------------------------------------------------
# contact-sheet
# ---------------------------------------------------------------------------


def cmd_contact_sheet(args: argparse.Namespace) -> int:
    site_dir = Path(args.site_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    paths = list(iter_image_paths(site_dir))
    if not paths:
        print(f"No images under {site_dir}", file=sys.stderr)
        return 2
    written = generate_contact_sheets(
        paths,
        out_dir,
        cols=args.cols,
        rows=args.rows,
        tile_w=args.tile_w,
        tile_h=args.tile_h,
    )
    print(f"Wrote {len(written)} contact sheet(s) to {out_dir}")
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="reef-sfm",
        description="Data acquisition and intake QC for reef-sfm-mote-keys.",
    )
    p.add_argument("--version", action="version", version=f"reef-sfm-provenance {__version__}")
    p.add_argument("-v", "--verbose", action="count", default=0,
                   help="-v for INFO, -vv for DEBUG")
    sub = p.add_subparsers(dest="command", required=True)

    # acquire
    sp = sub.add_parser("acquire", help="Download images from a USGS data release")
    sp.add_argument("--out-dir", required=True,
                    help="Project data root (e.g. /mnt/data/raw/P1WHKTRD)")
    sp.add_argument("--site", default=DEFAULT_SITE,
                    help=f"Site name to filter on (default: {DEFAULT_SITE})")
    sp.add_argument("--doi", default=DOI_IMAGES,
                    help=f"Data release DOI (default: {DOI_IMAGES})")
    sp.add_argument("--manifest", default=None,
                    help="Optional CSV manifest (url[,name][,size]) "
                         "to use instead of the ScienceBase API walk")
    sp.add_argument("--dry-run", action="store_true",
                    help="Enumerate but do not download")
    sp.add_argument("--max-workers", type=int, default=8, metavar="N",
                    help="Parallel download threads (default: 8; set 1 to serialize)")
    sp.set_defaults(func=cmd_acquire)

    # validate-intake
    sp = sub.add_parser("validate-intake", help="Catalog and QC a downloaded site directory")
    sp.add_argument("site_dir", help="Per-site directory of TIFFs")
    sp.add_argument("--site", default=DEFAULT_SITE)
    sp.add_argument("--doi", default=DOI_IMAGES)
    sp.add_argument("--out-dir", default=None,
                    help="Where to write the report (default: site_dir)")
    sp.add_argument("--write-inventory", action="store_true",
                    help="Also write intake_inventory.json")
    sp.add_argument("--use-exiftool", default=None,
                    action=argparse.BooleanOptionalAction,
                    help="Force exiftool on/off; default = auto-detect")
    sp.set_defaults(func=cmd_validate_intake)

    # contact-sheet
    sp = sub.add_parser("contact-sheet", help="Render JPEG contact sheets")
    sp.add_argument("site_dir")
    sp.add_argument("--out-dir", required=True)
    sp.add_argument("--cols", type=int, default=6)
    sp.add_argument("--rows", type=int, default=6)
    sp.add_argument("--tile-w", type=int, default=220)
    sp.add_argument("--tile-h", type=int, default=165)
    sp.set_defaults(func=cmd_contact_sheet)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
