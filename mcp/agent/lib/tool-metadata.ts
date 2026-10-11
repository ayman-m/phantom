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
 * Curated metadata table. Keyed by tool name (legacy flat AND v1.2
 * namespaced — both register the same metadata). Operator-facing,
 * so don't list low-level helpers — only tools the model is
 * realistically going to call.
 */
export const TOOL_METADATA_TABLE: Record<string, ToolMetadata> = {
  // ── Read-only / informational ─────────────────────────────────
  // Catalog + introspection tools. All safe to run in parallel
  // because they read from in-process state or a bounded API.

  phantom_list_observables: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  phantom_get_required_fields: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  phantom_list_scenarios: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  phantom_get_scenario: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  phantom_list_skills: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  phantom_get_skill: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  phantom_get_field_info: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },

  // CALDERA read-only
  caldera_list_agents: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  caldera_get_agent: {
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
  caldera_get_ability: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  caldera_list_operations: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  caldera_get_operation: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },

  // XSIAM read-only — XQL queries can be SLOW (some take minutes
  // against TB-scale logs) but they don't write. Keep them
  // concurrencySafe so the agent can run multiple queries in
  // parallel for cross-rule coverage analysis.
  xsiam_execute_xql_query: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
    hint: "Read-only XQL query against XSIAM PAPI. May be slow.",
  },
  xsiam_get_dataset_metadata: {
    readOnly: true,
    destructive: false,
    openWorld: false,
    concurrencySafe: true,
  },
  xsiam_list_rules: {
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

  send_webhook_log: {
    readOnly: false,
    destructive: false,
    openWorld: true,
    concurrencySafe: false,
    hint: "POSTs to WEBHOOK_ENDPOINT. External side effect.",
  },
  // xlog scenario worker — generates synthetic logs and SENDS
  // them. open-world (the SIEM sees them), serial within a worker.
  xlog_create_scenario_worker: {
    readOnly: false,
    destructive: false,
    openWorld: true,
    concurrencySafe: false,
    hint: "Spawns a long-running worker that emits synthetic logs to the destination.",
  },
  xlog_create_scenario_worker_from_query: {
    readOnly: false,
    destructive: false,
    openWorld: true,
    concurrencySafe: false,
  },
  xlog_create_worker: {
    readOnly: false,
    destructive: false,
    openWorld: true,
    concurrencySafe: false,
  },
  xlog_delete_worker: {
    readOnly: false,
    destructive: true,
    openWorld: false,
    concurrencySafe: false,
    hint: "Stops a running scenario worker. Cannot resume.",
  },

  // CALDERA write — REAL red-team operations. destructive=true so
  // the approval card gets the red border treatment.
  caldera_start_operation: {
    readOnly: false,
    destructive: true,
    openWorld: true,
    concurrencySafe: false,
    hint:
      "Starts a real CALDERA operation against the configured agents. " +
      "Produces actual TTPs against the test environment.",
  },
  caldera_stop_operation: {
    readOnly: false,
    destructive: false, // stopping isn't destructive; it's the
    // safe direction. Marked openWorld for the
    // CALDERA server interaction.
    openWorld: true,
    concurrencySafe: false,
  },

  // ── Self-modification ─────────────────────────────
  // These mutate Phantom's own state. Always destructive=true so
  // the operator sees the red border AND humanRequired gates them.

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
  api_keys_create: {
    readOnly: false,
    destructive: false,
    openWorld: false,
    concurrencySafe: false,
    hint: "Mints a new operator-scoped API key. Plaintext shown once.",
  },
  api_keys_rotate: {
    readOnly: false,
    destructive: true, // old key is invalidated
    openWorld: false,
    concurrencySafe: false,
  },
  api_keys_revoke: {
    readOnly: false,
    destructive: true,
    openWorld: false,
    concurrencySafe: false,
  },

  // Memory writes
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
  memory_list: {
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

/** Resolve metadata for a tool. Tries the exact tool name, then
 *  the legacy form (replacing `.` with `_`), then the namespaced
 *  form, then falls through to the default. */
export function resolveToolMetadata(toolName: string): ToolMetadata {
  if (TOOL_METADATA_TABLE[toolName]) {
    return TOOL_METADATA_TABLE[toolName];
  }
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
