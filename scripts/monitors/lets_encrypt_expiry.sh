#!/usr/bin/env bash
# lets_encrypt_expiry.sh — Let's Encrypt Certificate Expiry
# Exit 0=ok, 1=warning, 2=critical
# Env: LE_LIVE_DIR, WARN_DAYS, CRIT_DAYS, INCLUDE_DOMAINS

LE_LIVE_DIR="${LE_LIVE_DIR:-/etc/letsencrypt/live}"
WARN_DAYS="${WARN_DAYS:-20}"
CRIT_DAYS="${CRIT_DAYS:-7}"
INCLUDE_DOMAINS="${INCLUDE_DOMAINS:-}"

if ! command -v openssl &>/dev/null; then
    echo '{"status":"error","message":"openssl not found","value":null}'
    exit 2
fi

if [[ ! -d "$LE_LIVE_DIR" ]]; then
    echo "{\"status\":\"error\",\"message\":\"Let's Encrypt live directory not found: ${LE_LIVE_DIR}\",\"value\":null}"
    exit 2
fi

now_epoch=$(date +%s)
certs_json=""
overall_status="ok"
worst_days=999999
worst_domain=""

# Build inclusion set
declare -A include_set
if [[ -n "$INCLUDE_DOMAINS" ]]; then
    IFS=',' read -ra dom_list <<< "$INCLUDE_DOMAINS"
    for d in "${dom_list[@]}"; do
        d="${d// /}"
        include_set["$d"]=1
    done
fi

while IFS= read -r pem; do
    # Derive domain name from directory
    domain=$(basename "$(dirname "$pem")")

    # Apply domain filter
    if [[ -n "$INCLUDE_DOMAINS" ]] && [[ -z "${include_set[$domain]+x}" ]]; then
        continue
    fi

    if [[ ! -r "$pem" ]]; then
        entry="{\"domain\":\"${domain}\",\"days_remaining\":null,\"not_after\":null,\"status\":\"error\",\"message\":\"Certificate file not readable\"}"
        if [[ -n "$certs_json" ]]; then certs_json="${certs_json},${entry}"; else certs_json="${entry}"; fi
        overall_status="critical"
        continue
    fi

    not_after=$(openssl x509 -noout -enddate -in "$pem" 2>/dev/null | cut -d= -f2)
    if [[ -z "$not_after" ]]; then
        entry="{\"domain\":\"${domain}\",\"days_remaining\":null,\"not_after\":null,\"status\":\"error\",\"message\":\"Could not parse certificate\"}"
        if [[ -n "$certs_json" ]]; then certs_json="${certs_json},${entry}"; else certs_json="${entry}"; fi
        overall_status="critical"
        continue
    fi

    expiry_epoch=$(date -d "$not_after" +%s 2>/dev/null) || expiry_epoch=$(date -j -f "%b %d %T %Y %Z" "$not_after" +%s 2>/dev/null) || true

    if [[ -z "$expiry_epoch" ]]; then
        entry="{\"domain\":\"${domain}\",\"days_remaining\":null,\"not_after\":\"${not_after}\",\"status\":\"error\",\"message\":\"Could not parse expiry date\"}"
        if [[ -n "$certs_json" ]]; then certs_json="${certs_json},${entry}"; else certs_json="${entry}"; fi
        overall_status="critical"
        continue
    fi

    days_remaining=$(( (expiry_epoch - now_epoch) / 86400 ))
    not_after_clean="${not_after//\"/}"

    cert_status="ok"
    if [[ "$days_remaining" -le "$CRIT_DAYS" ]]; then
        cert_status="critical"
        overall_status="critical"
    elif [[ "$days_remaining" -le "$WARN_DAYS" ]]; then
        cert_status="warning"
        [[ "$overall_status" != "critical" ]] && overall_status="warning"
    fi

    if [[ "$days_remaining" -lt "$worst_days" ]]; then
        worst_days="$days_remaining"
        worst_domain="$domain"
    fi

    entry="{\"domain\":\"${domain}\",\"days_remaining\":${days_remaining},\"not_after\":\"${not_after_clean}\",\"status\":\"${cert_status}\"}"
    if [[ -n "$certs_json" ]]; then certs_json="${certs_json},${entry}"; else certs_json="${entry}"; fi

done < <(find "$LE_LIVE_DIR" -name "fullchain.pem" 2>/dev/null | sort)

if [[ -z "$certs_json" ]]; then
    echo "{\"status\":\"error\",\"message\":\"No Let's Encrypt certificates found in ${LE_LIVE_DIR}\",\"value\":null}"
    exit 2
fi

case "$overall_status" in
    critical)
        msg="CRITICAL: Certificate for ${worst_domain} expires in ${worst_days} day(s)"
        exit_code=2
        ;;
    warning)
        msg="WARNING: Certificate for ${worst_domain} expires in ${worst_days} day(s)"
        exit_code=1
        ;;
    *)
        msg="All Let's Encrypt certificates OK — soonest expiry in ${worst_days} day(s) (${worst_domain})"
        exit_code=0
        ;;
esac

echo "{\"status\":\"${overall_status}\",\"message\":\"${msg}\",\"value\":{\"certs\":[${certs_json}]}}"
exit "$exit_code"
