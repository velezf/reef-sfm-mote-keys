#!/usr/bin/env bash
# monitor.sh — log GPU and CPU/RAM utilization to timestamped files during a run.
#
# Purpose: capture time-series resource data so future instance-sizing decisions
# rest on real peaks (peak VRAM, sustained GPU%, RAM headroom), not snapshots.
# The smoke test (325 images) won't stress VRAM the way the full EDR_T1 run
# (2424 images) will, so data that actually informs sizing should come from
# a FULL transect run — but this works for any run.
#
# Writes two CSV-ish logs under /data/edr_work/logs/:
#   gpu_<stamp>.csv    — timestamp, gpu%, mem%, mem_used_MB, mem_total_MB
#   cpumem_<stamp>.csv — timestamp, cpu%, mem_used_MB, mem_total_MB, swap_used_MB
#
# Usage:
#   ./scripts/monitor.sh start        # start both loggers in the background
#   ./scripts/monitor.sh stop         # stop them, print log paths
#   ./scripts/monitor.sh status       # are they running?
#   ./scripts/monitor.sh summary      # peak/sustained stats from the latest logs
#   ./scripts/monitor.sh tail         # tail -f the most recent logs (Ctrl-C to exit)
#   ./scripts/monitor.sh logs         # list all log files with sizes
#
# Typical flow:
#   ./scripts/monitor.sh start
#   ./scripts/metashape/run_headless.sh dense
#   ./scripts/monitor.sh stop
#   ./scripts/monitor.sh summary
#
# The loggers are lightweight (~5 s interval) and survive your SSH session
# because they are disowned.  Stop them explicitly when the run finishes —
# they will otherwise sample quietly while the instance idles.
set -euo pipefail

LOGDIR="/data/edr_work/logs"
INTERVAL=5                       # seconds between samples
PIDFILE="$LOGDIR/.monitor_pids"

# Thresholds for interpretive hints in summary output
VRAM_WARN_PCT=80    # flag if peak VRAM usage exceeds this % of total
SWAP_WARN_MB=100    # flag if peak swap exceeds this many MB

mkdir -p "$LOGDIR"

# ---------------------------------------------------------------------------
# _cpu_pct — CPU utilisation from /proc/stat diff over 0.5 s.
# Lighter than top -bn1, no risk of non-zero exit codes from top.
# Returns one decimal, e.g. "42.3".
# ---------------------------------------------------------------------------
_cpu_pct() {
    local s1 s2
    s1="$(awk '/^cpu /{t=0; for(i=2;i<=NF;i++) t+=$i; print t, $5+$6}' /proc/stat)"
    sleep 0.5
    s2="$(awk '/^cpu /{t=0; for(i=2;i<=NF;i++) t+=$i; print t, $5+$6}' /proc/stat)"
    awk -v a="$s1" -v b="$s2" 'BEGIN {
        split(a, A); split(b, B)
        dt = B[1]-A[1]; di = B[2]-A[2]
        printf "%.1f", dt > 0 ? 100*(dt-di)/dt : 0
    }'
}

# ---------------------------------------------------------------------------
start_monitors() {
    # Double-start guard: key off the CPU pid (line 2 of pidfile), which is
    # always written regardless of GPU availability.  Keying off line 1
    # (gpu_pid) would give a false "not running" on CPU-only instances.
    if [[ -f "$PIDFILE" ]]; then
        local existing_cpu
        existing_cpu="$(awk 'NR==2' "$PIDFILE" 2>/dev/null || true)"
        if [[ -n "$existing_cpu" ]] && kill -0 "$existing_cpu" 2>/dev/null; then
            echo "Monitors already running (pidfile $PIDFILE). Run 'stop' first."
            exit 1
        fi
        echo "Stale pidfile found; cleaning up."
        rm -f "$PIDFILE"
    fi

    local stamp cpu_log gpu_log gpu_pid
    stamp="$(date +%Y%m%d_%H%M%S)"
    cpu_log="$LOGDIR/cpumem_${stamp}.csv"
    gpu_log=""
    gpu_pid=""

    # --- GPU logger -----------------------------------------------------------
    # nvidia-smi's own -l loop produces clean rows at a fixed interval;
    # nounits strips the "%" and "MiB" suffixes so awk arithmetic is trivial.
    if command -v nvidia-smi >/dev/null 2>&1; then
        gpu_log="$LOGDIR/gpu_${stamp}.csv"
        echo "timestamp,gpu_util_pct,mem_util_pct,mem_used_MB,mem_total_MB" > "$gpu_log"
        nvidia-smi \
            --query-gpu=timestamp,utilization.gpu,utilization.memory,memory.used,memory.total \
            --format=csv,noheader,nounits -l "$INTERVAL" >> "$gpu_log" 2>/dev/null &
        gpu_pid=$!
        disown "$gpu_pid"
    else
        echo "WARNING: nvidia-smi not found; GPU will not be logged."
    fi

    # --- CPU/RAM logger -------------------------------------------------------
    echo "timestamp,cpu_util_pct,mem_used_MB,mem_total_MB,swap_used_MB" > "$cpu_log"
    (
        # set +e: a single transient failure (e.g. awk on a torn /proc/stat read)
        # must not silently kill the logger for the rest of the run.
        set +e
        while true; do
            local ts cpu mem_used mem_total swap_used
            ts="$(date '+%Y/%m/%d %H:%M:%S')"         || ts="unknown"
            cpu="$(_cpu_pct)"                          || cpu="0"
            read -r mem_used mem_total \
                < <(free -m | awk '/^Mem:/ {print $3, $2}') \
                || { mem_used=0; mem_total=0; }
            swap_used="$(free -m | awk '/^Swap:/ {print $3}')" || swap_used="0"
            echo "${ts},${cpu},${mem_used},${mem_total},${swap_used}" >> "$cpu_log"
            # _cpu_pct already sleeps 0.5 s; subtract that to keep ~INTERVAL cadence.
            sleep "$(( INTERVAL - 1 ))"
        done
    ) &
    local cpu_pid=$!
    disown "$cpu_pid"

    # Pidfile layout (one item per line; gpu entries may be empty on CPU-only hosts):
    #   1: gpu_pid
    #   2: cpu_pid
    #   3: gpu_log path
    #   4: cpu_log path
    printf '%s\n%s\n%s\n%s\n' "$gpu_pid" "$cpu_pid" "$gpu_log" "$cpu_log" > "$PIDFILE"

    echo "Monitors started (interval ${INTERVAL} s)."
    [[ -n "$gpu_log" ]] && echo "  GPU log    : $gpu_log"
    echo "  CPU/RAM log: $cpu_log"
    echo "Stop with: $0 stop"
}

# ---------------------------------------------------------------------------
stop_monitors() {
    if [[ ! -f "$PIDFILE" ]]; then
        echo "No pidfile found; monitors don't appear to be running."
        exit 0
    fi

    local gpu_pid cpu_pid gpu_log cpu_log
    gpu_pid="$(awk 'NR==1' "$PIDFILE")"
    cpu_pid="$(awk 'NR==2' "$PIDFILE")"
    gpu_log="$(awk 'NR==3' "$PIDFILE")"
    cpu_log="$(awk 'NR==4' "$PIDFILE")"

    for pid in "$gpu_pid" "$cpu_pid"; do
        [[ -z "$pid" ]] && continue
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null && echo "Stopped pid $pid." || true
        else
            echo "pid $pid was already gone."
        fi
    done

    rm -f "$PIDFILE"
    echo "Monitors stopped."
    [[ -n "$gpu_log" ]] && echo "  GPU log    : $gpu_log"
    [[ -n "$cpu_log" ]] && echo "  CPU/RAM log: $cpu_log"
    echo "Run '$0 summary' to see peaks."
}

# ---------------------------------------------------------------------------
status_monitors() {
    if [[ ! -f "$PIDFILE" ]]; then
        echo "Monitors not running."
        return 0
    fi

    local gpu_pid cpu_pid
    gpu_pid="$(awk 'NR==1' "$PIDFILE")"
    cpu_pid="$(awk 'NR==2' "$PIDFILE")"

    local cpu_alive=false
    [[ -n "$cpu_pid" ]] && kill -0 "$cpu_pid" 2>/dev/null && cpu_alive=true

    if $cpu_alive; then
        echo "Monitors RUNNING."
        if [[ -n "$gpu_pid" ]] && kill -0 "$gpu_pid" 2>/dev/null; then
            echo "  GPU logger : pid $gpu_pid"
        else
            echo "  GPU logger : not running (no GPU or exited)"
        fi
        echo "  CPU logger : pid $cpu_pid"
        awk 'NR==3 && NF {print "  GPU log    : "$0} NR==4 && NF {print "  CPU/RAM log: "$0}' "$PIDFILE"
    else
        echo "Monitors not running (stale pidfile; run 'stop' to clean up)."
    fi
}

# ---------------------------------------------------------------------------
tail_logs() {
    local gpu_log cpu_log
    gpu_log="$(ls -t "$LOGDIR"/gpu_*.csv 2>/dev/null | head -1 || true)"
    cpu_log="$(ls -t "$LOGDIR"/cpumem_*.csv 2>/dev/null | head -1 || true)"

    if [[ -z "$gpu_log" && -z "$cpu_log" ]]; then
        echo "No log files found in $LOGDIR."
        exit 1
    fi

    local files=()
    [[ -n "$gpu_log"  ]] && files+=("$gpu_log")
    [[ -n "$cpu_log"  ]] && files+=("$cpu_log")

    echo "Tailing ${#files[@]} log(s) — Ctrl-C to stop."
    tail -f "${files[@]}"
}

# ---------------------------------------------------------------------------
list_logs() {
    echo "Log files in $LOGDIR:"
    ls -lh "$LOGDIR"/*.csv 2>/dev/null \
        | awk '{printf "  %-8s  %s\n", $5, $NF}' \
        || echo "  (none found)"
}

# ---------------------------------------------------------------------------
summary() {
    local gpu_log cpu_log
    gpu_log="$(ls -t "$LOGDIR"/gpu_*.csv 2>/dev/null | head -1 || true)"
    cpu_log="$(ls -t "$LOGDIR"/cpumem_*.csv 2>/dev/null | head -1 || true)"

    echo "=== Resource summary (right-sizing evidence) ==="
    echo "Note: smoke test (325 imgs) under-stresses VRAM vs full EDR_T1 (2424 imgs)."
    echo "Size off a FULL-transect run for a real instance decision."
    echo ""

    if [[ -n "$gpu_log" && -s "$gpu_log" ]]; then
        echo "GPU  ($gpu_log):"
        # nvidia-smi csv fields have leading spaces; gsub strips them before arithmetic.
        awk -F',' -v vram_warn="$VRAM_WARN_PCT" '
        NR>1 {
            for (i=1; i<=NF; i++) gsub(/^ +| +$/, "", $i)
            g = $2+0; if (g > maxg) maxg = g; sumg += g; n++
            m = $4+0; if (m > maxmem) maxmem = m
            tot = $5+0
        }
        END {
            if (n == 0) { print "  (no data rows)"; exit }
            pct = tot > 0 ? 100*maxmem/tot : 0
            printf "  peak GPU util  : %d%%\n",   maxg
            printf "  mean GPU util  : %.0f%%\n",  sumg/n
            printf "  peak VRAM used : %d MB of %d MB (%.0f%%)\n", maxmem, tot, pct
            printf "  samples        : %d\n", n
            print ""
            if (pct >= vram_warn)
                printf "  !! VRAM near capacity (%.0f%%) — consider a larger-memory GPU for the full run.\n", pct
            else
                printf "  VRAM headroom OK (%.0f%% used; warn threshold %d%%).\n", pct, vram_warn
            avg = sumg/n
            if (avg >= 90)
                print "  GPU-bound (sustained ~100%) — a faster GPU cuts wall time."
            else if (maxg < 50)
                print "  GPU lightly loaded — pipeline may be CPU- or I/O-bound during this stage."
        }' "$gpu_log"
    else
        echo "GPU: (no log found)"
    fi

    echo ""

    if [[ -n "$cpu_log" && -s "$cpu_log" ]]; then
        echo "CPU/RAM ($cpu_log):"
        awk -F',' -v swap_warn="$SWAP_WARN_MB" '
        NR>1 {
            c = $2+0; if (c > maxc) maxc = c; sumc += c; n++
            m = $3+0; if (m > maxmem) maxmem = m
            tot = $4+0
            s = $5+0; if (s > maxswap) maxswap = s
        }
        END {
            if (n == 0) { print "  (no data rows)"; exit }
            pct = tot > 0 ? 100*maxmem/tot : 0
            printf "  peak CPU util  : %.0f%%\n",  maxc
            printf "  mean CPU util  : %.0f%%\n",  sumc/n
            printf "  peak RAM used  : %d MB of %d MB (%.0f%%)\n", maxmem, tot, pct
            printf "  peak swap used : %d MB\n", maxswap
            printf "  samples        : %d\n", n
            print ""
            if (pct >= 85)
                printf "  !! RAM near capacity (%.0f%%) — increase instance RAM.\n", pct
            else
                printf "  RAM headroom OK (%.0f%% used).\n", pct
            if (maxswap >= swap_warn)
                printf "  !! Swap in use (%d MB peak) — RAM pressure; increase instance RAM.\n", maxswap
        }' "$cpu_log"
    else
        echo "CPU/RAM: (no log found)"
    fi
    echo ""
}

# ---------------------------------------------------------------------------
case "${1:-}" in
    start)   start_monitors ;;
    stop)    stop_monitors ;;
    status)  status_monitors ;;
    summary) summary ;;
    tail)    tail_logs ;;
    logs)    list_logs ;;
    *)
        echo "Usage: $0 {start|stop|status|summary|tail|logs}"
        exit 1
        ;;
esac
