#!/usr/bin/env bash
# =============================================================================
# 04_activate_trial.sh
# -----------------------------------------------------------------------------
# Activates the Agisoft Metashape Professional 30-day trial.
#
# THIS IS THE STEP THAT STARTS THE TRIAL CLOCK. Run it only when:
#   - Everything in 01_bootstrap.sh ran cleanly
#   - 02_install_metashape.sh ran cleanly (binary on disk)
#   - 03_install_dcv.sh ran cleanly (you can reach the GUI)
#   - 05_validate.sh ran cleanly (GPU visible, Python kernel works, etc.)
#   - The pre-trial boot-volume snapshot has been taken
#   - You actually intend to start the 30-day window today
#
# After this script runs, the timeline becomes:
#   Day 0   (today)            Trial activated
#   Day 0-2                    Chat 4: USGS data acquisition + intake QC
#   Day 2-10                   Chat 5: Metashape processing (dense recon is
#                              the long-running step, plan an overnight run)
#   Day 10-20                  Chat 6: provenance/QC/reconciliation layer
#   Day 20-25                  Chat 7: QGIS annotation
#   Day 25-30                  Buffer / re-runs
#   Day 30                     TRIAL EXPIRES — decide whether to buy a
#                              node-locked Pro license or shelve the project
#
# Note: the Metashape GUI activation dialog runs the same activation flow
# as `metashape.sh --activate <key>` but requires a display. We use the
# CLI path so this can be run over SSH. If your scenario requires GUI
# activation (e.g. offline activation files), connect over DCV first and
# use Help -> Activate Product instead, then skip this script.
# =============================================================================

set -euo pipefail

METASHAPE_BIN="${METASHAPE_BIN:-/opt/metashape-pro/metashape.sh}"
ACTIVATION_LOG="${HOME}/bootstrap-logs/metashape-trial-activation.log"

if [[ ! -x "${METASHAPE_BIN}" ]]; then
  echo "ERROR: ${METASHAPE_BIN} not found. Run 02_install_metashape.sh first."
  exit 1
fi

cat <<'EOF'
============================================================
METASHAPE 30-DAY TRIAL ACTIVATION
============================================================
This will start the 30-day countdown. Once activated, the
clock cannot be paused.

Pre-flight checklist:
  [ ] 01_bootstrap.sh ran cleanly
  [ ] 02_install_metashape.sh ran cleanly
  [ ] 03_install_dcv.sh ran cleanly
  [ ] 05_validate.sh ran cleanly
  [ ] Boot-volume snapshot tagged baseline-pre-trial exists
  [ ] You are ready to do Chats 4-7 in the next ~25 days

============================================================
EOF

read -r -p "Type ACTIVATE to confirm and start the trial clock: " confirm
if [[ "${confirm}" != "ACTIVATE" ]]; then
  echo "Aborted. Trial NOT activated."
  exit 1
fi

mkdir -p "$(dirname "${ACTIVATION_LOG}")"

# Record the moment we pull the trigger. The reconciliation report in Chat 6
# can cite this exact timestamp as the start of the trial window.
ACTIVATED_AT="$(date -Iseconds)"
INSTANCE_ID="$(curl -s --max-time 2 http://169.254.169.254/latest/meta-data/instance-id || echo unknown)"
MAC="$(ip -o link | awk -F': ' '/ether/ {print $2}' | xargs -I{} cat /sys/class/net/{}/address 2>/dev/null | head -1)"

{
  echo "# Metashape 30-day Pro trial activation"
  echo "activated_at:   ${ACTIVATED_AT}"
  echo "expires_circa:  $(date -d '+30 days' -Iseconds)"
  echo "instance_id:    ${INSTANCE_ID}"
  echo "primary_mac:    ${MAC}"
  echo "metashape_bin:  ${METASHAPE_BIN}"
  echo "metashape_ver:  $("${METASHAPE_BIN}" --version 2>&1 | head -1)"
} | tee -a "${ACTIVATION_LOG}"

echo ""
echo "Running activation request..."
# Agisoft documents `--activate <key>` for headless activation. The trial
# does not use a customer key — the flag with no key requests a trial.
# (Reference: Metashape Python API docs + Agisoft KB "headless activation".)
# In practice this requires interactive input for trial registration via the
# Agisoft web flow. The reliable path is:
#   1. Launch Metashape GUI over DCV
#   2. Help -> Activate Product
#   3. Select "Start trial"
#   4. Fill in the email registration form
#
# Print instructions and do NOT silently fail.
cat <<EOF

============================================================
TRIAL ACTIVATION — manual GUI step required
============================================================
Headless activation of a TRIAL (as opposed to a purchased
license key) is not reliably scriptable in Metashape 2.x.
The trial registration flow requires entering an email
address in the Agisoft activation dialog.

Do this now:

  1. Connect to DCV from your MacBook:
        Amazon DCV client -> 52.5.136.119:8443
        User: ubuntu
  2. Open a terminal inside the DCV session and run:
        /opt/metashape-pro/metashape.sh
  3. In Metashape: Help -> Activate Product
  4. Choose "Start 30-day trial"
  5. Enter registration email and accept terms
  6. Confirm the dialog closes with "Trial activated"

The trial fingerprint binds to the MAC of the active network
interface. Verify it bound to the SECONDARY ENI (the stable
one from Chat 2), not the primary ENI which may rotate.

Trial start: ${ACTIVATED_AT}
Trial end:   $(date -d '+30 days' -Iseconds)
============================================================
EOF
