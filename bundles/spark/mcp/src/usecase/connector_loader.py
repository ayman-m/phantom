"""Bundle-aware tool registry — instance-gated.

Reads the bundle at boot:
  - manifest.yaml → toolConnectors[]
  - connectors/<id>/connector.yaml → spec.tools[] + runtimeMapping

For each connector that has ≥1 instance in `data_root/instances.db`,
registers the connector's tools with names `<id>.<tool>` (and legacy
`<functionPrefix><tool>` aliases when MCP_LEGACY_TOOL_NAMES=true).
Every registered callable is wrapped in a closure that sets a
contextvar with the instance's config+secrets BEFORE invoking the
underlying connector function — so `get_config()` inside the function
returns the instance-specific values instead of env-var defaults.

Connectors with **zero** configured instances have **none** of their
tools advertised — this is objective 5 from the bundle architecture.

Built-in legacy tools (skills_*, simulation_skills.load_simulation_skills)
are NOT instance-gated; they're agent-runtime built-ins that today
live in phantom-mcp.

There is no env-var auto-migration: instances come only from the
marketplace install + instance-create flow (see the note further down).
"""

from __future__ import annotations

import functools
import inspect
import logging
import os
from pathlib import Path
from typing import Any, Callable, Iterator, NamedTuple

import yaml

from config.config import (
    reset_current_instance,
    set_current_instance,
)
from usecase.builtin_components import (
    asset_tools,
    cognitive_tools,
    coverage_tools,
    self_mod_tools,
    simulation_skills,
    skills_crud,
)
from usecase.connector_catalog import user_connectors
from usecase.credential_guardrail import assert_no_credential_tools
from usecase.event_log import event_log
from usecase.instance_store import Instance, InstanceStore
from usecase.secret_store import SecretStore

logger = logging.getLogger("Phantom MCP")


def _emit_tool_failed_event(
    tool: str, error: str | None, duration_ms: int, approval_id: str | None
) -> None:
    """Best-effort emit of `rt.tool.failed` to the observability event log.

    Called from both async + sync wrappers when a tool call raised. The
    audit log already captures the same data via `record_event()` — this
    is the parallel feed for runtime alerting / dashboards declared in
    `manifest.observability.events[]`.

    Returns None on any failure (event log not yet wired, undeclared
    event name, sqlite hiccup); never raises into caller.
    """
    el = event_log()
    if el is None:
        return
    payload: dict[str, Any] = {
        "tool": tool,
        "error": error,
        "duration_ms": duration_ms,
    }
    if approval_id is not None:
        payload["approval_id"] = approval_id
    try:
        el.record("rt.tool.failed", payload=payload, actor="agent")
    except Exception as exc:  # pragma: no cover — record() already swallows
        logger.debug("rt.tool.failed emit suppressed: %s", exc)


class ToolRegistration(NamedTuple):
    """One tool the MCP should register at startup.

    `namespaced_name` is the namespaced form (`<connector_id>.<tool_name>`).
    `legacy_name` is the flat legacy form
    (`<functionPrefix><tool_name>` for connector tools, or just the
    function name for built-ins); None when no legacy alias should
    be registered.
    `connector_id` is None for tools that aren't part of any
    connector (i.e. runtime built-ins).
    """

    namespaced_name: str
    legacy_name: str | None
    callable: Callable
    connector_id: str | None


def _legacy_alias(function_prefix: str, tool_name: str) -> str | None:
    """Compute the flat legacy alias for a connector tool.

    Normally `f"{function_prefix}{tool_name}"`. But the xsiam tools
    and the cortex-xdr tools are authored with the connector
    prefix ALREADY baked into `spec.tools[].name`, so naive concatenation
    DOUBLES it (`xdr_` + `xdr_incidents_list` -> `xdr_xdr_incidents_list`).
    The natural single-prefix name the model / docs / skills call
    ("xdr_incidents_list") would then never be advertised and would 404
    at the agent layer with "Unknown tool".

    When the tool name already starts with the prefix, the name IS the
    legacy alias — don't re-prepend. Returns None when no prefix applies.
    """
    if not function_prefix:
        return None
    if tool_name.startswith(function_prefix):
        return tool_name
    return f"{function_prefix}{tool_name}"


# ─────────────────────────────────────────────────────────────────
# Built-in legacy tools — NOT part of any connector and NOT
# instance-gated.
# ─────────────────────────────────────────────────────────────────

_BUILTIN_LEGACY_TOOLS: list[tuple[str, Callable]] = [
    ("load_simulation_skills", simulation_skills.load_simulation_skills),
    ("skills_list_all", skills_crud.skills_list_all),
    ("skills_read", skills_crud.skills_read),
    ("skills_create", skills_crud.skills_create),
    ("skills_update", skills_crud.skills_update),
    # NB: skills_delete is registered below, NOT here. The Phase-11
    # gated wrapper at self_mod_tools.skills_delete intercepts the call,
    # checks manifest.approvals.humanRequired[], and dispatches through
    # gate_and_execute(). Pointing the registration at skills_crud.skills_delete
    # directly would bypass the gate.
    # Cognitive tools (sessions + memory). The agent calls
    # these to manipulate its own conversation history and semantic
    # recall store. Like the skills_* tools, they're agent-runtime
    # built-ins, not connector-mediated, so they bypass the per-
    # instance contextvar wrapper.
    ("memory_store", cognitive_tools.memory_store),
    ("memory_search", cognitive_tools.memory_search),
    # memory_delete gives "forget that" a chat-reachable path (the
    # REST equivalent is DELETE /api/v1/memories/by-key/.).
    # Not a credential (no SecretStore value) and not catalog metadata
    # — plain operator-workflow-state CRUD, same category as memory
    # itself, so it belongs on the same side as memory_store/_search.
    ("memory_delete", cognitive_tools.memory_delete),
    # The model has no clock: without this it computed an epoch two years off. Read-only, no state.
    ("time_now", cognitive_tools.time_now),
    ("sessions_list", cognitive_tools.sessions_list),
    ("sessions_history", cognitive_tools.sessions_history),
    # Knowledge base. READ-ONLY at the agent surface; the
    # bundle's manifest.kbWrites: [] enforces that there's no
    # `knowledge_store` counterpart. The KB is populated at boot from
    # `bundles/spark/kbs/<name>/` directories per the manifest's
    # knowledge.bundled[] declaration.
    ("knowledge_search", cognitive_tools.knowledge_search),
    ("knowledge_list", cognitive_tools.knowledge_list),
    # Agent self-modification (Tier 1: read tools).
    # Lets the agent introspect the same operator-facing state the UI
    # shows: jobs, settings, instances, providers, approvals, audit,
    # api keys, manifest, metrics. None of these are gated — they're
    # pure reads. The corresponding write tools (Tier 2-4) are gated via
    # approvals.humanRequired[].
    ("jobs_list", self_mod_tools.jobs_list),
    ("jobs_get", self_mod_tools.jobs_get),
    ("jobs_runs", self_mod_tools.jobs_runs),
    ("settings_get", self_mod_tools.settings_get),
    ("personality_get", self_mod_tools.personality_get),
    ("instances_list", self_mod_tools.instances_list),
    ("instances_get", self_mod_tools.instances_get),
    # Log destinations read-only surface. Agent can list +
    # get redacted destination rows; UPDATE/DELETE/PROBE + any secret-bearing
    # CREATE stay REST-only (operator UI) per the credential guardrail.
    ("log_destinations_list", self_mod_tools.log_destinations_list),
    ("log_destinations_get", self_mod_tools.log_destinations_get),
    # Secretless-syslog CREATE only (catalog-side; writes NO
    # SecretStore value). Lets the agent cold-start a plain syslog
    # destination during store-driven resolution. Secret types (TLS-syslog,
    # xsiam_http, splunk_hec) are structurally rejected by the tool → UI-only.
    ("log_destinations_create", self_mod_tools.log_destinations_create),
    ("providers_list", self_mod_tools.providers_list),
    ("providers_get", self_mod_tools.providers_get),
    ("approvals_list_pending", self_mod_tools.approvals_list_pending),
    ("approvals_list_history", self_mod_tools.approvals_list_history),
    ("notifications_list", self_mod_tools.notifications_list),
    ("notifications_unread_count", self_mod_tools.notifications_unread_count),
    ("audit_search", self_mod_tools.audit_search),
    ("audit_recent", self_mod_tools.audit_recent),
    ("api_keys_list", self_mod_tools.api_keys_list),
    ("manifest_get", self_mod_tools.manifest_get),
    ("metrics_snapshot", self_mod_tools.metrics_snapshot),
    ("health_status", self_mod_tools.health_status),
    # Tier 2 soft-write tools. Each gates via
    # manifest.approvals.humanRequired[] so the agent can't mutate
    # runtime state without operator confirmation. The
    # _approval_gate.gate_and_execute helper handles the request +
    # wait + execute dance and emits agent_self_mod_* audit events.
    ("jobs_create", self_mod_tools.jobs_create),
    ("jobs_update", self_mod_tools.jobs_update),
    ("jobs_run_now", self_mod_tools.jobs_run_now),
    ("personality_update", self_mod_tools.personality_update),
    # Atomic merge variant. Agent prefers this when changing
    # only a subset of personality fields (e.g. just personalityMd)
    # so it doesn't have to read-then-write to avoid wiping the rest.
    # Same approval gate as personality_update (shares humanRequired
    # key — see self_mod_tools.personality_patch).
    ("personality_patch", self_mod_tools.personality_patch),
    ("settings_update", self_mod_tools.settings_update),
    ("notifications_dismiss", self_mod_tools.notifications_dismiss),
    ("notifications_dismiss_all", self_mod_tools.notifications_dismiss_all),
    ("approvals_resolve", self_mod_tools.approvals_resolve),
    # Tier 3 destructive tools. Same gate as Tier 2 but
    # risk_tier='destructive' so the approval card UI surfaces a red
    # banner. Each is a thin wrapper around an existing store method
    # (delete_job / delete / reset_to_default / clear).
    ("jobs_delete", self_mod_tools.jobs_delete),
    ("skills_delete", self_mod_tools.skills_delete),
    ("personality_reset", self_mod_tools.personality_reset),
    ("settings_reset", self_mod_tools.settings_reset),
    # ─────────────────────────────────────────────────────────────
    # Agent credential guardrail — DO NOT add credential tools
    # ─────────────────────────────────────────────────────────────
    # The tools named in usecase.credential_guardrail.CREDENTIAL_SIDE_TOOLS
    # (providers_*, instances_* and api_keys_* writes) are NOT registered
    # as MCP entries. That module is the one canonical list; the check
    # right after this list fails closed if any of them appears here.
    # They remain available at the REST surface (/api/v1/providers,
    # /api/v1/instances, /api/v1/api_keys) so the operator UI works,
    # but the chat agent has no handle to them, directly or through
    # agent_batch_propose.
    #
    # The agent retains the READ-ONLY surface (providers_list,
    # providers_get, instances_list, instances_get, api_keys_list)
    # — those return secrets redacted as "***".
    #
    # If you're adding a new MCP tool, ask: does it read or write a
    # SecretStore value? If yes, REST-only. See CLAUDE.md "Agent
    # credential guardrail (MANDATORY)" for the full rule.
    # They are deliberately absent from the agent surface, not merely gated.
    # ─────────────────────────────────────────────────────────────
    # Tier 5 multi-action batch. Approval-gated like every
    # other self-mod tool, but the ONE approval card it shows covers
    # N actions; the operator approves the plan once. Each action
    # inside executes under the approval-bypass contextvar so the
    # nested gate is a no-op (audit-only). See self_mod_tools.
    ("agent_batch_propose", self_mod_tools.agent_batch_propose),
    # Benchmark runner. Agent invokes from chat
    # with "run the phantom-soc-v1 benchmark"; the runner dispatches
    # each case in the manifest, scores, and records to
    # benchmark_runs.db. See usecase/benchmark_runner.py.
    ("bench_run", self_mod_tools.bench_run),
    # ─────────────────────────────────────────────────────────────
    # Marketplace tools — CATALOG operations (not credentials)
    # ─────────────────────────────────────────────────────────────
    # Per CLAUDE.md's "catalog boundary ≠ credential boundary"
    # distinction (extending the agent credential guardrail).
    # These tools mutate marketplace-level metadata (install state,
    # connector schemas, registry membership) — NOT credentials. The
    # operator phrases "install the web connector", "upload this
    # connector.yaml", "remove cortex-content from the marketplace"
    # are all in-bounds for the agent. The phrase "create an instance
    # of caldera with these credentials" is NOT (instance creation
    # carries secrets — still operator-only).
    ("marketplace_list", self_mod_tools.marketplace_list),
    ("marketplace_install", self_mod_tools.marketplace_install),
    ("marketplace_uninstall", self_mod_tools.marketplace_uninstall),
    ("connector_upload", self_mod_tools.connector_upload),
    # Closed-loop coverage engine. Read + ingest surface for the
    # detection inventory (detections_* and technique_coverage);
    # snapshots, diffs, gap detection and the `coverage_cycle_run`
    # orchestrator follow.
    ("detections_sync", coverage_tools.detections_sync),
    ("detections_list", coverage_tools.detections_list),
    ("detections_get", coverage_tools.detections_get),
    ("detections_recent_fires", coverage_tools.detections_recent_fires),
    ("technique_coverage", coverage_tools.technique_coverage),
    # Snapshots + drift.
    ("coverage_snapshot_take", coverage_tools.coverage_snapshot_take),
    ("coverage_snapshot_list", coverage_tools.coverage_snapshot_list),
    ("coverage_snapshot_get", coverage_tools.coverage_snapshot_get),
    ("coverage_diff", coverage_tools.coverage_diff),
    # Gap detection.
    ("coverage_gaps", coverage_tools.coverage_gaps),
    # Closed-loop orchestrator. Used by the
    # manifest job `continuous-coverage-cycle` and callable from
    # chat for ad-hoc cycles. Bypasses the connector tool wrapper
    # and POSTs directly to XSIAM PAPI using InstanceStore +
    # SecretStore for auth resolution.
    ("coverage_cycle_run", coverage_tools.coverage_cycle_run),
    # Asset generation. Assets live in a subsystem log ingestion cannot
    # reach, so populating the Cortex Asset Inventory is a deliberate,
    # separate action rather than a side effect of generating logs. The
    # tool takes a `logdest:<id>` reference and resolves it MCP-side, so
    # the destination's API key never crosses the agent's tool surface —
    # same property log_destination_resolver gives create_data_worker.
    ("phantom_generate_assets", asset_tools.phantom_generate_assets),
]

# Fail closed at import: a credential-side tool must never become an agent tool.
assert_no_credential_tools(
    (name for name, _fn in _BUILTIN_LEGACY_TOOLS),
    where="_BUILTIN_LEGACY_TOOLS",
)


# ─────────────────────────────────────────────────────────────────
# Bundle path resolution
# ─────────────────────────────────────────────────────────────────

DEFAULT_BUNDLE_ROOT = "/app/bundle"


def _bundle_root() -> Path:
    raw = os.getenv("BUNDLE_ROOT", DEFAULT_BUNDLE_ROOT)
    root = Path(raw).resolve()
    if not root.is_dir():
        raise RuntimeError(
            f"Bundle root {root} does not exist. Set BUNDLE_ROOT env var "
            f"or mount the bundle at {DEFAULT_BUNDLE_ROOT}."
        )
    return root


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return data


# ─────────────────────────────────────────────────────────────────
# No env-var auto-migration.
#
# connector_loader never materializes instances from environment
# variables (CALDERA_URL, PAPI_AUTH_HEADER, etc.) at boot. An env-var
# auto-migrate path would cause:
#
#   * "default state = no instances" requirement violations — the
#     operator wants fresh installs to come up clean, but auto-migrate
#     silently fills the instance store from env vars at every boot.
#   * "which path created this instance?" debugging — when a setup
#     form save and auto-migrate both fire in the same boot, the row
#     that survives depends on call order, not operator intent.
#   * Coupling between connector_loader (a loader concern) and env
#     settings (a config concern) that crossed two responsibility
#     boundaries.
#
# Per the canonical-state discipline (one state surface, one storage
# home), instances are created explicitly:
#
#   1. Operator clicks Install on the marketplace card (or the agent
#      calls the marketplace_install MCP tool).
#   2. Operator creates an instance via /connectors → Create Instance
#      (or POST /api/v1/instances) — supplying the config + secrets.
#
# Installs that already carry instances in the persisted data volume
# but no marketplace install row are handled by
# `usecase.marketplace_store.MarketplaceStore.upgrade_install_existing_instances`,
# which runs once at boot and auto-installs every connector that
# already has an instance row, so existing connectors stay installed.
# ─────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────
# Tool resolution per spec §7.4.1
# ─────────────────────────────────────────────────────────────────


# Map connector.yaml `type` → Python annotation. Anything outside this
# table falls back to `Any` so the tool still registers; the connector's
# own FastMCP will validate against the JSON Schema it derives from its
# real signature.
_YAML_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _build_container_proxy(
    *,
    connector_id: str,
    tool_name: str,
    args_spec: list[dict[str, Any]],
    description: str,
    proxy_call_tool: Callable,
) -> Callable:
    """Synthesize an async function whose signature mirrors a connector's
    `connector.yaml` tool args, then forwards the call to the connector's
    container via MCP-over-HTTP.

    Why this exists: FastMCP introspects the function's signature to build
    the MCP tool's input schema (one Pydantic field per parameter) and
    rejects callables that use **kwargs. The container-style branch
    doesn't have a real Python function to register — the actual function
    lives in the connector container — so we synthesize one whose only job
    is to satisfy FastMCP's introspection and forward to proxy_call_tool().

    The body packs all bound parameters into a dict (skipping None for
    optional args, matching agent-side legacy behavior) and POSTs to the
    container. The container's own FastMCP does the real validation
    against its in-process function signatures, so this layer doesn't need
    strict types — `Any` is good enough.
    """
    from config.config import get_config  # noqa: PLC0415

    # Build parameter declarations for compile(). Required args MUST come
    # first (no default), then optional args (with `= None`) — Python's
    # syntax rejects "parameter without a default follows parameter with
    # a default" otherwise. Appending in YAML order would produce invalid
    # Python the moment a connector
    # had required-after-optional in its args (caldera/create_adversary
    # has name, description=None, ability_ids in that order — the
    # synthesized signature wouldn't compile). Now we split + concatenate
    # so YAML order is irrelevant to the generated source's validity;
    # the param_names list (used to pack the args dict at call time)
    # still preserves YAML order for human-readable kwarg expansion in
    # logs / errors.
    #
    # Names are sanitized in the extreme case the YAML uses non-identifier
    # characters; today every bundled connector uses snake_case so this is
    # defensive.
    required_decls: list[str] = []
    optional_decls: list[str] = []
    param_names: list[str] = []
    annotations: dict[str, Any] = {}
    for arg in args_spec:
        name = arg.get("name")
        if not isinstance(name, str) or not name.isidentifier():
            # Skip — can't map to a Python parameter cleanly. Container
            # will see no value for this arg; the operator will get a
            # validation error from the container's MCP if it was
            # required. Logged loudly so the bundle author notices.
            logger.warning(
                "connector %r tool %r: skipping arg %r (not a valid Python "
                "identifier); container will not receive it",
                connector_id, tool_name, name,
            )
            continue
        py_type = _YAML_TYPE_MAP.get(arg.get("type", "").lower(), Any)
        annotations[name] = py_type
        if arg.get("required"):
            required_decls.append(name)
        else:
            # `= None` makes it optional; the body filters Nones before
            # forwarding so the container sees an absent key (not a
            # null) and can apply its own default.
            optional_decls.append(f"{name}=None")
        param_names.append(name)
    param_decls = required_decls + optional_decls

    annotations["return"] = Any
    param_list_src = ", ".join(param_decls)
    pack_src = ", ".join(f"{n!r}: {n}" for n in param_names) or ""

    # Synthesize the function. Source is built from connector.yaml (bundle-
    # immutable, not operator input). We compile + run via the builtins
    # exec primitive aliased to a local name; the closure captures
    # connector_id + tool_name + proxy_call_tool + get_config via the
    # namespace dict because compiled function definitions can't see
    # surrounding-frame locals.
    src = (
        f"async def _proxy({param_list_src}):\n"
        f"    cfg = get_config()\n"
        f"    container_url = getattr(cfg, 'container_url', None)\n"
        f"    if not container_url:\n"
        f"        raise RuntimeError(\n"
        f"            f\"connector {connector_id!r} instance has no \"\n"
        f"            f\"container_url — phantom-updater hasn't started \"\n"
        f"            f\"the container yet, or the routing entry was \"\n"
        f"            f\"deleted. Try recreating the instance via /connectors UI.\"\n"
        f"        )\n"
        f"    args = {{ {pack_src} }}\n"
        f"    args = {{k: v for k, v in args.items() if v is not None}}\n"
        f"    return await proxy_call_tool(container_url, {tool_name!r}, args)\n"
    )
    ns: dict[str, Any] = {
        "get_config": get_config,
        "proxy_call_tool": proxy_call_tool,
        "Any": Any,
    }
    _run = __builtins__["exec"] if isinstance(__builtins__, dict) else __builtins__.exec
    try:
        _run(compile(src, f"<container_proxy:{connector_id}/{tool_name}>", "exec"), ns)
    except SyntaxError as exc:
        raise RuntimeError(
            f"failed to build container proxy for "
            f"{connector_id}/{tool_name}: {exc}\n--- generated source ---\n{src}"
        ) from exc
    fn = ns["_proxy"]
    fn.__name__ = f"proxy_{connector_id}_{tool_name}"
    fn.__qualname__ = fn.__name__
    fn.__doc__ = description or f"Proxy to {connector_id} container for {tool_name}."
    fn.__annotations__ = annotations
    return fn


def _resolve_callable(
    connector_id: str,
    connector_dir: Path,
    spec_yaml: dict,
    instance_kwargs: dict | None = None,
) -> tuple[list[tuple[str, Callable]], str]:
    """Resolve tool callables for a connector — container-only path.

    The only runtime style is 'container' (per-instance container, tool
    calls proxied over MCP-over-HTTP): every connector runs as a
    per-instance container so the dispatch model is uniform.

    The schema-level enforcement (bundles/spark/connectors/connector
    .schema.json) was rejects style != 'container'; this function raises ValueError as a defense-in-
    depth check in case any user-uploaded connector.yaml slips past
    the schema (the upload path validates first; this is the
    second line of defense).

    See `_build_container_proxy` for the synthesized-signature
    machinery FastMCP requires.
    """
    runtime_mapping = spec_yaml.get("runtimeMapping") or {}
    style = runtime_mapping.get("style", "container")
    function_prefix = runtime_mapping.get("functionPrefix", "")

    if style != "container":
        raise ValueError(
            f"connectors/{connector_id}/connector.yaml: runtimeMapping.style "
            f"must be 'container' (got {style!r}). In-process "
            f"module/class dispatch is not supported — every connector runs "
            f"as a per-instance phantom-connector-<id>-<name> container."
        )

    # The connector code DOESN'T live in this Python process — it runs
    # in a separate container that the agent reaches via MCP-over-HTTP.
    # We don't importlib here; we synthesize closures that read the
    # per-instance `container_url` from get_config() at call time and
    # forward to proxy_call_tool(). The contextvar plumbing in
    # _wrap_with_instance handles instance binding identically for
    # every connector now.
    from pkg.connector_proxy import proxy_call_tool  # noqa: PLC0415

    pairs: list[tuple[str, Callable]] = []
    tools = (spec_yaml.get("spec") or {}).get("tools") or []
    for tool in tools:
        tool_name = tool.get("name")
        if not isinstance(tool_name, str):
            raise ValueError(
                f"connectors/{connector_id}/connector.yaml: spec.tools[] "
                f"entry missing 'name' (got {tool!r})"
            )

        # FastMCP rejects callables that use **kwargs — it introspects
        # the function signature to derive the MCP tool's input schema
        # (one Pydantic field per parameter) and refuses anything it
        # can't enumerate. So we synthesize a function whose signature
        # mirrors the connector.yaml `args` declaration, then close
        # over `tool_name` and forward to proxy_call_tool().
        args_spec = tool.get("args") or []
        proxy_fn = _build_container_proxy(
            connector_id=connector_id,
            tool_name=tool_name,
            args_spec=args_spec,
            description=tool.get("description") or "",
            proxy_call_tool=proxy_call_tool,
        )
        pairs.append((tool_name, proxy_fn))

    return pairs, function_prefix


# ─────────────────────────────────────────────────────────────────
# Per-instance contextvar wrapping
# ─────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────
# Manifest-key → Settings-attr translation table.
#
# `manifest.yaml:setup.bindsInstances[].template.config` uses clean
# abstract keys (baseUrl, apiKey, etc.) — those are what bundle
# authors write and what the connector.yaml configSchema documents.
# But the connector function code reads `get_config().caldera_url`
# i.e. Settings attribute names. The contextvar proxy looks up keys
# by Settings name, so we translate manifest keys → Settings names
# before stuffing the dict into the contextvar.
#
# Only setup-form-created instances pass through this map. If the
# connector functions are refactored to use clean abstract names, this
# map can shrink to {} and eventually be deleted.
# ─────────────────────────────────────────────────────────────────

_MANIFEST_TO_SETTINGS_KEYS: dict[str, dict[str, str]] = {
    "caldera": {
        "baseUrl": "caldera_url",
        "apiKey": "caldera_api_key",
        # redUser/redPassword aren't in Settings today — they're caldera
        # admin browser-flow creds. They go into the instance dict
        # untranslated and any consumer that needs them reads by the
        # original key.
    },
    "xsiam": {
        # Primary keys are the uniform names. Legacy papi* keys map to the SAME settings attributes so old
        # manifest-template values translate identically.
        "api_url": "papi_url_env_key",
        "api_key": "papi_auth_header_key",
        "api_id": "papi_auth_id_key",
        "papiUrl": "papi_url_env_key",
        "papiAuthHeader": "papi_auth_header_key",
        "papiAuthId": "papi_auth_id_key",
        "playgroundId": "playground_id",
        "webhookEndpoint": "webhook_endpoint",
        "webhookKey": "webhook_key",
    },
    "xlog": {
        "baseUrl": "xlog_url",
        "apiToken": "xlog_api_token",
        "webhookEndpoint": "webhook_endpoint",
        "webhookKey": "webhook_key",
    },
    "cortex-xdr": {
        # cortex-xdr uses the uniform api_* names — no legacy aliases.
        # No settings-attribute mapping needed because cortex-xdr
        # instance config is operator-form-driven only (no env-var
        # first-time-setup path). The empty dict keeps the
        # connector visible in the registry without forcing any
        # synthetic key translation.
    },
}


def _translate_keys(connector_id: str, source: dict[str, Any]) -> dict[str, Any]:
    """Translate manifest-style keys to Settings attribute names.

    Keys not in the translation table pass through unchanged — auto-
    migrated instances already use Settings names, so this is a no-op
    for them.
    """
    table = _MANIFEST_TO_SETTINGS_KEYS.get(connector_id, {})
    if not table:
        return source
    return {table.get(k, k): v for k, v in source.items()}


def _wrap_with_instance(
    fn: Callable,
    instance: Instance,
    secret_store: SecretStore | None = None,
    tool_name: str | None = None,
    legacy_name: str | None = None,
    human_required: set[str] | None = None,
) -> Callable:
    """Return a wrapper that sets the instance contextvar around `fn`.

    Secret VALUES are read from the SecretStore on EVERY call
    (not at registration time) so live secret rotation works — change
    the underlying file, next call sees the new value.

    Every call records one ACTION_TOOL_CALL audit event, with
    duration_ms and status (success/failure). The actor is tagged
    "agent" — that's the contract: anything coming through the MCP
    tool dispatch is the agent acting on behalf of (a delegated)
    user.

    Tools whose name is in `human_required` (drawn from the
    manifest's `approvals.humanRequired`) gate on a human approval
    before executing. The wrapper:
      1. Records ACTION_APPROVAL_REQUESTED in audit
      2. Calls `bus.request(...)` → gets approval_id
      3. Awaits `bus.wait_async(approval_id)` (or sync variant)
      4. Records ACTION_APPROVAL_RESOLVED with resolver + decision
      5. If approved: proceeds to call fn (records tool_call with
         metadata.approved_by + approval_id)
      6. If denied/timeout: raises ApprovalDeniedError or
         ApprovalTimeoutError → caller (the MCP) sees a tool error
         and the agent can react.

    The wrapper preserves fn's signature (via functools.wraps) so
    fastmcp's introspection sees the right Pydantic types / parameter
    names. Both async and sync callables are supported.
    """
    import time as _time

    from usecase.approvals_bus import (
        ApprovalDeniedError,
        ApprovalTimeoutError,
        STATUS_APPROVED,
        STATUS_TIMEOUT,
        approvals_bus,
        needs_human_approval,
    )
    from usecase.audit_log import (
        ACTION_APPROVAL_REQUESTED,
        ACTION_APPROVAL_RESOLVED,
        ACTION_TOOL_CALL,
        record_event,
        set_current_actor,
        reset_current_actor,
    )

    connector_id = instance.connector_id
    namespaced = f"{connector_id}.{tool_name}" if tool_name else connector_id
    bare_tool_name = tool_name or namespaced
    # Per-instance `trusted: true` flag in the instance config
    # bypasses the human-approval gate. Operators set this on lab/
    # sandbox connectors where every action is intentional; production
    # connectors leave it unset (default false) so the manifest's
    # humanRequired list still fires. See approvals_bus.needs_human_approval.
    instance_trusted = bool(instance.config.get("trusted", False))
    require_approval = needs_human_approval(
        tool_name=bare_tool_name,
        namespaced=namespaced,
        legacy_name=legacy_name,
        human_required=human_required or set(),
        instance_trusted=instance_trusted,
    )

    def _resolve_overrides() -> dict[str, Any]:
        merged = instance.merged_config(secret_store=secret_store)
        return _translate_keys(connector_id, merged)

    def _audit_arg_keys(args: tuple, kwargs: dict[str, Any]) -> list[str]:
        # Record only the SHAPE of the call (key names), never the
        # values — args may include credentials passed by the agent.
        keys = list(kwargs.keys())
        if args:
            keys.append(f"<{len(args)} positional>")
        return keys

    def _gate_request(args: tuple, kwargs: dict[str, Any]) -> str | None:
        """Open an approval request if needed; return id or None."""
        if not require_approval:
            return None
        bus = approvals_bus()
        if bus is None:
            # Bus not wired (boot order bug or test harness). Fail
            # closed — better to refuse than to silently bypass.
            raise ApprovalDeniedError(
                f"tool {namespaced} requires human approval but the "
                "approvals bus is not configured"
            )
        # Snapshot args by KEY (no values, identical to audit metadata
        # rule). The approval row needs enough context for the human to
        # decide; the bus's own _sanitize_args defends against value
        # leaks if the caller ever passes raw credentials.
        approval_id = bus.request(
            tool=bare_tool_name,
            namespaced=namespaced,
            actor="agent",
            args={**kwargs} if kwargs else {"<positional>": len(args)},
        )
        record_event(
            ACTION_APPROVAL_REQUESTED,
            target=f"approval:{approval_id}",
            status="pending",
            actor="agent",
            metadata={
                "approval_id": approval_id,
                "tool": namespaced,
                "connector_id": connector_id,
                "instance_id": instance.id,
                "arg_keys": _audit_arg_keys(args, kwargs),
            },
        )
        return approval_id

    def _gate_finish(approval_id: str, status: str, reason: str | None) -> None:
        """Record resolution in audit. Raises on non-approved status."""
        bus = approvals_bus()
        approval = bus.get(approval_id) if bus else None
        record_event(
            ACTION_APPROVAL_RESOLVED,
            target=f"approval:{approval_id}",
            status=status,
            actor=approval.resolver if approval and approval.resolver else "system",
            metadata={
                "approval_id": approval_id,
                "tool": namespaced,
                "decision": status,
                "reason": reason,
            },
        )
        if status == STATUS_APPROVED:
            return
        if status == STATUS_TIMEOUT:
            raise ApprovalTimeoutError(
                f"tool {namespaced} not approved within timeout "
                f"(approval_id={approval_id})"
            )
        raise ApprovalDeniedError(
            f"tool {namespaced} denied by {approval.resolver if approval else 'unknown'} "
            f"(approval_id={approval_id}, reason={reason!r})"
        )

    def _audit_meta(
        args: tuple, kwargs: dict[str, Any], approval_id: str | None
    ) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "tool": namespaced,
            "connector_id": connector_id,
            "instance_id": instance.id,
            "instance_name": instance.name,
            "arg_keys": _audit_arg_keys(args, kwargs),
        }
        if approval_id is not None:
            meta["approval_id"] = approval_id
            bus = approvals_bus()
            approval = bus.get(approval_id) if bus else None
            if approval and approval.resolver:
                meta["approved_by"] = approval.resolver
        return meta

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            token = set_current_instance(_resolve_overrides())
            actor_token = set_current_actor("agent")
            approval_id: str | None = None
            start = _time.perf_counter()
            status = "success"
            error: str | None = None
            try:
                # Gate on human approval BEFORE running.
                approval_id = _gate_request(args, kwargs)
                if approval_id is not None:
                    bus = approvals_bus()
                    decision, reason = await bus.wait_async(approval_id)
                    _gate_finish(approval_id, decision, reason)
                return await fn(*args, **kwargs)
            except Exception as exc:
                status = "failure"
                error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                duration_ms = int((_time.perf_counter() - start) * 1000)
                meta = _audit_meta(args, kwargs, approval_id)
                if error is not None:
                    meta["error"] = error
                record_event(
                    ACTION_TOOL_CALL,
                    target=f"tool:{namespaced}",
                    status=status,
                    actor="agent",
                    duration_ms=duration_ms,
                    metadata=meta,
                )
                # Mirror failures into the runtime-events feed declared
                # in manifest.observability.events[]. Audit captures the
                # same data, but observability is the high-signal stream
                # that operators wire alerts/dashboards to.
                if status == "failure":
                    _emit_tool_failed_event(
                        namespaced, error, duration_ms, approval_id
                    )
                reset_current_actor(actor_token)
                reset_current_instance(token)

        return async_wrapper

    @functools.wraps(fn)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        token = set_current_instance(_resolve_overrides())
        actor_token = set_current_actor("agent")
        approval_id: str | None = None
        start = _time.perf_counter()
        status = "success"
        error: str | None = None
        try:
            approval_id = _gate_request(args, kwargs)
            if approval_id is not None:
                bus = approvals_bus()
                decision, reason = bus.wait_sync(approval_id)
                _gate_finish(approval_id, decision, reason)
            return fn(*args, **kwargs)
        except Exception as exc:
            status = "failure"
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            duration_ms = int((_time.perf_counter() - start) * 1000)
            meta = _audit_meta(args, kwargs, approval_id)
            if error is not None:
                meta["error"] = error
            record_event(
                ACTION_TOOL_CALL,
                target=f"tool:{namespaced}",
                status=status,
                actor="agent",
                duration_ms=duration_ms,
                metadata=meta,
            )
            # Mirror failures into the runtime-events feed (see async
            # wrapper above for rationale).
            if status == "failure":
                _emit_tool_failed_event(
                    namespaced, error, duration_ms, approval_id
                )
            reset_current_actor(actor_token)
            reset_current_instance(token)

    return sync_wrapper


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────


def _connector_registrations(
    cid: str,
    pairs: list[tuple[str, Callable]],
    function_prefix: str,
    *,
    store: InstanceStore,
    secret_store: SecretStore,
    include_legacy_aliases: bool,
    human_required: set[str],
) -> tuple[list[ToolRegistration], str]:
    """Wrap one connector's tools for registration. Shared by bundle and user
    connectors so the two cannot drift apart. Returns the registrations and the
    label for the "Advertising connectors" log line."""
    # Phantom uses a single instance per connector. Use the first
    # (typically only) instance for the wrap.
    primary = store.list_for(cid)[0]

    # Per-instance disabled-tools filter. Operators
    # disable individual tools via the /connectors Tools tab; we
    # skip them at registration time so they never enter the
    # agent's tool catalog. Opt-out default: empty list = all
    # tools enabled. The filter matches against the BARE tool
    # name (not the namespaced `<connector_id>.<tool>` form) so
    # operator-facing toggle strings stay readable.
    disabled_set = set(primary.disabled_tools or [])
    original_count = len(pairs)
    if disabled_set:
        pairs = [(t, f) for (t, f) in pairs if t not in disabled_set]
        logger.info(
            "Connector %r instance %r: %d/%d tools enabled (operator disabled: %s)",
            cid, primary.name, len(pairs), original_count,
            sorted(disabled_set),
        )
    label = (
        f"{cid} ({primary.name}, {len(pairs)}/{original_count} tools)"
        if disabled_set
        else f"{cid} ({primary.name}, {len(pairs)} tools)"
    )

    registrations: list[ToolRegistration] = []
    for tool_name, raw_fn in pairs:
        namespaced = f"{cid}.{tool_name}"
        # The flat legacy alias. _legacy_alias() guards against the
        # doubled-prefix bug for connectors whose
        # spec.tools[].name already carries the connector prefix.
        legacy = (
            _legacy_alias(function_prefix, tool_name)
            if include_legacy_aliases
            else None
        )
        if legacy == namespaced:
            legacy = None
        wrapped = _wrap_with_instance(
            raw_fn,
            primary,
            secret_store=secret_store,
            tool_name=tool_name,
            legacy_name=legacy,
            human_required=human_required,
        )
        registrations.append(ToolRegistration(namespaced, legacy, wrapped, cid))
    return registrations, label


def iter_registrations(
    include_legacy_aliases: bool = True,
    store: InstanceStore | None = None,
    secret_store: SecretStore | None = None,
) -> Iterator[ToolRegistration]:
    """Yield every tool the MCP should register at startup.

    secret_store is passed through to `_wrap_with_instance`
    so each tool call resolves secrets fresh from the store at call
    time. None defaults to no resolution (legacy values pass through).

    Extracts `approvals.humanRequired` from the manifest and
    passes it through to the wrapper. Tools whose name appears in that
    set will gate on a human approval before executing (see
    InProcessApprovalsBus). The set membership is checked against the
    bare tool name, the namespaced form, AND the legacy alias — so the
    bundle author can use whichever form is most readable.
    """
    root = _bundle_root()
    manifest = _load_yaml(root / "manifest.yaml")
    tool_connectors = manifest.get("toolConnectors") or []

    # humanRequired list from manifest.yaml.
    approvals_block = manifest.get("approvals") or {}
    raw_human_required = approvals_block.get("humanRequired") or []
    human_required: set[str] = {
        s for s in raw_human_required if isinstance(s, str)
    }
    if human_required:
        logger.info(
            "Approvals: %d tool(s) require human approval before execution: %s",
            len(human_required), sorted(human_required),
        )

    if store is None:
        store = InstanceStore(secret_store=secret_store)
    if secret_store is None:
        secret_store = SecretStore()

    # No env-var auto-migrate. Tool registration gates on
    # the union of (marketplace_installs.db install state) AND
    # (instances.db instance presence). Both must be true for the
    # connector's tools to advertise. See connector_loader module
    # header for why there is no auto-migrate.
    declared_ids = {entry.get("id") for entry in tool_connectors if isinstance(entry.get("id"), str)}
    configured_ids = store.configured_connector_ids()

    advertised: list[str] = []
    skipped: list[str] = []

    for entry in tool_connectors:
        cid = entry.get("id")
        path = entry.get("path")
        if not isinstance(cid, str) or not isinstance(path, str):
            raise ValueError(
                f"manifest.yaml: toolConnectors[] entry missing id/path: {entry!r}"
            )

        if cid not in configured_ids:
            skipped.append(cid)
            continue

        connector_dir = (root / path).resolve()
        connector_yaml = connector_dir / "connector.yaml"
        if not connector_yaml.is_file():
            raise ValueError(f"{connector_yaml} does not exist")
        spec = _load_yaml(connector_yaml)
        pairs, function_prefix = _resolve_callable(cid, connector_dir, spec)

        regs, label = _connector_registrations(
            cid, pairs, function_prefix,
            store=store, secret_store=secret_store,
            include_legacy_aliases=include_legacy_aliases,
            human_required=human_required,
        )
        advertised.append(label)
        yield from regs

    # User-uploaded connectors. Same gate as bundle connectors: they advertise
    # tools only while they have an instance. Two differences: no legacy flat aliases
    # (an upload must never shadow a built-in tool name), and a broken upload is logged
    # and skipped instead of raising, so it cannot stop every other connector's tools.
    for ref in user_connectors(exclude_ids=declared_ids):
        if ref.id not in configured_ids:
            skipped.append(ref.id)
            continue
        try:
            spec = _load_yaml(ref.yaml_path)
            pairs, function_prefix = _resolve_callable(ref.id, ref.dir, spec)
            regs, label = _connector_registrations(
                ref.id, pairs, function_prefix,
                store=store, secret_store=secret_store,
                include_legacy_aliases=False,
                human_required=human_required,
            )
        except Exception:  # noqa: BLE001 - one bad upload must not break the rest
            logger.exception("User connector %r could not be registered; skipping it", ref.id)
            continue
        advertised.append(f"{label} [user]")
        yield from regs

    if skipped:
        logger.info(
            "Tool advertisement gated: skipping %d connector(s) without "
            "configured instances: %s",
            len(skipped),
            ", ".join(skipped),
        )
    if advertised:
        logger.info("Advertising connectors: %s", "; ".join(advertised))

    for legacy_name, fn in _BUILTIN_LEGACY_TOOLS:
        # Re-checked here (not only at import) so a list edited at runtime,
        # e.g. by a test or a plugin, cannot slip a credential tool through.
        assert_no_credential_tools([legacy_name], where="built-in tool registration")
        yield ToolRegistration(legacy_name, None, fn, None)


# ─────────────────────────────────────────────────────────────────
# Module-level singletons for the hot-reload pipeline.
#
# `set_reload_state(mcp, store, secret_store, tool_registry,
#                   include_legacy)` is called once from main.py after
# the initial registration completes. The /api/v1/admin/reload_tools
# endpoint and the post-container_url auto-reload in api/instances.py both pull
# this state to invoke `register_all_tools()` without needing
# explicit DI from every callsite.
# ─────────────────────────────────────────────────────────────────

_reload_state: dict[str, Any] | None = None


def set_reload_state(
    mcp: Any,
    store: InstanceStore,
    secret_store: SecretStore | None,
    tool_registry: dict[str, Any],
    include_legacy: bool,
) -> None:
    global _reload_state
    _reload_state = {
        "mcp": mcp,
        "store": store,
        "secret_store": secret_store,
        "tool_registry": tool_registry,
        "include_legacy": include_legacy,
    }


def reload_tools_now() -> tuple[int, int] | None:
    """Trigger a tool-registry reload using the wired state.
    Returns (newly_namespaced, newly_legacy), or None if not yet wired.
    """
    if _reload_state is None:
        return None
    return register_all_tools(
        mcp=_reload_state["mcp"],
        store=_reload_state["store"],
        secret_store=_reload_state["secret_store"],
        tool_registry=_reload_state["tool_registry"],
        include_legacy=_reload_state["include_legacy"],
    )


def register_all_tools(
    mcp: Any,
    store: InstanceStore,
    secret_store: SecretStore | None,
    tool_registry: dict[str, Any],
    include_legacy: bool = True,
) -> tuple[int, int]:
    """Register every tool that the current InstanceStore + bundle imply.

    Always re-registers (does NOT skip already-registered names). This
    is intentional: when an instance is deleted and recreated through the
    instance API, the old instance is gone.
    The OLD wrappers held closure references to the OLD instance
    objects whose secret_refs now point to deleted SecretStore paths;
    re-registering swaps in fresh wrappers with the NEW instance
    references. FastMCP's mcp.tool(name=X) tolerates duplicate-name
    registration (logs a "Component already exists" warning) and
    overrides cleanly — verified empirically on FastMCP 2.13+.

    Returns (namespaced_count, legacy_count) — total counts on this
    pass, NOT just newly added. The hot-reload caller uses the
    returned counts as a sanity signal; the post-setup auto-reload
    response folds them into the operator-visible JSON.

    Used by:
      * `main.py` async_main() at boot — first call, populates from zero.
      * `api/admin.py` /reload_tools endpoint — operator-driven reload.
      * `api/instances.py` after a connector instance's container_url is
        stored — auto-reload so the connector wrappers see it without a
        restart.
    """
    # Clear the tool_registry first so the dict reflects current
    # state. The previous-pass entries get replaced by the loop below.
    tool_registry.clear()

    namespaced_count = 0
    legacy_count = 0
    for reg in iter_registrations(
        include_legacy_aliases=include_legacy,
        store=store,
        secret_store=secret_store,
    ):
        # Re-register unconditionally. FastMCP overrides on duplicate
        # name; the warning it logs is benign in this pattern.
        mcp.tool(name=reg.namespaced_name)(reg.callable)
        tool_registry[reg.namespaced_name] = reg.callable
        namespaced_count += 1
        if reg.legacy_name and reg.legacy_name != reg.namespaced_name:
            mcp.tool(name=reg.legacy_name)(reg.callable)
            tool_registry[reg.legacy_name] = reg.callable
            legacy_count += 1
    return namespaced_count, legacy_count


def tool_summary(store: InstanceStore | None = None) -> dict[str, int]:
    """Return per-connector tool counts ONLY for connectors with instances.

    Connectors without instances contribute 0 (gated). Built-in legacy
    tools count regardless.
    """
    summary: dict[str, int] = {}
    if store is None:
        store = InstanceStore()
    configured = store.configured_connector_ids()
    root = _bundle_root()
    manifest = _load_yaml(root / "manifest.yaml")
    for entry in manifest.get("toolConnectors") or []:
        cid = entry.get("id")
        if not isinstance(cid, str):
            continue
        spec = _load_yaml((root / entry["path"]).resolve() / "connector.yaml")
        tools = (spec.get("spec") or {}).get("tools") or []
        summary[cid] = len(tools) if cid in configured else 0
    bundle_ids = {e.get("id") for e in manifest.get("toolConnectors") or [] if isinstance(e, dict)}
    for ref in user_connectors(exclude_ids=bundle_ids):
        try:
            tools = (_load_yaml(ref.yaml_path).get("spec") or {}).get("tools") or []
        except Exception:  # noqa: BLE001 - a bad upload is skipped, same as at registration
            continue
        summary[ref.id] = len(tools) if ref.id in configured else 0
    summary["_builtin_legacy"] = len(_BUILTIN_LEGACY_TOOLS)
    return summary
