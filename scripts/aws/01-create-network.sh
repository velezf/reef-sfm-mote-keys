#!/usr/bin/env bash
#
# 01-create-network.sh — networking layer
#
# Creates (or reconciles if already present):
#   - EC2 key pair                        $KEY_PAIR_NAME
#   - Security group with SSH + DCV rules $SECURITY_GROUP_NAME
#   - Elastic IP                          (Name=$EIP_NAME)
#   - Secondary ENI                       (Name=$SECONDARY_ENI_NAME)
#
# Why a SEPARATE secondary ENI?
#   - Metashape node-locked Pro licenses fingerprint against a MAC address.
#   - The primary ENI of an EC2 instance gets a fresh MAC when AWS replaces
#     the underlying host hardware (rare but real). An attached secondary ENI
#     keeps its MAC across detach/reattach as long as the ENI itself isn't
#     deleted.
#   - By binding the license to the secondary ENI's MAC, we decouple
#     license stability from instance-hardware concerns.
#
# IDEMPOTENT: re-running this script does NOT create duplicates. It detects
# existing resources by tag and reuses them. Use case: you change MY_IP_CIDR
# in config/aws-config.sh, re-run this script, and the SG rules update in
# place.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export PROJECT_ROOT
# shellcheck source=../../config/aws-config.sh
source "${PROJECT_ROOT}/config/aws-config.sh"
# shellcheck source=./lib.sh
source "${SCRIPT_DIR}/lib.sh"

log_step "Step 1: Creating networking resources"

ensure_aws_cli
require_var MY_IP_CIDR

# -----------------------------------------------------------------------------
# Determine VPC and subnet (default VPC unless config overrides)
# -----------------------------------------------------------------------------

if [[ -z "${VPC_ID:-}" ]]; then
    VPC_ID="$(aws ec2 describe-vpcs \
        --filters "Name=is-default,Values=true" \
        --region "$AWS_REGION" \
        --query 'Vpcs[0].VpcId' \
        --output text)"
    if [[ "$VPC_ID" == "None" || -z "$VPC_ID" ]]; then
        log_error "No default VPC in ${AWS_REGION}, and VPC_ID is not set in config."
        exit 1
    fi
    log_info "Using default VPC: ${VPC_ID}"
fi
persist_resource "vpc_id" "$VPC_ID"

if [[ -z "${SUBNET_ID:-}" ]]; then
    SUBNET_ID="$(aws ec2 describe-subnets \
        --filters "Name=vpc-id,Values=${VPC_ID}" "Name=availability-zone,Values=${AVAILABILITY_ZONE}" \
        --region "$AWS_REGION" \
        --query 'Subnets[0].SubnetId' \
        --output text)"
    if [[ "$SUBNET_ID" == "None" || -z "$SUBNET_ID" ]]; then
        log_error "No subnet found in VPC ${VPC_ID}, AZ ${AVAILABILITY_ZONE}."
        exit 1
    fi
    log_info "Using subnet: ${SUBNET_ID}"
fi
persist_resource "subnet_id" "$SUBNET_ID"

# -----------------------------------------------------------------------------
# Key pair
# -----------------------------------------------------------------------------

log_step "Reconciling key pair: ${KEY_PAIR_NAME}"

key_exists_in_aws="$(aws ec2 describe-key-pairs \
    --region "$AWS_REGION" \
    --filters "Name=key-name,Values=${KEY_PAIR_NAME}" \
    --query 'KeyPairs[0].KeyName' \
    --output text 2>/dev/null || echo "None")"

key_exists_locally=false
[[ -f "$KEY_PAIR_LOCAL_PATH" ]] && key_exists_locally=true

if [[ "$key_exists_in_aws" == "$KEY_PAIR_NAME" && "$key_exists_locally" == "true" ]]; then
    log_ok "Key pair exists both in AWS and at ${KEY_PAIR_LOCAL_PATH}"
elif [[ "$key_exists_in_aws" == "$KEY_PAIR_NAME" && "$key_exists_locally" == "false" ]]; then
    log_error "Key pair ${KEY_PAIR_NAME} exists in AWS but no local file at ${KEY_PAIR_LOCAL_PATH}."
    log_error "AWS does not let you re-download a private key. Options:"
    log_error "  a) Restore from your backups."
    log_error "  b) aws ec2 delete-key-pair --key-name ${KEY_PAIR_NAME} --region ${AWS_REGION}"
    log_error "     then re-run this script (will create a new pair)."
    log_error "     This will lock you out of any existing instance using the old key."
    exit 1
elif [[ "$key_exists_in_aws" != "$KEY_PAIR_NAME" && "$key_exists_locally" == "true" ]]; then
    log_warn "Local key exists at ${KEY_PAIR_LOCAL_PATH} but not in AWS."
    log_warn "Refusing to overwrite local key. Move/rename it and re-run."
    exit 1
else
    log_info "Creating new key pair ${KEY_PAIR_NAME}"
    mkdir -p "$(dirname "$KEY_PAIR_LOCAL_PATH")"
    chmod 700 "$(dirname "$KEY_PAIR_LOCAL_PATH")"
    aws ec2 create-key-pair \
        --key-name "$KEY_PAIR_NAME" \
        --key-type "ed25519" \
        --key-format "pem" \
        --tag-specifications "$(tag_args key-pair "$KEY_PAIR_NAME")" \
        --region "$AWS_REGION" \
        --query 'KeyMaterial' \
        --output text > "$KEY_PAIR_LOCAL_PATH"
    chmod 600 "$KEY_PAIR_LOCAL_PATH"
    log_ok "Created and saved private key to ${KEY_PAIR_LOCAL_PATH}"
fi

persist_resource "key_pair_name" "$KEY_PAIR_NAME"
persist_resource "key_pair_local_path" "$KEY_PAIR_LOCAL_PATH"

# -----------------------------------------------------------------------------
# Security group
# -----------------------------------------------------------------------------

log_step "Reconciling security group: ${SECURITY_GROUP_NAME}"

sg_id="$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=${SECURITY_GROUP_NAME}" "Name=vpc-id,Values=${VPC_ID}" \
    --region "$AWS_REGION" \
    --query 'SecurityGroups[0].GroupId' \
    --output text 2>/dev/null || echo "None")"

if [[ "$sg_id" == "None" || -z "$sg_id" ]]; then
    log_info "Creating security group ${SECURITY_GROUP_NAME}"
    sg_id="$(aws ec2 create-security-group \
        --group-name "$SECURITY_GROUP_NAME" \
        --description "reef-sfm-mote-keys: SSH and Amazon DCV from operator IP only" \
        --vpc-id "$VPC_ID" \
        --tag-specifications "$(tag_args security-group "$SECURITY_GROUP_NAME")" \
        --region "$AWS_REGION" \
        --query 'GroupId' \
        --output text)"
    log_ok "Created SG ${sg_id}"
else
    log_info "Security group exists: ${sg_id}"
fi

persist_resource "security_group_id" "$sg_id"

# Reconcile inbound rules. Strategy: revoke all existing inbound, then add what we want.
# This makes MY_IP_CIDR changes idempotent across re-runs.
log_info "Reconciling SG inbound rules for ${MY_IP_CIDR}"

# Revoke existing inbound rules (ignore errors if no rules exist)
existing_rules_json="$(aws ec2 describe-security-groups \
    --group-ids "$sg_id" \
    --region "$AWS_REGION" \
    --query 'SecurityGroups[0].IpPermissions' \
    --output json)"
if [[ "$existing_rules_json" != "[]" && -n "$existing_rules_json" ]]; then
    aws ec2 revoke-security-group-ingress \
        --group-id "$sg_id" \
        --ip-permissions "$existing_rules_json" \
        --region "$AWS_REGION" \
        > /dev/null
    log_info "Revoked existing inbound rules"
fi

# Add SSH (22) and DCV (8443 TCP + UDP for QUIC) from MY_IP_CIDR only.
# Amazon DCV uses TCP/8443 for connection and optionally UDP/8443 for QUIC
# acceleration. Open both — refusing UDP just falls back to TCP, no error.
aws ec2 authorize-security-group-ingress \
    --group-id "$sg_id" \
    --region "$AWS_REGION" \
    --ip-permissions \
        "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=${MY_IP_CIDR},Description=SSH from operator}]" \
        "IpProtocol=tcp,FromPort=8443,ToPort=8443,IpRanges=[{CidrIp=${MY_IP_CIDR},Description=Amazon DCV TCP}]" \
        "IpProtocol=udp,FromPort=8443,ToPort=8443,IpRanges=[{CidrIp=${MY_IP_CIDR},Description=Amazon DCV QUIC}]" \
    > /dev/null

log_ok "SG inbound rules now: SSH(22) + DCV(8443/tcp,udp) from ${MY_IP_CIDR}"

# Note: outbound default is "all" which is fine for apt/pip/Metashape license check-in.

# -----------------------------------------------------------------------------
# Elastic IP
# -----------------------------------------------------------------------------

log_step "Reconciling Elastic IP: ${EIP_NAME}"

eip_alloc_id="$(aws ec2 describe-addresses \
    --filters "Name=tag:Name,Values=${EIP_NAME}" "Name=tag:Project,Values=${PROJECT_TAG}" \
    --region "$AWS_REGION" \
    --query 'Addresses[0].AllocationId' \
    --output text 2>/dev/null || echo "None")"

if [[ "$eip_alloc_id" == "None" || -z "$eip_alloc_id" ]]; then
    log_info "Allocating new Elastic IP"
    eip_alloc_id="$(aws ec2 allocate-address \
        --domain vpc \
        --tag-specifications "$(tag_args elastic-ip "$EIP_NAME")" \
        --region "$AWS_REGION" \
        --query 'AllocationId' \
        --output text)"
    log_ok "Allocated EIP allocation-id ${eip_alloc_id}"
else
    log_info "Elastic IP exists: ${eip_alloc_id}"
fi

eip_public_ip="$(aws ec2 describe-addresses \
    --allocation-ids "$eip_alloc_id" \
    --region "$AWS_REGION" \
    --query 'Addresses[0].PublicIp' \
    --output text)"

log_ok "EIP: ${eip_public_ip} (allocation-id ${eip_alloc_id})"

persist_resource "eip_allocation_id" "$eip_alloc_id"
persist_resource "eip_public_ip" "$eip_public_ip"

# -----------------------------------------------------------------------------
# Secondary ENI (license MAC stability)
# -----------------------------------------------------------------------------

log_step "Reconciling secondary ENI: ${SECONDARY_ENI_NAME}"

eni_id="$(aws ec2 describe-network-interfaces \
    --filters "Name=tag:Name,Values=${SECONDARY_ENI_NAME}" "Name=tag:Project,Values=${PROJECT_TAG}" \
    --region "$AWS_REGION" \
    --query 'NetworkInterfaces[0].NetworkInterfaceId' \
    --output text 2>/dev/null || echo "None")"

if [[ "$eni_id" == "None" || -z "$eni_id" ]]; then
    log_info "Creating secondary ENI in ${SUBNET_ID}"
    eni_id="$(aws ec2 create-network-interface \
        --subnet-id "$SUBNET_ID" \
        --description "Stable MAC for Metashape Pro license fingerprint" \
        --groups "$sg_id" \
        --tag-specifications "$(tag_args network-interface "$SECONDARY_ENI_NAME")" \
        --region "$AWS_REGION" \
        --query 'NetworkInterface.NetworkInterfaceId' \
        --output text)"
    log_ok "Created ENI ${eni_id}"
else
    log_info "Secondary ENI exists: ${eni_id}"
fi

eni_mac="$(aws ec2 describe-network-interfaces \
    --network-interface-ids "$eni_id" \
    --region "$AWS_REGION" \
    --query 'NetworkInterfaces[0].MacAddress' \
    --output text)"

log_ok "Secondary ENI MAC: ${eni_mac}"
log_warn "Record this MAC. Metashape will bind its license to it in Chat 3."
log_warn "If this ENI is ever deleted, the license will need to be re-hosted."

persist_resource "secondary_eni_id" "$eni_id"
persist_resource "secondary_eni_mac" "$eni_mac"

log_step "Step 1 complete"
log_info "Next: scripts/aws/02-create-storage.sh"
