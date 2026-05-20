#!/usr/bin/env bash
#
# 02-create-storage.sh — standalone EBS data volume
#
# Creates the project data volume as a STANDALONE resource (not part of any
# launch template or AMI block-device-mapping). Why standalone:
#   - The volume survives instance termination. If you ever need to nuke and
#     rebuild the instance, the data stays put.
#   - It can be snapshotted independently from the boot volume.
#   - Snapshots of just-data are cheaper than snapshots of boot+data.
#
# After this script runs, the volume exists but is unattached. The launch
# script (04) attaches it via a separate aws ec2 attach-volume call.
#
# IDEMPOTENT: if a volume with our Name tag already exists, the script
# reuses it.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export PROJECT_ROOT
# shellcheck source=../../config/aws-config.sh
source "${PROJECT_ROOT}/config/aws-config.sh"
# shellcheck source=./lib.sh
source "${SCRIPT_DIR}/lib.sh"

log_step "Step 2: Creating EBS data volume"

ensure_aws_cli

existing_vol_id="$(aws ec2 describe-volumes \
    --filters "Name=tag:Name,Values=${DATA_VOLUME_NAME}" "Name=tag:Project,Values=${PROJECT_TAG}" \
    --region "$AWS_REGION" \
    --query 'Volumes[0].VolumeId' \
    --output text 2>/dev/null || echo "None")"

if [[ "$existing_vol_id" != "None" && -n "$existing_vol_id" ]]; then
    existing_vol_az="$(aws ec2 describe-volumes \
        --volume-ids "$existing_vol_id" \
        --region "$AWS_REGION" \
        --query 'Volumes[0].AvailabilityZone' \
        --output text)"
    log_info "Data volume already exists: ${existing_vol_id} in AZ ${existing_vol_az}"
    if [[ "$existing_vol_az" != "$AVAILABILITY_ZONE" ]]; then
        log_error "Volume is in AZ ${existing_vol_az}, but config says AVAILABILITY_ZONE=${AVAILABILITY_ZONE}."
        log_error "EBS volumes are AZ-bound. Either:"
        log_error "  a) Update AVAILABILITY_ZONE in config to match the existing volume."
        log_error "  b) Snapshot, delete, recreate from snapshot in the desired AZ."
        exit 1
    fi
    persist_resource "data_volume_id" "$existing_vol_id"
    log_ok "Reusing existing data volume"
    log_step "Step 2 complete (no change)"
    exit 0
fi

log_info "Creating ${DATA_VOLUME_SIZE_GB} GB ${DATA_VOLUME_TYPE} volume in ${AVAILABILITY_ZONE}"

# gp3: 3000 IOPS / 125 MB/s baseline included; sufficient for SfM workloads.
# Increase iops/throughput later if dense-cloud writes become a bottleneck.
vol_id="$(aws ec2 create-volume \
    --availability-zone "$AVAILABILITY_ZONE" \
    --size "$DATA_VOLUME_SIZE_GB" \
    --volume-type "$DATA_VOLUME_TYPE" \
    --encrypted \
    --tag-specifications "$(tag_args volume "$DATA_VOLUME_NAME")" \
    --region "$AWS_REGION" \
    --query 'VolumeId' \
    --output text)"

log_info "Created volume ${vol_id}, waiting for it to become available..."
wait_for_state volume "$vol_id" "available"

persist_resource "data_volume_id" "$vol_id"

log_step "Step 2 complete"
log_info "Volume created (unattached). It will be attached when the instance launches in step 4."
log_info "Next: scripts/aws/03-create-launch-template.sh"
