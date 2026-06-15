#!/usr/bin/env bash
# run_r2_aoi_dsm.sh — stage_aoi + stage_dsm for EDR_T1_R2
#
# stage_aoi: PCA + camera-track orientation, 10×1×5 m region crop, coverage %.
# stage_dsm: metric DSM at 1 cm, interp=ENABLED (Table S2 step 14).
#
# Coverage % (interp-OFF) read from esm.aoi after stage_aoi.
# If < 95 % — script exits with code 2; do NOT run stage_dsm.
# Sentinel on DSM success: R2_DSM_COMPLETE in log.

set -euo pipefail

PROJECT=/data/edr_work/edr_r2.psx
PIPELINE=/data/reef-sfm-mote-keys/scripts/metashape/run_pipeline.py
LOG_DIR=/data/edr_work/logs
METASHAPE=/opt/metashape-pro/metashape.sh
OUT_ROOT=/data/edr_work/products

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOG="${LOG_DIR}/r2_aoi_dsm_${STAMP}.log"
mkdir -p "${LOG_DIR}"

echo "=== R2 stage_aoi + stage_dsm $(date -u) ===" | tee -a "${LOG}"
echo "Log: ${LOG}"                                  | tee -a "${LOG}"
echo ""                                              | tee -a "${LOG}"

# ── stage_aoi ─────────────────────────────────────────────────────────────────
echo "--- stage_aoi ---" | tee -a "${LOG}"
"${METASHAPE}" -platform offscreen \
    -r "${PIPELINE}" \
    --project "${PROJECT}" \
    --transect EDR_T1_R2 \
    --out-root "${OUT_ROOT}" \
    --stage aoi \
    2>&1 | tee -a "${LOG}"

AOI_RC=${PIPESTATUS[0]}
if [ "${AOI_RC}" -ne 0 ]; then
    echo "*** stage_aoi FAILED (exit ${AOI_RC})" | tee -a "${LOG}"
    exit "${AOI_RC}"
fi

# ── Coverage check from esm.aoi ───────────────────────────────────────────────
echo "" | tee -a "${LOG}"
echo "--- Reading esm.aoi coverage ---" | tee -a "${LOG}"

COV=$("${METASHAPE}" -platform offscreen -r - <<'PYEOF' 2>/dev/null
import json, Metashape
doc = Metashape.Document()
doc.open("/data/edr_work/edr_r2.psx", read_only=True)
chunk = doc.chunks[0]
try:
    meta = json.loads(chunk.meta["esm.aoi"])
    cov = meta.get("coverage_interp_off", 0.0)
    print(f"{cov:.4f}")
except Exception as e:
    print(f"ERR:{e}")
PYEOF
)

echo "  esm.aoi.coverage_interp_off = ${COV}" | tee -a "${LOG}"

# Extract numeric value (handle ERR: prefix)
COV_NUM=$(echo "${COV}" | grep -oP '^[0-9.]+' || echo "0")
COV_PCT=$(python3 -c "print(f'{float(\"${COV_NUM}\")*100:.1f}%')" 2>/dev/null || echo "${COV_NUM}")
echo "  Coverage: ${COV_PCT}" | tee -a "${LOG}"

# Check >= 0.95
PASS=$(python3 -c "print('YES' if float('${COV_NUM}') >= 0.95 else 'NO')" 2>/dev/null || echo "NO")
if [ "${PASS}" != "YES" ]; then
    echo "" | tee -a "${LOG}"
    echo "*** COVERAGE BELOW 95% (got ${COV_PCT}) — STOP. AOI centering may still be off." \
        | tee -a "${LOG}"
    echo "    Review stage_aoi log above before running stage_dsm." | tee -a "${LOG}"
    exit 2
fi

echo "  Coverage >= 95% — proceeding to stage_dsm." | tee -a "${LOG}"
echo "" | tee -a "${LOG}"

# ── stage_dsm ─────────────────────────────────────────────────────────────────
echo "--- stage_dsm (interp=ENABLED, 1 cm, Table S2 step 14) ---" | tee -a "${LOG}"
"${METASHAPE}" -platform offscreen \
    -r "${PIPELINE}" \
    --project "${PROJECT}" \
    --transect EDR_T1_R2 \
    --out-root "${OUT_ROOT}" \
    --stage dsm \
    2>&1 | tee -a "${LOG}"

DSM_RC=${PIPESTATUS[0]}
if [ "${DSM_RC}" -ne 0 ]; then
    echo "*** stage_dsm FAILED (exit ${DSM_RC})" | tee -a "${LOG}"
    exit "${DSM_RC}"
fi

echo "" | tee -a "${LOG}"
echo "=== R2_DSM_COMPLETE $(date -u) ===" | tee -a "${LOG}"
echo "STOP — awaiting export + verification before reconcile." | tee -a "${LOG}"
