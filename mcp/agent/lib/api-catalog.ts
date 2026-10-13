/**
 * API endpoint catalog — the single source of truth for the
 * /help/api documentation page, the try-it-out tool, and the
 * generated OpenAPI 3.0 spec.
 *
 * Conventions:
 *   - `path` is the agent-side proxy path (`/api/agent/<route>`),
 *     since that's what operators invoke from outside the bundle.
 *     The proxy attaches MCP_TOKEN server-side and forwards to
 *     `/api/v1/<route>` on the embedded MCP. Documenting the agent
 *     side means callers don't have to know about MCP_TOKEN at all.
 *   - Categories mirror the operator's mental model: Cognitive
 *     (what the agent knows), Configuration (what it acts on),
 *     Operations (what it runs), Self-Modification (the approval-gated
 *     surface), Observability, Identity, Reports, Workflows.
 *   - Each entry carries enough metadata to (a) render a detail
 *     page with sample request/response, (b) drive the try-it-out
 *     form, and (c) generate the OpenAPI 3.0 path object.
 *
 * Adding a new endpoint:
 *   1. Pick or add a category.
 *   2. Append an ApiEndpoint with the path, method, params, and a
 *      runnable example. The detail page form auto-generates from
 *      the params + body schema.
 *   3. The /api/agent/openapi route picks it up automatically.
 */

export type ApiCategory =
  | "cognitive"
  | "configuration"
  | "operations"
  | "self-modification"
  | "observability"
  | "identity"
  | "reports"
  | "workflows";

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface ParamSpec {
  name: string;
  /** OpenAPI primitive: string | integer | boolean | number | array | object */
  type: string;
  description: string;
  required?: boolean;
  /** Default value shown as the placeholder in the try-it-out form. */
  example?: string | number | boolean;
  /** When the param is an enum, list valid values. */
  enum?: string[];
}

export interface BodySpec {
  /** Always JSON for our REST surface. */
  contentType: "application/json";
  /** A small JSON schema fragment (object / properties / required). */
  schema: Record<string, unknown>;
  /** A complete, valid example body. */
  example: Record<string, unknown>;
}

export interface ResponseSpec {
  /** HTTP status — "200" / "404" / etc. */
  status: string;
  description: string;
  /** Truncated representative response body for docs. */
  example?: unknown;
}

export interface ApiEndpoint {
  /** Slug for /help/api/[id]. Stable across renames. */
  id: string;
  category: ApiCategory;
  method: HttpMethod;
  /** Agent-side path, e.g. /api/agent/jobs/{jobName}/runs */
  path: string;
  summary: string;
  description: string;
  pathParams?: ParamSpec[];
  queryParams?: ParamSpec[];
  body?: BodySpec;
  responses: ResponseSpec[];
  /** Self-modification risk tier when this endpoint mutates state. Drives
   * the try-it-out warning banner color. Reads have no tier. */
  riskTier?: "soft" | "destructive" | "credential";
  /** True if invoking this endpoint requires operator approval at
   * the MCP-side gate (manifest.approvals.humanRequired[]). The
   * try-it-out UI surfaces this so operators don't get surprised. */
  requiresApproval?: boolean;
  /** OpenAPI tags for grouping in spec consumers. Defaults to category. */
  tags?: string[];
}

export const CATEGORY_META: Record<
  ApiCategory,
  { label: string; icon: string; description: string; color: string }
> = {
  cognitive: {
    label: "Cognitive",
    icon: "psychology",
    description: "Memory, knowledge bases, and chat sessions.",
    color: "primary",
  },
  configuration: {
    label: "Configuration",
    icon: "settings",
    description: "Runtime settings, persona, connector + provider instances, manifest.",
    color: "tertiary",
  },
  operations: {
    label: "Operations",
    icon: "schedule",
    description: "Scheduled jobs, run history, audit trail, notifications.",
    color: "primary",
  },
  "self-modification": {
    label: "Self-Modification",
    icon: "auto_fix_high",
    description: "Approvals lifecycle — what the agent has requested and what's pending.",
    color: "secondary",
  },
  observability: {
    label: "Observability",
    icon: "monitoring",
    description: "Health, metrics, embedder mode, request log.",
    color: "secondary",
  },
  identity: {
    label: "Identity & Access",
    icon: "vpn_key",
    description: "API keys — list, mint, rotate, revoke.",
    color: "error",
  },
  reports: {
    label: "Reports",
    icon: "description",
    description: "Coverage reports, simulation exports.",
    color: "primary",
  },
  workflows: {
    label: "Workflows",
    icon: "account_tree",
    description: "A2UI workflows + model catalog.",
    color: "tertiary",
  },
};

// ─────────────────────────────────────────────────────────────────
// COGNITIVE — memory, knowledge, sessions
// ─────────────────────────────────────────────────────────────────

const COGNITIVE: ApiEndpoint[] = [
  {
    id: "memory-list",
    category: "cognitive",
    method: "GET",
    path: "/api/agent/memory",
    summary: "List memory entries",
    description:
      "Return the agent's stored memories, optionally filtered by scope. " +
      "Memory rows are operator-curated facts about the org (tech stack, " +
      "past simulations, validated detections) that the agent recalls via " +
      "semantic search across sessions.",
    queryParams: [
      {
        name: "scope",
        type: "string",
        description: "Filter to one scope: agent | session:<id> | user | system.",
        example: "agent",
      },
      {
        name: "limit",
        type: "integer",
        description: "Max rows (1-500). Default 100.",
        example: 50,
      },
    ],
    responses: [
      {
        status: "200",
        description: "List of memory rows.",
        example: {
          memories: [
            {
              id: "m_8a3b…",
              key: "tech_stack:firewall",
              value: "Fortinet FortiGate (CEF, SYSLOG)",
              scope: "agent",
              created_at: "2026-04-12T08:00:00Z",
            },
          ],
          count: 1,
        },
      },
    ],
  },
  {
    id: "memory-search",
    category: "cognitive",
    method: "POST",
    path: "/api/agent/memory/search",
    summary: "Semantic search over memory",
    description:
      "Cosine-similarity search via the configured embedder " +
      "(VertexEmbedder / text-embedding-004 by default). Returns ranked " +
      "memory rows matching the natural-language query.",
    body: {
      contentType: "application/json",
      schema: {
        type: "object",
        required: ["query"],
        properties: {
          query: { type: "string", description: "Natural-language query." },
          limit: { type: "integer", description: "Top-K (1-100). Default 5." },
          scope: { type: "string", description: "Optional scope filter." },
        },
      },
      example: {
        query: "What firewall vendor are we using?",
        limit: 5,
        scope: "agent",
      },
    },
    responses: [
      {
        status: "200",
        description: "Ranked memory rows with cosine score.",
        example: {
          results: [
            {
              key: "tech_stack:firewall",
              value: "Fortinet FortiGate (CEF, SYSLOG)",
              score: 0.811,
            },
          ],
          count: 1,
        },
      },
    ],
  },
  {
    id: "memory-by-key",
    category: "cognitive",
    method: "GET",
    path: "/api/agent/memory/{key}",
    summary: "Get a memory by key",
    description: "Phantom keys memory rows by `key` per (key, scope). The path-param `key` carries the URL-encoded key.",
    pathParams: [
      { name: "key", type: "string", description: "URL-encoded memory key.", example: "tech_stack:firewall" },
    ],
    queryParams: [
      { name: "scope", type: "string", description: "Defaults to 'agent'.", example: "agent" },
    ],
    responses: [
      { status: "200", description: "Memory row." },
      { status: "404", description: "Key not found in scope." },
    ],
  },
  {
    id: "memory-delete",
    category: "cognitive",
    method: "DELETE",
    path: "/api/agent/memory/{key}",
    summary: "Delete a memory by key",
    description: "Permanently removes the row identified by (key, scope).",
    pathParams: [
      { name: "key", type: "string", description: "URL-encoded key.", example: "tech_stack:firewall" },
    ],
    queryParams: [
      { name: "scope", type: "string", description: "Default 'agent'.", example: "agent" },
    ],
    responses: [
      { status: "200", description: "Deleted." },
      { status: "404", description: "Key not found." },
    ],
    riskTier: "destructive",
  },
  {
    id: "knowledge-list",
    category: "cognitive",
    method: "GET",
    path: "/api/agent/knowledge",
    summary: "List loaded knowledge bases",
    description: "Per-KB summary: name, doc_count, latest_loaded_at. KBs are bundle-shipped reference content.",
    responses: [
      {
        status: "200",
        description: "List of KBs.",
        example: {
          kbs: [
            { name: "phantom-soc", doc_count: 3, latest_loaded_at: "2026-04-29T09:07:42Z" },
            { name: "xql-examples", doc_count: 161, latest_loaded_at: "2026-05-01T08:24:09Z" },
          ],
          count: 2,
        },
      },
    ],
  },
  {
    id: "knowledge-docs",
    category: "cognitive",
    method: "GET",
    path: "/api/agent/knowledge/{name}/docs",
    summary: "List documents in a KB",
    description: "Browse view — content omitted. Fetch a single doc via /docs/{doc_id} for the full body.",
    pathParams: [
      { name: "name", type: "string", description: "KB name.", example: "xql-examples" },
    ],
    queryParams: [
      { name: "limit", type: "integer", description: "Max rows (1-500). Default 100.", example: 100 },
      { name: "offset", type: "integer", description: "Pagination offset.", example: 0 },
      { name: "category", type: "string", description: "Filter by schema category.", example: "detection" },
    ],
    responses: [
      { status: "200", description: "List of docs (no content)." },
      { status: "404", description: "Unknown KB name." },
    ],
  },
  {
    id: "knowledge-doc-get",
    category: "cognitive",
    method: "GET",
    path: "/api/agent/knowledge/{name}/docs/{doc_id}",
    summary: "Fetch one knowledge document",
    description: "Returns the full doc with content and metadata. Audited.",
    pathParams: [
      { name: "name", type: "string", description: "KB name.", example: "xql-examples" },
      { name: "doc_id", type: "string", description: "Document ID.", example: "XQL-001-bbfbd1c9" },
    ],
    responses: [
      { status: "200", description: "Document with content + metadata." },
      { status: "404", description: "Doc not found in KB." },
    ],
  },
  {
    id: "knowledge-search",
    category: "cognitive",
    method: "POST",
    path: "/api/agent/knowledge/{name}/search",
    summary: "Semantic search within a KB",
    description: "Cosine search via the same embedder as memory_search. Filter by category, tighten with min_score.",
    pathParams: [
      { name: "name", type: "string", description: "KB name.", example: "xql-examples" },
    ],
    body: {
      contentType: "application/json",
      schema: {
        type: "object",
        required: ["query"],
        properties: {
          query: { type: "string" },
          limit: { type: "integer", description: "Default 5." },
          category: { type: "string", description: "Optional schema-category filter." },
          min_score: { type: "number", description: "Hide results below this cosine threshold." },
        },
      },
      example: { query: "C2 beaconing detection", limit: 5 },
    },
    responses: [
      { status: "200", description: "Ranked docs with cosine score." },
      { status: "400", description: "Empty / missing query field." },
      { status: "404", description: "Unknown KB name." },
    ],
  },
  {
    id: "sessions-list",
    category: "cognitive",
    method: "GET",
    path: "/api/agent/sessions",
    summary: "List chat sessions",
    description: "Newest first. Used by the chat sidebar.",
    queryParams: [
      { name: "user", type: "string", description: "Filter to one user.", example: "operator" },
      { name: "limit", type: "integer", description: "Default 20.", example: 20 },
      { name: "active_only", type: "boolean", description: "Hide ended sessions.", example: false },
    ],
    responses: [{ status: "200", description: "Sessions newest first." }],
  },
  {
    id: "sessions-create",
    category: "cognitive",
    method: "POST",
    path: "/api/agent/sessions",
    summary: "Create a chat session",
    description: "Used by the chat route at the start of each new conversation.",
    body: {
      contentType: "application/json",
      schema: {
        type: "object",
        properties: {
          user: { type: "string" },
          title: { type: "string" },
          meta: { type: "object" },
        },
      },
      example: { user: "operator", title: null, meta: {} },
    },
    responses: [{ status: "201", description: "Session created." }],
  },
  {
    id: "sessions-get",
    category: "cognitive",
    method: "GET",
    path: "/api/agent/sessions/{sessionId}",
    summary: "Fetch a session header + ordered messages",
    description: "Body shape: {session, messages: [{role, content, ...}]}.",
    pathParams: [{ name: "sessionId", type: "string", description: "Session UUID.", example: "s_abc…" }],
    responses: [
      { status: "200", description: "Session + messages." },
      { status: "404", description: "Session not found." },
    ],
  },
  {
    id: "sessions-end",
    category: "cognitive",
    method: "POST",
    path: "/api/agent/sessions/{sessionId}/end",
    summary: "Mark a session as ended",
    description: "Sessions stay browsable but no new messages can be appended. Idempotent.",
    pathParams: [{ name: "sessionId", type: "string", description: "Session UUID." }],
    responses: [{ status: "200", description: "Ended." }],
    riskTier: "soft",
  },
  {
    id: "sessions-export",
    category: "cognitive",
    method: "GET",
    path: "/api/agent/sessions/{sessionId}/export",
    summary: "Export a session as JSON or markdown",
    description: "Format defaults to JSON; pass ?format=markdown for a human-readable transcript.",
    pathParams: [{ name: "sessionId", type: "string", description: "Session UUID." }],
    queryParams: [
      { name: "format", type: "string", enum: ["json", "markdown"], example: "markdown", description: "Output format." },
    ],
    responses: [{ status: "200", description: "Transcript." }],
  },
  // ─── cognitive entries ───
  {
    id: "sessions-by-sessionId-fork-post",
    category: "cognitive",
    method: "POST",
    path: "/api/agent/sessions/{sessionId}/fork",
    summary: "Fork a chat session (branch from a prior message)",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "sessions-by-sessionId-messages",
    category: "cognitive",
    method: "GET",
    path: "/api/agent/sessions/{sessionId}/messages",
    summary: "List messages in a chat session",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "sessions-by-sessionId-messages-post",
    category: "cognitive",
    method: "POST",
    path: "/api/agent/sessions/{sessionId}/messages",
    summary: "Append a message to a chat session",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "skills",
    category: "cognitive",
    method: "GET",
    path: "/api/skills",
    summary: "List skills",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "skills-delete",
    category: "cognitive",
    method: "DELETE",
    path: "/api/skills",
    summary: "Delete skills",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "skills-post",
    category: "cognitive",
    method: "POST",
    path: "/api/skills",
    summary: "Create skills",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "skills-put",
    category: "cognitive",
    method: "PUT",
    path: "/api/skills",
    summary: "Replace skills",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
];

// ─────────────────────────────────────────────────────────────────
// CONFIGURATION — settings, personality, instances, providers, manifest
// ─────────────────────────────────────────────────────────────────

const CONFIGURATION: ApiEndpoint[] = [
  {
    id: "settings-get",
    category: "configuration",
    method: "GET",
    path: "/api/agent/settings",
    summary: "Snapshot of runtime settings",
    description:
      "Returns {defaults, overridable, effective, overrides}. `defaults` come " +
      "from manifest.settings.defaults; `overrides` are operator-set values " +
      "in `<data_root>/settings.db`; `effective` is the merged view.",
    responses: [
      {
        status: "200",
        description: "Settings snapshot.",
        example: {
          defaults: { geminiModel: "gemini-3.1-pro-preview", defaultScenario: "dark_secrets" },
          overridable: ["geminiModel", "defaultScenario", "defaultLogFormat"],
          effective: { geminiModel: "gemini-3.1-pro-preview" },
          overrides: [],
        },
      },
    ],
  },
  {
    id: "settings-update",
    category: "configuration",
    method: "PUT",
    path: "/api/agent/settings",
    summary: "Bulk set / clear runtime overrides",
    description:
      "Set or clear keys in one call. Keys not in manifest.settings.overridable[] " +
      "are rejected with a per-key reason in the response.",
    body: {
      contentType: "application/json",
      schema: {
        type: "object",
        properties: {
          updates: { type: "object", description: "Key → value pairs to set." },
          clear: { type: "array", items: { type: "string" }, description: "Keys to revert." },
          actor: { type: "string", description: "Optional audit actor." },
        },
      },
      example: { updates: { geminiModel: "gemini-2.5-flash" }, clear: [], actor: "user:operator" },
    },
    responses: [
      { status: "200", description: "{ applied, cleared, rejected }." },
      { status: "400", description: "Malformed body." },
    ],
    riskTier: "soft",
  },
  {
    id: "personality-get",
    category: "configuration",
    method: "GET",
    path: "/api/agent/personality",
    summary: "Get the agent's persona document",
    description:
      "Single-row persona — operator-defined markdown plus the action policy. Stored in MCP-side personality.db; the agent's chat-route system instruction reads `personalityMd` into the prompt and uses `actionPolicy` for safety classification.",
    responses: [
      {
        status: "200",
        description: "Persona document.",
        example: {
          personality: {
            personalityMd: "# Phantom Personality\n\n- Reply concisely.\n- Cite simulation IDs when referencing operations.\n",
            actionPolicy: {
              askWhenUnsure: true,
              confirmLocalActions: "approve-card",
              confirmExternalActions: "off",
            },
          },
          updated_at: "2026-05-06T10:00:00Z",
          updated_by: "user:operator",
          version: 3,
        },
      },
    ],
  },
  {
    id: "personality-defaults",
    category: "configuration",
    method: "GET",
    path: "/api/agent/personality/defaults",
    summary: "Get the default persona document",
    description:
      "The bundle default (`personalityMd` plus `actionPolicy`), independent of what is stored. The personality page fills any key a stored blob lacks from it and uses it for Reset Defaults, so the page carries no copy of the defaults.",
    responses: [
      {
        status: "200",
        description: "Default persona document.",
        example: {
          personality: {
            personalityMd: "# Phantom Personality\n\nYou are Phantom, a continuous SOC simulation agent. ...\n",
            actionPolicy: {
              localCategories: ["jobs", "settings", "personality"],
              externalCategories: ["xlog", "caldera", "xsiam", "simulations", "http-sender", "wec-sender"],
              askWhenUnsure: true,
              confirmLocalActions: "approve-card",
              confirmExternalActions: "off",
            },
          },
        },
      },
    ],
  },
  {
    id: "personality-put",
    category: "configuration",
    method: "PUT",
    path: "/api/agent/personality",
    summary: "Replace the persona document",
    description:
      "Last-write-wins. Bumps version; previous version is preserved in personality_history. The agent prefers `personality_patch` for partial updates (atomic merge) — direct PUT requires sending the full blob.",
    body: {
      contentType: "application/json",
      schema: {
        type: "object",
        required: ["personality"],
        properties: {
          personality: { type: "object", description: "Full persona blob." },
          actor: { type: "string", description: "Audit actor." },
        },
      },
      example: {
        personality: {
          personalityMd: "# Phantom Personality\n\n- Reply in three bullets when possible.\n",
        },
        actor: "user:operator",
      },
    },
    responses: [
      { status: "200", description: "Updated row with new version." },
      { status: "400", description: "Body missing `personality` object." },
    ],
    riskTier: "soft",
  },
  {
    id: "instances-list",
    category: "configuration",
    method: "GET",
    path: "/api/agent/instances",
    summary: "List connector instances",
    description:
      "XSIAM, Caldera, Xlog config blobs. Secret values NEVER returned — only secret_refs paths.",
    queryParams: [
      { name: "connector_id", type: "string", description: "Filter to xsiam | caldera | xlog.", example: "xsiam" },
    ],
    responses: [{ status: "200", description: "Instance rows." }],
  },
  {
    id: "providers-list",
    category: "configuration",
    method: "GET",
    path: "/api/agent/providers",
    summary: "List materialized provider instances",
    description: "Secrets redacted (paths only). Used by /providers admin page.",
    responses: [{ status: "200", description: "Provider rows." }],
  },
  {
    id: "providers-config",
    category: "configuration",
    method: "POST",
    path: "/api/agent/providers/config",
    summary: "Materialize or update a provider instance",
    description:
      "Operator submits creds (Vertex JSON, etc). Secrets land in the SecretStore (encrypted via PHANTOM_SECRET_KEK); the row stores paths.",
    body: {
      contentType: "application/json",
      schema: {
        type: "object",
        required: ["provider_id", "config"],
        properties: {
          provider_id: { type: "string", example: "vertex" },
          name: { type: "string", example: "primary-vertex" },
          config: { type: "object" },
          secret_refs: { type: "object" },
        },
      },
      example: {
        provider_id: "vertex",
        name: "primary-vertex",
        config: { project_id: "my-project", region: "us-central1" },
        secret_refs: { serviceAccountJson: "<paste JSON>" },
      },
    },
    responses: [{ status: "201", description: "Materialized." }, { status: "400", description: "Validation failure." }],
    riskTier: "credential",
  },
  {
    id: "models-list",
    category: "configuration",
    method: "GET",
    path: "/api/agent/models",
    summary: "List available models from configured providers",
    description: "Aggregates the model catalog from every materialized provider instance.",
    responses: [{ status: "200", description: "Model list." }],
  },
  {
    id: "manifest-get",
    category: "configuration",
    method: "GET",
    path: "/api/agent/manifest",
    summary: "Read the bundle manifest",
    description:
      "Read-only by spec — bundle is immutable at runtime. The agent introspects its own contract via this endpoint (which built-in tools, which require approval, etc).",
    responses: [
      {
        status: "200",
        description: "Manifest excerpt + runtime info.",
        example: {
          name: "phantom-soc-simulation",
          version: "1.0.0",
          runtime: { mode: "standalone-or-orchestrated", model: "gemini-3.1-pro-preview", setupRequired: false },
        },
      },
    ],
  },
  // ─── configuration entries ───
  {
    id: "backup",
    category: "configuration",
    method: "GET",
    path: "/api/agent/backup",
    summary: "Download a full backup ZIP of all operator state (auth-gated)",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "chat-post",
    category: "configuration",
    method: "POST",
    path: "/api/chat",
    summary: "Start or continue a chat session (SSE streaming response)",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "connectors",
    category: "configuration",
    method: "GET",
    path: "/api/agent/connectors",
    summary: "List all connector definitions known to the agent",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "connectors-by-id-by-action-post",
    category: "configuration",
    method: "POST",
    path: "/api/agent/connectors/{id}/{action}",
    summary: "Create connectors",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "instances-by-id",
    category: "configuration",
    method: "GET",
    path: "/api/agent/instances/{id}",
    summary: "List configured connector instances",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "instances-by-id-delete",
    category: "configuration",
    method: "DELETE",
    path: "/api/agent/instances/{id}",
    summary: "Delete instances",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "instances-by-id-patch",
    category: "configuration",
    method: "PATCH",
    path: "/api/agent/instances/{id}",
    summary: "Update instances",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "instances-by-id-test-post",
    category: "configuration",
    method: "POST",
    path: "/api/agent/instances/{id}/test",
    summary: "Create a new connector instance",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "internal-fire-hook-post",
    category: "configuration",
    method: "POST",
    path: "/api/agent/internal/fire-hook",
    summary: "Internal: fire a hook (used by hooks subsystem itself)",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "marketplace-by-connectorId-download",
    category: "configuration",
    method: "GET",
    path: "/api/agent/marketplace/{connectorId}/download",
    summary: "Get marketplace download",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "marketplace-by-connectorId-uninstall-delete",
    category: "configuration",
    method: "DELETE",
    path: "/api/agent/marketplace/{connectorId}/uninstall",
    summary: "Delete marketplace uninstall",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "marketplace-connectors",
    category: "configuration",
    method: "GET",
    path: "/api/marketplace/connectors",
    summary: "List the bundle connector cards",
    description:
      "The connectors that ship with Phantom, with their live tool lists. Connectors the operator uploaded are not here: see /api/agent/marketplace/catalog/user.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "marketplace-connectors-by-id",
    category: "configuration",
    method: "GET",
    path: "/api/marketplace/connectors/{id}",
    summary: "Get one bundle connector card",
    description:
      "Looks the id up in the bundle list above, so an uploaded connector answers 404.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "marketplace-catalog-user",
    category: "configuration",
    method: "GET",
    path: "/api/agent/marketplace/catalog/user",
    summary: "List the cards for uploaded connectors",
    description:
      "One card per connector the operator uploaded (name, version, tools, config fields, image), built from the MCP marketplace catalogue. The Marketplace tab appends these to the bundle cards.",
    responses: [{ status: "200", description: "Array of connector cards (empty when nothing is uploaded)." }],
  },
  {
    id: "marketplace-by-connectorId-delete",
    category: "configuration",
    method: "DELETE",
    path: "/api/agent/marketplace/{connectorId}",
    summary: "Delete an uploaded connector",
    description:
      "Removes the install marker and the stored connector.yaml. 403 for a bundle connector, 409 while instances exist.",
    pathParams: [{ name: "connectorId", type: "string", description: "Id of the uploaded connector." }],
    responses: [{ status: "200", description: "{connector_id, deleted: true}." }],
    riskTier: "soft",
  },
  {
    id: "marketplace-install-post",
    category: "configuration",
    method: "POST",
    path: "/api/agent/marketplace/install",
    summary: "Install a connector from the marketplace",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "marketplace-installed",
    category: "configuration",
    method: "GET",
    path: "/api/agent/marketplace/installed",
    summary: "List currently-installed marketplace connectors",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "marketplace-upload-post",
    category: "configuration",
    method: "POST",
    path: "/api/agent/marketplace/upload",
    summary: "Upload a connector bundle (zip) for one-off install",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "openapi",
    category: "configuration",
    method: "GET",
    path: "/api/agent/openapi",
    summary: "Return the OpenAPI 3.0 spec for the agent's REST surface",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "operator-state-by-key",
    category: "configuration",
    method: "GET",
    path: "/api/agent/operator-state/{key}",
    summary: "Get operator state",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "operator-state-by-key-delete",
    category: "configuration",
    method: "DELETE",
    path: "/api/agent/operator-state/{key}",
    summary: "Delete operator state",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "operator-state-by-key-put",
    category: "configuration",
    method: "PUT",
    path: "/api/agent/operator-state/{key}",
    summary: "Replace operator state",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "providers-vertex-test-post",
    category: "configuration",
    method: "POST",
    path: "/api/agent/providers/vertex/test",
    summary: "Test Vertex AI provider credentials",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "restore-post",
    category: "configuration",
    method: "POST",
    path: "/api/agent/restore",
    summary: "Restore operator state from a backup ZIP",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
];

// ─────────────────────────────────────────────────────────────────
// OPERATIONS — jobs, audit, notifications
// ─────────────────────────────────────────────────────────────────

const OPERATIONS: ApiEndpoint[] = [
  {
    id: "jobs-list",
    category: "operations",
    method: "GET",
    path: "/api/agent/jobs",
    summary: "List scheduled jobs",
    description: "Both manifest-shipped and runtime-created jobs.",
    queryParams: [
      { name: "source", type: "string", enum: ["manifest", "runtime"], description: "Filter by source.", example: "runtime" },
    ],
    responses: [
      {
        status: "200",
        description: "List of jobs.",
        example: {
          jobs: [
            {
              name: "daily-soc-coverage-summary",
              cron: "0 8 * * *",
              timezone: "UTC",
              source: "manifest",
              enabled: true,
              next_due_at: "2026-05-02T08:00:00Z",
            },
          ],
          count: 1,
        },
      },
    ],
  },
  {
    id: "jobs-create",
    category: "operations",
    method: "POST",
    path: "/api/agent/jobs",
    summary: "Create a runtime job",
    description: "Persists to jobs.db AND mirrors to <data_root>/jobs/<name>.yaml so the runtime def is git-trackable.",
    body: {
      contentType: "application/json",
      schema: {
        type: "object",
        required: ["name", "cron", "action"],
        properties: {
          name: { type: "string", description: "Filesystem-safe name (no slashes, dots)." },
          cron: { type: "string", description: "5-field POSIX cron." },
          timezone: { type: "string", description: "IANA TZ name. Default UTC." },
          action: { type: "object", description: "{type: chat|tool_call|log, ...}" },
          enabled: { type: "boolean" },
          run_once: { type: "boolean", description: "Auto-disable after first fire." },
          description: { type: "string", description: "Optional note on what the job is for (up to 2000 characters). Shown on /jobs and the job page." },
        },
      },
      example: {
        name: "weekly-coverage-summary",
        description: "Weekly XQL coverage digest for the SOC lead",
        cron: "0 9 * * MON",
        timezone: "UTC",
        action: { type: "tool_call", name: "xlog.generate_coverage_report", args: { request: { include_simulations: true, limit: 50 } } },
        enabled: true,
        run_once: false,
      },
    },
    responses: [
      { status: "201", description: "Job created." },
      { status: "400", description: "Validation error (invalid cron, name conflict, etc)." },
    ],
    riskTier: "soft",
  },
  {
    id: "jobs-get",
    category: "operations",
    method: "GET",
    path: "/api/agent/jobs/{jobName}",
    summary: "Fetch one job",
    description: "Returns full row including last_status, next_due_at, enabled, cron, action.",
    pathParams: [{ name: "jobName", type: "string", description: "Job name.", example: "daily-soc-coverage-summary" }],
    responses: [
      { status: "200", description: "Job row." },
      { status: "404", description: "Not found." },
    ],
  },
  {
    id: "jobs-update",
    category: "operations",
    method: "PATCH",
    path: "/api/agent/jobs/{jobName}",
    summary: "Patch a runtime job",
    description: "Manifest jobs ignore most updates and revert on next boot.",
    pathParams: [{ name: "jobName", type: "string", description: "Job name." }],
    body: {
      contentType: "application/json",
      schema: {
        type: "object",
        properties: {
          cron: { type: "string" },
          timezone: { type: "string" },
          action: { type: "object" },
          enabled: { type: "boolean" },
          description: { type: "string", description: "Omit to keep the stored note; \"\" clears it." },
        },
      },
      example: { enabled: false },
    },
    responses: [{ status: "200", description: "Updated row." }],
    riskTier: "soft",
  },
  {
    id: "jobs-delete",
    category: "operations",
    method: "DELETE",
    path: "/api/agent/jobs/{jobName}",
    summary: "Permanently remove a job",
    description: "Runtime jobs: gone for good (YAML mirror also removed). Manifest jobs: reappear on next boot.",
    pathParams: [{ name: "jobName", type: "string", description: "Job name." }],
    responses: [{ status: "200", description: "Deleted." }],
    riskTier: "destructive",
  },
  {
    id: "jobs-runs",
    category: "operations",
    method: "GET",
    path: "/api/agent/jobs/{jobName}/runs",
    summary: "Recent run history",
    description: "Each row has run_id, started_at, finished_at, status (success|failure), result, error.",
    pathParams: [{ name: "jobName", type: "string", description: "Job name." }],
    queryParams: [{ name: "limit", type: "integer", description: "Default 20.", example: 20 }],
    responses: [{ status: "200", description: "Run rows." }],
  },
  {
    id: "jobs-action",
    category: "operations",
    method: "POST",
    path: "/api/agent/jobs/{jobName}/{action}",
    summary: "Trigger a job action",
    description: "Action is one of: run (fire now), pause (set enabled=false), resume (set enabled=true).",
    pathParams: [
      { name: "jobName", type: "string", description: "Job name." },
      { name: "action", type: "string", enum: ["run", "pause", "resume"], description: "Verb.", example: "run" },
    ],
    responses: [{ status: "200", description: "Action applied." }],
    riskTier: "soft",
  },
  {
    id: "audit-list",
    category: "operations",
    method: "GET",
    path: "/api/agent/audit",
    summary: "Search the audit log",
    description: "Filter by action, actor, target_prefix, free-text query, time range.",
    queryParams: [
      { name: "q", type: "string", description: "Free-text against action/target/metadata.", example: "caldera" },
      { name: "action", type: "string", description: "Exact action filter.", example: "tool_call" },
      { name: "actor", type: "string", description: "Exact actor filter.", example: "operator" },
      { name: "target_prefix", type: "string", description: "Prefix filter.", example: "memory:" },
      { name: "limit", type: "integer", description: "Default 50.", example: 50 },
    ],
    responses: [{ status: "200", description: "Audit rows newest-first." }],
  },
  {
    id: "audit-stream",
    category: "operations",
    method: "GET",
    path: "/api/agent/audit/stream",
    summary: "Server-sent events stream of audit rows",
    description: "Long-lived SSE — emits one event per new audit row. Used by the live activity panel.",
    responses: [{ status: "200", description: "text/event-stream." }],
  },
  {
    id: "notifications-list",
    category: "operations",
    method: "GET",
    path: "/api/agent/notifications",
    summary: "List notifications",
    description: "Operator inbox, newest first. Page with limit and offset; the response carries `total` (rows matching the filters, ignoring limit and offset).",
    queryParams: [
      { name: "unread", type: "boolean", description: "Hide already-read.", example: true },
      { name: "limit", type: "integer", description: "Rows per page. Default 100.", example: 50 },
      { name: "offset", type: "integer", description: "Rows to skip. Default 0.", example: 50 },
      { name: "since", type: "string", description: "Only rows created at or after this ISO-8601 UTC timestamp.", example: "2026-10-12T00:00:00.000000Z" },
      { name: "target", type: "string", description: "Only rows for this target, for example user:operator.", example: "user:operator" },
    ],
    responses: [{ status: "200", description: "{notifications, count, total}." }],
  },
  {
    id: "notifications-ack-all",
    category: "operations",
    method: "POST",
    path: "/api/agent/notifications/ack-all",
    summary: "Mark every unread notification read",
    description: "Optional body {target} limits it to one target. Returns {acked: <rows changed>}.",
    responses: [{ status: "200", description: "{acked}." }],
    riskTier: "soft",
  },
  {
    id: "notifications-ack",
    category: "operations",
    method: "POST",
    path: "/api/agent/notifications/{id}/ack",
    summary: "Mark a notification as read",
    description: "Idempotent.",
    pathParams: [{ name: "id", type: "string", description: "Notification UUID." }],
    responses: [{ status: "200", description: "Acked." }],
    riskTier: "soft",
  },
];

// ─────────────────────────────────────────────────────────────────
// SELF-MODIFICATION — approvals lifecycle
// ─────────────────────────────────────────────────────────────────

const SELF_MOD: ApiEndpoint[] = [
  {
    id: "approvals-list",
    category: "self-modification",
    method: "GET",
    path: "/api/agent/approvals",
    summary: "List approval requests",
    description:
      "Pending + history depending on status filter. Each row includes risk_tier (soft|destructive|credential) — drives the inline approval card UI.",
    queryParams: [
      { name: "status", type: "string", enum: ["pending", "approved", "denied", "timeout"], description: "Filter by status.", example: "pending" },
      { name: "limit", type: "integer", description: "Default 50.", example: 50 },
    ],
    responses: [
      {
        status: "200",
        description: "Approval rows.",
        example: {
          approvals: [
            {
              id: "apv_abc",
              tool: "personality_update",
              actor: "agent",
              status: "pending",
              risk_tier: "soft",
              created_at: "2026-05-01T12:34:56.789Z",
              args: { blob_keys: ["personalityMd"], patch: true },
            },
          ],
          count: 1,
        },
      },
    ],
  },
  {
    id: "approvals-resolve",
    category: "self-modification",
    method: "POST",
    path: "/api/agent/approvals/{id}/resolve",
    summary: "Approve or deny a pending request",
    description:
      "Defense-in-depth: the bus's actor != resolver check rejects self-resolution (ApprovalSelfResolveError).",
    pathParams: [{ name: "id", type: "string", description: "Approval UUID.", example: "apv_abc" }],
    body: {
      contentType: "application/json",
      schema: {
        type: "object",
        required: ["decision"],
        properties: {
          decision: { type: "string", enum: ["approved", "denied"] },
          reason: { type: "string" },
          actor: { type: "string" },
        },
      },
      example: { decision: "approved", reason: null, actor: "user:operator" },
    },
    responses: [
      { status: "200", description: "Resolved row." },
      { status: "403", description: "Self-resolution blocked." },
    ],
    riskTier: "soft",
  },
  // ─── self-modification entries ───
  {
    id: "agent-definitions",
    category: "self-modification",
    method: "GET",
    path: "/api/agent/agent-definitions",
    summary: "List all configured chat agent definitions",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "agent-definitions-by-id",
    category: "self-modification",
    method: "GET",
    path: "/api/agent/agent-definitions/{id}",
    summary: "List all configured chat agent definitions",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "agent-definitions-by-id-delete",
    category: "self-modification",
    method: "DELETE",
    path: "/api/agent/agent-definitions/{id}",
    summary: "Delete agent definitions",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "agent-definitions-by-id-patch",
    category: "self-modification",
    method: "PATCH",
    path: "/api/agent/agent-definitions/{id}",
    summary: "Update agent definitions",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "agent-definitions-post",
    category: "self-modification",
    method: "POST",
    path: "/api/agent/agent-definitions",
    summary: "Create a new chat agent definition",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "hooks",
    category: "self-modification",
    method: "GET",
    path: "/api/agent/hooks",
    summary: "List all configured hooks",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "hooks-builtins",
    category: "self-modification",
    method: "GET",
    path: "/api/agent/hooks/builtins",
    summary: "List all configured hooks",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "hooks-by-id",
    category: "self-modification",
    method: "GET",
    path: "/api/agent/hooks/{id}",
    summary: "List all configured hooks",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "hooks-by-id-delete",
    category: "self-modification",
    method: "DELETE",
    path: "/api/agent/hooks/{id}",
    summary: "Delete hooks",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "hooks-by-id-patch",
    category: "self-modification",
    method: "PATCH",
    path: "/api/agent/hooks/{id}",
    summary: "Update hooks",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "hooks-post",
    category: "self-modification",
    method: "POST",
    path: "/api/agent/hooks",
    summary: "Create a new hook",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "jobs-yaml-issues",
    category: "self-modification",
    method: "GET",
    path: "/api/agent/jobs/yaml-issues",
    summary: "List YAML parse issues across configured jobs",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "plugin-entries",
    category: "self-modification",
    method: "GET",
    path: "/api/agent/plugin-entries",
    summary: "List installed plugin entries (skills/agents/hooks bundles)",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "plugin-entries-by-dist_name-delete",
    category: "self-modification",
    method: "DELETE",
    path: "/api/agent/plugin-entries/{dist_name}",
    summary: "Delete plugin entries",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "plugin-entries-install-post",
    category: "self-modification",
    method: "POST",
    path: "/api/agent/plugin-entries/install",
    summary: "Install a plugin bundle from URL",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "plugin-hooks",
    category: "self-modification",
    method: "GET",
    path: "/api/agent/plugin-hooks",
    summary: "List hook definitions contributed by installed plugins",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "plugins",
    category: "self-modification",
    method: "GET",
    path: "/api/agent/plugins",
    summary: "List installed Phantom plugins",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "plugins-reload-post",
    category: "self-modification",
    method: "POST",
    path: "/api/agent/plugins/reload",
    summary: "Reload plugin entries (re-scan installed plugins)",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "tasks",
    category: "self-modification",
    method: "GET",
    path: "/api/agent/tasks",
    summary: "List background tasks (agent-spawned subagents)",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "tasks-by-id",
    category: "self-modification",
    method: "GET",
    path: "/api/agent/tasks/{id}",
    summary: "List background tasks (agent-spawned subagents)",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "tasks-by-id-abort-post",
    category: "self-modification",
    method: "POST",
    path: "/api/agent/tasks/{id}/abort",
    summary: "Abort a running background task",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "tasks-post",
    category: "self-modification",
    method: "POST",
    path: "/api/agent/tasks",
    summary: "Create tasks",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "tool-call-post",
    category: "self-modification",
    method: "POST",
    path: "/api/agent/tool/call",
    summary: "Invoke an MCP tool by name with arguments",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
];

// ─────────────────────────────────────────────────────────────────
// OBSERVABILITY — health, metrics
// ─────────────────────────────────────────────────────────────────

const OBSERVABILITY: ApiEndpoint[] = [
  {
    id: "health",
    category: "observability",
    method: "GET",
    path: "/api/agent/health",
    summary: "Liveness + readiness probe",
    description:
      "Returns {status, embedder_mode}. embedder_mode='vertex' means the live VertexEmbedder is wired; 'stub' means no Vertex provider is saved yet (add one on /providers; it takes effect immediately).",
    responses: [
      {
        status: "200",
        description: "Health snapshot.",
        example: { status: "ok", embedder_mode: "vertex" },
      },
    ],
  },
  {
    id: "metrics",
    category: "observability",
    method: "GET",
    path: "/api/agent/metrics",
    summary: "Prometheus exposition",
    description:
      "Standard /metrics scrape target. Includes phantom_embedder_* gauges (upstream_calls, cache_hits, errors_total, fallback_calls, cache_entries) refreshed at scrape time.",
    responses: [
      {
        status: "200",
        description: "text/plain Prometheus 0.0.4 exposition.",
        example:
          "# HELP phantom_embedder_upstream_calls_total Vertex embed() calls...\nphantom_embedder_upstream_calls_total 4.0\n",
      },
    ],
  },
  // ─── observability entries ───
  {
    id: "bench-runs",
    category: "observability",
    method: "GET",
    path: "/api/agent/bench/runs",
    summary: "List benchmark runs",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "bench-runs-by-run_id",
    category: "observability",
    method: "GET",
    path: "/api/agent/bench/runs/{run_id}",
    summary: "List benchmark runs",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "bench-runs-post",
    category: "observability",
    method: "POST",
    path: "/api/agent/bench/runs",
    summary: "Create bench runs",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "detections",
    category: "observability",
    method: "GET",
    path: "/api/agent/detections",
    summary: "List detections",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "detections-by-rule_id",
    category: "observability",
    method: "GET",
    path: "/api/agent/detections/{rule_id}",
    summary: "Get detections",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "detections-by-rule_id-fires",
    category: "observability",
    method: "GET",
    path: "/api/agent/detections/{rule_id}/fires",
    summary: "List rule-fire events for a detection rule",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "detections-coverage-techniques",
    category: "observability",
    method: "GET",
    path: "/api/agent/detections/coverage/techniques",
    summary: "Coverage breakdown by MITRE technique",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "detections-sync-post",
    category: "observability",
    method: "POST",
    path: "/api/agent/detections/sync",
    summary: "Sync detections from configured XSIAM/EDR instances",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "digests",
    category: "observability",
    method: "GET",
    path: "/api/agent/digests",
    summary: "List the image digests + version of the running stack",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "observability-events",
    category: "observability",
    method: "GET",
    path: "/api/agent/observability/events",
    summary: "Query the persisted runtime-events store",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "observability-events-post",
    category: "observability",
    method: "POST",
    path: "/api/agent/observability/events",
    summary: "Create observability events",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "observability-events-summary",
    category: "observability",
    method: "GET",
    path: "/api/agent/observability/events/summary",
    summary: "Query the persisted runtime-events store",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "version",
    category: "observability",
    method: "GET",
    path: "/api/agent/version",
    summary: "Return the running stack's version + commit SHA",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
];

// ─────────────────────────────────────────────────────────────────
// IDENTITY — API keys
// ─────────────────────────────────────────────────────────────────

const IDENTITY: ApiEndpoint[] = [
  {
    id: "api-keys-list",
    category: "identity",
    method: "GET",
    path: "/api/agent/api-keys",
    summary: "List minted API keys",
    description: "Metadata only — id, label, scopes, last_used. Plaintext is unrecoverable post-mint by design.",
    responses: [{ status: "200", description: "Key rows." }],
  },
  {
    id: "api-keys-create",
    category: "identity",
    method: "POST",
    path: "/api/agent/api-keys",
    summary: "Mint a new API key",
    description: "Plaintext returned ONCE in the response. Capture it immediately — no retrieval path.",
    body: {
      contentType: "application/json",
      schema: {
        type: "object",
        required: ["label"],
        properties: {
          label: { type: "string" },
          scopes: { type: "array", items: { type: "string" } },
        },
      },
      example: { label: "gh-actions", scopes: ["jobs:write", "audit:read"] },
    },
    responses: [
      {
        status: "201",
        description: "Created. Body includes plaintext (one-time).",
        example: { id: "abc12345", label: "gh-actions", plaintext: "phk_abc12345_…" },
      },
    ],
    riskTier: "credential",
  },
  {
    id: "api-keys-revoke",
    category: "identity",
    method: "DELETE",
    path: "/api/agent/api-keys/{id}",
    summary: "Revoke an API key",
    description: "Permanent — store.verify() returns None for any token derived from this key.",
    pathParams: [{ name: "id", type: "string", description: "Key id (the 8-hex prefix).", example: "abc12345" }],
    responses: [{ status: "200", description: "Revoked." }],
    riskTier: "credential",
  },
  // ─── identity entries ───
  {
    id: "auth-change-password-post",
    category: "identity",
    method: "POST",
    path: "/api/auth/change-password",
    summary: "Change operator password",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "auth-login-post",
    category: "identity",
    method: "POST",
    path: "/api/auth/login",
    summary: "Authenticate operator + issue session cookie",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "auth-logout-post",
    category: "identity",
    method: "POST",
    path: "/api/auth/logout",
    summary: "Invalidate operator session",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
  {
    id: "auth-status",
    category: "identity",
    method: "GET",
    path: "/api/auth/status",
    summary: "Check current operator session status",
    description:
      "Run the endpoint via the try-it-out form to see the response shape.",
    responses: [{ status: "200", description: "OK" }],
  },
];

// ─────────────────────────────────────────────────────────────────
// REPORTS + WORKFLOWS
// ─────────────────────────────────────────────────────────────────

const REPORTS: ApiEndpoint[] = [
  {
    id: "reports-coverage",
    category: "reports",
    method: "GET",
    path: "/api/agent/reports?report=coverage",
    summary: "Generate the SOC coverage report",
    description: "Proxies to xlog's /api/v1/coverage-report. Returns scenario+technique coverage breakdown.",
    queryParams: [
      { name: "report", type: "string", enum: ["coverage", "simulation-export"], description: "Report type.", example: "coverage" },
    ],
    responses: [{ status: "200", description: "JSON report." }],
  },
  {
    id: "reports-export",
    category: "reports",
    method: "GET",
    path: "/api/agent/reports?report=simulation-export&simulationId={id}",
    summary: "Export a single simulation",
    description: "Returns the simulation's events as JSON (default) or markdown.",
    queryParams: [
      { name: "report", type: "string", enum: ["simulation-export"], description: "Required for this endpoint.", example: "simulation-export" },
      { name: "simulationId", type: "string", description: "Simulation UUID." },
      { name: "format", type: "string", enum: ["json", "markdown"], example: "json", description: "Output format." },
    ],
    responses: [{ status: "200", description: "Exported simulation." }],
  },
];

const WORKFLOWS: ApiEndpoint[] = [
  {
    id: "workflows-list",
    category: "workflows",
    method: "GET",
    path: "/api/agent/workflows",
    summary: "List A2UI workflows",
    description: "Per-bundle declared workflows — chat, setup, etc.",
    responses: [{ status: "200", description: "Workflow list." }],
  },
];

export const API_ENDPOINTS: ApiEndpoint[] = [
  ...COGNITIVE,
  ...CONFIGURATION,
  ...OPERATIONS,
  ...SELF_MOD,
  ...OBSERVABILITY,
  ...IDENTITY,
  ...REPORTS,
  ...WORKFLOWS,
];

// ─── Helpers ─────────────────────────────────────────────────────

export function getEndpointById(id: string): ApiEndpoint | undefined {
  return API_ENDPOINTS.find((e) => e.id === id);
}

export function getEndpointsByCategory(c: ApiCategory): ApiEndpoint[] {
  return API_ENDPOINTS.filter((e) => e.category === c);
}

export function searchEndpoints(query: string): ApiEndpoint[] {
  const q = query.trim().toLowerCase();
  if (!q) return API_ENDPOINTS;
  return API_ENDPOINTS.filter((e) => {
    return (
      e.summary.toLowerCase().includes(q) ||
      e.description.toLowerCase().includes(q) ||
      e.path.toLowerCase().includes(q) ||
      e.method.toLowerCase().includes(q) ||
      e.category.includes(q)
    );
  });
}
