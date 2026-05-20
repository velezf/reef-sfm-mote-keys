#!/usr/bin/env bash
#
# start-instance.sh — resume a stopped instance for a new work session
#
# Starts the instance and then sanity-checks the things that matter for
# Metashape's license fingerprint:
#   - Secondary ENI still attached (same eni-id, same MAC)
#   - Data volume still attached
#   - Elastic IP still associated
#
# If any of those are wrong, we bail loudly rather than letting Metashape
# discover the problem and possibly invalidate the license.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export PROJECT_ROOT
# shellcheck source=../../config/aws-config.sh
source "${PROJECT_ROOT}/config/aws-config.sh"
# shellcheck source=./lib.sh
source "${SCRIPT_DIR}/lib.sh"

log_step "Starting instance"

ensure_aws_cli

instance_id="$(read_resource "instance_id")"
secondary_eni_id="$(read_resource "secondary_eni_id")"
expected_mac="$(read_resource "secondary_eni_mac")"
data_vol_id="$(read_resource "data_volume_id")"
eip_alloc_id="$(read_resource "eip_allocation_id")"

require_var instance_id
require_var secondary_eni_id
require_var expected_mac
require_var data_vol_id
require_var eip_alloc_id

current_state="$(aws ec2 describe-instances \
    --instance-ids "$instance_id" \
    --region "$AWS_REGION" \
    --query 'Reservations[0].Instances[0].State.Name' \
    --output text)"

case "$current_state" in
    running)
        log_info "Instance ${instance_id} is already running."
        ;;
    stopped)
        log_info "Starting ${instance_id}..."
        aws ec2 start-instances --instance-ids "$instance_id" --region "$AWS_REGION" > /dev/null
        wait_for_state instance "$instance_id" "running"
        ;;
    pending)
        wait_for_state instance "$instance_id" "running"
        ;;
    stopping)
        log_info "Instance is stopping. Waiting for it to fully stop, then starting..."
        wait_for_state instance "$instance_id" "stopped"
        aws ec2 start-instances --instance-ids "$instance_id" --region "$AWS_REGION" > /dev/null
        wait_for_state instance "$instance_id" "running"
        ;;
    *)
        log_error "Cannot start from state: ${current_state}"
        exit 1
        ;;
esac

# -----------------------------------------------------------------------------
# License-critical sanity checks
# -----------------------------------------------------------------------------

log_step "Sanity-checking license-critical attachments"

# Secondary ENI
attached_eni_id="$(aws ec2 describe-instances \
    --instance-ids "$instance_id" \
    --region "$AWS_REGION" \
    --query 'Reservations[0].Instances[0].NetworkInterfaces[?Attachment.DeviceIndex==`1`].NetworkInterfaceId' \
    --output text 2>/dev/null || echo "")"

if [[ "$attached_eni_id" != "$secondary_eni_id" ]]; then
    log_error "Secondary ENI mismatch."
    log_error "  Expected (license-bound): ${secondary_eni_id}"
    log_error "  Currently attached at device 1: ${attached_eni_id:-NONE}"
    log_error "Re-attaching the correct ENI..."
    if [[ -n "$attached_eni_id" && "$attached_eni_id" != "None" ]]; then
        log_error "Refusing to auto-fix. Investigate manually."
        exit 1
    fi
    aws ec2 attach-network-interface \
        --network-interface-id "$secondary_eni_id" \
        --instance-id "$instance_id" \
        --device-index 1 \
        --region "$AWS_REGION" \
        > /dev/null
    log_ok "Re-attached license ENI ${secondary_eni_id}"
else
    log_ok "Secondary ENI: ${secondary_eni_id} attached at device-index 1"
fi

# MAC of the secondary ENI must be unchanged
actual_mac="$(aws ec2 describe-network-interfaces \
    --network-interface-ids "$secondary_eni_id" \
    --region "$AWS_REGION" \
    --query 'NetworkInterfaces[0].MacAddress' \
    --output text)"

if [[ "$actual_mac" != "$expected_mac" ]]; then
    log_error "Secondary ENI MAC has changed!"
    log_error "  Expected (in license): ${expected_mac}"
    log_error "  Actual now:            ${actual_mac}"
    log_error "Metashape license will likely fail. Contact Agisoft support before reactivating."
    exit 1
else
    log_ok "Secondary MAC unchanged: ${actual_mac}"
fi

# Data volume
attached_vol="$(aws ec2 describe-volumes \
    --volume-ids "$data_vol_id" \
    --region "$AWS_REGION" \
    --query 'Volumes[0].Attachments[0].InstanceId' \
    --output text 2>/dev/null || echo "None")"

if [[ "$attached_vol" != "$instance_id" ]]; then
    log_warn "Data volume not attached to this instance. Re-attaching..."
    aws ec2 attach-volume \
        --volume-id "$data_vol_id" \
        --instance-id "$instance_id" \
        --device "$DATA_VOLUME_DEVICE" \
        --region "$AWS_REGION" \
        > /dev/null
    log_ok "Data volume re-attached."
else
    log_ok "Data volume attached"
fi

# Elastic IP
eip_associated_with="$(aws ec2 describe-addresses \
    --allocation-ids "$eip_alloc_id" \
    --region "$AWS_REGION" \
    --query 'Addresses[0].InstanceId' \
    --output text 2>/dev/null || echo "None")"

if [[ "$eip_associated_with" != "$instance_id" ]]; then
    log_warn "EIP not associated with this instance. Reassociating..."
    aws ec2 associate-address \
        --instance-id "$instance_id" \
        --allocation-id "$eip_alloc_id" \
        --region "$AWS_REGION" \
        > /dev/null
    log_ok "EIP reassociated."
else
    log_ok "EIP associated"
fi

eip_public_ip="$(read_resource "eip_public_ip")"

log_step "Instance ready"
log_info ""
log_info "Connect: ssh ${SSH_ALIAS}    (or: ssh -i ${KEY_PAIR_LOCAL_PATH} ${SSH_USER}@${eip_public_ip})"
log_info ""
log_info "Reminder: this instance is now BILLING for compute (~\$1.32/hour)."
log_info "Stop it at end of session: ./scripts/aws/stop-instance.sh"
