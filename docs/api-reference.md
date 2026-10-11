# Phantom — API Reference

The embedded MCP exposes admin + integration HTTP routes at `/api/v1/*` on port `8080`. All routes require `Authorization: Bearer <token>` unless otherwise noted, where `<token>` is either:

- **MCP_TOKEN** — bundle-internal admin token. Generated at container start (or pinned in `.env`). The Next.js UI uses this for every internal call.
- **API key** (`phantom_ak_<id>_<secret>`) — operator-minted, scoped, revocable. See `/api/v1/api_keys` to mint.

Routes that are intentionally unauthenticated (Prometheus exposition, MCP JSON-RPC entrypoint) are marked **(unauth)**.

> **Schema convention**: all responses are `application/json` unless noted. Errors return `{"error": "..."}` with the appropriate status code.

---

## Setup + first-run

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/setup` | Return the bundle's setup schema (connectors, providers, settings, secret slots). Drives the first-run form. |
| `POST` | `/api/v1/setup` | Materialize connector + provider instances from operator-supplied values. Body: `{"values": {...}, "replace": true}`. |

## Connector instances

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/instances` | List all materialized connector instances. |
| `POST` | `/api/v1/instances` | Create a new instance manually. |
| `DELETE` | `/api/v1/instances/{id}` | Delete an instance and its secret refs. |

## Provider instances + models

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/providers` | List provider instances (Vertex, etc.). |
| `POST` | `/api/v1/providers` | Create a new provider instance. |
| `DELETE` | `/api/v1/providers/{id}` | Delete a provider instance. |
| `GET` | `/api/v1/models` | Active model catalog merged from all provider instances. |

## Settings (manifest.settings runtime overrides)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/settings` | `{defaults, overridable, effective, overrides}` snapshot. |
| `PUT` | `/api/v1/settings` | Bulk set/clear: body `{"updates": {key: value}, "clear": [keys], "actor": "id"}`. Returns 207 if some keys rejected. Audit-logged. |

## API keys (external integrations)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/api_keys` | List active + revoked keys (admin: requires MCP_TOKEN, not API keys). |
| `POST` | `/api/v1/api_keys` | Mint. Body `{"label": "siem-poller", "scopes": ["audit:read"], "actor": "operator"}`. **Plaintext is returned ONCE** in `key` field, never recoverable. |
| `DELETE` | `/api/v1/api_keys/{key_id}` | Revoke. Idempotent. Audit-logged. |

## Audit log (append-only)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/audit` | Filter by `?action`, `?actor`, `?target`, `?target_prefix`, `?since`, `?until`, `?limit`, `?offset`. |
| `GET` | `/api/v1/audit/summary` | Counts-by-action posture rollup. |

## Approvals (async cross-loop signaling)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/approvals` | List pending + resolved approval requests. |
| `POST` | `/api/v1/approvals/{id}/resolve` | Operator decision. Body `{"decision": "approve"|"deny", "actor": "id"}`. Wakes the awaiting tool call. |

## Cognitive layer (sessions + memory + context)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/sessions` | List sessions with message counts. |
| `POST` | `/api/v1/sessions` | Create a new session (or append a message to an existing one). |
| `DELETE` | `/api/v1/sessions/{id}` | Delete a session and its message history. |
| `GET` | `/api/v1/memories` | Search/list semantic memories (`?q`, `?scope`, `?limit`). |
| `POST` | `/api/v1/memories` | Upsert a memory (key/value with optional TTL). |
| `DELETE` | `/api/v1/memories/{id}` | Delete a memory. |
| `POST` | `/api/v1/context` | Assemble per-turn context within `manifest.context.budgetTokens`. |

## Knowledge bases (read-only)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/kbs` | List ingested KBs from `bundles/spark/kbs/`. |
| `GET` | `/api/v1/kbs/{kb}/search` | Vector + BM25 hybrid search over a KB (`?q`, `?limit`). |

## Jobs (manifest.jobs[] cron)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/jobs` | List declared jobs with their cron expressions, last fire status, next fire time. |

## Notifications (manifest.notifications.topics)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/notifications/topics` | The bundle's declared topic catalog. |
| `GET` | `/api/v1/notifications` | List dispatched notifications. `?target=user:operator&unread=true&limit=100`. |
| `GET` | `/api/v1/notifications/unread_count` | Integer count, optionally filtered by target. |
| `POST` | `/api/v1/notifications` | Publish. Body `{"topic": "...", "payload": {...}, "actor": "id"}`. Topic must be declared in the manifest. |
| `POST` | `/api/v1/notifications/{id}/ack` | Mark read. |

**Channel webhook fan-out**: topics with `target: "channel:<name>"` get POSTed
to operator-supplied webhook URLs from env vars. Convention: hyphens become
underscores, name is uppercased.

| Manifest target | Env var |
|---|---|
| `channel:soc` | `PHANTOM_NOTIFICATION_CHANNEL_SOC` |
| `channel:purple-team` | `PHANTOM_NOTIFICATION_CHANNEL_PURPLE_TEAM` |

The dispatcher POSTs JSON `{topic, severity, target, id, created_at, payload}` to the URL.
Channels with no URL configured skip silently (`dispatch_status="failed"`,
`dispatch_error="no webhook URL configured..."`); the notification still
persists for operator review.

## Telemetry (opt-in usage counters)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/telemetry` | `{enabled, declared_events, total_recorded, counts_by_event}`. |
| `POST` | `/api/v1/telemetry/enable` | Toggle. Body `{"enabled": true|false, "actor": "id"}`. Privacy-by-default OFF on first boot. |
| `POST` | `/api/v1/telemetry/record` | Record one event. Body `{"event": "<name>", "count": 1, "payload": {...}}`. Events must be declared in `manifest.telemetry.events`. |
| `GET` | `/api/v1/telemetry/daily` | Per-day buckets. `?event=<name>&days=30`. |

## Media uploads

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/media` | Multipart form upload (`file`, optional `actor`). Returns metadata + extraction status. 413 if over `manifest.media.uploadMaxMb`. |
| `GET` | `/api/v1/media` | Paginated metadata list (`?limit`, `?offset`). |
| `GET` | `/api/v1/media/{id}` | Single metadata + extracted text. |
| `GET` | `/api/v1/media/{id}/raw` | Original bytes (FileResponse). |
| `DELETE` | `/api/v1/media/{id}` | Remove file + metadata. Audit-logged. |

## Update introspection (manifest.update)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/update/info` | Current image + commit + bundle build provenance, plus the manifest's `update` block (`channel`, `registryUrl`, `autoUpdate`). When `autoUpdate: false` (the bundle's default), returns operator-readable guidance for manual upgrades (`docker compose pull && up -d --force-recreate`). Auto-update polling itself is documented future work — this endpoint makes the deploy's update posture inspectable today. |

## Observability — metrics

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/metrics` | **(unauth)** Prometheus 0.0.4 text exposition. Counters/gauges/histograms for tool calls, HTTP requests, manifest-declared metrics. |
| `GET` | `/api/v1/metrics/snapshot` | JSON `{name: kind}` for the agent UI's debug panel. |

## A2UI v0.8 surface streaming

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/ui/manifest` | Bundle's UI manifest (entry surface, catalogs). |
| `GET` | `/api/v1/ui/catalogs/{name}` | A2UI component catalog. |
| `GET` | `/api/v1/ui/surfaces/{name}` | JSONL stream for a surface (one A2UI op per line). |

## MCP JSON-RPC

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/stream/mcp` | **(unauth bearer for tool calls; auth via `MCP_TOKEN` header for admin tools)** FastMCP streamable-http transport. Tools advertised here only when their connector instance is materialized. |
| `GET` | `/ping/` | **(unauth)** Liveness probe used by the container healthcheck. |

---

## Audit events

The append-only `audit_events` table records every state change. Per `manifest.audit.events`, the recognized event names are:

| Event | When | Target |
|---|---|---|
| `tool_call` | Every MCP tool dispatch | `tool:<connector>.<name>` |
| `simulation_created` | Worker created via xlog | `simulation:<id>` |
| `scenario_started` | Scenario worker started | `scenario:<name>` |
| `caldera_operation_created` | Red-team op launched | `operation:<id>` |
| `detection_validation_recorded` | Detection check completed | `validation:<id>` |
| `coverage_report_generated` | Coverage report produced | `report:<id>` |
| `setup_completed` | Setup form submitted successfully | `setup` |
| `settings_changed` | `/api/v1/settings PUT` | `setting:<key>` |
| `instance_created` | Connector instance materialized | `instance:<id>` |
| `approval_requested` / `approval_resolved` | Approval gate transitions | `approval:<id>` |
| `job_registered` / `job_fired` / `job_completed` / `job_failed` | Cron lifecycle | `job:<name>` |
| `api_key_created` / `api_key_revoked` | API key lifecycle | `api_key:<id>` |
| `notification_published` | Notification dispatched | `notification:<id>` |
| `telemetry_toggled` | Operator enabled/disabled telemetry | `telemetry:state` |
| `media_uploaded` / `media_deleted` | Media file lifecycle | `media:<id>` |

Filter by event name with `?action=settings_changed`, by target prefix with `?target_prefix=tool:`, etc.

---

## Curated tool catalog

The `bundles/tool-catalog.yaml` enumerates the curated tools. The live MCP advertises a tool ONLY when its connector has at least one materialized instance (objective 5). To inspect what's currently live:

```bash
curl http://localhost:8080/api/v1/setup -H "Authorization: Bearer $MCP_TOKEN" | jq
```

Or run the bundled snapshot generator:

```bash
python3 scripts/generate_mcp_tool_snapshot.py --output /tmp/snapshot.json
python3 scripts/validate_tool_snapshot.py --catalog bundles/tool-catalog.yaml --snapshot /tmp/snapshot.json
```

---

## Versioning

The spec version this implements is **spark-agents v1.2** (see `bundles/spark/manifest.yaml`'s `schemaVersion`). Future bundle versions may add or rename routes; the agent UI's runtime config (`mcp/agent/lib/runtime-config.ts`) is the source of truth for the routes the UI actually depends on.
