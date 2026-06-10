"""test_gen_manifest.py — TDD for scripts/gen_manifest.py (pure Python).

No EC2, no Metashape. One contract test:
  - manifest of a tmp dir with one known file → expected row present
    (path, size, sha256, harvest date all in the output).
One guard test:
  - MANIFEST.md itself is excluded from its own entries (no recursion).
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path


def _load_gen_manifest():
    spec = importlib.util.spec_from_file_location(
        "gen_manifest",
        Path(__file__).parent.parent / "scripts" / "gen_manifest.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


gm = _load_gen_manifest()


def test_known_file_row_present(tmp_path: Path) -> None:
    """A file in a subdirectory produces a row with the correct path, size,
    and sha256 in MANIFEST.md."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    content = b"dense cloud harvested"
    (logs_dir / "t1_dense.log").write_bytes(content)

    gm.generate_manifest(tmp_path)

    manifest = (tmp_path / "MANIFEST.md").read_text()
    expected_sha = hashlib.sha256(content).hexdigest()

    assert "t1_dense.log" in manifest, "filename not in manifest"
    assert expected_sha in manifest, "sha256 not in manifest"
    assert str(len(content)) in manifest, "byte size not in manifest"


def test_manifest_excludes_itself(tmp_path: Path) -> None:
    """MANIFEST.md is not listed as a row in its own table (no self-reference)."""
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "run.log").write_bytes(b"x")

    gm.generate_manifest(tmp_path)

    manifest = (tmp_path / "MANIFEST.md").read_text()
    lines = [ln for ln in manifest.splitlines() if "MANIFEST.md" in ln and ln.strip().startswith("|")]
    assert not lines, f"MANIFEST.md listed as a data row: {lines}"
