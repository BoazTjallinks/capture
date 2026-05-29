#!/usr/bin/env python3
# backup_age.py — Backup File Age
# Exit 0=ok, 1=warning, 2=error
# Env: BACKUP_PATH, WARN_HOURS, CRIT_HOURS, MIN_SIZE_BYTES

import glob
import json
import os
import sys
import time


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _out(status: str, message: str, value=None) -> None:
    print(json.dumps({"status": status, "message": message, "value": value}))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    backup_pattern = os.environ.get("BACKUP_PATH", "/var/backups/latest.tar.gz")
    warn_hours = float(os.environ.get("WARN_HOURS", "26"))
    crit_hours = float(os.environ.get("CRIT_HOURS", "48"))
    min_size_bytes = int(os.environ.get("MIN_SIZE_BYTES", "1024"))

    # Glob expand — supports patterns like /backups/*.tar.gz
    candidates = glob.glob(backup_pattern)

    if not candidates:
        _out(
            "error",
            f"No backup files found matching '{backup_pattern}'",
            {"path_pattern": backup_pattern},
        )
        sys.exit(2)

    # Find the newest file by mtime
    newest_path: str | None = None
    newest_mtime: float = -1.0

    for path in candidates:
        try:
            st = os.stat(path)
        except FileNotFoundError:
            continue  # race condition — file disappeared after glob
        except PermissionError:
            _out("error", f"Permission denied accessing: {path}", {"path": path})
            sys.exit(2)
        except OSError as exc:
            _out("error", f"Cannot stat '{path}': {exc}", {"path": path})
            sys.exit(2)

        if st.st_mtime > newest_mtime:
            newest_mtime = st.st_mtime
            newest_path = path
            newest_size = st.st_size

    if newest_path is None:
        _out(
            "error",
            f"Could not stat any backup files matching '{backup_pattern}'",
            {"path_pattern": backup_pattern},
        )
        sys.exit(2)

    now = time.time()
    age_seconds = now - newest_mtime
    age_hours = age_seconds / 3600.0
    age_hours_rounded = round(age_hours, 2)

    value = {
        "file_path": newest_path,
        "age_hours": age_hours_rounded,
        "size_bytes": newest_size,
        "mtime_epoch": int(newest_mtime),
        "files_found": len(candidates),
    }

    # --- Size check ---
    if newest_size < min_size_bytes:
        _out(
            "error",
            (
                f"Backup file too small: {newest_path} is {newest_size} bytes "
                f"(minimum {min_size_bytes} bytes)"
            ),
            value,
        )
        sys.exit(2)

    # --- Age check (critical takes priority) ---
    if age_hours >= crit_hours:
        _out(
            "error",
            (
                f"Backup critically old: {newest_path} is {age_hours_rounded}h old "
                f"(threshold {crit_hours}h)"
            ),
            value,
        )
        sys.exit(2)

    if age_hours >= warn_hours:
        _out(
            "warning",
            (
                f"Backup may be stale: {newest_path} is {age_hours_rounded}h old "
                f"(threshold {warn_hours}h)"
            ),
            value,
        )
        sys.exit(1)

    _out(
        "ok",
        f"Backup OK: {newest_path} is {age_hours_rounded}h old, {newest_size} bytes",
        value,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
