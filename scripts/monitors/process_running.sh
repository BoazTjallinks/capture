#!/usr/bin/env bash
# process_running.sh — Process Running Check
# Exit 0=ok, 2=critical (below MIN_COUNT)
# Env: PROCESS_NAME, MIN_COUNT, MATCH_FULL

PROCESS_NAME="${PROCESS_NAME:-sshd}"
MIN_COUNT="${MIN_COUNT:-1}"
MATCH_FULL="${MATCH_FULL:-0}"

if ! command -v pgrep &>/dev/null; then
    echo '{"status":"error","message":"pgrep not found","value":null}'
    exit 2
fi

if [[ "$MATCH_FULL" == "1" ]]; then
    count=$(pgrep -cf "$PROCESS_NAME" 2>/dev/null || echo "0")
else
    count=$(pgrep -c "$PROCESS_NAME" 2>/dev/null || echo "0")
fi

# pgrep exits 1 when no processes found; the || echo "0" above handles that,
# but count may also be empty string in edge cases
if ! [[ "$count" =~ ^[0-9]+$ ]]; then
    count=0
fi

if [[ "$count" -ge "$MIN_COUNT" ]]; then
    status="ok"
    msg="Process '${PROCESS_NAME}' running (${count} instance(s))"
    exit_code=0
else
    status="critical"
    msg="CRITICAL: Process '${PROCESS_NAME}' not running — found ${count}, need ${MIN_COUNT}"
    exit_code=2
fi

echo "{\"status\":\"${status}\",\"message\":\"${msg}\",\"value\":{\"process\":\"${PROCESS_NAME}\",\"count\":${count},\"min_count\":${MIN_COUNT},\"match_full\":${MATCH_FULL}}}"
exit "$exit_code"
