/**
 * Backup and restore of the operator's workflow state (operator_state.db: the
 * journeys marked tested, saved metric bookmarks, ...). It is not a secret and
 * not platform catalogue, so it travels in its own section of the backup zip:
 *
 *   operator_state.json   { count, entries: [{ key, value, updated_at }] }
 *
 * `GET /api/v1/operator-state` returns `{ entries, count }`; restore writes each
 * key back with `PUT /api/v1/operator-state/{key}` and body `{ value }`. These
 * helpers are the pure part (shaping the file, deciding what to write), used by
 * app/api/agent/backup/route.ts and app/api/agent/restore/route.ts.
 *
 * Erasable-syntax TypeScript only, so scripts/test-operator-state-backup.mjs can
 * import this file directly with Node's type stripping.
 */

export const OPERATOR_STATE_FILE = "operator_state.json";

export interface OperatorStateEntry {
  key: string;
  value: unknown;
  updated_at?: string;
}

export interface OperatorStateSection {
  count: number;
  entries: OperatorStateEntry[];
}

function asRecord(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {};
}

function entriesOf(raw: unknown): OperatorStateEntry[] {
  const list = asRecord(raw).entries;
  if (!Array.isArray(list)) return [];
  const out: OperatorStateEntry[] = [];
  for (const item of list) {
    const e = asRecord(item);
    if (typeof e.key !== "string" || e.key === "" || !("value" in e)) continue;
    out.push({
      key: e.key,
      value: e.value,
      ...(typeof e.updated_at === "string" ? { updated_at: e.updated_at } : {}),
    });
  }
  return out;
}

/** The body of operator_state.json, from the MCP's list response. */
export function buildOperatorStateSection(listResponse: unknown): OperatorStateSection {
  const entries = entriesOf(listResponse);
  return { count: entries.length, entries };
}

export interface OperatorStateRestorePlan {
  /** Keys to PUT, with the value to write. */
  puts: { key: string; value: unknown }[];
  /** Keys left alone because the destination already has them. */
  skipped: number;
  /** Entries in the file that could not be used. */
  invalid: number;
}

/**
 * What to write on the destination. A key the destination already holds is
 * kept unless `force` is set, like every other section; the last entry wins if
 * the file repeats a key.
 */
export function planOperatorStateRestore(
  file: unknown,
  existingKeys: Iterable<string>,
  force: boolean,
): OperatorStateRestorePlan {
  const rawList = asRecord(file).entries;
  const total = Array.isArray(rawList) ? rawList.length : 0;
  const entries = entriesOf(file);
  const existing = new Set(existingKeys);
  const byKey = new Map<string, unknown>();
  for (const e of entries) byKey.set(e.key, e.value);
  const puts: { key: string; value: unknown }[] = [];
  let skipped = 0;
  for (const [key, value] of byKey) {
    if (existing.has(key) && !force) skipped += 1;
    else puts.push({ key, value });
  }
  return { puts, skipped, invalid: total - entries.length };
}
