"""Syslog destination handler — UDP, TCP, and TLS forwarders.

The merged_config dict reaches this module with both the operator-set
config fields AND any resolved secrets (e.g. tls_client_key when
protocol=tls). Plaintext secrets only flow through process boundaries
on the MCP server side; the agent's MCP tool surface never sees them.

Wire format:
  - RFC5424: <PRI>1 <iso-ts> <hostname> <app-name> <procid> <msgid> - <msg>
  - RFC3164: <PRI><Mmm dd hh:mm:ss> <hostname> <app-name>: <msg>

PRI is computed from the configured facility (kern=0..local7=23)
plus a static severity (NOTICE=5) for synthetic-traffic records.

# XSIAM-broker dataset routing

When this destination points at an XSIAM broker VM (the most common
production use case), the broker parses INCOMING syslog content. If
the messages are CEF-formatted with the standard 8-field header
(`CEF:0|<vendor>|<product>|<version>|<id>|<name>|<sev>|<ext>`), the
broker automatically routes records into the XSIAM dataset named:

    `<vendor>_<product>_raw`

(both lowercased + non-alphanumeric chars replaced with `_`). So
sending `CEF:0|phantom|smoke_test|...` lands in `phantom_smoke_test_raw`;
sending `CEF:0|fortinet|fortigate|...` lands in `fortinet_fortigate_raw`.

Records arrive fully parsed: each CEF extension key becomes a typed
column (`act`, `src`, `dst`, `spt`, `dpt`, `suser`, `cs1`, etc.).
No modeling rule needed for the basic columns.

## What this handler emits

This handler's `send()` JSON-encodes each record dict into the syslog
MSG body. That is NOT CEF — it's syslog with a JSON payload. Brokers
that aren't configured to recognize JSON-wrapped syslog will drop
those messages OR route to a generic catchall dataset.

**For production traffic targeting an XSIAM broker, prefer
`phantom_create_data_worker(type="CEF", vendor=..., product=...,
destination=udp:<broker-host>:<broker-port>, observables_dict=...)`**
— xlog formats the CEF properly, the broker parses cleanly, and the
records land in the expected `<vendor>_<product>_raw` dataset.

This handler is correct for non-XSIAM syslog targets (rsyslog,
syslog-ng, on-prem SIEMs) AND for connectivity testing via probe().

(Contrast with the xsiam_http handler — that path ALWAYS lands in
`phantom_logs_raw` regardless of source/vendor/product tags. See
bundles/spark/destinations/xsiam_http/handler.py.)
"""

from __future__ import annotations

import asyncio
import json
import socket
import ssl
import time
from datetime import datetime, timezone
from typing import Any

# Syslog facility codes (per RFC5424 § 6.2.1)
_FACILITY_CODES = {
    "kern": 0, "user": 1, "mail": 2, "daemon": 3, "auth": 4, "syslog": 5,
    "local0": 16, "local1": 17, "local2": 18, "local3": 19,
    "local4": 20, "local5": 21, "local6": 22, "local7": 23,
}
_SEVERITY_NOTICE = 5  # synthetic-traffic records flagged as informational


def _pri(facility_name: str) -> int:
    """Compute the syslog PRI from facility + fixed NOTICE severity."""
    fac = _FACILITY_CODES.get(facility_name.lower(), 16)  # default local0
    return fac * 8 + _SEVERITY_NOTICE


def _format_rfc5424(
    msg: str, *, hostname: str = "phantom", app_name: str = "phantom",
    pri: int = 134,
) -> bytes:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return f"<{pri}>1 {ts} {hostname} {app_name} - - - {msg}\n".encode("utf-8")


def _format_rfc3164(
    msg: str, *, hostname: str = "phantom", app_name: str = "phantom",
    pri: int = 134,
) -> bytes:
    # BSD format uses Mmm dd hh:mm:ss in LOCAL time (not UTC). We emit
    # UTC anyway — operator-side syslog server can adjust if needed.
    ts = datetime.now(timezone.utc).strftime("%b %d %H:%M:%S")
    return f"<{pri}>{ts} {hostname} {app_name}: {msg}\n".encode("utf-8")


def _format_message(msg: str, *, framing: str, facility: str) -> bytes:
    pri = _pri(facility)
    if framing == "rfc3164":
        return _format_rfc3164(msg, pri=pri)
    return _format_rfc5424(msg, pri=pri)


def _make_tls_context(merged_config: dict[str, Any]) -> ssl.SSLContext:
    """Build an SSL context from optional CA + client cert/key.

    `tls_ca_cert` (PEM) and `tls_client_cert` (PEM) come through as
    plain strings. `tls_client_key` is the resolved-from-SecretStore
    private key. We materialize them to temp files because Python's
    ssl.SSLContext.load_verify_locations only accepts paths, not
    in-memory bytes (pre-3.10 anyway).
    """
    import tempfile, os
    ctx = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED

    ca = merged_config.get("tls_ca_cert")
    if ca:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".pem", delete=False,
        ) as f:
            f.write(ca)
            ca_path = f.name
        ctx.load_verify_locations(cafile=ca_path)
        try:
            os.unlink(ca_path)
        except OSError:
            pass

    cert = merged_config.get("tls_client_cert")
    key = merged_config.get("tls_client_key")
    if cert and key:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".crt", delete=False,
        ) as f:
            f.write(cert)
            cert_path = f.name
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".key", delete=False,
        ) as f:
            f.write(key)
            key_path = f.name
        try:
            ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
        finally:
            try: os.unlink(cert_path)
            except OSError: pass
            try: os.unlink(key_path)
            except OSError: pass

    return ctx


async def _send_udp(host: str, port: int, payloads: list[bytes]) -> None:
    """Send one or more datagrams. Each payload is one syslog message."""
    loop = asyncio.get_running_loop()
    # asyncio's create_datagram_endpoint is overkill for one-shot UDP
    # sends; fall back to a blocking socket in an executor.

    def _do_send() -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            for p in payloads:
                s.sendto(p, (host, port))
        finally:
            s.close()

    await loop.run_in_executor(None, _do_send)


async def _send_tcp(
    host: str, port: int, payloads: list[bytes],
    *, use_tls: bool = False, merged_config: dict[str, Any] | None = None,
) -> None:
    loop = asyncio.get_running_loop()

    def _do_send() -> None:
        s = socket.create_connection((host, port), timeout=10)
        try:
            if use_tls:
                ctx = _make_tls_context(merged_config or {})
                s = ctx.wrap_socket(s, server_hostname=host)
            for p in payloads:
                # Octet-framing not required for most syslog-over-TCP
                # implementations; rsyslog/syslog-ng default to LF-framed.
                s.sendall(p)
        finally:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()

    await loop.run_in_executor(None, _do_send)


async def probe(merged_config: dict[str, Any]) -> dict[str, Any]:
    """Send a single test message; report ok/error/latency."""
    host = str(merged_config.get("host") or "").strip()
    port = int(merged_config.get("port") or 514)
    protocol = str(merged_config.get("protocol") or "udp").lower()
    framing = str(merged_config.get("framing") or "rfc5424")
    facility = str(merged_config.get("facility") or "local0")
    if not host:
        return {"ok": False, "error": "host is required",
                "latency_ms": 0}

    msg = _format_message(
        "phantom test message — log-destination probe at " +
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        framing=framing, facility=facility,
    )

    started = time.monotonic()
    try:
        if protocol == "udp":
            await _send_udp(host, port, [msg])
        elif protocol == "tcp":
            await _send_tcp(host, port, [msg], use_tls=False)
        elif protocol == "tls":
            await _send_tcp(
                host, port, [msg], use_tls=True,
                merged_config=merged_config,
            )
        else:
            return {"ok": False,
                    "error": f"unknown protocol: {protocol!r}",
                    "latency_ms": 0}
    except (socket.gaierror, ConnectionRefusedError, OSError,
            ssl.SSLError, TimeoutError) as e:
        latency = int((time.monotonic() - started) * 1000)
        return {"ok": False,
                "error": f"{type(e).__name__}: {e}",
                "latency_ms": latency}

    latency = int((time.monotonic() - started) * 1000)
    return {"ok": True, "error": None, "latency_ms": latency}


async def send(
    merged_config: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Send a batch of records as syslog messages.

    Each record is JSON-serialized into the syslog MSG portion. The
    operator's syslog server is responsible for parsing the embedded
    JSON (most modern SIEMs do this natively).
    """
    host = str(merged_config.get("host") or "").strip()
    port = int(merged_config.get("port") or 514)
    protocol = str(merged_config.get("protocol") or "udp").lower()
    framing = str(merged_config.get("framing") or "rfc5424")
    facility = str(merged_config.get("facility") or "local0")
    if not host:
        return {"sent": 0, "failed": len(records),
                "errors": ["host is required"]}

    payloads = [
        _format_message(json.dumps(r, default=str),
                        framing=framing, facility=facility)
        for r in records
    ]

    try:
        if protocol == "udp":
            await _send_udp(host, port, payloads)
        elif protocol == "tcp":
            await _send_tcp(host, port, payloads, use_tls=False)
        elif protocol == "tls":
            await _send_tcp(
                host, port, payloads, use_tls=True,
                merged_config=merged_config,
            )
        else:
            return {"sent": 0, "failed": len(records),
                    "errors": [f"unknown protocol: {protocol!r}"]}
    except Exception as e:  # noqa: BLE001
        return {"sent": 0, "failed": len(records),
                "errors": [f"{type(e).__name__}: {e}"]}

    return {"sent": len(records), "failed": 0, "errors": []}
