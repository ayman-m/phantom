"""Agent self-modification built-in tools — Tier 1 (read-only).

These tools let the agent inspect the same runtime state the operator
sees in the admin UI: jobs, settings, instances, providers, approvals,
notifications, audit log, api keys, manifest, and metrics. They're
the read half of the "agent configures itself via chat" feature
(spec patch in docs/agent-self-modification.md).

# Why "self-modification" includes pure reads

A SOC operator typing "what jobs do I have scheduled?" expects the
agent to actually look — not paraphrase from memory of an older turn.
Without these read tools, the agent has to either (a) lie convincingly
or (b) say "I can't see that". Both are bad. The reads close the
introspection gap; the writes (Tier 2-4) close the mutation gap.

# Approval gates

NONE of these tools are gated. They're pure reads: no audit-worthy
state change, no destructive risk. Auditing happens at the underlying
store layer where appropriate (e.g. kb.get_doc emits a
`kb_doc_read` event; instances_get does NOT — connector configs are
read-mostly already).

# Singleton lookup pattern

Each tool resolves its dependency through that store's module-level
singleton (memory_store(), kb_store(), instance_store(), etc.) at
call time. If the runtime didn't wire the store (test harness, early
boot), the tool returns a clean error instead of crashing. Same
convention as cognitive_tools.memory_store / .knowledge_search.

# Schema

Each tool takes plain Python args (FastMCP coerces from JSON-RPC
arguments). Return shape is always `dict[str, Any]` with one of:
  - `{"<resource>s": [...], "count": N}` for list endpoints
  - `{"<resource>": {...}}` for get endpoints
  - `{"error": "..."}` when the underlying store is missing or fails

The agent's chat-route system instruction teaches it which
tool to reach for given operator phrasing — see the per-tool docstring
for the trigger phrase examples.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from usecase.credential_guardrail import (
    CredentialGuardrailError,
    assert_no_credential_tools,
    is_credential_tool,
)
from usecase.settings_store import is_agent_protected_setting

logger = logging.getLogger("Phantom MCP")


# ─────────────────────────────────────────────────────────────────
# Jobs — agent reads its own scheduled work.
# Trigger phrases: "what jobs are scheduled?", "list my cron jobs",
# "did the daily SOC report run today?", "show me job runs"
# ─────────────────────────────────────────────────────────────────


def jobs_list(source: str | None = None) -> dict[str, Any]:
    """List all scheduled jobs (manifest + runtime).

    Args:
        source: optional filter — "manifest" or "runtime". Null = all.
            Manifest jobs are baked into the bundle; runtime jobs were
            added via the API (and mirror to <data_root>/jobs/*.yaml).

    Returns {jobs: [{name, cron, timezone, action, source, enabled,
                     last_status, next_due_at, ...}], count}.
    """
    from usecase.job_scheduler import scheduler
    s = scheduler()
    if s is None:
        return {"error": "scheduler not initialized on this MCP runtime"}
    jobs = [j.to_dict() for j in s.list_jobs()]
    if source in ("manifest", "runtime"):
        jobs = [j for j in jobs if j.get("source") == source]
    return {"jobs": jobs, "count": len(jobs)}


def jobs_get(name: str) -> dict[str, Any]:
    """Fetch a single job by name (the unique identifier).

    Args:
        name: job name as declared in manifest.jobs[] or POSTed via
            /api/v1/jobs.

    Returns {job: {...}} or {error} on miss.
    """
    from usecase.job_scheduler import scheduler
    s = scheduler()
    if s is None:
        return {"error": "scheduler not initialized on this MCP runtime"}
    j = s.get_job(name)
    if j is None:
        return {"error": f"job {name!r} not found"}
    return {"job": j.to_dict()}


def jobs_runs(name: str, limit: int = 20) -> dict[str, Any]:
    """Recent run history for a job (succeeded + failed).

    Args:
        name: job name.
        limit: max rows (1-200). Default 20.

    Returns {runs: [{run_id, started_at, finished_at, status, result,
                     error}], count}.
    """
    from usecase.job_scheduler import scheduler
    s = scheduler()
    if s is None:
        return {"error": "scheduler not initialized on this MCP runtime"}
    j = s.get_job(name)
    if j is None:
        return {"error": f"job {name!r} not found"}
    limit = max(1, min(int(limit or 20), 200))
    runs = s.list_runs(name, limit=limit)
    return {
        "name": name,
        "runs": [r.to_dict() if hasattr(r, "to_dict") else r for r in runs],
        "count": len(runs),
    }


# ─────────────────────────────────────────────────────────────────
# Settings — runtime overrides over manifest.settings.defaults.
# Trigger phrases: "what's my default scenario?", "show my settings",
# "what model am I using?"
# ─────────────────────────────────────────────────────────────────


def settings_get() -> dict[str, Any]:
    """Snapshot of runtime settings: defaults, overridable allowlist,
    current overrides, and the merged effective values.

    Returns {defaults, overridable, effective, overrides}.

    `effective.defaultModel` is the install's default model, a canonical
    "provider/model" ref (provider ids: vertex, anthropic, openai), for example
    "anthropic/claude-sonnet-5-5". It is what a chat turn, job or subagent
    uses when no model is picked for it. The operator sets it with "Set as
    default" on /models; you cannot change it (see settings_update). If it names
    a provider that has no credentials, chat uses the recommended model of the
    first configured provider instead, which /models shows as "Default
    (derived)". To say which model THIS conversation runs on, use the model
    named in your system prompt, not this setting.
    """
    from usecase.settings_store import settings_store
    s = settings_store()
    if s is None:
        return {"error": "settings store not initialized on this MCP runtime"}
    return s.describe()


# ─────────────────────────────────────────────────────────────────
# Personality — agent reads its own persona doc.
# Trigger phrases: "what's your personality?", "show your system prompt
# overlay", "are you set to concise mode?"
# ─────────────────────────────────────────────────────────────────


def personality_get() -> dict[str, Any]:
    """The agent's current persona — free-form markdown plus the action policy.

    Returns {personality, updated_at, updated_by, version}. The blob's
    `personalityMd` is the persona document rendered into your system
    prompt; `actionPolicy` is the local/external confirmation policy
    the chat route enforces. A blob saved by an older release may also
    carry keys nothing reads any more (permissionLevel, defaultModel
    (the persona's old copy; the install default is the `defaultModel`
    setting, read with settings_get), fallbackModel, maxConcurrentRuns, dailySummary, summaryTime,
    escalationThreshold, vertexCacheEnabled, autoCompactMinDropped,
    memoryMmrLambda, memoryTemporalDecayLambda); ignore them and do not
    offer to change them.

    The persona document is operator-tunable at runtime via the
    /settings/personality UI page or the Tier-2 `personality_update`
    tool. Reads are cheap (single-row SQLite lookup); the agent should
    consult this when the operator asks about its own configured
    behavior, defaults, or preferences.
    """
    from usecase.personality_store import personality_store
    s = personality_store()
    if s is None:
        return {"error": "personality store not initialized on this MCP runtime"}
    return s.get_or_default().to_dict()


# ─────────────────────────────────────────────────────────────────
# Organization — the one fictitious company every simulation uses.
# Trigger phrases: "who works in Finance?", "what is the CFO's laptop?",
# "which subnets do we have?", "simulate a login for a Sales user"
# ─────────────────────────────────────────────────────────────────


def organization_get(
    section: str | None = None,
    filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
    detail: bool = False,
    organization_id: str | None = None,
) -> dict[str, Any]:
    """Read the organization Phantom is simulating: its people, accounts, hosts, networks and cloud accounts.

    CALL THIS BEFORE you generate any log, event or scenario that names a user, host or address. Use only what it returns:
    never invent a user, a host name, an address or a domain. Every person has one primary workstation with one fixed
    address; put that login, workstation and address together in every log about the person, so the events of different
    sources (identity provider, Windows, firewall, cloud) stitch onto the same entities in Cortex.

    Args:
        section: what to read. One of "overview" (default: counts, domain, sites, warnings), "people" (login, name, title,
            department, manager, site, workstation and its IP, SID, Okta id, home egress IP, flags), "accounts" (every
            logon account with its SID, host and groups, including the adm. admin accounts, service accounts and the
            break-glass account), "hosts" (domain controllers, servers, DMZ, network, security and cloud hosts and the
            workstations, each with IP, network, role and purpose), "networks" (VLANs and address blocks), "sites",
            "groups" (with members), "personas" (the VIP targets, the outlier to attack from, contractors, leavers,
            administrators, service and break-glass accounts), "cloud" (AWS account, Azure tenant, GCP project),
            "egress" (public NAT addresses) or "cortex" (the internal ranges and domain suffix for Cortex Network
            Configuration).
        filter: narrow the rows. "department=Finance", "flag=vip", "site=JED", "role=server", "kind=admin",
            "manager=nalharbi", several joined by commas ("department=IT,site=RUH"), or a bare word matched against names,
            logins, titles and addresses ("noura", "10.20.1.").
        limit: most rows per page (1-500, default 50). A page is also capped at about 12 KB so the chat never cuts it:
            `total`, `returned`, `offset` and `truncated` say exactly what you got, and `next_offset` is where the next
            page starts. When `truncated` is true, call again with `offset=next_offset` (or add a filter) BEFORE you use
            the list: never assume rows you have not seen.
        offset: first row of the page (0-based). Use the previous result's `next_offset`.
        detail: false (default) returns the columns most tasks need (login, name, email, title, department, manager,
            site, workstation and its address, flags; for accounts the SID and host). true adds SIDs, Okta ids, home egress
            addresses, groups, cloud access and dates for people, groups for accounts, and the OS, RID and FQDN for hosts.
            Ask for it only when you need those columns.
        organization_id: read an organization other than the active one. Leave empty for the active one.

    Returns {section, total, offset, returned, truncated, next_offset?, rows} (the overview and the cloud/egress/cortex sections return their
    fields directly), or {"error": ...}.

    Example: organization_get(section="people", filter="department=Finance")
    Example: organization_get(section="personas")  # who to target, who to attack from
    Example: organization_get(section="hosts", filter="role=server")
    """
    from usecase import organization_model as om
    from usecase.organization_store import organization_store
    store = organization_store()
    if store is None:
        return {"error": "organization store not initialized on this MCP runtime"}
    rec = store.get(organization_id) if organization_id else store.get_active()
    if rec is None:
        return {"error": f"no organization {organization_id!r}" if organization_id else "no active organization"}
    try:
        out = om.section(rec.document, section, filter, limit, offset, detail)
    except om.OrganizationError as exc:
        return {"error": str(exc)}
    return {"organization": {"id": rec.id, "name": rec.name, "version": rec.version, "active": rec.active}, **out}


def organization_list() -> dict[str, Any]:
    """List the organizations Phantom has: the bundled Phantom Lab and any the operator added, and which one is active.

    Returns {organizations: [{id, name, source, active, version, people, hosts, domain}], active_id, count}. The active
    one is what every simulation uses. Trigger phrases: "which organizations do we have?", "what organization is active?".
    """
    from usecase.organization_store import organization_store
    store = organization_store()
    if store is None:
        return {"error": "organization store not initialized on this MCP runtime"}
    recs = store.list()
    return {"organizations": [r.meta() for r in recs], "active_id": next((r.id for r in recs if r.active), None),
            "count": len(recs)}


# ─────────────────────────────────────────────────────────────────
# Connector instances — XSIAM, Caldera, Xlog config blobs.
# Trigger phrases: "what's my XSIAM URL?", "show me the connector
# instances", "is Caldera configured?"
# ─────────────────────────────────────────────────────────────────


def instances_list(connector_id: str | None = None) -> dict[str, Any]:
    """List materialized connector instances. Secrets are NEVER
    returned — only secret-slot path references.

    Args:
        connector_id: optional filter — "xsiam", "caldera", "xlog".
            Null = all.

    Returns {instances: [{id, name, connector_id, config, secret_refs:
                          {slot: path}, created_at, enabled,
                          container_url}], count}.
    """
    from usecase.instance_store import instance_store
    s = instance_store()
    if s is None:
        return {"error": "instance store not initialized on this MCP runtime"}
    rows = s.list_for(connector_id) if connector_id else s.list_all()
    out = []
    for inst in rows:
        d = {
            "id": inst.id,
            "name": inst.name,
            "connector_id": inst.connector_id,
            "config": dict(inst.config),
            # Expose only the slot names + paths, never values.
            "secret_refs": dict(inst.secret_refs),
            "created_at": getattr(inst, "created_at", None),
            "enabled": getattr(inst, "enabled", True),
            "container_url": getattr(inst, "container_url", None),
        }
        out.append(d)
    return {"instances": out, "count": len(out)}


def instances_get(instance_id: str) -> dict[str, Any]:
    """Fetch one connector instance by id (UUID).

    Returns {instance: {id, name, connector_id, config, secret_refs,
                        created_at, enabled, container_url}} or {error}.
    Secrets are NEVER returned (only paths).
    """
    from usecase.instance_store import instance_store
    s = instance_store()
    if s is None:
        return {"error": "instance store not initialized on this MCP runtime"}
    inst = s.get(instance_id)
    if inst is None:
        return {"error": f"instance {instance_id!r} not found"}
    return {
        "instance": {
            "id": inst.id,
            "name": inst.name,
            "connector_id": inst.connector_id,
            "config": dict(inst.config),
            "secret_refs": dict(inst.secret_refs),
            "created_at": getattr(inst, "created_at", None),
            "enabled": getattr(inst, "enabled", True),
            "container_url": getattr(inst, "container_url", None),
        },
    }


# ─────────────────────────────────────────────────────────────────
# Providers — model providers (Vertex, Anthropic, OpenAI).
# Trigger phrases: "what models can I use?", "is Vertex configured?",
# "is Claude set up?", "list my LLM providers"
# ─────────────────────────────────────────────────────────────────


# Config values the agent may read back. Vertex's project and region say which
# Google project the install is wired to, which the agent needs to answer "is
# Vertex configured?". Every other config key (an OpenAI organization or
# project id, a gateway base URL, anything a later provider adds) is reported as
# set or not, never as its value: the agent has no use for them, and an id or an
# internal gateway host in a chat transcript is a disclosure.
_PROVIDER_CONFIG_SHOWN: dict[str, tuple[str, ...]] = {"vertex": ("project_id", "region")}


def _provider_view(p: Any) -> dict[str, Any]:
    shown = _PROVIDER_CONFIG_SHOWN.get(p.provider_id, ())
    return {
        "id": p.id,
        "name": p.name,
        "provider_id": p.provider_id,
        "config": {k: v for k, v in p.config.items() if k in shown},
        "config_set": {
            k: (v is not None and v != "")
            for k, v in p.config.items()
            if k not in shown
        },
        "secret_refs": dict(p.secret_refs),
        "created_at": getattr(p, "created_at", None),
        "updated_at": getattr(p, "updated_at", None),
    }


def providers_list(provider_id: str | None = None) -> dict[str, Any]:
    """List materialized provider instances. Secrets redacted (paths only).

    The provider ids are "vertex" (Google Gemini models, service-account JSON),
    "anthropic" (Claude models, API key) and "openai" (OpenAI models, API key).
    A provider with no instance here is not configured, and its models are not
    selectable on /models or in chat. This lists configuration only: it never
    returns a key, and which models exist is on /models (GET /api/agent/models).
    You cannot add, change or test a provider; send the operator to /providers.

    Settings other than Vertex's project_id and region are reported only as
    set or not set (config_set), never as values: an OpenAI organization or
    project id and a base URL are not shown to the agent. To tell the operator
    whether a gateway base URL is in use, say "a custom base URL is set"
    (config_set.base_url true); they can read the value on /providers.

    Args:
        provider_id: optional filter — "vertex", "anthropic" or "openai". Null = all.

    Returns {providers: [{id, name, provider_id, config (vertex: project_id,
             region; otherwise empty), config_set: {key: bool}, secret_refs,
             created_at, updated_at}], count}.
    """
    from usecase.provider_store import provider_store
    s = provider_store()
    if s is None:
        return {"error": "provider store not initialized on this MCP runtime"}
    rows = s.list_for(provider_id) if provider_id else s.list_all()
    out = [_provider_view(p) for p in rows]
    return {"providers": out, "count": len(out)}


def providers_get(provider_instance_id: str) -> dict[str, Any]:
    """Fetch one provider instance by id.

    Same shape and the same redaction as providers_list: Vertex's project_id and
    region are values; every other setting (organization, project, base URL) is
    only reported as set or not in config_set. Secrets are never returned.
    """
    from usecase.provider_store import provider_store
    s = provider_store()
    if s is None:
        return {"error": "provider store not initialized on this MCP runtime"}
    p = s.get(provider_instance_id)
    if p is None:
        return {"error": f"provider instance {provider_instance_id!r} not found"}
    return {"provider": _provider_view(p)}


# ─────────────────────────────────────────────────────────────────
# Approvals — pending + history (this matters because the agent's own
# write-tool calls land here too).
# Trigger phrases: "do I have pending approvals?", "what's waiting on
# my OK?"
# ─────────────────────────────────────────────────────────────────


def approvals_list_pending(limit: int = 50) -> dict[str, Any]:
    """List pending approval requests (not yet approved or rejected).

    Returns {approvals: [{id, tool, args, requested_at, requester_actor,
                          risk_tier}], count}.
    """
    from usecase.approvals_bus import approvals_bus
    bus = approvals_bus()
    if bus is None:
        return {"error": "approvals bus not initialized on this MCP runtime"}
    limit = max(1, min(int(limit or 50), 200))
    rows = bus.list_pending(limit=limit) if hasattr(bus, "list_pending") else []
    return {
        "approvals": [r.to_dict() if hasattr(r, "to_dict") else r for r in rows],
        "count": len(rows),
    }


def approvals_list_history(limit: int = 50) -> dict[str, Any]:
    """List recently-resolved approval requests.

    Returns {approvals: [{id, tool, args, resolved_at, decision, approver_actor}],
             count}.
    """
    from usecase.approvals_bus import approvals_bus
    bus = approvals_bus()
    if bus is None:
        return {"error": "approvals bus not initialized on this MCP runtime"}
    limit = max(1, min(int(limit or 50), 200))
    rows = bus.list_history(limit=limit) if hasattr(bus, "list_history") else []
    return {
        "approvals": [r.to_dict() if hasattr(r, "to_dict") else r for r in rows],
        "count": len(rows),
    }


# ─────────────────────────────────────────────────────────────────
# Notifications — operator inbox.
# Trigger phrases: "any notifications?", "show me unread alerts"
# ─────────────────────────────────────────────────────────────────


def notifications_list(
    unread_only: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """List notifications, newest first.

    Args:
        unread_only: when true, hide already-read notifications.
        limit: max rows (1-500). Default 50.

    Returns {notifications: [...], count}.
    """
    from usecase.notifications import notification_store
    s = notification_store()
    if s is None:
        return {"error": "notification store not initialized on this MCP runtime"}
    limit = max(1, min(int(limit or 50), 500))
    if hasattr(s, "list"):
        rows = s.list(unread_only=bool(unread_only), limit=limit)
    elif hasattr(s, "list_notifications"):
        rows = s.list_notifications(unread_only=bool(unread_only), limit=limit)
    else:
        return {"error": "notification store has no list method"}
    return {
        "notifications": [n.to_dict() if hasattr(n, "to_dict") else n for n in rows],
        "count": len(rows),
    }


def notifications_unread_count() -> dict[str, Any]:
    """How many unread notifications are waiting?

    Returns {unread: N}.
    """
    from usecase.notifications import notification_store
    s = notification_store()
    if s is None:
        return {"error": "notification store not initialized on this MCP runtime"}
    if hasattr(s, "unread_count"):
        n = s.unread_count()
    else:
        # Fallback: count via list().
        rows = s.list(unread_only=True, limit=10000) if hasattr(s, "list") else []
        n = len(rows)
    return {"unread": n}


# ─────────────────────────────────────────────────────────────────
# Audit log — forensic queries on the agent's own behavior.
# Trigger phrases: "show me the last 20 tool calls", "what did the
# agent do at 3pm?", "audit search 'caldera'"
# ─────────────────────────────────────────────────────────────────


def audit_search(
    q: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    target_prefix: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Search the audit log.

    Args:
        q: free-text match against action/target/metadata. Applied
            client-side after the indexed filters because SqliteAuditLog
            doesn't have a full-text index. Slower than the other
            params; use action/actor/target_prefix when you can.
        action: exact action filter (e.g. "tool_call", "job_fired").
        actor: exact actor filter (e.g. "operator", "scheduler").
        target_prefix: target prefix filter (e.g. "memory:", "kb:phantom-soc:").
        limit: max rows (1-500). Default 50.

    Returns {events: [...], count}.
    """
    from usecase.audit_log import audit_log
    log = audit_log()
    if log is None:
        return {"error": "audit log not initialized on this MCP runtime"}
    limit = max(1, min(int(limit or 50), 500))
    # SqliteAuditLog has no `search()` method (the read method is
    # `query()`) and no free-text `query=...` param, so:
    #   1) Use `log.query(...)` with the parameter names it actually
    #      accepts (action, actor, target_prefix, limit).
    #   2) Honor the `q` free-text param by post-filtering
    #      client-side — SqliteAuditLog has no FTS. Applied AFTER the
    #      indexed filters narrow the result set, so this stays
    #      tractable in practice.
    #   3) query() returns list[dict] directly via _row_to_dict, so no
    #      `r.to_dict()` conversion is needed.
    rows = log.query(
        action=action or None,
        actor=actor or None,
        target_prefix=target_prefix or None,
        # Overfetch when q is set so post-filtering still has enough
        # to satisfy the caller's `limit` after dropping non-matches.
        limit=(limit * 4 if q else limit),
    )
    if q:
        needle = q.lower()
        rows = [
            r for r in rows
            if needle in (r.get("action") or "").lower()
            or needle in (r.get("target") or "").lower()
            or needle in (r.get("metadata_json") or "").lower()
        ]
        rows = rows[:limit]
    return {
        "events": rows,
        "count": len(rows),
    }


def audit_recent(limit: int = 20) -> dict[str, Any]:
    """Most recent N audit events (cheaper shortcut for the dashboard view).

    Returns {events: [...], count}.
    """
    from usecase.audit_log import audit_log
    log = audit_log()
    if log is None:
        return {"error": "audit log not initialized on this MCP runtime"}
    limit = max(1, min(int(limit or 20), 200))
    # SqliteAuditLog has one implementation with one read method,
    # `query()`, which already returns list[dict] via _row_to_dict — no
    # hasattr fallbacks or `r.to_dict()` conversion are needed.
    rows = log.query(limit=limit)
    return {
        "events": rows,
        "count": len(rows),
    }


# ─────────────────────────────────────────────────────────────────
# API keys — IDs + scopes + last_used. NEVER the secret value.
# Trigger phrases: "what api keys are issued?", "show me my tokens"
# ─────────────────────────────────────────────────────────────────


def api_keys_list() -> dict[str, Any]:
    """List minted API keys. Returns metadata only — the secret value
    is unrecoverable post-mint by design.

    Returns {api_keys: [{id, label, scopes, created_at, last_used_at,
                          revoked}], count}.
    """
    from usecase.api_keys import api_key_store
    s = api_key_store()
    if s is None:
        return {"error": "api key store not initialized on this MCP runtime"}
    rows = s.list() if hasattr(s, "list") else s.list_all()
    out = []
    for k in rows:
        d = k.to_dict() if hasattr(k, "to_dict") else dict(k)
        # Defense-in-depth: scrub anything that looks like a value.
        d.pop("token", None)
        d.pop("secret", None)
        d.pop("hash", None)
        out.append(d)
    return {"api_keys": out, "count": len(out)}


# ─────────────────────────────────────────────────────────────────
# Manifest — the bundle's static config blob. Read-only at runtime
# by spec; agent introspects to know its own capabilities.
# Trigger phrases: "what tools are allowed?", "show the manifest"
# ─────────────────────────────────────────────────────────────────


def manifest_get(section: str | None = None) -> dict[str, Any]:
    """Read the bundle's manifest.yaml. Read-only by spec — runtime
    can never mutate the bundle. Useful for the agent to introspect
    its own contract: which tools are allowed, which require approval,
    which secrets are bound, etc.

    Args:
        section: optional top-level key filter ("tools", "approvals",
            "knowledge", etc.). Null = full manifest.

    Returns {manifest: {...}} or {section: ..., value: {...}}.
    """
    bundle_root = Path(os.getenv("BUNDLE_ROOT", "/app/bundle"))
    manifest_path = bundle_root / "manifest.yaml"
    if not manifest_path.is_file():
        return {"error": f"manifest not found at {manifest_path}"}
    try:
        import yaml  # already a dep via fastmcp
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"failed to parse manifest: {exc}"}
    if not isinstance(data, dict):
        return {"error": "manifest is not a YAML mapping"}
    if section:
        if section not in data:
            return {"section": section, "value": None}
        return {"section": section, "value": data[section]}
    return {"manifest": data}


# ─────────────────────────────────────────────────────────────────
# Metrics — agent self-diagnoses health.
# Trigger phrases: "are you healthy?", "what's your error rate?",
# "show me the embedder stats"
# ─────────────────────────────────────────────────────────────────


def metrics_snapshot(name_prefix: str | None = None) -> dict[str, Any]:
    """Snapshot of all named metrics + their current values. Mirrors
    /api/v1/metrics/snapshot but returns parsed values, not just kinds.

    Args:
        name_prefix: optional filter (e.g. "phantom_embedder_" returns
            just embedder stats).

    Returns {metrics: {name: {kind, values}}, count}.
    """
    from usecase.metrics_registry import metrics_registry
    reg = metrics_registry()
    if reg is None:
        return {"error": "metrics registry not initialized on this MCP runtime"}
    out: dict[str, Any] = {}
    for name in reg.names():
        if name_prefix and not name.startswith(name_prefix):
            continue
        m = reg.get(name)
        if m is None:
            continue
        kind = type(m).__name__.lower()
        # Best-effort value extraction across Counter / Gauge / Histogram.
        values: Any = None
        if hasattr(m, "_values"):
            with getattr(m, "_lock", _NoopLock()):
                # Convert tuple keys (sorted (k,v) pairs) to dict for JSON.
                values = {
                    "" if not k else _format_key(k): v
                    for k, v in m._values.items()
                }
        elif hasattr(m, "_data"):
            values = "histogram (use /api/v1/metrics for buckets)"
        out[name] = {"kind": kind, "values": values}
    return {"metrics": out, "count": len(out)}


class _NoopLock:
    """Context-manager no-op for metrics that don't expose their lock."""
    def __enter__(self) -> None:
        return None
    def __exit__(self, *args: Any) -> None:
        return None


def _format_key(key: tuple[tuple[str, str], ...]) -> str:
    if not key:
        return ""
    return ",".join(f"{k}={v}" for k, v in key)


# ─────────────────────────────────────────────────────────────────
# Health status — agent self-diagnoses ops state.
# Trigger phrases: "are you healthy?", "is everything OK?"
# ─────────────────────────────────────────────────────────────────


def health_status() -> dict[str, Any]:
    """Combined health snapshot: embedder mode, metric registry size,
    pending approvals count, recent error count.

    Returns {ok: bool, embedder_mode, pending_approvals, errors_5min, ...}.

    Reads embedder_mode from the live EmbedderRuntime, which is re-decided
    whenever a Vertex provider is saved on /providers, so it never lags the
    stored configuration. Falls back to the PHANTOM_EMBEDDER_MODE env var only
    when no runtime is wired (unit tests, a docker-exec shell).

    Embeddings (memory and knowledge-base search) are Vertex-only. On an
    install that has no Vertex provider (chat on Claude or OpenAI alone) the
    embedder is in stub mode, which returns hash-similarity scores instead of
    semantic matches. That is reported in `embedder_warning` and
    `embedder_mode: "stub"` but does NOT make `ok` false: `ok` is false only
    for a fault, such as a configured Vertex embedder that cannot start. When
    you relay this, say that memory and knowledge search are not semantic on
    this install and that chat is unaffected; do not call the install unhealthy.
    """
    out: dict[str, Any] = {"ok": True}

    try:
        from usecase.embedder_runtime import embedder_runtime
        rt = embedder_runtime()
    except Exception:
        rt = None
    if rt is not None:
        out["embedder_mode"] = rt.mode
        out["embedder_model"] = rt.embedder_model_id
        warning = rt.warning()
    else:
        out["embedder_mode"] = os.environ.get("PHANTOM_EMBEDDER_MODE", "unknown")
        warning = (
            None if out["embedder_mode"] == "vertex"
            else "Embedder mode could not be read from the running server."
        )
    if warning:
        out["embedder_warning"] = warning
        # Only a fault turns `ok` off. No Vertex provider is a normal state on
        # a Claude-only or OpenAI-only install.
        if rt is None or rt.is_fault():
            out["ok"] = False

    # Cross-model embedding mismatches — rows in memory.db whose
    # stored vector was produced by a DIFFERENT embedder than the one
    # live now (most commonly: written by the TextHash stub before
    # Vertex creds were submitted, never re-embedded after the
    # switch). embedder_mode alone can't surface this: TextHash and
    # Vertex are both 768-dim, so a stale row doesn't fail any
    # existing check, it just silently degrades that row's search
    # ranking. A nonzero count here means "re-store the affected
    # memories (or wait for them to be naturally re-stored) to get
    # them back onto the live embedder."
    try:
        from usecase.memory_store import memory_store as _memory_store_singleton
        from usecase.kb_store import knowledge_base as _kb_singleton
        mem_store = _memory_store_singleton()
        kb = _kb_singleton()
        total = (mem_store.embedding_model_mismatches if mem_store else 0) + (
            kb.embedding_model_mismatches if kb else 0
        )
        out["embedding_model_mismatches"] = total
        if mem_store is not None:
            out["embedding_model_mismatches_memory"] = mem_store.embedding_model_mismatches
        if kb is not None:
            out["embedding_model_mismatches_kb"] = kb.embedding_model_mismatches
    except Exception:
        pass

    # Approvals pending
    try:
        from usecase.approvals_bus import approvals_bus
        bus = approvals_bus()
        if bus is not None and hasattr(bus, "list_pending"):
            out["pending_approvals"] = len(bus.list_pending(limit=1000))
    except Exception:
        pass

    # Recent error count (audit log)
    try:
        from usecase.audit_log import audit_log
        log = audit_log()
        if log is not None:
            # SqliteAuditLog has no .search() method, so a hasattr-guarded
            # search() call would always fall through to [] and
            # metrics_health would silently report `errors_recent=0`
            # regardless of actual error volume. query() returns
            # list[dict] directly.
            recent = log.query(limit=200)
            out["errors_recent"] = sum(
                1 for r in recent if r.get("status") == "failure"
            )
    except Exception:
        pass

    # Vertex embedder error count (mirrors /metrics)
    try:
        from usecase.vertex_embedder import get_embedder
        e = get_embedder()
        if e is not None:
            stats = e.stats()
            out["embedder_errors_total"] = stats.get("error_count", 0)
            out["embedder_upstream_calls_total"] = stats.get("upstream_calls", 0)
            out["embedder_cache_hits"] = stats.get("cache_hits", 0)
    except Exception:
        pass

    return out


# ═════════════════════════════════════════════════════════════════
# TIER 2 — soft-write tools
#
# These mutate runtime state (jobs, settings, personality, notifications)
# and gate via manifest.approvals.humanRequired[]. Each one wraps the
# underlying mutation in `gate_and_execute()` from `_approval_gate`,
# which dispatches through the InProcessApprovalsBus and surfaces a
# pending row in /approvals for operator confirmation.
#
# Trigger phrases the agent recognizes:
#   "schedule a daily SOC report at 8am"     → jobs_create
#   "pause the daily-soc-coverage job"        → jobs_update(enabled=False)
#   "run the coverage report now"             → jobs_run_now
#   "always reply in three bullet points"     → personality_update
#   "change my default scenario to ransomware"→ settings_update
#   "dismiss notification N"                  → notifications_dismiss
#   "approve approval ABC"                    → approvals_resolve
# ═════════════════════════════════════════════════════════════════


# ─── Jobs (3 tools) ─────────────────────────────────────────────


async def jobs_create(
    name: str,
    cron: str,
    action: dict[str, Any],
    timezone: str = "UTC",
    enabled: bool = True,
    run_once: bool = False,
    bypass_approvals: bool = False,
    model_id: str | None = None,
    thinking_enabled: bool = False,
    permission_policy: dict[str, Any] | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Schedule a new runtime job. Waits for approval when the install gates it.

    Args:
        name: unique identifier (filesystem-safe; no slashes, dots).
        cron: 5-field expression (POSIX cron).
        action: discriminated by `type` — one of:

            type="chat" — fire a chat turn against this agent:
              {"type": "chat",
               "message": "...",
               "skill"?: "<canonical_skill_name>",
               "session_id"?: "..."}

              `skill` (optional) pins which skill the chat turn loads
              into its system prompt. The scheduler injects the
              skill's MD content into the dispatched turn as
              <skill name="..."> ... </skill>, so the agent enters the
              conversation with that skill already in context. Set
              this when the operator's request names a specific
              skill — e.g. "run the bruteforce_vpn_to_lateral skill
              every morning", "schedule a daily port-scan-detection
              simulation". When omitted, the agent picks a skill at
              runtime based on the message content (good for open-
              ended prompts like "summarize last night's alerts").

            type="tool_call" — invoke an MCP tool with args:
              {"type": "tool_call", "name": "<tool_name>",
               "args": { ...tool_request_body... }}

              For scheduled or one-shot log generation, wrap the real
              log-generation tool this way — there is no first-class
              `type="log"` action (job actions are only
              {prompt, tool_call}). Example,
              generating CEF logs to a syslog destination once:
              {"type": "tool_call", "name": "xlog.create_data_worker",
               "args": {"type": "CEF", "destination": "logdest:<id>",
                         "count": 5, "vendor": "...", "product": "...",
                         "observables_dict": {...},
                         "required_fields": [...]}}
              `name` here is the FULL registered tool name (connector-
              namespaced, e.g. `xlog.create_data_worker` — see
              `tools/list` or the connector's own docstring for the
              exact args shape). A bare `phantom_create_data_worker` is
              NOT a valid tool name on its own; use the namespaced form.

        timezone: IANA TZ name. Default UTC.
        enabled: schedule starts active. Default true.
        run_once: auto-disable after first fire. Default false.
        bypass_approvals: when true, the job runs without firing the
            approval gate for any destructive tool it calls
            (e.g. skills_delete, settings_reset). Default false — the
            safe default; every destructive tool needs operator
            confirmation. Set true ONLY when the operator explicitly
            says they trust the job to run unattended — concrete
            trigger phrases: "don't ask me each time", "auto-approve
            this job", "run unattended", "set it and forget it".
            The audit log records every bypass-fired tool with
            `auto_approved=true` and `bypass_source=job:<name>` so
            post-hoc review still surfaces what ran. Off by default
            because once a job is bypassed it can do destructive work
            at 3am without the operator looking — match the operator's
            stated intent, don't infer it.
        model_id: per-job model override, a canonical model ref
            "provider/model" (for example "vertex/gemini-3.7-flash",
            "anthropic/claude-haiku-5-5" or "openai/gpt-6-luna"; the
            provider ids are vertex, anthropic and openai).
            When set, the job's chat dispatches send `body.model =
            <ref>` and the chat route runs the job on exactly that
            model; omit it and the job runs on the install's default
            model (set by the operator on /models). Use cheap models
            for high-volume / triage workloads and reserve the default
            for tasks where quality matters. Concrete trigger phrases:
            "run this job on flash", "use gemini-pro for the nightly
            summary", "run this on Claude", "run this on the cheap
            model". The refs the
            install accepts are listed by GET /api/agent/models (the
            /models page); this tool does not check the value, but a
            ref that is unknown, retired or whose provider is not
            configured makes every dispatch FAIL with MODEL_UNAVAILABLE
            (the run is marked failed and the job-run-failed
            notification fires). Nothing is ever substituted. A bare id
            such as "gemini-3.7-flash" still resolves when exactly one
            configured provider offers it, but always write the
            canonical ref. Omit (default None) to use the install
            default.
        thinking_enabled: extended-thinking toggle.
            When true, the job's dispatch carries `body.thinking
            = true` so the model uses its extended-reasoning path
            (each provider maps it to its own reasoning mode: Gemini
            thinking, Claude thinking, OpenAI reasoning; a model with no
            thinking mode silently ignores it). Set when the operator says
            "use deep thinking", "give it more reasoning room",
            "extended thinking for this job". Default false.
        permission_policy: per-job tool allowlist.
            Declarative policy enforced by the chat-route's
            tool-dispatch loop: before each tool fires, the loop
            evaluates the policy and may short-circuit with a deny
            (the model sees a tool-error result, the chat thread
            surfaces the denial reason). Shape:
                {
                  "allowed_tools": ["pattern", ...],
                  "denied_tools": ["pattern", ...]
                }
            Patterns are globs (same as HookMatcher.toolGlob: `*`, `?`,
            comma-separated lists). Set when the operator scopes the
            job — concrete trigger phrases: "only let this job touch
            xlog tools", "don't let this job call any caldera tools".
            There is no per-job approval list: whether a call needs an
            approval card follows the install's approval list, so do
            not offer to "approve" tools per job. Omit / pass None
            to leave the policy unrestricted (the runtime default).
            Example: `{"allowed_tools": ["phantom_*", "xlog.*"], "denied_tools":
            ["*_delete"]}` restricts the job to xlog tools AND blocks
            destructive deletes within that family. Evaluation order:
            denied beats allowed beats default-allow.
        description: a short free-text note on what the job is for
            (up to 2000 characters). It is the same text as the
            Description field on the /jobs/new form: shown under the
            schedule on the /jobs list and under the title on the job's
            page, and copied by Duplicate. Set it whenever the operator
            says why the job exists or what it watches — concrete
            trigger phrases: "describe it as ...", "note that this is
            for the Okta demo", "label it 'weekly coverage digest'".
            Omit it (default) when they gave no purpose; do not invent
            one. Plain text, no secrets.

    Returns the persisted job row on success.

    Trigger phrases: "schedule a daily X at Y", "create a cron job
    that does Z every Monday morning", "send N <vendor> logs once now".

    Idempotency discipline: BEFORE creating a job, call
    `jobs_list()` and check whether a job with the same intent already
    exists. The agent tends to duplicate jobs when the
    operator phrases the request slightly differently across turns
    ("schedule a malicious-email skill every 15 minutes" → creates
    `skill-malicious-email-15min`; then "create an email-malware job
    every 15 minutes" → creates `email-malware-15min` instead of
    recognizing it's the same scheduled work). When a likely duplicate
    is detected, prefer `jobs_update()` to modify the existing job
    over creating a near-duplicate. Distinguish "same intent" via the
    triple (cron expression, action.type, action.skill OR
    action.message gist) — exact name match is too narrow, exact
    payload match is too wide.
    """
    from usecase.builtin_components._approval_gate import gate_and_execute
    from usecase.job_scheduler import scheduler
    s = scheduler()
    if s is None:
        return {"error": "scheduler not initialized on this MCP runtime"}

    def _exec() -> dict[str, Any]:
        row = s.add_job(
            name=name, cron=cron, timezone_name=timezone,
            action=action, enabled=enabled, run_once=run_once,
            bypass_approvals=bypass_approvals,
            model_id=model_id,
            thinking_enabled=thinking_enabled,
            permission_policy=permission_policy,
            description=description,
        )
        return {"job": row.to_dict() if hasattr(row, "to_dict") else None}

    try:
        return await gate_and_execute(
            tool_name="jobs_create",
            args={
                "name": name, "cron": cron, "action": action,
                "timezone": timezone, "enabled": enabled, "run_once": run_once,
                "bypass_approvals": bypass_approvals,
                "model_id": model_id,
                "thinking_enabled": thinking_enabled,
                "permission_policy": permission_policy,
                "description": description,
            },
            risk_tier="soft",
            executor=_exec,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "tool": "jobs_create"}


async def jobs_update(
    name: str,
    cron: str | None = None,
    timezone: str | None = None,
    action: dict[str, Any] | None = None,
    enabled: bool | None = None,
    bypass_approvals: bool | None = None,
    model_id: str | None = None,
    thinking_enabled: bool | None = None,
    permission_policy: dict[str, Any] | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Modify an existing runtime job. Waits for approval when the install gates it.

    Only fields supplied as non-None get patched; everything else
    stays. To pause a job, call with `enabled=False`. To change the
    cadence, pass `cron`. Manifest jobs (source='manifest') ignore
    most updates and revert at next boot — see job_scheduler docs.

    Args:
        name: the job's canonical name (required for the patch lookup).
        cron: 5-field POSIX cron expression. Pass to change the cadence;
            omit to keep the current schedule.
        timezone: IANA TZ name. Omit to keep current.
        action: discriminated-union job action — same shape as
            jobs_create's action arg (type=chat / tool_call). See
            jobs_create's docstring for the full action shape,
            including the `skill` field on the chat action and how
            to wrap log generation as a tool_call action.
        enabled: false to pause the cron, true to resume. Omit to
            keep current state.
        bypass_approvals: toggle the per-job auto-approval flag.
            When true, every dispatch for this job carries
            `X-Phantom-Approval-Bypass: 1` so the MCP-side
            gate skips the operator-confirmation dance for tools in
            manifest.approvals.humanRequired[]. Audit rows still
            record each fired tool with `auto_approved=true` and
            `bypass_source=job:<name>` so post-hoc review surfaces
            what ran unattended. Set ONLY when the operator
            explicitly asks ("auto-approve from now on", "stop
            asking me each time", "run unattended"). Omit to keep
            current value.
        model_id: per-job model override.
            Sentinel semantics: omit / None to preserve the current
            override; empty string "" to CLEAR the override (revert
            to the install's default model); any other string to set
            to that model ref. Example payloads:
            `{"model_id": "vertex/gemini-3.7-flash"}` to switch to
            flash; `{"model_id": ""}` to clear; omitting the field
            entirely leaves the existing value untouched. Always a
            canonical "provider/model" ref. See jobs_create for the
            full discussion of when to set it and what happens when
            the model is unavailable.
        thinking_enabled: toggle extended thinking on/off for this
            job's dispatches. Tri-state — omit to keep
            current, true / false to set. See jobs_create's docstring
            for details.
        permission_policy: per-job tool allowlist.
            Sentinel semantics: omit / None to preserve the existing
            policy; `{}` (empty dict) to clear the policy (revert to
            no restrictions); non-empty dict to set. See jobs_create
            for the full policy shape + glob syntax discussion.
        description: the job's free-text note (what it is for).
            Sentinel semantics: omit / None to preserve the current
            note; empty string "" to CLEAR it; any other text (up to
            2000 characters) to set it. Concrete trigger phrases:
            "rename the description to ...", "add a note that this
            job feeds the demo", "remove the description". See
            jobs_create for where it is shown.

    Returns the updated job row on success.
    """
    from usecase.builtin_components._approval_gate import gate_and_execute
    from usecase.job_scheduler import scheduler
    s = scheduler()
    if s is None:
        return {"error": "scheduler not initialized on this MCP runtime"}

    def _exec() -> dict[str, Any]:
        row = s.update_job(
            name,
            cron=cron, timezone_name=timezone,
            action=action, enabled=enabled,
            bypass_approvals=bypass_approvals,
            model_id=model_id,
            thinking_enabled=thinking_enabled,
            permission_policy=permission_policy,
            description=description,
        )
        return {"job": row.to_dict() if hasattr(row, "to_dict") else None}

    try:
        return await gate_and_execute(
            tool_name="jobs_update",
            args={
                k: v for k, v in {
                    "name": name, "cron": cron, "timezone": timezone,
                    "action": action, "enabled": enabled,
                    "bypass_approvals": bypass_approvals,
                    "model_id": model_id,
                    "thinking_enabled": thinking_enabled,
                    "permission_policy": permission_policy,
                    "description": description,
                }.items() if v is not None
            },
            risk_tier="soft",
            executor=_exec,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "tool": "jobs_update"}


async def jobs_run_now(name: str) -> dict[str, Any]:
    """Trigger a job immediately, outside its cron schedule.
    Waits for approval when the install gates it.

    Useful for "run the coverage report now" or "test that the
    nightly summary still works." The job's regular schedule is
    unaffected — the next regular fire still happens.

    Returns {run: {...}} with the run record on success.
    """
    from usecase.builtin_components._approval_gate import gate_and_execute
    from usecase.job_scheduler import scheduler
    s = scheduler()
    if s is None:
        return {"error": "scheduler not initialized on this MCP runtime"}

    async def _exec() -> dict[str, Any]:
        run = await s.trigger_now(name)
        return {"run": run.to_dict() if hasattr(run, "to_dict") else None}

    try:
        return await gate_and_execute(
            tool_name="jobs_run_now",
            args={"name": name},
            risk_tier="soft",
            executor=_exec,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "tool": "jobs_run_now"}


# ─── Personality (1 tool) ───────────────────────────────────────


async def personality_update(blob: dict[str, Any]) -> dict[str, Any]:
    """Replace the agent's persona document. Waits for approval when the install gates it.

    The approval row carries the full proposed blob; the operator's
    UI renders a diff against the current version so they
    see exactly what's changing before approving.

    Args:
        blob: the full new personality. MUST be a dict matching the
            shape returned by `personality_get` — agent should fetch
            current, modify, then update with the full new object
            (read-modify-write). Unknown keys are accepted and stored,
            but only `personalityMd` and `actionPolicy` have any effect.

    Returns {personality, updated_at, updated_by, version}.

    Trigger phrases: "always answer in three bullet points",
    "be more concise", "update the personality so you cite
    simulation IDs more aggressively". Tone and working style go in
    `personalityMd` as markdown; there are no tone, proactivity,
    model or permission fields to set.
    """
    from usecase.builtin_components._approval_gate import gate_and_execute
    from usecase.personality_store import personality_store
    s = personality_store()
    if s is None:
        return {"error": "personality store not initialized on this MCP runtime"}
    if not isinstance(blob, dict):
        return {"error": "blob must be a JSON object"}

    def _exec() -> dict[str, Any]:
        updated = s.put(blob, actor="agent")
        return updated.to_dict()

    try:
        return await gate_and_execute(
            tool_name="personality_update",
            args={"blob_keys": sorted(blob.keys())},  # full blob would
            # bloat the approval row; keys alone tell the operator
            # what's changing; the diff is computed at render time.
            risk_tier="soft",
            executor=_exec,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "tool": "personality_update"}


async def personality_patch(updates: dict[str, Any]) -> dict[str, Any]:
    """Atomic merge update for the agent's persona. Waits for approval when the install gates it.

    Like `personality_update` but does the read-modify-write inside
    one call: fetches the current blob, shallow-merges `updates` over
    it, and writes the result. The agent doesn't have to remember to
    fetch first — calling

        personality_patch({"personalityMd": "...new markdown..."})

    is safe and won't wipe the other field (actionPolicy) the way a
    naive `personality_update({"personalityMd": "..."})` would.

    Args:
        updates: keys to set/replace. A shallow merge — top-level keys
            in `updates` overwrite the current blob's same-named keys;
            unspecified keys pass through unchanged.

    Returns {personality, updated_at, updated_by, version}.

    Approval gate: this tool requests approval under the same
    `personality_update` name (manifest's humanRequired list keys on
    bare names, and patch is semantically the same operation as
    update — different ergonomics, identical risk surface). The
    approval row's `args.blob_keys` lists ONLY the keys being
    patched, so operators see "agent wants to change `personalityMd`"
    instead of the noisier full-blob keylist.

    Trigger phrases: "be more concise", "update your personality.md
    to add a guideline about citing simulation IDs", "soften your
    tone".
    """
    from usecase.builtin_components._approval_gate import gate_and_execute
    from usecase.personality_store import personality_store
    s = personality_store()
    if s is None:
        return {"error": "personality store not initialized on this MCP runtime"}
    if not isinstance(updates, dict):
        return {"error": "updates must be a JSON object"}
    if not updates:
        return {"error": "updates must be non-empty"}

    def _apply() -> dict[str, Any]:
        current = s.get_or_default().blob
        merged = {**current, **updates}
        updated = s.put(merged, actor="agent")
        return updated.to_dict()

    try:
        return await gate_and_execute(
            # Use the actual tool name for the gate. The chat-side
            # `isToolGated()` check keys on the agent-facing tool name
            # (the one Gemini sees + dispatches), not the gate's
            # internal name; aliasing to "personality_update" would make
            # isToolGated("personality_patch") return false → no inline
            # approval card → silent 5-min hang. `personality_patch`
            # has its own humanRequired entry in manifest.yaml, so the
            # approval row + audit trail correctly distinguish patches
            # from full-replace updates (operators can see "agent
            # wants to patch personalityMd" instead of the noisier
            # "agent wants to update personality").
            tool_name="personality_patch",
            args={"blob_keys": sorted(updates.keys()), "patch": True},
            risk_tier="soft",
            executor=_apply,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "tool": "personality_patch"}


# ─── Organization (2 tools) ─────────────────────────────────────


async def organization_update(
    changes: dict[str, Any],
    note: str | None = None,
    organization_id: str | None = None,
) -> dict[str, Any]:
    """Change the organization: add or edit people, hosts, networks and groups, or remove them. Waits for approval when the install gates it.

    The change is validated as a whole and applied only if the organization stays consistent (every host address inside
    its network, every manager and workstation existing, no duplicate login, host name or address). A rejected change
    changes nothing and the error lists every problem. Every accepted change is kept in the organization's history, so
    the operator can undo it. The bundled Phantom Lab is read-only: changing it makes an editable copy
    (`phantom-lab-custom`), which becomes the active organization when Phantom Lab was; the result says so.

    Args:
        changes: an object with any of
            "upsert": {"people": [...], "hosts": [...], "networks": [...], "sites": [...], "groups": [...],
                       "service_accounts": [...]}  - add an entry, or merge fields into the entry with the same login
                       (people, service_accounts), name (hosts, groups) or id (networks, sites); null deletes a field.
            "remove": {"people": ["login", ...], "hosts": ["name", ...], ...}  - delete by login, name or id.
            "set":    {"description": "...", "locale": {"timezone": "Asia/Dubai"}, "cortex": {...}, "egress": {...},
                       "cloud": {...}, "domain": {...}, "name": "..."}  - deep-merge a scalar section.
            A NEW PERSON needs only given_name, family_name, title and department (add "site" for Jeddah or Remote).
            Their login (first initial + family name), email, workstation (a new PHWS-nnn host with the next free
            address in the site's block), SID, Okta id, groups and manager are filled in, and `notes` says what was added.
        note: a short reason, kept in the history ("onboarding: two Finance hires").
        organization_id: edit an organization other than the active one. Leave empty for the active one.

    Returns {organization: {id, name, version, active}, notes, forked_from} or {"error": ..., "errors": [...]}.

    Trigger phrases: "add a new hire to Finance with a laptop", "add a server for the new HR system", "remove the
    leaver", "add a /24 for the lab VLAN".

    Example: organization_update({"upsert": {"people": [{"given_name": "Amira", "family_name": "Alfarsi",
                                  "title": "Financial Analyst", "department": "Finance"}]}}, note="new hire")
    Example: organization_update({"remove": {"hosts": ["PHSRV-BKP01"]}})
    """
    from usecase import organization_model as om
    from usecase.builtin_components._approval_gate import gate_and_execute
    from usecase.organization_store import OrganizationStoreError, organization_store
    store = organization_store()
    if store is None:
        return {"error": "organization store not initialized on this MCP runtime"}
    if not isinstance(changes, dict) or not changes:
        return {"error": "changes must be a non-empty JSON object with upsert, remove and/or set"}
    target = organization_id or (store.get_active().id if store.get_active() else None)
    if target is None:
        return {"error": "no active organization"}

    def _apply() -> dict[str, Any]:
        try:
            rec, notes, forked_from = store.apply_changes(target, changes, actor="agent", note=note)
        except om.OrganizationError as exc:
            return {"error": str(exc), "errors": exc.errors}
        except OrganizationStoreError as exc:
            return {"error": str(exc)}
        return {"organization": {"id": rec.id, "name": rec.name, "version": rec.version, "active": rec.active},
                "notes": notes, "forked_from": forked_from}

    try:
        return await gate_and_execute(
            tool_name="organization_update",
            args={"organization": target, "collections": sorted({*(changes.get("upsert") or {}),
                                                                 *(changes.get("remove") or {}),
                                                                 *(changes.get("set") or {})})},
            risk_tier="soft",
            executor=_apply,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "tool": "organization_update"}


async def organization_activate(organization_id: str) -> dict[str, Any]:
    """Make an organization the active one, the company every simulation uses from now on. Waits for approval when the install gates it.

    Nothing is removed by switching: the previous organization stays, and so do the users and assets it already created
    in Cortex. Connector containers pick the change up on their next call. Use organization_list to see the ids.

    Args:
        organization_id: the id to activate, for example "phantom-lab".

    Returns {organization: {id, name, version, active}} or {"error": ...}.
    Trigger phrases: "switch to the Acme organization", "go back to Phantom Lab".
    """
    from usecase.builtin_components._approval_gate import gate_and_execute
    from usecase.organization_store import OrganizationStoreError, organization_store
    store = organization_store()
    if store is None:
        return {"error": "organization store not initialized on this MCP runtime"}

    def _apply() -> dict[str, Any]:
        try:
            rec = store.activate(organization_id, actor="agent")
        except OrganizationStoreError as exc:
            return {"error": str(exc)}
        return {"organization": {"id": rec.id, "name": rec.name, "version": rec.version, "active": rec.active}}

    try:
        return await gate_and_execute(
            tool_name="organization_activate",
            args={"organization": organization_id},
            risk_tier="soft",
            executor=_apply,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "tool": "organization_activate"}


# ─── Settings (1 tool) ──────────────────────────────────────────


def _protected_setting_rejection(key: str) -> dict[str, Any]:
    """`rejected[]` entry for a model-selection key the agent may not write."""
    return {
        "key": key,
        "reason": (
            f"'{key}' selects the model and is operator-only: the agent cannot "
            "change or clear it. The operator sets the default model outside "
            "chat (Set as default on /models, or the settings REST API); a chat session's model is a per-session "
            "preference (/model <name>) and never a global setting."
        ),
    }


async def settings_update(
    updates: dict[str, Any] | None = None,
    clear: list[str] | None = None,
) -> dict[str, Any]:
    """Set or clear runtime settings overrides. Waits for approval when the install gates it (soft).

    Only keys in manifest.settings.overridable[] can be modified; others
    are returned in `rejected[]` rather than mutating anything. The
    current allow-list (Spark bundle) is:

        - defaultLogDestination             (default webhook/sink address)
        - setupUiUser                       (operator's display name)
        - defaultLogFormat                  (e.g. "cef", "leef", "syslog")
        - defaultScenario                   (default scenario file stem)
        - requireHumanApprovalForOperations (bool — toggles bundle-wide
                                             approval gate)
        - coverageReportFormat              (e.g. "markdown", "json")

    Anything else (random env names, secrets, MCP internals) is silently
    rejected — connector credentials and provider credentials are set by
    the operator on the Instances and Providers pages, not by the agent.

    MODEL SELECTION IS NOT WRITABLE HERE. `defaultModel`, the install's
    default model (a canonical "provider/model" ref such as
    "vertex/gemini-3.1-pro-preview"), and any other key whose name ends
    in "model" is operator-only: the operator sets the default with the
    "Set as default" action on /models (or the settings REST API,
    PUT /api/agent/settings, which checks the ref against the model
    registry). You can READ it with settings_get. A call
    naming such a key is refused with a `rejected[]` entry and changes
    nothing. A chat session's model is a per-session preference (header
    dropdown, or the operator's `/model <name>` command) and is NOT a
    global setting: never call this tool to record, confirm or "sync"
    the session's model, and never call it to answer a question such as
    "what model are you?" (the system prompt states the model in use).

    Args:
        updates: {key: value} pairs to set. Values must JSON-serialize.
            Model-selection keys are rejected.
        clear:   keys to revert to manifest defaults (omit/null = no clear).
            Model-selection keys are rejected.

    Returns {applied, cleared, rejected}. There is no bypass_approvals
    knob on this tool; if the session's approval mode is "manual" the
    operator approves once in the UI. If "bypass", the call still goes
    through but the operator sees it in the audit log.
    """
    from usecase.builtin_components._approval_gate import gate_and_execute
    from usecase.settings_store import settings_store
    s = settings_store()
    if s is None:
        return {"error": "settings store not initialized on this MCP runtime"}
    updates = updates or {}
    clear = clear or []

    # Model-selection keys are operator/REST-only. Refuse them before the
    # approval gate so a refused call never creates an approval card.
    rejected_protected: list[dict[str, Any]] = []
    allowed_updates: dict[str, Any] = {}
    for k, v in updates.items():
        if is_agent_protected_setting(k):
            rejected_protected.append(_protected_setting_rejection(k))
        else:
            allowed_updates[k] = v
    allowed_clear: list[str] = []
    for k in clear:
        if is_agent_protected_setting(k):
            rejected_protected.append(_protected_setting_rejection(k))
        else:
            allowed_clear.append(k)
    if not allowed_updates and not allowed_clear:
        return {"applied": [], "cleared": [], "rejected": rejected_protected}
    updates, clear = allowed_updates, allowed_clear

    def _exec() -> dict[str, Any]:
        applied: list[str] = []
        cleared: list[str] = []
        rejected: list[dict[str, Any]] = list(rejected_protected)
        for k, v in updates.items():
            try:
                s.set(k, v, actor="agent")
                applied.append(k)
            except (PermissionError, ValueError) as pe:
                # Not overridable, or a value of the wrong type for this setting.
                rejected.append({"key": k, "reason": str(pe)})
        for k in clear:
            try:
                if s.clear(k, actor="agent"):
                    cleared.append(k)
            except PermissionError as pe:
                rejected.append({"key": k, "reason": str(pe)})
        return {
            "applied": applied, "cleared": cleared, "rejected": rejected,
        }

    try:
        return await gate_and_execute(
            tool_name="settings_update",
            args={
                "update_keys": sorted(updates.keys()),
                "clear": list(clear),
            },
            risk_tier="soft",
            executor=_exec,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "tool": "settings_update"}


# ─── Notifications (2 tools) ────────────────────────────────────


async def notifications_dismiss(notification_id: str) -> dict[str, Any]:
    """Mark one notification as read/acknowledged. Waits for approval when the install gates it
    (low risk but worth a one-click confirm so the agent can't silently
    hide alerts the operator cares about).

    Returns {dismissed: bool}.
    """
    from usecase.builtin_components._approval_gate import gate_and_execute
    from usecase.notifications import notification_store
    store = notification_store()
    if store is None:
        return {"error": "notification store not initialized on this MCP runtime"}

    def _exec() -> dict[str, Any]:
        ok = store.ack(notification_id)
        return {"dismissed": bool(ok), "id": notification_id}

    try:
        return await gate_and_execute(
            tool_name="notifications_dismiss",
            args={"notification_id": notification_id},
            risk_tier="soft",
            executor=_exec,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "tool": "notifications_dismiss"}


async def notifications_dismiss_all(
    target: str | None = None,
) -> dict[str, Any]:
    """Mark every unread notification as read.
    Waits for approval when the install gates it.

    Args:
        target: optional filter ("user:operator", "channel:soc").
            Null = all targets.

    Returns {dismissed: N}.
    """
    from usecase.builtin_components._approval_gate import gate_and_execute
    from usecase.notifications import notification_store
    store = notification_store()
    if store is None:
        return {"error": "notification store not initialized on this MCP runtime"}

    def _exec() -> dict[str, Any]:
        # Same store call the /notifications page's Mark All Read uses.
        return {"dismissed": store.ack_all(target=target)}

    try:
        return await gate_and_execute(
            tool_name="notifications_dismiss_all",
            args={"target": target} if target else {},
            risk_tier="soft",
            executor=_exec,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "tool": "notifications_dismiss_all"}


# ─── Approvals (1 tool) ─────────────────────────────────────────


async def approvals_resolve(
    approval_id: str,
    decision: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Resolve a pending approval. Waits for approval when the install gates it (yes — gating the
    gate-resolver looks recursive, but it's correct: an agent that
    can resolve random approvals would defeat the human-in-the-loop
    contract entirely. The bus's actor != resolver check additionally
    prevents self-resolution at the storage level.

    The operator's preferred way to resolve approvals is the
    /approvals UI. This tool exists for flows where the operator
    explicitly tells the agent to do it — e.g. "approve the latest
    pending approval and tell me what changed."

    Args:
        approval_id: UUID of a pending row.
        decision: "approved" | "denied" (or aliases).
        reason: optional human-readable note.

    Returns the resolved approval row.
    """
    from usecase.approvals_bus import approvals_bus
    from usecase.builtin_components._approval_gate import gate_and_execute
    bus = approvals_bus()
    if bus is None:
        return {"error": "approvals bus not initialized on this MCP runtime"}

    def _exec() -> dict[str, Any]:
        # NOTE: the bus's resolve() RAISES ApprovalSelfResolveError if
        # the resolver matches the original requester (see
        # bus.resolve). We pass actor="agent" — if the agent is asked
        # to resolve an approval IT initiated, this raises and we
        # surface the error to the agent's reply.
        resolved = bus.resolve(
            approval_id, resolver="agent",
            decision=decision, reason=reason,
        )
        if resolved is None:
            return {"error": f"approval {approval_id!r} not found"}
        return {"approval": resolved.to_dict()}

    try:
        return await gate_and_execute(
            tool_name="approvals_resolve",
            args={"approval_id": approval_id, "decision": decision},
            risk_tier="soft",
            executor=_exec,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "tool": "approvals_resolve"}


# ═════════════════════════════════════════════════════════════════
# TIER 3 — destructive tools
#
# Each one IRRECOVERABLY removes data: a scheduled job, a custom
# skill file, an entire personality blob, a settings override. Same gate machinery as Tier 2 but with `risk_tier="destructive"`
# so the approval card UI renders a red banner and the
# operator's audit trail is filterable on agent_self_mod_executed
# WHERE risk_tier='destructive'.
#
# Trigger phrases:
#   "delete the daily-soc-coverage job"            → jobs_delete
#   "remove the legacy skill X"                    → skills_delete
#   "reset my personality to defaults"             → personality_reset
#   "clear the defaultModel override"              → settings_reset (refused for model keys)
#
# Deleting connector instances and providers is NOT here: those hold
# credentials and are REST-only (usecase/credential_guardrail.py).
# ═════════════════════════════════════════════════════════════════


async def jobs_delete(name: str) -> dict[str, Any]:
    """Permanently remove a runtime job. Waits for approval when the install gates it (destructive).

    Manifest jobs (source='manifest') can be removed via this tool;
    they reappear on next boot from the manifest. Runtime jobs are
    gone for good — their YAML mirror at <data_root>/jobs/<name>.yaml
    is also removed (see job_scheduler._remove_job_yaml).

    Returns {deleted: bool, name}.
    """
    from usecase.builtin_components._approval_gate import gate_and_execute
    from usecase.job_scheduler import scheduler
    s = scheduler()
    if s is None:
        return {"error": "scheduler not initialized on this MCP runtime"}

    def _exec() -> dict[str, Any]:
        ok = s.delete_job(name)
        return {"deleted": bool(ok), "name": name}

    try:
        return await gate_and_execute(
            tool_name="jobs_delete",
            args={"name": name},
            risk_tier="destructive",
            executor=_exec,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "tool": "jobs_delete"}


async def skills_delete(file_path: str) -> dict[str, Any]:
    """Permanently remove a skill markdown file. Waits for approval when the install gates it
    (destructive).

    Wraps the un-gated `skills_crud.skills_delete` function with the
    approval gate. The connector_loader registration for
    `skills_delete` points at THIS function (not skills_crud.skills_delete
    directly) so the gate is always enforced.

    Args:
        file_path: Relative path to skill file (e.g.,
                   'scenarios/port_scan.md'). Parameter name MUST match
                   the underlying skills_crud.skills_delete signature
                   AND the legacy MCP Tool inputSchema in
                   skills_crud.py — both expect `file_path`. Renaming
                   it would break the delete surface: the Next.js
                   /api/skills DELETE route passes `file_path` per the
                   legacy schema, FastMCP's per-tool validator
                   (derived from THIS function's signature) would
                   reject any other name as "Unexpected keyword
                   argument," and the Pydantic error string would be
                   wrapped into the tool's result content, which the
                   Next.js side then fails to JSON.parse.

    Returns the underlying skills_crud result on success.
    """
    from usecase.builtin_components import skills_crud
    from usecase.builtin_components._approval_gate import gate_and_execute

    def _exec() -> dict[str, Any]:
        # skills_crud.skills_delete returns a JSON-encoded string;
        # parse it back so the gate's caller (the MCP tool result
        # content path) gets a structured dict it can compose into
        # its own response shape consistently with the other
        # gated wrappers in this module (jobs_delete, settings_reset,
        # etc.) which all return dicts.
        import json as _json
        raw = skills_crud.skills_delete(file_path)
        try:
            return _json.loads(raw) if isinstance(raw, str) else raw
        except (_json.JSONDecodeError, TypeError):
            # Fall through with raw string wrapped — extreme defensive
            # path; should never trigger because skills_crud.skills_delete
            # always returns json.dumps(dict).
            return {"success": True, "raw": raw}

    try:
        return await gate_and_execute(
            tool_name="skills_delete",
            args={"file_path": file_path},
            risk_tier="destructive",
            executor=_exec,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "tool": "skills_delete"}


async def personality_reset() -> dict[str, Any]:
    """Revert the agent's persona to the bundle default. Waits for approval when the install gates it
    (destructive).

    Wipes any operator-tuned customization. The previous version is
    preserved in personality_history so the operator can manually
    re-apply if reset was a mistake.

    Returns {personality, updated_at, updated_by, version}.
    """
    from usecase.builtin_components._approval_gate import gate_and_execute
    from usecase.personality_store import personality_store
    s = personality_store()
    if s is None:
        return {"error": "personality store not initialized on this MCP runtime"}

    def _exec() -> dict[str, Any]:
        updated = s.reset_to_default(actor="agent")
        return updated.to_dict()

    try:
        return await gate_and_execute(
            tool_name="personality_reset",
            args={},
            risk_tier="destructive",
            executor=_exec,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "tool": "personality_reset"}


async def settings_reset(
    keys: list[str] | None = None,
) -> dict[str, Any]:
    """Clear runtime settings overrides. Waits for approval when the install gates it (destructive).

    Model-selection keys (`defaultModel` and any key ending in "model")
    are operator-only and are never cleared by this tool: naming one is
    refused, and clearing everything leaves them untouched. Both cases
    list them under `rejected[]`.

    Args:
        keys: list of override keys to clear. If None or empty,
            clears EVERY override except the model-selection keys —
            equivalent to "revert all my customizations". Operator
            probably wants this on a fresh deploy or when
            troubleshooting "why is the agent doing X?"

    Returns {cleared: [...], not_found: [...], rejected: [...]}.
    """
    from usecase.builtin_components._approval_gate import gate_and_execute
    from usecase.settings_store import settings_store
    s = settings_store()
    if s is None:
        return {"error": "settings store not initialized on this MCP runtime"}

    target_keys = list(keys) if keys else [o.key for o in s.overrides()]
    rejected = [
        _protected_setting_rejection(k)
        for k in target_keys if is_agent_protected_setting(k)
    ]
    target_keys = [k for k in target_keys if not is_agent_protected_setting(k)]
    if not target_keys:
        return {"cleared": [], "not_found": [], "rejected": rejected}

    def _exec() -> dict[str, Any]:
        cleared: list[str] = []
        not_found: list[str] = []
        for k in target_keys:
            if s.clear(k, actor="agent"):
                cleared.append(k)
            else:
                not_found.append(k)
        return {"cleared": cleared, "not_found": not_found, "rejected": rejected}

    try:
        return await gate_and_execute(
            tool_name="settings_reset",
            args={"keys": target_keys},
            risk_tier="destructive",
            executor=_exec,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "tool": "settings_reset"}


# Credential-side tools (instances_*, providers_*, api_keys_* writes) are
# deliberately NOT defined in this module. They are REST-only; the canonical
# list of their names is usecase/credential_guardrail.py. Keeping them out of
# the agent-facing module means no dispatch table here (agent_batch_propose
# below, or any later one) can reach them by name.


# ═════════════════════════════════════════════════════════════════════
# TIER 5 — multi-action batch
#
# The problem this solves: when the agent has multiple
# mutations to make (e.g. "schedule a daily simulation job for each of
# my 5 skills"), every job_create would fire its own approval
# card. Operators saw 5 sequential cards for what was conceptually one
# decision, and the agent often timed out on rows 2-5 because the
# operator had already mentally committed by the time card 1 cleared.
#
# `agent_batch_propose` bundles N actions into ONE approval
# card. After the operator approves, the executor sets the
# approval-bypass contextvar and dispatches each action in sequence —
# each per-tool gate sees the bypass and executes immediately (with
# full audit trail), no further UI ceremony. If any action fails, the
# loop continues and partial-success is returned; the operator can
# review per-action results in the response.
#
# Design constraints:
#   1. The batch tool itself is approval-gated. Otherwise the agent
#      could chain unbounded actions without ever showing a card.
#   2. agent_batch_propose can NOT batch itself (no nesting). The
#      _BATCHABLE_TOOLS whitelist excludes it.
#   3. approvals_resolve is also excluded — resolving approvals as part
#      of a batch under approval would be a logical loop.
#   4. Connector tools (web.*, xsiam.*, etc.) can't use the simple
#      await-loop here because they need per-instance contextvar setup;
#      they are dispatched through the tool_dispatcher instead (see
#      the connector-tool coverage note in agent_batch_propose).
# ═════════════════════════════════════════════════════════════════════


_BATCHABLE_TOOLS: dict[str, Any] = {}


def _populate_batchable_tools() -> None:
    """Lazy-populate the batchable-tools dispatch table.

    Done lazily (and once) to dodge the forward-reference problem of
    referencing tool functions in a module-level dict before their
    definitions parse. Called inside `agent_batch_propose` on first use.

    The whitelist is intentionally narrower than `BUILTIN_TOOLS` in
    connector_loader: it includes only the WRITE tools (Tier 2-3
    self-mod ops) — reads don't need batching because they're not
    approval-gated. It also excludes `agent_batch_propose` (no nesting)
    and `approvals_resolve` (logical loop hazard).

    Credential-side tools (usecase/credential_guardrail.py) are never in
    this table; the check at the end of this function enforces it.
    """
    if _BATCHABLE_TOOLS:
        return
    _BATCHABLE_TOOLS.update({
        # Tier 2 (soft writes)
        "jobs_create": jobs_create,
        "jobs_update": jobs_update,
        "jobs_run_now": jobs_run_now,
        "personality_update": personality_update,
        "personality_patch": personality_patch,
        "organization_update": organization_update,
        "organization_activate": organization_activate,
        "settings_update": settings_update,
        "notifications_dismiss": notifications_dismiss,
        "notifications_dismiss_all": notifications_dismiss_all,
        # Tier 3 (destructive)
        "jobs_delete": jobs_delete,
        "skills_delete": skills_delete,
        "personality_reset": personality_reset,
        "settings_reset": settings_reset,
    })
    # Fail closed: the table must never contain a credential-side tool, even
    # after a later edit. Roll back the partial population so a caller that
    # catches this does not see a poisoned table.
    try:
        assert_no_credential_tools(
            _BATCHABLE_TOOLS, where="agent_batch_propose dispatch table",
        )
    except CredentialGuardrailError:
        _BATCHABLE_TOOLS.clear()
        raise


async def agent_batch_propose(actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Bundle N self-modification actions into ONE approval ceremony.

    When the operator asks the agent to take multiple actions at once
    ("schedule a daily simulation job for each of my 5 skills",
    "delete these 3 jobs", "dismiss all of these notifications"),
    use this tool to present them as ONE approval card instead
    of firing N independent approvals. The operator sees the full plan
    inline and approves (or denies) the whole batch.

    Trigger phrases:
        "do all of these at once"
        "create jobs for all 5 skills with one approval"
        "I don't want to approve each one separately"
        ANY chat turn where the agent plans to make 2+ gated mutations
        in immediate succession with no operator dialogue between them

    Behavior:
        1. agent_batch_propose itself triggers ONE approval card.
        2. Card displays the action list (tool name + summarized args
           per row) so the operator sees the whole plan.
        3. On approve: bypass contextvar is set; actions execute in
           order. Each per-tool gate audits a "bypass" event but skips
           the UI ceremony.
        4. On deny: nothing executes.
        5. Per-action failures during execution don't abort the loop —
           the response reports partial success.

    Args:
        actions: list of {tool: str, args: dict}. Each action may be:
            - A built-in Tier 2/3 self-mod tool (`jobs_*`, `settings_*`,
              `personality_*`, `notifications_*`, `skills_delete`).
              Dispatched directly for speed.
            - A connector tool registered on the running MCP (e.g.
              `xsiam/send_webhook_log`, `caldera/create_operation`,
              `web/navigate`). Dispatched through the unified
              tool_dispatcher (same path the scheduler uses), which
              preserves per-instance contextvar setup, Pydantic
              marshalling, and result unwrapping.
            - A read tool (`*_list`, `*_get`, `audit_*`, etc.) — works
              but is rarely useful inside a batch since reads don't
              cost approvals; the agent should call them inline.

            Excluded (loop hazards): `agent_batch_propose` itself,
            `approvals_resolve`.

            Refused (credential guardrail): connector instances,
            providers and API keys hold credentials, so no action may
            name `instances_create/update/delete`,
            `providers_create/update/delete` or
            `api_keys_create/rotate/revoke`, bare or namespaced. They
            are operator-only (REST/UI). Tell the operator to use the
            Instances, Providers or API keys page instead.

    Returns:
        {
          batch_id: str,
          ok: bool,                    # overall success flag
          approved: bool,
          executed: int,
          succeeded: int,
          failed: int,
          per_action_results: [
            {tool, args, ok: bool, result?, error?},
            ...
          ],
        }

    Errors raised:
        - ApprovalDeniedError if the operator denies the batch
        - ApprovalTimeoutError if no decision within the gate timeout
        - ValueError if `actions` is empty, malformed, or contains
          unbatchable or credential-side tool names (raised BEFORE the approval card —
          the agent sees a clean validation error to fix and retry)
    """
    from usecase.audit_log import (
        set_current_approval_bypass,
        reset_current_approval_bypass,
    )
    from usecase.builtin_components._approval_gate import gate_and_execute

    # Eager validation BEFORE firing the approval card. Better UX: the
    # agent sees the error and can correct without burning operator
    # attention on a malformed card.
    if not isinstance(actions, list) or not actions:
        return {
            "ok": False,
            "error": "actions must be a non-empty list",
            "tool": "agent_batch_propose",
        }
    if len(actions) > 25:
        # Soft cap: a 25-action batch already shows a long approval
        # card. Larger batches likely indicate the agent should ask
        # the operator to chunk the request rather than ratify a wall
        # of actions in one go.
        return {
            "ok": False,
            "error": (
                f"batch too large ({len(actions)} actions); split into "
                f"multiple batches of ≤25"
            ),
            "tool": "agent_batch_propose",
        }

    _populate_batchable_tools()

    # Connector-tool batch coverage: besides the built-in self-mod
    # tools in _BATCHABLE_TOOLS, any tool in the process-wide
    # tool_registry can appear in a batch, dispatched through the same fastmcp.Client path
    # the job scheduler uses — so per-instance contextvar setup,
    # Pydantic marshalling, and CallToolResult unwrapping all work
    # identically to agent-driven calls.
    #
    # Two hard exclusions apply (the loop-hazard set):
    #   - agent_batch_propose itself (no nesting)
    #   - approvals_resolve (logical loop)
    from usecase.tool_dispatcher import get_tool_dispatcher
    dispatcher = get_tool_dispatcher()

    # We can read the tool_registry directly via the connector_loader's
    # private singleton — same one set_reload_state populates at boot.
    # Importing the private name is OK here because it's a tightly-
    # coupled pair within the same bundle.
    def _tool_in_registry(name: str) -> bool:
        try:
            from usecase import connector_loader  # type: ignore[attr-defined]
            state = getattr(connector_loader, "_reload_state", None)
            if not isinstance(state, dict):
                return False
            reg = state.get("tool_registry") or {}
            return name in reg
        except Exception:
            return False

    _UNBATCHABLE = {"agent_batch_propose", "approvals_resolve"}

    normalized: list[dict[str, Any]] = []
    for idx, raw in enumerate(actions):
        if not isinstance(raw, dict):
            return {
                "ok": False,
                "error": f"action[{idx}] must be an object",
                "tool": "agent_batch_propose",
            }
        tool_name = raw.get("tool")
        action_args = raw.get("args") or {}
        if not isinstance(tool_name, str) or not tool_name:
            return {
                "ok": False,
                "error": f"action[{idx}].tool is required (string)",
                "tool": "agent_batch_propose",
            }
        if not isinstance(action_args, dict):
            return {
                "ok": False,
                "error": f"action[{idx}].args must be an object",
                "tool": "agent_batch_propose",
            }
        # Credential guardrail. Checked before the dispatch-route split so
        # it covers BOTH routes (built-in table and registry dispatch),
        # and by name so it still holds if the table is edited later.
        if is_credential_tool(tool_name):
            return {
                "ok": False,
                "error": (
                    f"action[{idx}].tool {tool_name!r} is a credential-side "
                    f"tool and cannot be run by the agent, alone or in a "
                    f"batch. Credentials (provider auth, instance secrets, "
                    f"API keys) are operator-only: ask the operator to use "
                    f"the Instances, Providers or API keys page."
                ),
                "tool": "agent_batch_propose",
                "guardrail": "credential",
            }
        if tool_name in _UNBATCHABLE:
            return {
                "ok": False,
                "error": (
                    f"action[{idx}].tool {tool_name!r} cannot appear inside a "
                    f"batch (loop hazard). Excluded: {sorted(_UNBATCHABLE)}"
                ),
                "tool": "agent_batch_propose",
            }
        # Two dispatch routes:
        #   - Built-in self-mod tool (in _BATCHABLE_TOOLS): direct call,
        #     no fastmcp.Client overhead.
        #   - Any other registered tool (connector tools, cognitive
        #     read tools, etc.): dispatch through tool_dispatcher().
        is_builtin = tool_name in _BATCHABLE_TOOLS
        is_registered = _tool_in_registry(tool_name)
        if not is_builtin and not is_registered:
            return {
                "ok": False,
                "error": (
                    f"action[{idx}].tool {tool_name!r} is not a known "
                    f"tool. Built-ins: {sorted(_BATCHABLE_TOOLS.keys())}. "
                    f"Connector tools must be registered in the tool "
                    f"registry — check that the corresponding connector "
                    f"has an instance configured."
                ),
                "tool": "agent_batch_propose",
            }
        if not is_builtin and dispatcher is None:
            return {
                "ok": False,
                "error": (
                    f"action[{idx}].tool {tool_name!r} requires the "
                    f"tool dispatcher, which isn't installed on this "
                    f"MCP runtime"
                ),
                "tool": "agent_batch_propose",
            }
        normalized.append({"tool": tool_name, "args": action_args})

    import uuid
    batch_id = str(uuid.uuid4())

    # Build the approval-card args payload. The UI keys on `actions`
    # being present to render the list view; if absent, falls through
    # to the standard single-action card layout. We also include a
    # concise summary so the audit log doesn't need to re-parse args.
    gate_args = {
        "batch_id": batch_id,
        "action_count": len(normalized),
        "actions": [
            {
                "tool": a["tool"],
                # Persist arg KEYS only on the audit row by default;
                # full args are persisted on the approval card so the
                # operator sees what's being proposed without grep'ing
                # the audit log. The approval bus already redacts known
                # credential fields per its sanitize pass.
                "args": a["args"],
            }
            for a in normalized
        ],
        "summary": _summarize_batch(normalized),
    }

    async def _execute_batch() -> dict[str, Any]:
        """Run each action in sequence under bypass-contextvar.

        Two dispatch paths:
          1. Built-in self-mod tool — direct fn call (faster).
          2. Connector tool / any other registered tool — dispatch via
             tool_dispatcher() which routes through fastmcp.Client and
             therefore preserves per-instance contextvar setup, Pydantic
             marshalling, and CallToolResult unwrapping. Same path the
             scheduler uses.

        Failure mode: per-action errors are captured and returned —
        they do NOT abort the loop. The operator gets a complete
        per-action result map so they can see what worked vs. didn't
        and decide whether to re-run the failed subset.
        """
        token = set_current_approval_bypass(True)
        per_action: list[dict[str, Any]] = []
        succeeded = 0
        failed = 0
        try:
            for action in normalized:
                tool_name = action["tool"]
                action_args = action["args"]
                try:
                    if tool_name in _BATCHABLE_TOOLS:
                        # Path 1: built-in. Direct call, no fastmcp
                        # round-trip.
                        fn = _BATCHABLE_TOOLS[tool_name]
                        result = fn(**action_args)
                        import asyncio as _asyncio
                        if _asyncio.iscoroutine(result):
                            result = await result
                    else:
                        # Path 2: connector/other registered tool. Go
                        # through the unified dispatcher so per-instance
                        # contextvar wiring fires correctly. dispatcher
                        # was validated non-None during normalization
                        # for non-builtin paths.
                        assert dispatcher is not None  # mypy hint
                        result = await dispatcher(tool_name, action_args)
                    # Tools that internally fail (e.g. "settings store
                    # not initialized") return a dict with `error` —
                    # treat that as failure for the per-action count so
                    # the operator's audit trail surfaces the right
                    # success/failure breakdown.
                    if isinstance(result, dict) and result.get("error"):
                        per_action.append({
                            "tool": tool_name,
                            "args": action_args,
                            "ok": False,
                            "error": result["error"],
                        })
                        failed += 1
                        _emit_batch_action_metric(tool_name, "fail")
                    else:
                        per_action.append({
                            "tool": tool_name,
                            "args": action_args,
                            "ok": True,
                            "result": result,
                        })
                        succeeded += 1
                        _emit_batch_action_metric(tool_name, "success")
                except Exception as exc:  # noqa: BLE001
                    per_action.append({
                        "tool": tool_name,
                        "args": action_args,
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    failed += 1
                    _emit_batch_action_metric(tool_name, "fail")
        finally:
            reset_current_approval_bypass(token)
        # Batch was approved + executed — record the proposal
        # outcome + size histogram observation. Lazy-registers the
        # metrics if main.py's manifest-counter loop didn't already
        # (histograms aren't in the manifest declaration loop).
        _emit_batch_proposal_metric(approved=True, size=len(normalized))
        return {
            "batch_id": batch_id,
            "ok": failed == 0,
            "approved": True,
            "executed": len(normalized),
            "succeeded": succeeded,
            "failed": failed,
            "per_action_results": per_action,
        }

    try:
        return await gate_and_execute(
            tool_name="agent_batch_propose",
            args=gate_args,
            risk_tier="soft",  # The batch row inherits the highest
            # risk among its actions; the approvals UI may upgrade
            # severity from this baseline based on what's inside.
            executor=_execute_batch,
        )
    except Exception as exc:  # noqa: BLE001
        # Gate raised → denied/timeout/bus-error path. Record
        # the proposal outcome as not approved so dashboards can see
        # the deny-vs-approve ratio. Size is still meaningful (how big
        # was the rejected ask?).
        _emit_batch_proposal_metric(approved=False, size=len(normalized))
        return {
            "ok": False,
            "approved": False,
            "batch_id": batch_id,
            "error": str(exc),
            "tool": "agent_batch_propose",
        }


# ─── batch metrics emission ──────────────────────────────────────────
#
# Three Prometheus metrics for agent_batch_propose. The first two are
# also pre-declared in manifest.observability.metrics[] so dashboards
# see them as 0-valued counters before any batch fires. The histogram
# is registered lazily on first call (histograms aren't in the
# manifest pre-registration loop).
#
# Metric design:
#   - phantom_batch_proposals_total{approved="true"|"false"}
#       counter — every agent_batch_propose call increments once. Lets
#       the operator see batch usage AND the deny-rate over time.
#   - phantom_batch_actions_total{tool="...",result="success"|"fail"}
#       counter — one inc per action inside a batch. The tool label
#       reveals which tools dominate batch traffic; the result label
#       splits success vs failure for per-tool reliability dashboards.
#   - phantom_batch_size (histogram, custom count-buckets 1/2/3/5/10/25)
#       distribution of batch sizes. Bucket choice matches the
#       25-action cap — a value above the top bucket would mean
#       validation regressed (the eager check should block it).


def _emit_batch_proposal_metric(*, approved: bool, size: int) -> None:
    """Increment proposals_total + observe size. Silent no-op when the
    metrics registry isn't installed (test harness, partial boot)."""
    try:
        from usecase.metrics_registry import metrics_registry  # type: ignore
        reg = metrics_registry()
        if reg is None:
            return
        c = reg.counter(
            "phantom_batch_proposals_total",
            "agent_batch_propose calls broken down by outcome (approved/denied)",
        )
        c.inc(approved=str(approved).lower())
        h = reg.histogram(
            "phantom_batch_size",
            "distribution of agent_batch_propose batch sizes",
            buckets=(1.0, 2.0, 3.0, 5.0, 10.0, 25.0),
        )
        h.observe(float(size))
    except Exception:  # noqa: BLE001
        # Metrics failures must NEVER affect the tool's primary path.
        # The agent's batch result is correct regardless of whether
        # observability collected the data point.
        pass


def _emit_batch_action_metric(tool_name: str, result: str) -> None:
    """Per-action counter with {tool, result} labels. Same silent-fail
    contract as _emit_batch_proposal_metric."""
    try:
        from usecase.metrics_registry import metrics_registry  # type: ignore
        reg = metrics_registry()
        if reg is None:
            return
        c = reg.counter(
            "phantom_batch_actions_total",
            "individual action executions inside batches, labeled by tool + result",
        )
        c.inc(tool=tool_name, result=result)
    except Exception:  # noqa: BLE001
        pass


def _summarize_batch(actions: list[dict[str, Any]]) -> str:
    """Generate a one-line operator-readable summary of the batch
    contents. Used in the approval-card title and audit-log metadata."""
    from collections import Counter
    counts = Counter(a["tool"] for a in actions)
    parts = [f"{n}× {t}" for t, n in sorted(counts.items())]
    return f"batch of {len(actions)} actions: " + ", ".join(parts)


# ─────────────────────────────────────────────────────────────────
# Marketplace tools (catalog operations — not credentials)
#
# Per the agent credential guardrail (CLAUDE.md "Agent
# credential guardrail (MANDATORY)"), the agent cannot read/write/
# mint/rotate credentials. These 4 tools are CATALOG operations —
# install state, schema upload, registry membership — NOT
# credential operations. They legitimately belong in the agent's
# tool surface.
#
# The distinction codified for future maintainers:
#
#   * Credential boundary: anything that reads, writes, mints, or
#     rotates a SecretStore value. Forbidden for the agent.
#       Examples: instances_create (carries secrets), api_keys_*,
#       providers_create.
#
#   * Catalog boundary: anything that mutates the CONNECTOR-
#     CATALOG-LEVEL metadata — install state, connector schemas,
#     marketplace membership. Permitted for the agent.
#       Examples: marketplace_install, connector_upload.
#
# The two boundaries can move independently. The catalog boundary
# is open to the agent; the credential boundary stays closed.
# ─────────────────────────────────────────────────────────────────


def marketplace_list() -> dict[str, Any]:
    """List marketplace connectors with install state + instance counts.

    READ-ONLY catalog operation. Same data the operator sees on
    /connectors → Marketplace tab. Use this when the operator asks
    "what connectors are available?", "which ones are installed?",
    "what's in the marketplace?".

    Returns {connectors: [{id, version, description, tools_count,
    tags, origin, installed, install, instances_count}], count}.

    `origin` is "bundle" (shipped in the image) or "user" (uploaded
    via connector_upload). `installed` is True only when the operator
    has explicitly installed the connector via marketplace_install
    (or the upgrade migration installed it because instances
    already existed).
    """
    from usecase.marketplace_store import get_marketplace_store
    from api.marketplace import _scan_catalogue, _instances_count
    from usecase.instance_store import instance_store

    mp = get_marketplace_store()
    if mp is None:
        return {"error": "marketplace store not initialized on this MCP runtime"}
    s = instance_store()
    if s is None:
        return {"error": "instance store not initialized on this MCP runtime"}

    catalogue = _scan_catalogue()
    installs_by_id = {r.connector_id: r for r in mp.list_installed()}
    connectors: list[dict[str, Any]] = []
    for cid, summary in sorted(catalogue.items()):
        row = installs_by_id.get(cid)
        connectors.append(
            {
                **summary,
                "installed": row is not None,
                "install": (
                    {
                        "connector_id": row.connector_id,
                        "installed_at": row.installed_at,
                        "origin": row.origin,
                        "version": row.version,
                    }
                    if row
                    else None
                ),
                "instances_count": _instances_count(s, cid),
            }
        )
    return {"connectors": connectors, "count": len(connectors)}


def marketplace_install(connector_id: str) -> dict[str, Any]:
    """Mark a connector as installed — making it available for
    instance creation.

    Catalog operation. NOT a credential operation — installs a
    catalog entry, doesn't touch secrets. Per CLAUDE.md's catalog-
    vs-credential boundary distinction, this is in-bounds for the
    agent.

    Use when the operator says "install <name>", "make <name>
    available", "enable the <name> connector". Idempotent: installing
    an already-installed connector returns the existing row.

    Args:
        connector_id: the connector to install. Must exist in the
            marketplace catalogue (bundle or previously uploaded
            user connector). Returns {error} if unknown.

    Returns {ok, install: {connector_id, installed_at, origin,
    version}} or {error}. After successful install the operator can
    create an instance via the /connectors UI (the agent does NOT
    create instances — that's a credential operation requiring
    secrets, which the credential guardrail forbids).
    """
    from usecase.marketplace_store import get_marketplace_store
    from api.marketplace import _scan_catalogue
    from usecase.audit_log import record_event

    mp = get_marketplace_store()
    if mp is None:
        return {"error": "marketplace store not initialized on this MCP runtime"}
    if not isinstance(connector_id, str) or not connector_id:
        return {"error": "connector_id must be a non-empty string"}

    catalogue = _scan_catalogue()
    summary = catalogue.get(connector_id)
    if summary is None:
        return {
            "error": (
                f"connector {connector_id!r} not found in catalogue. "
                f"Available: {sorted(catalogue.keys())}"
            ),
        }
    origin = summary["origin"]
    row = mp.install(
        connector_id,
        origin=origin,
        version=summary.get("version", "0.0.0"),
    )
    record_event(
        action="marketplace_install",
        target=f"connector:{connector_id}",
        status="success",
        metadata={"origin": origin, "version": row.version, "by": "agent"},
    )
    return {
        "ok": True,
        "install": {
            "connector_id": row.connector_id,
            "installed_at": row.installed_at,
            "origin": row.origin,
            "version": row.version,
        },
        "next_step": (
            f"The connector is now available for instance creation. The "
            f"operator can create an instance via /connectors → {connector_id} "
            f"→ Create Instance (the agent itself can't create instances "
            f"because that's a credential operation — see CLAUDE.md's "
            f"agent credential guardrail)."
        ),
    }


def marketplace_uninstall(connector_id: str) -> dict[str, Any]:
    """Remove the install marker from a connector.

    Catalog operation. Refuses if instances exist for the connector
    (returns {error, instances_count}) — the operator must delete
    instances first via the /connectors UI. Instance deletion IS
    a credential operation (secret cleanup) so the agent can't do
    it; this is a guard that prevents a half-cleaned-up state.

    Use when the operator says "uninstall <name>", "remove <name>
    from the marketplace", "I don't need <name> anymore".

    Args:
        connector_id: the connector to uninstall. Returns {error} if
            unknown, not installed, or has live instances.

    Returns {ok, removed} or {error, instances_count}.
    """
    from usecase.marketplace_store import get_marketplace_store
    from api.marketplace import _instances_count
    from usecase.instance_store import instance_store
    from usecase.audit_log import record_event

    mp = get_marketplace_store()
    if mp is None:
        return {"error": "marketplace store not initialized on this MCP runtime"}
    if not isinstance(connector_id, str) or not connector_id:
        return {"error": "connector_id must be a non-empty string"}

    if not mp.is_installed(connector_id):
        return {"error": f"connector {connector_id!r} is not installed"}

    s = instance_store()
    if s is not None:
        n = _instances_count(s, connector_id)
        if n > 0:
            return {
                "error": (
                    f"connector {connector_id!r} has {n} instance(s); "
                    f"the operator must delete them first via /connectors → "
                    f"{connector_id} → Instances. The agent can't delete "
                    f"instances (per CLAUDE.md's credential guardrail)."
                ),
                "instances_count": n,
            }

    removed = mp.uninstall(connector_id)
    record_event(
        action="marketplace_uninstall",
        target=f"connector:{connector_id}",
        status="success" if removed else "noop",
        metadata={"by": "agent"},
    )
    return {"ok": True, "removed": removed}


def connector_upload(yaml_content: str) -> dict[str, Any]:
    """Upload a new connector schema (YAML content) into the marketplace.

    Catalog operation. The YAML content carries the connector's
    manifest — id, version, description, tools, config schema, secret
    slots, and the OCI image reference. No secrets, no credential
    material. Per CLAUDE.md's catalog-vs-credential distinction this
    sits firmly on the catalog side.

    Use when the operator says "upload this connector", "add a new
    connector to the marketplace", or pastes a YAML and asks "can you
    register this?".

    Validation pipeline (fail-fast on first error):
      1. yaml_content is non-empty and parses as a top-level YAML
         object.
      2. Spec validates against connector.schema.json.
      3. spec.id does not collide with a bundle connector id.
      4. spec.id is not already an uploaded user connector.
      5. spec has an 'image' field — required for user connectors.

    On success: writes
    /app/data/user_connectors/<id>/connector.yaml, emits a
    `connector_uploaded` audit event, returns the parsed summary.

    Args:
        yaml_content: the YAML text the operator wants to upload.
            Full connector.yaml content. See
            bundles/spark/connectors/connector.schema.json for the
            shape.

    Returns {ok, connector: {id, version, description, ...},
    next_step} or {error, code}. After success the operator should
    install the connector via marketplace_install(<id>) then create
    an instance via /connectors (instance creation = secrets =
    operator-only per credential guardrail).
    """
    from usecase.connector_schema import (
        ConnectorSpecError,
        validate_connector_spec,
    )
    from usecase.marketplace_store import resolved_data_root
    from api.marketplace import (
        _scan_catalogue,
        _connector_summary,
    )
    from usecase.audit_log import record_event

    if not isinstance(yaml_content, str) or not yaml_content.strip():
        return {"error": "yaml_content must be a non-empty string"}

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return {"error": "server missing pyyaml dep — cannot parse YAML"}

    try:
        spec = yaml.safe_load(yaml_content)
    except yaml.YAMLError as err:
        return {"error": f"YAML failed to parse: {err}"}
    if not isinstance(spec, dict):
        return {"error": "YAML must be a top-level object"}

    try:
        validate_connector_spec(spec, source_path="<connector_upload>")
    except ConnectorSpecError as err:
        return {"error": str(err), "code": "schema_validation_failed"}

    cid = spec.get("id")
    if not isinstance(cid, str):
        return {"error": "YAML missing valid id field"}

    catalogue = _scan_catalogue()
    existing = catalogue.get(cid)
    if existing is not None:
        if existing.get("origin") == "bundle":
            return {
                "error": (
                    f"connector id {cid!r} is reserved by a bundle "
                    f"connector; choose a different id"
                ),
                "code": "id_collides_with_bundle",
            }
        return {
            "error": (
                f"user connector {cid!r} already exists; the operator "
                f"must DELETE it via /connectors before re-uploading"
            ),
            "code": "id_already_exists",
        }

    image_ref = spec.get("image")
    if not isinstance(image_ref, str) or not image_ref.strip():
        return {
            "error": (
                "user connectors must declare an 'image' field with the "
                "OCI image reference of the published connector "
                "container (e.g. 'ghcr.io/your-org/your-connector:v1.0')"
            ),
            "code": "image_ref_required",
        }

    target_dir = resolved_data_root() / "user_connectors" / cid
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "connector.yaml").write_text(
            yaml_content, encoding="utf-8",
        )
    except OSError as err:
        return {"error": f"could not persist user connector: {err}"}

    record_event(
        action="connector_uploaded",
        target=f"connector:{cid}",
        status="success",
        metadata={
            "origin": "user",
            "version": spec.get("version", "0.0.0"),
            "image": image_ref,
            "tools_count": len((spec.get("spec") or {}).get("tools") or []),
            "by": "agent",
        },
    )

    return {
        "ok": True,
        "connector": _connector_summary(
            cid, target_dir / "connector.yaml", "user",
        ),
        "next_step": (
            f"Call marketplace_install({cid!r}) to make this connector "
            f"available for instance creation. The operator then creates "
            f"an instance via /connectors → {cid} → Create Instance."
        ),
    }


# ─── benchmark runner tool ───────────────────────────────────────────


async def bench_run(
    manifest: str,
    router_preset_model: str | None = None,
    thinking_enabled: bool = False,
) -> dict[str, Any]:
    """Run a benchmark manifest against the chat route. Waits for approval when the install gates it.

    Dispatches each case in the manifest via the agent's /api/chat
    endpoint, collects tool calls + final response + cost + wall,
    scores via the 5-axis scorer, records to benchmark_runs.db.

    Args:
        manifest: Either a path to a YAML manifest file (absolute or
            relative to CWD on the agent container) OR a bundled-corpus
            id ("phantom-soc-v1" resolves to bench_cases/phantom-soc-v1.yaml
            packaged with the agent image). Concrete trigger phrases:
            "run the phantom-soc-v1 benchmark", "run the bench
            manifest at /tmp/my-bench.yaml".
        router_preset_model: Optional per-bench model override sent as
            body.model on every dispatched case, a canonical "provider/
            model" ref. Use "vertex/gemini-3.7-flash" for a cheap-routing
            preset bench, "vertex/gemini-3.1-pro-preview" for a
            thinking-on-by-default preset, or omit to use the install
            default. A model that is unknown or unavailable fails each
            case with MODEL_UNAVAILABLE; nothing is substituted.
        thinking_enabled: Pass through to body.thinking on every case.
            Honored by models that have a thinking or reasoning mode;
            others ignore it.

    Returns: { "run_id": str, "summary": {...} } on success;
             { "error": str } on manifest-parse failure.

    Trigger phrases: "run the phantom-soc-v1 benchmark", "bench the
    agent on flash routing", "run the bench manifest <path>".
    """
    from usecase.builtin_components._approval_gate import gate_and_execute
    from usecase.benchmark_runner import run_manifest as _run_manifest_async

    async def _exec() -> dict[str, Any]:
        try:
            summary = await _run_manifest_async(
                manifest,
                router_preset_model=router_preset_model,
                thinking_enabled=thinking_enabled,
                record=True,
            )
        except ValueError as exc:
            return {"error": str(exc)}
        return {
            "run_id": summary.run_id,
            "summary": summary.to_dict(),
        }

    try:
        return await gate_and_execute(
            tool_name="bench_run",
            args={
                "manifest": manifest,
                "router_preset_model": router_preset_model,
                "thinking_enabled": thinking_enabled,
            },
            risk_tier="soft",
            executor=_exec,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "tool": "bench_run"}


# ─── Log destinations — read-only surface ──────────────────────────


def log_destinations_list(type_id: str | None = None) -> dict[str, Any]:
    """List configured log destinations (forwarding targets).

    Secrets are NEVER returned — only redacted "***" sentinels for slots
    that are populated. Use this to discover which destinations the
    operator has configured before calling `phantom_create_data_worker`
    with a `destination_id`.

    Args:
        type_id: optional filter — "syslog", "webhook", "xsiam_http",
            "splunk_hec". Null = all types.

    Returns {destinations: [{id, name, type_id, config, secrets (redacted),
                             enabled, is_default, last_probe_at,
                             last_probe_ok, created_at}], count}.

    The agent should prefer destinations marked `is_default: true` for
    a given type when the operator hasn't specified one explicitly.
    """
    from usecase.log_destinations_store import get_log_destination_store
    s = get_log_destination_store()
    rows = s.list_all(type_id=type_id) if type_id else s.list_all()
    out: list[dict[str, Any]] = []
    for d in rows:
        out.append(d.to_dict(include_secrets=False))
    return {"destinations": out, "count": len(out)}


def log_destinations_get(destination_id: str) -> dict[str, Any]:
    """Fetch one log destination by id (uuid) or name.

    Returns {destination: {...}} or {error}. Secrets are NEVER returned
    (only redacted "***" sentinels).

    The agent should call this to confirm a destination exists + see its
    config (host/port/url) before passing its id to a worker.
    """
    from usecase.log_destinations_store import get_log_destination_store
    s = get_log_destination_store()
    d = s.get(destination_id)
    if d is None:
        return {"error": f"log destination {destination_id!r} not found"}
    return {"destination": d.to_dict(include_secrets=False)}


def log_destinations_create(
    name: str, host: str, port: int, protocol: str = "udp"
) -> dict[str, Any]:
    """Create a plain (secretless) syslog Log Destination from a prompt.

    SECRETLESS SYSLOG ONLY. This tool deliberately CANNOT create a
    destination that carries a secret (TLS-syslog, xsiam_http, splunk_hec) —
    those are operator-only: tell the operator to add them in the
    /log-destinations UI. Catalog-side per the credential guardrail: it
    writes NO SecretStore value (plain UDP/TCP syslog has no secret slot).

    Use this when the operator wants to simulate to syslog and NO syslog
    destination exists yet (the zero-destinations cold start). The first
    syslog destination created is marked the type default, so a later bare
    "simulate ..." auto-routes to it.

    Args:
        name: operator-facing handle (must be unique).
        host: syslog target host or IP (e.g. the XSIAM broker IP).
        port: syslog target port (e.g. 514).
        protocol: 'udp' or 'tcp'. NOT 'tls' — TLS syslog carries a
            client-key secret, so direct the operator to the
            /log-destinations UI for that.

    Returns the created destination dict (secrets redacted), or {error}.
    """
    proto = (protocol or "udp").lower()
    if proto not in ("udp", "tcp"):
        return {
            "error": (
                f"protocol must be 'udp' or 'tcp' (got {protocol!r}). "
                "TLS syslog carries a client-key secret — add it in the "
                "/log-destinations UI; the agent only creates secretless "
                "syslog destinations."
            )
        }
    from usecase.log_destinations_store import get_log_destination_store
    s = get_log_destination_store()
    first_of_type = not s.list_all(type_id="syslog")
    try:
        dest = s.create(
            name=name,
            type_id="syslog",
            config={"host": str(host), "port": str(port), "protocol": proto},
            secrets={},
            is_default=first_of_type,
            description="Created via agent (secretless syslog).",
        )
    except ValueError as exc:
        return {"error": str(exc)}
    return dest.to_dict(include_secrets=False)
