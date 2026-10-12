/**
 * The model registry as the UI reads it: GET /api/agent/models.
 *
 * That route returns a bare JSON array of models. The /models page and the
 * /jobs/new Model dropdown both read it through `fetchModelCatalog`, so the
 * two can never disagree about what is registered. (The job form once read
 * `data.models` off the array, got undefined, and always showed its
 * empty-state text while /models listed twelve models.)
 *
 * Free of imports and of non-erasable TypeScript so
 * scripts/test-model-catalog.mjs can load it with Node's type stripping.
 */

export interface CatalogModel {
  provider: string;
  model: string;
  displayName?: string;
  kind?: string;
  supportsThinking?: boolean;
  /** Coming-soon entry: listed on /models but not routable. */
  wip?: boolean;
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

/** Models a job (or the chat header) may be pinned to: chat models that
 *  are actually routable, so no embedding/image/voice and no wip entries. */
export function selectableChatModels<T extends CatalogModel>(models: T[]): T[] {
  return models.filter((m) => (!m.kind || m.kind === "chat") && !m.wip);
}
