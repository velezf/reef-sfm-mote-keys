#!/usr/bin/env bash
#
# 06-create-baseline-snapshot.sh — snapshot boot + data volumes pre-Chat-3
#
# Captures the "freshly launched, first-boot complete, no software installed
# yet" state. Restoring from this snapshot would put us back at the start of
# Chat 3 without having to re-launch the instance or re-mount the data
# volume.
#
# Two snapshots produced:
#   - Boot volume snapshot (root EBS)
#   - Data volume snapshot (the /data EBS)
#
# Snapshot cost is low (~$0.05/GB-month for the delta over the previous
# snapshot, ~$0 for the initial one if mostly empty). We can prune these
# later if storage costs become an issue, but at this stage they're cheap
# insurance.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export PROJECT_ROOT
# shellcheck source=../../config/aws-config.sh
source "${PROJECT_ROOT}/config/aws-config.sh"
# shellcheck source=./lib.sh
source "${SCRIPT_DIR}/lib.sh"

log_step "Step 6: Baseline snapshot (pre-Chat-3)"

ensure_aws_cli

instance_id="$(read_resource "instance_id")"
data_vol_id="$(read_resource "data_volume_id")"
require_var instance_id "Run 04-launch-instance.sh first."
require_var data_vol_id "Run 02-create-storage.sh first."

# Find the boot volume by querying the instance's block device mappings.
boot_vol_id="$(aws ec2 describe-instances \
    --instance-ids "$instance_id" \
    --region "$AWS_REGION" \
    --query 'Reservations[0].Instances[0].BlockDeviceMappings[?DeviceName==`/dev/sda1`].Ebs.VolumeId' \
    --output text)"

if [[ -z "$boot_vol_id" || "$boot_vol_id" == "None" ]]; then
    log_error "Could not find boot volume for instance ${instance_id}"
    exit 1
fi

log_info "Boot volume: ${boot_vol_id}"
log_info "Data volume: ${data_vol_id}"

# Use create-snapshots (plural) so both volumes are captured in a single
# crash-consistent multi-volume snapshot operation.
log_info "Creating multi-volume snapshot..."

snapshot_json="$(aws ec2 create-snapshots \
    --instance-specification "InstanceId=${instance_id}" \
    --description "Baseline pre-Chat-3: instance launched, data volume mounted, no Metashape" \
    --tag-specifications "ResourceType=snapshot,Tags=[
        {Key=Project,Value=${PROJECT_TAG}},
        {Key=Name,Value=${SNAPSHOT_TAG_BASELINE}},
        {Key=Stage,Value=baseline-pre-chat3}
    ]" \
    --region "$AWS_REGION" \
    --output json)"

snapshot_ids="$(echo "$snapshot_json" | jq -r '.Snapshots[].SnapshotId' | paste -sd, -)"
log_ok "Snapshot IDs: ${snapshot_ids}"

persist_resource "baseline_snapshot_ids" "$snapshot_ids"

log_info "Snapshots are completing asynchronously (often takes 5-30 minutes for"
log_info "the first one). You don't have to wait — they continue in the background"
log_info "and don't block further work."

log_info ""
log_info "To watch progress:"
log_info "  aws ec2 describe-snapshots --snapshot-ids ${snapshot_ids//,/ } --region ${AWS_REGION} \\"
log_info "    --query 'Snapshots[].[SnapshotId,Progress,State]' --output table"

log_step "Step 6 complete"
log_info ""
log_info "AWS infrastructure layer is fully set up. Status:"
log_info "  - Instance running, EIP attached, secondary ENI attached, data volume mounted"
log_info "  - Multi-volume baseline snapshot in progress"
log_info ""
log_info "You are ready for Chat 3. Stop the instance between sessions:"
log_info "  ./scripts/aws/stop-instance.sh"
