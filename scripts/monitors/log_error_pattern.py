#!/usr/bin/env python3
# log_error_pattern.py — Log File Error Pattern
# Exit 0=ok, 1=warning, 2=error
# Env: LOG_PATH, TAIL_LINES, ERROR_REGEX, IGNORE_REGEX, WARN_COUNT, CRIT_COUNT

import glob
import json
import os
import re
import sys


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _out(status: str, message: str, value=None) -> None:
    print(json.dumps({"status": status, "message": message, "value": value}))


# ---------------------------------------------------------------------------
# Efficient tail implementation
# Reads the file from the end in 8 KB chunks to retrieve the last N lines.
# Works on any seekable file and avoids loading the whole file into memory.
# ---------------------------------------------------------------------------

CHUNK_SIZE = 8192


def tail_lines(path: str, n: int) -> list[str]:
    """Return the last *n* lines of *path* without reading the whole file."""
    with open(path, "rb") as fh:
        fh.seek(0, 2)  # seek to end
        file_size = fh.tell()

        if file_size == 0:
            return []

        buf = bytearray()
        pos = file_size
        lines_found = 0

        while pos > 0 and lines_found <= n:
            read_size = min(CHUNK_SIZE, pos)
            pos -= read_size
            fh.seek(pos)
            chunk = fh.read(read_size)
            buf = bytearray(chunk) + buf
            lines_found = buf.count(b"\n")

        # Decode and split; the first element may be a partial line — drop it
        # unless we read the entire file
        text = buf.decode("utf-8", errors="replace")
        all_lines = text.splitlines()

        if pos > 0:
            # We didn't reach the start of the file: first entry may be partial
            all_lines = all_lines[1:]

        return all_lines[-n:] if len(all_lines) > n else all_lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log_path_pattern = os.environ.get("LOG_PATH", "/var/log/syslog")
    tail_n = int(os.environ.get("TAIL_LINES", "500"))
    error_pattern = os.environ.get("ERROR_REGEX", r"(?i)\b(error|fatal|panic|traceback)\b")
    ignore_pattern = os.environ.get("IGNORE_REGEX", "").strip()
    warn_count = int(os.environ.get("WARN_COUNT", "1"))
    crit_count = int(os.environ.get("CRIT_COUNT", "10"))

    # Compile regexes
    try:
        error_re = re.compile(error_pattern)
    except re.error as exc:
        _out("error", f"Invalid ERROR_REGEX: {exc}", None)
        sys.exit(2)

    ignore_re = None
    if ignore_pattern:
        try:
            ignore_re = re.compile(ignore_pattern)
        except re.error as exc:
            _out("error", f"Invalid IGNORE_REGEX: {exc}", None)
            sys.exit(2)

    # Glob expand to support patterns like /var/log/app/*.log
    matched_paths = sorted(glob.glob(log_path_pattern))
    if not matched_paths:
        _out("error", f"No files found matching '{log_path_pattern}'", {"path_pattern": log_path_pattern})
        sys.exit(2)

    # If multiple files matched pick the most recently modified one;
    # this handles patterns like /var/log/app/app.log* where the live log
    # is the one without a rotation suffix.
    if len(matched_paths) > 1:
        matched_paths = sorted(matched_paths, key=lambda p: os.path.getmtime(p), reverse=True)

    log_file = matched_paths[0]

    try:
        lines = tail_lines(log_file, tail_n)
    except FileNotFoundError:
        _out("error", f"Log file not found: {log_file}", {"path": log_file})
        sys.exit(2)
    except PermissionError:
        _out("error", f"Permission denied reading: {log_file}", {"path": log_file})
        sys.exit(2)
    except OSError as exc:
        _out("error", f"Cannot read '{log_file}': {exc}", {"path": log_file})
        sys.exit(2)

    match_lines: list[str] = []
    for line in lines:
        if error_re.search(line):
            if ignore_re and ignore_re.search(line):
                continue
            match_lines.append(line)

    count = len(match_lines)
    # Return first 3 matching lines for context (truncate at 300 chars each)
    sample = [ln[:300] for ln in match_lines[:3]]

    value = {
        "log_file": log_file,
        "lines_checked": len(lines),
        "match_count": count,
        "sample_lines": sample,
        "error_regex": error_pattern,
        "ignore_regex": ignore_pattern or None,
    }

    if count >= crit_count:
        _out(
            "error",
            f"CRITICAL: {count} error pattern matches in last {len(lines)} lines of {log_file}",
            value,
        )
        sys.exit(2)

    if count >= warn_count:
        _out(
            "warning",
            f"WARNING: {count} error pattern matches in last {len(lines)} lines of {log_file}",
            value,
        )
        sys.exit(1)

    _out(
        "ok",
        f"No error patterns found in last {len(lines)} lines of {log_file}",
        value,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
