#!/usr/bin/env bash
# spot_imds_watch.sh — watch for a spot interruption and checkpoint on notice.
#
# Part B (spot orchestration), built 2026-06-05. Run DETACHED alongside the
# controller (the controller launches it). Polls two IMDS signals:
#   * events/recommendations/rebalance  — the EARLY, soft warning (minutes)
#   * spot/instance-action              — the HARD ~2-minute reclaim notice
#
# On the hard notice it does the only durable thing available in 2 minutes:
#   1. records the notice to the state dir,
#   2. snapshots the EBS data volume — this captures the LAST VERIFIED
#      STAGE-BOUNDARY CHECKPOINT (run_pipeline saves+verifies at each stage end),
#   3. writes a RESUME_FROM marker (the next stage to run, from the honest
#      reconciler) and the RECLAIM_STOP flag the controller halts on,
#   4. exits so the instance can be reclaimed cleanly.
#
# HONEST LIMITATION (surfaced on purpose): we CANNOT force the in-flight
# Metashape stage to save early — Metashape only persists at stage end (and, for
# the dense, depth maps incrementally). So a reclaim mid-stage loses that stage's
# in-progress work; the snapshot is crash-consistent at the last completed stage
# and the controller re-runs the interrupted stage on the replacement instance.
# This is exactly why the dense (buildPointCloud, not mid-stage checkpointable)
# needs the on-demand-vs-spot decision before it is committed to spot.

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_spot.sh
source "${HERE}/lib_spot.sh"
LOG_TAG="imds-watch"

: "${POLL_SECONDS:=5}"

mkdir -p "${STATE_DIR}"

write_resume_marker(){
  # Ask the honest reconciler what the next stage is (read-only; no lock).
  local next
  next="$("${METASHAPE_SH}" -platform offscreen -r "${HERE}/pipeline_state.py" \
            --project "${PROJECT}" 2>/dev/null \
            | sed -n 's/.*"next_stage": *"\([^"]*\)".*/\1/p' | head -1)"
  {
    echo "reclaimed_at=$(ts)"
    echo "next_stage=${next:-unknown}"
    echo "note=in-flight stage (if any) was NOT saved; resume re-runs it from the last checkpoint"
  } > "${RESUME_MARKER}"
  slog "RESUME marker written: next_stage=${next:-unknown}"
}

on_reclaim(){
  local kind="$1"
  slog "RECLAIM (${kind}) detected — checkpointing before exit."
  echo "kind=${kind} at=$(ts)" > "${STATE_DIR}/RECLAIM_NOTICE"
  local snap; snap="$(snapshot_data_volume "spot-reclaim-${kind}")" || true
  [ -n "${snap}" ] && echo "snapshot=${snap}" >> "${STATE_DIR}/RECLAIM_NOTICE"
  write_resume_marker
  # Halt the controller: it checks this flag between stages.
  echo "stop_at=$(ts) reason=${kind} snapshot=${snap:-none}" > "${STOP_FLAG}"
  slog "RECLAIM handled: snapshot=${snap:-FAILED}, STOP flag set. Exiting watcher."
}

slog "IMDS watcher started (poll=${POLL_SECONDS}s, project=${PROJECT}, vol=${DATA_VOLUME_ID})."
rebalance_seen=0
while true; do
  # Hard reclaim notice: 200 + JSON {action:'stop'|'terminate'|'hibernate', time}.
  if imds latest/meta-data/spot/instance-action >/dev/null 2>&1; then
    on_reclaim "instance-action"
    exit 0
  fi
  # Soft early warning: log once, keep running (gives the operator/controller
  # a head start; the real checkpoint happens on the hard notice above).
  if [ "${rebalance_seen}" -eq 0 ] \
     && imds latest/meta-data/events/recommendations/rebalance >/dev/null 2>&1; then
    rebalance_seen=1
    slog "REBALANCE recommendation received — reclaim may be near; watching for hard notice."
    echo "rebalance_at=$(ts)" > "${STATE_DIR}/REBALANCE_NOTICE"
  fi
  # The controller removes STOP_FLAG only at a fresh start; if it appeared from a
  # prior signal, exit (nothing more to do).
  [ -e "${STOP_FLAG}" ] && { slog "STOP flag already present — exiting watcher."; exit 0; }
  sleep "${POLL_SECONDS}"
done
