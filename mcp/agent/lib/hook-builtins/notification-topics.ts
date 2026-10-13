/**
 * Notification topics the built-in hooks publish to.
 *
 * Each built-in publishes to ONE fixed topic. The embedded MCP's
 * notification store (usecase/notifications.py) rejects any topic that is
 * not declared in bundles/spark/manifest.yaml `notifications.topics`, so a
 * free-text topic could only ever name an undeclared one. Adding a topic
 * here means declaring it in the manifest in the same change;
 * bundles/spark/mcp/tests/test_hook_builtin_topics.py fails if the two
 * drift.
 *
 * No imports, and erasable TypeScript only, so
 * scripts/test-hook-builtin-topics.mjs can import this file directly.
 */

/** cost-warn-over-budget (RunEnd). */
export const COST_WARNING_TOPIC = "cost-warning";

/** pre-compact-context-warning (PreCompact). */
export const CONTEXT_WARNING_TOPIC = "context-warning";

/** Every topic a built-in hook publishes. */
export const BUILTIN_HOOK_TOPICS = [COST_WARNING_TOPIC, CONTEXT_WARNING_TOPIC] as const;
