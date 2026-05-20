# reef-sfm-mote-keys — AWS configuration
#
# Single source of truth for all AWS scripts. Sourced by every script in
# scripts/aws/. Edit values here, not in the scripts.
#
# This file is checked into git. It contains resource NAMES and configuration,
# but never secrets. AWS credentials live in ~/.aws/credentials and never here.

# -----------------------------------------------------------------------------
# Identity / region
# -----------------------------------------------------------------------------

# us-east-1 chosen because:
#   - Lower DLAMI release latency than other regions (new images land here first)
#   - All g6 instance families generally available
#   - Cheapest GPU spot/on-demand pricing among US regions
#   - Florida data is east-coast; latency is fine
# Change only if you have a specific reason.
export AWS_REGION="us-east-1"

# All resources tagged with this for cost tracking and cleanup.
# Do not change after Chat 2 — the cost report and teardown script depend on it.
export PROJECT_TAG="reef-sfm-mote-keys"

# -----------------------------------------------------------------------------
# Instance specification
# -----------------------------------------------------------------------------

# g6.4xlarge: 1x NVIDIA L4 (24 GB VRAM), 16 vCPU, 64 GB RAM.
# Pricing (us-east-1, on-demand, May 2026): $1.3232/hr running, ~$0/hr stopped
# (EBS storage charges only). The L4 has more VRAM than the dense-cloud step
# of Metashape typically needs for a single 10x2m transect, but the 16 vCPU /
# 64 GB RAM matters for the CPU-bound alignment phase.
#
# Do NOT change this after the Metashape Pro trial activates in Chat 3.
# Per the 8-step stability pattern: changing instance size after activation
# may invalidate the license fingerprint.
export INSTANCE_TYPE="g6.4xlarge"

# Friendly name for the instance and most resources.
export INSTANCE_NAME="${PROJECT_TAG}-workstation"

# -----------------------------------------------------------------------------
# AMI lookup (resolved at script runtime, never hardcoded)
# -----------------------------------------------------------------------------

# We use AWS's published SSM parameter to look up the latest DLAMI ID at the
# moment of the launch-template build. Hardcoding an AMI ID would rot within
# weeks — AWS publishes a new DLAMI roughly twice a month. The parameter name
# itself is stable; what it resolves to advances over time.
#
# To pin an AMI for reproducibility (recommended for portfolio reproducibility),
# the create-launch-template script CAPTURES the resolved ID at build time and
# writes it to docs/aws-resources.md. Later launches use the launch template's
# captured ID, not the live SSM lookup.
#
# DLAMI choice: "Base OSS Nvidia Driver GPU" variant. This gives us:
#   - Ubuntu 24.04 LTS
#   - NVIDIA OSS driver pre-installed (supports G6 / L4)
#   - CUDA 12.8 toolkit
#   - No pre-installed ML frameworks (we don't need PyTorch/TF for Metashape)
# Reference: https://docs.aws.amazon.com/dlami/latest/devguide/aws-deep-learning-base-gpu-ami-ubuntu-24-04.html
export DLAMI_SSM_PARAMETER="/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-24.04/latest/ami-id"

# -----------------------------------------------------------------------------
# Networking
# -----------------------------------------------------------------------------

export VPC_ID=""  # Empty = use default VPC. Filled in by 01-create-network.sh if needed.
export SUBNET_ID=""  # Empty = pick first subnet in the AZ chosen below.

# Availability zone. Pinning the AZ matters because:
#   - The EBS data volume is AZ-bound; it can only attach to an instance in
#     the same AZ.
#   - The secondary ENI is also AZ-bound.
# us-east-1a is the canonical default. If it has capacity issues, switch to
# us-east-1b BEFORE running 02-create-storage.sh — once the data volume exists,
# the AZ is locked.
export AVAILABILITY_ZONE="us-east-1a"

export SECURITY_GROUP_NAME="${PROJECT_TAG}-sg"

# Your public IP for inbound SSH and DCV. Set this to your current home IP
# in CIDR /32 form, e.g. "203.0.113.45/32".
# Look it up with: curl -s https://checkip.amazonaws.com
# If you work from multiple locations, re-run 01-create-network.sh after
# editing this value; it's idempotent and will replace the rule.
# CRITICAL: never use 0.0.0.0/0 — exposes SSH/DCV to the entire internet.
export MY_IP_CIDR="192.231.146.225/32"  # MUST be set before running 01-create-network.sh

# Elastic IP allocation ID (filled in by 01-create-network.sh).
# Stored in docs/aws-resources.md after creation.
export EIP_ALLOCATION_ID=""

# Secondary ENI ID — provides the stable MAC address that Metashape's
# license fingerprint binds to. Created in 01-create-network.sh, attached
# to the instance in 04-launch-instance.sh, persisted across stop/start
# cycles. NEVER delete or recreate this ENI once the Metashape Pro license
# has been activated against it.
export SECONDARY_ENI_ID=""

# -----------------------------------------------------------------------------
# Storage
# -----------------------------------------------------------------------------

# Boot volume: comes from the AMI. We override to gp3 200 GB so there's
# headroom for Metashape projects' temp files and apt upgrades.
export BOOT_VOLUME_SIZE_GB=200
export BOOT_VOLUME_TYPE="gp3"

# Data volume: separate EBS volume for project files, images, Metashape
# projects, outputs. Kept SEPARATE from boot so:
#   - We can snapshot it independently
#   - We can stop/start/rebuild the instance without losing data
#   - Boot-volume size stays small (cheaper snapshots)
# 1 TB is overkill for the EasternDryRocks site alone (~5 GB of raw imagery,
# probably 50 GB of intermediate Metashape state and final products), but
# at $0.08/GB-month for gp3 it's $80/month at worst. v2 multi-site work
# would fill it. Resize down at teardown if you want.
export DATA_VOLUME_SIZE_GB=1000
export DATA_VOLUME_TYPE="gp3"
export DATA_VOLUME_DEVICE="/dev/sdf"   # Logical name AWS uses; appears as /dev/nvme1n1 on Nitro.
export DATA_VOLUME_MOUNT_POINT="/data"

# -----------------------------------------------------------------------------
# SSH access
# -----------------------------------------------------------------------------

# Name of the EC2 key pair. Created by 01-create-network.sh if it doesn't
# already exist; if it does exist in AWS, the script verifies the local
# private-key file is also present.
export KEY_PAIR_NAME="${PROJECT_TAG}-keypair"
export KEY_PAIR_LOCAL_PATH="${HOME}/.ssh/${KEY_PAIR_NAME}.pem"

# Username for SSH. Default for Ubuntu AMIs is 'ubuntu'.
export SSH_USER="ubuntu"

# SSH alias to register in ~/.ssh/config (used by docs/aws-setup.md instructions).
export SSH_ALIAS="reef-ec2"

# -----------------------------------------------------------------------------
# Naming conventions for derived resources
# -----------------------------------------------------------------------------

export LAUNCH_TEMPLATE_NAME="${PROJECT_TAG}-launch-template"
export DATA_VOLUME_NAME="${PROJECT_TAG}-data-volume"
export SECONDARY_ENI_NAME="${PROJECT_TAG}-license-eni"
export EIP_NAME="${PROJECT_TAG}-eip"

# Snapshot tags
export SNAPSHOT_TAG_BASELINE="${PROJECT_TAG}-baseline-pre-chat3"
export SNAPSHOT_TAG_PRE_TRIAL="${PROJECT_TAG}-pre-metashape-trial"

# -----------------------------------------------------------------------------
# Output file for resource IDs (filled in as resources are created)
# -----------------------------------------------------------------------------

# This file is gitignored by default — it contains resource IDs that aren't
# secret but aren't useful to anyone else. Each script appends its results
# here so later scripts (and you) have a single place to look up what exists.
export RESOURCES_FILE="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}/docs/aws-resources.md"
