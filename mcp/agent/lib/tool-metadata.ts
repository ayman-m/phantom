/**
 * Tool metadata table
 *
 * Adapted from SnowAgent's Tool contract (snow-agent-complete/snow-
 * agent/06-tools-permissions/Tool.ts), which carries `readOnly`,
 * `destructive`, `openWorld`, `concurrencySafe` flags inline on the
 * tool definition. Phantom's MCP tools come from the FastMCP
 * connector loader and don't expose these flags in their schemas;
 * this curated table fills the gap.
 *
 * Why a table instead of pushing flags into manifest's tool specs:
 *
 *   - Adding fields to `bundles/spark/connectors/<id>/connector.yaml`
 *     forces every connector author to know the agent-runtime
 *     vocabulary.
 *   - Many tools are already deployed; backfilling 80 tool specs is
 *     a churn-heavy diff per connector.
 *   - The metadata is fundamentally agent-runtime concerns, not
 *     contract concerns — it changes meaning as the chat-route's
 *     orchestration policies evolve.
 *
 * What the chat-route uses each flag for:
 *
 *   readOnly         — affects nothing today. Future: skip the
 *                      audit-row write for read-only calls (they're
 *                      already in tool_call audit), reducing audit
 *                      log volume.
 *   destructive      — surfaces a red border on the approval card.
 *                      The approval gate already gates these via
 *                      manifest.approvals.humanRequired[]; this is
 *                      the visual.
 *   openWorld        — the tool can trigger external side effects
 *                      (Slack post, webhook fire). Currently visual
 *                      only — amber border on approval card.
 *   concurrencySafe  — parallel batch: when the model
 *                      fires N tools in one turn AND ALL of them
 *                      are concurrencySafe, the chat-route
 *                      `Promise.all`s them instead of running
 *                      serially. Cuts latency for read-heavy turns.
 *
 * Defaults (when a tool isn't in the table):
 *   readOnly: false        — assume it might write
 *   destructive: false     — assume not unless we know
 *   openWorld: false       — assume self-contained
 *   concurrencySafe: false — fail-safe: assume serial-only
 */

export interface ToolMetadata {
  readOnly: boolean;
  destructive: boolean;
  openWorld: boolean;
  concurrencySafe: boolean;
  /** Optional one-line description shown on hover in the approval
   *  card. Free text; just operator-facing context. */
  hint?: string;
}

const DEFAULT_METADATA: ToolMetadata = {
  readOnly: false,
  destructive: false,
  openWorld: false,
  concurrencySafe: false,
};

/**
 * Curated metadata table. Keyed by the legacy flat tool name
 * (`<functionPrefix><tool>`, for example `xsiam_run_xql_query`); the
 * namespaced `<connector>.<tool>` form of the same tool resolves to the same
 * row in resolveToolMetadata. Operator-facing, so don't list low-level
 * helpers — only tools the model is realistically going to call.
 *
 * Every key must be a tool the MCP really registers:
 * bundles/spark/mcp/tests/test_shipped_tool_references.py rebuilds the tool
 * catalog from the connector.yaml files and the built-in registry and fails
 * on a name that is not in it.
 */
export const TOOL_METADATA_TABLE: Record<string, ToolMetadata> = {
  // ── Read-only / informational ─────────────────────────────────
  // Catalog + introspection tools. All safe to run in parallel
  // because they read from in-process state or a bounded API.

  phantom_get_field_info: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  skills_list_all: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  skills_read: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  load_simulation_skills: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  knowledge_list: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  knowledge_search: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },

  // Organization: the sample company every simulation uses
  organization_get: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  organization_list: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },

  // CALDERA read-only
  caldera_get_all_agents: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  caldera_get_agent_by_paw: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  caldera_get_all_abilities: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  caldera_get_ability_by_id: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  caldera_get_all_operations: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  caldera_get_operation_by_id: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },

  // XSIAM read-only — XQL queries can be SLOW (some take minutes
  // against TB-scale logs) but they don't write. Keep them
  // concurrencySafe so the agent can run multiple queries in
  // parallel for cross-rule coverage analysis.
  xsiam_run_xql_query: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
    hint: "Read-only XQL query against the XSIAM tenant. May be slow.",
  },
  xsiam_get_datasets: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  xsiam_get_dataset_fields: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  cortex_list_correlation_rules: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },

  // ── Open-world (external side effects) ────────────────────────
  // These post to external systems. Visible amber border on the
  // approval card. Not parallelizable because two sends might
  // interact (e.g. two webhook fires arriving out-of-order at the
  // SIEM and confusing dedup logic).

  xsiam_send_webhook_log: {
    readOnly: false,
    destructive: false,
    openWorld: true,
    concurrencySafe: false,
    hint: "POSTs to WEBHOOK_ENDPOINT. External side effect.",
  },
  // Log-generation workers — generate synthetic logs and SEND
  // them. open-world (the SIEM sees them), serial within a worker.
  phantom_create_scenario_worker: {
    readOnly: false,
    destructive: false,
    openWorld: true,
    concurrencySafe: false,
    hint: "Spawns a long-running worker that emits synthetic logs to the destination.",
  },
  phantom_create_data_worker: {
    readOnly: false,
    destructive: false,
    openWorld: true,
    concurrencySafe: false,
  },
  phantom_kill_worker: {
    readOnly: false,
    destructive: true,
    openWorld: false,
    concurrencySafe: false,
    hint: "Stops a running worker. Cannot resume.",
  },

  // CALDERA write — REAL red-team operations. destructive=true so
  // the approval card gets the red border treatment.
  caldera_create_operation: {
    readOnly: false,
    destructive: true,
    openWorld: true,
    concurrencySafe: false,
    hint: 
      "Launches a real CALDERA operation against the configured agents. " +
      "Produces actual TTPs against the test environment.",
  },
  // Changing an operation's state (pause, stop) is the safe direction, not
  // destructive. Marked openWorld for the CALDERA server interaction.
  caldera_update_operation: {
    readOnly: false,
    destructive: false,
    openWorld: true,
    concurrencySafe: false,
    hint: "Applies a partial update to an operation, for example to pause or stop it.",
  },

  // ── Self-modification ─────────────────────────────
  // These mutate Phantom's own state. Always destructive=true so
  // the operator sees the red border AND humanRequired gates them.
  // (There is no api_keys_create / rotate / revoke here: those are
  // REST-only by the credential guardrail, so the agent has no tool.)

  jobs_create: {
    readOnly: false,
    destructive: false,
    openWorld: false,
    concurrencySafe: false,
    hint: "Creates a scheduled chat-action job.",
  },
  jobs_update: {
    readOnly: false,
    destructive: false,
    openWorld: false,
    concurrencySafe: false,
  },
  jobs_delete: {
    readOnly: false,
    destructive: true,
    openWorld: false,
    concurrencySafe: false,
    hint: "Deletes a scheduled job. Irreversible.",
  },
  personality_update: {
    readOnly: false,
    destructive: false,
    openWorld: false,
    concurrencySafe: false,
  },
  organization_update: {
    readOnly: false,
    destructive: false,
    openWorld: false,
    concurrencySafe: false,
    hint: "Edits the active organization (a bundled one is copied first). Every edit is kept in its history.",
  },
  organization_activate: {
    readOnly: false,
    destructive: false,
    openWorld: false,
    concurrencySafe: false,
  },
  personality_reset: {
    readOnly: false,
    destructive: true,
    openWorld: false,
    concurrencySafe: false,
    hint: "Resets the agent persona to bundle defaults.",
  },
  settings_update: {
    readOnly: false,
    destructive: false,
    openWorld: false,
    concurrencySafe: false,
  },
  settings_reset: {
    readOnly: false,
    destructive: true,
    openWorld: false,
    concurrencySafe: false,
  },

  // Memory
  memory_store: {
    readOnly: false,
    destructive: false,
    openWorld: false,
    concurrencySafe: false,
  },
  time_now: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  memory_search: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  memory_delete: {
    readOnly: false,
    destructive: true,
    openWorld: false,
    concurrencySafe: false,
  },
};

/**
 * Namespaced names whose legacy flat alias is not just the namespaced name
 * with "." replaced by "_" (the connector's functionPrefix differs from its
 * id). Maps to the table key. The test above checks both sides exist.
 */
export const NAMESPACED_TO_TABLE_KEY: Record<string, string> = {
  "xlog.get_field_info": "phantom_get_field_info",
  "xlog.create_data_worker": "phantom_create_data_worker",
  "xlog.create_scenario_worker": "phantom_create_scenario_worker",
  "xlog.kill_worker": "phantom_kill_worker",
  "cortex-content.list_correlation_rules": "cortex_list_correlation_rules",
};

/** Resolve metadata for a tool. Tries the exact tool name, then
 *  the legacy form (replacing `.` with `_`), then the namespaced
 *  form, then falls through to the default. */
export function resolveToolMetadata(toolName: string): ToolMetadata {
  if (TOOL_METADATA_TABLE[toolName]) {
    return TOOL_METADATA_TABLE[toolName];
  }
  const aliased = NAMESPACED_TO_TABLE_KEY[toolName];
  if (aliased && TOOL_METADATA_TABLE[aliased]) return TOOL_METADATA_TABLE[aliased];
  // Try the alternate namespacing: v1.2 namespaced
  // `<connector>.<tool>` ↔ legacy `<connector>_<tool>`.
  if (toolName.includes(".")) {
    const flat = toolName.replace(/\./g, "_");
    if (TOOL_METADATA_TABLE[flat]) return TOOL_METADATA_TABLE[flat];
  } else if (toolName.includes("_")) {
    // Try replacing the FIRST underscore with a dot (most common
    // pattern: connector_tool → connector.tool).
    const idx = toolName.indexOf("_");
    const dotted =
      toolName.slice(0, idx) + "." + toolName.slice(idx + 1);
    if (TOOL_METADATA_TABLE[dotted]) return TOOL_METADATA_TABLE[dotted];
  }
  return DEFAULT_METADATA;
}

/** Helper for the chat-route's parallel-batch decision: returns
 *  true when ALL of the given tool calls are concurrencySafe. */
export function allConcurrencySafe(toolNames: string[]): boolean {
  if (toolNames.length === 0) return false;
  return toolNames.every((n) => resolveToolMetadata(n).concurrencySafe);
}
