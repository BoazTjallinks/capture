#!/usr/bin/env python3
# dns_check.py — DNS Resolution Check
# Exit 0=ok, 1=warning, 2=error
# Env: HOSTNAME, RECORD_TYPE, EXPECTED_IPS, TIMEOUT_MS

import json
import os
import socket
import sys
import threading
import time


def _out(status: str, message: str, value=None) -> None:
    print(json.dumps({"status": status, "message": message, "value": value}))


def resolve(hostname: str, family: int, result_box: list, error_box: list) -> None:
    """Run in a thread so we can enforce a wall-clock timeout."""
    try:
        infos = socket.getaddrinfo(hostname, None, family)
        ips = list(dict.fromkeys(info[4][0] for info in infos))  # deduplicate, preserve order
        result_box.append(ips)
    except socket.gaierror as exc:
        error_box.append(exc)
    except OSError as exc:
        error_box.append(exc)


def main() -> None:
    hostname = os.environ.get("HOSTNAME", "www.google.com")
    record_type = os.environ.get("RECORD_TYPE", "A").upper()
    expected_raw = os.environ.get("EXPECTED_IPS", "").strip()
    timeout_ms = int(os.environ.get("TIMEOUT_MS", "3000"))

    if record_type not in ("A", "AAAA"):
        _out("error", f"Unsupported RECORD_TYPE '{record_type}'; use A or AAAA", None)
        sys.exit(2)

    family = socket.AF_INET if record_type == "A" else socket.AF_INET6
    expected_ips = [ip.strip() for ip in expected_raw.split(",") if ip.strip()] if expected_raw else []

    result_box: list = []
    error_box: list = []

    t = threading.Thread(target=resolve, args=(hostname, family, result_box, error_box), daemon=True)
    t0 = time.monotonic()
    t.start()
    t.join(timeout=timeout_ms / 1000.0)
    elapsed_ms = round((time.monotonic() - t0) * 1000)

    if t.is_alive():
        _out(
            "error",
            f"DNS timeout after {elapsed_ms}ms resolving {hostname} ({record_type})",
            {"elapsed_ms": elapsed_ms, "hostname": hostname, "record_type": record_type},
        )
        sys.exit(2)

    if error_box:
        exc = error_box[0]
        msg = str(exc)
        # Provide friendlier messages for common errno codes
        if isinstance(exc, socket.gaierror):
            code = exc.args[0] if exc.args else None
            if code == socket.EAI_NONAME or code == -2:
                msg = f"Name '{hostname}' does not exist"
            elif code == socket.EAI_AGAIN:
                msg = f"Temporary DNS failure resolving '{hostname}'"
            elif code == socket.EAI_NODATA:
                msg = f"No {record_type} records found for '{hostname}'"
        _out(
            "error",
            f"DNS resolution failed for {hostname} ({record_type}): {msg}",
            {"elapsed_ms": elapsed_ms, "hostname": hostname, "record_type": record_type},
        )
        sys.exit(2)

    resolved_ips: list = result_box[0]

    value = {
        "hostname": hostname,
        "record_type": record_type,
        "resolved_ips": resolved_ips,
        "elapsed_ms": elapsed_ms,
    }

    if expected_ips:
        missing = [ip for ip in expected_ips if ip not in resolved_ips]
        unexpected = [ip for ip in resolved_ips if ip not in expected_ips]
        value["expected_ips"] = expected_ips
        value["missing_ips"] = missing
        value["unexpected_ips"] = unexpected

        if missing:
            _out(
                "error",
                f"{hostname} ({record_type}): expected IPs missing: {', '.join(missing)}",
                value,
            )
            sys.exit(2)

        _out(
            "ok",
            f"{hostname} ({record_type}) resolved in {elapsed_ms}ms — all expected IPs present",
            value,
        )
        sys.exit(0)

    _out(
        "ok",
        f"{hostname} ({record_type}) resolved to {', '.join(resolved_ips)} in {elapsed_ms}ms",
        value,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
