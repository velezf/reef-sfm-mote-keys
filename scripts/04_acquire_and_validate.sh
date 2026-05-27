#!/usr/bin/env bash
#
# Acquire EasternDryRocks imagery from USGS P1WHKTRD, validate intake, and
# emit contact sheets.  Designed to be run inside a long-lived `tmux` or
# `screen` session on the EC2 instance so an SSH drop won't kill the
# download.
#
# Usage:
#     ./scripts/04_acquire_and_validate.sh [DATA_ROOT] [--manifest PATH]
#
# DATA_ROOT defaults to /data, which is where Chat 2's launch template
# mounts the secondary EBS data volume.
#
# --manifest PATH passes a pre-built CSV (url,name,size) directly to
# `reef-sfm acquire`, bypassing the ScienceBase API walk.  Use this when
# the IDS viewer's image_data.csv export has been reshaped via the
# scripts/manifest_from_ids_export.py recipe (see ADR-0008).

set -euo pipefail

DATA_ROOT="${1:-/data}"
shift || true

MANIFEST=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --manifest)
            MANIFEST="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

SITE="${SITE:-EasternDryRocks}"
DOI="${DOI:-10.5066/P1WHKTRD}"
MAX_WORKERS="${MAX_WORKERS:-}"

RAW_DIR="${DATA_ROOT}/raw/P1WHKTRD"
SITE_DIR="${RAW_DIR}/${SITE}"
FIG_DIR="${DATA_ROOT}/figures/contact_sheets/${SITE}"

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "${PROJECT_DIR}"

# Prefer the project venv if present, else `uv run` resolves it.
if [[ -x ".venv/bin/reef-sfm" ]]; then
    REEF_SFM=(".venv/bin/reef-sfm")
else
    REEF_SFM=(uv run reef-sfm)
fi

ACQUIRE_ARGS=(--out-dir "${RAW_DIR}" --site "${SITE}" --doi "${DOI}")
if [[ -n "${MANIFEST}" ]]; then
    if [[ ! -f "${MANIFEST}" ]]; then
        echo "Manifest file not found: ${MANIFEST}" >&2
        exit 2
    fi
    echo "Using manifest: ${MANIFEST}"
    ACQUIRE_ARGS+=(--manifest "${MANIFEST}")
fi
if [[ -n "${MAX_WORKERS}" ]]; then
    ACQUIRE_ARGS+=(--max-workers "${MAX_WORKERS}")
fi

echo "=== reef-sfm acquire ==="
"${REEF_SFM[@]}" -v acquire "${ACQUIRE_ARGS[@]}"

echo
echo "=== reef-sfm validate-intake ==="
"${REEF_SFM[@]}" -v validate-intake "${SITE_DIR}" \
    --site "${SITE}" --doi "${DOI}" \
    --write-inventory

echo
echo "=== reef-sfm contact-sheet ==="
"${REEF_SFM[@]}" -v contact-sheet "${SITE_DIR}" --out-dir "${FIG_DIR}"

echo
echo "Done.  Outputs:"
echo "  Provenance:    ${SITE_DIR}/_provenance.json"
echo "  Inventory:     ${SITE_DIR}/intake_inventory.json"
echo "  QC report:     ${SITE_DIR}/intake_qc_report.{md,json}"
echo "  Contact sheets: ${FIG_DIR}/"
echo
echo "Next: take an EBS snapshot of the data volume as a recovery point."
echo "  aws ec2 create-snapshot \\"
echo "    --volume-id <DATA_VOLUME_ID_FROM_CHAT_2> \\"
echo "    --description 'reef-sfm-mote-keys: post-Chat-4 EasternDryRocks intake'"
