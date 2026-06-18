"""W3C PROV export.

Converts a :class:`RunManifest` into a PROV document modeled as:

* **Entities** — source images, dense point cloud, DSM, orthomosaic, processing
  report, and the QC/reconciliation reports.
* **Activities** — intake validation, alignment, dense-cloud generation,
  DSM/orthomosaic generation, QC validation, metric reconciliation.
* **Agents** — the processing software, the compute instance, the operator, and
  this package.

The ``prov`` dependency is confined to this module so the core models stay
library-agnostic; if ``prov`` is absent we emit an equivalent PROV-JSON-shaped
dict so the CLI still works.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .models import RunManifest

logger = logging.getLogger(__name__)

NS_URI = "https://velezf.github.io/reef-sfm-mote-keys/prov#"
NS_PREFIX = "reef"


def to_prov_document(manifest: RunManifest):
    """Build a ``prov.model.ProvDocument`` from the manifest.

    Falls back to a plain dict (PROV-JSON-shaped) if the ``prov`` package is
    unavailable, so the CLI works without the optional dependency.
    """
    try:
        from prov.model import ProvDocument
    except ImportError:
        logger.warning("prov not installed; emitting PROV-JSON-shaped dict instead.")
        return _to_prov_dict(manifest)

    doc = ProvDocument()
    doc.add_namespace(NS_PREFIX, NS_URI)

    def qn(local: str) -> str:
        return f"{NS_PREFIX}:{local}"

    # Agents
    pkg = doc.agent(qn("reef_sfm_provenance"), {"prov:type": "prov:SoftwareAgent"})
    doc.agent(qn("operator"))
    for sv in manifest.environment.software:
        doc.agent(qn(f"software/{sv.name}"), {"reef:version": sv.version or "unknown"})
    if manifest.environment.instance_id:
        doc.agent(
            qn(f"instance/{manifest.environment.instance_id}"),
            {"prov:type": "prov:SoftwareAgent"},
        )

    # Entities: artifacts + input dataset
    if manifest.input_dataset:
        doc.entity(qn("input_dataset"),
                   {"reef:image_count": manifest.input_dataset.image_count})
    for art in manifest.artifacts:
        doc.entity(
            qn(f"artifact/{art.kind.value}"),
            {"reef:path": art.path, "reef:sha256": art.sha256 or ""},
        )

    # Activities: pipeline steps, associated with the software agent
    for step in manifest.steps:
        act = doc.activity(qn(f"activity/{step.name}"), step.started_at, step.ended_at)
        doc.wasAssociatedWith(act, pkg)
        for out in step.outputs:
            ent = doc.entity(qn(f"output/{out}"))
            doc.wasGeneratedBy(ent, act)

    if manifest.input_dataset:
        doc.wasAttributedTo(qn("input_dataset"), qn("operator"))

    return doc


def _to_prov_dict(manifest: RunManifest) -> dict:
    """Minimal PROV-JSON-shaped fallback when ``prov`` is unavailable."""
    return {
        "prefix": {NS_PREFIX: NS_URI},
        "agent": {f"{NS_PREFIX}:reef_sfm_provenance": {"prov:type": "prov:SoftwareAgent"}},
        "entity": {
            f"{NS_PREFIX}:artifact/{a.kind.value}": {
                "reef:path": a.path,
                "reef:sha256": a.sha256,
            }
            for a in manifest.artifacts
        },
        "activity": {
            f"{NS_PREFIX}:activity/{s.name}": {
                "prov:startTime": s.started_at.isoformat() if s.started_at else None
            }
            for s in manifest.steps
        },
    }


def export_prov(manifest: RunManifest, path: str | Path) -> Path:
    """Serialize the PROV representation to ``provenance.json``.

    If *path* is a directory, writes ``provenance.json`` inside it.
    Returns the file path written.
    """
    p = Path(path)
    if p.is_dir():
        p = p / "provenance.json"
    doc = to_prov_document(manifest)
    if hasattr(doc, "serialize"):
        p.write_text(doc.serialize(indent=2))
    else:
        p.write_text(json.dumps(doc, indent=2, default=str))
    logger.info("wrote provenance to %s", p)
    return p
