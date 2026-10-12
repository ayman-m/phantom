/**
 * The "what does the destination already hold?" step of a restore.
 *
 * Every section of app/api/agent/restore/route.ts that skips entries the
 * destination already has first lists those entries. If that listing FAILS
 * (the MCP is down, answers an error, or sends a body of an unexpected shape)
 * the destination must NOT be treated as empty: doing so would write the whole
 * section over entries that are really there. Without Overwrite the section is
 * skipped with a warning instead; with Overwrite the operator has asked for
 * the write anyway, so it goes ahead.
 *
 * Erasable-syntax TypeScript only, so scripts/test-restore-existing.mjs can
 * import this file directly with Node's type stripping.
 */

export type ExistingLookup =
  | { ok: true; keys: Set<string> }
  | { ok: false; reason: string };

/**
 * Run a listing. `fetchBody` resolves to the parsed response and must throw on
 * a non-OK answer; `keysOf` returns the keys the body holds, or null when the
 * body is not the expected shape. Never throws.
 */
export async function lookupExistingKeys(
  fetchBody: () => Promise<unknown>,
  keysOf: (body: unknown) => string[] | null,
): Promise<ExistingLookup> {
  let body: unknown;
  try {
    body = await fetchBody();
  } catch (e) {
    return { ok: false, reason: e instanceof Error ? e.message : String(e) };
  }
  let keys: string[] | null;
  try {
    keys = keysOf(body);
  } catch (e) {
    return { ok: false, reason: e instanceof Error ? e.message : String(e) };
  }
  if (keys === null) {
    return { ok: false, reason: "unexpected response shape" };
  }
  return { ok: true, keys: new Set(keys) };
}

/** Keys of a `{ [field]: [...] }` list response, or null if `field` is not a list. */
export function keysFromList(
  body: unknown,
  field: string | null,
  keyOf: (item: Record<string, unknown>) => string | null,
): string[] | null {
  const raw =
    field === null
      ? body
      : body !== null && typeof body === "object" && !Array.isArray(body)
        ? (body as Record<string, unknown>)[field]
        : undefined;
  if (!Array.isArray(raw)) return null;
  const out: string[] = [];
  for (const item of raw) {
    if (item === null || typeof item !== "object" || Array.isArray(item)) continue;
    const k = keyOf(item as Record<string, unknown>);
    if (k !== null) out.push(k);
  }
  return out;
}

export interface SectionGuard {
  /** False when the section must be skipped. */
  proceed: boolean;
  /** Keys the destination holds (empty when the listing failed under force). */
  existing: Set<string>;
  /** Present when the section is skipped; goes into the response's warnings. */
  warning?: string;
}

/**
 * Decide whether a section may be written. `label` names the section for the
 * warning ("instances"), `incoming` is how many entries the backup holds.
 */
export function guardSection(
  lookup: ExistingLookup,
  force: boolean,
  label: string,
  incoming: number,
): SectionGuard {
  if (lookup.ok) return { proceed: true, existing: lookup.keys };
  if (force) return { proceed: true, existing: new Set() };
  return {
    proceed: false,
    existing: new Set(),
    warning:
      `${label}: skipped ${incoming} entr${incoming === 1 ? "y" : "ies"} ` +
      `because the destination's existing ${label} could not be listed ` +
      `(${lookup.reason}). Nothing was written for this section. Retry the ` +
      "restore, or tick Overwrite existing entries to write it anyway.",
  };
}
