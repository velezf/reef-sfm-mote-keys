#!/usr/bin/env bash
#
# 04-launch-instance.sh — launch the workstation and wire it up
#
# Sequence:
#   1. Launch from the launch template (instance comes up with primary ENI in
#      the SG and a fresh MAC on the primary interface).
#   2. Wait for the instance to reach 'running' state.
#   3. Associate the Elastic IP with the primary ENI (-> stable public IP).
#   4. Attach the secondary ENI (-> stable secondary MAC for Metashape).
#   5. Attach the standalone EBS data volume.
#   6. Wait for system status checks to pass.
#
# After this script: the instance is running but software-bare. SSH in and
# run 05-first-boot-setup.sh to format/mount the data volume and set the
# hostname.
#
# Re-running this script while the instance already exists is a no-op (the
# script detects an existing tagged instance and exits cleanly).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export PROJECT_ROOT
# shellcheck source=../../config/aws-config.sh
source "${PROJECT_ROOT}/config/aws-config.sh"
# shellcheck source=./lib.sh
source "${SCRIPT_DIR}/lib.sh"

log_step "Step 4: Launching instance"

ensure_aws_cli

# Pull dependencies
template_id="$(read_resource "launch_template_id")"
subnet_id="$(read_resource "subnet_id")"
eip_alloc_id="$(read_resource "eip_allocation_id")"
secondary_eni_id="$(read_resource "secondary_eni_id")"
data_vol_id="$(read_resource "data_volume_id")"

require_var template_id "Run 03-create-launch-template.sh first."
require_var subnet_id "Run 01-create-network.sh first."
require_var eip_alloc_id "Run 01-create-network.sh first."
require_var secondary_eni_id "Run 01-create-network.sh first."
require_var data_vol_id "Run 02-create-storage.sh first."

# -----------------------------------------------------------------------------
# Check for an existing instance
# -----------------------------------------------------------------------------

existing_instance_id="$(aws ec2 describe-instances \
    --filters \
        "Name=tag:Project,Values=${PROJECT_TAG}" \
        "Name=tag:Name,Values=${INSTANCE_NAME}" \
        "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --region "$AWS_REGION" \
    --query 'Reservations[0].Instances[0].InstanceId' \
    --output text 2>/dev/null || echo "None")"

if [[ "$existing_instance_id" != "None" && -n "$existing_instance_id" ]]; then
    log_warn "Instance already exists: ${existing_instance_id}"
    log_warn "If you want a fresh launch (e.g. AMI bump), use stop-instance.sh and"
    log_warn "teardown.sh first. The 8-step stability pattern says don't terminate"
    log_warn "and recreate after Metashape activates."
    persist_resource "instance_id" "$existing_instance_id"
    log_step "Step 4 complete (no change)"
    exit 0
fi

# -----------------------------------------------------------------------------
# Launch
# -----------------------------------------------------------------------------

log_info "Launching from launch template ${template_id} into subnet ${subnet_id}"

instance_id="$(aws ec2 run-instances \
    --launch-template "LaunchTemplateId=${template_id},Version=\$Default" \
    --subnet-id "$subnet_id" \
    --region "$AWS_REGION" \
    --query 'Instances[0].InstanceId' \
    --output text)"

log_ok "Launched ${instance_id}"
persist_resource "instance_id" "$instance_id"

wait_for_state instance "$instance_id" "running"

# -----------------------------------------------------------------------------
# Associate Elastic IP
# -----------------------------------------------------------------------------

log_step "Associating Elastic IP"

aws ec2 associate-address \
    --instance-id "$instance_id" \
    --allocation-id "$eip_alloc_id" \
    --region "$AWS_REGION" \
    > /dev/null

eip_public_ip="$(read_resource "eip_public_ip")"
log_ok "EIP ${eip_public_ip} now points to ${instance_id}"

# -----------------------------------------------------------------------------
# Attach secondary ENI (DeviceIndex 1; primary is 0)
# -----------------------------------------------------------------------------

log_step "Attaching secondary ENI (license MAC)"

# Check if ENI is already attached to something else
eni_attached_to="$(aws ec2 describe-network-interfaces \
    --network-interface-ids "$secondary_eni_id" \
    --region "$AWS_REGION" \
    --query 'NetworkInterfaces[0].Attachment.InstanceId' \
    --output text 2>/dev/null || echo "None")"

if [[ "$eni_attached_to" == "$instance_id" ]]; then
    log_info "Secondary ENI already attached to this instance"
elif [[ "$eni_attached_to" != "None" && -n "$eni_attached_to" ]]; then
    log_error "Secondary ENI is attached to a different instance: ${eni_attached_to}"
    log_error "This shouldn't happen unless something went wrong earlier."
    exit 1
else
    aws ec2 attach-network-interface \
        --network-interface-id "$secondary_eni_id" \
        --instance-id "$instance_id" \
        --device-index 1 \
        --region "$AWS_REGION" \
        > /dev/null
    log_ok "Attached secondary ENI ${secondary_eni_id} as device 1"
fi

eni_mac="$(read_resource "secondary_eni_mac")"
log_info "License MAC is: ${eni_mac}"

# -----------------------------------------------------------------------------
# Attach data volume
# -----------------------------------------------------------------------------

log_step "Attaching data volume"

vol_attached_to="$(aws ec2 describe-volumes \
    --volume-ids "$data_vol_id" \
    --region "$AWS_REGION" \
    --query 'Volumes[0].Attachments[0].InstanceId' \
    --output text 2>/dev/null || echo "None")"

if [[ "$vol_attached_to" == "$instance_id" ]]; then
    log_info "Data volume already attached to this instance"
elif [[ "$vol_attached_to" != "None" && -n "$vol_attached_to" ]]; then
    log_error "Data volume is attached to a different instance: ${vol_attached_to}"
    exit 1
else
    aws ec2 attach-volume \
        --volume-id "$data_vol_id" \
        --instance-id "$instance_id" \
        --device "$DATA_VOLUME_DEVICE" \
        --region "$AWS_REGION" \
        > /dev/null
    log_ok "Attached data volume ${data_vol_id} as ${DATA_VOLUME_DEVICE}"
    log_info "On Nitro instances (g6 family is Nitro), this appears as /dev/nvme1n1"
fi

# -----------------------------------------------------------------------------
# Wait for system status checks (instance + system reachability) to pass.
# This is more useful than 'running' because it tells you when SSH will work.
# -----------------------------------------------------------------------------

log_step "Waiting for system status checks to pass"

log_info "This typically takes 1-3 minutes after launch."
aws ec2 wait instance-status-ok \
    --instance-ids "$instance_id" \
    --region "$AWS_REGION"
log_ok "Instance and system status checks: ok"

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

cat >&2 <<EOF

$(printf "${C_BOLD}${C_GREEN}Instance is up.${C_RESET}\n")

Instance ID:  ${instance_id}
Public IP:    ${eip_public_ip}
Secondary MAC: ${eni_mac}    <-- Metashape license fingerprint
Data volume:  ${data_vol_id} as ${DATA_VOLUME_DEVICE} (Nitro: /dev/nvme1n1)
SSH key:      ${KEY_PAIR_LOCAL_PATH}

Next steps:

1. Add an entry to ~/.ssh/config (see config/ssh-config.snippet):

     Host ${SSH_ALIAS}
         HostName ${eip_public_ip}
         User ${SSH_USER}
         IdentityFile ${KEY_PAIR_LOCAL_PATH}

2. Test SSH:

     ssh ${SSH_ALIAS}

   On first connect, accept the host key. If SSH hangs, double-check
   MY_IP_CIDR in config/aws-config.sh matches your current IP.

3. Run the on-instance first-boot setup:

     ./scripts/aws/05-first-boot-setup.sh

   (This copies itself to the instance over SSH and runs it there.)

EOF

log_step "Step 4 complete"
