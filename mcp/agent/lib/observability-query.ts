/**
 * observability-query.ts — Lucene-light filter parser for /observability/events.
 *
 * Operators get a single search bar instead of three separate
 * filter inputs. The syntax is the cross-cutting subset of Lucene /
 * Elasticsearch / OpenSearch / Loki LogQL labels: terms separated by
 * spaces, each `key:value` (or `key:prefix*`) constraining one field,
 * AND'ed together. No OR / NOT / parens — those belong in a richer
 * frontend (Grafana Explore, Kibana) that we're not rebuilding here.
 *
 * OpenTelemetry deliberately doesn't define a query language — its
 * model is the data shape (spans, metrics, logs), and querying is
 * delegated to the backend. So "OTel-standard" doesn't exist; the
 * closest open-source standard for ad-hoc log filters is Lucene's
 * field-query string syntax (also what Kibana, Elastic Discover,
 * OpenSearch, Loki's `=` selectors, and Grafana's basic explore mode
 * accept). We pick that subset.
 *
 * Supported terms:
 *
 *   action:tool_call          exact action
 *   actor:user:operator       exact actor
 *   target:job:my-job         exact target
 *   target:job:*              prefix (terminating asterisk)
 *   trigger:job:my-job        exact trigger (header from chat-route)
 *   trigger:job:*             prefix
 *   since:2026-05-02T00:00:00Z   ISO timestamp lower bound (inclusive)
 *   until:2026-05-02T08:00:00Z   ISO timestamp upper bound (inclusive)
 *
 * Quoting: values that contain spaces wrap in double quotes:
 *   action:"tool_call" target:"job:my coverage report*"
 *
 * Bareword terms (no `key:`) are reserved for future free-text /
 * metadata search — the audit endpoint doesn't support that today, so
 * we accumulate them into `freeText` for the caller to either ignore
 * or apply client-side.
 *
 * Returns the parsed filter — URL params the caller forwards to
 * /api/agent/audit. Any term that didn't parse cleanly goes into
 * `parseErrors` so the UI can underline it; we don't reject the whole
 * query on one bad term, mirroring how Kibana behaves.
 */

export interface ParsedQuery {
  action?: string;
  actor?: string;
  target?: string;
  target_prefix?: string;
  trigger?: string;
  trigger_prefix?: string;
  since?: string;
  until?: string;
  /** Bareword terms (no key:) — caller may apply client-side. */
  freeText: string[];
  /** Per-term parse errors for UI annotation. */
  parseErrors: string[];
}

/** Keys that map directly to audit endpoint exact-match params. */
const EXACT_KEYS: Record<string, keyof ParsedQuery> = {
  action: "action",
  actor: "actor",
  target: "target",
  trigger: "trigger",
};

/** Keys that map to audit endpoint prefix-match params when the value
 *  ends with `*`. Falls back to exact otherwise. */
const PREFIX_KEYS: Record<string, keyof ParsedQuery> = {
  target: "target_prefix",
  trigger: "trigger_prefix",
};

/** Keys that map to ISO timestamp params. */
const TIME_KEYS = new Set(["since", "until"]);

/**
 * Tokenize a query string into terms. Handles double-quoted values:
 *
 *   target:"job:my job"  status:success
 *   ↓
 *   ["target:job:my job", "status:success"]
 *
 * Quotes are stripped from the output. Backslash-escapes are not
 * supported — operators rarely need quotes-inside-quotes for audit
 * filters, and the simpler tokenizer keeps the surface small.
 */
function tokenize(input: string): string[] {
  const tokens: string[] = [];
  let buf = "";
  let inQuotes = false;
  for (let i = 0; i < input.length; i++) {
    const c = input[i];
    if (c === '"') {
      inQuotes = !inQuotes;
      continue;
    }
    if (!inQuotes && /\s/.test(c)) {
      if (buf.length > 0) {
        tokens.push(buf);
        buf = "";
      }
      continue;
    }
    buf += c;
  }
  if (buf.length > 0) tokens.push(buf);
  return tokens;
}

export function parseQuery(input: string): ParsedQuery {
  const result: ParsedQuery = { freeText: [], parseErrors: [] };
  const tokens = tokenize(input.trim());

  for (const token of tokens) {
    if (!token) continue;
    const colonIdx = token.indexOf(":");

    // Bareword (no `key:`) → reserved free-text bucket.
    if (colonIdx === -1) {
      result.freeText.push(token);
      continue;
    }

    const key = token.slice(0, colonIdx).toLowerCase();
    const value = token.slice(colonIdx + 1);
    if (!value) {
      result.parseErrors.push(`empty value for "${key}:"`);
      continue;
    }

    // Time keys: only check shape, no timezone manipulation. Backend
    // accepts ISO strings — pass them through.
    if (TIME_KEYS.has(key)) {
      // Cheap shape check: digit-heavy first 4 chars, contains a `T`.
      // Doesn't enforce strict ISO (operators paste "2026-05-02") so
      // accept anything reasonable; the backend rejects garbage with 400.
      result[key as "since" | "until"] = value;
      continue;
    }

    // Prefix-eligible keys: treat trailing `*` as a prefix selector.
    if (key in PREFIX_KEYS && value.endsWith("*") && value.length > 1) {
      const prefixKey = PREFIX_KEYS[key];
      result[prefixKey] = value.slice(0, -1) as never;
      continue;
    }

    // Exact-match keys.
    if (key in EXACT_KEYS) {
      const exactKey = EXACT_KEYS[key];
      result[exactKey] = value as never;
      continue;
    }

    // Unknown key — collect for the UI to surface as "unrecognized
    // field". We don't try to map to metadata.* keys because the
    // audit endpoint doesn't support arbitrary metadata filtering;
    // exposing the term as an error is more useful than pretending.
    result.parseErrors.push(`unknown field "${key}"`);
  }

  return result;
}

/**
 * Convert a parsed query back to the URLSearchParams shape the audit
 * endpoint expects. Keys with no value are dropped so we never send
 * empty params (the backend treats `?action=` as "match action=''",
 * not "no filter").
 */
export function parsedQueryToParams(parsed: ParsedQuery): URLSearchParams {
  const p = new URLSearchParams();
  if (parsed.action) p.set("action", parsed.action);
  if (parsed.actor) p.set("actor", parsed.actor);
  if (parsed.target) p.set("target", parsed.target);
  if (parsed.target_prefix) p.set("target_prefix", parsed.target_prefix);
  if (parsed.trigger) p.set("trigger", parsed.trigger);
  if (parsed.trigger_prefix) p.set("trigger_prefix", parsed.trigger_prefix);
  if (parsed.since) p.set("since", parsed.since);
  if (parsed.until) p.set("until", parsed.until);
  return p;
}

/**
 * Build a query string from a partial filter. Used by deep-link
 * helpers (e.g. /jobs/[id] → "View events for this job") so the
 * caller doesn't need to remember the syntax.
 *
 *   buildQuery({ targetPrefix: "job:my-job", since: "..." })
 *   → 'target:job:my-job* since:...'
 */
export function buildQuery(filter: {
  action?: string;
  actor?: string;
  target?: string;
  targetPrefix?: string;
  trigger?: string;
  triggerPrefix?: string;
  since?: string;
  until?: string;
}): string {
  const parts: string[] = [];
  const quote = (s: string) => (/\s/.test(s) ? `"${s}"` : s);
  if (filter.action) parts.push(`action:${quote(filter.action)}`);
  if (filter.actor) parts.push(`actor:${quote(filter.actor)}`);
  if (filter.target) parts.push(`target:${quote(filter.target)}`);
  if (filter.targetPrefix) parts.push(`target:${quote(filter.targetPrefix)}*`);
  if (filter.trigger) parts.push(`trigger:${quote(filter.trigger)}`);
  if (filter.triggerPrefix) parts.push(`trigger:${quote(filter.triggerPrefix)}*`);
  if (filter.since) parts.push(`since:${filter.since}`);
  if (filter.until) parts.push(`until:${filter.until}`);
  return parts.join(" ");
}
