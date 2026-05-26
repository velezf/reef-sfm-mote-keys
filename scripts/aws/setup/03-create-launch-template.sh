#!/usr/bin/env bash
#
# 03-create-launch-template.sh — build the EC2 launch template
#
# A launch template captures everything needed to launch the instance in a
# reproducible way:
#   - AMI ID (pinned at template-build time)
#   - Instance type
#   - Key pair name
#   - Security group(s)
#   - Block device mappings (boot volume override)
#   - User data (none here; we bootstrap via SSH in Chat 3)
#   - Resource tags
#
# We DO NOT include the data volume in the launch template's block device
# mappings. The data volume is a standalone resource that we attach after
# launch (see 04-launch-instance.sh). This is what lets the data volume
# outlive the instance.
#
# IDEMPOTENT: if the template already exists, we add a new VERSION pinning
# the latest AMI ID; the previous version is preserved for rollback.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export PROJECT_ROOT
# shellcheck source=../../config/aws-config.sh
source "${PROJECT_ROOT}/config/aws-config.sh"
# shellcheck source=../lib.sh
source "${SCRIPT_DIR}/../lib.sh"

log_step "Step 3: Building launch template"

ensure_aws_cli

# Load resource IDs from step 1
sg_id="$(read_resource "security_group_id")"
require_var sg_id "Run 01-create-network.sh first."

# Resolve current DLAMI AMI ID and PIN it into the template
log_info "Resolving DLAMI SSM parameter -> AMI ID"
ami_id="$(aws ssm get-parameter \
    --region "$AWS_REGION" \
    --name "$DLAMI_SSM_PARAMETER" \
    --query 'Parameter.Value' \
    --output text)"
log_ok "AMI: ${ami_id}"
persist_resource "ami_id" "$ami_id"

# Build the LaunchTemplateData JSON.
#
# Notes:
#   - DeleteOnTermination=true on boot volume: if we terminate the instance,
#     the boot volume goes away. We snapshot it before terminating in
#     teardown.sh.
#   - VolumeType=gp3 with explicit IOPS/Throughput: gp3 defaults to 3000 IOPS /
#     125 MB/s, which is fine, but specifying them explicitly future-proofs
#     against AWS default changes.
#   - We DON'T put NetworkInterfaces here, because we want the launch script
#     to drive ENI logic. Putting the secondary ENI in the template would
#     conflict with the standalone ENI we created in step 1.
#   - User data is intentionally empty. Software bootstrap is Chat 3.

template_data_file="$(mktemp)"
trap 'rm -f "$template_data_file"' EXIT

cat > "$template_data_file" <<EOF
{
  "ImageId": "${ami_id}",
  "InstanceType": "${INSTANCE_TYPE}",
  "KeyName": "${KEY_PAIR_NAME}",
  "SecurityGroupIds": ["${sg_id}"],
  "BlockDeviceMappings": [
    {
      "DeviceName": "/dev/sda1",
      "Ebs": {
        "VolumeSize": ${BOOT_VOLUME_SIZE_GB},
        "VolumeType": "${BOOT_VOLUME_TYPE}",
        "Iops": 3000,
        "Throughput": 125,
        "DeleteOnTermination": true,
        "Encrypted": true
      }
    }
  ],
  "TagSpecifications": [
    {
      "ResourceType": "instance",
      "Tags": [
        {"Key": "Project", "Value": "${PROJECT_TAG}"},
        {"Key": "Name", "Value": "${INSTANCE_NAME}"}
      ]
    },
    {
      "ResourceType": "volume",
      "Tags": [
        {"Key": "Project", "Value": "${PROJECT_TAG}"},
        {"Key": "Name", "Value": "${INSTANCE_NAME}-boot"}
      ]
    }
  ],
  "MetadataOptions": {
    "HttpTokens": "required",
    "HttpEndpoint": "enabled"
  }
}
EOF

# Check if the template already exists
existing_template_id="$(aws ec2 describe-launch-templates \
    --filters "Name=launch-template-name,Values=${LAUNCH_TEMPLATE_NAME}" \
    --region "$AWS_REGION" \
    --query 'LaunchTemplates[0].LaunchTemplateId' \
    --output text 2>/dev/null || echo "None")"

if [[ "$existing_template_id" == "None" || -z "$existing_template_id" ]]; then
    log_info "Creating launch template ${LAUNCH_TEMPLATE_NAME}"
    template_id="$(aws ec2 create-launch-template \
        --launch-template-name "$LAUNCH_TEMPLATE_NAME" \
        --version-description "Initial; AMI ${ami_id}" \
        --launch-template-data "file://${template_data_file}" \
        --tag-specifications "$(tag_args launch-template "$LAUNCH_TEMPLATE_NAME")" \
        --region "$AWS_REGION" \
        --query 'LaunchTemplate.LaunchTemplateId' \
        --output text)"
    template_version=1
    log_ok "Created launch template ${template_id} version 1"
else
    log_info "Launch template exists: ${existing_template_id}. Adding new version with latest AMI."
    template_version="$(aws ec2 create-launch-template-version \
        --launch-template-id "$existing_template_id" \
        --version-description "Refresh; AMI ${ami_id} ($(date -u +%Y-%m-%dT%H:%M:%SZ))" \
        --launch-template-data "file://${template_data_file}" \
        --region "$AWS_REGION" \
        --query 'LaunchTemplateVersion.VersionNumber' \
        --output text)"
    template_id="$existing_template_id"

    # Set the new version as default so 04-launch-instance.sh picks it up
    aws ec2 modify-launch-template \
        --launch-template-id "$template_id" \
        --default-version "$template_version" \
        --region "$AWS_REGION" \
        > /dev/null
    log_ok "Added version ${template_version} and set as default"
fi

persist_resource "launch_template_id" "$template_id"
persist_resource "launch_template_default_version" "$template_version"

log_step "Step 3 complete"
log_info "Next: scripts/aws/04-launch-instance.sh"
