#!/usr/bin/env bash
# spot_controller.sh — auto-resume controller around run_pipeline.py --stage.
#
# Part B (spot orchestration), built 2026-06-05. Run DETACHED (tmux/setsid).
#
# WHAT IT DOES
#   1. Fail-fast preconditions (lib_spot.sh precheck_all) — abort before compute
#      if the world isn't sane (no data mount / license MAC drift / no disk /
#      foreign lock).
#   2. Launch the IMDS reclaim watcher in the background.
#   3. Reconcile HONEST state from the project on disk (pipeline_state.py) and
#      refuse to advance if any stage is `inconsistent` (meta-without-artifact —
#      the 2026-06-04 lie class).
#   4. Run the remaining stages one at a time via `run_pipeline.py --stage <s>`,
#      starting from the reconciler's next_stage. Each stage opens -> runs ->
#      verified-saves -> exits, so a reclaim costs at most the in-flight stage.
#   5. After each stage: re-reconcile and confirm the stage is now `done` ON
#      DISK. rc==0 is NEVER sufficient on its own — only on-disk verification
#      marks a stage verified-done (the honest sentinel rule).
#   6. Between stages, honor the watcher's RECLAIM_STOP flag: the snapshot +
#      resume marker are already written, so exit cleanly for replacement.
#
# GUARDRAIL (matches the project rule "dense only on explicit go"): the
# controller STOPS when it reaches `dense` UNLESS --allow-dense is passed. It
# will never silently start the dense.
#
# IDEMPOTENT RESUME: re-launching on a replacement instance re-runs this script;
# completed stages self-skip inside run_pipeline, and the reconciler resumes from
# the first not-done stage. Same script + same volume => resume for free.

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_spot.sh
source "${HERE}/lib_spot.sh"
LOG_TAG="spot-ctl"

ALLOW_DENSE=0
STOP_BEFORE=""              # optional: halt cleanly before this stage
EXTRA_PIPELINE_ARGS="${EXTRA_PIPELINE_ARGS:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --allow-dense) ALLOW_DENSE=1 ;;
    --stop-before) STOP_BEFORE="$2"; shift ;;
    --project)     PROJECT="$2"; shift ;;
    *) slog "unknown arg: $1"; exit 64 ;;
  esac
  shift
done

PIPELINE_STAGES=(import step4 align markers scale reduce level dense filter aoi dsm ortho gate report)
EVENT_LOG="${STATE_DIR}/controller_events.jsonl"
mkdir -p "${STATE_DIR}"

event(){  # event <stage> <event> <rc>
  printf '{"ts":"%s","stage":"%s","event":"%s","rc":%s}\n' \
    "$(ts)" "$1" "$2" "${3:-null}" >> "${EVENT_LOG}"
}

reconcile(){  # writes authoritative STATE_FILE; echoes next_stage; rc 2 => inconsistent
  local rc
  "${METASHAPE_SH}" -platform offscreen -r "${HERE}/pipeline_state.py" \
    --project "${PROJECT}" --write "${STATE_FILE}" >/dev/null 2>&1
  rc=$?
  sed -n 's/.*"next_stage": *"\([^"]*\)".*/\1/p' "${STATE_FILE}" 2>/dev/null | head -1
  return "${rc}"
}

# ---- 0. fresh start: clear a stale STOP flag from a prior run ----------------
if [ -e "${STOP_FLAG}" ]; then
  slog "Clearing stale RECLAIM_STOP from a previous run."
  rm -f "${STOP_FLAG}" "${STATE_DIR}/RECLAIM_NOTICE" "${STATE_DIR}/REBALANCE_NOTICE"
fi

# ---- 1. fail-fast preconditions ---------------------------------------------
slog "=== spot controller start (project=${PROJECT}, allow_dense=${ALLOW_DENSE}) ==="
if ! precheck_all; then
  slog "ABORT: preconditions failed."; event "-" "precheck_failed" 1; exit 1
fi

# ---- 2. launch the reclaim watcher ------------------------------------------
setsid bash "${HERE}/spot_imds_watch.sh" >> "${STATE_DIR}/imds_watch.log" 2>&1 &
WATCH_PID=$!
slog "IMDS watcher launched (pid ${WATCH_PID}, log ${STATE_DIR}/imds_watch.log)."
# Reap the watcher on any controller exit UNLESS it stopped us for a reclaim
# (in that case it has its own checkpoint work to finish / has already exited).
cleanup_watch(){ [ -e "${STOP_FLAG}" ] || kill "${WATCH_PID}" 2>/dev/null || true; }
trap cleanup_watch EXIT

# ---- 3. honest reconcile + refuse to advance past a lie ---------------------
next_stage="$(reconcile)"; rc=$?
if [ "${rc}" -eq 2 ]; then
  slog "ABORT: project has an INCONSISTENT stage (meta present, artifact missing)."
  slog "       Inspect ${STATE_FILE} — do NOT advance past unverified state."
  event "-" "inconsistent_state" 2; exit 3
fi
slog "Reconciled. Next stage to run: ${next_stage:-<none — pipeline complete>}"
[ -z "${next_stage}" ] && { slog "Pipeline already complete on disk. Nothing to do."; exit 0; }

# ---- 4-6. run remaining stages from next_stage ------------------------------
started=0
for st in "${PIPELINE_STAGES[@]}"; do
  [ "${st}" = "${next_stage}" ] && started=1
  [ "${started}" -eq 0 ] && continue

  # reclaim between stages? checkpoint already taken by the watcher -> exit clean
  if [ -e "${STOP_FLAG}" ]; then
    slog "RECLAIM_STOP present before stage '${st}'. Checkpoint already snapshotted; "
    slog "resume on a replacement instance with the same volume. See ${RESUME_MARKER}."
    event "${st}" "reclaim_halt" null; exit 0
  fi
  # explicit stop-before
  if [ -n "${STOP_BEFORE}" ] && [ "${st}" = "${STOP_BEFORE}" ]; then
    slog "Reached --stop-before='${st}'. Halting cleanly."; event "${st}" "stop_before" null; exit 0
  fi
  # DENSE GUARDRAIL — never auto-start without explicit go
  if [ "${st}" = "dense" ] && [ "${ALLOW_DENSE}" -ne 1 ]; then
    slog "Reached 'dense'. GUARDRAIL: dense requires --allow-dense (explicit go). Halting."
    slog "Align+markers (and any pre-dense stages) are done + verified on disk."
    event "dense" "dense_guardrail_halt" null; exit 0
  fi

  slog "--- STAGE ${st}: launching run_pipeline ---"
  event "${st}" "start" null
  # shellcheck disable=SC2086 -- EXTRA_PIPELINE_ARGS is an intentional word split
  "${METASHAPE_SH}" -platform offscreen -r "${RUN_PIPELINE}" \
    --project "${PROJECT}" --stage "${st}" ${EXTRA_PIPELINE_ARGS}
  rc=$?
  event "${st}" "exit" "${rc}"
  if [ "${rc}" -ne 0 ]; then
    slog "STAGE ${st} FAILED (rc=${rc}). Stopping — not advancing on a failed stage."
    exit "${rc}"
  fi

  # HONEST verification: rc==0 is not enough. Re-reconcile and confirm THIS stage
  # is now done on disk; a meta-without-artifact result is the lie class -> stop.
  vnext="$(reconcile)"; vrc=$?
  if [ "${vrc}" -eq 2 ]; then
    slog "STAGE ${st}: rc==0 but reconcile found INCONSISTENT state — refusing to continue."
    event "${st}" "verify_inconsistent" 2; exit 3
  fi
  if [ "${vnext}" = "${st}" ]; then
    slog "STAGE ${st}: rc==0 but reconciler still reports it as next_stage (artifact NOT persisted). STOP."
    event "${st}" "verify_not_persisted" 2; exit 3
  fi
  slog "STAGE ${st}: done + verified on disk (next: ${vnext:-<complete>})."
  event "${st}" "verified_done" 0
done

slog "=== controller finished: all requested stages done + verified. ==="
