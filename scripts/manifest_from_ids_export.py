#!/usr/bin/env python3
"""
Reshape an IDS viewer "image_data.csv" export into the manifest CSV
format expected by `reef-sfm acquire --manifest`.

Background:
  The USGS IDS viewer at https://cmgds.marine.usgs.gov/idsviewer/ lets
  you click "Download all details" on a data-release page and get back a
  zip containing image_data.csv, exif_data.csv, and keyword_data.csv.
  The image_data.csv has 25 columns including a `public_path` field with
  the direct HTTPS URL for each TIFF — this is the column we need.

  Our acquisition.read_manifest_csv() expects a simpler shape:
      url,name,size

  This script does the column rename and the per-site filter in one step.

Usage:
  python scripts/manifest_from_ids_export.py \\
      --input  path/to/ImageryDataSystem_YYYYMMDDHHMMSS/image_data.csv \\
      --output data/raw/edr_acquisition_manifest.csv \\
      --site-code EDR

Site codes observed in P1WHKTRD filenames:
  AS  American Shoal       LK  Looe Key
  CI  Cook Island          RK  Rock Key
  CP  Cats Paw             SK  Sand Key
  DL  Dogs Leg             SL  Summerland Ledges
  EDR Eastern Dry Rocks
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def reshape(input_path: Path, output_path: Path, site_code: str) -> int:
    """Filter to one site and emit url/name/size columns. Returns row count."""
    needle = f"_{site_code}_"
    written = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with input_path.open(newline="") as fin, output_path.open("w", newline="") as fout:
        reader = csv.DictReader(fin)
        required = {"public_path", "filename", "file_size"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(
                f"Input CSV missing required columns: {sorted(missing)}. "
                f"Got: {reader.fieldnames}"
            )
        writer = csv.DictWriter(fout, fieldnames=["url", "name", "size"])
        writer.writeheader()
        for row in reader:
            if needle not in row["filename"]:
                continue
            if not row["public_path"]:
                continue
            writer.writerow({
                "url": row["public_path"],
                "name": row["filename"],
                "size": row["file_size"],
            })
            written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--input", required=True, type=Path,
                   help="Path to image_data.csv from the IDS viewer export")
    p.add_argument("--output", required=True, type=Path,
                   help="Where to write the reshaped manifest")
    p.add_argument("--site-code", required=True,
                   help="Site code embedded in filenames, e.g. EDR for Eastern Dry Rocks")
    args = p.parse_args(argv)

    if not args.input.is_file():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 2

    n = reshape(args.input, args.output, args.site_code)
    print(f"Wrote {n} rows to {args.output}")
    return 0 if n > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
