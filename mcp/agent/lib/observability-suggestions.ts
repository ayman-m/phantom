/**
 * observability-suggestions.ts — autocomplete logic for the
 * /observability/* query bar. Pure function over the current input
 * state; the UI layer drives keyboard nav and accept/dismiss.
 *
 * Suggestions are scoped to the LAST whitespace-delimited token in
 * the input — multi-token queries like
 *   `target:job:my-job* action:t`
 * complete the trailing `action:t` independently, leaving the rest
 * of the buffer untouched. That mirrors how Splunk SPL, Kibana KQL,
 * and Loki LogQL bar autocomplete work — each clause is independent
 * inside a Boolean AND.
 *
 * Three categories of suggestion:
 *
 *   1. Filter keys (static)            — when the token has no `:`,
 *      suggest the recognized keys (action, actor, target, trigger,
 *      since, until). Inserted with a trailing `:` so the operator
 *      can keep typing the value.
 *
 *   2. Known value enums (static)      — when the token is `key:partial`
 *      and the key has a known value list, suggest matching values:
 *        * action: → 46 known phantom audit actions
 *        * actor:  → agent / user:operator / system / scheduler:*
 *
 *   3. Dynamic resource names          — when the token is
 *      `target:job:partial` or `trigger:job:partial`, suggest from
 *      the live job list passed in via `dynamicSources.jobNames`.
 *      Same for `target:tool:` if the page passes tool names. The
 *      dynamic source is fetched by the page; this util is pure.
 *
 * Returns an array of grouped suggestions. The UI renders one
 * group per category with a header label so the operator sees why
 * each item is there ("Filter keys" vs "Known actions" vs "Jobs").
 */

export interface Suggestion {
  /** The string the operator's cursor will jump to after accepting. */
  insert: string;
  /** What to show in the dropdown (often the same as `insert`). */
  label: string;
  /** Optional dim hint shown to the right of `label`. */
  hint?: string;
  /** True when the suggestion is a key (we append `:`); false for values. */
  isKey?: boolean;
}

export interface SuggestionGroup {
  label: string;
  items: Suggestion[];
}

export interface DynamicSources {
  /** Live job names from /api/agent/jobs. Used for target:/trigger:job:* */
  jobNames?: string[];
}

// Static catalogs ------------------------------------------------------------

const KEYS: { key: string; hint: string }[] = [
  { key: "action", hint: "audit event type" },
  { key: "actor", hint: "agent, user:operator, system" },
  { key: "target", hint: "tool:*, job:*, instance:*, …" },
  { key: "trigger", hint: "what initiated the chain" },
  { key: "since", hint: "ISO lower bound" },
  { key: "until", hint: "ISO upper bound" },
];

// Mirrors bundles/spark/mcp/src/usecase/audit_log.py — keep in sync if
// you add new ACTION_* constants. This list is for autocomplete only;
// the parser doesn't validate against it (operators may type valid
// custom action names, e.g. from a fork).
const KNOWN_ACTIONS: string[] = [
  "tool_call",
  "simulation_created",
  "scenario_started",
  "caldera_operation_created",
  "detection_validation_recorded",
  "coverage_report_generated",
  "setup_completed",
  "settings_changed",
  "instance_created",
  "instance_deleted",
  "provider_created",
  "provider_deleted",
  "secret_read",
  "secret_write",
  "secret_deleted",
  "approval_requested",
  "approval_resolved",
  "session_created",
  "session_ended",
  "session_deleted",
  "message_appended",
  "memory_stored",
  "memory_searched",
  "memory_deleted",
  "context_assembled",
  "job_registered",
  "job_fired",
  "job_completed",
  "job_failed",
  "job_skipped",
  "job_enabled",
  "job_disabled",
  "job_removed",
  "job_updated",
  "kb_loaded",
  "kb_doc_indexed",
  "kb_doc_removed",
  "kb_searched",
  "kb_doc_read",
  "personality_changed",
  "agent_self_mod_requested",
  "agent_self_mod_executed",
  "detections_synced",
  "coverage_snapshot_taken",
  "coverage_drift_detected",
  "coverage_gap_observed",
];

const KNOWN_ACTORS: { value: string; hint?: string }[] = [
  { value: "agent", hint: "phantom agent's own actions" },
  { value: "user:operator", hint: "operator-clicked actions in the UI" },
  { value: "system", hint: "boot-time + scheduler-internal" },
  { value: "scheduler:continuous-coverage-cycle", hint: "manifest job" },
];

const TARGET_PREFIXES = ["job:", "tool:", "instance:", "secret:", "connector:", "provider:"];
const TRIGGER_PREFIXES = ["job:", "operator:", "manifest:"];

// Helpers --------------------------------------------------------------------

/** Find the last whitespace-delimited token starting at the cursor.
 *  Returns the token's start index in the buffer + the token text. */
export function tokenAtCursor(
  buffer: string,
  cursor: number,
): { start: number; text: string } {
  // Scan back from cursor to the previous whitespace (or start).
  let start = cursor;
  while (start > 0 && !/\s/.test(buffer[start - 1])) start--;
  return { start, text: buffer.slice(start, cursor) };
}

/** Build the new buffer when a suggestion is accepted: replace the
 *  current token with the suggestion's `insert` value. The cursor's
 *  new position is right after the inserted text. */
export function applySuggestion(
  buffer: string,
  cursor: number,
  suggestion: Suggestion,
): { next: string; cursor: number } {
  const { start } = tokenAtCursor(buffer, cursor);
  const before = buffer.slice(0, start);
  const after = buffer.slice(cursor);
  const next = `${before}${suggestion.insert}${after}`;
  return { next, cursor: start + suggestion.insert.length };
}

// Main entry -----------------------------------------------------------------

/** Return suggestion groups for the current buffer + cursor. */
export function getSuggestions(
  buffer: string,
  cursor: number,
  dynamic: DynamicSources = {},
): SuggestionGroup[] {
  const { text: token } = tokenAtCursor(buffer, cursor);

  // ── Empty / no colon yet → key suggestions ──────────────────────
  const colonIdx = token.indexOf(":");
  if (colonIdx === -1) {
    const partial = token.toLowerCase();
    const items: Suggestion[] = KEYS.filter((k) => k.key.startsWith(partial)).map(
      (k) => ({
        insert: `${k.key}:`,
        label: `${k.key}:`,
        hint: k.hint,
        isKey: true,
      }),
    );
    if (items.length === 0) return [];
    return [{ label: "Filter keys", items }];
  }

  // Token shape: `key:partial[:more]`
  const key = token.slice(0, colonIdx).toLowerCase();
  const valuePart = token.slice(colonIdx + 1);

  // ── action: → known audit action enum ──────────────────────────
  if (key === "action") {
    const partial = valuePart.toLowerCase();
    const items: Suggestion[] = KNOWN_ACTIONS.filter((a) =>
      a.startsWith(partial),
    )
      .slice(0, 10)
      .map((a) => ({ insert: `action:${a}`, label: a }));
    if (items.length === 0) return [];
    return [{ label: "Known actions", items }];
  }

  // ── actor: → known actors ──────────────────────────────────────
  if (key === "actor") {
    const partial = valuePart.toLowerCase();
    const items: Suggestion[] = KNOWN_ACTORS.filter((a) =>
      a.value.startsWith(partial),
    ).map((a) => ({
      insert: `actor:${a.value}`,
      label: a.value,
      hint: a.hint,
    }));
    if (items.length === 0) return [];
    return [{ label: "Known actors", items }];
  }

  // ── target: / trigger: → prefix family + dynamic resource names ─
  if (key === "target" || key === "trigger") {
    const prefixes = key === "target" ? TARGET_PREFIXES : TRIGGER_PREFIXES;
    const groups: SuggestionGroup[] = [];

    // Layer 1: if the value doesn't yet have a prefix family selected,
    // suggest the families.
    const hasFamily = prefixes.some((p) => valuePart.startsWith(p));
    if (!hasFamily) {
      const familyMatches = prefixes
        .filter((p) => p.startsWith(valuePart.toLowerCase()))
        .map<Suggestion>((p) => ({
          insert: `${key}:${p}`,
          label: `${key}:${p}`,
          hint: "prefix",
        }));
      if (familyMatches.length > 0) {
        groups.push({
          label: key === "target" ? "Target prefixes" : "Trigger prefixes",
          items: familyMatches,
        });
      }
    }

    // Layer 2: if the value is `job:<partial>` and we have job names,
    // suggest matching ones. Add a trailing `*` automatically when
    // suggesting a partial match family-wide ("job:" alone → "job:*").
    if (
      (valuePart === "job:" || valuePart.startsWith("job:")) &&
      dynamic.jobNames &&
      dynamic.jobNames.length > 0
    ) {
      const partial = valuePart.slice("job:".length).toLowerCase();
      const items: Suggestion[] = dynamic.jobNames
        .filter((n) => n.toLowerCase().startsWith(partial))
        .slice(0, 10)
        .map((n) => ({
          insert: `${key}:job:${/\s/.test(n) ? `"${n}"` : n}`,
          label: `${key}:job:${n}`,
        }));
      if (items.length > 0) {
        groups.push({ label: "Jobs", items });
      }
    }

    return groups;
  }

  // ── since: / until: → ISO timestamp hints ──────────────────────
  if (key === "since" || key === "until") {
    const now = new Date();
    const isoNow = now.toISOString().slice(0, 19) + "Z";
    const isoMinus1h = new Date(now.getTime() - 3600_000).toISOString().slice(0, 19) + "Z";
    const isoMinus24h = new Date(now.getTime() - 86400_000).toISOString().slice(0, 19) + "Z";
    const today = now.toISOString().slice(0, 10);
    const items: Suggestion[] = [
      { insert: `${key}:${isoMinus1h}`, label: "1 hour ago", hint: isoMinus1h },
      { insert: `${key}:${isoMinus24h}`, label: "24 hours ago", hint: isoMinus24h },
      { insert: `${key}:${today}`, label: `today (${today})`, hint: "from start of day" },
      { insert: `${key}:${isoNow}`, label: "now", hint: isoNow },
    ];
    return [{ label: key === "since" ? "Since (lower bound)" : "Until (upper bound)", items }];
  }

  return [];
}
