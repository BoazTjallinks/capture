#!/usr/bin/env python3
# http_health.py — HTTP Endpoint Health
# Exit 0=ok, 1=warning, 2=error
# Env: URL, METHOD, EXPECT_STATUS, EXPECT_BODY_REGEX, LATENCY_WARN_MS,
#      LATENCY_CRIT_MS, TIMEOUT_MS, VERIFY_TLS

import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request


def _out(status: str, message: str, value=None) -> None:
    print(json.dumps({"status": status, "message": message, "value": value}))


def parse_status_ranges(spec: str) -> list[tuple[int, int]]:
    """Parse a comma-separated list of status codes and ranges like '200-299,301'."""
    ranges = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            ranges.append((int(lo_s), int(hi_s)))
        else:
            code = int(part)
            ranges.append((code, code))
    return ranges


def status_matches(code: int, ranges: list[tuple[int, int]]) -> bool:
    return any(lo <= code <= hi for lo, hi in ranges)


def main() -> None:
    url = os.environ.get("URL", "https://example.com/health")
    method = os.environ.get("METHOD", "GET").upper()
    expect_status_spec = os.environ.get("EXPECT_STATUS", "200-299")
    expect_body_regex = os.environ.get("EXPECT_BODY_REGEX", "").strip()
    latency_warn_ms = int(os.environ.get("LATENCY_WARN_MS", "1000"))
    latency_crit_ms = int(os.environ.get("LATENCY_CRIT_MS", "3000"))
    timeout_ms = int(os.environ.get("TIMEOUT_MS", "5000"))
    verify_tls_str = os.environ.get("VERIFY_TLS", "1").strip()
    verify_tls = verify_tls_str not in ("0", "false", "no", "False", "No")

    # Parse expected status ranges
    try:
        expected_ranges = parse_status_ranges(expect_status_spec)
    except ValueError as exc:
        _out("error", f"Invalid EXPECT_STATUS '{expect_status_spec}': {exc}", None)
        sys.exit(2)

    # Compile body regex if given
    body_re = None
    if expect_body_regex:
        try:
            body_re = re.compile(expect_body_regex)
        except re.error as exc:
            _out("error", f"Invalid EXPECT_BODY_REGEX: {exc}", None)
            sys.exit(2)

    # Build SSL context
    if verify_tls:
        ssl_ctx = ssl.create_default_context()
    else:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url=url, method=method)
    req.add_header("User-Agent", "Checkmate-Monitor/1.0")

    t0 = time.monotonic()
    status_code = -1
    body_bytes = b""
    http_version = ""

    try:
        with urllib.request.urlopen(req, timeout=timeout_ms / 1000.0, context=ssl_ctx) as resp:
            elapsed_ms = round((time.monotonic() - t0) * 1000)
            status_code = resp.status
            # Read up to 64 KB for body inspection; we don't want to stall on huge responses
            body_bytes = resp.read(65536)
            http_version = f"HTTP/{resp.version // 10}.{resp.version % 10}" if resp.version else ""
    except urllib.error.HTTPError as exc:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        status_code = exc.code
        try:
            body_bytes = exc.read(65536)
        except OSError:
            body_bytes = b""
    except urllib.error.URLError as exc:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        reason = str(exc.reason)
        if "timed out" in reason.lower() or "timeout" in reason.lower():
            _out(
                "error",
                f"Connection timed out after {elapsed_ms}ms reaching {url}",
                {"url": url, "elapsed_ms": elapsed_ms},
            )
        elif "certificate" in reason.lower() or "ssl" in reason.lower():
            _out(
                "error",
                f"TLS/SSL error connecting to {url}: {reason}",
                {"url": url, "elapsed_ms": elapsed_ms},
            )
        elif "connection refused" in reason.lower():
            _out(
                "error",
                f"Connection refused by {url}",
                {"url": url, "elapsed_ms": elapsed_ms},
            )
        else:
            _out(
                "error",
                f"Request to {url} failed: {reason}",
                {"url": url, "elapsed_ms": elapsed_ms},
            )
        sys.exit(2)
    except TimeoutError:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _out(
            "error",
            f"Request timed out after {elapsed_ms}ms ({timeout_ms}ms limit) — {url}",
            {"url": url, "elapsed_ms": elapsed_ms},
        )
        sys.exit(2)
    except OSError as exc:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _out(
            "error",
            f"Network error reaching {url}: {exc}",
            {"url": url, "elapsed_ms": elapsed_ms},
        )
        sys.exit(2)

    body_bytes_len = len(body_bytes)
    value = {
        "url": url,
        "method": method,
        "status_code": status_code,
        "elapsed_ms": elapsed_ms,
        "bytes": body_bytes_len,
        "http_version": http_version,
    }

    # --- Check latency first (most expensive path) ---
    if elapsed_ms >= latency_crit_ms:
        _out(
            "error",
            f"Critical latency: {url} responded in {elapsed_ms}ms (threshold {latency_crit_ms}ms)",
            value,
        )
        sys.exit(2)

    if elapsed_ms >= latency_warn_ms:
        _out(
            "warning",
            f"High latency: {url} responded in {elapsed_ms}ms (threshold {latency_warn_ms}ms)",
            value,
        )
        sys.exit(1)

    # --- Check HTTP status code ---
    if not status_matches(status_code, expected_ranges):
        _out(
            "error",
            f"Unexpected HTTP {status_code} from {url} (expected {expect_status_spec})",
            value,
        )
        sys.exit(2)

    # --- Check body regex ---
    if body_re is not None:
        body_str = body_bytes.decode("utf-8", errors="replace")
        if not body_re.search(body_str):
            _out(
                "error",
                f"Body regex '{expect_body_regex}' not found in response from {url}",
                value,
            )
            sys.exit(2)

    _out(
        "ok",
        f"HTTP {status_code} from {url} in {elapsed_ms}ms ({body_bytes_len} bytes)",
        value,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
