"""phantom_create_data_worker fills unset identity fields from the active organization, on both paths."""
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from src import workers  # noqa: E402


class _Client:
    captured: dict = {}

    def __init__(self, url):
        pass

    async def execute_query(self, query, variables):
        _Client.captured = {"query": query, "variables": variables}
        return {"createDataWorker": {"worker": "w", "type": "CEF", "status": "Running", "count": "1", "interval": "2",
                                     "destination": "udp:10.20.3.10:514", "createdAt": "now"},
                "createScenarioWorkerFromQuery": [{"worker": "w", "type": "CEF"}]}


def _run(**kwargs):
    orig = (workers.PhantomGraphQLClient, workers.resolve_xlog_url)
    workers.PhantomGraphQLClient, workers.resolve_xlog_url = _Client, lambda ctx: "http://x"
    try:
        out = asyncio.run(workers.phantom_create_data_worker(**kwargs))
    finally:
        workers.PhantomGraphQLClient, workers.resolve_xlog_url = orig
    return out, _Client.captured["variables"]


FW_SCHEMA = [{"name": n, "type": "string"} for n in ("suser", "shost", "src", "dst", "dhost", "act")]


def test_schema_path_binds_entities_and_reports_them():
    out, variables = _run(type="CEF", destination="udp:10.20.3.10:514", vendor="V", product="P", schema_override=FW_SCHEMA,
                          observables_dict={"act": ["allow"]}, max_events=10)
    obs = variables["input"]["observablesDict"]
    assert obs["act"] == ["allow"] and len(obs["__entities__"]) >= 40
    rep = out[0]["organization_defaults"]
    assert rep["organization"] == "phantom-lab" and set(rep["bound"]) == {"suser", "shost", "src", "dst", "dhost"}


def test_use_organization_false_changes_nothing():
    out, variables = _run(type="CEF", destination="udp:10.20.3.10:514", vendor="V", product="P", schema_override=FW_SCHEMA,
                          observables_dict={"act": ["allow"]}, max_events=10, use_organization=False)
    assert variables["input"]["observablesDict"] == {"act": ["allow"]}
    assert "organization_defaults" not in out[0]


def test_legacy_path_pins_one_actor_and_reports():
    out, variables = _run(type="CEF", destination="udp:10.20.3.10:514", vendor="V", product="P", count=3)
    log = variables["steps"][0]["logs"][0]
    assert log["observablesDict"]["user"] == ["aalzamil"] and log["observablesDict"]["srcHost"][0].startswith("PHWS-")
    assert out[0]["organization_defaults"]["actor"] == "aalzamil"


def test_unreadable_organization_stops_the_call_with_a_clear_message(monkeypatch):
    from runtime import organization_view as ov
    from runtime.organization_reader import OrganizationUnavailable

    def broken(pinned):
        raise OrganizationUnavailable("organization.db not found at /app/data/organization.db")

    ov.set_organization_loader(broken)
    with pytest.raises(ValueError, match="organization.db not found"):
        _run(type="CEF", destination="udp:10.20.3.10:514", vendor="V", product="P", schema_override=FW_SCHEMA, max_events=1)
