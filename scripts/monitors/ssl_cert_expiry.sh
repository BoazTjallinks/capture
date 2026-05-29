#!/usr/bin/env bash
# ssl_cert_expiry.sh — SSL Certificate Expiry via openssl s_client
# Exit 0=ok, 1=warning, 2=critical
# Env: HOST, PORT, WARN_DAYS, CRIT_DAYS, STARTTLS

HOST="${HOST:-example.com}"
PORT="${PORT:-443}"
WARN_DAYS="${WARN_DAYS:-30}"
CRIT_DAYS="${CRIT_DAYS:-7}"
STARTTLS="${STARTTLS:-}"

if ! command -v openssl &>/dev/null; then
    echo '{"status":"error","message":"openssl not found","value":null}'
    exit 2
fi

# Build s_client command
starttls_args=()
if [[ -n "$STARTTLS" ]]; then
    starttls_args=(-starttls "$STARTTLS")
fi

# Fetch the certificate; timeout after 10 seconds
cert_output=$(echo "" | timeout 10 openssl s_client \
    -connect "${HOST}:${PORT}" \
    -servername "$HOST" \
    "${starttls_args[@]}" \
    2>/dev/null) || true

if [[ -z "$cert_output" ]]; then
    echo "{\"status\":\"error\",\"message\":\"Could not connect to ${HOST}:${PORT}\",\"value\":null}"
    exit 2
fi

not_after=$(echo "$cert_output" | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)

if [[ -z "$not_after" ]]; then
    echo "{\"status\":\"error\",\"message\":\"Could not parse certificate from ${HOST}:${PORT}\",\"value\":null}"
    exit 2
fi

# Days remaining using date arithmetic
expiry_epoch=$(date -d "$not_after" +%s 2>/dev/null) || expiry_epoch=$(date -j -f "%b %d %T %Y %Z" "$not_after" +%s 2>/dev/null) || true

if [[ -z "$expiry_epoch" ]]; then
    echo "{\"status\":\"error\",\"message\":\"Could not parse certificate expiry date: ${not_after}\",\"value\":null}"
    exit 2
fi

now_epoch=$(date +%s)
days_remaining=$(( (expiry_epoch - now_epoch) / 86400 ))

# Sanitise not_after for JSON (remove double quotes if any)
not_after_clean="${not_after//\"/}"

if [[ "$days_remaining" -le "$CRIT_DAYS" ]]; then
    status="critical"
    msg="CRITICAL: SSL certificate for ${HOST} expires in ${days_remaining} day(s) (${not_after_clean})"
    exit_code=2
elif [[ "$days_remaining" -le "$WARN_DAYS" ]]; then
    status="warning"
    msg="WARNING: SSL certificate for ${HOST} expires in ${days_remaining} day(s) (${not_after_clean})"
    exit_code=1
else
    status="ok"
    msg="SSL certificate for ${HOST} OK — expires in ${days_remaining} day(s)"
    exit_code=0
fi

echo "{\"status\":\"${status}\",\"message\":\"${msg}\",\"value\":{\"host\":\"${HOST}\",\"port\":${PORT},\"days_remaining\":${days_remaining},\"not_after\":\"${not_after_clean}\"}}"
exit "$exit_code"
