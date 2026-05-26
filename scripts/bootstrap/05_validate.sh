#!/usr/bin/env bash
# =============================================================================
# 05_validate.sh
# -----------------------------------------------------------------------------
# Verifies that the EC2 bootstrap completed correctly. Exits non-zero on
# any failure so it can serve as a gate before 04_activate_trial.sh runs.
#
# Checks:
#   1. nvidia-smi shows the L4 GPU
#   2. nvcc reports a CUDA version
#   3. Metashape CLI launches and reports a version
#   4. Metashape Python module imports from the bundled interpreter
#   5. Metashape enumerates the GPU at the API level
#   6. Project uv venv exists
#   7. Jupyter kernel registered
#   8. QGIS installed
#   9. DCV server is listening on 8443
#   10. Data volume mounted with adequate free space
# =============================================================================

set -u  # NOT -e: we want every check to run even if earlier ones fail

REPO_CHECKOUT="${REPO_CHECKOUT:-/data/reef-sfm-mote-keys}"
METASHAPE_BIN="${METASHAPE_BIN:-/opt/metashape-pro/metashape.sh}"
DATA_VOLUME_MOUNT="${DATA_VOLUME_MOUNT:-/data}"
MIN_FREE_GB="${MIN_FREE_GB:-200}"

pass_count=0
fail_count=0

pass() { printf "  [PASS] %s\n" "$*"; pass_count=$((pass_count + 1)); }
fail() { printf "  [FAIL] %s\n" "$*"; fail_count=$((fail_count + 1)); }
info() { printf "  [info] %s\n" "$*"; }

echo "============================================================"
echo "reef-sfm-mote-keys :: bootstrap validation"
echo "============================================================"

# -- 1. nvidia-smi ------------------------------------------------------------
echo ""
echo "[1/10] NVIDIA driver"
if command -v nvidia-smi >/dev/null 2>&1; then
  if gpu="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null)"; then
    info "GPU: ${gpu}"
    if [[ "${gpu}" == *"L4"* ]]; then
      pass "L4 GPU detected"
    else
      fail "GPU is not an L4 — got '${gpu}' — instance type may not be g6.4xlarge"
    fi
  else
    fail "nvidia-smi failed to query GPU"
  fi
else
  fail "nvidia-smi not found"
fi

# -- 2. nvcc ------------------------------------------------------------------
echo ""
echo "[2/10] CUDA toolkit"
if [[ -x /usr/local/cuda/bin/nvcc ]]; then
  cuda_ver="$(/usr/local/cuda/bin/nvcc --version | awk '/release/ {print $5}' | tr -d ',' || true)"
  if [[ -n "${cuda_ver}" ]]; then
    pass "CUDA toolkit ${cuda_ver}"
  else
    fail "nvcc found but didn't report a version"
  fi
else
  fail "/usr/local/cuda/bin/nvcc missing"
fi

# -- 3. Metashape CLI ---------------------------------------------------------
echo ""
echo "[3/10] Metashape CLI launches"
if [[ -x "${METASHAPE_BIN}" ]]; then
  if ms_ver="$("${METASHAPE_BIN}" --version 2>&1 | head -1)"; then
    pass "Metashape CLI: ${ms_ver}"
  else
    fail "metashape.sh --version returned non-zero"
  fi
else
  fail "${METASHAPE_BIN} not found or not executable"
fi

# -- 4. Metashape Python API via -r -------------------------------------------
echo ""
echo "[4/10] Metashape Python API imports"
cat > /tmp/ms_validate.py << 'PYEOF'
import Metashape
print(Metashape.app.version)
PYEOF
if api_ver=$(/opt/metashape-pro/metashape.sh -r /tmp/ms_validate.py 2>/dev/null | grep -E '^[0-9]+\.[0-9]+'); then
  pass "Metashape Python API: ${api_ver}"
else
  fail "Metashape Python API import failed via metashape.sh -r"
fi

# -- 5. Metashape enumerates GPU devices --------------------------------------
echo ""
echo "[5/10] Metashape enumerates GPU devices"
cat > /tmp/ms_gpu.py << 'PYEOF'
import Metashape
devices = Metashape.app.enumGPUDevices()
if not devices:
    raise SystemExit('NO_GPUS')
for d in devices:
    print(d.get('name','?'), '-', d.get('vendor','?'))
PYEOF
gpu_list=$(/opt/metashape-pro/metashape.sh -r /tmp/ms_gpu.py 2>/dev/null | grep -v "^No\|^Agisoft\|^Platform\|^CPU\|^RAM\|^Found")
if [[ -z "${gpu_list}" ]]; then
  fail "Metashape enumGPUDevices() returned empty"
else
  info "Metashape sees: ${gpu_list}"
  pass "Metashape enumerates at least one GPU"
fi

# -- 6. Project venv ----------------------------------------------------------
echo ""
echo "[6/10] Project uv venv"
if [[ -x "${REPO_CHECKOUT}/.venv/bin/python" ]]; then
  py_ver=$("${REPO_CHECKOUT}/.venv/bin/python" --version 2>&1)
  pass "${py_ver} at ${REPO_CHECKOUT}/.venv"
else
  fail "Project venv missing at ${REPO_CHECKOUT}/.venv (run 'uv sync' in the repo)"
fi

# -- 7. Jupyter kernel --------------------------------------------------------
echo ""
echo "[7/10] Jupyter kernel registered"
if [[ -f "${HOME}/.local/share/jupyter/kernels/reef-sfm-mote-keys/kernel.json" ]]; then
  argv0=$(python3 -c "import json,sys;print(json.load(open('${HOME}/.local/share/jupyter/kernels/reef-sfm-mote-keys/kernel.json'))['argv'][0])" 2>/dev/null || true)
  if [[ "${argv0}" == *".venv/bin/python"* ]]; then
    pass "Kernel points at project venv"
  else
    fail "Kernel registered but argv[0] doesn't point at the project venv: ${argv0}"
  fi
else
  fail "Jupyter kernel 'reef-sfm-mote-keys' not registered"
fi

# -- 8. QGIS ------------------------------------------------------------------
echo ""
echo "[8/10] QGIS installed"
if command -v qgis >/dev/null 2>&1; then
  qgis_ver=$(qgis --version 2>&1 | head -1)
  pass "${qgis_ver}"
else
  fail "qgis not on PATH"
fi

# -- 9. DCV listening ---------------------------------------------------------
echo ""
echo "[9/10] DCV server listening on 8443"
if systemctl is-active --quiet dcvserver 2>/dev/null; then
  if sudo ss -tlnp 2>/dev/null | grep -q ':8443'; then
    pass "dcvserver active, listening on 8443"
  else
    fail "dcvserver service running but 8443 not in LISTEN state"
  fi
else
  fail "dcvserver systemd unit is not active"
fi

# -- 10. Data volume -----------------------------------------------------------
echo ""
echo "[10/10] Data volume mounted with free space"
if mountpoint -q "${DATA_VOLUME_MOUNT}"; then
  free_gb=$(df -BG --output=avail "${DATA_VOLUME_MOUNT}" | tail -1 | tr -d 'G ')
  info "${DATA_VOLUME_MOUNT}: ${free_gb} GB available"
  if (( free_gb >= MIN_FREE_GB )); then
    pass "Data volume has ${free_gb} GB free (>= ${MIN_FREE_GB} GB)"
  else
    fail "Data volume only has ${free_gb} GB free (< ${MIN_FREE_GB} GB) — Chat 5 dense reconstruction may run out of space"
  fi
else
  fail "${DATA_VOLUME_MOUNT} is not a mountpoint"
fi

# -- summary ------------------------------------------------------------------
echo ""
echo "============================================================"
echo "PASS: ${pass_count}    FAIL: ${fail_count}"
echo "============================================================"

if (( fail_count > 0 )); then
  echo "Validation failed. Resolve the failures before running 04_activate_trial.sh."
  exit 1
else
  echo "All checks passed. Take the pre-trial boot-volume snapshot, then run"
  echo "04_activate_trial.sh when you're ready to start the 30-day clock."
  exit 0
fi
