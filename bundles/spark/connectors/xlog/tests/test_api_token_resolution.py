"""The xlog connector reads its API token from the secret slot that exists.

The slot is named `apiToken` everywhere it is defined: connector.yaml
`secretSlots`, manifest.yaml `secretRefs`, and the instance-creation UI. The
container runtime merges resolved secrets into instance config keyed by SLOT
NAME, so `apiToken` is the key that is present. `xlog_api_token` is the
agent-side key used when connectors run in-process; it is accepted only as a
fallback for hand-written instance configs.

A missing token must not be silent: the connector would otherwise send NO
Authorization header, which is indistinguishable from a connector correctly
configured with no token. Reading the wrong key, or swallowing the missing-key
error, would hide exactly that.

These tests pin the slot name, so the code and the definitions cannot drift apart.
"""

from __future__ import annotations

import sys
import types as _types
from pathlib import Path

import pytest

_CONN_ROOT = Path(__file__).resolve().parents[1]
if str(_CONN_ROOT) not in sys.path:
    sys.path.insert(0, str(_CONN_ROOT))


def _install_cfg(**attrs):
    """Install a config proxy exposing exactly `attrs`.

    Mirrors the real container proxy, which RAISES AttributeError on a missing
    key (phantom-connector-runtime/config/config.py) — that is precisely what
    getattr's default was swallowing.
    """
    config_pkg = _types.ModuleType("config")
    config_mod = _types.ModuleType("config.config")

    class _Cfg:
        def __init__(self, values):
            self._values = values

        def __getattr__(self, name):
            if name in self._values:
                return self._values[name]
            raise AttributeError(f"config key {name!r} not set")

    config_mod.get_config = lambda: _Cfg(attrs)  # type: ignore[attr-defined]
    config_pkg.config = config_mod  # type: ignore[attr-defined]
    sys.modules["config"] = config_pkg
    sys.modules["config.config"] = config_mod


def _resolve():
    for mod in ("src._graphql_client",):
        sys.modules.pop(mod, None)
    from src._graphql_client import _resolve_api_token
    return _resolve_api_token()


def test_reads_the_slot_that_actually_exists():
    """`apiToken` is the slot name in connector.yaml and the UI."""
    _install_cfg(apiToken="tok-abc")
    assert _resolve() == "tok-abc"


def test_the_agent_side_key_alone_still_works_as_a_fallback():
    """The agent-side key `xlog_api_token` is honoured, but only as a fallback."""
    _install_cfg(xlog_api_token="legacy-tok")
    assert _resolve() == "legacy-tok"


def test_canonical_slot_wins_over_legacy():
    _install_cfg(apiToken="correct", xlog_api_token="stale")
    assert _resolve() == "correct"


def test_missing_token_returns_none_without_raising():
    """The container proxy raises on missing keys; we must not propagate."""
    _install_cfg(xlog_url="http://localhost:8000")
    assert _resolve() is None


def test_whitespace_only_token_is_treated_as_absent():
    _install_cfg(apiToken="   ")
    assert _resolve() is None


def test_token_is_stripped():
    _install_cfg(apiToken="  tok-xyz\n")
    assert _resolve() == "tok-xyz"


def test_does_not_fall_back_to_the_local_env_key():
    """baseUrl may point at an xlog the operator runs themselves.

    Falling back to this container's own XLOG_API_KEY would send our locally
    generated secret to a third-party host. The token must come from the
    instance that names the destination.
    """
    import os
    os.environ["XLOG_API_KEY"] = "local-secret-must-not-leak"
    os.environ["XLOG_API_TOKEN"] = "local-secret-must-not-leak"
    try:
        _install_cfg(xlog_url="http://someone-elses-host:8000")
        assert _resolve() is None
    finally:
        os.environ.pop("XLOG_API_KEY", None)
        os.environ.pop("XLOG_API_TOKEN", None)


def test_slot_name_matches_connector_yaml():
    """Pins the constant against the YAML, so they cannot drift."""
    import re
    from src._graphql_client import _TOKEN_SLOT

    yaml_text = (_CONN_ROOT / "connector.yaml").read_text()
    slots = re.findall(r"secretSlots:\s*\n\s*-\s*name:\s*\"([^\"]+)\"", yaml_text)
    assert slots, "could not find secretSlots in connector.yaml"
    assert _TOKEN_SLOT == slots[0], (
        f"_graphql_client reads {_TOKEN_SLOT!r} but connector.yaml declares "
        f"{slots[0]!r} — this mismatch would silently drop authentication"
    )


def test_missing_token_is_logged_not_silent(caplog):
    """Silence is what let this ship; absence must be visible in the logs."""
    _install_cfg(xlog_url="http://localhost:8000")
    with caplog.at_level("WARNING", logger="Phantom MCP"):
        assert _resolve() is None
    assert any("no API token" in r.message or "no API token" in r.getMessage()
               for r in caplog.records), "expected a warning naming the missing token"
