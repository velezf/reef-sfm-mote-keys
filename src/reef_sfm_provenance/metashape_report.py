"""Parse a Metashape processing report (HTML/text) → RunManifest.

Extraction points are isolated here so they can be updated when the report
format changes without touching the rest of the package. Fields that cannot be
extracted are left None — the manifest is always constructible regardless of
parse success (a best-effort, never-crash contract).
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from .models import ProcessingEnvironment, RunManifest, SoftwareVersion

logger = logging.getLogger(__name__)


def parse_report(
    report_path: str | Path,
    *,
    run_id: str,
    site: str,
    transect: str | None = None,
) -> RunManifest:
    """Best-effort parse of a Metashape HTML/text/PDF report into a RunManifest.

    Fields that cannot be extracted remain None. The returned manifest is always
    valid and serializable regardless of how little the parser extracts.
    """
    p = Path(report_path)
    text = _read_text(p)

    return RunManifest(
        run_id=run_id,
        site=site,
        transect=transect,
        environment=_extract_environment(text),
        camera_alignment=_extract_alignment(text),
        error_metrics=_extract_errors(text),
    )


def from_esm_report(esm_dict: dict[str, Any], *, run_id: str, site: str) -> RunManifest:
    """Build a RunManifest from the ``esm.report`` dict written to chunk.meta by stage_report.

    This is the primary population path for in-pipeline use; ``parse_report`` is
    the fallback for post-hoc HTML/PDF parsing.
    """
    outcome: dict[str, Any] = esm_dict.get("outcome") or {}

    camera_alignment: dict[str, Any] = {}
    if outcome.get("input_image_count") is not None:
        camera_alignment["images_total"] = outcome["input_image_count"]
    if outcome.get("registered_image_count") is not None:
        camera_alignment["images_aligned"] = outcome["registered_image_count"]

    error_metrics: dict[str, Any] = {}
    if outcome.get("final_reprojection_rms_px") is not None:
        error_metrics["reprojection_error_px"] = outcome["final_reprojection_rms_px"]
    if outcome.get("per_scalebar_errors_m"):
        errs = outcome["per_scalebar_errors_m"]
        error_metrics["scalebar_error_m"] = max(abs(e) for e in errs)

    return RunManifest(
        run_id=run_id,
        site=site,
        camera_alignment=camera_alignment,
        error_metrics=error_metrics,
    )


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _read_text(p: Path) -> str:
    if not p.exists():
        logger.warning("report not found: %s", p)
        return ""
    suffix = p.suffix.lower()
    if suffix in (".html", ".htm", ".txt", ".xml"):
        return p.read_text(errors="replace")
    if suffix == ".pdf":
        try:
            result = subprocess.run(
                ["pdftotext", str(p), "-"],
                capture_output=True, text=True, timeout=30,
            )
            return result.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.debug("pdftotext unavailable; returning empty text for %s", p.name)
            return ""
    # Unknown extension — try reading as text.
    try:
        return p.read_text(errors="replace")
    except OSError:
        return ""


def _extract_environment(text: str) -> ProcessingEnvironment:
    sw: list[SoftwareVersion] = []
    m = re.search(r"Agisoft\s+Metashape(?:\s+Professional)?\s+([\d.]+)", text, re.I)
    if m:
        sw.append(SoftwareVersion(name="Agisoft Metashape Professional", version=m.group(1)))
    return ProcessingEnvironment(software=sw)


def _extract_alignment(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    m = re.search(r"(\d[\d,]*)\s+images?\s+(?:were\s+)?aligned", text, re.I)
    if m:
        out["images_aligned"] = int(m.group(1).replace(",", ""))
    return out


def _extract_errors(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    m = re.search(r"reprojection\s+error[^:]*:\s*([\d.]+)\s*(?:pix|px)", text, re.I)
    if m:
        out["reprojection_error_px"] = float(m.group(1))
    return out
