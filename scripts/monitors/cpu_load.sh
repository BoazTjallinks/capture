#!/usr/bin/env bash
# cpu_load.sh — CPU Load Average
# Exit 0=ok, 1=warning, 2=critical
# Env: WINDOW (1|5|15), WARN_PER_CORE, CRIT_PER_CORE

WINDOW="${WINDOW:-5}"
WARN_PER_CORE="${WARN_PER_CORE:-0.8}"
CRIT_PER_CORE="${CRIT_PER_CORE:-1.5}"

if [[ ! -r /proc/loadavg ]]; then
    echo '{"status":"error","message":"/proc/loadavg not readable","value":null}'
    exit 2
fi

if ! command -v nproc &>/dev/null; then
    echo '{"status":"error","message":"nproc not found","value":null}'
    exit 2
fi

read -r load_1 load_5 load_15 _ < /proc/loadavg
cores=$(nproc)

case "$WINDOW" in
    1)  load_val="$load_1" ;;
    15) load_val="$load_15" ;;
    *)  load_val="$load_5" ;;
esac

# Use awk for floating-point comparison
result=$(awk -v load="$load_val" -v cores="$cores" -v warn="$WARN_PER_CORE" -v crit="$CRIT_PER_CORE" '
BEGIN {
    per_core = load / cores
    if (per_core >= crit) {
        print "critical " per_core
    } else if (per_core >= warn) {
        print "warning " per_core
    } else {
        print "ok " per_core
    }
}')

status=$(echo "$result" | awk '{print $1}')
load_per_core=$(echo "$result" | awk '{printf "%.4f", $2}')

case "$status" in
    critical)
        msg="CRITICAL: Load per core ${load_per_core} (${load_val} over ${cores} core(s), window ${WINDOW}m)"
        exit_code=2
        ;;
    warning)
        msg="WARNING: Load per core ${load_per_core} (${load_val} over ${cores} core(s), window ${WINDOW}m)"
        exit_code=1
        ;;
    *)
        msg="CPU load OK — ${load_val} over ${cores} core(s) (${load_per_core} per core, window ${WINDOW}m)"
        exit_code=0
        ;;
esac

echo "{\"status\":\"${status}\",\"message\":\"${msg}\",\"value\":{\"load_1\":${load_1},\"load_5\":${load_5},\"load_15\":${load_15},\"cores\":${cores},\"window\":${WINDOW},\"load_per_core\":${load_per_core}}}"
exit "$exit_code"
