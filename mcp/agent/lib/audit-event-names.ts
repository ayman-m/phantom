/**
 * Standard observability event-name aliases
 *
 * Phantom emits its own audit action names (chat_compaction_*,
 * chat_context_warning, chat_cache_hit, hook_dispatched, task_*,
 * chat_plan_*, connector_*, chat_turn_cost).
 *
 * This file documents the mapping from those phantom-internal names
 * to the SnowAgent / OTel-conventional standard event names. Useful
 * when:
 *   - Forwarding to external observability (Datadog, OTel collector)
 *   - Querying across heterogeneous deploys with different vendor
 *     conventions
 *   - Operators familiar with SnowAgent's event names looking up
 *     the equivalent Phantom action
 *
 * The mapping is consultative — Phantom continues to write the
 * phantom-internal names as the canonical action column; this file
 * provides the OTel-friendly form for downstream consumers. A future
 * phase can wire the mapping into an OTel exporter that re-emits
 * audit rows under the standard names.
 *
 * Adapted from SnowAgent's standard event names
 * (snow-agent-complete/snow-agent/13-observability-policy-auth/).
 */

export const AUDIT_EVENT_NAME_ALIASES: Record<string, string> = {
  // Run lifecycle (hook events; this maps the audit
  // names to OTel-conventional dot.namespaced form).
  hook_dispatched: "agent.hook.dispatched",

  // Compaction lifecycle.
  chat_compaction_start: "agent.context.compaction.started",
  chat_compaction_end: "agent.context.compaction.completed",
  chat_compaction_failed: "agent.context.compaction.failed",

  // Context guard.
  chat_context_warning: "agent.context.warning",

  // Prompt caching (any provider; the row names the provider and model_ref).
  chat_cache_hit: "agent.model.cache.hit",

  // Plan mode.
  chat_plan_proposed: "agent.plan.proposed",
  chat_plan_failed: "agent.plan.failed",

  // Cost tracking: one row per model call, with provider, model_ref, cache-write
  // and reasoning tokens, and a priced flag (cost_usd is null when unpriced).
  chat_turn_cost: "agent.model.cost",

  // Model registry: one row per live model-list fetch per provider.
  provider_models_refreshed: "agent.provider.models.refreshed",
  provider_models_refresh_failed: "agent.provider.models.refresh_failed",

  // Provider connection test (the Providers page): {provider, ok, status}, never a key.
  provider_test: "agent.provider.test",

  // A model provider's non-fatal observation during a call: a downgraded tool
  // choice, a dropped tool call, an unknown tool name, a refusal. Also sent as
  // the SSE `debug` event.
  provider_event: "agent.provider.event",

  // A named model cannot serve (unknown, retired, provider not configured).
  // The turn, command, job run or subagent ends with MODEL_UNAVAILABLE.
  chat_model_rejected: "agent.model.rejected",

  // Task registry.
  task_created: "agent.task.created",
  task_started: "agent.task.started",
  task_completed: "agent.task.completed",
  task_failed: "agent.task.failed",
  task_aborted: "agent.task.aborted",
  task_pending: "agent.task.pending",
  task_transitioned: "agent.task.transitioned",

  // Connector state machine.
  connector_failed: "agent.connector.failed",
  connector_auth_required: "agent.connector.auth_required",
  connector_disabled: "agent.connector.disabled",
  connector_enabled: "agent.connector.enabled",
  connector_probed: "agent.connector.probed",

  // Hooks lifecycle.
  hook_upsert: "agent.hook.upsert",
  hook_enabled: "agent.hook.enabled",
  hook_disabled: "agent.hook.disabled",
  hook_deleted: "agent.hook.deleted",

  // Plugins.
  plugins_reloaded: "agent.plugins.reloaded",

  // Subagents.
  chat_subagent_started: "agent.subagent.started",
  chat_subagent_completed: "agent.subagent.completed",
  chat_subagent_failed: "agent.subagent.failed",
  agent_definition_upsert: "agent.definition.upsert",
  agent_definition_enabled: "agent.definition.enabled",
  agent_definition_disabled: "agent.definition.disabled",
  agent_definition_deleted: "agent.definition.deleted",

  // Core phantom families. Surface them here
  // so downstream consumers see consistent dot-namespaced names.
  tool_call: "agent.tool.call",
  approval_requested: "agent.approval.requested",
  approval_resolved: "agent.approval.resolved",
  scenario_started: "rt.scenario.started",
  caldera_operation_created: "rt.caldera.operation.created",
  detection_validation_recorded: "rt.detection.validation.recorded",
};

/** Inverse mapping: standard name → phantom action. Used by
 *  observability importers that need to translate. */
export const AUDIT_STANDARD_TO_PHANTOM: Record<string, string> = (() => {
  const out: Record<string, string> = {};
  for (const [phantom, std] of Object.entries(AUDIT_EVENT_NAME_ALIASES)) {
    out[std] = phantom;
  }
  return out;
})();

/** Resolve a phantom action name to its standard form, or pass
 *  through if no mapping exists. */
export function toStandardEventName(action: string): string {
  return AUDIT_EVENT_NAME_ALIASES[action] ?? action;
}

/** Resolve a standard event name to its phantom form. Identity
 *  fallback for unknown names. */
export function toPhantomActionName(standard: string): string {
  return AUDIT_STANDARD_TO_PHANTOM[standard] ?? standard;
}
