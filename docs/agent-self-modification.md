# Agent self-modification

What the agent may change about its own runtime from chat, what it may never touch, and how an operator decision is required when the bundle asks for one. Self-modification covers operator-visible runtime data (jobs, settings, persona, skills, notifications, log destinations) and marketplace catalog state. It never covers credentials or the bundle itself.

## Boundaries

| Category | Examples | Agent access |
|---|---|---|
| **Credential** | provider credentials, per-instance secrets, API-key plaintext, UI password | **None.** No MCP tool reads or writes them. REST-only, for the operator UI. |
| **Catalog** | marketplace install state, connector schemas, registry membership | Read and write through the catalog tools. |
| **Runtime data** | jobs, settings, persona, skills, notifications, secretless syslog destinations | Read and write through the tools below. |
| **Bundle** | manifest, system prompt, `tools.allow` / `tools.deny`, `approvals.humanRequired` | **None.** Immutable at runtime. |

The credential rule is the root `CLAUDE.md` guardrail. Before adding a tool, ask whether it reads or writes a SecretStore value; if it does, it stays REST-only.

## Tool families

All are registered in `_BUILTIN_LEGACY_TOOLS` in `bundles/spark/mcp/src/usecase/connector_loader.py` and implemented in `usecase/builtin_components/self_mod_tools.py`.

- **Read (no gate in the tool code):** `jobs_list`, `jobs_get`, `jobs_runs`, `settings_get`, `personality_get`, `instances_list`, `instances_get`, `providers_list`, `providers_get`, `log_destinations_list`, `log_destinations_get`, `approvals_list_pending`, `approvals_list_history`, `notifications_list`, `notifications_unread_count`, `audit_search`, `audit_recent`, `api_keys_list`, `manifest_get`, `metrics_snapshot`, `health_status`. Instance, provider and API-key reads return metadata with every secret redacted as `***`.
- **Routine writes:** `jobs_create`, `jobs_update`, `jobs_run_now`, `personality_update`, `personality_patch`, `settings_update`, `notifications_dismiss`, `notifications_dismiss_all`, `approvals_resolve`, and `log_destinations_create` (secretless syslog destinations only; secret-bearing types are rejected by the tool).
- **Destructive:** `jobs_delete`, `skills_delete`, `personality_reset`, `settings_reset`.
- **Skills:** `skills_create` and `skills_update` call the skills store directly and are never gated.
- **Batch:** `agent_batch_propose` runs N actions under one approval; the nested calls are audit-only. It never runs a credential-side tool (see below), and it excludes itself and `approvals_resolve`.
- **Catalog:** `marketplace_list`, `marketplace_install`, `marketplace_uninstall`, `connector_upload`.

## What the agent cannot do

- Create, update or delete providers or connector instances (they carry secrets): `providers_*` writes and `instances_*` writes do not exist as tools.
- Mint, rotate or revoke API keys.
- Create secret-bearing log destinations (TLS syslog, XSIAM HTTP, Splunk HEC); the operator does that in the UI.
- Edit the manifest, the system prompt template, `tools.allow`, `tools.deny` or `approvals.humanRequired`. `manifest_set`, `manifest_update`, `system_prompt_update`, `tools_allow_update`, `tools_deny_update` and `approvals_humanrequired_update` are listed in `tools.deny` so a bundle author cannot enable them either.
- Approve its own request (see below).

## Approvals

Approval gating is **list-driven and off by default**. A tool gates on a human decision only if its name appears in `approvals.humanRequired[]` in `bundles/spark/manifest.yaml`. The shipped list is empty. Entries match a bare name, a namespaced name (`<connector>.<name>`) or a legacy alias, and take effect at MCP boot with no code change. The reference list is kept in the manifest as `humanRequired__DISABLED`. With gating off, every call still writes an `agent_self_mod_*` audit event.

When a gate-capable tool is listed (every state-changing tool in `self_mod_tools.py` routes through `gate_and_execute`; the read tools and `skills_create` / `skills_update` do not):

1. The tool call creates a row with `bus.request(actor="agent", risk_tier=...)` and blocks on `bus.wait_async`. `risk_tier` is `soft` or `destructive` for the tools above.
2. The chat route notices the pending row, emits an `approval_pending` SSE event, and the UI renders an inline approval card (`mcp/agent/lib/approvals-config.ts` classifies the tier for card styling).
3. The operator approves or denies in the card or at `/api/v1/approvals/{id}/resolve`; the tool call then runs or returns a denial.

Invariants:

- **No self-approval.** `InProcessApprovalsBus.resolve` raises `ApprovalSelfResolveError` when the resolver equals the requester, whatever path created the request.
- **Per-caller bypass.** A job may set `bypass_approvals: true` and a chat session `approval_mode: bypass`. The call runs immediately and records an `auto_approved` audit row. Bypass does not cover `jobs_create` itself.
- **Gating never widens credential reach.** The credential boundary above holds with gating on or off.
- **One list of credential-side tools.** `usecase/credential_guardrail.py` names them (`providers_*`, `instances_*` and `api_keys_*` writes). The tool catalogue fails closed at import if one is registered. The batch tool builds its table without them and refuses any action that names one, bare or namespaced. The job scheduler's tool dispatcher refuses them too, so a `tool_call` job cannot name one either. Tests: `bundles/spark/mcp/tests/test_credential_guardrail.py`.

## Implementation map

| Concern | Location |
|---|---|
| Tool registration and the credential guardrail comment | `bundles/spark/mcp/src/usecase/connector_loader.py` |
| Canonical credential-side tool names | `bundles/spark/mcp/src/usecase/credential_guardrail.py` |
| Tool bodies, gate helper | `bundles/spark/mcp/src/usecase/builtin_components/self_mod_tools.py` |
| Approvals bus and `ApprovalSelfResolveError` | `bundles/spark/mcp/src/usecase/approvals_bus.py` |
| Gate list, `tools.allow` / `tools.deny` | `bundles/spark/manifest.yaml` |
| Chat-route SSE event and card tier | `mcp/agent/app/api/chat/route.ts`, `mcp/agent/lib/approvals-config.ts` |
