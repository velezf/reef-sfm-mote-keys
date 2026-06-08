#!/usr/bin/env bash
# Reproducible REAL-CHUNK integration smoke for the vendored 2.x USGS Logan routine
# (ADR-0023). Copies a real aligned chunk to a scratch psx, runs the 2.x RU/PA/RE
# filters against the real 2.3.1 tie_points cloud, then DISCARDS the scratch. Never
# touches the source psx or any live/shipped project. Exits non-zero on any API error.
#
#   scripts/metashape/run_logan_real_chunk_smoke.sh [SOURCE_ALIGNED_PSX]
#
# Default SOURCE = edr_t3-1.psx (smallest real aligned T3 chunk: 515 cams / ~822k tie
# points). The source is opened only by `cp`; the smoke runs on the copy.
set -euo pipefail

SRC="${1:-/data/edr_work/edr_t3-1.psx}"
MS="${METASHAPE:-/opt/metashape-pro/metashape.sh}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRATCH="$(mktemp -d /data/edr_work/.logan_smoke.XXXXXX)"
trap 'rm -rf "$SCRATCH"' EXIT

case "$SRC" in
  *backups/*) echo "refusing to use a backup as source"; exit 2;;
  /data/edr_work/edr_t1.psx|/data/edr_work/edr_t3.psx)
    echo "refusing to use the live/shipped psx $SRC as source"; exit 2;;
esac

cp -a "$SRC" "$SCRATCH/scratch.psx"
cp -a "${SRC%.psx}.files" "$SCRATCH/scratch.files"

"$MS" -platform offscreen -r "$HERE/smoke_logan_real_chunk.py" "$SCRATCH/scratch.psx" \
  2>&1 | grep -E "vendored module|fixture:|RU ok|PA ok|RE ok|SMOKE: PASS|Error|Traceback"
echo "scratch discarded: $SCRATCH"
