#!/usr/bin/env bash
# tcp_port_listening.sh — TCP Port Listening Check
# Exit 0=ok, 2=critical (any port not listening)
# Env: PORTS, BIND_ADDR

PORTS="${PORTS:-22}"
BIND_ADDR="${BIND_ADDR:-}"

# Choose between ss and netstat
if command -v ss &>/dev/null; then
    use_ss=1
elif command -v netstat &>/dev/null; then
    use_ss=0
else
    echo '{"status":"error","message":"Neither ss nor netstat found","value":null}'
    exit 2
fi

get_listening_addrs() {
    local port="$1"
    if [[ "$use_ss" -eq 1 ]]; then
        ss -ltnH "sport = :${port}" 2>/dev/null | awk '{print $4}'
    else
        netstat -ltn 2>/dev/null | awk -v p=":${port}" '$4 ~ p"$" {print $4}'
    fi
}

ports_json=""
overall_status="ok"
not_listening=""

IFS=',' read -ra port_list <<< "$PORTS"

for port in "${port_list[@]}"; do
    port="${port// /}"
    [[ -z "$port" ]] && continue

    # Validate numeric port
    if ! [[ "$port" =~ ^[0-9]+$ ]] || [[ "$port" -lt 1 || "$port" -gt 65535 ]]; then
        entry="{\"port\":\"${port}\",\"listening\":false,\"bind\":null,\"status\":\"error\",\"message\":\"Invalid port number\"}"
        if [[ -n "$ports_json" ]]; then ports_json="${ports_json},${entry}"; else ports_json="${entry}"; fi
        overall_status="critical"
        continue
    fi

    listening_addrs=$(get_listening_addrs "$port")
    is_listening=false
    matched_bind=""

    if [[ -n "$listening_addrs" ]]; then
        if [[ -z "$BIND_ADDR" ]]; then
            is_listening=true
            matched_bind=$(echo "$listening_addrs" | head -1)
        else
            # Check if the desired bind address is in the list
            while IFS= read -r addr; do
                addr_host="${addr%:*}"
                if [[ "$addr_host" == "$BIND_ADDR" || "$addr_host" == "0.0.0.0" || "$addr_host" == "::" || "$addr_host" == "*" ]]; then
                    is_listening=true
                    matched_bind="$addr"
                    break
                fi
            done <<< "$listening_addrs"
        fi
    fi

    if [[ "$is_listening" == "true" ]]; then
        port_status="ok"
        port_msg="Port ${port} is listening on ${matched_bind}"
    else
        port_status="critical"
        port_msg="Port ${port} is NOT listening"
        overall_status="critical"
        not_listening="${not_listening:+${not_listening}, }${port}"
    fi

    bind_val="null"
    [[ -n "$matched_bind" ]] && bind_val="\"${matched_bind}\""

    entry="{\"port\":${port},\"listening\":${is_listening},\"bind\":${bind_val},\"status\":\"${port_status}\",\"message\":\"${port_msg}\"}"
    if [[ -n "$ports_json" ]]; then ports_json="${ports_json},${entry}"; else ports_json="${entry}"; fi
done

if [[ -z "$ports_json" ]]; then
    echo '{"status":"error","message":"No valid ports specified","value":null}'
    exit 2
fi

if [[ "$overall_status" == "critical" ]]; then
    msg="CRITICAL: Ports not listening — ${not_listening}"
    exit_code=2
else
    msg="All ports listening OK"
    exit_code=0
fi

echo "{\"status\":\"${overall_status}\",\"message\":\"${msg}\",\"value\":{\"ports\":[${ports_json}]}}"
exit "$exit_code"
