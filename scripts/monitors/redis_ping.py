#!/usr/bin/env python3
# redis_ping.py — Redis Ping (raw RESP protocol, stdlib only)
# Exit 0=ok, 1=warning, 2=error
# Env: REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_USERNAME,
#      USE_TLS, TIMEOUT_MS, LATENCY_WARN_MS

import json
import os
import socket
import ssl
import sys
import time


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _out(status: str, message: str, value=None) -> None:
    print(json.dumps({"status": status, "message": message, "value": value}))


# ---------------------------------------------------------------------------
# RESP protocol helpers
# ---------------------------------------------------------------------------

def resp_inline(command: str) -> bytes:
    """Encode a command as an inline RESP string (simple, no args needed for PING)."""
    return (command + "\r\n").encode()


def resp_array(*args: str) -> bytes:
    """Encode a command as a RESP array (used for AUTH username password, HELLO)."""
    parts = [f"*{len(args)}\r\n"]
    for arg in args:
        encoded = arg.encode("utf-8")
        parts.append(f"${len(encoded)}\r\n")
        parts.append(arg + "\r\n")
    return "".join(parts).encode("utf-8")


def recv_line(sock: socket.socket) -> str:
    """Read bytes until CRLF, return the line without the CRLF."""
    buf = bytearray()
    while True:
        b = sock.recv(1)
        if not b:
            raise ConnectionError("Socket closed while reading RESP line")
        buf.extend(b)
        if buf[-2:] == b"\r\n":
            return buf[:-2].decode("utf-8", errors="replace")


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError(f"Socket closed after {len(buf)}/{n} bytes")
        buf.extend(chunk)
    return bytes(buf)


def read_resp(sock: socket.socket):
    """Read one RESP value from the socket."""
    line = recv_line(sock)
    if not line:
        raise ConnectionError("Empty RESP line")

    prefix = line[0]
    rest = line[1:]

    if prefix == "+":
        # Simple string
        return rest
    elif prefix == "-":
        # Error
        raise RuntimeError(f"Redis error: {rest}")
    elif prefix == ":":
        # Integer
        return int(rest)
    elif prefix == "$":
        # Bulk string
        length = int(rest)
        if length == -1:
            return None
        data = recv_exact(sock, length)
        recv_exact(sock, 2)  # consume CRLF
        return data.decode("utf-8", errors="replace")
    elif prefix == "*":
        # Array
        count = int(rest)
        if count == -1:
            return None
        return [read_resp(sock) for _ in range(count)]
    else:
        raise ValueError(f"Unknown RESP prefix: {prefix!r}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    host = os.environ.get("REDIS_HOST", "127.0.0.1")
    port = int(os.environ.get("REDIS_PORT", "6379"))
    password = os.environ.get("REDIS_PASSWORD", "").strip()
    username = os.environ.get("REDIS_USERNAME", "").strip()
    use_tls_str = os.environ.get("USE_TLS", "0").strip()
    use_tls = use_tls_str not in ("0", "false", "no", "False", "No")
    timeout_ms = int(os.environ.get("TIMEOUT_MS", "2000"))
    latency_warn_ms = int(os.environ.get("LATENCY_WARN_MS", "100"))

    timeout_sec = timeout_ms / 1000.0
    value_base = {"host": host, "port": port, "tls": use_tls}

    t0 = time.monotonic()

    try:
        raw_sock = socket.create_connection((host, port), timeout=timeout_sec)

        if use_tls:
            ssl_ctx = ssl.create_default_context()
            sock = ssl_ctx.wrap_socket(raw_sock, server_hostname=host)
        else:
            sock = raw_sock

        sock.settimeout(timeout_sec)

        with sock:
            # AUTH — send before any other command
            if password:
                if username:
                    sock.sendall(resp_array("AUTH", username, password))
                else:
                    sock.sendall(resp_array("AUTH", password))

                auth_resp = read_resp(sock)
                # auth_resp should be "+OK"
                if isinstance(auth_resp, str):
                    if auth_resp.upper() != "OK":
                        elapsed_ms = round((time.monotonic() - t0) * 1000)
                        _out(
                            "error",
                            f"Redis AUTH failed: unexpected response '{auth_resp}'",
                            {**value_base, "elapsed_ms": elapsed_ms},
                        )
                        sys.exit(2)
                # RuntimeError is raised by read_resp for RESP errors (e.g. WRONGPASS)

            # PING
            t_ping = time.monotonic()
            sock.sendall(resp_inline("PING"))
            pong = read_resp(sock)
            elapsed_ms = round((time.monotonic() - t0) * 1000)
            ping_ms = round((time.monotonic() - t_ping) * 1000)

        if isinstance(pong, str) and pong.upper() == "PONG":
            pass  # success
        else:
            _out(
                "error",
                f"Redis PING returned unexpected response: {pong!r}",
                {**value_base, "elapsed_ms": elapsed_ms},
            )
            sys.exit(2)

    except RuntimeError as exc:
        # Raised by read_resp for Redis -ERR responses (auth failure, etc.)
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        msg = str(exc)
        if "WRONGPASS" in msg or "NOAUTH" in msg or "invalid password" in msg.lower():
            _out("error", f"Redis authentication failed: {msg}", {**value_base, "elapsed_ms": elapsed_ms})
        else:
            _out("error", f"Redis error: {msg}", {**value_base, "elapsed_ms": elapsed_ms})
        sys.exit(2)
    except socket.timeout:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _out("error", f"Redis timeout after {elapsed_ms}ms ({host}:{port})", {**value_base, "elapsed_ms": elapsed_ms})
        sys.exit(2)
    except TimeoutError:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _out("error", f"Redis timeout after {elapsed_ms}ms ({host}:{port})", {**value_base, "elapsed_ms": elapsed_ms})
        sys.exit(2)
    except ConnectionRefusedError:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _out("error", f"Redis connection refused by {host}:{port}", {**value_base, "elapsed_ms": elapsed_ms})
        sys.exit(2)
    except socket.gaierror as exc:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _out("error", f"DNS resolution failed for '{host}': {exc.strerror}", {**value_base, "elapsed_ms": elapsed_ms})
        sys.exit(2)
    except ssl.SSLError as exc:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _out("error", f"TLS error connecting to {host}:{port}: {exc}", {**value_base, "elapsed_ms": elapsed_ms})
        sys.exit(2)
    except (ConnectionError, ValueError) as exc:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _out("error", f"Redis protocol error from {host}:{port}: {exc}", {**value_base, "elapsed_ms": elapsed_ms})
        sys.exit(2)
    except OSError as exc:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _out("error", f"Network error reaching {host}:{port}: {exc}", {**value_base, "elapsed_ms": elapsed_ms})
        sys.exit(2)

    value = {**value_base, "elapsed_ms": elapsed_ms, "ping_ms": ping_ms}

    if elapsed_ms >= latency_warn_ms:
        _out(
            "warning",
            f"Redis {host}:{port} PONG received but slow: {elapsed_ms}ms (threshold {latency_warn_ms}ms)",
            value,
        )
        sys.exit(1)

    _out("ok", f"Redis PONG received from {host}:{port} in {elapsed_ms}ms", value)
    sys.exit(0)


if __name__ == "__main__":
    main()
