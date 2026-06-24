#!/usr/bin/env bash
#
# teardown.sh — end-of-project cleanup
#
# Actual order used on 2026-06-23 (lessons from the real run):
#   0. Verify preconditions: local artifact sha256, git state, snapshots completed
#   1. Pull utilization logs (scp before instance is unreachable)
#   2. Create AMI — environment-restore insurance before touching anything
#   3. Commit inventory + AMI id to git, push BEFORE releasing anything
#   4. Disassociate + release EIP (do before terminate so it's explicit)
#   5. Terminate instance (boot vol auto-deletes; data vol survives — see note)
#   6. Wait instance-terminated
#   7. Delete data volume explicitly (DeleteOnTermination=false on the data vol)
#   8. Delete secondary ENI, security group, key pair
#   9. Verify all snapshots survived
#
# What this script DOES delete (compute and one-off network resources):
#   - The EC2 instance (terminate)
#   - The boot volume (deleted by DeleteOnTermination=true)
#   - The data volume (DeleteOnTermination=false — must delete explicitly)
#   - The Elastic IP (disassociated then released)
#   - The secondary ENI (only AFTER instance terminates)
#   - The launch template
#   - The security group
#   - The key pair (in AWS only; the local .pem file is preserved)
#
# What this script DOES NOT delete (preserved for portfolio reproducibility):
#   - Snapshots (all tagged Project=reef-sfm-mote-keys)
#   - The AMI created in step 2
#
# Reasoning: snapshots are cheap (~$0.05/GB-month) and they're the immutable
# record of "the project as it ran." The AMI adds relaunch capability.
#
# This script is INTERACTIVE — it prompts before each destructive action.
# Run with --yes to skip prompts (NOT recommended for first run).
#
# PRECONDITIONS — all must pass or the script aborts:
#   a. A local artifact sha256 can be checked (edit ARTIFACT_PATH / ARTIFACT_SHA256)
#   b. git origin/main has the manifest + ADR commit
#   c. The as-built snapshots are completed / 100%

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
# PRECONDITIONS — all must pass; script aborts on any failure
# -----------------------------------------------------------------------------

log_step "Checking preconditions"

# a. Local artifact sha256 (edit these two variables for your project)
ARTIFACT_PATH="${PROJECT_ROOT}/data/products/EDR_T1_R2/edr_t1_r2_q030_zeropitch_ortho_20260623.tif"
ARTIFACT_SHA256="32e971d37f68dce606ee73102de6d06dfcd8fb13e4f68874bc394db91405d0e8"
if [[ -f "$ARTIFACT_PATH" ]]; then
    actual_sha="$(shasum -a 256 "$ARTIFACT_PATH" | awk '{print $1}')"
    if [[ "$actual_sha" == "$ARTIFACT_SHA256" ]]; then
        log_ok "Precondition A: artifact sha256 verified."
    else
        log_error "Precondition A FAILED: sha256 mismatch on ${ARTIFACT_PATH}"
        log_error "  expected: ${ARTIFACT_SHA256}"
        log_error "  actual:   ${actual_sha}"
        exit 1
    fi
else
    log_warn "Precondition A: artifact not found at ${ARTIFACT_PATH} — skipping sha check."
    log_warn "Verify manually before proceeding."
    if ! confirm "Continue without artifact sha check?"; then exit 1; fi
fi

# b. Git state: origin/main should have the provenance commit
git_top="$(git -C "${PROJECT_ROOT}" rev-parse --show-toplevel 2>/dev/null)"
if [[ -n "$git_top" ]]; then
    git -C "${PROJECT_ROOT}" fetch origin --quiet 2>/dev/null || true
    origin_log="$(git -C "${PROJECT_ROOT}" log --oneline origin/main -3 2>/dev/null)"
    log_info "Precondition B: origin/main recent commits:"
    echo "$origin_log" | while read -r line; do log_info "  $line"; done
    if ! confirm "Does origin/main look right (manifest + ADR committed)?"; then
        log_error "Precondition B: git state not confirmed. Aborting."; exit 1
    fi
else
    log_warn "Not in a git repo — skipping git check."
fi

# c. Required snapshots completed
log_step "Precondition C: verifying snapshots"
REQUIRED_SNAPS=("snap-044e99b2343ea7a7c" "snap-01b844ca1259652fb" "snap-01d7a140ed04a151e")
all_snaps_ok=true
for snap in "${REQUIRED_SNAPS[@]}"; do
    state="$(aws ec2 describe-snapshots --snapshot-ids "$snap" \
        --region "$AWS_REGION" \
        --query 'Snapshots[0].[State,Progress]' --output text 2>/dev/null || echo "NOT_FOUND")"
    if [[ "$state" == "completed	100%" ]]; then
        log_ok "  ${snap}: completed 100%"
    else
        log_error "  ${snap}: ${state} — FAIL"
        all_snaps_ok=false
    fi
done
if [[ "$all_snaps_ok" == "false" ]]; then
    log_error "Precondition C FAILED: one or more required snapshots not completed. Aborting."
    exit 1
fi

log_ok "All preconditions passed. Proceeding with teardown."

# -----------------------------------------------------------------------------
# Step 1: Pull utilization logs while instance is still reachable
# -----------------------------------------------------------------------------

log_step "Step 1: Pull utilization logs from EC2"
log_info "Run manually before this script if the instance is already unreachable:"
log_info "  mkdir -p ${PROJECT_ROOT}/docs/utilization"
log_info "  scp reef-ec2:/data/edr_work/logs/gpu_*.csv reef-ec2:/data/edr_work/logs/cpumem_*.csv \\"
log_info "      ${PROJECT_ROOT}/docs/utilization/"

# -----------------------------------------------------------------------------
# Step 2: Create AMI — do this BEFORE releasing anything
# -----------------------------------------------------------------------------

log_step "Step 2: Create AMI (environment-restore insurance)"
instance_id="$(read_resource "instance_id")"
if confirm "Create AMI from ${instance_id} before teardown? (Recommended — takes a few minutes)"; then
    ami_id="$(aws ec2 create-image \
        --instance-id "$instance_id" \
        --name "reef-sfm-as-built-$(date +%Y-%m-%d)" \
        --no-reboot \
        --tag-specifications "ResourceType=image,Tags=[{Key=Project,Value=${PROJECT_TAG}}]" \
        --region "$AWS_REGION" \
        --query 'ImageId' --output text)"
    log_info "AMI creation started: ${ami_id} — waiting for available state..."
    aws ec2 wait image-available --image-ids "$ami_id" --region "$AWS_REGION"
    log_ok "AMI available: ${ami_id}"
    # Record AMI id and its backing snapshots
    ami_snap_ids="$(aws ec2 describe-images --image-ids "$ami_id" --region "$AWS_REGION" \
        --query 'Images[0].BlockDeviceMappings[].Ebs.SnapshotId' --output text)"
    log_info "AMI backing snapshots: ${ami_snap_ids}"
    log_warn "COMMIT THE AMI ID TO git (docs/aws-resources.md) BEFORE CONTINUING."
    if ! confirm "Have you committed the AMI id (${ami_id}) and pushed to origin/main?"; then
        log_error "Commit the AMI id before destroying anything. Aborting."; exit 1
    fi
fi

# -----------------------------------------------------------------------------
# Step 3 (original): Pre-teardown final data snapshot
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
# Release EIP BEFORE instance termination (explicit disassociate + release)
# Note: EIP auto-disassociates on terminate, but being explicit avoids a timing
# window where the address could be charged as idle.
# -----------------------------------------------------------------------------

log_step "Release Elastic IP (before terminate)"

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

eip_alloc_id="$(read_resource "eip_allocation_id")"
if [[ -n "$eip_alloc_id" ]]; then
    addr_info="$(aws ec2 describe-addresses \
        --allocation-ids "$eip_alloc_id" \
        --region "$AWS_REGION" \
        --query 'Addresses[0].[AllocationId,AssociationId]' \
        --output text 2>/dev/null || echo "None")"

    if [[ "$addr_info" != "None" ]]; then
        assoc_id="$(echo "$addr_info" | awk '{print $2}')"
        if confirm "Disassociate + release EIP $(read_resource eip_public_ip)?"; then
            # Disassociate first if still associated
            if [[ -n "$assoc_id" && "$assoc_id" != "None" ]]; then
                aws ec2 disassociate-address --association-id "$assoc_id" --region "$AWS_REGION"
                log_info "EIP disassociated."
            fi
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
    vol_state="$(aws ec2 describe-volumes \
        --volume-ids "$data_vol_id" \
        --region "$AWS_REGION" \
        --query 'Volumes[0].State' \
        --output text 2>/dev/null || echo "not-found")"

    if [[ "$vol_state" == "not-found" ]]; then
        log_ok "Data volume ${data_vol_id} already gone (DeleteOnTermination was true, or deleted earlier)."
    elif [[ "$vol_state" == "available" ]]; then
        log_warn "Data volume ${data_vol_id} is detached and available (DeleteOnTermination=false)."
        log_warn "It continues to bill at ~\$0.08/GB-month."
        if confirm "Delete the data volume (cannot be undone, but snapshots remain)?"; then
            aws ec2 delete-volume --volume-id "$data_vol_id" --region "$AWS_REGION"
            log_ok "Data volume deleted. Snapshots preserved."
        else
            log_info "Data volume kept. Delete manually: aws ec2 delete-volume --volume-id ${data_vol_id}"
        fi
    else
        log_warn "Data volume ${data_vol_id} state: ${vol_state} — check manually."
    fi
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

log_step "Teardown complete — final safety check"

log_info "Verifying required snapshots survived:"
all_ok=true
for snap in "${REQUIRED_SNAPS[@]}"; do
    snap_state="$(aws ec2 describe-snapshots --snapshot-ids "$snap" \
        --region "$AWS_REGION" \
        --query 'Snapshots[0].[State,Progress]' --output text 2>/dev/null || echo "NOT_FOUND")"
    if [[ "$snap_state" == "completed	100%" ]]; then
        log_ok "  ${snap}: completed 100%"
    else
        log_error "  ${snap}: ${snap_state} — CHECK IMMEDIATELY"
        all_ok=false
    fi
done
[[ "$all_ok" == "true" ]] && log_ok "All required snapshots intact." || log_error "SNAPSHOT CHECK FAILED."

log_info ""
log_info "All snapshots tagged Project=${PROJECT_TAG}:"
aws ec2 describe-snapshots \
    --owner-ids self \
    --filters "Name=tag:Project,Values=${PROJECT_TAG}" \
    --region "$AWS_REGION" \
    --query 'Snapshots[].[SnapshotId,State,Description]' \
    --output table >&2

log_info ""
log_info "Snapshot + AMI storage costs roughly \$0.05/GB-month for unique data."
log_info "If you want to fully clean up snapshots later:"
log_info "  aws ec2 describe-snapshots --owner-ids self \\"
log_info "    --filters Name=tag:Project,Values=${PROJECT_TAG} \\"
log_info "    --query 'Snapshots[].SnapshotId' --output text --region ${AWS_REGION} \\"
log_info "    | xargs -n1 -I{} aws ec2 delete-snapshot --snapshot-id {} --region ${AWS_REGION}"
