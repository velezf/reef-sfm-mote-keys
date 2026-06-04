#!/usr/bin/env bash
# T1 align -> marker-discovery -> EXIT at the pre-dense STOP. NEVER runs dense.
# Detached (setsid/tmux) so it survives SSH disconnect. Idempotent: stages self-skip.
set -uo pipefail
SC=/data/reef-sfm-mote-keys/scripts/metashape/run_pipeline.py
P=/data/edr_work/edr_t1.psx
MS="/opt/metashape-pro/metashape.sh -platform offscreen -r $SC"
echo "=== T1 ALIGN START $(date -u +%Y-%m-%dT%H:%M:%SZ) (detached) ==="
$MS --project "$P" --transect EDR_T1 --focal-mode fallback --stage align 2>&1
rc=$?
echo "=== ALIGN EXIT=$rc $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
if [ $rc -eq 0 ]; then
  echo "=== T1 MARKERS (discovery, plateau auto-tolerance) START $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  $MS --project "$P" --transect EDR_T1 --stage markers 2>&1
  echo "=== MARKERS EXIT=$? $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
else
  echo "*** ALIGN FAILED (rc=$rc) — NOT running markers. ***"
fi
echo "=== PRE-DENSE STOP: align+markers done; dense NOT started (awaits explicit go). ==="
echo "T1_ALIGN_MARKERS_COMPLETE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
