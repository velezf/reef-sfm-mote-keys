#!/usr/bin/env bash
# lib_spot.sh — shared helpers for the spot-instance orchestration layer
# (Part B, built 2026-06-05 during the T1 align window).
#
# SCOPE: this is an ORCHESTRATION layer AROUND run_pipeline.py's existing
# `--stage` entrypoint. It changes NO methodology (ESM Table S2 params live in
# run_pipeline.py and are untouched). It exists to make the long stages survive
# a spot reclaim and to keep an HONEST record of what is actually on disk —
# the same lesson as the 2026-06-04 incident: never claim done unless the
# artifact persisted.
#
# Source this; do not execute it directly. Callers: spot_imds_watch.sh,
# spot_controller.sh.
#
# All resource IDs default to the values recorded in docs/aws-resources.md
# (gitignored) and are OVERRIDABLE via environment so a fresh spot instance can
# point at the same persistent EBS data volume (the volume-id is stable across
# instances; the instance-id is not — so we discover the instance-id at runtime
# and keep the volume-id as a config default).

# ----------------------------------------------------------------------------- #
# Config (env-overridable)
# ----------------------------------------------------------------------------- #
: "${PROJECT:=/data/edr_work/edr_t1.psx}"
: "${DATA_MOUNT:=/data}"
: "${DATA_VOLUME_ID:=vol-08bcf0ab11df2c9ed}"   # persistent EBS data vol (stable)
: "${AWS_REGION_DEFAULT:=us-east-1}"
: "${EXPECTED_LICENSE_MAC:=0a:ff:fc:67:89:8f}" # secondary-ENI license anchor
: "${METASHAPE_SH:=/opt/metashape-pro/metashape.sh}"
: "${RUN_PIPELINE:=/data/reef-sfm-mote-keys/scripts/metashape/run_pipeline.py}"
: "${STATE_DIR:=/data/edr_work/state}"
: "${MIN_FREE_GB:=60}"                          # fail-fast disk floor
: "${IMDS_BASE:=http://169.254.169.254}"

STATE_FILE="${STATE_DIR}/spot_pipeline_state.json"
STOP_FLAG="${STATE_DIR}/RECLAIM_STOP"           # watcher writes -> controller halts
RESUME_MARKER="${STATE_DIR}/RESUME_FROM"        # last verified-done stage on reclaim

ts(){ date -u +%Y-%m-%dT%H:%M:%SZ; }
slog(){ echo "[$(ts)] [${LOG_TAG:-spot}] $*"; }

# ----------------------------------------------------------------------------- #
# IMDSv2 (token-required) helpers
# ----------------------------------------------------------------------------- #
_imds_token(){
  curl -sf -X PUT "${IMDS_BASE}/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null
}

# imds <path>  -> echoes body, rc!=0 if not 200. Always sends a fresh token.
imds(){
  local tok path="$1"
  tok="$(_imds_token)" || return 1
  curl -sf -H "X-aws-ec2-metadata-token: ${tok}" "${IMDS_BASE}/${path#/}" 2>/dev/null
}

imds_instance_id(){ imds latest/meta-data/instance-id; }
imds_region(){ imds latest/meta-data/placement/region; }

# ----------------------------------------------------------------------------- #
# Fail-fast preconditions — assert the world is sane BEFORE any compute.
# Each prints a clear reason and returns non-zero on failure. precheck_all
# aggregates; callers abort the run on its non-zero rc.
# ----------------------------------------------------------------------------- #
check_data_mount(){
  if ! mountpoint -q "${DATA_MOUNT}"; then
    slog "PRECHECK FAIL: ${DATA_MOUNT} is not a mountpoint (data volume not attached?)."
    return 1
  fi
  slog "PRECHECK ok: ${DATA_MOUNT} mounted."
}

check_project_present(){
  if [ ! -f "${PROJECT}" ]; then
    slog "PRECHECK FAIL: project ${PROJECT} missing."
    return 1
  fi
  slog "PRECHECK ok: project ${PROJECT} present."
}

check_disk_free(){
  local free_gb
  free_gb="$(df -BG --output=avail "${DATA_MOUNT}" 2>/dev/null | tail -1 | tr -dc '0-9')"
  if [ -z "${free_gb}" ] || [ "${free_gb}" -lt "${MIN_FREE_GB}" ]; then
    slog "PRECHECK FAIL: only ${free_gb:-?} GB free on ${DATA_MOUNT} (< ${MIN_FREE_GB} GB floor)."
    return 1
  fi
  slog "PRECHECK ok: ${free_gb} GB free on ${DATA_MOUNT}."
}

check_license_mac(){
  # The node-locked license is bound to the secondary-ENI MAC. If AWS rotated
  # the MAC (host change / restore-from-snapshot), activation breaks — fail
  # fast here rather than burn an hour and lose it at save.
  if ip -o link 2>/dev/null | grep -qi "${EXPECTED_LICENSE_MAC}"; then
    slog "PRECHECK ok: license-anchor MAC ${EXPECTED_LICENSE_MAC} present."
  else
    slog "PRECHECK FAIL: expected license MAC ${EXPECTED_LICENSE_MAC} NOT on any interface "
    slog "             (MAC drift -> Metashape activation will break). Re-host before running."
    return 1
  fi
}

check_license_active(){
  # Live probe via the Metashape Python API. Takes NO project lock (safe to run
  # while a stage is active). Confirms activated AND valid. Uses a temp script
  # file (more portable than `-r /dev/stdin`).
  local probe out
  probe="$(mktemp /tmp/ms_lic_probe.XXXXXX.py)"
  printf 'import Metashape\nprint("ACT", Metashape.app.activated, Metashape.License().valid)\n' > "${probe}"
  out="$(timeout 120 "${METASHAPE_SH}" -platform offscreen -r "${probe}" 2>/dev/null | grep '^ACT ')"
  rm -f "${probe}"
  if echo "${out}" | grep -q 'ACT True True'; then
    slog "PRECHECK ok: Metashape activated + license valid."
  else
    slog "PRECHECK FAIL: Metashape not activated/valid (got: '${out:-<none>}')."
    return 1
  fi
}

check_no_foreign_lock(){
  # A stale lock would otherwise make Metashape silently open read-only. The
  # pipeline's own open_or_create handles the clean-or-abort decision (it scans
  # /proc for a live holder); here we just refuse to start if a lock exists AND
  # a live Metashape holder is running that ISN'T our own controller-launched run.
  local lock="${PROJECT%.psx}.files/lock"
  if [ -e "${lock}" ]; then
    if pgrep -af 'metashape.*-platform offscreen' >/dev/null 2>&1; then
      slog "PRECHECK FAIL: ${lock} present AND a live Metashape process exists — "
      slog "             another run holds the project. Refusing to start."
      return 1
    fi
    slog "PRECHECK note: stale lock ${lock} present, no live holder — "
    slog "             open_or_create will clean-with-log on open."
  else
    slog "PRECHECK ok: no project lock present."
  fi
}

check_gpu(){
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
    slog "PRECHECK ok: GPU present ($(nvidia-smi -L | head -1))."
  else
    # Non-fatal: Metashape will run CPU-only, just slowly. Warn, don't block.
    slog "PRECHECK warn: no GPU detected (nvidia-smi) — stages will run CPU-only."
  fi
}

precheck_all(){
  local rc=0
  check_data_mount      || rc=1
  check_project_present || rc=1
  check_disk_free       || rc=1
  check_license_mac     || rc=1
  check_no_foreign_lock || rc=1
  check_gpu             || true              # advisory only
  if [ "${SKIP_LICENSE_PROBE:-0}" != "1" ]; then
    check_license_active || rc=1
  fi
  if [ "${rc}" -ne 0 ]; then
    slog "PRECHECK: one or more fail-fast checks FAILED — not starting."
  else
    slog "PRECHECK: all fail-fast checks passed."
  fi
  return "${rc}"
}

# ----------------------------------------------------------------------------- #
# Data-volume discovery + EBS snapshot (the spot recovery point)
# ----------------------------------------------------------------------------- #
resolve_region(){
  local r; r="$(imds_region)"; echo "${r:-${AWS_REGION_DEFAULT}}"
}

# snapshot_data_volume <reason>  -> echoes the new snapshot id (or empty on failure)
snapshot_data_volume(){
  local reason="${1:-checkpoint}" region iid snap
  region="$(resolve_region)"
  iid="$(imds_instance_id || echo unknown)"
  if ! command -v aws >/dev/null 2>&1; then
    slog "SNAPSHOT skip: aws CLI not available."
    return 1
  fi
  slog "SNAPSHOT: creating snapshot of ${DATA_VOLUME_ID} in ${region} (reason=${reason})..."
  snap="$(aws ec2 create-snapshot --region "${region}" \
            --volume-id "${DATA_VOLUME_ID}" \
            --description "reef-sfm spot ${reason} from ${iid} $(ts)" \
            --tag-specifications \
              "ResourceType=snapshot,Tags=[{Key=Project,Value=reef-sfm-mote-keys},{Key=reason,Value=${reason}},{Key=src-instance,Value=${iid}}]" \
            --query 'SnapshotId' --output text 2>/dev/null)"
  if [ -n "${snap}" ] && [ "${snap}" != "None" ]; then
    slog "SNAPSHOT: created ${snap} (async; completes in background)."
    echo "${snap}"
  else
    slog "SNAPSHOT FAIL: create-snapshot returned no id (check IAM / region)."
    return 1
  fi
}
