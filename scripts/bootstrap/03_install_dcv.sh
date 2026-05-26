#!/usr/bin/env bash
# =============================================================================
# 03_install_dcv.sh
# -----------------------------------------------------------------------------
# Installs Amazon DCV server (formerly NICE DCV) 2025.0 on Ubuntu 24.04 plus
# a minimal XFCE desktop for it to render. Configures an automatic session
# for the `ubuntu` user.
#
# Notes
# -----
# - The DLAMI does NOT ship DCV. We install the deb packages directly from
#   d1uj6qtbmh3dt5.cloudfront.net.
# - We use XFCE because it's lightweight and reliable over remote display.
#   GNOME on a server is overkill and has rendering issues over DCV.
# - DCV licensing is automatic on EC2 (instance metadata signals AWS-hosted)
#   so we don't need to set up a license file.
# - The DCV server listens on 8443/TCP and 8443/UDP (QUIC). Chat 2's security
#   group should already allow 8443 from the operator's IP.
# - We run an "automatic console session" so the ubuntu user has a single
#   persistent session — convenient for the project's purposes. Multi-user
#   setups would use virtual sessions instead.
# =============================================================================

set -euo pipefail

DCV_VERSION="${DCV_VERSION:-2025.0-20103}"
DCV_TGZ="nice-dcv-${DCV_VERSION}-ubuntu2404-x86_64.tgz"
DCV_URL="https://d1uj6qtbmh3dt5.cloudfront.net/2025.0/Servers/${DCV_TGZ}"
DOWNLOAD_DIR="${DOWNLOAD_DIR:-/tmp}"

log() { printf '[dcv-install] %s\n' "$*"; }

# --- 1. XFCE desktop ---------------------------------------------------------
log "Installing XFCE desktop and xorg server..."
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  xfce4 xfce4-goodies \
  xorg \
  dbus-x11 \
  xserver-xorg-video-dummy \
  mesa-utils

# --- 2. NVIDIA + xorg config for headless GPU rendering ----------------------
# Without this, DCV can't get an X server to attach to on a server with no
# physical display attached. nvidia-xconfig generates an xorg.conf that
# tells X to use the NVIDIA driver in headless mode.
log "Configuring xorg for headless NVIDIA rendering..."
if command -v nvidia-xconfig >/dev/null 2>&1; then
  sudo nvidia-xconfig --preserve-busid --enable-all-gpus --connected-monitor=DFP || true
fi
# Suppress the gdm/lightdm prompt — we don't want a display manager grabbing
# the console; DCV manages sessions itself.
sudo systemctl disable gdm3 2>/dev/null || true
sudo systemctl disable lightdm 2>/dev/null || true

# --- 3. Download and install DCV ---------------------------------------------
if dpkg -s nice-dcv-server >/dev/null 2>&1; then
  log "DCV server already installed: $(dpkg -s nice-dcv-server | awk '/^Version:/ {print $2}')"
else
  cd "${DOWNLOAD_DIR}"
  if [[ ! -f "${DCV_TGZ}" ]]; then
    log "Downloading ${DCV_URL}"
    # Import Amazon DCV GPG key
    wget -qO - https://d1uj6qtbmh3dt5.cloudfront.net/NICE-GPG-KEY \
      | gpg --import -
    wget --tries=3 --timeout=60 "${DCV_URL}"
  fi
  log "Extracting and installing DCV server packages..."
  tar -xzf "${DCV_TGZ}"
  local_dir="${DCV_TGZ%.tgz}"
  cd "${local_dir}"
  # The directory holds three .deb files: nice-dcv-server, nice-xdcv,
  # and nice-dcv-gl (the GL-acceleration plugin). Install all three.
  sudo apt-get install -y ./nice-dcv-server_*.deb ./nice-xdcv_*.deb || true
  # nice-dcv-gl is optional but useful for GPU-accelerated OpenGL — try to
  # install but don't fail if it's not present in the archive
  if ls ./nice-dcv-gl_*.deb >/dev/null 2>&1; then
    sudo apt-get install -y ./nice-dcv-gl_*.deb
  fi
  cd "${DOWNLOAD_DIR}"
fi

# --- 4. Add ubuntu user to the video group so DCV can use the GPU ------------
sudo usermod -aG video ubuntu

# --- 5. Configure an automatic console session for the ubuntu user -----------
log "Configuring auto-launched DCV console session for ubuntu user..."
sudo tee /etc/dcv/dcv.conf >/dev/null <<'EOF'
[license]

[log]

[session-management]
create-session = true

[session-management/automatic-console-session]
owner = "ubuntu"

[display]
target-fps = 30
EOF

# --- 6. Enable and start DCV server -------------------------------------------
log "Enabling dcvserver systemd unit..."
sudo systemctl enable dcvserver
sudo systemctl restart dcvserver
sleep 2
sudo systemctl status dcvserver --no-pager | head -20

# --- 7. Set a password for the ubuntu user (DCV auth uses system creds) ------
log ""
log "============================================================"
log "ACTION REQUIRED: set a password for the ubuntu user."
log "DCV authenticates against system credentials by default."
log "Run:"
log "  sudo passwd ubuntu"
log "============================================================"

# --- 8. Print connection info -----------------------------------------------
PUB_IP="$(curl -s --max-time 2 http://169.254.169.254/latest/meta-data/public-ipv4 || echo '<elastic-ip>')"
log ""
log "DCV server ready."
log "  Connect from macOS using the Amazon DCV client:"
log "  https://download.nice-dcv.com/  (choose the macOS client)"
log "  URL:  ${PUB_IP}:8443"
log "  User: ubuntu"
log "  Pass: (the password you set above)"
log ""
log "Verify the listener is up:"
sudo ss -tlnp | grep -E ':8443' || log "  (no listener on 8443 yet — check 'sudo systemctl status dcvserver')"
