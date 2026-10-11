"""Per-connector health probes — shared between the /connectors and
/instances routes.

Earlier the probe lived in api/connectors.py but the /instances
routes also need to call it (POST /api/v1/instances/{id}/test). Lifted
to the usecase layer so both API modules can import without tripping
a circular import (api/instances.py → api/connectors.py).

`PROBE_IMPLEMENTED` lists connector_ids with a real probe wired here.
Other connectors (notably xsiam, which would need a PAPI roundtrip)
fall back to the legacy reset-to-pending behavior in the caller.

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
"""

from __future__ import annotations

import os
from typing import Any

import httpx


# http-sender and wec-sender are deliberately NOT listed: the only honest
# probe is to post an event to the operator's collector or broker, and a probe
# runs unprompted whenever the Test button is pressed. Their own tools are the
# explicit test: `send_test_event` (one identifiable event, reports whether the
# destination accepted it) and, for wec-sender, `list_subscriptions` (a read-only
# enumeration that proves the certificate and the route).
PROBE_IMPLEMENTED: frozenset[str] = frozenset(
    {"xlog", "caldera", "xsiam", "cortex-docs", "cortex-content", "cortex-xdr"}
)


def _first(*candidates: Any) -> str:
    """Return the first non-empty stringable candidate, or ''."""
    for c in candidates:
        if c is None:
            continue
        s = str(c).strip()
        if s:
            return s
    return ""


async def real_probe(
    connector_id: str,
    *,
    config: dict[str, Any] | None = None,
    secrets: dict[str, Any] | None = None,
) -> tuple[bool, str | None, bool]:
    """Run a real health probe against the connector's upstream.

    Resolution order for connection details:
      1. explicit `config`/`secrets` kwargs (operator's form values)
      2. environment variables (legacy default; used when no
         instance context is available, e.g. the /connectors probe)

    Returns (ok, error_message, is_auth_error). PHANTOM_TLS_VERIFY=0
    (default in self-signed mode) tolerates the agent's auto-generated
    cert for compose-internal HTTPS callees.
    """
    cfg = config or {}
    sec = secrets or {}
    timeout = httpx.Timeout(5.0, connect=3.0)
    verify = os.environ.get("PHANTOM_TLS_VERIFY", "0") == "1"

    try:
        if connector_id == "xlog":
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
            headers = {"Authorization": token} if token else {}

            # Probe sends ONE request against the configured URL and
            # reports the verbatim outcome. No silent scheme flipping,
            # no retries with the opposite protocol — if the operator's
            # stored baseUrl is wrong (e.g. http:// against an
            # HTTPS-only listener after a TLS rollout), the probe's job
            # is to surface the failure so the operator updates the
            # config explicitly via /connectors. The probe is a test,
            # not a self-healer.
            async with httpx.AsyncClient(timeout=timeout, verify=verify) as c:
                r = await c.get(f"{url}/health", headers=headers)
            if r.status_code == 200:
                return (True, None, False)
            if r.status_code in (401, 403):
                return (False, f"HTTP {r.status_code} from {url}", True)
            return (False, f"HTTP {r.status_code} from {url}", False)

        if connector_id == "caldera":
            url = _first(
                cfg.get("baseUrl"),
                cfg.get("caldera_url"),
                cfg.get("url"),
                os.environ.get("CALDERA_URL"),
                "http://caldera:8888",
            ).rstrip("/")
            # Probe GET /api/v2/health (not the unauthenticated root login
            # page) with the operator's API key in the KEY header. Caldera's API protects /api/v2/* endpoints
            # with the same KEY-header convention the connector itself
            # uses for tool calls (see bundles/spark/connectors/caldera/
            # src/connector.py::_caldera_request). This way Test
            # Connection actually validates the key the operator typed
            # — wrong key returns 401, which we surface with
            # is_auth_error=true so the UI can flip the badge to amber.
            #
            # A root-page probe would rubber-stamp any caldera whose
            # service is up, even with a bad API key, and the operator
            # would only learn the key was wrong on the first caldera
            # tool call (which then 401s).
            api_key = _first(
                sec.get("apiKey"),
                sec.get("api_key"),
                sec.get("caldera_api_key"),
                os.environ.get("CALDERA_API_KEY"),
            )
            if not api_key:
                return (False, "apiKey is not configured", True)
            headers = {"KEY": api_key, "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=timeout, verify=verify) as c:
                r = await c.get(f"{url}/api/v2/health", headers=headers)
            if r.status_code == 200:
                return (True, None, False)
            if r.status_code in (401, 403):
                return (
                    False,
                    f"HTTP {r.status_code} from {url}/api/v2/health "
                    "(API key rejected)",
                    True,
                )
            return (
                False,
                f"HTTP {r.status_code} from {url}/api/v2/health",
                False,
            )

        if connector_id == "xsiam":
            # XSIAM PAPI auth: Authorization=<api_key> + x-xdr-auth-id=<id>.
            # Probe endpoint: POST /public_api/v1/xql/get_datasets with
            # empty body. Lightweight, authenticated, no side effects —
            # the connector already uses this in xsiam_get_datasets()
            # at bundles/spark/connectors/xsiam/src/connector.py.
            #
            # Config + secret names are the uniform api_url/api_id/api_key
            # (matches the Cortex XDR connector). Legacy papi* names are
            # still accepted on read so older instances keep working; new
            # instances write the uniform names.
            base = _first(
                cfg.get("api_url"),
                cfg.get("papiUrl"),
                cfg.get("baseUrl"),
                cfg.get("xsiam_papi_url"),
                os.environ.get("CORTEX_MCP_PAPI_URL"),
                os.environ.get("XSIAM_API_URL"),
            ).rstrip("/")
            if not base:
                return (False, "api_url is not configured", False)
            # Connector normalizes the URL to end at /public_api/v1; do
            # the same here so operators can paste either form into the
            # setup field.
            if "/public_api/v1" not in base:
                base = base.split("/public_api")[0].rstrip("/") + "/public_api/v1"
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
                return (False, "api_key (Authorization header) is not configured", True)
            if not api_key_id:
                return (False, "api_id (X-Auth-ID header) is not configured", True)
            headers = {
                "Authorization": api_key,
                "x-xdr-auth-id": str(api_key_id),
                "Content-Type": "application/json",
            }
            async with httpx.AsyncClient(timeout=timeout, verify=verify) as c:
                r = await c.post(
                    f"{base}/xql/get_datasets",
                    headers=headers,
                    json={},
                )
            if r.status_code == 200:
                return (True, None, False)
            if r.status_code in (401, 403):
                return (False, f"HTTP {r.status_code} from XSIAM PAPI", True)
            return (
                False,
                f"HTTP {r.status_code} from {base}/xql/get_datasets",
                False,
            )

        if connector_id == "cortex-docs":
            # The Cortex documentation is on GitBook (cortex-docs.paloaltonetworks.com).
            # Probe: the XSIAM book root as Markdown, public and light. Only a 200
            # counts as healthy: treating any 4xx as "reachable" would let a retired
            # API keep looking fine.
            base = "https://cortex-docs.paloaltonetworks.com"
            async with httpx.AsyncClient(timeout=timeout, verify=verify, follow_redirects=True) as c:
                r = await c.get(f"{base}/cortex-xsiam.md", headers={"Accept": "text/markdown"})
            if r.status_code == 200:
                return (True, None, False)
            return (False, f"HTTP {r.status_code} from {base}/cortex-xsiam.md", False)

        if connector_id == "cortex-xdr":
            # Probe the Cortex XDR Public API.
            # Same auth model as XSIAM (Authorization + x-xdr-auth-id)
            # but XDR has a dedicated healthcheck endpoint we can hit
            # without any side effects.
            #
            # Probe choice: POST /public_api/v1/incidents/get_incidents
            # with an empty request_data — XDR returns 200 with zero
            # results when filters are empty, OR 400 if it interprets
            # the body as malformed. Either way, the upstream is
            # reachable + the creds are valid (we'd get 401 otherwise).
            base = _first(
                cfg.get("api_url"),
                cfg.get("baseUrl"),
            ).rstrip("/")
            if not base:
                return (False, "api_url is not configured", False)
            if "/public_api/v1" not in base:
                base = base.split("/public_api")[0].rstrip("/") + "/public_api/v1"
            api_key = _first(sec.get("api_key"))
            api_id = _first(cfg.get("api_id"), sec.get("api_id"))
            if not api_key:
                return (False, "api_key (Authorization header) is not configured", True)
            if not api_id:
                return (False, "api_id (X-Auth-ID header) is not configured", True)
            headers = {
                "Authorization": api_key,
                "x-xdr-auth-id": str(api_id),
                "Content-Type": "application/json",
            }
            async with httpx.AsyncClient(timeout=timeout, verify=verify) as c:
                # Use search_to=1 to minimize data transfer.
                r = await c.post(
                    f"{base}/incidents/get_incidents",
                    headers=headers,
                    json={"request_data": {"search_from": 0, "search_to": 1}},
                )
            if r.status_code == 200:
                return (True, None, False)
            if r.status_code in (401, 403):
                return (False, f"HTTP {r.status_code} from XDR API (creds rejected)", True)
            # 400 with empty filters can happen depending on XDR API
            # version; surface as auth-shaped because the operator's
            # config is the actionable surface.
            return (
                False,
                f"HTTP {r.status_code} from {base}/incidents/get_incidents",
                False,
            )

        if connector_id == "cortex-content":
            # Probe verifies the bundled catalog directory is present
            # and readable. The catalog ships with the agent image; if
            # it's missing the image was built without it (CI defect).
            try:
                from pathlib import Path as _Path
                # The catalog lives at /app/bundle/connectors/cortex-content/baked/
                # in the agent container. In tests / dev, walk up from this
                # module to bundles/spark/connectors/cortex-content/baked/.
                candidates = [
                    _Path("/app/bundle/connectors/cortex-content/baked/_manifest.json"),
                    _Path(__file__).resolve().parents[3]
                    / "connectors" / "cortex-content" / "baked" / "_manifest.json",
                ]
                if any(p.is_file() for p in candidates):
                    return (True, None, False)
                return (
                    False,
                    "cortex-content catalog directory is missing from the bundle",
                    False,
                )
            except Exception as exc:  # noqa: BLE001
                return (False, f"catalog probe: {type(exc).__name__}: {exc}", False)

        # No real probe wired — caller falls back to reset-to-pending.
        return (True, None, False)
    except httpx.HTTPError as exc:
        return (False, f"{type(exc).__name__}: {exc}", False)
    except Exception as exc:  # noqa: BLE001 — best-effort probe
        return (False, f"{type(exc).__name__}: {exc}", False)
