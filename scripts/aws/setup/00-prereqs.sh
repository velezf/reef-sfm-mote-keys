#!/usr/bin/env bash
#
# 00-prereqs.sh — verify environment before touching AWS
#
# What this does:
#   - Verifies aws CLI and jq are installed.
#   - Verifies credentials work (aws sts get-caller-identity).
#   - Verifies MY_IP_CIDR is set (you need this for the security group).
#   - Resolves the DLAMI SSM parameter to a concrete AMI ID and prints it.
#   - Suggests an AWS Budgets alert command (does NOT auto-create; that's a
#     deliberate one-time setup decision the operator should make).
#
# What this does NOT do:
#   - Create any AWS resources. This is a read-only diagnostic.
#
# Run this first. Re-run any time you change config/aws-config.sh.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export PROJECT_ROOT
# shellcheck source=../../config/aws-config.sh
source "${PROJECT_ROOT}/config/aws-config.sh"
# shellcheck source=../lib.sh
source "${SCRIPT_DIR}/../lib.sh"

log_step "Step 0: Verifying prerequisites"

ensure_aws_cli

log_step "Verifying config/aws-config.sh"

require_var AWS_REGION
require_var PROJECT_TAG
require_var INSTANCE_TYPE
require_var AVAILABILITY_ZONE
require_var MY_IP_CIDR \
    "Look up your IP with: curl -s https://checkip.amazonaws.com — then put that/32 in MY_IP_CIDR"

# Validate MY_IP_CIDR isn't 0.0.0.0/0
if [[ "$MY_IP_CIDR" == "0.0.0.0/0" ]]; then
    log_error "MY_IP_CIDR is 0.0.0.0/0 — refusing to open SSH and DCV to the entire internet."
    log_error "Set MY_IP_CIDR to your specific IP in /32 form."
    exit 1
fi

# Validate MY_IP_CIDR looks like a CIDR
if ! [[ "$MY_IP_CIDR" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$ ]]; then
    log_error "MY_IP_CIDR '${MY_IP_CIDR}' doesn't look like a CIDR (e.g. 203.0.113.45/32)"
    exit 1
fi

log_ok "MY_IP_CIDR = ${MY_IP_CIDR}"

# Detect current IP and compare — if different, warn
current_ip="$(curl -fsS https://checkip.amazonaws.com 2>/dev/null || echo "unknown")"
expected_ip="${MY_IP_CIDR%/*}"
if [[ "$current_ip" != "unknown" && "$current_ip" != "$expected_ip" ]]; then
    log_warn "Your current public IP is ${current_ip}, but MY_IP_CIDR is set to ${MY_IP_CIDR}."
    log_warn "Update config/aws-config.sh and re-run scripts/aws/01-create-network.sh"
    log_warn "to update the security group inbound rule (the script is idempotent)."
fi

log_step "Resolving DLAMI SSM parameter -> AMI ID"

ami_id="$(aws ssm get-parameter \
    --region "$AWS_REGION" \
    --name "$DLAMI_SSM_PARAMETER" \
    --query 'Parameter.Value' \
    --output text 2>&1)" || {
        log_error "Failed to resolve DLAMI SSM parameter:"
        log_error "$ami_id"
        log_error "Possible causes: IAM principal lacks ssm:GetParameter, or"
        log_error "the parameter path has changed. See:"
        log_error "  https://docs.aws.amazon.com/dlami/latest/devguide/aws-deep-learning-base-gpu-ami-ubuntu-24-04.html"
        exit 1
    }

log_ok "DLAMI resolves to: ${ami_id}"

# Pull the AMI's name for sanity
ami_name="$(aws ec2 describe-images \
    --region "$AWS_REGION" \
    --image-ids "$ami_id" \
    --query 'Images[0].Name' \
    --output text 2>/dev/null || echo "unknown")"
log_info "AMI name: ${ami_name}"

log_step "Verifying instance type ${INSTANCE_TYPE} is available in ${AVAILABILITY_ZONE}"

# Some GPU instance types have AZ-specific capacity. Better to find out now.
offerings="$(aws ec2 describe-instance-type-offerings \
    --location-type availability-zone \
    --filters "Name=location,Values=${AVAILABILITY_ZONE}" "Name=instance-type,Values=${INSTANCE_TYPE}" \
    --region "$AWS_REGION" \
    --query 'InstanceTypeOfferings[0].InstanceType' \
    --output text 2>/dev/null || echo "None")"

if [[ "$offerings" == "$INSTANCE_TYPE" ]]; then
    log_ok "${INSTANCE_TYPE} is offered in ${AVAILABILITY_ZONE}"
else
    log_warn "${INSTANCE_TYPE} is NOT offered in ${AVAILABILITY_ZONE}."
    log_warn "Try switching AVAILABILITY_ZONE in config/aws-config.sh to:"
    aws ec2 describe-instance-type-offerings \
        --location-type availability-zone \
        --filters "Name=instance-type,Values=${INSTANCE_TYPE}" \
        --region "$AWS_REGION" \
        --query 'InstanceTypeOfferings[].Location' \
        --output text 2>/dev/null | tr '\t' '\n' | sed 's/^/      /' >&2
    exit 1
fi

log_step "Suggested next steps"

cat >&2 <<EOF

Prerequisites look good.

If you have not yet set up an AWS Budgets alert for this project, do it now.
Suggested daily threshold: \$5/day, alert at 80%. Example command:

  aws budgets create-budget \\
    --account-id $(aws sts get-caller-identity --query Account --output text) \\
    --budget '{
      "BudgetName": "${PROJECT_TAG}-daily",
      "BudgetLimit": {"Amount": "5.00", "Unit": "USD"},
      "TimeUnit": "DAILY",
      "BudgetType": "COST",
      "CostFilters": {"TagKeyValue": ["user:Project\$${PROJECT_TAG}"]}
    }' \\
    --notifications-with-subscribers '[...]'   # see AWS docs for the subscriber format

Tag-based cost filtering only works after you've activated the 'Project' tag
in the Billing console -> Cost Allocation Tags. Do that once, before launching
the instance. AWS-internal tag activation takes ~24 hours to start filtering.

Next: scripts/aws/01-create-network.sh
EOF

log_ok "Step 0 complete"
