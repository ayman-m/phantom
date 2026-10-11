"""The `schema_override` path of `phantom_create_data_worker`
MUST forward `observables_dict` as `observablesDict` in the `createDataWorker`
mutation variables, alongside
`type/count/interval/destination/vendor/product/schemaOverride`.

Dropping `observablesDict` would mean every forced-field override (a
threat-intel IP, a username, or — critically — a classifier value a modeling
rule keys on via `filter <field> in (...)`) never reaches the synthesized
event: XDM would cap at 0 for enum-classified vendors, and a shared-CEF-header
stream could never route to its own dataset.

These tests don't hit the network — they patch the GraphQL client to capture
the mutation variables, and patch the URL resolver so no real `ctx` is needed.
"""

from __future__ import annotations

import asyncio
import sys
import types as _types
from pathlib import Path

# `_xlog_url_resolver` / `_graphql_client` transitively import `config.config`
# at module load in some build layouts. Stub it so the test stays hermetic.
if "config.config" not in sys.modules:
    config_pkg = _types.ModuleType("config")
    config_mod = _types.ModuleType("config.config")

    class _Cfg:
        xlog_url = "http://localhost:8000"

    config_mod.get_config = lambda: _Cfg()  # type: ignore[attr-defined]
    config_pkg.config = config_mod  # type: ignore[attr-defined]
    sys.modules["config"] = config_pkg
    sys.modules["config.config"] = config_mod

# Connector root on sys.path so `from src.workers import …` resolves and the
# relative `from ._graphql_client import …` inside it works.
_CONN_ROOT = Path(__file__).resolve().parents[1]
if str(_CONN_ROOT) not in sys.path:
    sys.path.insert(0, str(_CONN_ROOT))

from src import workers  # noqa: E402


class _FakeClient:
    """Captures the (query, variables) passed to execute_query."""

    captured: dict = {}

    def __init__(self, url):  # url comes from the patched resolve_xlog_url
        pass

    async def execute_query(self, query, variables):
        _FakeClient.captured = {"query": query, "variables": variables}
        return {
            "createDataWorker": {
                "worker": "worker_test",
                "type": "CEF",
                "status": "Running",
                "count": "1",
                "interval": "2",
                "destination": "udp:10.0.0.8:514",
                "createdAt": "now",
            }
        }


def _run_worker(**kwargs):
    """Invoke the tool with the GraphQL client + URL resolver patched."""
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


def test_schema_override_path_forwards_observables_dict():
    variables = _run_worker(
        type="CEF",
        destination="udp:10.0.0.8:514",
        vendor="Okta",
        product="Okta",
        schema_override=[{"name": "eventType", "type": "string"}],
        observables_dict={"eventType": ["user.session.start"]},
    )
    inp = variables.get("input", {})
    # The schema-override branch must carry observablesDict into the mutation.
    assert "observablesDict" in inp and inp["observablesDict"], inp
    # The seeded classifier value survives normalization (key may be remapped,
    # the value must not be dropped).
    assert "user.session.start" in str(inp["observablesDict"]), inp


def test_schema_override_path_omits_observables_when_absent():
    """Defensive — with no observables_dict, observablesDict is None-stripped
    from the input (no empty key leaking into the mutation)."""
    variables = _run_worker(
        type="CEF",
        destination="udp:10.0.0.8:514",
        vendor="Okta",
        product="Okta",
        schema_override=[{"name": "eventType", "type": "string"}],
    )
    inp = variables.get("input", {})
    assert "schemaOverride" in inp  # sanity: we hit the override branch
    assert "observablesDict" not in inp, inp


def test_schema_override_path_does_not_rename_vendor_field_names():
    """Vendor schema field names must reach the wire VERBATIM.

    `_normalize_observable_keys` maps legacy snake_case aliases onto the
    camelCase faker vocabulary (`event_id` -> `eventId`). That is right for the
    scenario/faker paths, whose namespace IS that 46-key vocabulary, and wrong
    on the schema_override path, where the namespace is the VENDOR SCHEMA.

    Renaming would turn a Windows Event Log or AMSI event's pinned `event_id`
    into `eventId`, which matches no declared schema field, so the pin would be
    silently discarded and the generator would emit a random token. That would
    break every Windows Event ID scenario outright -- `event_id` is what selects
    4624 (logon) from 4769 (service ticket). The same collision exists for
    `query`/`query_type` (DNS), `action`, `os`, `user`, `severity` and 40 more.
    """
    variables = _run_worker(
        type="CEF",
        destination="udp:10.0.0.27:5514",
        vendor="microsoft",
        product="windows",
        schema_override=[
            {"name": "event_id", "type": "string"},
            {"name": "provider_name", "type": "string"},
            {"name": "query_type", "type": "string"},
        ],
        observables_dict={
            "event_id": ["4769"],
            "provider_name": ["Microsoft-Windows-Security-Auditing"],
            "query_type": ["A"],
        },
    )
    obs = variables.get("input", {}).get("observablesDict") or {}
    assert obs.get("event_id") == ["4769"], obs
    assert obs.get("query_type") == ["A"], obs
    assert "eventId" not in obs, f"vendor field name was aliased away: {obs}"
    assert obs.get("provider_name") == ["Microsoft-Windows-Security-Auditing"], obs


# ---------------------------------------------------------------------------
# `__entities__` (identity binding) must survive the tool surface.
# xlog's override generator draws one field-map per record from
# observables_dict["__entities__"]; the tool must not type observables_dict as
# Dict[str, List[str]], or FastMCP would reject every call carrying it.
# ---------------------------------------------------------------------------

_ENTITIES = [
    {"source_device_host": "WS-1001", "source_ip": "10.20.14.11", "source_user": "ahmed.alharbi"},
    {"source_device_host": "WS-1002", "source_ip": "10.20.14.12", "source_user": "fatima.alqahtani"},
]


def test_signature_annotation_accepts_entities():
    """FastMCP validates arguments against the function's annotations BEFORE
    the body runs — that is where a too-narrow annotation is rejected, so calling
    the function directly would not catch it."""
    import inspect
    import typing

    from pydantic import TypeAdapter

    ann = typing.get_type_hints(workers.phantom_create_data_worker)["observables_dict"]
    TypeAdapter(ann).validate_python({"app": ["ssl"], "__entities__": _ENTITIES})
    # The request model carries the same field and must agree.
    workers.CreateDataWorkerRequest(type="CEF", observables_dict={"__entities__": _ENTITIES})
    assert inspect.signature(workers.phantom_create_data_worker).parameters["observables_dict"]


def test_schema_override_path_forwards_entities_verbatim():
    variables = _run_worker(
        type="CEF",
        destination="udp:10.0.0.27:5514",
        vendor="panw",
        product="ngfw_traffic",
        schema_override=[
            {"name": "source_device_host", "type": "string"},
            {"name": "source_ip", "type": "ipv4"},
            {"name": "source_user", "type": "string"},
            {"name": "app", "type": "string"},
        ],
        observables_dict={"app": ["ssl"], "__entities__": _ENTITIES},
    )
    obs = variables.get("input", {}).get("observablesDict") or {}
    assert obs.get("__entities__") == _ENTITIES, obs
    assert obs.get("app") == ["ssl"], obs


def test_legacy_path_rejects_entities_with_a_clear_error():
    import pytest

    with pytest.raises(ValueError, match="requires schema_override"):
        _run_worker(
            type="CEF",
            destination="udp:10.0.0.27:5514",
            vendor="PHANTOM",
            product="EDR",
            observables_dict={"__entities__": _ENTITIES},
        )
