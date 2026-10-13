/**
 * Shape of the personality document the personality page edits, and the one
 * rule for turning a stored blob into it. Pure and client-safe so the page
 * and its test share it.
 *
 * There are no defaults here: the canonical default document is
 * DEFAULT_PERSONALITY in the MCP's personality_store.py, reached through
 * /api/agent/personality/defaults.
 */

export interface ActionPolicy {
  /** Tool categories the agent classifies as "operating on itself".
   * Local-tagged turns require an inline approval card before the
   * underlying tool fires (humanRequired[] enforcement). */
  localCategories: string[];
  /** Tool categories the agent classifies as "operating on the SOC
   * environment outside the agent". Subject to confirmExternalActions
   * (default: soft confirmation in chat). */
  externalCategories: string[];
  /** When the agent's classification confidence is low, ASK the
   * operator for clarification rather than guessing. Strongly
   * recommended ON. */
  askWhenUnsure: boolean;
  /** UX cadence for local-side actions before they execute. */
  confirmLocalActions: "approve-card" | "soft" | "off";
  /** UX cadence for external-side actions before they execute. */
  confirmExternalActions: "approve-card" | "soft" | "off";
}

export interface AgentConfig {
  // There are no structured "tone" or "thinking" knobs, and no
  // permission, model, concurrency, notification, caching, compaction or
  // memory-ranking knobs: nothing at runtime reads them. Operators
  // express tone and reasoning style through `personalityMd` (free-form
  // markdown) instead, and the chat route enforces `actionPolicy`.

  // Action Policy — local vs external boundary
  actionPolicy: ActionPolicy;

  // Advanced
  personalityMd: string;
}

// The keys this page owns. A blob stored by an earlier release can carry
// others (permissionLevel, defaultModel, ... responseStyle, and the four
// retired Tuning knobs); they are not loaded, so the next save writes the
// blob without them.
export const PAGE_KEYS: readonly (keyof AgentConfig)[] = ["actionPolicy", "personalityMd"];

export function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function isCompleteConfig(v: Record<string, unknown>): v is Record<string, unknown> & AgentConfig {
  const p = v.actionPolicy;
  return (
    typeof v.personalityMd === "string" &&
    isRecord(p) &&
    Array.isArray(p.localCategories) &&
    Array.isArray(p.externalCategories) &&
    typeof p.askWhenUnsure === "boolean" &&
    typeof p.confirmLocalActions === "string" &&
    typeof p.confirmExternalActions === "string"
  );
}

/**
 * The stored blob laid over the defaults: only PAGE_KEYS survive, a key the
 * blob lacks takes its default, and a partial actionPolicy is completed
 * field by field. Returns null when the result is still not a full
 * AgentConfig (the defaults themselves were malformed).
 */
export function resolveConfig(
  defaults: Record<string, unknown>,
  stored: Record<string, unknown>,
): AgentConfig | null {
  const out: Record<string, unknown> = {};
  for (const k of PAGE_KEYS) {
    if (k in stored) out[k] = stored[k];
    else if (k in defaults) out[k] = defaults[k];
  }
  if (isRecord(defaults.actionPolicy) && isRecord(stored.actionPolicy)) {
    out.actionPolicy = { ...defaults.actionPolicy, ...stored.actionPolicy };
  }
  return isCompleteConfig(out) ? { actionPolicy: out.actionPolicy, personalityMd: out.personalityMd } : null;
}
