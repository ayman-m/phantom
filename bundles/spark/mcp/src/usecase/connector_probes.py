"""Per-connector health probes — shared between the /connectors and
/instances routes.

Earlier the probe lived in api/connectors.py but the /instances
routes also need to call it (POST /api/v1/instances/{id}/test). Lifted
to the usecase layer so both API modules can import without tripping
a circular import (api/instances.py → api/connectors.py).

`PROBE_IMPLEMENTED` lists the connector_ids with a probe wired here: all nine
bundle connectors. A connector outside that set (an operator-uploaded one) has no
built-in test; the caller answers `probe_implemented: false` and the UI says so.

What a probe may do
-------------------
A probe runs whenever the operator presses Test Connection, unprompted by the
agent, so it is READ-ONLY by construction:

  * it never sends an event, a log line or a WS-Management request, and never
    makes a POST to an operator collector, broker or tenant for the
    sender connectors. xlog, caldera and the Cortex probes read; xsiam and
    cortex-xdr POST to a read-only listing endpoint (the same one the
    connector's own tool uses);
  * http-sender and wec-sender prove REACHABILITY only (an unauthenticated GET
    to the collector URL, or to the Cribl endpoint for an instance that has only
    that; a bare TCP connect to the broker port). They cannot
    prove the collector key or the client certificate without sending an event
    or a WS-Man request, so their success message says so and points at the
    connector's own explicit check (`send_test_event`; `list_subscriptions`);
  * the sender probes never put a secret on the wire: the key slot is only
    checked for presence.

Result shape: `probe()` returns a `ProbeResult` (ok, error, is_auth_error and a
`message` for the operator on success). `real_probe()` is the original
`(ok, error, is_auth_error)` tuple form kept for api/connectors.py.

Container check
---------------
Every bundle connector runs as its own container (`runtimeMapping.style:
container`); the agent reaches its tools through the container's
`container_url`. With `check_container=True` the probe first does
`GET <container_url>/health` (served by the connector runtime), so a connector
whose upstream is fine but whose container is not running reports that instead
of passing.

Callers pass `config` and `secrets` dicts explicitly so an
operator-edited instance config (e.g. a custom Caldera port) is
honored rather than silently ignored; absent kwargs fall through to
the env defaults so the legacy /connectors/{id}/probe endpoint keeps
working without instance context.

Naming convention: instance config keys vary depending on creation
path. The bindsInstances templates in bundles/spark/manifest.yaml
use `baseUrl`/`apiToken`/`apiKey`. Older auto-migrated instances use
connector-prefixed names (`xlog_url`, `caldera_api_key`). The probe
checks both.

TLS: `PHANTOM_TLS_VERIFY=1` turns verification on for the compose-internal
callees (xlog, caldera, the browser sidecar, connector containers), which serve
the agent's auto-generated certificate. Internet callees (Cortex tenants, the
Cortex docs, an XSIAM HTTP collector) are always verified, exactly as the
connectors do, so a probe cannot pass where the connector would fail TLS;
http-sender's own `verifyTls` setting governs its collector.

Timeouts: the agent's proxy to this server gives up after 15 s, so one probe is
bounded by `PROBE_DEADLINE_S` (12 s): the container check takes at most 3 s and
each upstream request at most 5 s (http-sender: its `timeoutSeconds`, capped at
8 s).
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import socket
import ssl
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx


# Every bundle connector has a probe. The ids are the connector directories under
# bundles/spark/connectors (minus `_runtime`); tests/test_connector_probes.py
# pins that equality so a new bundle connector cannot ship without one.
PROBE_IMPLEMENTED: frozenset[str] = frozenset(
    {
        "xlog",
        "caldera",
        "xsiam",
        "cortex-docs",
        "cortex-content",
        "cortex-xdr",
        "web",
        "http-sender",
        "wec-sender",
    }
)

PROBE_DEADLINE_S = 12.0
_CONTAINER_TIMEOUT_S = 3.0
_REQUEST_TIMEOUT_S = 5.0
_SENDER_TIMEOUT_CAP_S = 8.0


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    error: str | None = None
    is_auth_error: bool = False
    # Shown to the operator on success: what the probe proved and, for the sender
    # connectors, what it did not.
    message: str | None = None

    def as_tuple(self) -> tuple[bool, str | None, bool]:
        return (self.ok, self.error, self.is_auth_error)


def _ok(message: str | None = None) -> ProbeResult:
    return ProbeResult(True, None, False, message)


def _fail(error: str, *, auth: bool = False) -> ProbeResult:
    return ProbeResult(False, error, auth, None)


def _first(*candidates: Any) -> str:
    """Return the first non-empty stringable candidate, or ''."""
    for c in candidates:
        if c is None:
            continue
        s = str(c).strip()
        if s:
            return s
    return ""


def _internal_verify() -> bool:
    """TLS verification for compose-internal callees (self-signed by default)."""
    return os.environ.get("PHANTOM_TLS_VERIFY", "0") == "1"


def _new_client(**kwargs: Any) -> httpx.AsyncClient:
    """The one place an HTTP client is built, so tests can swap in a mock transport."""
    return httpx.AsyncClient(**kwargs)


async def _open_connection(host: str, port: int) -> tuple[Any, Any]:
    """The one place a raw TCP connection is opened (tests patch it)."""
    return await asyncio.open_connection(host, port)


async def _resolve_ipv4(host: str) -> str | None:
    """First IPv4 address of `host`, or None when it cannot be resolved."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
    return infos[0][4][0] if infos else None


def _tls_reason(exc: BaseException) -> str | None:
    """A TLS failure's reason when `exc` (or its cause chain) is an ssl error."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, ssl.SSLError):
            return getattr(cur, "reason", None) or str(cur)
        cur = cur.__cause__ or cur.__context__
    return None


def _describe_transport_error(exc: Exception, target: str) -> str:
    """One operator-readable line for a transport failure. Never carries a header."""
    tls = _tls_reason(exc)
    if tls:
        return f"TLS error talking to {target}: {tls}"
    if isinstance(exc, httpx.TimeoutException):
        return f"timed out talking to {target}"
    if isinstance(exc, httpx.ConnectError):
        return f"cannot connect to {target}: {exc}"
    return f"{type(exc).__name__} talking to {target}: {exc}"


def _err_msg(response: httpx.Response) -> str:
    """The Cortex `err_msg` of an error body (or a short slice of the text)."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:160].strip()
    if isinstance(body, dict):
        for holder in (body, body.get("reply")):
            if isinstance(holder, dict):
                for key in ("err_msg", "err_extra", "error"):
                    if holder.get(key):
                        return str(holder[key])[:160]
    return ""


# ── container check ───────────────────────────────────────────────────────────


async def _check_container(container_url: str | None) -> str | None:
    """None when the instance's connector container answers /health, else the problem."""
    if not container_url:
        return (
            "the connector container has not started (the instance has no container_url yet); "
            "its tools cannot run until it does"
        )
    url = f"{container_url.rstrip('/')}/health"
    try:
        async with _new_client(
            timeout=httpx.Timeout(_CONTAINER_TIMEOUT_S, connect=2.0), verify=_internal_verify()
        ) as c:
            r = await c.get(url)
    except Exception as exc:  # noqa: BLE001 - any failure is "container unreachable"
        return f"connector container unreachable: {_describe_transport_error(exc, container_url)}"
    if r.status_code != 200:
        return f"connector container at {container_url} answered HTTP {r.status_code} on /health"
    return None


# ── Cortex public API (xsiam, cortex-xdr) ─────────────────────────────────────


def _papi_base(url: str) -> str:
    """Normalise a tenant API URL exactly as the connectors' Fetcher does: end at /public_api/v1."""
    base = url.rstrip("/")
    if "/public_api" not in base:
        return f"{base}/public_api/v1"
    if not base.endswith("/public_api/v1"):
        return base.split("/public_api")[0].rstrip("/") + "/public_api/v1"
    return base


def _classify_papi(r: httpx.Response, product: str, where: str) -> ProbeResult:
    """Map a Cortex public API answer onto a probe result.

    401 is the genuine authentication failure (a wrong key or ID; also what an
    Advanced key gets, because the connector sends a plain header). A 403 is not
    necessarily one: Cortex answers 403 `Datasets not found` when a dataset does
    not exist, which means the key authenticated. Any other 403 is the key's role
    lacking permission for the endpoint.
    """
    if r.status_code == 200:
        return _ok(f"{product} accepted the API key and ID")
    msg = _err_msg(r)
    if r.status_code == 401:
        return _fail(
            f"HTTP 401 from {product}: the API key or ID was rejected "
            "(use a Standard key; the connector does not sign Advanced-key requests)",
            auth=True,
        )
    if r.status_code == 403:
        if "datasets not found" in msg.lower():
            return _ok(f"{product} accepted the API key and ID (the tenant reports no datasets yet)")
        detail = f": {msg}" if msg else ""
        return _fail(
            f"HTTP 403 from {product}{detail} (the key authenticated but its role lacks permission for this call)",
            auth=True,
        )
    if r.status_code == 402:
        return _fail(f"HTTP 402 from {product}: the tenant lacks the licence for this API")
    detail = f": {msg}" if msg else ""
    return _fail(f"HTTP {r.status_code} from {where}{detail}")


# ── per-connector probes ──────────────────────────────────────────────────────

Handler = Callable[[dict[str, Any], dict[str, Any]], Awaitable[ProbeResult]]


async def _probe_xlog(cfg: dict[str, Any], sec: dict[str, Any]) -> ProbeResult:
    url = _first(
        cfg.get("baseUrl"),
        cfg.get("xlog_url"),
        cfg.get("url"),
        os.environ.get("XLOG_URL"),
        # Final fallback is https: xlog serves HTTPS unconditionally
        # (TLS via the shared phantom_tls volume). It only applies if
        # ALL upstream sources are unset (rare in production where
        # compose always sets XLOG_URL), but an http fallback would
        # get "Empty reply from server" from the HTTPS-only listener
        # and surface a misleading connector-down signal.
        "https://xlog:8000",
    ).rstrip("/")
    token = _first(
        sec.get("apiToken"),
        sec.get("xlog_api_key"),
        sec.get("api_token"),
        os.environ.get("XLOG_API_KEY"),
        os.environ.get("XLOG_API_TOKEN"),
    )
    if not token:
        return _fail("apiToken is not configured (xlog refuses every request but /health without it)", auth=True)
    headers = {"Authorization": token}

    # The probe sends ONE request per step against the configured URL and
    # reports the verbatim outcome. No silent scheme flipping, no retries with
    # the opposite protocol: if the stored baseUrl is wrong (e.g. http:// against
    # an HTTPS-only listener after a TLS rollout) the probe's job is to surface
    # the failure so the operator updates the config via /connectors.
    #
    # `/health` is the one path xlog answers without a token (docker healthchecks
    # need that), so on its own it would pass with a wrong token. Step 2 reads
    # `/api/v1/worker-rates`, an authenticated read-only snapshot.
    async with _new_client(timeout=httpx.Timeout(_REQUEST_TIMEOUT_S, connect=3.0), verify=_internal_verify()) as c:
        r = await c.get(f"{url}/health")
        if r.status_code != 200:
            return _fail(f"HTTP {r.status_code} from {url}/health")
        r = await c.get(f"{url}/api/v1/worker-rates", headers=headers)
    if r.status_code == 200:
        return _ok("xlog is reachable and accepted the API token")
    if r.status_code == 401:
        return _fail(f"HTTP 401 from {url}: the API token was rejected", auth=True)
    if r.status_code == 503:
        return _fail(f"HTTP 503 from {url}: xlog has no API token configured (XLOG_API_KEY is unset on the xlog service)")
    return _fail(f"HTTP {r.status_code} from {url}/api/v1/worker-rates")


async def _probe_caldera(cfg: dict[str, Any], sec: dict[str, Any]) -> ProbeResult:
    url = _first(
        cfg.get("baseUrl"),
        cfg.get("caldera_url"),
        cfg.get("url"),
        os.environ.get("CALDERA_URL"),
        "http://caldera:8888",
    ).rstrip("/")
    # GET /api/v2/health with the operator's API key in the KEY header. Caldera
    # puts /api/v2/* behind the same KEY-header auth the connector uses for its
    # tool calls (bundles/spark/connectors/caldera/src/connector.py::
    # _caldera_request), and the health handler is not exempt (third_party/
    # caldera app/api/v2/handlers/health_api.py), so a wrong key answers 401.
    # A root-page probe would rubber-stamp any caldera that is up.
    api_key = _first(
        sec.get("apiKey"),
        sec.get("api_key"),
        sec.get("caldera_api_key"),
        os.environ.get("CALDERA_API_KEY"),
    )
    if not api_key:
        return _fail("apiKey is not configured", auth=True)
    headers = {"KEY": api_key, "Content-Type": "application/json"}
    async with _new_client(timeout=httpx.Timeout(_REQUEST_TIMEOUT_S, connect=3.0), verify=_internal_verify()) as c:
        r = await c.get(f"{url}/api/v2/health", headers=headers)
    if r.status_code == 200:
        return _ok("Caldera is reachable and accepted the API key")
    if r.status_code in (401, 403):
        return _fail(f"HTTP {r.status_code} from {url}/api/v2/health (API key rejected)", auth=True)
    return _fail(f"HTTP {r.status_code} from {url}/api/v2/health")


async def _probe_xsiam(cfg: dict[str, Any], sec: dict[str, Any]) -> ProbeResult:
    # XSIAM PAPI auth: Authorization=<Standard api_key> + x-xdr-auth-id=<id>.
    # Endpoint: POST /public_api/v1/xql/get_datasets with an empty body: a
    # read-only listing, the same call the connector's xsiam_get_datasets tool
    # makes. Config + secret names are the uniform api_url/api_id/api_key (as the
    # Cortex XDR connector); the legacy papi* names are accepted on read.
    base = _first(
        cfg.get("api_url"),
        cfg.get("papiUrl"),
        cfg.get("baseUrl"),
        cfg.get("xsiam_papi_url"),
        os.environ.get("CORTEX_MCP_PAPI_URL"),
        os.environ.get("XSIAM_API_URL"),
    )
    if not base:
        return _fail("api_url is not configured")
    api_key = _first(
        sec.get("api_key"),
        sec.get("papiAuthHeader"),
        os.environ.get("CORTEX_MCP_PAPI_AUTH_HEADER"),
        os.environ.get("XSIAM_API_KEY"),
    )
    api_key_id = _first(
        cfg.get("api_id"),
        cfg.get("papiAuthId"),
        cfg.get("xsiam_api_id"),
        sec.get("papiAuthId"),  # belt-and-suspenders if migrated to a secret
        os.environ.get("CORTEX_MCP_PAPI_AUTH_ID"),
        os.environ.get("XSIAM_API_ID"),
    )
    if not api_key:
        return _fail("api_key (Authorization header) is not configured", auth=True)
    if not api_key_id:
        return _fail("api_id (X-Auth-ID header) is not configured", auth=True)
    base = _papi_base(base)
    headers = {"Authorization": api_key, "x-xdr-auth-id": str(api_key_id), "Content-Type": "application/json"}
    # The connector's PAPI client follows redirects; so does the probe.
    async with _new_client(
        timeout=httpx.Timeout(_REQUEST_TIMEOUT_S, connect=3.0), verify=True, follow_redirects=True
    ) as c:
        r = await c.post(f"{base}/xql/get_datasets", headers=headers, json={})
    return _classify_papi(r, "XSIAM", f"{base}/xql/get_datasets")


async def _probe_cortex_xdr(cfg: dict[str, Any], sec: dict[str, Any]) -> ProbeResult:
    # Same auth as XSIAM (Standard key as a plain Authorization header +
    # x-xdr-auth-id). Endpoint: POST /public_api/v1/incidents/get_incidents with
    # a one-row window: read-only, and the call behind the connector's headline
    # tool, so a 200 also proves the key's role can read incidents. (The
    # documented GET /healthcheck needs the same two headers and an RBAC
    # permission, so it would not be a lighter check on the role.)
    base = _first(cfg.get("api_url"), cfg.get("baseUrl"))
    if not base:
        return _fail("api_url is not configured")
    api_key = _first(sec.get("api_key"))
    api_id = _first(cfg.get("api_id"), sec.get("api_id"))
    if not api_key:
        return _fail("api_key (Authorization header) is not configured", auth=True)
    if not api_id:
        return _fail("api_id (X-Auth-ID header) is not configured", auth=True)
    base = _papi_base(base)
    headers = {"Authorization": api_key, "x-xdr-auth-id": str(api_id), "Content-Type": "application/json"}
    async with _new_client(timeout=httpx.Timeout(_REQUEST_TIMEOUT_S, connect=3.0), verify=True) as c:
        r = await c.post(
            f"{base}/incidents/get_incidents",
            headers=headers,
            json={"request_data": {"search_from": 0, "search_to": 1}},
        )
    return _classify_papi(r, "Cortex XDR", f"{base}/incidents/get_incidents")


async def _probe_cortex_docs(cfg: dict[str, Any], sec: dict[str, Any]) -> ProbeResult:
    # The Cortex documentation is on GitBook. Probe the XSIAM book root as
    # Markdown, public and light. Only a 200 counts as healthy: treating any 4xx
    # as "reachable" would let a retired API keep looking fine.
    base = "https://cortex-docs.paloaltonetworks.com"
    async with _new_client(
        timeout=httpx.Timeout(_REQUEST_TIMEOUT_S, connect=3.0), verify=True, follow_redirects=True
    ) as c:
        r = await c.get(f"{base}/cortex-xsiam.md", headers={"Accept": "text/markdown"})
    if r.status_code == 200:
        return _ok("the Cortex documentation site is reachable")
    return _fail(f"HTTP {r.status_code} from {base}/cortex-xsiam.md")


async def _probe_cortex_content(cfg: dict[str, Any], sec: dict[str, Any]) -> ProbeResult:
    # Verifies the bundled catalog is present and readable. The catalog ships in
    # the agent image; if it is missing the image was built without it. This does
    # NOT prove the connector container's own copy: its /health (the container
    # check) only says the process is alive.
    from pathlib import Path as _Path

    # The catalog lives at /app/bundle/connectors/cortex-content/baked/ in the
    # agent container. In tests / dev, walk up from this module to
    # bundles/spark/connectors/cortex-content/baked/.
    candidates = [
        _Path("/app/bundle/connectors/cortex-content/baked/_manifest.json"),
        _Path(__file__).resolve().parents[3] / "connectors" / "cortex-content" / "baked" / "_manifest.json",
    ]
    if any(p.is_file() for p in candidates):
        return _ok("the bundled content catalog is present")
    return _fail("cortex-content catalog directory is missing from the bundle")


def _cdp_http_url(raw: str) -> str | None:
    """The http(s) form of a CDP URL (ws:// -> http://, wss:// -> https://), or None if unusable."""
    parts = urlsplit(raw.strip())
    scheme = {"ws": "http", "wss": "https", "http": "http", "https": "https"}.get(parts.scheme.lower())
    if not scheme or not parts.hostname:
        return None
    return urlunsplit((scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


async def _probe_web(cfg: dict[str, Any], sec: dict[str, Any]) -> ProbeResult:
    raw = _first(cfg.get("cdp_url"), "http://phantom-browser:9222")
    http_url = _cdp_http_url(raw)
    if not http_url:
        return _fail(f"cdp_url {raw!r} is not a ws://, wss://, http:// or https:// URL with a host")
    parts = urlsplit(http_url)
    host = parts.hostname or ""
    # Chromium's DevTools server answers HTTP 500 to a Host header that is not an
    # IP address or localhost, so (as the connector does before it hands the URL to
    # Playwright) resolve the name first and ask the IP.
    netloc = parts.netloc
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if host != "localhost":
            try:
                ip = await _resolve_ipv4(host)
            except OSError as exc:
                return _fail(f"cannot resolve the browser host {host!r}: {exc} (is the phantom-browser container up? compose profile 'browser')")
            if ip:
                netloc = f"{ip}:{parts.port}" if parts.port else ip
    url = urlunsplit((parts.scheme, netloc, parts.path, "", "")) + "/json/version"
    try:
        async with _new_client(
            timeout=httpx.Timeout(_REQUEST_TIMEOUT_S, connect=3.0), verify=_internal_verify()
        ) as c:
            r = await c.get(url)
    except Exception as exc:  # noqa: BLE001
        return _fail(_describe_transport_error(exc, f"the browser at {raw}"))
    if r.status_code != 200:
        return _fail(f"HTTP {r.status_code} from {raw}/json/version")
    try:
        body = r.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or not (body.get("webSocketDebuggerUrl") or body.get("Browser")):
        return _fail(f"{raw}/json/version did not return a Chrome DevTools description (is this the browser sidecar?)")
    return _ok(f"the browser sidecar is reachable ({body.get('Browser') or 'DevTools endpoint'})")


def _truthy(value: Any, default: bool = True) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off")
    if value is None:
        return default
    return bool(value)


def _number(value: Any, default: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return n if n > 0 else default


def _count_additional(raw: Any) -> int:
    if isinstance(raw, list):
        return len(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except ValueError:
            return 0
        return len(data) if isinstance(data, list) else 0
    return 0


# The path every Cribl integration endpoint ends in; keep in step with PATH in
# bundles/spark/connectors/http-sender/src/cribl.py (the connector's own check).
_CRIBL_PATH = "/logs/v1/integrated/cribl/data"


async def _probe_http_sender_cribl(cfg: dict[str, Any], sec: dict[str, Any], url: str) -> ProbeResult:
    """The Cribl-only form of the http-sender probe: config check + reachability of the Cribl endpoint.

    Same rule as the collector probe: one unauthenticated GET, no body, no token, no event.
    """
    parts = urlsplit(url)
    problems = []
    if parts.scheme != "https" or not parts.hostname:
        # The connector refuses a non-https Cribl URL (the token travels in a header).
        problems.append("criblUrl must be an https:// URL with a host name")
    elif not parts.path.endswith(_CRIBL_PATH):
        problems.append(f"criblUrl must end in {_CRIBL_PATH} (an HTTP collector's /logs/v1/event URL does not belong here)")
    if not _first(sec.get("criblToken")):
        problems.append("the criblToken secret is not set")
    if problems:
        return _fail("; ".join(problems), auth=problems == ["the criblToken secret is not set"])
    verify = _truthy(cfg.get("verifyTls"), True)
    timeout = min(_number(cfg.get("timeoutSeconds"), 15.0), _SENDER_TIMEOUT_CAP_S)
    try:
        async with _new_client(timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0)), verify=verify, follow_redirects=False) as c:
            r = await c.get(url)
    except Exception as exc:  # noqa: BLE001
        return _fail(_describe_transport_error(exc, parts.netloc))
    n_extra = _count_additional(cfg.get("additionalDestinations"))
    skipped = f" Not contacted: {n_extra} additional destination(s)." if n_extra else ""
    return _ok(
        f"the Cribl endpoint at {parts.netloc} is reachable (HTTP {r.status_code} to an unauthenticated GET); "
        "the Cribl token was not sent and is NOT verified, and no event was sent. "
        "Run the connector's send_test_event on a cribl_<source> destination for the end-to-end check." + skipped
    )


async def _probe_http_sender(cfg: dict[str, Any], sec: dict[str, Any]) -> ProbeResult:
    """Config check + reachability of the PRIMARY collector (or, for a Cribl-only instance, of the Cribl endpoint).
    Sends no event and no key."""
    url = _first(cfg.get("collectorUrl"))
    vendor, product = _first(cfg.get("vendor")), _first(cfg.get("product"))
    cribl_url = _first(cfg.get("criblUrl"))
    if cribl_url and not url and not vendor and not product:
        return await _probe_http_sender_cribl(cfg, sec, cribl_url)
    problems = []
    if not url:
        problems.append("collectorUrl is not set")
    if not vendor or not product:
        problems.append("vendor and product are required (they name the destination)")
    if not _first(sec.get("collectorKey")):
        problems.append("the collectorKey secret is not set")
    parts = urlsplit(url) if url else None
    if parts is not None and (parts.scheme != "https" or not parts.hostname):
        # The connector refuses a non-https collector URL, so a pass here would be a lie.
        problems.append("collectorUrl must be an https:// URL with a host name")
    if problems:
        return _fail("; ".join(problems), auth=problems == ["the collectorKey secret is not set"])
    verify = _truthy(cfg.get("verifyTls"), True)
    timeout = min(_number(cfg.get("timeoutSeconds"), 15.0), _SENDER_TIMEOUT_CAP_S)
    # One unauthenticated GET: no body, no Authorization header. A collector
    # answers it with 401/404/405 or similar and that is enough: DNS, TCP, TLS and
    # the HTTP layer work. Nothing here can create an event.
    try:
        async with _new_client(timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0)), verify=verify, follow_redirects=False) as c:
            r = await c.get(url)
    except Exception as exc:  # noqa: BLE001
        return _fail(_describe_transport_error(exc, parts.netloc))
    not_contacted = []
    n_extra = _count_additional(cfg.get("additionalDestinations"))
    if n_extra:
        not_contacted.append(f"{n_extra} additional destination(s)")
    if _first(cfg.get("criblUrl")):
        not_contacted.append("the Cribl endpoint")
    skipped = f" Not contacted: {' and '.join(not_contacted)}." if not_contacted else ""
    return _ok(
        f"the collector at {parts.netloc} is reachable (HTTP {r.status_code} to an unauthenticated GET); "
        "the collector key was not sent and is NOT verified, and no event was sent. "
        "Run the connector's send_test_event for the end-to-end check." + skipped
    )


def _wec_host_port(value: str) -> tuple[str, int] | str:
    """(host, port) of a Subscription Manager value, or the problem. Applies the same checks as the connector's parser (wec-sender/src/wsman.py)."""
    raw = (value or "").strip()
    if not raw:
        return "subscriptionManagerUrl is not set"
    url = raw
    if not raw.lower().startswith(("http://", "https://")):
        parts: dict[str, str] = {}
        for token in raw.split(","):
            key, sep, val = token.strip().partition("=")
            if not sep:
                return "subscriptionManagerUrl: expected Server=<https url>[,Refresh=<s>][,IssuerCA=<sha1>]"
            parts[key.strip().lower()] = val.strip()
        if "server" not in parts:
            return "subscriptionManagerUrl has no Server=<https url> part"
        url = parts["server"]
        if parts.get("refresh"):
            try:
                int(parts["refresh"])
            except ValueError:
                return "subscriptionManagerUrl: Refresh must be a whole number of seconds"
        if parts.get("issuerca") and not re.fullmatch(r"[0-9A-Fa-f]{40}", re.sub(r"[\s:]", "", parts["issuerca"])):
            return "IssuerCA must be a 40-hex-digit SHA-1 thumbprint"
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return "subscriptionManagerUrl must be an https URL with a host name"
    try:
        port = parsed.port or 5986
    except ValueError:
        return "subscriptionManagerUrl has an invalid port"
    return parsed.hostname, port


async def _probe_wec_sender(cfg: dict[str, Any], sec: dict[str, Any]) -> ProbeResult:
    """Config check + a bare TCP connect to the Broker VM's WEC port. No TLS, no WS-Man request."""
    target = _wec_host_port(_first(cfg.get("subscriptionManagerUrl")))
    problems = []
    if isinstance(target, str):
        problems.append(target)
    for slot in ("clientPfx", "clientPfxPassword"):
        if not _first(sec.get(slot)):
            problems.append(f"the {slot} secret is not set")
    if problems:
        only_secrets = not isinstance(target, str)
        return _fail("; ".join(problems), auth=only_secrets)
    host, port = target  # type: ignore[misc] - narrowed: a str target was returned above
    timeout = min(_number(cfg.get("timeoutSeconds"), 30.0), _REQUEST_TIMEOUT_S)
    writer = None
    try:
        _reader, writer = await asyncio.wait_for(_open_connection(host, port), timeout)
    except asyncio.TimeoutError:
        return _fail(f"timed out connecting to {host}:{port} (is the Broker VM's Windows Event Collector applet on, and TCP {port} open?)")
    except OSError as exc:
        return _fail(f"cannot connect to {host}:{port}: {exc}")
    finally:
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 1.0)
            except Exception:  # noqa: BLE001 - closing a probe socket is best effort
                pass
    return _ok(
        f"TCP {port} on {host} accepts connections; the client certificate, its CA and the WS-Management "
        "exchange are NOT verified, and no event was sent. Run the connector's list_subscriptions "
        "(read-only) for the end-to-end check."
    )


_HANDLERS: dict[str, Handler] = {
    "xlog": _probe_xlog,
    "caldera": _probe_caldera,
    "xsiam": _probe_xsiam,
    "cortex-xdr": _probe_cortex_xdr,
    "cortex-docs": _probe_cortex_docs,
    "cortex-content": _probe_cortex_content,
    "web": _probe_web,
    "http-sender": _probe_http_sender,
    "wec-sender": _probe_wec_sender,
}


async def _run(
    connector_id: str,
    cfg: dict[str, Any],
    sec: dict[str, Any],
    container_url: str | None,
    check_container: bool,
) -> ProbeResult:
    if check_container:
        problem = await _check_container(container_url)
        if problem:
            return _fail(problem)
    result = await _HANDLERS[connector_id](cfg, sec)
    if result.ok and check_container:
        return ProbeResult(True, None, False, (result.message or "") + " The connector container is up.")
    return result


async def probe(
    connector_id: str,
    *,
    config: dict[str, Any] | None = None,
    secrets: dict[str, Any] | None = None,
    container_url: str | None = None,
    check_container: bool = False,
) -> ProbeResult:
    """Run the connector's read-only health probe.

    Resolution order for connection details: explicit `config`/`secrets` (the
    operator's form values), then environment variables (legacy default, used
    when no instance context is available).
    """
    if connector_id not in _HANDLERS:
        # A connector id listed in PROBE_IMPLEMENTED without a handler must fail,
        # not pass: a silent True here is how a probe goes stale.
        return _fail(f"no built-in test exists for connector {connector_id!r}")
    try:
        return await asyncio.wait_for(
            _run(connector_id, config or {}, secrets or {}, container_url, check_container),
            PROBE_DEADLINE_S,
        )
    except asyncio.TimeoutError:
        return _fail(f"the test did not finish within {int(PROBE_DEADLINE_S)} seconds")
    except httpx.HTTPError as exc:
        return _fail(f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001 - best-effort probe
        return _fail(f"{type(exc).__name__}: {exc}")


async def real_probe(
    connector_id: str,
    *,
    config: dict[str, Any] | None = None,
    secrets: dict[str, Any] | None = None,
    container_url: str | None = None,
    check_container: bool = False,
) -> tuple[bool, str | None, bool]:
    """`probe()` as the `(ok, error_message, is_auth_error)` tuple."""
    return (
        await probe(
            connector_id,
            config=config,
            secrets=secrets,
            container_url=container_url,
            check_container=check_container,
        )
    ).as_tuple()
