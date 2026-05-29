#!/usr/bin/env bash
# inode_usage.sh — Inode Exhaustion Check
# Exit 0=ok, 1=warning, 2=critical
# Env: WARN_PCT, CRIT_PCT, EXCLUDE_FS

WARN_PCT="${WARN_PCT:-85}"
CRIT_PCT="${CRIT_PCT:-95}"
EXCLUDE_FS="${EXCLUDE_FS:-tmpfs|devtmpfs|squashfs|overlay}"

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
    # Fields: Filesystem Type Inodes IUsed IFree IUse% Mounted
    fstype=$(echo "$line" | awk '{print $2}')
    mount=$(echo "$line" | awk '{print $7}')
    iuse_raw=$(echo "$line" | awk '{print $6}')
    iuse_pct="${iuse_raw//%/}"
    filesystem=$(echo "$line" | awk '{print $1}')
    iused=$(echo "$line" | awk '{print $4}')
    ifree=$(echo "$line" | awk '{print $5}')
    inodes=$(echo "$line" | awk '{print $3}')

    if ! [[ "$iuse_pct" =~ ^[0-9]+$ ]]; then
        continue
    fi

    if echo "$fstype" | grep -qE "^(${EXCLUDE_FS})$"; then
        continue
    fi

    # Skip filesystems reporting 0 inodes (e.g. FAT)
    if [[ "$inodes" == "0" || "$inodes" == "-" ]]; then
        continue
    fi

    mount_status="ok"
    if [[ "$iuse_pct" -ge "$CRIT_PCT" ]]; then
        mount_status="critical"
        overall_status="critical"
    elif [[ "$iuse_pct" -ge "$WARN_PCT" ]]; then
        mount_status="warning"
        [[ "$overall_status" != "critical" ]] && overall_status="warning"
    fi

    if [[ "$iuse_pct" -ge "$worst_pct" ]]; then
        worst_pct="$iuse_pct"
        worst_mount="$mount"
        worst_fs="$filesystem"
    fi

    entry="{\"mount\":\"${mount}\",\"filesystem\":\"${filesystem}\",\"type\":\"${fstype}\",\"inodes\":\"${inodes}\",\"iused\":\"${iused}\",\"ifree\":\"${ifree}\",\"iuse_pct\":${iuse_pct},\"status\":\"${mount_status}\"}"
    if [[ -n "$mounts_json" ]]; then
        mounts_json="${mounts_json},${entry}"
    else
        mounts_json="${entry}"
    fi
done < <(df -PTi 2>/dev/null | tail -n +2)

if [[ -z "$mounts_json" ]]; then
    echo '{"status":"error","message":"No mountpoints matched criteria or inodes not supported","value":null}'
    exit 2
fi

case "$overall_status" in
    critical)
        msg="CRITICAL: ${worst_mount} (${worst_fs}) inode usage at ${worst_pct}%"
        exit_code=2
        ;;
    warning)
        msg="WARNING: ${worst_mount} (${worst_fs}) inode usage at ${worst_pct}%"
        exit_code=1
        ;;
    *)
        msg="All inodes OK — highest usage ${worst_pct}% on ${worst_mount}"
        exit_code=0
        ;;
esac

echo "{\"status\":\"${overall_status}\",\"message\":\"${msg}\",\"value\":{\"max_iuse_pct\":${worst_pct},\"worst_mount\":\"${worst_mount}\",\"mounts\":[${mounts_json}]}}"
exit "$exit_code"
