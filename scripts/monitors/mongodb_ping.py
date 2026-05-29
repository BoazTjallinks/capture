#!/usr/bin/env python3
# mongodb_ping.py — MongoDB Ping (wire protocol, stdlib only)
# Exit 0=ok, 1=warning, 2=error
# Env: MONGO_HOST, MONGO_PORT, TIMEOUT_MS, LATENCY_WARN_MS
#
# Implements just enough of the MongoDB wire protocol to send OP_MSG {ping:1}
# and verify a successful response.  No third-party libraries required.

import json
import os
import socket
import struct
import sys
import time


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _out(status: str, message: str, value=None) -> None:
    print(json.dumps({"status": status, "message": message, "value": value}))


# ---------------------------------------------------------------------------
# Minimal inline BSON helpers (just enough for ping + decode response)
# ---------------------------------------------------------------------------
# BSON spec: https://bsonspec.org/spec.html

def _bson_int32_field(key: str, val: int) -> bytes:
    return b"\x10" + key.encode() + b"\x00" + struct.pack("<i", val)


def _bson_string_field(key: str, val: str) -> bytes:
    encoded = val.encode("utf-8") + b"\x00"
    return b"\x02" + key.encode() + b"\x00" + struct.pack("<i", len(encoded)) + encoded


def bson_encode_ping() -> bytes:
    """Encode {ping: 1, $db: "admin"} as BSON."""
    body = _bson_int32_field("ping", 1) + _bson_string_field("$db", "admin")
    body += b"\x00"  # document terminator
    return struct.pack("<i", 4 + len(body)) + body


def bson_decode(data: bytes) -> dict:
    """Decode a BSON document into a Python dict.
    Supports int32, int64, double, boolean, UTF-8 string, embedded document.
    """
    result: dict = {}
    doc_size = struct.unpack_from("<i", data, 0)[0]
    offset = 4
    end = doc_size - 1  # byte before the terminating null

    while offset < end:
        type_byte = data[offset]
        offset += 1
        if type_byte == 0x00:
            break

        # Read key (null-terminated CString)
        key_end = data.index(b"\x00", offset)
        key = data[offset:key_end].decode(errors="replace")
        offset = key_end + 1

        if type_byte == 0x10:    # int32
            val = struct.unpack_from("<i", data, offset)[0]
            offset += 4
        elif type_byte == 0x01:  # double
            val = struct.unpack_from("<d", data, offset)[0]
            offset += 8
        elif type_byte == 0x08:  # boolean
            val = bool(data[offset])
            offset += 1
        elif type_byte == 0x02:  # UTF-8 string
            str_len = struct.unpack_from("<i", data, offset)[0]
            offset += 4
            val = data[offset: offset + str_len - 1].decode(errors="replace")
            offset += str_len
        elif type_byte == 0x12:  # int64
            val = struct.unpack_from("<q", data, offset)[0]
            offset += 8
        elif type_byte == 0x11:  # BSON Timestamp (uint64)
            val = struct.unpack_from("<Q", data, offset)[0]
            offset += 8
        elif type_byte == 0x03:  # embedded document — recurse
            sub_size = struct.unpack_from("<i", data, offset)[0]
            val = bson_decode(data[offset: offset + sub_size])
            offset += sub_size
        else:
            # Unknown type: cannot determine field width, stop parsing
            break

        result[key] = val

    return result


# ---------------------------------------------------------------------------
# MongoDB OP_MSG (opCode 2013) wire framing
# ---------------------------------------------------------------------------
# Header layout: int32 messageLength | int32 requestId | int32 responseTo | int32 opCode
# OP_MSG body:   int32 flagBits | byte sectionKind(0) | BSON document

OP_MSG = 2013


def build_op_msg(bson_body: bytes, request_id: int = 1) -> bytes:
    flag_bits = struct.pack("<I", 0)   # no flags
    section_kind = b"\x00"             # kind 0 = body section
    payload = flag_bits + section_kind + bson_body
    msg_len = 16 + len(payload)        # 16-byte header + payload
    header = struct.pack("<iiii", msg_len, request_id, 0, OP_MSG)
    return header + payload


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError(f"Socket closed after {len(buf)}/{n} bytes")
        buf.extend(chunk)
    return bytes(buf)


def read_op_msg_response(sock: socket.socket) -> dict:
    header = recv_exact(sock, 16)
    msg_len, _req_id, _resp_to, op_code = struct.unpack_from("<iiii", header)

    if op_code != OP_MSG:
        raise ValueError(f"Unexpected opCode {op_code}; expected {OP_MSG} (OP_MSG)")

    payload_len = msg_len - 16
    if payload_len < 5:  # flagBits(4) + kind(1) minimum
        raise ValueError(f"OP_MSG payload too short: {payload_len} bytes")

    payload = recv_exact(sock, payload_len)
    section_kind = payload[4]
    if section_kind != 0:
        raise ValueError(f"Unexpected section kind {section_kind}; expected 0")

    bson_data = payload[5:]
    return bson_decode(bson_data)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    host = os.environ.get("MONGO_HOST", "127.0.0.1")
    port = int(os.environ.get("MONGO_PORT", "27017"))
    timeout_ms = int(os.environ.get("TIMEOUT_MS", "3000"))
    latency_warn_ms = int(os.environ.get("LATENCY_WARN_MS", "200"))

    timeout_sec = timeout_ms / 1000.0
    value_base = {"host": host, "port": port}

    t0 = time.monotonic()

    try:
        with socket.create_connection((host, port), timeout=timeout_sec) as sock:
            sock.settimeout(timeout_sec)

            msg = build_op_msg(bson_encode_ping())
            sock.sendall(msg)
            response = read_op_msg_response(sock)

        elapsed_ms = round((time.monotonic() - t0) * 1000)

        ok_val = response.get("ok")
        if ok_val != 1 and ok_val != 1.0:
            _out(
                "error",
                f"MongoDB ping returned ok={ok_val!r} from {host}:{port}",
                {**value_base, "elapsed_ms": elapsed_ms, "response": response},
            )
            sys.exit(2)

    except socket.timeout:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _out("error", f"MongoDB timeout after {elapsed_ms}ms connecting to {host}:{port}", {**value_base, "elapsed_ms": elapsed_ms})
        sys.exit(2)
    except TimeoutError:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _out("error", f"MongoDB timeout after {elapsed_ms}ms connecting to {host}:{port}", {**value_base, "elapsed_ms": elapsed_ms})
        sys.exit(2)
    except ConnectionRefusedError:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _out("error", f"MongoDB connection refused by {host}:{port}", {**value_base, "elapsed_ms": elapsed_ms})
        sys.exit(2)
    except socket.gaierror as exc:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _out("error", f"DNS resolution failed for '{host}': {exc.strerror}", {**value_base, "elapsed_ms": elapsed_ms})
        sys.exit(2)
    except (ConnectionError, ValueError, struct.error) as exc:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _out("error", f"MongoDB protocol error from {host}:{port}: {exc}", {**value_base, "elapsed_ms": elapsed_ms})
        sys.exit(2)
    except OSError as exc:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _out("error", f"Network error reaching {host}:{port}: {exc}", {**value_base, "elapsed_ms": elapsed_ms})
        sys.exit(2)

    value = {**value_base, "elapsed_ms": elapsed_ms}

    if elapsed_ms >= latency_warn_ms:
        _out(
            "warning",
            f"MongoDB {host}:{port} ping OK but slow: {elapsed_ms}ms (threshold {latency_warn_ms}ms)",
            value,
        )
        sys.exit(1)

    _out("ok", f"MongoDB PONG received from {host}:{port} in {elapsed_ms}ms", value)
    sys.exit(0)


if __name__ == "__main__":
    main()
