"""Run manifest I/O: load/write RunManifest JSON; disk integrity check.

Named ``run_manifest`` (not ``manifest``) to avoid shadowing the existing
``reef_sfm_provenance.manifest`` subpackage (``manifest/schema.py``).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .models import RunManifest


def load_manifest(path: str | Path) -> RunManifest:
    """Load a RunManifest from a file or directory.

    If *path* is a directory, looks for ``run_manifest.json`` inside it.
    """
    p = Path(path)
    if p.is_dir():
        p = p / "run_manifest.json"
    return RunManifest.model_validate_json(p.read_text())


def write_manifest(manifest: RunManifest, path: str | Path) -> Path:
    """Write a RunManifest to *path*.

    If *path* is a directory, writes ``run_manifest.json`` inside it.
    Returns the file path written.
    """
    p = Path(path)
    if p.is_dir():
        p = p / "run_manifest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(manifest.model_dump_json(indent=2))
    return p


def verify_against_disk(manifest: RunManifest, root: Path) -> list[dict]:
    """Check each artifact against the filesystem.

    Returns a list of dicts with keys:
      path   — artifact path (relative to root)
      status — ``ok`` | ``missing`` | ``empty`` | ``hash_mismatch``
      detail — human-readable explanation

    All artifacts are checked; the list is always complete (never raises on
    a missing or mismatched file — that is what the caller is checking for).
    """
    findings: list[dict] = []
    for art in manifest.artifacts:
        full = root / art.path
        if not full.exists():
            findings.append({"path": art.path, "status": "missing", "detail": "file not found"})
            continue
        if full.stat().st_size == 0:
            findings.append({"path": art.path, "status": "empty", "detail": "zero bytes"})
            continue
        if art.sha256:
            actual = hashlib.sha256(full.read_bytes()).hexdigest()
            if actual != art.sha256:
                findings.append({
                    "path": art.path,
                    "status": "hash_mismatch",
                    "detail": f"expected {art.sha256[:8]}… got {actual[:8]}…",
                })
                continue
        findings.append({"path": art.path, "status": "ok", "detail": ""})
    return findings
