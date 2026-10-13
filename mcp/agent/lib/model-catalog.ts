/**
 * The model registry as the UI reads it: GET /api/agent/models.
 *
 * That route returns a bare JSON array of models. The /models pages, the chat
 * header's picker and the /jobs/new and bench Model dropdowns all read it
 * through `fetchModelCatalog`, so they can never disagree about what is
 * registered. (The job form once read `data.models` off the array, got
 * undefined, and always showed its empty-state text while /models listed
 * twelve models.)
 *
 * Free of imports and of non-erasable TypeScript so
 * scripts/test-job-form.mjs can load it with Node's type stripping.
 */

export interface CatalogModel {
  provider: string;
  model: string;
  /** Canonical "provider/model". */
  ref?: string;
  displayName?: string;
  kind?: string;
  supportsThinking?: boolean;
  /** Chat can run on this model right now (registry-computed). */
  selectable?: boolean;
  /** "available", "deprecated", "unverified", ... */
  availability?: string;
  reason?: string | null;
}

/** Validate the route's payload. A non-array body is a contract break, not
 *  an empty registry, so it throws instead of returning []. */
export function parseModelCatalog<T extends CatalogModel = CatalogModel>(
  payload: unknown,
): T[] {
  if (!Array.isArray(payload)) {
    throw new Error("model registry returned an unexpected payload");
  }
  return payload as T[];
}

/** GET /api/agent/models. Throws on a non-2xx response or a bad payload. */
export async function fetchModelCatalog<T extends CatalogModel = CatalogModel>(
  signal?: AbortSignal,
): Promise<T[]> {
  const r = await fetch("/api/agent/models", { cache: "no-store", signal });
  if (!r.ok) throw new Error(`models fetch ${r.status}`);
  return parseModelCatalog<T>(await r.json());
}

/** Models a job, the bench or the chat header may be pinned to: chat models
 *  the registry says are selectable, so no embedding/image/voice, nothing
 *  retired, unconfigured or unreachable. */
export function selectableChatModels<T extends CatalogModel>(models: T[]): T[] {
  return models.filter(
    (m) => (!m.kind || m.kind === "chat") && m.selectable === true,
  );
}

/**
 * The canonical "provider/model" a stored model string stands for: a ref as it
 * is, or a bare id that exactly one provider in `models` offers (jobs and
 * sessions written before refs existed hold bare ids). Null when the string
 * names no listed model or is ambiguous; the caller then shows it as it is.
 * Writes always go out canonical.
 */
export function refForStoredModel(
  models: Array<Pick<CatalogModel, "provider" | "model" | "ref">>,
  stored: string,
): string | null {
  const wanted = stored.trim().toLowerCase();
  if (!wanted) return null;
  const refOf = (m: Pick<CatalogModel, "provider" | "model" | "ref">) => m.ref ?? `${m.provider}/${m.model}`;
  const exact = models.filter((m) => refOf(m).toLowerCase() === wanted);
  if (exact.length === 1) return refOf(exact[0]);
  if (wanted.includes("/")) return null;
  const bare = models.filter((m) => m.model.toLowerCase() === wanted);
  return bare.length === 1 ? refOf(bare[0]) : null;
}

/** Short provider names for headings. */
const PROVIDER_NAMES: Record<string, string> = {
  vertex: "Google Gemini",
  anthropic: "Anthropic",
  openai: "OpenAI",
};

export function providerName(provider: string): string {
  return PROVIDER_NAMES[provider] ?? provider;
}

/** Providers in the order pickers list them. */
const PROVIDER_ORDER = ["vertex", "anthropic", "openai"];

export function compareProviders(a: string, b: string): number {
  const ia = PROVIDER_ORDER.indexOf(a);
  const ib = PROVIDER_ORDER.indexOf(b);
  return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b);
}

/** A picker row's secondary label for a model near retirement, or "". */
export function lifecycleBadge(model: CatalogModel): string {
  return model.availability === "deprecated" ? "deprecated" : "";
}
