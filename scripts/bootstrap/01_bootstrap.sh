#!/usr/bin/env bash
# =============================================================================
# reef-sfm-mote-keys :: Chat 3 :: EC2 bootstrap
# =============================================================================
# Runs on a freshly-launched g6.4xlarge running the AWS Deep Learning Base
# OSS Nvidia Driver GPU AMI (Ubuntu 24.04). Brings the instance from "logged
# in for the first time" to "ready to install Metashape", but does NOT
# install or activate Metashape itself. That happens in 02_install_metashape.sh
# and 04_activate_trial.sh so the trial clock starts as late as possible.
#
# DESIGN NOTES
# ------------
# Every major step is a bash function. Source this file (`. 01_bootstrap.sh`)
# and call the function you want, or invoke the script with a function name
# as argument (`./01_bootstrap.sh step_python`). The default `run_all` target
# runs everything in order with timing.
#
# Idempotency: every step checks for the presence of its outputs and skips
# if already satisfied. Safe to re-run after a crash. Not safe to run
# concurrently with itself.
#
# Logging: each step prefixes its output with a step name and elapsed time.
# Errors abort the step but do not abort sourced shells.
#
# Assumes: Ubuntu 24.04, running as the `ubuntu` user with sudo, the AWS
# Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04) — the
# 20260522 snapshot used here ships NVIDIA driver 595.71.05, CUDA 13.2,
# Python 3.12, kernel 6.14-aws. Older DLAMI snapshots shipped driver
# 570.x with CUDA 12.6/12.8 — the validation script doesn't pin to a
# specific version, just confirms the GPU stack is functional.
# =============================================================================

set -u  # do NOT `set -e` at the top level — each step decides its own failure mode
shopt -s inherit_errexit 2>/dev/null || true

# ---- configuration knobs ----------------------------------------------------
REPO_URL="${REPO_URL:-git@github.com:velezf/reef-sfm-mote-keys.git}"
REPO_HTTPS_URL="${REPO_HTTPS_URL:-https://github.com/velezf/reef-sfm-mote-keys.git}"
DATA_VOLUME_MOUNT="${DATA_VOLUME_MOUNT:-/data}"    # Chat 2 mounted the data EBS here
REPO_CHECKOUT="${REPO_CHECKOUT:-${DATA_VOLUME_MOUNT}/reef-sfm-mote-keys}"
METASHAPE_VERSION="${METASHAPE_VERSION:-2.3.1}"     # current Pro release as of May 2026
METASHAPE_INSTALL_DIR="${METASHAPE_INSTALL_DIR:-/opt/metashape-pro}"
DCV_VERSION="${DCV_VERSION:-2025.0-20103}"
GIT_USER_NAME="${GIT_USER_NAME:-Francisco Velez}"
GIT_USER_EMAIL="${GIT_USER_EMAIL:-velezf@users.noreply.github.com}"

LOG_DIR="${HOME}/bootstrap-logs"
mkdir -p "${LOG_DIR}"

# ---- helpers ----------------------------------------------------------------
log() {
  # shellcheck disable=SC2155
  local ts="$(date '+%Y-%m-%d %H:%M:%S')"
  printf '[%s] %s\n' "${ts}" "$*" | tee -a "${LOG_DIR}/bootstrap.log"
}

run_step() {
  # run_step <function_name> — wraps a step with timing and logging
  local fn="$1"
  log ">>> START ${fn}"
  local t0
  t0="$(date +%s)"
  if "${fn}"; then
    local t1
    t1="$(date +%s)"
    log "<<< OK    ${fn}  ($((t1 - t0))s)"
    return 0
  else
    local rc=$?
    log "!!! FAIL  ${fn}  (exit ${rc})"
    return "${rc}"
  fi
}

require_root_or_sudo() {
  if [[ "${EUID}" -ne 0 ]] && ! sudo -n true 2>/dev/null; then
    log "ERROR: this step needs passwordless sudo. Reconnect with sudo cached or run as root."
    return 1
  fi
}

# =============================================================================
# Step: system updates
# Expected time: 3-6 minutes depending on age of the AMI snapshot
# =============================================================================
step_apt_update() {
  require_root_or_sudo || return 1
  sudo DEBIAN_FRONTEND=noninteractive apt-get update -y
  sudo DEBIAN_FRONTEND=noninteractive apt-get -y \
    -o Dpkg::Options::="--force-confdef" \
    -o Dpkg::Options::="--force-confold" \
    upgrade
  # autoremove old kernels etc. so /boot doesn't fill up before snapshots
  sudo DEBIAN_FRONTEND=noninteractive apt-get -y autoremove
}

# =============================================================================
# Step: verify NVIDIA driver and CUDA (DLAMI should have these pre-installed)
# Expected time: <30 seconds
# =============================================================================
step_verify_gpu_stack() {
  log "Checking NVIDIA driver via nvidia-smi..."
  if ! command -v nvidia-smi >/dev/null; then
    log "ERROR: nvidia-smi not found. This script assumes the AWS Deep Learning"
    log "       Base OSS Nvidia Driver GPU AMI. If you launched a vanilla Ubuntu"
    log "       AMI, install the driver manually before continuing."
    return 1
  fi
  nvidia-smi || return 1

  log "Checking CUDA via nvcc..."
  # DLAMI puts CUDA under /usr/local/cuda-12.8 with a /usr/local/cuda symlink.
  # The default user PATH may not include it; add for this shell.
  if [[ -x /usr/local/cuda/bin/nvcc ]]; then
    /usr/local/cuda/bin/nvcc --version
  else
    log "ERROR: /usr/local/cuda/bin/nvcc missing. CUDA toolkit not on the AMI?"
    return 1
  fi

  log "Recording driver + CUDA versions to docs/ec2-bootstrap-versions.txt"
  mkdir -p "${REPO_CHECKOUT}/docs" 2>/dev/null || true
  {
    echo "# Captured by step_verify_gpu_stack on $(date -Iseconds)"
    echo "# Host: $(hostname)  Instance: $(curl -s --max-time 2 http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || echo unknown)"
    nvidia-smi --query-gpu=name,driver_version,vbios_version,memory.total --format=csv
    /usr/local/cuda/bin/nvcc --version
    cat /etc/os-release | grep -E '^(NAME|VERSION)='
    uname -r
  } > "${REPO_CHECKOUT}/docs/ec2-bootstrap-versions.txt" 2>/dev/null || true
}

# =============================================================================
# Step: confirm the secondary ENI from Chat 2 is attached
# License fingerprint binds to a MAC. If the secondary ENI isn't here,
# stop now — activating Metashape against the wrong MAC will rehost the
# license to something unstable.
# =============================================================================
step_verify_eni() {
  log "Listing network interfaces and MAC addresses..."
  ip -br link show
  log ""
  log "Expected: at least two interfaces (primary ENI + the stable secondary ENI"
  log "from Chat 2). The MAC of the secondary ENI is what Metashape will bind to."
  log "Record this MAC to docs/aws-resources.md if you haven't already."
  # We don't fail the step — just surface the data. Operator verifies.
}

# =============================================================================
# Step: build essentials and CLI quality-of-life
# Expected time: 1-2 minutes
# =============================================================================
step_apt_essentials() {
  require_root_or_sudo || return 1
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential \
    git \
    curl \
    wget \
    unzip \
    p7zip-full \
    htop \
    tmux \
    jq \
    rsync \
    pkg-config \
    ca-certificates \
    gnupg \
    lsb-release
}

# =============================================================================
# Step: Python 3.12 toolchain
# DLAMI ships /usr/bin/python3.12, but venv and dev headers aren't always
# present. Install explicitly.
# Expected time: 30-60 seconds
# =============================================================================
step_python() {
  require_root_or_sudo || return 1
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3.12 python3.12-venv python3.12-dev \
    python3-pip
  python3.12 --version
}

# =============================================================================
# Step: uv package manager
# Installs to ~/.local/bin/uv; ensure that's on PATH for the ubuntu user.
# Expected time: 10-20 seconds
# =============================================================================
step_uv() {
  if command -v uv >/dev/null 2>&1; then
    log "uv already installed: $(uv --version)"
    return 0
  fi
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # Ensure PATH update is persistent for future shells
  if ! grep -q 'astral-sh/uv' "${HOME}/.bashrc" 2>/dev/null; then
    cat >> "${HOME}/.bashrc" <<'EOF'

# uv (Astral) — installed by reef-sfm bootstrap
export PATH="${HOME}/.local/bin:${PATH}"
EOF
  fi
  # shellcheck source=/dev/null
  export PATH="${HOME}/.local/bin:${PATH}"
  uv --version
}

# =============================================================================
# Step: git config + GitHub SSH key
# Generates a new ed25519 key if one isn't present and prints the public
# key. The operator has to register it with GitHub manually — we can't
# automate that securely from here.
# Expected time: <10 seconds (excluding manual GitHub registration step)
# =============================================================================
step_git() {
  git config --global user.name "${GIT_USER_NAME}"
  git config --global user.email "${GIT_USER_EMAIL}"
  git config --global init.defaultBranch main
  git config --global pull.rebase false

  local key="${HOME}/.ssh/id_ed25519"
  if [[ ! -f "${key}" ]]; then
    mkdir -p "${HOME}/.ssh"
    chmod 700 "${HOME}/.ssh"
    ssh-keygen -t ed25519 -C "${GIT_USER_EMAIL} (reef-ec2)" -f "${key}" -N ""
  fi

  # Add github.com to known_hosts so the first git clone doesn't prompt
  if ! grep -q '^github.com ' "${HOME}/.ssh/known_hosts" 2>/dev/null; then
    ssh-keyscan -H github.com >> "${HOME}/.ssh/known_hosts" 2>/dev/null
  fi

  log ""
  log "============================================================"
  log "ACTION REQUIRED: register this public key with GitHub"
  log "https://github.com/settings/ssh/new   (title: reef-ec2)"
  log "============================================================"
  cat "${key}.pub"
  log "============================================================"
  log "Then test with:  ssh -T git@github.com"
  log "Expected response: 'Hi velezf! You've successfully authenticated...'"
  log "============================================================"
}

# =============================================================================
# Step: clone the project repo onto the data volume
# Expected time: <10 seconds for a fresh repo
# =============================================================================
step_clone_repo() {
  # Sanity-check the data volume is actually mounted before writing to it
  if ! mountpoint -q "${DATA_VOLUME_MOUNT}"; then
    log "ERROR: ${DATA_VOLUME_MOUNT} is not a mountpoint. Chat 2's fstab"
    log "       entry didn't mount the secondary EBS data volume. Fix that"
    log "       before continuing — we do NOT want the repo on the root volume."
    return 1
  fi

  # Make sure ubuntu owns the data volume root
  if [[ ! -w "${DATA_VOLUME_MOUNT}" ]]; then
    sudo chown -R ubuntu:ubuntu "${DATA_VOLUME_MOUNT}"
  fi

  if [[ -d "${REPO_CHECKOUT}/.git" ]]; then
    log "Repo already cloned at ${REPO_CHECKOUT}; pulling latest"
    git -C "${REPO_CHECKOUT}" pull --ff-only
    return 0
  fi

  # Prefer SSH (key registered above); fall back to HTTPS if SSH fails
  if ! git clone "${REPO_URL}" "${REPO_CHECKOUT}"; then
    log "SSH clone failed; falling back to HTTPS (read-only). Fix the SSH key"
    log "registration before pushing from this instance."
    git clone "${REPO_HTTPS_URL}" "${REPO_CHECKOUT}"
  fi
}

# =============================================================================
# Step: uv sync the project environment
# Expected time: 1-3 minutes for the initial sync (minimal deps from Chat 1)
# =============================================================================
step_uv_sync() {
  export PATH="${HOME}/.local/bin:${PATH}"
  cd "${REPO_CHECKOUT}"
  uv sync
  log "Project venv at: ${REPO_CHECKOUT}/.venv"
  "${REPO_CHECKOUT}/.venv/bin/python" --version
}

# =============================================================================
# Step: register the Jupyter kernel
# The kernel spec lives under ~/.local/share/jupyter/kernels/ and points at
# this project's venv. Cursor Remote-SSH and Jupyter both find it there.
# Expected time: <10 seconds
# =============================================================================
step_jupyter_kernel() {
  export PATH="${HOME}/.local/bin:${PATH}"
  cd "${REPO_CHECKOUT}"
  uv run python -m ipykernel install --user \
    --name reef-sfm-mote-keys \
    --display-name "Python (reef-sfm-mote-keys)"

  log "Registered kernels:"
  uv run jupyter kernelspec list
}

# =============================================================================
# Step: QGIS LTR
# QGIS on Ubuntu 24.04 from the official QGIS repo (apt's qgis package is
# usually out of date). Installs qgis + grass + python bindings.
# Expected time: 3-6 minutes (qgis pulls a lot of deps)
# =============================================================================
step_qgis() {
  require_root_or_sudo || return 1
  if command -v qgis >/dev/null 2>&1; then
    log "QGIS already installed: $(qgis --version 2>&1 | head -1 || true)"
    return 0
  fi

  # Use the official QGIS apt repo for the LTR build
  sudo install -d -m 0755 /etc/apt/keyrings
  if [[ ! -f /etc/apt/keyrings/qgis-archive-keyring.gpg ]]; then
    wget -qO - https://download.qgis.org/downloads/qgis-archive-keyring.gpg \
      | sudo tee /etc/apt/keyrings/qgis-archive-keyring.gpg >/dev/null
  fi

  local codename
  codename="$(lsb_release -cs)"
  sudo tee /etc/apt/sources.list.d/qgis.sources >/dev/null <<EOF
Types: deb
URIs: https://qgis.org/ubuntu-ltr
Suites: ${codename}
Components: main
Architectures: amd64
Signed-By: /etc/apt/keyrings/qgis-archive-keyring.gpg
EOF

  sudo DEBIAN_FRONTEND=noninteractive apt-get update -y
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    qgis qgis-plugin-grass python3-qgis
  qgis --version 2>&1 | head -1 || true
}

# =============================================================================
# Step: NICE DCV (Amazon DCV) server + XFCE desktop
# Delegated to a separate script for readability — see 03_install_dcv.sh.
# This step just calls it.
# Expected time: 5-10 minutes
# =============================================================================
step_dcv() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  bash "${here}/03_install_dcv.sh"
}

# =============================================================================
# Step: Metashape Pro tarball install (NO trial activation)
# Delegated to 02_install_metashape.sh.
# Expected time: 2-5 minutes
# =============================================================================
step_metashape_install() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  bash "${here}/02_install_metashape.sh"
}

# =============================================================================
# Step: validation (delegated to 05_validate.sh)
# Expected time: 1-2 minutes
# =============================================================================
step_validate() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  bash "${here}/05_validate.sh"
}

# =============================================================================
# Orchestrator — runs everything except trial activation
# =============================================================================
run_all() {
  run_step step_apt_update         || return 1
  run_step step_verify_gpu_stack   || return 1
  run_step step_verify_eni         # informational; never fails
  run_step step_apt_essentials     || return 1
  run_step step_python             || return 1
  run_step step_uv                 || return 1
  run_step step_git                || return 1
  log ""
  log "============================================================"
  log "PAUSE: register the SSH key with GitHub (printed above),"
  log "       then re-run this script with 'step_clone_repo' onward,"
  log "       OR confirm the key is registered and press ENTER."
  log "============================================================"
  if [[ -t 0 ]]; then read -r -p "Press ENTER to continue, Ctrl-C to abort: " _; fi
  run_step step_clone_repo         || return 1
  run_step step_uv_sync            || return 1
  run_step step_jupyter_kernel     || return 1
  run_step step_qgis               || return 1
  run_step step_dcv                || return 1
  run_step step_metashape_install  || return 1
  run_step step_validate           || return 1

  log ""
  log "============================================================"
  log "BOOTSTRAP COMPLETE (pre-trial baseline)"
  log "Next:"
  log "  1. Take the boot-volume snapshot tagged baseline-pre-trial"
  log "     (see docs/ec2-bootstrap.md, 'Pre-trial snapshot')."
  log "  2. When ready to start the 30-day trial clock, run:"
  log "       bash scripts/bootstrap/04_activate_trial.sh"
  log "============================================================"
}

# ---- dispatch ---------------------------------------------------------------
# If sourced, just expose the functions and stop.
# If executed, run the function named by $1 (default: run_all).
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  target="${1:-run_all}"
  if declare -F "${target}" >/dev/null; then
    "${target}"
  else
    log "Unknown step: ${target}"
    log "Available steps:"
    declare -F | awk '{print $3}' | grep -E '^(step_|run_)'
    exit 2
  fi
fi
