"""reef_sfm_provenance.manifest — the processing-manifest contract.

Chat-6 layer: a typed schema for everything we must be able to say about a
Metashape processing run — provenance (what ran where, on which bytes),
parameters (what was asked of Metashape; Toth ESM Table S2 vocabulary), and
outcome (what came back). The schema is the contract; *populating* it from a
real Metashape report / EC2 environment is a later branch, which is why
every field is Optional.
"""

from reef_sfm_provenance.manifest.schema import (
    OutcomeBlock,
    ParametersBlock,
    ProcessingManifest,
    ProvenanceBlock,
)

__all__ = [
    "OutcomeBlock",
    "ParametersBlock",
    "ProcessingManifest",
    "ProvenanceBlock",
]
