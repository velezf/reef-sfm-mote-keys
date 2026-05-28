#!/usr/bin/env bash
# run_headless.sh — launch the EDR pipeline headless, survives SSH disconnects.
#
# The dense-cloud stage at ESM "High" quality on ~3,271 images is expected to
# run 24-48 h on the g6.4xlarge / L4 (per ADR-0010 Consequences). It MUST NOT
# be tied to your SSH session. This wrapper runs the pipeline inside tmux and
# tees output to a timestamped log on the data volume.
#
# Usage:
#   ./run_headless.sh align        # quick, foreground-ish
#   ./run_headless.sh dense        # the long one — detaches into tmux
#   ./run_headless.sh all
#
# Reattach later:  tmux attach -t edr
set -euo pipefail

STAGE="${1:-all}"
METASHAPE="/opt/metashape-pro/metashape.sh"
REPO="/data/reef-sfm-mote-keys"
SCRIPT="$REPO/scripts/metashape/run_pipeline.py"
# Working area for Metashape project + products on the data volume (NOT the raw
# image dir, which stays read-only/hash-stable from Chat 4).
WORK="/data/edr_work"
PROJECT="$WORK/edr.psx"
IMAGE_ROOT="/data/raw/P1WHKTRD/EasternDryRocks"   # flat dir; grouping is by filename
OUT_ROOT="$WORK/products"
LOGDIR="$WORK/logs"
FOCAL_DECISION="$WORK/smoke/products/focal_decision.json"
SESSION="edr"

mkdir -p "$WORK" "$LOGDIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="$LOGDIR/pipeline_${STAGE}_${STAMP}.log"

ARGS=(-r "$SCRIPT" --project "$PROJECT" --out-root "$OUT_ROOT" --stage "$STAGE")
# image-root only needed for align; harmless to always pass
ARGS+=(--image-root "$IMAGE_ROOT")
# Focal-length decision artifact from the smoke test (read by the align stage):
ARGS+=(--focal-decision "$FOCAL_DECISION")
# If the Logan module has been vendored + verified, point at it:
if python3 -c "import reduce_error" 2>/dev/null; then
  ARGS+=(--logan-module reduce_error)
  echo "Logan module detected; using it for error reduction."
else
  echo "Logan module NOT importable; pipeline will use the built-in faithful"
  echo "transcription for error reduction. See docs Logan-integration section."
fi

echo "Launching stage '$STAGE' under tmux session '$SESSION'."
echo "Log: $LOG"
tmux new-session -d -s "$SESSION" \
  "$METASHAPE ${ARGS[*]} 2>&1 | tee '$LOG'; echo EXIT=\$? | tee -a '$LOG'"
echo "Detached. Reattach with:  tmux attach -t $SESSION"
echo "Tail the log with:        tail -f '$LOG'"
