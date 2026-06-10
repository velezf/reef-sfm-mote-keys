#!/usr/bin/env bash
# harvest_artifacts.sh — rsync pipeline artifacts from EC2 to local artifacts/.
#
# Usage:
#   ./scripts/harvest_artifacts.sh [--dry-run] [--source <EC2_PATH>]
#                                   [--dest <LOCAL_PATH>] [--include-project]
#
# Defaults:
#   EC2 host  : reef-ec2 (SSH alias from ~/.ssh/config)
#   EC2 source: /data/edr_work
#   local dest: artifacts/   (relative to repo root)
#
# By default, *.psx and *.files/ are excluded (full project archive is large
# and lives in EBS snapshots). Pass --include-project to pull them too.
# --dry-run  shows what would transfer without writing anything.
# Idempotent: re-running syncs only changed/new files (rsync checksum).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

EC2_HOST="reef-ec2"
EC2_SOURCE="/data/edr_work"
LOCAL_DEST="${REPO_ROOT}/artifacts"
DRY_RUN=0
INCLUDE_PROJECT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)          DRY_RUN=1 ;;
    --include-project)  INCLUDE_PROJECT=1 ;;
    --source)           EC2_SOURCE="$2"; shift ;;
    --dest)             LOCAL_DEST="$2"; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 64 ;;
  esac
  shift
done

RSYNC_OPTS=(-avh --checksum --progress)
[[ "${DRY_RUN}" -eq 1 ]] && RSYNC_OPTS+=(--dry-run)

# Always exclude full project archives unless explicitly requested
EXCLUDES=(
  --exclude="*.psz"
  --exclude="backups/"
  --exclude="edr_t1.files/"
  --exclude="edr_t3.files/"
  --exclude="edr_t3-1.files/"
)
if [[ "${INCLUDE_PROJECT}" -eq 0 ]]; then
  EXCLUDES+=(
    --exclude="*.psx"
    --exclude="*_postlevel_*.files/"
    --exclude="*_preregion_*.files/"
    --exclude="*_postdense_*.files/"
    --exclude="*_pcvalidate.files/"
    --exclude="*_pipevalidate.files/"
    --exclude="*_planartest.files/"
    --exclude="*_relevel*.files/"
    --exclude="*_qab.files/"
  )
fi

echo "=== harvest_artifacts.sh ==="
echo "  source : ${EC2_HOST}:${EC2_SOURCE}/"
echo "  dest   : ${LOCAL_DEST}/"
[[ "${DRY_RUN}" -eq 1 ]]        && echo "  mode   : DRY-RUN (no files written)"
[[ "${INCLUDE_PROJECT}" -eq 1 ]] && echo "  project: INCLUDED (*.psx + *.files)"
echo ""

mkdir -p "${LOCAL_DEST}/logs" "${LOCAL_DEST}/qc" "${LOCAL_DEST}/rasters" \
         "${LOCAL_DEST}/previews" "${LOCAL_DEST}/renders"

rsync "${RSYNC_OPTS[@]}" "${EXCLUDES[@]}" \
  "${EC2_HOST}:${EC2_SOURCE}/" \
  "${LOCAL_DEST}/"

echo ""
echo "=== harvest complete ==="
