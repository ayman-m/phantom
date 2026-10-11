"""`phantom_create_data_worker` WITHOUT a schema_override must send xlog a payload
its GraphQL types accept.

Regression: the generic path put `durationSeconds` / `maxEvents` inside the
`steps[0].logs[0]` object, which is xlog's `WorkerFakerInput` and defines
neither field. Because the lifetime wrapper fills in `duration_seconds=900` for
every call that sets no bound, EVERY generic-path call was rejected with
"Field 'durationSeconds' is not defined by type 'WorkerFakerInput'".

The burst bounds are carried by the schema_override path (`DataWorkerCreateInput`
defines them); the generic path uses xlog's count-bounded Rosetta sender.

Hermetic: the GraphQL client is replaced, and the field names the log step may
carry are read from the xlog source with `ast` (the test skips when this
connector is checked out without the xlog tree).
"""

from __future__ import annotations

import ast
import asyncio
import re
import sys
import types as _types
from pathlib import Path

import pytest

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

_XLOG_TYPES = _CONN_ROOT.parents[3] / "xlog" / "app" / "types" / "sender.py"


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(p.title() for p in rest)


def _input_fields(class_name: str) -> set[str]:
    tree = ast.parse(_XLOG_TYPES.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                _camel(stmt.target.id)
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            }
    raise AssertionError(f"{class_name} not found in {_XLOG_TYPES}")


class _FakeClient:
    captured: dict = {}

    def __init__(self, url):
        pass

    async def execute_query(self, query, variables):
        _FakeClient.captured = {"query": query, "variables": variables}
        return {"createScenarioWorkerFromQuery": [], "createDataWorker": {}}


def _run(**kwargs):
    orig_client, orig_resolver = workers.PhantomGraphQLClient, workers.resolve_xlog_url
    workers.PhantomGraphQLClient = _FakeClient
    workers.resolve_xlog_url = lambda ctx: "http://localhost:8000"
    try:
        _FakeClient.captured = {}
        asyncio.run(workers.phantom_create_data_worker(**kwargs))
    finally:
        workers.PhantomGraphQLClient, workers.resolve_xlog_url = orig_client, orig_resolver
    return _FakeClient.captured.get("variables", {})


def test_generic_path_never_sends_burst_bounds_in_the_log_step():
    for extra in ({}, {"duration_seconds": 120}, {"max_events": 50}, {"continuous": True}):
        variables = _run(type="CEF", destination="udp:10.0.0.8:514", vendor="X", product="Y", **extra)
        log = variables["steps"][0]["logs"][0]
        assert "durationSeconds" not in log and "maxEvents" not in log, (extra, log)


@pytest.mark.skipif(not _XLOG_TYPES.is_file(), reason="xlog source tree not alongside this connector")
def test_generic_path_log_step_only_uses_fields_xlog_defines():
    allowed = _input_fields("WorkerFakerInput")
    variables = _run(
        type="CEF", destination="udp:10.0.0.8:514", vendor="X", product="Y",
        count=3, interval=2, version="1.0", datetime_iso="2026-01-01 00:00:00",
        observables_dict={"srcHost": ["h1"]}, required_fields=["srcHost"],
    )
    log = variables["steps"][0]["logs"][0]
    unknown = set(log) - allowed
    assert not unknown, f"log step carries fields xlog's WorkerFakerInput rejects: {sorted(unknown)}"
    # And the step wrapper itself.
    assert set(variables["steps"][0]) - _input_fields("DetailedQueryScenarioStep") == set()


@pytest.mark.skipif(not _XLOG_TYPES.is_file(), reason="xlog source tree not alongside this connector")
def test_override_path_still_sends_burst_bounds_xlog_defines():
    allowed = _input_fields("DataWorkerCreateInput")
    assert {"durationSeconds", "maxEvents"} <= allowed
    variables = _run(
        type="CEF", destination="udp:10.0.0.8:514", vendor="X", product="Y",
        schema_override=[{"name": "srcip", "type": "string"}], duration_seconds=120,
    )
    inp = variables["input"]
    assert inp.get("durationSeconds") == 120, inp
    unknown = set(inp) - allowed
    assert not unknown, f"override input carries fields xlog rejects: {sorted(unknown)}"
