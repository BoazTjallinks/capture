#!/usr/bin/env bash
# memory_swap.sh — Memory & Swap Pressure
# Exit 0=ok, 1=warning, 2=critical
# Env: MEM_WARN_PCT, MEM_CRIT_PCT, SWAP_WARN_PCT, SWAP_CRIT_PCT

MEM_WARN_PCT="${MEM_WARN_PCT:-85}"
MEM_CRIT_PCT="${MEM_CRIT_PCT:-95}"
SWAP_WARN_PCT="${SWAP_WARN_PCT:-50}"
SWAP_CRIT_PCT="${SWAP_CRIT_PCT:-80}"

if [[ ! -r /proc/meminfo ]]; then
    echo '{"status":"error","message":"/proc/meminfo not readable","value":null}'
    exit 2
fi

mem_total=$(awk '/^MemTotal:/{print $2}' /proc/meminfo)
mem_available=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)
swap_total=$(awk '/^SwapTotal:/{print $2}' /proc/meminfo)
swap_free=$(awk '/^SwapFree:/{print $2}' /proc/meminfo)

if [[ -z "$mem_total" || "$mem_total" -eq 0 ]]; then
    echo '{"status":"error","message":"Could not read MemTotal from /proc/meminfo","value":null}'
    exit 2
fi

mem_used=$(( mem_total - mem_available ))
mem_used_pct=$(( mem_used * 100 / mem_total ))

# Swap
swap_used=0
swap_used_pct=0
swap_status="ok"
if [[ -n "$swap_total" && "$swap_total" -gt 0 ]]; then
    swap_used=$(( swap_total - swap_free ))
    swap_used_pct=$(( swap_used * 100 / swap_total ))
fi

# Convert kB to MB for human-readable output
mem_total_mb=$(( mem_total / 1024 ))
mem_used_mb=$(( mem_used / 1024 ))
swap_total_mb=$(( swap_total / 1024 ))
swap_used_mb=$(( swap_used / 1024 ))

# Determine per-resource status
mem_status="ok"
if [[ "$mem_used_pct" -ge "$MEM_CRIT_PCT" ]]; then
    mem_status="critical"
elif [[ "$mem_used_pct" -ge "$MEM_WARN_PCT" ]]; then
    mem_status="warning"
fi

if [[ "$swap_total" -gt 0 ]]; then
    if [[ "$swap_used_pct" -ge "$SWAP_CRIT_PCT" ]]; then
        swap_status="critical"
    elif [[ "$swap_used_pct" -ge "$SWAP_WARN_PCT" ]]; then
        swap_status="warning"
    fi
fi

# Overall status = worst of the two
overall_status="ok"
for s in "$mem_status" "$swap_status"; do
    if [[ "$s" == "critical" ]]; then
        overall_status="critical"
    elif [[ "$s" == "warning" && "$overall_status" != "critical" ]]; then
        overall_status="warning"
    fi
done

case "$overall_status" in
    critical)
        if [[ "$mem_status" == "critical" ]]; then
            msg="CRITICAL: Memory usage at ${mem_used_pct}% (${mem_used_mb}MB / ${mem_total_mb}MB)"
        else
            msg="CRITICAL: Swap usage at ${swap_used_pct}% (${swap_used_mb}MB / ${swap_total_mb}MB)"
        fi
        exit_code=2
        ;;
    warning)
        if [[ "$mem_status" == "warning" ]]; then
            msg="WARNING: Memory usage at ${mem_used_pct}% (${mem_used_mb}MB / ${mem_total_mb}MB)"
        else
            msg="WARNING: Swap usage at ${swap_used_pct}% (${swap_used_mb}MB / ${swap_total_mb}MB)"
        fi
        exit_code=1
        ;;
    *)
        msg="Memory OK (${mem_used_pct}% used), Swap OK (${swap_used_pct}% used)"
        exit_code=0
        ;;
esac

echo "{\"status\":\"${overall_status}\",\"message\":\"${msg}\",\"value\":{\"mem_total_mb\":${mem_total_mb},\"mem_used_mb\":${mem_used_mb},\"mem_used_pct\":${mem_used_pct},\"mem_status\":\"${mem_status}\",\"swap_total_mb\":${swap_total_mb},\"swap_used_mb\":${swap_used_mb},\"swap_used_pct\":${swap_used_pct},\"swap_status\":\"${swap_status}\"}}"
exit "$exit_code"
