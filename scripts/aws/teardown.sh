#!/usr/bin/env bash
#
# teardown.sh — end-of-project cleanup
#
# What this script DOES delete (compute and one-off network resources):
#   - The EC2 instance (terminate)
#   - The boot volume (deleted by DeleteOnTermination=true in the launch template)
#   - The Elastic IP (released)
#   - The secondary ENI (only AFTER instance terminates — without it the ENI
#     can't be deleted)
#   - The launch template
#   - The security group
#   - The key pair (in AWS only; the local .pem file is preserved so you can
#     verify old snapshots if needed)
#
# What this script DOES NOT delete (preserved for portfolio reproducibility):
#   - Snapshots (boot + data, any tagged with Project=reef-sfm-mote-keys)
#   - The standalone data volume (you may want a final snapshot of it first)
#
# Reasoning: snapshots are cheap (~$0.05/GB-month) and they're the immutable
# record of "the project as it ran." Keeping them costs maybe a few dollars
# a month. Recreating a complete instance from them later is a one-script
# operation if v2 happens.
#
# This script is INTERACTIVE — it prompts before each destructive action.
# Run with --yes to skip prompts (NOT recommended for first run).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export PROJECT_ROOT
# shellcheck source=../../config/aws-config.sh
source "${PROJECT_ROOT}/config/aws-config.sh"
# shellcheck source=./lib.sh
source "${SCRIPT_DIR}/lib.sh"

AUTO_YES=false
for arg in "$@"; do
    case "$arg" in
        --yes|-y) AUTO_YES=true ;;
        *) log_error "Unknown argument: $arg"; exit 1 ;;
    esac
done

confirm() {
    local prompt="$1"
    if [[ "$AUTO_YES" == "true" ]]; then
        log_info "[auto-yes] ${prompt}"
        return 0
    fi
    read -r -p "${prompt} [y/N] " response
    [[ "$response" =~ ^[Yy]$ ]]
}

log_step "Teardown: end-of-project cleanup"
log_warn "This is destructive. Read each prompt carefully."

ensure_aws_cli

# -----------------------------------------------------------------------------
# Pre-teardown: offer to snapshot the data volume one more time
# -----------------------------------------------------------------------------

data_vol_id="$(read_resource "data_volume_id")"
if [[ -n "$data_vol_id" ]]; then
    log_step "Final data volume snapshot"
    if confirm "Create a final snapshot of the data volume ${data_vol_id} before teardown?"; then
        snap_id="$(aws ec2 create-snapshot \
            --volume-id "$data_vol_id" \
            --description "Final pre-teardown snapshot of project data volume" \
            --tag-specifications "ResourceType=snapshot,Tags=[
                {Key=Project,Value=${PROJECT_TAG}},
                {Key=Name,Value=${PROJECT_TAG}-final-data},
                {Key=Stage,Value=final-pre-teardown}
            ]" \
            --region "$AWS_REGION" \
            --query 'SnapshotId' \
            --output text)"
        persist_resource "final_data_snapshot_id" "$snap_id"
        log_ok "Final snapshot started: ${snap_id} (completes asynchronously)"
    fi
fi

# -----------------------------------------------------------------------------
# Terminate instance
# -----------------------------------------------------------------------------

instance_id="$(read_resource "instance_id")"
if [[ -n "$instance_id" ]]; then
    state="$(aws ec2 describe-instances \
        --instance-ids "$instance_id" \
        --region "$AWS_REGION" \
        --query 'Reservations[0].Instances[0].State.Name' \
        --output text 2>/dev/null || echo "not-found")"

    if [[ "$state" == "not-found" || "$state" == "terminated" ]]; then
        log_info "Instance ${instance_id} already gone."
    else
        if confirm "Terminate instance ${instance_id} (state: ${state})?"; then
            aws ec2 terminate-instances --instance-ids "$instance_id" --region "$AWS_REGION" > /dev/null
            log_info "Waiting for termination..."
            aws ec2 wait instance-terminated --instance-ids "$instance_id" --region "$AWS_REGION"
            log_ok "Instance terminated. Boot volume auto-deleted."
        else
            log_warn "Skipped instance termination. The rest of teardown will fail or be skipped."
            log_warn "Re-run when ready."
            exit 0
        fi
    fi
fi

# -----------------------------------------------------------------------------
# Delete secondary ENI (now that instance is gone)
# -----------------------------------------------------------------------------

secondary_eni_id="$(read_resource "secondary_eni_id")"
if [[ -n "$secondary_eni_id" ]]; then
    eni_exists="$(aws ec2 describe-network-interfaces \
        --network-interface-ids "$secondary_eni_id" \
        --region "$AWS_REGION" \
        --query 'NetworkInterfaces[0].NetworkInterfaceId' \
        --output text 2>/dev/null || echo "None")"

    if [[ "$eni_exists" == "$secondary_eni_id" ]]; then
        log_warn "About to delete the secondary ENI ${secondary_eni_id}."
        log_warn "MAC: $(read_resource secondary_eni_mac)"
        log_warn "Once deleted, this MAC is GONE. Any Metashape license bound to it"
        log_warn "is dead. Only proceed if you've already deactivated the license"
        log_warn "(Metashape menu -> Help -> Deactivate Software)."
        if confirm "Delete secondary ENI ${secondary_eni_id}?"; then
            aws ec2 delete-network-interface \
                --network-interface-id "$secondary_eni_id" \
                --region "$AWS_REGION"
            log_ok "Secondary ENI deleted."
        else
            log_warn "Skipped ENI deletion. Re-run teardown later to clean up."
        fi
    fi
fi

# -----------------------------------------------------------------------------
# Release Elastic IP
# -----------------------------------------------------------------------------

eip_alloc_id="$(read_resource "eip_allocation_id")"
if [[ -n "$eip_alloc_id" ]]; then
    eip_exists="$(aws ec2 describe-addresses \
        --allocation-ids "$eip_alloc_id" \
        --region "$AWS_REGION" \
        --query 'Addresses[0].AllocationId' \
        --output text 2>/dev/null || echo "None")"

    if [[ "$eip_exists" == "$eip_alloc_id" ]]; then
        if confirm "Release Elastic IP $(read_resource eip_public_ip) (allocation ${eip_alloc_id})?"; then
            aws ec2 release-address --allocation-id "$eip_alloc_id" --region "$AWS_REGION"
            log_ok "EIP released."
        fi
    fi
fi

# -----------------------------------------------------------------------------
# Delete launch template
# -----------------------------------------------------------------------------

template_id="$(read_resource "launch_template_id")"
if [[ -n "$template_id" ]]; then
    template_exists="$(aws ec2 describe-launch-templates \
        --launch-template-ids "$template_id" \
        --region "$AWS_REGION" \
        --query 'LaunchTemplates[0].LaunchTemplateId' \
        --output text 2>/dev/null || echo "None")"

    if [[ "$template_exists" == "$template_id" ]]; then
        if confirm "Delete launch template ${template_id}?"; then
            aws ec2 delete-launch-template --launch-template-id "$template_id" --region "$AWS_REGION" > /dev/null
            log_ok "Launch template deleted."
        fi
    fi
fi

# -----------------------------------------------------------------------------
# Delete security group
# -----------------------------------------------------------------------------

sg_id="$(read_resource "security_group_id")"
if [[ -n "$sg_id" ]]; then
    sg_exists="$(aws ec2 describe-security-groups \
        --group-ids "$sg_id" \
        --region "$AWS_REGION" \
        --query 'SecurityGroups[0].GroupId' \
        --output text 2>/dev/null || echo "None")"

    if [[ "$sg_exists" == "$sg_id" ]]; then
        if confirm "Delete security group ${sg_id}?"; then
            # The SG can only be deleted after the instance is fully terminated
            # AND the ENI is deleted. Both should be done by now.
            if ! aws ec2 delete-security-group --group-id "$sg_id" --region "$AWS_REGION" 2>&1; then
                log_warn "SG deletion failed (probably still has dependencies)."
                log_warn "Wait a few minutes for instance termination to fully release the SG, then re-run."
            else
                log_ok "Security group deleted."
            fi
        fi
    fi
fi

# -----------------------------------------------------------------------------
# Delete key pair (AWS side only; local .pem stays)
# -----------------------------------------------------------------------------

if [[ -n "${KEY_PAIR_NAME:-}" ]]; then
    key_exists="$(aws ec2 describe-key-pairs \
        --key-names "$KEY_PAIR_NAME" \
        --region "$AWS_REGION" \
        --query 'KeyPairs[0].KeyName' \
        --output text 2>/dev/null || echo "None")"

    if [[ "$key_exists" == "$KEY_PAIR_NAME" ]]; then
        if confirm "Delete key pair ${KEY_PAIR_NAME} from AWS? (Local file at ${KEY_PAIR_LOCAL_PATH} preserved.)"; then
            aws ec2 delete-key-pair --key-name "$KEY_PAIR_NAME" --region "$AWS_REGION"
            log_ok "AWS-side key pair deleted. Local file kept."
        fi
    fi
fi

# -----------------------------------------------------------------------------
# Data volume: handle last because it's the most precious
# -----------------------------------------------------------------------------

if [[ -n "$data_vol_id" ]]; then
    vol_exists="$(aws ec2 describe-volumes \
        --volume-ids "$data_vol_id" \
        --region "$AWS_REGION" \
        --query 'Volumes[0].VolumeId' \
        --output text 2>/dev/null || echo "None")"

    if [[ "$vol_exists" == "$data_vol_id" ]]; then
        log_warn "The standalone data volume ${data_vol_id} still exists."
        log_warn "It is no longer attached to anything but continues to bill at"
        log_warn "~\$0.08/GB-month = ~\$$(( DATA_VOLUME_SIZE_GB * 8 / 100 ))/month."
        log_warn "RECOMMENDATION: keep it for now if v2 is likely soon."
        if confirm "Delete the data volume (cannot be undone, but snapshots remain)?"; then
            aws ec2 delete-volume --volume-id "$data_vol_id" --region "$AWS_REGION"
            log_ok "Data volume deleted. Snapshots are preserved."
        else
            log_info "Data volume kept. Delete it manually later with:"
            log_info "  aws ec2 delete-volume --volume-id ${data_vol_id} --region ${AWS_REGION}"
        fi
    fi
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

log_step "Teardown complete"

log_info "Surviving resources:"
log_info "  Snapshots tagged Project=${PROJECT_TAG}:"
aws ec2 describe-snapshots \
    --owner-ids self \
    --filters "Name=tag:Project,Values=${PROJECT_TAG}" \
    --region "$AWS_REGION" \
    --query 'Snapshots[].[SnapshotId,StartTime,VolumeSize,Description]' \
    --output table >&2

log_info ""
log_info "Snapshot storage costs roughly \$0.05/GB-month for the unique data."
log_info "If you want to fully clean up snapshots later:"
log_info "  aws ec2 describe-snapshots --owner-ids self \\"
log_info "    --filters Name=tag:Project,Values=${PROJECT_TAG} \\"
log_info "    --query 'Snapshots[].SnapshotId' --output text --region ${AWS_REGION} \\"
log_info "    | xargs -n1 -I{} aws ec2 delete-snapshot --snapshot-id {} --region ${AWS_REGION}"
