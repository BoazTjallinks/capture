#!/usr/bin/env python3
# entra_cert_expiry.py — Entra ID App Registration Secret & Certificate Expiry
# Exit 0=ok, 1=warning, 2=error
# Env: AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET,
#      WARN_DAYS, CRIT_DAYS, APP_FILTER, INCLUDE_EXPIRED,
#      GRAPH_BASE, LOGIN_BASE

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _out(status: str, message: str, value=None) -> None:
    print(json.dumps({"status": status, "message": message, "value": value}))


def _die(message: str, value=None) -> None:
    _out("error", message, value)
    sys.exit(2)


# ---------------------------------------------------------------------------
# Minimal HTTP helper (urllib only, no requests)
# ---------------------------------------------------------------------------

def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict | None = None,
    data: bytes | None = None,
    timeout: float = 30.0,
) -> tuple[int, dict]:
    """Perform a single HTTP request, return (status_code, parsed_json)."""
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    if data is not None and "Content-Type" not in (headers or {}):
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = b""
        try:
            raw = exc.read()
        except OSError:
            pass
        try:
            body = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = {"raw": raw.decode("utf-8", errors="replace")}
        return exc.code, body


# ---------------------------------------------------------------------------
# Token acquisition
# ---------------------------------------------------------------------------

def get_access_token(tenant_id: str, client_id: str, client_secret: str, login_base: str) -> str:
    """Obtain a bearer token using the client_credentials grant."""
    token_url = f"{login_base.rstrip('/')}/{tenant_id}/oauth2/v2.0/token"
    payload = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
        }
    ).encode()

    status, body = _http_json(token_url, method="POST", data=payload)

    if status != 200:
        error_desc = body.get("error_description", body.get("error", "unknown"))
        # Sanitise: never echo client_secret in output
        error_desc = error_desc.replace(client_secret, "***") if client_secret in error_desc else error_desc
        _die(f"Failed to acquire access token (HTTP {status}): {error_desc}")

    token = body.get("access_token", "")
    if not token:
        _die("Token response did not contain access_token")
    return token  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Graph pagination with 429 retry
# ---------------------------------------------------------------------------

def graph_get_all(
    url: str,
    token: str,
    graph_base: str,
    max_retries: int = 5,
    timeout: float = 30.0,
) -> list[dict]:
    """Fetch all pages from a Graph endpoint, honouring @odata.nextLink and Retry-After."""
    results: list[dict] = []
    current_url: str | None = url

    while current_url:
        retries = 0
        while True:
            status, body = _http_json(
                current_url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
            )

            if status == 429:
                retry_after = int(body.get("error", {}).get("retryAfter", 10)) if isinstance(body.get("error"), dict) else 10
                # Also look for the standard Retry-After value embedded in the response
                retry_after = max(retry_after, 1)
                retries += 1
                if retries > max_retries:
                    _die(f"Graph API rate-limit (429) persisted after {max_retries} retries; giving up")
                time.sleep(retry_after)
                continue

            if status == 401:
                _die("Graph API returned 401 Unauthorized — check app permissions (Application.Read.All)")

            if status == 403:
                _die("Graph API returned 403 Forbidden — ensure the service principal has Application.Read.All")

            if status not in (200,):
                error_msg = ""
                if isinstance(body.get("error"), dict):
                    error_msg = body["error"].get("message", "")
                _die(f"Graph API error (HTTP {status}): {error_msg or json.dumps(body)}")

            break  # successful response

        items = body.get("value", [])
        results.extend(items)
        current_url = body.get("@odata.nextLink")

    return results


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def parse_iso8601(s: str) -> datetime | None:
    """Parse an ISO 8601 datetime string to a timezone-aware datetime (UTC)."""
    if not s:
        return None
    # Graph returns 'YYYY-MM-DDTHH:MM:SSZ' or 'YYYY-MM-DDTHH:MM:SS.fffffffZ'
    s_clean = s.rstrip("Z").split(".")[0]  # strip fractional seconds and trailing Z
    try:
        dt = datetime.strptime(s_clean, "%Y-%m-%dT%H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            dt = datetime.strptime(s_clean, "%Y-%m-%d")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # --- Required parameters ---
    tenant_id = os.environ.get("AZURE_TENANT_ID", "").strip()
    client_id = os.environ.get("AZURE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("AZURE_CLIENT_SECRET", "").strip()

    missing = [k for k, v in [
        ("AZURE_TENANT_ID", tenant_id),
        ("AZURE_CLIENT_ID", client_id),
        ("AZURE_CLIENT_SECRET", client_secret),
    ] if not v]
    if missing:
        _die(f"Missing required environment variables: {', '.join(missing)}")

    # --- Optional parameters ---
    warn_days = int(os.environ.get("WARN_DAYS", "30"))
    crit_days = int(os.environ.get("CRIT_DAYS", "7"))
    app_filter_raw = os.environ.get("APP_FILTER", "").strip()
    include_expired_str = os.environ.get("INCLUDE_EXPIRED", "1").strip()
    graph_base = os.environ.get("GRAPH_BASE", "https://graph.microsoft.com").rstrip("/")
    login_base = os.environ.get("LOGIN_BASE", "https://login.microsoftonline.com").rstrip("/")

    app_filter = [f.strip() for f in app_filter_raw.split(",") if f.strip()] if app_filter_raw else []
    include_expired = include_expired_str not in ("0", "false", "no", "False", "No")

    # --- Auth ---
    token = get_access_token(tenant_id, client_id, client_secret, login_base)

    # --- Fetch apps ---
    apps_url = (
        f"{graph_base}/v1.0/applications"
        "?$select=id,appId,displayName,passwordCredentials,keyCredentials"
        "&$top=999"
    )
    apps = graph_get_all(apps_url, token, graph_base)

    # --- Apply APP_FILTER ---
    if app_filter:
        apps = [
            a for a in apps
            if any(
                (a.get("displayName") or "").startswith(prefix)
                for prefix in app_filter
            )
        ]

    now = datetime.now(tz=timezone.utc)
    expiring: list[dict] = []
    apps_checked = 0
    creds_total = 0

    for app in apps:
        app_name = app.get("displayName") or app.get("appId", "unknown")
        app_id = app.get("appId", "")
        object_id = app.get("id", "")
        apps_checked += 1

        # passwordCredentials = secrets
        for cred in app.get("passwordCredentials", []) or []:
            creds_total += 1
            end_dt = parse_iso8601(cred.get("endDateTime", ""))
            if end_dt is None:
                continue
            days_remaining = (end_dt - now).days
            if not include_expired and days_remaining < 0:
                continue
            if days_remaining <= warn_days:
                expiring.append(
                    {
                        "app_name": app_name,
                        "app_id": app_id,
                        "object_id": object_id,
                        "credential_type": "secret",
                        "credential_name": cred.get("displayName") or cred.get("keyId", ""),
                        "credential_id": cred.get("keyId", ""),
                        "expires_utc": end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "days_remaining": days_remaining,
                    }
                )

        # keyCredentials = certificates
        for cred in app.get("keyCredentials", []) or []:
            creds_total += 1
            end_dt = parse_iso8601(cred.get("endDateTime", ""))
            if end_dt is None:
                continue
            days_remaining = (end_dt - now).days
            if not include_expired and days_remaining < 0:
                continue
            if days_remaining <= warn_days:
                expiring.append(
                    {
                        "app_name": app_name,
                        "app_id": app_id,
                        "object_id": object_id,
                        "credential_type": "certificate",
                        "credential_name": cred.get("displayName") or cred.get("keyId", ""),
                        "credential_id": cred.get("keyId", ""),
                        "expires_utc": end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "days_remaining": days_remaining,
                    }
                )

    # Sort by soonest expiry first
    expiring.sort(key=lambda c: c["days_remaining"])

    crit_items = [c for c in expiring if c["days_remaining"] <= crit_days]
    warn_items = [c for c in expiring if crit_days < c["days_remaining"] <= warn_days]
    expired_items = [c for c in expiring if c["days_remaining"] < 0]

    value = {
        "apps_checked": apps_checked,
        "credentials_checked": creds_total,
        "expiring": expiring,
        "crit_count": len(crit_items),
        "warn_count": len(warn_items),
        "expired_count": len(expired_items),
    }

    if crit_items:
        worst = crit_items[0]
        _out(
            "error",
            (
                f"CRITICAL: {len(crit_items)} credential(s) expire within {crit_days}d "
                f"— worst: '{worst['app_name']}' ({worst['credential_type']}) "
                f"in {worst['days_remaining']}d"
            ),
            value,
        )
        sys.exit(2)

    if expired_items and include_expired:
        worst = expired_items[0]
        _out(
            "error",
            (
                f"CRITICAL: {len(expired_items)} credential(s) already expired "
                f"— oldest: '{worst['app_name']}' ({worst['credential_type']}) "
                f"{abs(worst['days_remaining'])}d ago"
            ),
            value,
        )
        sys.exit(2)

    if warn_items:
        worst = warn_items[0]
        _out(
            "warning",
            (
                f"WARNING: {len(warn_items)} credential(s) expire within {warn_days}d "
                f"— soonest: '{worst['app_name']}' ({worst['credential_type']}) "
                f"in {worst['days_remaining']}d"
            ),
            value,
        )
        sys.exit(1)

    _out(
        "ok",
        (
            f"All credentials OK — checked {apps_checked} apps, "
            f"{creds_total} credentials, none expiring within {warn_days}d"
        ),
        value,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
