#!/usr/bin/env bash
# T1 align -> marker-discovery -> EXIT at the pre-dense STOP. NEVER runs dense.
# Detached (setsid/tmux) so it survives SSH disconnect. Idempotent: stages self-skip.
#
# HARDENED 2026-06-04 after the read-only-open incident (~2 h align lost at save,
# then a FALSE-POSITIVE completion sentinel). The completion sentinel
# T1_ALIGN_MARKERS_COMPLETE is now written ONLY when BOTH stages return rc==0 AND
# a read-only reopen confirms align+markers persisted on disk. Any failure writes
# T1_ALIGN_MARKERS_FAILED and exits non-zero. The pipeline's own open_or_create
# fail-fasts on a read-only/locked open in ~1 s, so a 2 h burn-then-fail cannot
# recur. NEVER write the COMPLETE line unconditionally.
set -uo pipefail
SC=/data/reef-sfm-mote-keys/scripts/metashape/run_pipeline.py
P=/data/edr_work/edr_t1.psx
MS="/opt/metashape-pro/metashape.sh -platform offscreen -r $SC"
ts(){ date -u +%Y-%m-%dT%H:%M:%SZ; }

fail(){  # $1 = stage label, $2 = rc
  echo "*** $1 FAILED (rc=$2) — NOT running later stages, NOT writing completion sentinel. ***"
  echo "T1_ALIGN_MARKERS_FAILED $(ts)"
  exit "$2"
}

echo "=== T1 ALIGN START $(ts) (detached, hardened launcher) ==="

$MS --project "$P" --transect EDR_T1 --focal-mode fallback --stage align 2>&1
rc=$?
echo "=== ALIGN EXIT=$rc $(ts) ==="
[ $rc -eq 0 ] || fail ALIGN $rc

echo "=== T1 MARKERS (discovery, plateau auto-tolerance) START $(ts) ==="
$MS --project "$P" --transect EDR_T1 --stage markers 2>&1
rc=$?
echo "=== MARKERS EXIT=$rc $(ts) ==="
[ $rc -eq 0 ] || fail MARKERS $rc

echo "=== VERIFY (reopen read-only; confirm align+markers persisted) START $(ts) ==="
$MS --project "$P" --verify --verify-expect aligned,markers 2>&1
rc=$?
echo "=== VERIFY EXIT=$rc $(ts) ==="
[ $rc -eq 0 ] || fail VERIFY $rc

echo "=== PRE-DENSE STOP: align+markers done AND verified on disk; dense NOT started (awaits explicit go). ==="
echo "T1_ALIGN_MARKERS_COMPLETE $(ts)"
