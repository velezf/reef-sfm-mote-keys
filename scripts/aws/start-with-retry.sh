#!/usr/bin/env bash
#
# start-with-retry.sh — retry start-instances until capacity is available,
#                       then hand off to start-instance.sh for sanity checks.
#
# g6 instances in us-east-1c occasionally hit InsufficientInstanceCapacity.
# This script polls until AWS accepts the start request, then delegates the
# full license-sanity-check flow to start-instance.sh.
#
# Usage:
#   ./scripts/aws/start-with-retry.sh [interval_seconds [max_minutes]]
#
#   interval_seconds — how long to wait between attempts (default: 30)
#   max_minutes      — give up after this many minutes (default: 5)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export PROJECT_ROOT

# shellcheck source=../../config/aws-config.sh
source "${PROJECT_ROOT}/config/aws-config.sh"
# shellcheck source=./lib.sh
source "${SCRIPT_DIR}/lib.sh"

INTERVAL="${1:-30}"
MAX_MINUTES="${2:-5}"
DEADLINE=$(( $(date +%s) + MAX_MINUTES * 60 ))

ensure_aws_cli

instance_id="$(read_resource "instance_id")"
require_var instance_id

# ── Pre-flight: is it already going? ─────────────────────────────────────────
current_state="$(aws ec2 describe-instances \
    --instance-ids "$instance_id" \
    --region "$AWS_REGION" \
    --query 'Reservations[0].Instances[0].State.Name' \
    --output text)"

case "$current_state" in
    running|pending)
        log_info "Instance is already ${current_state} — delegating to start-instance.sh."
        exec "${SCRIPT_DIR}/start-instance.sh"
        ;;
    stopped|stopping)
        ;;  # normal; proceed to retry loop below
    *)
        log_error "Cannot start from state: ${current_state}"
        exit 1
        ;;
esac

if [[ "$current_state" == "stopping" ]]; then
    log_info "Instance is still stopping — waiting for it to reach 'stopped' first..."
    wait_for_state instance "$instance_id" "stopped"
fi

# ── Retry loop ────────────────────────────────────────────────────────────────
log_step "Capacity retry loop — ${INSTANCE_TYPE} in ${AVAILABILITY_ZONE}"
log_info "Polling every ${INTERVAL}s, giving up after ${MAX_MINUTES}m. Press Ctrl-C to abort."
log_info ""

attempt=0
tmpfile="$(mktemp)"
trap 'rm -f "$tmpfile"' EXIT

while true; do
    attempt=$((attempt + 1))
    log_info "Attempt ${attempt} — $(date '+%H:%M:%S')"

    if aws ec2 start-instances \
           --instance-ids "$instance_id" \
           --region "$AWS_REGION" \
           > /dev/null 2>"$tmpfile"
    then
        log_ok "AWS accepted the start request — handing off to start-instance.sh"
        rm -f "$tmpfile"
        exec "${SCRIPT_DIR}/start-instance.sh"
    fi

    err_output="$(cat "$tmpfile")"

    if echo "$err_output" | grep -q "InsufficientInstanceCapacity"; then
        if (( $(date +%s) + INTERVAL > DEADLINE )); then
            log_error "No capacity after ${MAX_MINUTES}m — giving up. Try again later or check other AZs."
            exit 1
        fi
        log_warn "No capacity yet. Retrying in ${INTERVAL}s..."
    elif echo "$err_output" | grep -q "IncorrectInstanceState"; then
        # A previous attempt may have already triggered a start; hand off.
        log_info "Instance already transitioning — delegating to start-instance.sh."
        rm -f "$tmpfile"
        exec "${SCRIPT_DIR}/start-instance.sh"
    else
        log_error "Unexpected AWS error — aborting retry loop:"
        log_error "$err_output"
        exit 1
    fi

    sleep "$INTERVAL"
done
