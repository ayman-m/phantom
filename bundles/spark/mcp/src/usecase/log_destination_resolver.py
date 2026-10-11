"""Resolve a `logdest:<id>` worker-destination reference to a concrete
address — MCP-side ONLY.

This module runs inside the agent/MCP container, the only place that can
read both `log_destinations.db` AND the SecretStore. The chat agent passes
a destination *reference* (`logdest:<id>`); the connector-proxy chokepoint
(`pkg.connector_proxy.proxy_call_tool`) calls `resolve_worker_args` right
before forwarding the `phantom_create_data_worker` call to the xlog
connector. The xsiam_http secret therefore travels only MCP→connector over
the internal network — it never crosses the agent's tool surface, so the
credential guardrail holds.

Resolution per destination type:
  * syslog     → `destination = "<protocol>:<host>:<port>"` (no secret)
  * xsiam_http → `destination = "XSIAM_WEBHOOK"` plus injected
                 `webhook_url` + `webhook_key` (the plaintext auth_key)
  * other (webhook/splunk_hec) → not wired into xlog yet → ValueError
"""
from __future__ import annotations

from typing import Any

_PREFIX = "logdest:"


def resolve_worker_args(args: dict[str, Any]) -> dict[str, Any]:
    """If `args['destination']` is a `logdest:<id>` reference, rewrite it
    in place to a concrete address (and inject webhook_url/webhook_key for
    xsiam_http). Any other destination value is returned untouched.

    Raises ValueError on an unknown id or an unsupported destination type
    — the proxy surfaces that as a tool error rather than silently falling
    back to a hardcoded address.
    """
    dest = args.get("destination")
    if not isinstance(dest, str) or not dest.startswith(_PREFIX):
        return args  # raw udp:/tcp: address, XSIAM_WEBHOOK, etc. — untouched

    dest_id = dest[len(_PREFIX):].strip()
    from usecase.log_destinations_store import get_log_destination_store

    store = get_log_destination_store()
    row = store.get(dest_id)
    if row is None:
        raise ValueError(f"log destination {dest_id!r} not found")

    cfg = row.config or {}
    if row.type_id == "syslog":
        proto = cfg.get("protocol", "udp")
        args["destination"] = f"{proto}:{cfg['host']}:{cfg['port']}"
    elif row.type_id == "xsiam_http":
        merged = store.merged_config(dest_id) or {}
        args["destination"] = "XSIAM_WEBHOOK"
        args["webhook_url"] = cfg.get("url")
        args["webhook_key"] = merged.get("auth_key")
    else:
        raise ValueError(
            f"destination type {row.type_id!r} is not wired into log "
            "generation yet (webhook/splunk_hec land in a later release); "
            "use a syslog or xsiam_http destination"
        )
    return args
