#!/usr/bin/env python3
# tcp_reachability.py — TCP Port Reachability
# Exit 0=ok, 1=warning, 2=error
# Env: HOST, PORT, TIMEOUT_MS, LATENCY_WARN_MS

import errno
import json
import os
import socket
import sys
import time


def _out(status: str, message: str, value=None) -> None:
    print(json.dumps({"status": status, "message": message, "value": value}))


def main() -> None:
    host = os.environ.get("HOST", "1.1.1.1")
    port_str = os.environ.get("PORT", "443")
    timeout_ms = int(os.environ.get("TIMEOUT_MS", "3000"))
    latency_warn_ms = int(os.environ.get("LATENCY_WARN_MS", "500"))

    try:
        port = int(port_str)
        if not (1 <= port <= 65535):
            raise ValueError("out of range")
    except ValueError:
        _out("error", f"Invalid PORT value '{port_str}'; must be 1-65535", None)
        sys.exit(2)

    timeout_sec = timeout_ms / 1000.0
    t0 = time.monotonic()

    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            pass
        elapsed_ms = round((time.monotonic() - t0) * 1000)
    except socket.timeout:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _out(
            "error",
            f"TCP timeout after {elapsed_ms}ms connecting to {host}:{port}",
            {"host": host, "port": port, "elapsed_ms": elapsed_ms},
        )
        sys.exit(2)
    except TimeoutError:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _out(
            "error",
            f"TCP timeout after {elapsed_ms}ms connecting to {host}:{port}",
            {"host": host, "port": port, "elapsed_ms": elapsed_ms},
        )
        sys.exit(2)
    except ConnectionRefusedError:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _out(
            "error",
            f"Connection refused by {host}:{port}",
            {"host": host, "port": port, "elapsed_ms": elapsed_ms},
        )
        sys.exit(2)
    except socket.gaierror as exc:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _out(
            "error",
            f"DNS resolution failed for '{host}': {exc.strerror}",
            {"host": host, "port": port, "elapsed_ms": elapsed_ms},
        )
        sys.exit(2)
    except OSError as exc:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        # ENETUNREACH, EHOSTUNREACH, etc.
        if exc.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH):
            msg = f"Host {host}:{port} is unreachable (network/routing error)"
        elif exc.errno == errno.ECONNRESET:
            msg = f"Connection reset by {host}:{port}"
        else:
            msg = f"TCP connect to {host}:{port} failed: {exc.strerror or exc}"
        _out("error", msg, {"host": host, "port": port, "elapsed_ms": elapsed_ms})
        sys.exit(2)

    value = {
        "host": host,
        "port": port,
        "elapsed_ms": elapsed_ms,
    }

    if elapsed_ms >= latency_warn_ms:
        _out(
            "warning",
            f"TCP {host}:{port} reachable but slow: {elapsed_ms}ms (threshold {latency_warn_ms}ms)",
            value,
        )
        sys.exit(1)

    _out(
        "ok",
        f"TCP {host}:{port} reachable in {elapsed_ms}ms",
        value,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
