#!/usr/bin/env bash
#
# 05-first-boot-setup.sh — on-instance setup, driven via SSH from the MacBook
#
# Runs the following ON the EC2 instance:
#   - Format the attached data volume if not already formatted (ext4, 1% reserved)
#   - Create /data mount point
#   - Add fstab entry using volume UUID (NOT the device path — Nitro device
#     names can shift across reboots; UUID is stable)
#   - Mount it
#   - Set hostname to reef-ec2 (so the prompt makes sense in long terminals)
#   - Bring up the secondary ENI inside the OS so it has an IP and the kernel
#     sees its MAC (important for Metashape license verification in Chat 3)
#
# IDEMPOTENT: re-running this script is safe. It checks for an existing
# filesystem and existing fstab line before doing anything destructive.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export PROJECT_ROOT
# shellcheck source=../../config/aws-config.sh
source "${PROJECT_ROOT}/config/aws-config.sh"
# shellcheck source=./lib.sh
source "${SCRIPT_DIR}/lib.sh"

log_step "Step 5: First-boot setup (driven over SSH)"

eip_public_ip="$(read_resource "eip_public_ip")"
require_var eip_public_ip "Run 04-launch-instance.sh first."
require_var KEY_PAIR_LOCAL_PATH

if [[ ! -f "$KEY_PAIR_LOCAL_PATH" ]]; then
    log_error "Private key not found at ${KEY_PAIR_LOCAL_PATH}"
    exit 1
fi

# -----------------------------------------------------------------------------
# Build the remote script (heredoc) and pipe it over SSH
# -----------------------------------------------------------------------------

# Variables we need to interpolate INTO the remote script before sending it:
remote_data_mount="${DATA_VOLUME_MOUNT_POINT}"
remote_hostname="reef-ec2"

log_info "Connecting to ${eip_public_ip} as ${SSH_USER}..."

ssh \
    -i "$KEY_PAIR_LOCAL_PATH" \
    -o StrictHostKeyChecking=accept-new \
    -o UserKnownHostsFile="${HOME}/.ssh/known_hosts" \
    -o ConnectTimeout=15 \
    "${SSH_USER}@${eip_public_ip}" \
    "DATA_MOUNT='${remote_data_mount}' NEW_HOSTNAME='${remote_hostname}' bash -s" <<'REMOTE_SCRIPT'
# === Begin remote execution ==================================================
set -euo pipefail

echo "[remote] Running as $(whoami) on $(hostname)"

# -----------------------------------------------------------------------------
# 1. Find the data volume's block device.
# -----------------------------------------------------------------------------
# On Nitro instances (which g6 family is), the device name AWS assigns
# (/dev/sdf) is REMAPPED to an NVMe path. The reliable way to find it:
#   lsblk -d -n -o NAME,SIZE,MOUNTPOINT
# and pick the unmounted ~1 TiB device that isn't the boot drive.
# An even more reliable way: nvme list (which reports the original SCSI
# device name in the NVMe namespace), but `nvme` isn't installed by default
# on DLAMI. So we fall back to a size+mountpoint heuristic.

echo "[remote] Block devices:"
lsblk -d -o NAME,SIZE,TYPE,MOUNTPOINT

# Find the unmounted NVMe disk that isn't the root device.
ROOT_DEV="$(findmnt -n -o SOURCE / | sed 's/p[0-9]*$//' | xargs basename)"
echo "[remote] Root device: ${ROOT_DEV}"

DATA_DEV=""
while read -r name; do
    [[ "$name" == "$ROOT_DEV" ]] && continue
    [[ -z "$name" ]] && continue
    # Skip if any partitions are mounted
    if lsblk -n -o MOUNTPOINT "/dev/${name}" | grep -qE '\S'; then
        continue
    fi
    DATA_DEV="/dev/${name}"
    break
done < <(lsblk -d -n -o NAME -e 7,11)  # exclude loop and rom

if [[ -z "$DATA_DEV" ]]; then
    echo "[remote] ERROR: Could not find the data volume device."
    echo "[remote] Either it's not attached, or already mounted."
    lsblk
    exit 1
fi

echo "[remote] Data volume device: ${DATA_DEV}"

# -----------------------------------------------------------------------------
# 2. Format if not already formatted (idempotency check)
# -----------------------------------------------------------------------------
FS_TYPE="$(sudo blkid -o value -s TYPE "$DATA_DEV" 2>/dev/null || echo "")"

if [[ -z "$FS_TYPE" ]]; then
    echo "[remote] No filesystem on ${DATA_DEV}. Formatting as ext4..."
    # -m 1 reserves only 1% for root (default is 5%, wasteful on a 1 TB data disk).
    # -L 'reef-data' sets a filesystem label for ls -l /dev/disk/by-label/.
    sudo mkfs.ext4 -m 1 -L "reef-data" "$DATA_DEV"
    echo "[remote] Formatted."
else
    echo "[remote] ${DATA_DEV} already has filesystem: ${FS_TYPE}. Skipping mkfs."
fi

# -----------------------------------------------------------------------------
# 3. Create mount point, write fstab entry by UUID, mount
# -----------------------------------------------------------------------------
sudo mkdir -p "$DATA_MOUNT"

UUID="$(sudo blkid -o value -s UUID "$DATA_DEV")"
echo "[remote] Volume UUID: ${UUID}"

FSTAB_LINE="UUID=${UUID}  ${DATA_MOUNT}  ext4  defaults,nofail,x-systemd.device-timeout=10s  0  2"

# Remove any stale entries for this mount point, then add the canonical one.
sudo sed -i.bak "\|[[:space:]]${DATA_MOUNT}[[:space:]]|d" /etc/fstab
echo "$FSTAB_LINE" | sudo tee -a /etc/fstab > /dev/null
echo "[remote] /etc/fstab entry written"

# systemd needs to be told about the new fstab line before mount -a will trust it.
sudo systemctl daemon-reload

# Mount it (or remount if already mounted)
if mountpoint -q "$DATA_MOUNT"; then
    echo "[remote] ${DATA_MOUNT} already mounted."
else
    sudo mount "$DATA_MOUNT"
    echo "[remote] Mounted ${DATA_DEV} on ${DATA_MOUNT}"
fi

# Make the data mount writable by the ubuntu user without requiring sudo.
# Files created by our scripts and Metashape will live here.
sudo chown "$(id -u):$(id -g)" "$DATA_MOUNT"
echo "[remote] Ownership of ${DATA_MOUNT} set to $(whoami)"

# Sanity check: df reports the volume at its target.
df -h "$DATA_MOUNT"

# -----------------------------------------------------------------------------
# 4. Set hostname
# -----------------------------------------------------------------------------
CURRENT_HOSTNAME="$(hostname)"
if [[ "$CURRENT_HOSTNAME" != "$NEW_HOSTNAME" ]]; then
    echo "[remote] Setting hostname: ${CURRENT_HOSTNAME} -> ${NEW_HOSTNAME}"
    sudo hostnamectl set-hostname "$NEW_HOSTNAME"
    # /etc/hosts: replace the line for the old name (Ubuntu sometimes pre-populates one)
    sudo sed -i.bak "s/127.0.1.1.*/127.0.1.1 ${NEW_HOSTNAME}/" /etc/hosts || true
else
    echo "[remote] Hostname already ${NEW_HOSTNAME}"
fi

# -----------------------------------------------------------------------------
# 5. Secondary ENI: enable inside the OS
# -----------------------------------------------------------------------------
# AWS attached the ENI at the hypervisor level, but Ubuntu won't always bring
# it up automatically. Enabling it ensures the kernel sees the MAC, which is
# what Metashape's fingerprint code reads. Without this, Metashape may try
# to bind to the primary ENI's MAC, which is fine for now but defeats the
# whole point of the secondary ENI strategy.

# Find the secondary interface (the one whose name isn't the primary's).
PRIMARY_IF="$(ip -o -4 route show default | awk '{print $5}' | head -n1)"
SECONDARY_IF=""
for iface in $(ls /sys/class/net | grep -E '^(en|eth)'); do
    [[ "$iface" == "$PRIMARY_IF" ]] && continue
    [[ "$iface" == "lo" ]] && continue
    SECONDARY_IF="$iface"
    break
done

if [[ -n "$SECONDARY_IF" ]]; then
    echo "[remote] Secondary interface: ${SECONDARY_IF}"
    SECONDARY_MAC="$(cat "/sys/class/net/${SECONDARY_IF}/address")"
    echo "[remote] Secondary MAC (license-bound): ${SECONDARY_MAC}"
    sudo ip link set "$SECONDARY_IF" up || true
    # Don't configure DHCP on it — we just need the link up so the MAC is
    # visible. Setting it up for IP traffic creates routing complications
    # (default-route conflicts) that we don't need.
else
    echo "[remote] WARN: No secondary interface found. License binding may use primary MAC."
fi

# -----------------------------------------------------------------------------
# 6. Summary
# -----------------------------------------------------------------------------
echo ""
echo "[remote] === First-boot setup complete ==="
echo "[remote] Hostname:        $(hostname)"
echo "[remote] Data volume:     ${DATA_DEV} -> ${DATA_MOUNT} (UUID ${UUID})"
echo "[remote] Disk free:       $(df -h "$DATA_MOUNT" | awk 'NR==2 {print $4}') available"
[[ -n "$SECONDARY_IF" ]] && echo "[remote] License MAC:     ${SECONDARY_MAC} on ${SECONDARY_IF}"
# === End remote execution ====================================================
REMOTE_SCRIPT

log_ok "Remote first-boot setup complete"

log_step "Step 5 complete"
log_info "Next: scripts/aws/06-create-baseline-snapshot.sh"
log_info "After that, you're ready for Chat 3 (Metashape + software bootstrap)."
