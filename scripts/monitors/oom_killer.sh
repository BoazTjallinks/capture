#!/usr/bin/env bash
# oom_killer.sh — OOM Killer Activity
# Exit 0=ok, 1=warning, 2=critical
# Env: LOOKBACK_MINUTES, WARN_COUNT, CRIT_COUNT

LOOKBACK_MINUTES="${LOOKBACK_MINUTES:-60}"
WARN_COUNT="${WARN_COUNT:-1}"
CRIT_COUNT="${CRIT_COUNT:-3}"

# Collect OOM events — prefer journalctl (systemd), fall back to dmesg -T
oom_lines=""

if command -v journalctl &>/dev/null; then
    oom_lines=$(journalctl -k --since "${LOOKBACK_MINUTES} minutes ago" 2>/dev/null \
        | grep -iE "oom.kill|killed process|out of memory" || true)
fi

# Fallback or supplement with dmesg if journalctl yielded nothing
if [[ -z "$oom_lines" ]] && command -v dmesg &>/dev/null; then
    # dmesg -T requires kernel >= 3.5; suppress error on older kernels
    raw_dmesg=$(dmesg -T 2>/dev/null || dmesg 2>/dev/null || true)
    if [[ -n "$raw_dmesg" ]]; then
        # Filter only recent entries by matching timestamp if possible,
        # otherwise take all OOM lines (conservative — may include old events)
        oom_lines=$(echo "$raw_dmesg" | grep -iE "oom.kill|killed process|out of memory" || true)
    fi
fi

# Count unique kill events (lines containing "Killed process")
oom_count=0
last_victim=""

if [[ -n "$oom_lines" ]]; then
    # Count lines that represent actual kills
    oom_count=$(echo "$oom_lines" | grep -ic "killed process" || true)
    if ! [[ "$oom_count" =~ ^[0-9]+$ ]]; then
        oom_count=0
    fi

    # Extract most recent victim (last matching line)
    last_line=$(echo "$oom_lines" | grep -i "killed process" | tail -1 || true)
    if [[ -n "$last_line" ]]; then
        # Try to extract process name from "Killed process NNN (name)"
        victim=$(echo "$last_line" | grep -oP 'Killed process \d+ \(\K[^)]+' 2>/dev/null || \
                 echo "$last_line" | sed 's/.*Killed process [0-9]* (\([^)]*\)).*/\1/' 2>/dev/null || true)
        last_victim="${victim:-unknown}"
    fi
fi

if [[ "$oom_count" -ge "$CRIT_COUNT" ]]; then
    status="critical"
    msg="CRITICAL: ${oom_count} OOM kill event(s) in last ${LOOKBACK_MINUTES} minute(s) — last victim: ${last_victim:-none}"
    exit_code=2
elif [[ "$oom_count" -ge "$WARN_COUNT" ]]; then
    status="warning"
    msg="WARNING: ${oom_count} OOM kill event(s) in last ${LOOKBACK_MINUTES} minute(s) — last victim: ${last_victim:-none}"
    exit_code=1
else
    status="ok"
    msg="No OOM kill events in last ${LOOKBACK_MINUTES} minute(s)"
    exit_code=0
fi

last_victim_json="null"
[[ -n "$last_victim" ]] && last_victim_json="\"${last_victim}\""

echo "{\"status\":\"${status}\",\"message\":\"${msg}\",\"value\":{\"oom_count\":${oom_count},\"lookback_minutes\":${LOOKBACK_MINUTES},\"last_victim\":${last_victim_json}}}"
exit "$exit_code"
