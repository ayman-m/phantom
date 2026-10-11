# Phantom — Architecture

Two views: deployment topology and runtime data flow. All diagrams are mermaid — render in GitHub directly or `npx @mermaid-js/mermaid-cli -i this.md -o this.svg` for offline copies.

---

## 1. Deployment topology

The shape that defines what's where, what talks to what, and which trust boundary each component lives in.

```mermaid
flowchart LR
  subgraph Operator["Operator workstation"]
    Browser["Browser"]
  end

  subgraph MachineA["Machine A (slim)<br/>or Single host (all-in-one)"]
    direction TB
    subgraph PA["phantom-agent container<br/>(one image, two processes)"]
      Next["Next.js UI<br/>:3000"]
      MCP["Embedded MCP<br/>Python + FastMCP<br/>:8080"]
      Next -. localhost .-> MCP
    end
    Vol1[("phantom_mcp_data<br/>sqlite stores")]
    Vol2[("phantom_mcp_skills<br/>skills library")]
    Bind[/".phantom-agent/<br/>setup.json + .env.generated"/]
    PA --- Vol1
    PA --- Vol2
    PA --- Bind
  end

  subgraph MachineB["Machine B (slim only)<br/>or same host (all-in-one)"]
    XLog["xlog<br/>FastAPI + Strawberry GraphQL<br/>:8000"]
    Caldera["caldera<br/>MITRE Caldera 5.3.0<br/>:8888 :8443"]
  end

  subgraph External["External SaaS"]
    XSIAM["XSIAM tenant<br/>PAPI + webhook"]
    Vertex["Google Vertex AI<br/>Gemini chat + embeddings"]
  end

  Browser -- "https / 3000" --> Next
  MCP -- "HTTP" --> XLog
  MCP -- "HTTP / HTTPS" --> Caldera
  MCP -- "HTTPS / PAPI bearer" --> XSIAM
  MCP -- "HTTPS / SA JWT" --> Vertex
  Next -- "HTTPS / Gemini API key or SA" --> Vertex
```

**Reading guide.**

- The dashed line between Next.js and MCP is `localhost` only — they live in the **same container**, share the same trust boundary. The MCP is part of the agent's image, not a sibling service. This is per the spark-agents v1.2 bundle spec and what makes the slim split-deploy bundle viable (one image to ship).
- The two compose recipes in the repo correspond to two arrangements of this diagram:
  - `docker-compose.yml` — Machine A and Machine B collapse into the same Docker network on one host (all-in-one).
  - `docker-compose.agent-only.yml` — Machine A only; Machine B is operated by another team and reached via HTTP at the URLs the operator types into the setup form.
- Volumes (`phantom_mcp_data`, `phantom_mcp_skills`) survive container restarts AND `docker compose down`. Drop them only with `down -v` (destructive). The `./.phantom-agent/` bind-mount holds the setup form's submitted values.

---

## 2. Runtime data flow

What happens between "operator types a chat message" and "agent makes a connector tool call".

```mermaid
sequenceDiagram
  autonumber
  participant Op as Operator (browser)
  participant UI as Next.js UI
  participant MCP as Embedded MCP
  participant Vertex as Vertex / Gemini
  participant Conn as Connector (caldera/xsiam/xlog)
  participant Audit as Audit log
  participant Mem as Memory + KB

  Op->>UI: Send chat message
  UI->>MCP: POST /api/v1/sessions (append message)
  MCP->>Audit: record(action="session_message_appended")
  UI->>MCP: POST /api/v1/context (assemble per-turn context)
  MCP->>Mem: search(query, scope, k)
  Mem-->>MCP: top-k memories + KB chunks
  MCP-->>UI: assembled context (within budgetTokens)
  UI->>Vertex: chat(messages + context, tools=[...])
  Vertex-->>UI: tool_use suggestion
  UI->>MCP: JSON-RPC: call_tool("caldera/start_operation", {...})
  MCP->>MCP: approvals gate (if humanRequired)
  MCP->>Conn: HTTP request with resolved secrets
  Conn-->>MCP: response
  MCP->>Audit: record(action="tool_call", target="tool:caldera.start_operation")
  MCP->>Mem: optional memory write
  MCP-->>UI: tool_result
  UI->>Vertex: continuation with tool_result
  Vertex-->>UI: final response
  UI->>MCP: POST /api/v1/sessions (append assistant message)
  UI-->>Op: render
```

**Key invariants.**

- **Secret resolution at tool-call time.** The MCP holds only paths in its sqlite stores (`/secrets/agents/...`); the SecretStore is a mode-0700 file-backed vault. Secrets resolve from path → value at the moment a connector tool fires, never earlier. This is what makes the audit log safe to query even with admin token: there are no plaintext secrets anywhere in queryable storage.
- **Audit trail.** Every state change leaves a row. The audit table is append-only at the storage layer (no DELETE/UPDATE in `SqliteAuditLog`). Even with admin token, an operator can't tamper with the log via HTTP.
- **Approvals gate.** Tools listed in `manifest.approvals.humanRequired` block on `asyncio.Event` until the operator decides via `/api/v1/approvals/{id}/resolve`. The bus's boot-time orphan reaper marks zombie pending rows from a prior process as `STATUS_TIMEOUT`.
- **Cognitive layer.** Sessions (episodic), memory (semantic), and context (per-turn working memory) are wired together via the `ContextAssembler`. Embeddings flow through `VertexEmbedder` (text-embedding-004) when configured, falling back to a deterministic `TextHashEmbedder` when no Vertex provider instance exists.
- **Cron pipeline.** Scheduled jobs go through the same `fastmcp.Client(mcp)` dispatch path as agent-driven calls. The args block validates against the tool's Pydantic schema; mismatches surface as `job_failed` audit rows with the exact validation error.

---

## Capability inventory

For a flat list of "which spec capability is implemented where":

| Capability | Storage | API | Spec ref |
|---|---|---|---|
| Audit log | `audit.db` (append-only) | `/api/v1/audit*` | §6.10 row 14 |
| Approvals | `approvals.db` + asyncio | `/api/v1/approvals*` | §6.10 row 15 |
| Secrets | mode-0700 file vault | (resolved at tool-call) | §6.10 row 17 |
| Instances | `instances.db` (paths only) | `/api/v1/instances` | §7.5 |
| Providers | `provider_instances.db` (paths only) | `/api/v1/providers` | §7.6 |
| Sessions | `sessions.db` + `messages.db` | `/api/v1/sessions` | §6.10 sessions |
| Memory | `memory.db` (vec search, brute-force) | `/api/v1/memories` | §6.10 memory |
| Context | (in-process assembler) | `/api/v1/context` | §6.10 context |
| Knowledge | `kb.db` (per KB, hybrid search) | `/api/v1/kbs*` | §6.10 knowledge |
| Jobs | `jobs.db` + croniter | `/api/v1/jobs` | §6.10 jobs |
| Settings | `settings.db` (override layer) | `/api/v1/settings` | manifest.settings |
| API keys | `api_keys.db` (sha256 hashes) | `/api/v1/api_keys*` | external integration |
| Notifications | `notifications.db` + topic catalog | `/api/v1/notifications*` | manifest.notifications |
| Telemetry | `telemetry.db` (opt-in) | `/api/v1/telemetry*` | manifest.telemetry |
| Media | `media.db` + `<data_root>/media/<id>/` | `/api/v1/media*` | manifest.media |
| Metrics | in-process Prometheus registry | `/api/v1/metrics` | manifest.observability.metrics |
| A2UI streaming | bundled JSONL surfaces | `/api/v1/ui/*` | A2UI v0.8 |
