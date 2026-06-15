#!/usr/bin/env bash
# R2 single-transect pre-dense reconstruction (Option 2, ADR-0033).
# Runs: import → step4 → align → [CHECKPOINT] → markers → scale → reduce → level
# STOPS before dense. NEVER opens EDR_T1 or EDR_T3 projects.
# Detached (run in tmux) so it survives SSH disconnect; idempotent (stages self-skip).
#
# CHECKPOINT after align: if registration < 80%, script stops — do NOT run reduce
# on a bad alignment. Scale-bar escalation (markers gate fail) also stops the run.
set -uo pipefail

REPO=/data/reef-sfm-mote-keys
SC=$REPO/scripts/metashape/run_pipeline.py
P=/data/edr_work/edr_r2.psx
IMG=/data/raw/P1WHKTRD/EasternDryRocks
LOGDIR=/data/edr_work/logs
MS="/opt/metashape-pro/metashape.sh -platform offscreen -r $SC"
COMMON="--project $P --image-root $IMG --transect EDR_T1_R2"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOG=$LOGDIR/r2_predense_${STAMP}.log

ts(){ date -u +%Y-%m-%dT%H:%M:%SZ; }

fail() {
  echo "*** $1 FAILED (rc=$2) $(ts) ***"
  echo "R2_PREDENSE_FAILED $1 $(ts)"
  exit "$2"
}

check_align_rate() {
  # Extract most recent "rate: XX.X%" from log; abort if < 80%.
  rate=$(grep -oP 'rate: \K[\d.]+' "$LOG" | tail -1)
  if [ -z "$rate" ]; then
    echo "WARNING: could not parse alignment rate from log — inspect manually before proceeding."
    return
  fi
  echo "=== CHECKPOINT: alignment rate = ${rate}% ==="
  if [ "$(echo "$rate < 80" | bc -l)" = "1" ]; then
    echo "*** CHECKPOINT FAIL: alignment rate ${rate}% < 80% — STOPPING before error reduction. ***"
    echo "R2_PREDENSE_FAILED poor-alignment $(ts)"
    exit 1
  fi
  echo "=== CHECKPOINT PASS: ${rate}% >= 80% — proceeding to markers. ==="
}

exec > >(tee "$LOG") 2>&1
echo "=== R2 PRE-DENSE START $STAMP ==="
echo "    project : $P"
echo "    imagery : $IMG  (EDR_T1_R2 swath, 272 images)"
echo "    log     : $LOG"

# ── Stage 1: import 272 R2 TIFFs ──────────────────────────────────────────────
echo "--- STAGE import $(ts) ---"
$MS $COMMON --focal-mode fallback --stage import
rc=$?; echo "--- import EXIT=$rc $(ts) ---"; [ $rc -eq 0 ] || fail import $rc

# ── Stage 2: image quality (disable < 0.50) ───────────────────────────────────
echo "--- STAGE step4 $(ts) ---"
$MS $COMMON --stage step4
rc=$?; echo "--- step4 EXIT=$rc $(ts) ---"; [ $rc -eq 0 ] || fail step4 $rc

# ── Stage 3: align (High, Generic ON, 60k KP, 0 TP, excl-stationary ON) ──────
echo "--- STAGE align $(ts) ---"
$MS $COMMON --focal-mode fallback --stage align
rc=$?; echo "--- align EXIT=$rc $(ts) ---"; [ $rc -eq 0 ] || fail align $rc

# ── CHECKPOINT: registration % ────────────────────────────────────────────────
check_align_rate

# ── Stage 4: detect coded targets (Circular 12-bit, auto-tolerance from 20) ──
echo "--- STAGE markers $(ts) ---"
$MS $COMMON --stage markers
rc=$?; echo "--- markers EXIT=$rc $(ts) ---"
if [ $rc -ne 0 ]; then
  echo "*** MARKER ESCALATION (rc=$rc) — STOP for GUI scale-bar fix. ***"
  echo "    Escalation report: /data/edr_work/products/EDR_T1_R2/markers_escalation.json"
  echo "    Fix markers in DCV GUI, Save, then re-run --stage markers to validate."
  echo "R2_PREDENSE_MARKERS_ESCALATED $(ts)"
  exit $rc
fi

# ── Stage 5: assign 25 cm scale bars (headless, ADR-0033 §scale-bars) ─────────
echo "--- STAGE scale $(ts) ---"
$MS $COMMON --stage scale
rc=$?; echo "--- scale EXIT=$rc $(ts) ---"; [ $rc -eq 0 ] || fail scale $rc

# ── Stage 6: error reduction — Logan RU30 → PA3.5 → RE0.3 (ADR-0023) ─────────
echo "--- STAGE reduce $(ts) ---"
$MS $COMMON --stage reduce
rc=$?; echo "--- reduce EXIT=$rc $(ts) ---"; [ $rc -eq 0 ] || fail reduce $rc

# ── Stage 7: level / orient (camera-nadir, local CRS — ADR-0024/0025) ─────────
# WATCH: hemisphere-flip. If level exits non-zero or chunk extent is absurd, STOP.
echo "--- STAGE level $(ts) ---"
$MS $COMMON --stage level
rc=$?; echo "--- level EXIT=$rc $(ts) ---"; [ $rc -eq 0 ] || fail level $rc

# ── PRE-DENSE STOP ────────────────────────────────────────────────────────────
echo ""
echo "=== PRE-DENSE STOP: all 7 stages complete. Dense NOT started. ==="
echo "=== Inspect this log + project, then issue explicit GO/NO-GO for dense. ==="
echo "R2_PREDENSE_COMPLETE $(ts)"
