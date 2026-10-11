"""Tests for DestinationHandlerRegistry.

The spec.yaml `handler:` field is a file path, not a dotted Python module
path (a dotted path would not resolve inside the agent container, where
/app/bundle is not on sys.path), so handlers load by file path. This
suite exercises initialize() directly.
"""

from __future__ import annotations

import pytest

from src.usecase.destination_handler_registry import (
    initialize,
    list_registered,
    get_handler,
    reset_for_tests,
)
from src.usecase.destination_types_loader import reset_loader_for_tests


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_for_tests()
    reset_loader_for_tests()
    yield
    reset_for_tests()
    reset_loader_for_tests()


def test_initialize_imports_all_four_v1_handlers() -> None:
    """The four shipped types (syslog/webhook/xsiam_http/splunk_hec)
    all load their handler.py and validate as having probe() + send()."""
    initialize()
    registered = list_registered()
    assert {"syslog", "webhook", "xsiam_http", "splunk_hec"}.issubset(
        set(registered),
    ), f"missing v1 handlers: {registered}"


def test_each_handler_exposes_probe_and_send() -> None:
    """validate_handler_module() checks for both functions; if any are
    missing, initialize() raises. This test confirms the structural
    interface is satisfied by every shipped handler."""
    initialize()
    for type_id in ("syslog", "webhook", "xsiam_http", "splunk_hec"):
        handler = get_handler(type_id)
        assert handler is not None, f"{type_id} handler not loaded"
        assert callable(getattr(handler, "probe", None)), \
            f"{type_id}.probe missing or not callable"
        assert callable(getattr(handler, "send", None)), \
            f"{type_id}.send missing or not callable"


def test_initialize_is_idempotent() -> None:
    """Calling initialize() twice doesn't re-load or fail."""
    initialize()
    first = set(list_registered())
    initialize()
    second = set(list_registered())
    assert first == second
