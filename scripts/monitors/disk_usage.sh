#!/usr/bin/env bash
# disk_usage.sh — Disk Usage Threshold
# Exit 0=ok, 1=warning, 2=critical
# Env: WARN_PCT, CRIT_PCT, EXCLUDE_FS, INCLUDE_MOUNTS

WARN_PCT="${WARN_PCT:-80}"
CRIT_PCT="${CRIT_PCT:-90}"
EXCLUDE_FS="${EXCLUDE_FS:-tmpfs|devtmpfs|squashfs|overlay|aufs}"
INCLUDE_MOUNTS="${INCLUDE_MOUNTS:-}"

if ! command -v df &>/dev/null; then
    echo '{"status":"error","message":"df command not found","value":null}'
    exit 2
fi

worst_pct=0
worst_mount=""
worst_fs=""
mounts_json=""
overall_status="ok"

while IFS= read -r line; do
    # Fields: Filesystem Type Size Used Avail Use% Mounted
    fstype=$(echo "$line" | awk '{print $2}')
    mount=$(echo "$line" | awk '{print $7}')
    use_raw=$(echo "$line" | awk '{print $6}')
    use_pct="${use_raw//%/}"
    filesystem=$(echo "$line" | awk '{print $1}')

    # Skip header or lines without numeric use%
    if ! [[ "$use_pct" =~ ^[0-9]+$ ]]; then
        continue
    fi

    # Exclude by filesystem type
    if echo "$fstype" | grep -qE "^(${EXCLUDE_FS})$"; then
        continue
    fi

    # Filter to included mounts if specified
    if [[ -n "$INCLUDE_MOUNTS" ]]; then
        match=0
        IFS=',' read -ra wanted <<< "$INCLUDE_MOUNTS"
        for w in "${wanted[@]}"; do
            if [[ "$mount" == "$w" ]]; then
                match=1
                break
            fi
        done
        [[ "$match" -eq 0 ]] && continue
    fi

    # Determine per-mount status
    mount_status="ok"
    if [[ "$use_pct" -ge "$CRIT_PCT" ]]; then
        mount_status="critical"
        overall_status="critical"
    elif [[ "$use_pct" -ge "$WARN_PCT" ]]; then
        mount_status="warning"
        [[ "$overall_status" != "critical" ]] && overall_status="warning"
    fi

    if [[ "$use_pct" -ge "$worst_pct" ]]; then
        worst_pct="$use_pct"
        worst_mount="$mount"
        worst_fs="$filesystem"
    fi

    entry="{\"mount\":\"${mount}\",\"filesystem\":\"${filesystem}\",\"type\":\"${fstype}\",\"used_pct\":${use_pct},\"status\":\"${mount_status}\"}"
    if [[ -n "$mounts_json" ]]; then
        mounts_json="${mounts_json},${entry}"
    else
        mounts_json="${entry}"
    fi
done < <(df -PT 2>/dev/null | tail -n +2)

if [[ -z "$mounts_json" ]]; then
    echo '{"status":"error","message":"No mountpoints matched criteria","value":null}'
    exit 2
fi

case "$overall_status" in
    critical)
        msg="CRITICAL: ${worst_mount} (${worst_fs}) at ${worst_pct}% used"
        exit_code=2
        ;;
    warning)
        msg="WARNING: ${worst_mount} (${worst_fs}) at ${worst_pct}% used"
        exit_code=1
        ;;
    *)
        msg="All disks OK — highest usage ${worst_pct}% on ${worst_mount}"
        exit_code=0
        ;;
esac

echo "{\"status\":\"${overall_status}\",\"message\":\"${msg}\",\"value\":{\"max_used_pct\":${worst_pct},\"worst_mount\":\"${worst_mount}\",\"mounts\":[${mounts_json}]}}"
exit "$exit_code"
