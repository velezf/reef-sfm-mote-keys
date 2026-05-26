#!/usr/bin/env bash
# =============================================================================
# 02_install_metashape.sh
# -----------------------------------------------------------------------------
# Downloads, extracts, and installs Agisoft Metashape Pro on Linux. Does NOT
# activate the trial. The trial clock starts only when 04_activate_trial.sh
# runs, so feel free to run this script any time during setup.
#
# Metashape's Linux requirements (per Agisoft docs):
#   - Debian/Ubuntu with glibc 2.19+
#   - libxcb-xinerama0 (apt) — Agisoft calls this out explicitly
#   - For headless work, a Python 3 interpreter is needed for the bundled
#     Metashape module. Metashape ships its own Python under
#     /opt/metashape-pro/python/, used when you run `metashape.sh` directly.
#     The Metashape module is also importable from /opt/metashape-pro/python/lib
#     into other Python 3 interpreters when LD_LIBRARY_PATH is set correctly,
#     but we'll only do that inside the project's uv venv if/when needed.
# =============================================================================

set -euo pipefail

METASHAPE_VERSION="${METASHAPE_VERSION:-2.3.1}"
METASHAPE_INSTALL_DIR="${METASHAPE_INSTALL_DIR:-/opt/metashape-pro}"
DOWNLOAD_DIR="${DOWNLOAD_DIR:-/tmp}"

# Current release as of May 2026. Pinning to 2.3.1 deliberately:
# - Toth et al. 2025 was processed on Metashape Pro 2.x
# - The PIFSC SOP parameter values are documented against 2.x
# - Upgrading mid-project would invalidate the parameter mapping
# If a newer 2.x release exists, check the release notes for parameter
# changes before bumping.
TARBALL="metashape-pro_$(echo "${METASHAPE_VERSION}" | tr '.' '_')_amd64.tar.gz"
URL="https://download.agisoft.com/${TARBALL}"
URL_MIRROR="https://s3-eu-west-1.amazonaws.com/download.agisoft.com/${TARBALL}"

log() { printf '[metashape-install] %s\n' "$*"; }

log "Installing Agisoft Metashape Professional ${METASHAPE_VERSION}"

# --- 1. Dependencies that Metashape needs at runtime -------------------------
log "Installing Agisoft-listed Linux dependencies..."
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  libxcb-xinerama0 \
  libxcb-cursor0 \
  libgl1 \
  libegl1 \
  libxkbcommon-x11-0 \
  libdbus-1-3 \
  libfontconfig1 \
  libxrender1 \
  libxi6

# --- 2. Skip download if already extracted -----------------------------------
if [[ -x "${METASHAPE_INSTALL_DIR}/metashape.sh" ]]; then
  log "Metashape already installed at ${METASHAPE_INSTALL_DIR}; skipping download."
  log "Installed version: $("${METASHAPE_INSTALL_DIR}/metashape.sh" --version 2>&1 | head -1 || true)"
else
  # --- 3. Download tarball -------------------------------------------------
  cd "${DOWNLOAD_DIR}"
  if [[ ! -f "${TARBALL}" ]]; then
    log "Downloading ${URL}"
    if ! wget --tries=3 --timeout=60 -O "${TARBALL}" "${URL}"; then
      log "Primary download failed; trying mirror ${URL_MIRROR}"
      wget --tries=3 --timeout=60 -O "${TARBALL}" "${URL_MIRROR}"
    fi
  else
    log "Tarball already in ${DOWNLOAD_DIR}; skipping download."
  fi

  # --- 4. Extract to /opt --------------------------------------------------
  log "Extracting to ${METASHAPE_INSTALL_DIR}"
  sudo mkdir -p "${METASHAPE_INSTALL_DIR}"
  # Tarball top-level dir is "metashape-pro" — strip it to put files directly
  # in /opt/metashape-pro.
  sudo tar -xzf "${TARBALL}" -C "${METASHAPE_INSTALL_DIR}" --strip-components=1
  sudo chown -R root:root "${METASHAPE_INSTALL_DIR}"
  sudo chmod +x "${METASHAPE_INSTALL_DIR}/metashape.sh"
fi

# --- 5. Wrapper script for CLI access ----------------------------------------
# A symlink doesn't work because metashape.sh derives paths from $0.
# When invoked through a symlink in /usr/local/bin, $0 resolves to the
# symlink path and dirname gives /usr/local/bin instead of
# /opt/metashape-pro, breaking the library path setup.
# A wrapper script that exec's the real path sidesteps this entirely.
if [[ ! -f /usr/local/bin/metashape ]]; then
  log "Creating wrapper script /usr/local/bin/metashape"
  sudo tee /usr/local/bin/metashape > /dev/null << 'WRAPPER'
#!/bin/bash
exec /opt/metashape-pro/metashape.sh "$@"
WRAPPER
  sudo chmod +x /usr/local/bin/metashape
fi

# --- 5a. Fix tarball permissions ---------------------------------------------
# The Metashape tarball extracts with rwx------ on most files, making them
# inaccessible to the ubuntu user. Open up read and execute bits.
log "Fixing tarball permissions on ${METASHAPE_INSTALL_DIR}..."
sudo chmod -R g+rX,o+rX "${METASHAPE_INSTALL_DIR}"

# --- 6. Make the bundled Python module importable from our project venv ------
# Metashape's Python module lives under /opt/metashape-pro/python/lib. The
# safe pattern is to copy the .pth-style discovery into the project venv
# rather than mutating the system Python. We just print instructions here
# instead of doing it — the venv lives on the data volume and may not be
# initialised yet when this script runs in a different order.
log ""
log "To import the Metashape Python API from the project venv, run:"
log "  echo '/opt/metashape-pro/python/lib/python3.X/site-packages' \\"
log "    > \${REPO_CHECKOUT}/.venv/lib/python3.12/site-packages/metashape.pth"
log "(adjust the python3.X path to match the bundled interpreter)"
log ""
log "Or, simpler: use the bundled interpreter directly for headless processing:"
log "  /opt/metashape-pro/python/bin/python3 your_script.py"
log ""

# --- 7. Print version and stop ------------------------------------------------
log "Installation complete. NOT activating the trial — that's 04_activate_trial.sh."
log ""
log "Verifying installation (headless --version check)..."
/usr/local/bin/metashape --version
