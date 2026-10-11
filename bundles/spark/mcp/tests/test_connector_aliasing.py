"""Guard for the connector legacy-alias doubled-prefix case.

The xsiam and cortex-xdr tools are authored with the connector prefix
already baked into ``spec.tools[].name``. The flat legacy alias
``f"{functionPrefix}{tool_name}"`` must not double it
(``xdr_`` + ``xdr_incidents_list`` -> ``xdr_xdr_incidents_list``); otherwise
the natural single-prefix name the model / docs / skills call
(``xdr_incidents_list``) would never be advertised and would 404 at the
agent layer with "Unknown tool".
"""

from __future__ import annotations

import glob
import os

import yaml

from usecase.connector_loader import _legacy_alias


def test_bare_name_gets_prefixed():
    # Normal case: spec.tools[].name is bare → alias = prefix + name.
    assert _legacy_alias("xsiam_", "incidents_list") == "xsiam_incidents_list"
    assert _legacy_alias("caldera_", "start_operation") == "caldera_start_operation"


def test_already_prefixed_name_is_not_doubled():
    # The name already carries the prefix → do NOT re-prepend.
    assert _legacy_alias("xdr_", "xdr_incidents_list") == "xdr_incidents_list"
    assert _legacy_alias("xsiam_", "xsiam_alerts_list") == "xsiam_alerts_list"


def test_no_prefix_returns_none():
    assert _legacy_alias("", "anything") is None


def test_incidents_tools_resolve_to_natural_single_prefix_names():
    """The xsiam and cortex-xdr connectors. The model-facing alias must
    be the single-prefix natural name in both cases — regardless of whether
    the container strips the prefix (xsiam, bare spec name) or not
    (cortex-xdr, prefixed spec name because xdr_ != cortex-xdr_)."""
    assert _legacy_alias("xsiam_", "incidents_list") == "xsiam_incidents_list"
    assert _legacy_alias("xdr_", "xdr_incidents_list") == "xdr_incidents_list"


def test_no_bundled_connector_yaml_yields_a_doubled_alias():
    """End-to-end over the real bundle: no connector's (functionPrefix,
    spec.tools[].name) pair may produce a doubled legacy alias. This catches
    a connector authored with the prefix already in the tool name."""
    root = os.path.join(os.path.dirname(__file__), "..", "..", "connectors")
    yamls = glob.glob(os.path.join(root, "*", "connector.yaml"))
    assert yamls, "no connector.yaml files found — wrong path?"
    offenders: list[str] = []
    for cy in yamls:
        spec = yaml.safe_load(open(cy)) or {}
        cid = spec.get("id") or os.path.basename(os.path.dirname(cy))
        fp = (spec.get("runtimeMapping") or {}).get("functionPrefix", "") or ""
        for tool in (spec.get("spec") or {}).get("tools") or []:
            name = tool.get("name")
            if not isinstance(name, str):
                continue
            alias = _legacy_alias(fp, name)
            if alias and fp and alias.startswith(fp + fp):
                offenders.append(f"{cid}: {name!r} (prefix {fp!r}) -> {alias!r}")
    assert not offenders, "doubled legacy aliases found:\n" + "\n".join(offenders)
