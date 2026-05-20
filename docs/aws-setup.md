# AWS infrastructure setup

This document records the AWS infrastructure layer for the `reef-sfm-mote-keys` project: the single stable EC2 GPU workstation on which Agisoft Metashape Professional will process the Florida Keys coral reef imagery in subsequent chats.

This is Layer 2 of the project. Layer 1 (the Git repo scaffold) is already done. Layer 3 (Metashape and other software inside the instance) is Chat 3. Nothing in this document installs Metashape — the goal here is a stable, license-friendly Linux GPU workstation that Metashape can be installed onto and stay activated against, then stopped and started repeatedly across a 6–8 weekend project without invalidating the license fingerprint.

## Why a single stable instance, not auto-scaling or spot

Metashape Professional, when run under a node-locked Pro license, fingerprints the host: MAC address, CPU, drive, motherboard serial. If the underlying hardware changes, activation breaks and Agisoft Support has to re-host the license. This is the central operational constraint and it shapes every decision in this layer.

The alternatives all fail this constraint:

- **Auto-scaling group.** Cycles instances. Each new instance is a new fingerprint. Wrong tool.
- **Spot instances.** AWS can reclaim them at two minutes' notice. License re-activation thrash. Wrong tool.
- **Terminate-and-recreate-from-AMI nightly.** A new AMI launch is a new instance, which can mean a new MAC and a different physical host. Wrong tool, even though it would be cheap.
- **Stop and start the same instance.** This is what we want. Stopping pauses compute billing. Starting re-launches on the same logical instance with the same primary ENI, same data volume, and (because we explicitly attached a stable secondary ENI) the same license-bound MAC. The instance can be stopped between weekend sessions to keep cost down while preserving everything Metashape cares about.

The "8-step stability pattern" referenced in the project plan is the operational checklist that supports this. It is encoded in the scripts in `scripts/aws/`; this document explains the reasoning.

## Why Linux over Windows for this workflow

The project is a portfolio piece for a senior clinical research informatician who is comfortable with the Linux command line and SSH. Picking Windows for the EC2 workstation would mean:

- RDP instead of SSH as the primary access protocol. Higher friction, worse for long-running terminal work in Cursor Remote-SSH.
- Windows-specific licensing surcharges on the EC2 hourly rate (typically $0.05–0.10/hour extra on a g6.4xlarge, adding up to real money over 6–8 weekends).
- A heavier OS image (~30 GB minimum boot volume) and slower start/stop cycles.
- Tooling friction: `uv`, `git`, `apt`, `tmux`, and the Python data engineering stack all assume Linux. PowerShell adds gratuitous translation overhead.
- The original Mote/USGS workflow uses Metashape Pro on whatever desktop OS the researcher prefers, and the Combs 2021 / Toth 2025 papers describe no Windows-specific dependencies. The methodology is OS-agnostic.

The only Windows-specific tool in the planned workflow is ArcGIS Pro, which the project plan explicitly de-scopes in Chat 7 in favor of QGIS (Linux-native and fully sufficient for the annotation tasks).

Choosing Linux is therefore not a compromise but the right default for the work and the operator.

## Architecture summary

| Component | Choice | Rationale |
|---|---|---|
| Compute | EC2 `g6.4xlarge` | NVIDIA L4 (24 GB VRAM), 16 vCPU, 64 GB RAM. L4 has enough VRAM for Metashape dense-cloud on single 10×2m transects; the 16 vCPU / 64 GB matters more for the CPU-bound alignment phase. |
| OS / drivers | AWS Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04) | Ships with NVIDIA OSS driver and CUDA 12.8 pre-installed and verified against G6 instances. Saves ~1 hour of driver setup vs. plain Ubuntu Server AMI. |
| Primary access | SSH from MacBook Terminal / iTerm2 | The daily driver. Mostly through the `reef-ec2` alias in `~/.ssh/config`. |
| GUI access | Amazon DCV (formerly NICE DCV) | Used in Chat 5 for Metashape's Gradual Selection / scale-bar / manual QA steps, and in Chat 7 for QGIS annotation. Installed in Chat 3. |
| Public IP | Elastic IP | Stable across stop/start. Keeps `~/.ssh/config` and DCV bookmarks valid. |
| License MAC | Secondary ENI | Decouples Metashape's license fingerprint from the primary ENI. See "License stability" below. |
| Boot storage | 200 GB gp3 EBS, encrypted | Inside the launch template, `DeleteOnTermination=true`. Snapshotted before any major change. |
| Project storage | 1 TB gp3 EBS, encrypted | Standalone (not in the launch template). Survives instance termination so v2 work can build on it. |
| Region | `us-east-1` | DLAMI lands here first; cheapest GPU pricing among US regions; Florida data is east-coast (latency moot). |
| AZ | `us-east-1a` | Pinned. EBS volumes and ENIs are AZ-bound; the pin protects against accidental cross-AZ launches that would orphan the data volume. |
| AWS account | Personal account | Keeps the books clean for a career-transition portfolio. Not NIH STRIDES. |

## The 8-step stability pattern, mapped to scripts

| # | Rule | Where it's enforced |
|---|---|---|
| 1 | Same EC2 instance, never terminate/recreate | `04-launch-instance.sh` detects an existing tagged instance and refuses to launch a duplicate. `teardown.sh` is interactive and labeled "end-of-project". |
| 2 | Preserve the EBS root volume | The root volume has `DeleteOnTermination=true` (so it's cheap to clean up at end-of-project), but the operational pattern is *stop*, not *terminate*. Stopped instances retain their root volume. |
| 3 | Secondary EBS data volume | Created standalone by `02-create-storage.sh`. Not part of the launch template. Attached at launch by `04-launch-instance.sh`. Survives instance termination. |
| 4 | Elastic IP | Allocated by `01-create-network.sh`. Associated at launch. Reassociated automatically by `start-instance.sh` if it ever drifts. |
| 5 | Same hostname | Set to `reef-ec2` by `05-first-boot-setup.sh` via `hostnamectl`. Persists across reboots. |
| 6 | Same ENI (stable MAC) | Secondary ENI created by `01-create-network.sh` with a Name tag for re-discovery. Attached at device-index 1 by `04-launch-instance.sh`. `start-instance.sh` verifies on every resume that the MAC hasn't drifted; bails loudly if it has. |
| 7 | No instance-size changes after activation | Not enforced by code (AWS doesn't gate this). Enforced by discipline and called out at the top of `aws-config.sh`. |
| 8 | Snapshots are reference, not equivalent to "same machine" | `06-create-baseline-snapshot.sh` produces a multi-volume snapshot. Snapshots are restorable to *new* instances; if you ever restore from one, treat the result as fingerprint-different and expect to re-host the Metashape license. |

## License stability: why a secondary ENI

Metashape's node-locked Pro license fingerprint includes the MAC address of a network interface. AWS gives every primary ENI a fresh MAC when AWS replaces the underlying physical host — which can happen silently during stop/start on rare occasion, and is more likely after maintenance events. If Metashape's license is bound to the primary ENI's MAC and AWS rotates that MAC, the license breaks and you spend an afternoon on Agisoft Support to re-host.

A *secondary* ENI is created as its own resource, not as part of the instance launch. Its MAC is fixed for the life of the ENI. We attach it at device-index 1 (primary is 0). Inside the OS, `05-first-boot-setup.sh` brings the secondary interface up so the kernel sees its MAC. When Metashape is installed in Chat 3, it discovers this MAC via the standard network-stack mechanisms and binds the license to it.

From that point on:

- Stop the instance: secondary ENI stays attached, MAC unchanged.
- Start the instance: secondary ENI reattaches automatically at the same device index, MAC unchanged.
- AWS rotates the primary ENI's MAC during a maintenance event: irrelevant. Metashape doesn't care; it's looking at the secondary.
- You manually detach the secondary ENI: this is the one thing that breaks the license, which is why the lifecycle scripts never do that. `teardown.sh` does delete the ENI, but only at end-of-project and after prompting.

`start-instance.sh` runs three sanity checks on every resume:

1. Secondary ENI is still attached at device-index 1.
2. Secondary MAC matches the one recorded in `docs/aws-resources.md`.
3. Data volume is still attached.

If any check fails, the script bails before Metashape ever runs, and you investigate from a calm position instead of from inside an unhappy Metashape session.

## Resource lifecycle map

```
                         ┌──────────────────────────────┐
                         │  Launch template (vN)        │ ← AMI ID pinned at build time
                         │  (script 03)                 │   New version per re-build
                         └──────────────┬───────────────┘
                                        │ run-instances
                                        ▼
   Elastic IP ─── associate ──►   ┌────────────┐  ◄─── attach data volume (standalone)
   (script 01)                    │  EC2       │       (script 02)
                                  │  instance  │
   Secondary ENI ── attach ─────► │  (script   │
   (script 01)                    │   04)      │
                                  └─────┬──────┘
                                        │ ssh
                                        ▼
                                  on-instance setup
                                  (script 05)
                                        │
                                        ▼
                                  multi-volume baseline snapshot
                                  (script 06)
                                        │
                                        ▼
                                  ┌────────────────┐
                                  │ READY FOR      │
                                  │ CHAT 3         │
                                  └────────────────┘
```

## Costs

### Running vs. stopped

g6.4xlarge in `us-east-1`, on-demand:

| State | Hourly compute | EBS (boot 200 GB + data 1 TB, gp3) | Approx total |
|---|---|---|---|
| Running | $1.3232 / hr | ~$0.13 / hr | ~$1.46 / hr |
| Stopped | $0 | ~$0.13 / hr | ~$0.13 / hr (~$96/month) |
| Terminated, data volume kept | $0 | ~$0.11 / hr (1 TB only) | ~$80/month |

Snapshot storage: ~$0.05 / GB-month for the *unique* data (delta from the previous snapshot). The baseline snapshot of a freshly-mounted empty 1 TB volume is near-zero; subsequent snapshots cost the size of changes.

### Aim for stopped between work sessions

A 6–8 weekend project, with say 24 active hours per weekend (Saturday + Sunday, 12 hours/day), is:

- 7 weekends × 24 hours = 168 active hours
- 168 hours × $1.46/hr = **~$245 active compute**
- Plus stopped hours: (~7 weeks - 168 hours) × $0.13 ≈ **~$140 stopped EBS**
- Plus snapshot storage: **~$10**
- **Total expected project cost: $400–500**

If you forget to stop the instance for one full weekend (48 hours running idle), that's +$60. Forgetting for a full week is +$220. The single biggest cost-control discipline is `./scripts/aws/stop-instance.sh` at the end of every session.

### Budget alert

Activate the `Project` cost-allocation tag in the Billing console (Billing → Cost allocation tags → User-defined → activate). Tag activation takes about 24 hours to start filtering. After that, set a budget:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

aws budgets create-budget \
  --account-id "$ACCOUNT_ID" \
  --budget '{
    "BudgetName": "reef-sfm-mote-keys-daily",
    "BudgetLimit": {"Amount": "10.00", "Unit": "USD"},
    "TimeUnit": "DAILY",
    "BudgetType": "COST",
    "CostFilters": {"TagKeyValue": ["user:Project$reef-sfm-mote-keys"]}
  }' \
  --notifications-with-subscribers '[{
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 80,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "YOUR_EMAIL@example.com"}]
  }]'
```

Daily threshold of $10 catches "I left the instance running" inside one billing day. A weekly budget at $50 catches slower leaks.

### Snapshot pricing reality-check

`describe-snapshots` doesn't show cost. The Billing console line item is "EBS Snapshot — GB-month standard". If you need a back-of-envelope estimate, the AWS Pricing API can quote `productFamily=Storage Snapshot`. For this project, snapshot costs are not material; the boot snapshot is ~$1/month, data snapshots scale with how much you fill the data volume.

## macOS-specific setup notes

### AWS CLI

```bash
brew install awscli jq
aws configure
# AWS Access Key ID:     <from IAM>
# AWS Secret Access Key: <from IAM>
# Default region name:   us-east-1
# Default output format: json
```

Verify:

```bash
aws sts get-caller-identity
```

### IAM permissions

The scripts use these AWS API calls. A user/role with `AmazonEC2FullAccess` plus `AWSBudgetsActionsWithAWSResourceControlAccess` (or read-only Budgets) is sufficient. For a more conservative IAM policy:

- `ec2:Describe*`
- `ec2:RunInstances`, `ec2:StartInstances`, `ec2:StopInstances`, `ec2:TerminateInstances`
- `ec2:CreateLaunchTemplate*`, `ec2:DeleteLaunchTemplate*`, `ec2:ModifyLaunchTemplate`
- `ec2:CreateSecurityGroup`, `ec2:AuthorizeSecurityGroupIngress`, `ec2:RevokeSecurityGroupIngress`, `ec2:DeleteSecurityGroup`
- `ec2:CreateKeyPair`, `ec2:DeleteKeyPair`
- `ec2:AllocateAddress`, `ec2:AssociateAddress`, `ec2:ReleaseAddress`
- `ec2:CreateNetworkInterface`, `ec2:AttachNetworkInterface`, `ec2:DeleteNetworkInterface`
- `ec2:CreateVolume`, `ec2:AttachVolume`, `ec2:DetachVolume`, `ec2:DeleteVolume`
- `ec2:CreateSnapshot`, `ec2:CreateSnapshots`, `ec2:DeleteSnapshot`
- `ec2:CreateTags`
- `ssm:GetParameter` (for DLAMI lookup)
- `sts:GetCallerIdentity`

### Key pair file permissions

After `01-create-network.sh` creates `~/.ssh/reef-sfm-mote-keys-keypair.pem`, the script chmods it to `600`. If you ever copy the key file, preserve those permissions or SSH will refuse to use it:

```bash
chmod 600 ~/.ssh/reef-sfm-mote-keys-keypair.pem
```

### Terminal.app vs. iTerm2

Either works. **iTerm2 recommended** for this project because:

- Tabbed sessions let you keep one tab on SSH-into-EC2 (for `htop`, `tmux`) and another on the MacBook (for `git`, editing).
- "Hotkey window" gives you a global keyboard shortcut to a persistent terminal — useful for "I just need to check whether the dense-cloud is still running".
- Better Unicode handling for `lsblk` / `tree` / Metashape's processing reports.

`brew install --cask iterm2` and you're done.

### NICE DCV / Amazon DCV: where it lives

The Deep Learning AMI does **not** include the DCV server. We install it in Chat 3 from the Amazon DCV download site:

```
https://download.nice-dcv.com/  (redirects to amazondcv.com)
```

Note for Chat 3: the product was renamed from **NICE DCV** to **Amazon DCV** with the 2024.0 release. Current version as of May 2026 is 2025.0-20103. The package name still contains `nice-dcv-` for now, e.g.:

```
https://d1uj6qtbmh3dt5.cloudfront.net/2025.0/Servers/nice-dcv-2025.0-20103-ubuntu2404-x86_64.tgz
```

The server listens on TCP/8443 by default with optional UDP/8443 (QUIC) for low-latency. The security group created in `01-create-network.sh` opens both, restricted to `MY_IP_CIDR`. The MacBook client is downloadable from the same site.

## Running the setup

The scripts are numbered and intended to be run in order, from the repo root:

```bash
# 0. Verify prerequisites and discover the current DLAMI
./scripts/aws/00-prereqs.sh

# 1. Networking: key pair, SG, EIP, secondary ENI
#    Make sure MY_IP_CIDR is set in config/aws-config.sh first.
./scripts/aws/01-create-network.sh

# 2. Standalone EBS data volume
./scripts/aws/02-create-storage.sh

# 3. Launch template (pins the current DLAMI)
./scripts/aws/03-create-launch-template.sh

# 4. Launch the instance, attach EIP / ENI / data volume
./scripts/aws/04-launch-instance.sh

# Set up ~/.ssh/config from the snippet:
IP=$(grep eip_public_ip docs/aws-resources.md | sed -E 's/.*`([^`]+)`.*/\1/')
sed "s/REPLACE_WITH_EIP/${IP}/" config/ssh-config.snippet >> ~/.ssh/config

# 5. First-boot setup (runs ON the instance over SSH)
./scripts/aws/05-first-boot-setup.sh

# 6. Baseline snapshot of boot + data volumes
./scripts/aws/06-create-baseline-snapshot.sh
```

Each script is idempotent: re-running it after a successful run is a no-op or a reconciliation of drift (e.g. SG rules if `MY_IP_CIDR` changed).

After step 6: **ready for Chat 3**. The instance is up, mounted, snapshotted; no software installed yet, so the Metashape trial clock has not started.

## Operational scripts

| Script | Purpose | When to run |
|---|---|---|
| `stop-instance.sh` | Stop the instance, preserve everything | End of every work session |
| `start-instance.sh` | Resume the instance, verify license-critical state | Start of every work session |
| `teardown.sh` | End-of-project cleanup; preserves snapshots and (by default) the data volume | Once, after Chat 9 ships |

`start-instance.sh` is the more important of the two: it's what catches a license-fingerprint drift before Metashape does. Get into the habit of running it (not just "aws ec2 start-instances") to start every session.

## What to do if the license breaks anyway

Despite the secondary-ENI strategy, it's possible Metashape's fingerprint will reject reactivation after some AWS-level event we didn't anticipate. The recovery path:

1. Stop the instance.
2. In Metashape's UI (or via CLI on the running instance) deactivate the current license: this returns the seat to Agisoft so it can be re-hosted.
3. Email Agisoft Support with the new fingerprint and a brief explanation (your account history will show this isn't license abuse).
4. Re-activate against the new fingerprint.

Worst case is a 24–48 hour delay. The 30-day Pro trial gives some slack but does not survive deactivation, which is why we don't activate against a permanent license until we know the trial worked cleanly on this hardware.

## Things this layer deliberately does NOT do

- **CloudFormation / Terraform / CDK.** The project plan specified bash scripts, and bash with AWS CLI is the right level of indirection for a single-instance, mostly-static setup. Adding IaC for nine AWS resources would be more code to read and reason about than the scripts themselves.
- **Auto-start scheduling.** Some teams configure CloudWatch Events to auto-stop instances tagged "stop me at 6pm". For a personal project with deliberate session-based work, the human-in-the-loop discipline of explicit `stop-instance.sh` is more reliable.
- **Custom AMI baking.** Some workflows bake the Metashape install into a custom AMI for fast cold-launch. We don't, because (a) baking a Metashape-Pro-activated AMI would burn a license seat into an immutable image, (b) the license fingerprint wouldn't match the launched instance anyway, and (c) Chat 3's bootstrap script is fast enough.
- **VPC / subnet creation.** We use the default VPC. A senior cloud-ops person would create a dedicated VPC for project isolation; for a personal portfolio project on a personal AWS account, the default VPC is fine and one less thing to clean up.
- **Multi-region anything.** Single region, single AZ, single instance. The data is in Florida, the instance is in `us-east-1`, the operator is in Maryland. Nothing here benefits from geographic distribution.

## Cross-reference to other chats

- **Chat 3** will SSH into the instance set up here and install Metashape, NICE DCV server, Python (uv-managed), Jupyter kernel, and QGIS. The very last step of Chat 3 is the 30-day Metashape Pro trial activation; this layer's stability work is the foundation that activation depends on.
- **Chats 4–7** all run against this same instance. No infrastructure changes during those chats.
- **Chat 9** is when `teardown.sh` runs (if it runs at all). The roadmap notes recommend keeping the instance stopped after v1.0 ships in case v2 starts soon.
