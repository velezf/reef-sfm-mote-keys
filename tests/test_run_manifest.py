"""Tests for reef_sfm_provenance.run_manifest (load/write/verify_against_disk)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from reef_sfm_provenance.models import Artifact, ArtifactKind, RunManifest
from reef_sfm_provenance.run_manifest import load_manifest, verify_against_disk, write_manifest


def _make_manifest(**kwargs) -> RunManifest:
    return RunManifest(run_id="EDR_T1_R2_test", site="EasternDryRocks", **kwargs)


# ---------------------------------------------------------------------------
# load / write round-trip
# ---------------------------------------------------------------------------

def test_write_to_file_and_load_back(tmp_path: Path):
    m = _make_manifest(transect="T1_R2", camera_alignment={"images_total": 272})
    out = write_manifest(m, tmp_path / "run_manifest.json")
    assert out.exists()
    loaded = load_manifest(out)
    assert loaded.run_id == m.run_id
    assert loaded.camera_alignment["images_total"] == 272


def test_write_to_dir_creates_run_manifest_json(tmp_path: Path):
    m = _make_manifest()
    out = write_manifest(m, tmp_path)
    assert out.name == "run_manifest.json"
    assert out.exists()


def test_load_from_dir_finds_run_manifest_json(tmp_path: Path):
    m = _make_manifest()
    write_manifest(m, tmp_path)
    loaded = load_manifest(tmp_path)
    assert loaded.run_id == m.run_id


def test_round_trip_preserves_artifacts(tmp_path: Path):
    m = _make_manifest(
        artifacts=[Artifact(kind=ArtifactKind.DSM, path="products/dsm.tif", sha256="ab" * 32)]
    )
    write_manifest(m, tmp_path)
    loaded = load_manifest(tmp_path)
    assert loaded.artifacts[0].sha256 == "ab" * 32
    assert loaded.artifacts[0].kind is ArtifactKind.DSM


# ---------------------------------------------------------------------------
# verify_against_disk
# ---------------------------------------------------------------------------

def test_verify_ok_when_file_present_and_hash_matches(tmp_path: Path):
    content = b"fake DSM bytes"
    sha = hashlib.sha256(content).hexdigest()
    (tmp_path / "dsm.tif").write_bytes(content)

    m = _make_manifest(artifacts=[Artifact(kind=ArtifactKind.DSM, path="dsm.tif", sha256=sha)])
    findings = verify_against_disk(m, tmp_path)
    assert len(findings) == 1
    assert findings[0]["status"] == "ok"


def test_verify_missing_file(tmp_path: Path):
    m = _make_manifest(
        artifacts=[Artifact(kind=ArtifactKind.DSM, path="does_not_exist.tif")]
    )
    findings = verify_against_disk(m, tmp_path)
    assert findings[0]["status"] == "missing"


def test_verify_empty_file(tmp_path: Path):
    (tmp_path / "empty.tif").write_bytes(b"")
    m = _make_manifest(
        artifacts=[Artifact(kind=ArtifactKind.DSM, path="empty.tif")]
    )
    findings = verify_against_disk(m, tmp_path)
    assert findings[0]["status"] == "empty"


def test_verify_hash_mismatch(tmp_path: Path):
    (tmp_path / "dsm.tif").write_bytes(b"real content")
    wrong_sha = "00" * 32
    m = _make_manifest(
        artifacts=[Artifact(kind=ArtifactKind.DSM, path="dsm.tif", sha256=wrong_sha)]
    )
    findings = verify_against_disk(m, tmp_path)
    assert findings[0]["status"] == "hash_mismatch"


def test_verify_no_sha_skips_hash_check(tmp_path: Path):
    (tmp_path / "ortho.tif").write_bytes(b"ortho bytes")
    m = _make_manifest(
        artifacts=[Artifact(kind=ArtifactKind.ORTHOMOSAIC, path="ortho.tif")]  # no sha256
    )
    findings = verify_against_disk(m, tmp_path)
    assert findings[0]["status"] == "ok"


def test_verify_all_findings_returned(tmp_path: Path):
    content = b"data"
    sha = hashlib.sha256(content).hexdigest()
    (tmp_path / "good.tif").write_bytes(content)
    # missing.tif intentionally absent
    m = _make_manifest(
        artifacts=[
            Artifact(kind=ArtifactKind.DSM, path="good.tif", sha256=sha),
            Artifact(kind=ArtifactKind.ORTHOMOSAIC, path="missing.tif"),
        ]
    )
    findings = verify_against_disk(m, tmp_path)
    assert len(findings) == 2
    statuses = {f["status"] for f in findings}
    assert statuses == {"ok", "missing"}


def test_verify_no_artifacts_returns_empty_list(tmp_path: Path):
    m = _make_manifest()
    findings = verify_against_disk(m, tmp_path)
    assert findings == []
