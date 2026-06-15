#!/usr/bin/env bash
# run_r2_dense.sh — dense point cloud build for EDR_T1_R2
#
# Table S2 step-12 binding params (must match these exactly):
#   Quality       : High  (downscale=2 in buildDepthMaps)
#   Depth filter  : Mild  (Metashape.MildFiltering)
#   Point colors  : True  (buildPointCloud point_colors=True)
#   Point confidence: True (buildPointCloud point_confidence=True — always on)
#   Tie-pt covariance: applied at Step 6 align (not a dense-stage param)
#
# Pre-dense bounding box: chunk.resetRegion() via r2_set_dense_region.py
# Post-dense crop to 10×1×5 m AOI: stage_aoi (separate session)
#
# Sentinel on success: R2_DENSE_COMPLETE in log
# STOP after dense — do NOT auto-proceed to filter / DSM.

set -euo pipefail

PROJECT=/data/edr_work/edr_r2.psx
PIPELINE=/data/reef-sfm-mote-keys/scripts/metashape/run_pipeline.py
REGION_SETTER=/data/edr_work/probes/r2_set_dense_region.py
LOG_DIR=/data/edr_work/logs
METASHAPE=/opt/metashape-pro/metashape.sh

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOG="${LOG_DIR}/r2_dense_${STAMP}.log"
mkdir -p "${LOG_DIR}"

echo "=== R2 DENSE BUILD $(date -u) ===" | tee -a "${LOG}"
echo "Project : ${PROJECT}"              | tee -a "${LOG}"
echo "Log     : ${LOG}"                  | tee -a "${LOG}"
echo "Params  : Quality=High downscale=2  Filter=Mild  Colors=True  Confidence=True" | tee -a "${LOG}"
echo ""                                  | tee -a "${LOG}"

# ── Step 0: set bounding box via resetRegion ─────────────────────────────────
echo "--- Pre-dense: setting bounding box via chunk.resetRegion() ---" | tee -a "${LOG}"
"${METASHAPE}" -platform offscreen \
    -r "${REGION_SETTER}" \
    2>&1 | tee -a "${LOG}"

echo ""                                  | tee -a "${LOG}"
echo "--- Launching stage_dense ---"    | tee -a "${LOG}"

# ── Step 1: dense build ───────────────────────────────────────────────────────
"${METASHAPE}" -platform offscreen \
    -r "${PIPELINE}" \
    --project "${PROJECT}" \
    --transect EDR_T1_R2 \
    --stage dense \
    2>&1 | tee -a "${LOG}"

RC=${PIPESTATUS[0]}
if [ "${RC}" -ne 0 ]; then
    echo "*** stage_dense FAILED (exit ${RC}) — see ${LOG}" | tee -a "${LOG}"
    exit "${RC}"
fi

echo ""                                  | tee -a "${LOG}"
echo "=== R2_DENSE_COMPLETE $(date -u) ===" | tee -a "${LOG}"
echo "STOP — do NOT run filter or DSM. Review dense metrics first." | tee -a "${LOG}"
