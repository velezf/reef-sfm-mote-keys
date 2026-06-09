#!/usr/bin/env bash
# run_t1_full_sequence.sh — markers → scale → POST-SCALE VERIFY → reduce → level → probe
#
# Orchestrates the live T1 reduce recovery:
#   1. Restores edr_t1.psx from edr_t1_preSTEP5_20260608T185845Z (clean pre-scale).
#   2. Runs --stage markers (must exit headless-pass).
#   3. Runs --stage scale (commits ADR-0024 LOCAL_CS fix).
#   4. POST-SCALE VERIFY: checks crs=LOCAL, refs disabled, scale~0.153, 4 bars intact.
#      Halts here if state does not match Arm B — never reduces on unexpected state.
#   5. Runs --stage reduce (vendored Logan 2.x, compute_rmse=False, guards armed).
#   6. Runs --stage level.
#   7. Runs t1_postlevel_probe.py and prints report.
#   STOP. Dense requires a separate explicit GO.
#
# Run in tmux so it survives SSH disconnect:
#   tmux new-session -d -s t1run 'bash /data/reef-sfm-mote-keys/scripts/ops/run_t1_full_sequence.sh 2>&1 | tee /data/edr_work/t1_sequence.log'
# Monitor: tmux attach -t t1run
# FIREWALL: P13HMEON comparison-only. No dense. No live PSX change before step 1 restore.
set -uo pipefail

SC=/data/reef-sfm-mote-keys/scripts/metashape/run_pipeline.py
P=/data/edr_work/edr_t1.psx
BACKUP=/data/edr_work/backups/edr_t1_preSTEP5_20260608T185845Z
OUT_ROOT=/data/edr_work/products
PROBE=/data/reef-sfm-mote-keys/scripts/metashape/probes/t1_postlevel_probe.py
VERIFY=/data/reef-sfm-mote-keys/scripts/metashape/probes/t1_postscale_verify.py
MS="/opt/metashape-pro/metashape.sh -platform offscreen"
ts(){ date -u +%Y-%m-%dT%H:%M:%SZ; }

fail(){
    echo "*** HALTED at stage=$1 (rc=$2) $(ts)"
    echo "*** No dense. No further stages. Backup preserved."
    exit "$2"
}

echo "=== T1 FULL SEQUENCE START $(ts) ==="

# --- Safety: no stale lock ---
LOCK=/data/edr_work/edr_t1.files/lock
if [ -f "$LOCK" ]; then
    echo "LOCK FILE EXISTS at $LOCK — check for live Metashape process."
    echo "Remove the lock manually if it is orphaned, then re-run. HALT."
    exit 1
fi

# --- 1. Restore from pre-scale backup ---
echo
echo "=== RESTORE $(ts) ==="
echo "Source : $BACKUP"
echo "Destination : $P (+ edr_t1.files)"
rm -rf /data/edr_work/edr_t1.files
cp -a  "$BACKUP/edr_t1.files" /data/edr_work/edr_t1.files
cp     "$BACKUP/edr_t1.psx"   /data/edr_work/edr_t1.psx
echo "Restore complete. PSX mtime: $(stat -c %y /data/edr_work/edr_t1.psx)"

# --- 2. markers ---
echo
echo "=== MARKERS $(ts) ==="
$MS -r "$SC" --project "$P" --transect EDR_T1 --stage markers 2>&1
rc=$?
echo "=== MARKERS EXIT=$rc $(ts) ==="
[ $rc -eq 0 ] || fail markers $rc

# --- 3. scale (commits ADR-0024 LOCAL_CS fix) ---
echo
echo "=== SCALE $(ts) ==="
$MS -r "$SC" --project "$P" --transect EDR_T1 --stage scale 2>&1
rc=$?
echo "=== SCALE EXIT=$rc $(ts) ==="
[ $rc -eq 0 ] || fail scale $rc

# --- 4. POST-SCALE VERIFY ---
echo
echo "=== POST-SCALE VERIFY $(ts) ==="
$MS -r "$VERIFY" "$P" 2>&1
rc=$?
echo "=== VERIFY EXIT=$rc $(ts) ==="
if [ $rc -ne 0 ]; then
    echo "POST-SCALE VERIFY FAILED — state does not match Arm B."
    echo "HALTING. Do NOT reduce on unexpected state. Investigate before proceeding."
    exit 1
fi
echo "Verify PASSED — proceeding to reduce."

# --- 5. reduce (vendored Logan 2.x, compute_rmse=False, guards 3a/3b/3c) ---
echo
echo "=== REDUCE $(ts) ==="
$MS -r "$SC" --project "$P" --transect EDR_T1 --stage reduce 2>&1
rc=$?
echo "=== REDUCE EXIT=$rc $(ts) ==="
[ $rc -eq 0 ] || fail reduce $rc

# --- 6. level ---
echo
echo "=== LEVEL $(ts) ==="
$MS -r "$SC" --project "$P" --transect EDR_T1 --stage level 2>&1
rc=$?
echo "=== LEVEL EXIT=$rc $(ts) ==="
[ $rc -eq 0 ] || fail level $rc

# --- 7. post-level probe ---
echo
echo "=== POST-LEVEL PROBE $(ts) ==="
$MS -r "$PROBE" "$P" "$OUT_ROOT" 2>&1
rc=$?
echo "=== PROBE EXIT=$rc $(ts) ==="

echo
echo "=== T1 FULL SEQUENCE DONE $(ts) ==="
echo "STOP. Dense requires a separate explicit GO."
