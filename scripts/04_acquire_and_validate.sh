#!/usr/bin/env bash
#
# Acquire EasternDryRocks imagery from USGS P1WHKTRD, validate intake, and
# emit contact sheets.  Designed to be run inside a long-lived `tmux` or
# `screen` session on the EC2 instance so an SSH drop won't kill the
# download.
#
# Usage:
#     ./scripts/04_acquire_and_validate.sh [DATA_ROOT]
#
# DATA_ROOT defaults to /data, which is where Chat 2's launch template
# mounts the secondary EBS data volume.

set -euo pipefail

DATA_ROOT="${1:-/data}"
SITE="${SITE:-EasternDryRocks}"
DOI="${DOI:-10.5066/P1WHKTRD}"

RAW_DIR="${DATA_ROOT}/raw/P1WHKTRD"
SITE_DIR="${RAW_DIR}/${SITE}"
FIG_DIR="${DATA_ROOT}/figures/contact_sheets/${SITE}"

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "${PROJECT_DIR}"

# Use the project venv if present, else assume reef-sfm is on PATH.
if [[ -x ".venv/bin/reef-sfm" ]]; then
    REEF_SFM=".venv/bin/reef-sfm"
else
    REEF_SFM="reef-sfm"
fi

echo "=== reef-sfm acquire ==="
"${REEF_SFM}" -v acquire --out-dir "${RAW_DIR}" --site "${SITE}" --doi "${DOI}"

echo
echo "=== reef-sfm validate-intake ==="
"${REEF_SFM}" -v validate-intake "${SITE_DIR}" \
    --site "${SITE}" --doi "${DOI}" \
    --write-inventory

echo
echo "=== reef-sfm contact-sheet ==="
"${REEF_SFM}" -v contact-sheet "${SITE_DIR}" --out-dir "${FIG_DIR}"

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
echo "    --description \"reef-sfm-mote-keys: post-Chat-4 EasternDryRocks intake\""
