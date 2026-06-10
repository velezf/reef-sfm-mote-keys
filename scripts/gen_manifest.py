#!/usr/bin/env python3
"""gen_manifest.py — walk artifacts/ and write artifacts/MANIFEST.md.

Usage:
    python scripts/gen_manifest.py [--root <artifacts_dir>]

Writes MANIFEST.md at the root of the artifacts tree with one row per file:
  path (relative to artifacts root), size_bytes, sha256, harvested (ISO date).

MANIFEST.md itself is excluded from the table. .gitkeep files are excluded.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_manifest(root: Path) -> Path:
    """Walk root, write MANIFEST.md, return its path.

    Parameters
    ----------
    root : directory to walk (the artifacts/ tree)

    Returns
    -------
    Path — path to the written MANIFEST.md
    """
    manifest_path = root / "MANIFEST.md"
    harvested = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    rows: list[tuple[str, int, str, str]] = []
    for dirpath, _, filenames in os.walk(root):
        for fname in sorted(filenames):
            if fname == "MANIFEST.md" or fname == ".gitkeep":
                continue
            full = Path(dirpath) / fname
            rel = str(full.relative_to(root))
            size = full.stat().st_size
            sha = _sha256(full)
            rows.append((rel, size, sha, harvested))

    rows.sort(key=lambda r: r[0])

    lines = [
        "# Artifact Manifest",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "",
        "| path | size_bytes | sha256 | harvested |",
        "|------|------------|--------|-----------|",
    ]
    for rel, size, sha, date in rows:
        lines.append(f"| {rel} | {size} | {sha} | {date} |")

    manifest_path.write_text("\n".join(lines) + "\n")
    return manifest_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).parent.parent / "artifacts",
        help="artifacts directory to walk (default: repo artifacts/)",
    )
    args = ap.parse_args()
    out = generate_manifest(args.root)
    print(f"Wrote {out} ({out.stat().st_size} bytes, {sum(1 for ln in out.read_text().splitlines() if ln.startswith('|') and 'path' not in ln) } file(s))")


if __name__ == "__main__":
    main()
