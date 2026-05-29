#!/usr/bin/env bash
# systemd_service.sh — Systemd Service Status
# Exit 0=ok, 1=warning (degraded/inactive), 2=critical (failed)
# Env: SERVICES, REQUIRE_ENABLED

SERVICES="${SERVICES:-ssh.service}"
REQUIRE_ENABLED="${REQUIRE_ENABLED:-0}"

if ! command -v systemctl &>/dev/null; then
    echo '{"status":"error","message":"systemctl not found — not a systemd system","value":null}'
    exit 2
fi

services_json=""
overall_status="ok"
failed_names=""
inactive_names=""

IFS=',' read -ra svc_list <<< "$SERVICES"

for svc in "${svc_list[@]}"; do
    svc="${svc// /}"  # trim spaces
    [[ -z "$svc" ]] && continue

    active_state=$(systemctl is-active "$svc" 2>/dev/null || true)
    failed_state=$(systemctl is-failed "$svc" 2>/dev/null || true)

    enabled_state="n/a"
    if [[ "$REQUIRE_ENABLED" == "1" ]]; then
        enabled_state=$(systemctl is-enabled "$svc" 2>/dev/null || echo "unknown")
    fi

    svc_status="ok"
    svc_msg=""

    if [[ "$failed_state" == "failed" ]]; then
        svc_status="critical"
        svc_msg="Service is in failed state"
        overall_status="critical"
        failed_names="${failed_names:+${failed_names}, }${svc}"
    elif [[ "$active_state" != "active" ]]; then
        svc_status="warning"
        svc_msg="Service is ${active_state}"
        [[ "$overall_status" != "critical" ]] && overall_status="warning"
        inactive_names="${inactive_names:+${inactive_names}, }${svc}"
    elif [[ "$REQUIRE_ENABLED" == "1" && "$enabled_state" != "enabled" ]]; then
        svc_status="warning"
        svc_msg="Service is active but not enabled (${enabled_state})"
        [[ "$overall_status" != "critical" ]] && overall_status="warning"
        inactive_names="${inactive_names:+${inactive_names}, }${svc}"
    else
        svc_msg="Service is running"
    fi

    entry="{\"service\":\"${svc}\",\"active\":\"${active_state}\",\"failed\":\"${failed_state}\",\"enabled\":\"${enabled_state}\",\"status\":\"${svc_status}\",\"message\":\"${svc_msg}\"}"
    if [[ -n "$services_json" ]]; then
        services_json="${services_json},${entry}"
    else
        services_json="${entry}"
    fi
done

if [[ -z "$services_json" ]]; then
    echo '{"status":"error","message":"No services specified","value":null}'
    exit 2
fi

case "$overall_status" in
    critical)
        msg="CRITICAL: Failed services — ${failed_names}"
        exit_code=2
        ;;
    warning)
        msg="WARNING: Inactive/not-enabled services — ${inactive_names}"
        exit_code=1
        ;;
    *)
        msg="All services running OK"
        exit_code=0
        ;;
esac

echo "{\"status\":\"${overall_status}\",\"message\":\"${msg}\",\"value\":{\"services\":[${services_json}]}}"
exit "$exit_code"
