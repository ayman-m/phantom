"""Connector state HTTP endpoints.

Exposes the SqliteConnectorStateStore for the agent UI's
/connectors page.

Endpoints (all require `Authorization: Bearer <MCP_TOKEN>`):

  GET    /api/v1/connectors             → list all with state
  GET    /api/v1/connectors/{id}        → fetch one
  POST   /api/v1/connectors/{id}/disable → mark disabled
  POST   /api/v1/connectors/{id}/enable  → mark pending (re-probe
                                           on next tool call)
  POST   /api/v1/connectors/{id}/probe   → force a state refresh
                                           (calls a connector-
                                           specific health probe;
                                           connectors without one
                                           just reset to pending)
"""

from __future__ import annotations

import logging

import yaml
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.connector_catalog import effective_connectors, find_connector
from usecase.marketplace_store import ORIGIN_BUNDLE
from usecase.connector_state import (
    SqliteConnectorStateStore,
)
from usecase.audit_log import (
    SqliteAuditLog,
    set_current_actor,
    reset_current_actor,
)
from usecase.connector_probes import PROBE_IMPLEMENTED, real_probe
from usecase.instance_store import InstanceStore

logger = logging.getLogger("Phantom MCP")


# Probes moved to usecase/connector_probes.py so /api/v1/instances/{id}/test
# can use them too without a circular import. See that module for the
# per-connector probe logic + the rationale for which connectors get a
# real probe vs the reset-to-pending fallback.
_real_probe = real_probe
_PROBE_IMPLEMENTED = PROBE_IMPLEMENTED


def register_connector_routes(
    mcp: FastMCP,
    state_store: SqliteConnectorStateStore,
    instance_store: InstanceStore,
    audit: SqliteAuditLog,
) -> None:
    """Register /api/v1/connectors/* routes."""

    @mcp.custom_route(
        "/api/v1/connectors", methods=["GET"], include_in_schema=False
    )
    async def list_connectors(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        # Merge manifest-declared connectors with any state rows.
        # A connector that's in the manifest but never probed
        # appears with state='pending'; one in state but not in
        # manifest appears as 'orphaned' (probably operator removed
        # it after a connector was deleted upstream).
        states = {s.connector_id: s for s in state_store.list()}
        configured_ids = (
            instance_store.configured_connector_ids()
            if instance_store else set()
        )
        seen: set[str] = set()
        result: list[dict] = []
        # Bundle connectors first (manifest order), then uploaded user
        # connectors, both from the shared catalog.
        for ref in effective_connectors():
            cid = ref.id
            seen.add(cid)
            s = states.get(cid)
            row = (
                s.to_dict() if s
                else {
                    "connector_id": cid,
                    "state": "pending",
                    "last_transition_at": None,
                    "last_probed_at": None,
                    "last_error": None,
                    "consecutive_failures": 0,
                }
            )
            row["configured"] = cid in configured_ids
            row["origin"] = ref.origin
            row["in_manifest"] = ref.origin == ORIGIN_BUNDLE
            result.append(row)
        # Any orphaned state rows: known to neither the manifest nor
        # the uploaded connectors.
        for cid, s in states.items():
            if cid in seen:
                continue
            row = s.to_dict()
            row["configured"] = cid in configured_ids
            row["origin"] = "orphaned"
            row["in_manifest"] = False
            result.append(row)
        return JSONResponse({"connectors": result, "count": len(result)})

    @mcp.custom_route(
        "/api/v1/connectors/{connector_id}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_connector(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        cid = request.path_params["connector_id"]
        s = state_store.get(cid)
        ref = find_connector(cid)
        if s is None:
            # Not yet probed; surface the catalog stub (bundle or user).
            if ref is not None:
                return JSONResponse(
                    {
                        "connector": {
                            "connector_id": cid,
                            "state": "pending",
                            "last_transition_at": None,
                            "last_probed_at": None,
                            "last_error": None,
                            "consecutive_failures": 0,
                            "configured": False,
                            "origin": ref.origin,
                            "in_manifest": ref.origin == ORIGIN_BUNDLE,
                        }
                    }
                )
            return JSONResponse({"error": "not found"}, status_code=404)
        d = s.to_dict()
        d["origin"] = ref.origin if ref is not None else "orphaned"
        d["in_manifest"] = ref is not None and ref.origin == ORIGIN_BUNDLE
        return JSONResponse({"connector": d})

    @mcp.custom_route(
        "/api/v1/connectors/{connector_id}/disable",
        methods=["POST"],
        include_in_schema=False,
    )
    async def disable_connector(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            cid = request.path_params["connector_id"]
            s = state_store.set_disabled(cid, disabled=True)
            if s is None:
                return JSONResponse(
                    {"error": "not found"}, status_code=404
                )
            audit.record(
                action="connector_disabled",
                target=f"connector:{cid}",
                status="skipped",
                metadata={"connector_id": cid},
            )
            return JSONResponse({"connector": s.to_dict()})
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/connectors/{connector_id}/enable",
        methods=["POST"],
        include_in_schema=False,
    )
    async def enable_connector(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            cid = request.path_params["connector_id"]
            s = state_store.set_disabled(cid, disabled=False)
            if s is None:
                return JSONResponse(
                    {"error": "not found"}, status_code=404
                )
            audit.record(
                action="connector_enabled",
                target=f"connector:{cid}",
                status="success",
                metadata={"connector_id": cid},
            )
            return JSONResponse({"connector": s.to_dict()})
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/connectors/{connector_id}/_record_success",
        methods=["POST"],
        include_in_schema=False,
    )
    async def record_success(request: Request) -> JSONResponse:
        """Internal endpoint — chat-route calls after a successful
        tool dispatch. Marks the connector connected, resets
        consecutive_failures. Underscore prefix flags it as an
        intra-Phantom call (operators wouldn't trigger this from
        the UI directly)."""
        if (resp := require_bearer(request)) is not None:
            return resp
        cid = request.path_params["connector_id"]
        s = state_store.record_success(cid)
        # Don't audit success records — they're high-volume and
        # already reflected in tool_call audit rows.
        return JSONResponse({"connector": s.to_dict()})

    @mcp.custom_route(
        "/api/v1/connectors/{connector_id}/_record_failure",
        methods=["POST"],
        include_in_schema=False,
    )
    async def record_failure(request: Request) -> JSONResponse:
        """Internal endpoint — chat-route calls when a tool fails.
        Body: {error: str, is_auth_error: bool}. Auth errors
        transition the connector to `needs-auth` (operator sees
        the reauth chip); other errors transition to `failed`."""
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            cid = request.path_params["connector_id"]
            try:
                body = await request.json()
            except Exception:
                body = {}
            error = (
                body.get("error") if isinstance(body, dict) else None
            ) or "(unspecified error)"
            is_auth = bool(
                body.get("is_auth_error") if isinstance(body, dict)
                else False
            )
            existing = state_store.get(cid)
            s = state_store.record_failure(
                cid, error=str(error), is_auth_error=is_auth
            )
            # Audit only on STATE TRANSITIONS, not every failure
            # (auth_required can fire repeatedly while the operator
            # is investigating; we want one audit row per
            # connected→needs-auth transition, not one per call).
            if (
                existing is None
                or existing.state != s.state
            ):
                audit.record(
                    action=(
                        "connector_auth_required" if is_auth
                        else "connector_failed"
                    ),
                    target=f"connector:{cid}",
                    status="failure",
                    metadata={
                        "connector_id": cid,
                        "from_state": existing.state if existing else None,
                        "to_state": s.state,
                        "error": str(error)[:200],
                        "consecutive_failures": s.consecutive_failures,
                    },
                )
            return JSONResponse({"connector": s.to_dict()})
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/connectors/{connector_id}/probe",
        methods=["POST"],
        include_in_schema=False,
    )
    async def probe_connector(request: Request) -> JSONResponse:
        """Run the connector's read-only health probe and update state
        accordingly: "connected" / "failed" / "needs-auth" from the
        outcome (usecase/connector_probes.py; all nine bundle connectors
        have one). A connector without a probe (an operator-uploaded
        one) falls back to the legacy reset-to-pending behavior so the
        next tool call re-evaluates.
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            cid = request.path_params["connector_id"]
            existing = state_store.get(cid)
            if existing is None:
                state_store.upsert_pending(cid)

            if cid in _PROBE_IMPLEMENTED:
                # Pass the first instance's resolved config +
                # secrets so the probe tests the operator-configured
                # endpoint rather than the env-var defaults. With the
                # 1:1 instance↔connector mapping in single-tenant
                # Phantom there's typically one instance per connector;
                # if multiple exist we just probe the first (the
                # /instances/{id}/test endpoint is the per-instance
                # surface for finer control).
                first_inst = next(iter(instance_store.list_for(cid)), None)
                cfg = first_inst.config if first_inst else None
                sec = (
                    first_inst.resolved_secrets(instance_store.secret_store)
                    if first_inst
                    else None
                )
                ok, err, is_auth = await _real_probe(
                    cid,
                    config=cfg,
                    secrets=sec,
                    # With an instance, also check its connector container;
                    # without one the probe falls back to env defaults.
                    container_url=first_inst.container_url if first_inst else None,
                    check_container=first_inst is not None,
                )
                if ok:
                    new_state = state_store.record_success(cid)
                    audit_status = "success"
                else:
                    new_state = state_store.record_failure(
                        cid, error=err or "probe failed", is_auth_error=is_auth
                    )
                    audit_status = "failure"
                audit.record(
                    action="connector_probed",
                    target=f"connector:{cid}",
                    status=audit_status,
                    metadata={
                        "connector_id": cid,
                        "ok": ok,
                        "error": err,
                        "is_auth_error": is_auth,
                    },
                )
                return JSONResponse({"connector": new_state.to_dict()})

            # Fallback: reset to pending so the next tool call re-evaluates.
            # Preserves consecutive_failures so repeated probes without
            # fixing the upstream issue still surface the failure count.
            if existing is not None:
                state_store.set_disabled(cid, disabled=False)
            audit.record(
                action="connector_probed",
                target=f"connector:{cid}",
                status="success",
                metadata={"connector_id": cid, "probe_kind": "reset-to-pending"},
            )
            current = state_store.get(cid)
            return JSONResponse(
                {"connector": current.to_dict() if current else None}
            )
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/connectors/{connector_id}/tools",
        methods=["GET"],
        include_in_schema=False,
    )
    async def list_connector_tools(request: Request) -> JSONResponse:
        """Introspect a connector's available tools.

        Reads the connector's `connector.yaml`'s spec.tools[] list and
        returns one row per tool: name, description (one-line), args
        summary. Includes per-instance disabled state when an
        ?instance_id=<id> query param is supplied (so the Tools tab can
        render the checkboxes with the correct initial states).

        Used by the /connectors instance-detail Tools tab. Operators
        check/uncheck tools; the change flows to
        `PATCH /api/v1/instances/<id> { disabled_tools: [...] }`.
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        cid = request.path_params["connector_id"]

        # Resolve the connector's yaml through the shared catalog, so
        # uploaded user connectors work the same as bundle ones.
        ref = find_connector(cid)
        if ref is None:
            return JSONResponse(
                {"error": f"connector {cid!r} not found (neither in the bundle manifest nor uploaded)"},
                status_code=404,
            )
        try:
            spec = yaml.safe_load(ref.yaml_path.read_text()) or {}
        except Exception as exc:
            return JSONResponse(
                {"error": f"connector.yaml parse failed: {exc}"},
                status_code=500,
            )

        tools_raw = (spec.get("spec") or {}).get("tools") or []
        instance_id = request.query_params.get("instance_id")
        disabled_set: set[str] = set()
        if instance_id:
            inst = instance_store.get(instance_id)
            if inst is not None and inst.connector_id == cid:
                disabled_set = set(inst.disabled_tools or [])

        rows: list[dict[str, object]] = []
        for tool in tools_raw:
            if not isinstance(tool, dict):
                continue
            tname = tool.get("name")
            if not isinstance(tname, str) or not tname:
                continue
            description = tool.get("description") or ""
            # Truncate long descriptions to a one-line summary for the UI
            summary = description.strip().splitlines()[0][:200] if description else ""
            args = tool.get("args") or []
            arg_count = len(args) if isinstance(args, list) else 0
            rows.append({
                "name": tname,
                "namespaced": f"{cid}.{tname}",
                "summary": summary,
                "description": description,
                "arg_count": arg_count,
                "method": tool.get("method", ""),
                "disabled": tname in disabled_set,
            })

        return JSONResponse({
            "connector_id": cid,
            "tools": rows,
            "total": len(rows),
            "enabled": sum(1 for r in rows if not r["disabled"]),
            "disabled": sum(1 for r in rows if r["disabled"]),
            "instance_id": instance_id,
        })
