#!/usr/bin/env bash
#
# stop-instance.sh — stop the instance between work sessions
#
# Stopping (not terminating):
#   - Cost goes from ~$1.32/hr (g6.4xlarge running) to ~$0/hr compute.
#   - EBS storage continues to bill: ~$0.08/GB-month for gp3 = roughly
#     $80/month for the 1 TB data volume + ~$16/month for the 200 GB boot
#     volume = ~$96/month while stopped.
#   - Elastic IP: AWS no longer charges for EIPs associated with stopped
#     instances as of mid-2024 (verify on your current bill anyway).
#     Historically there was a small charge for unassociated EIPs.
#   - Instance state, ENI attachments, and volume attachments are preserved.
#   - The primary ENI keeps its MAC.
#   - The secondary ENI stays attached and keeps ITS MAC — which is what
#     Metashape's license binds to.
#
# After running this, run start-instance.sh to resume. Public IP doesn't
# change because the Elastic IP is sticky.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export PROJECT_ROOT
# shellcheck source=../../config/aws-config.sh
source "${PROJECT_ROOT}/config/aws-config.sh"
# shellcheck source=./lib.sh
source "${SCRIPT_DIR}/lib.sh"

log_step "Stopping instance"

ensure_aws_cli

instance_id="$(read_resource "instance_id")"
require_var instance_id "No instance recorded. Has 04-launch-instance.sh run?"

current_state="$(aws ec2 describe-instances \
    --instance-ids "$instance_id" \
    --region "$AWS_REGION" \
    --query 'Reservations[0].Instances[0].State.Name' \
    --output text)"

case "$current_state" in
    stopped)
        log_info "Instance ${instance_id} is already stopped."
        exit 0
        ;;
    stopping)
        log_info "Instance ${instance_id} is stopping."
        wait_for_state instance "$instance_id" "stopped"
        exit 0
        ;;
    pending)
        log_warn "Instance is still starting up. Waiting for 'running' before stopping..."
        wait_for_state instance "$instance_id" "running"
        ;;
    running)
        ;;
    *)
        log_error "Unexpected instance state: ${current_state}"
        exit 1
        ;;
esac

log_info "Stopping ${instance_id}..."
aws ec2 stop-instances --instance-ids "$instance_id" --region "$AWS_REGION" > /dev/null
wait_for_state instance "$instance_id" "stopped"

log_ok "Instance stopped. Compute charges paused."
log_info "Storage billing continues for boot+data EBS volumes."
log_info "Resume with: ./scripts/aws/start-instance.sh"
