"""Task 5 — `phantom_create_data_worker` MUST forward the platform-injected
`webhook_url` / `webhook_key` as `webhookUrl` / `webhookKey` on BOTH GraphQL
routes it takes (the schema_override `createDataWorker` path and the
`createScenarioWorkerFromQuery` fallback path).

Context: the MCP-side log-destination resolver rewrites a `logdest:<id>`
xsiam_http destination to 'XSIAM_WEBHOOK' and injects the resolved endpoint +
auth key into these two args before the call reaches this connector. xlog's
two XSIAM_WEBHOOK branches read webhookUrl/webhookKey (env fallback when None),
so the connector must carry them through. None → stripped → GraphQL null →
xlog env fallback (legacy behavior preserved).

Hermetic — patches the GraphQL client to capture mutation variables (same
pattern as test_create_data_worker_observables.py); no network, no real ctx.
"""

from __future__ import annotations

import asyncio
import sys
import types as _types
from pathlib import Path

if "config.config" not in sys.modules:
    config_pkg = _types.ModuleType("config")
    config_mod = _types.ModuleType("config.config")

    class _Cfg:
        xlog_url = "http://localhost:8000"

    config_mod.get_config = lambda: _Cfg()  # type: ignore[attr-defined]
    config_pkg.config = config_mod  # type: ignore[attr-defined]
    sys.modules["config"] = config_pkg
    sys.modules["config.config"] = config_mod

_CONN_ROOT = Path(__file__).resolve().parents[1]
if str(_CONN_ROOT) not in sys.path:
    sys.path.insert(0, str(_CONN_ROOT))

from src import workers  # noqa: E402


class _FakeClient:
    captured: dict = {}

    def __init__(self, url):
        pass

    async def execute_query(self, query, variables):
        _FakeClient.captured = {"query": query, "variables": variables}
        return {
            "createDataWorker": {
                "worker": "worker_test", "type": "CEF", "status": "Running",
                "count": "1", "interval": "2",
                "destination": "XSIAM_WEBHOOK", "createdAt": "now",
            }
        }


def _run_worker(**kwargs):
    orig_client = workers.PhantomGraphQLClient
    orig_resolver = workers.resolve_xlog_url
    workers.PhantomGraphQLClient = _FakeClient
    workers.resolve_xlog_url = lambda ctx: "http://localhost:8000"
    try:
        _FakeClient.captured = {}
        asyncio.run(workers.phantom_create_data_worker(**kwargs))
    finally:
        workers.PhantomGraphQLClient = orig_client
        workers.resolve_xlog_url = orig_resolver
    return _FakeClient.captured.get("variables", {})


def test_schema_override_path_forwards_webhook_url_and_key():
    # schema_override present → createDataWorker mutation → input.webhookUrl/Key.
    variables = _run_worker(
        type="CEF", destination="XSIAM_WEBHOOK", vendor="Okta", product="Okta",
        schema_override=[{"name": "eventType", "type": "string"}],
        webhook_url="https://store-resolved.example/logs", webhook_key="STOREKEY",
    )
    inp = variables.get("input", {})
    assert inp.get("webhookUrl") == "https://store-resolved.example/logs", inp
    assert inp.get("webhookKey") == "STOREKEY", inp


def test_scenario_path_forwards_webhook_url_and_key():
    # No schema_override → createScenarioWorkerFromQuery → top-level variables.
    variables = _run_worker(
        type="CEF", destination="XSIAM_WEBHOOK", vendor="Okta", product="Okta",
        webhook_url="https://store-resolved.example/logs", webhook_key="STOREKEY",
    )
    assert variables.get("webhookUrl") == "https://store-resolved.example/logs", variables
    assert variables.get("webhookKey") == "STOREKEY", variables


def test_webhook_fields_stripped_when_absent_scenario_path():
    # Plain syslog worker, no store destination → no webhook keys leak into vars.
    variables = _run_worker(
        type="CEF", destination="udp:10.0.0.8:514", vendor="X", product="Y",
    )
    assert "webhookUrl" not in variables, variables
    assert "webhookKey" not in variables, variables


def test_webhook_fields_stripped_when_absent_override_path():
    variables = _run_worker(
        type="CEF", destination="udp:10.0.0.8:514", vendor="X", product="Y",
        schema_override=[{"name": "srcip", "type": "string"}],
    )
    inp = variables.get("input", {})
    assert "schemaOverride" in inp  # sanity: override branch hit
    assert "webhookUrl" not in inp, inp
    assert "webhookKey" not in inp, inp
