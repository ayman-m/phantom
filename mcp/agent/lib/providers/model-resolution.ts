/**
 * Which model serves a turn, and the checks that keep a bad model name out of
 * a stored setting.
 *
 * The chain, first hit wins:
 *
 *   header   the model the request names (chat header picker, a job's
 *            `model_id`, a bench case)
 *   session  the session's `/model` preference
 *   default  the install default (`defaultModel` setting), when its provider
 *            is configured
 *   derived  the `recommended` model of the first configured provider, in the
 *            fixed order vertex, anthropic, openai
 *
 * A model that was named (header, session, default) and cannot be used fails;
 * it is never swapped for another. The only softening is on the install
 * default: a default whose provider is not configured is treated as unset and
 * the derived model serves instead. That is derived from evidence the system
 * can observe (which providers have credentials), not a runtime fallback: a
 * default that names a configured provider but an unknown, retired or
 * unselectable model still fails. Derivation looks at the FIRST configured
 * provider only, so a prompt carrying security telemetry never moves to a
 * different vendor because the first one's recommended model is unavailable.
 *
 * The caller passes the registry entries including retired ones
 * (`list({includeRetired: true})`) so a retired id is reported as retired.
 *
 * Pure: no I/O, no environment, no `@/` imports (unit tests load it with
 * Node's type stripping). Erasable TypeScript only.
 */

import type { ModelRef } from './types.ts';
import { PROVIDER_LABELS, PROVIDER_ORDER } from './registry/lookup.ts';
import { resolveModelRef, type ResolveErrorCode } from './registry/resolve-ref.ts';
import type { ModelEntry } from './registry/types.ts';

export type ModelSource = 'header' | 'session' | 'default' | 'derived';

export type RejectionReason = ResolveErrorCode | 'NO_PROVIDER_CONFIGURED';

export interface TurnModelInput {
  /** `model` from the request: a canonical ref or a bare id. */
  header?: string | null;
  /** The request's `provider`, used to qualify a bare header id. "auto" is ignored. */
  headerProvider?: string | null;
  /** The session's `/model` preference. */
  session?: string | null;
  /** The effective `defaultModel` setting. */
  installDefault?: string | null;
}

export interface ModelChoice {
  ok: true;
  ref: ModelRef;
  /** "provider/model" */
  canonical: string;
  source: ModelSource;
  entry: ModelEntry;
}

export interface ModelRejection {
  ok: false;
  /** The error code the chat stream carries. */
  code: 'MODEL_UNAVAILABLE';
  reason: RejectionReason;
  /** Which link of the chain named the model that failed. */
  source: ModelSource;
  /** What was asked for. Empty when nothing was (no provider configured). */
  requested: string;
  /** Operator-readable, safe to show in the chat and to store in an audit row. */
  message: string;
  /** Selectable refs close to what was asked for. */
  suggestions: string[];
  options?: string[];
}

export type TurnModelResult = ModelChoice | ModelRejection;

const NO_PROVIDER_MESSAGE =
  'No model provider is configured. Add credentials for one on the Providers page.';

function nonEmpty(v: string | null | undefined): string | undefined {
  const t = typeof v === 'string' ? v.trim() : '';
  return t || undefined;
}

function choice(entry: ModelEntry, source: ModelSource): ModelChoice {
  return {
    ok: true,
    ref: { provider: entry.provider, model: entry.model },
    canonical: entry.ref,
    source,
    entry,
  };
}

function hasProvider(entries: readonly ModelEntry[], provider: string): boolean {
  return entries.some((e) => e.provider === provider && e.providerState !== 'not_configured');
}

/** The refs the registry would currently let a chat run on, best first. */
export function selectableRefs(entries: readonly ModelEntry[], limit = 3): string[] {
  const picks: string[] = [];
  for (const provider of PROVIDER_ORDER) {
    const rec = entries.find((e) => e.provider === provider && e.recommended && e.selectable);
    if (rec) picks.push(rec.ref);
  }
  for (const e of entries) {
    if (picks.length >= limit) break;
    if (e.selectable && !picks.includes(e.ref)) picks.push(e.ref);
  }
  return picks.slice(0, limit);
}

/**
 * The model a turn uses when nothing else is chosen: the recommended model of
 * the first configured provider. `null` when no provider is configured or that
 * provider's recommended model cannot be used right now.
 */
export function deriveDefault(
  entries: readonly ModelEntry[],
): { ok: true; choice: ModelChoice } | { ok: false; reason: RejectionReason; message: string; suggestions: string[] } {
  const provider = PROVIDER_ORDER.find((p) => hasProvider(entries, p));
  if (!provider) {
    return { ok: false, reason: 'NO_PROVIDER_CONFIGURED', message: NO_PROVIDER_MESSAGE, suggestions: [] };
  }
  const rec = entries.find((e) => e.provider === provider && e.recommended);
  if (rec && rec.selectable) return { ok: true, choice: choice(rec, 'derived') };
  const which = rec ? `${PROVIDER_LABELS[provider]} model ${rec.ref}` : `${PROVIDER_LABELS[provider]} models`;
  const why = rec?.reason ? `: ${rec.reason}` : '.';
  return {
    ok: false,
    reason: 'MODEL_NOT_SELECTABLE',
    message: `No default model is set, and the recommended ${which} cannot be used right now${why}`,
    suggestions: selectableRefs(entries),
  };
}

function qualify(model: string, provider: string | null | undefined): string {
  const p = nonEmpty(provider)?.toLowerCase();
  if (!p || p === 'auto' || model.includes('/')) return model;
  return PROVIDER_ORDER.some((id) => id === p) ? `${p}/${model}` : model;
}

const SOURCE_LABEL: Record<ModelSource, string> = {
  header: 'The model you picked',
  session: 'This session is set to',
  default: "The install's default model",
  derived: 'The derived default model',
};

function advice(source: ModelSource): string {
  switch (source) {
    case 'session':
      return ' Use /model <name> to pick another model, or /model auto to follow the install default.';
    case 'default':
      return ' Choose a new default on the Models page.';
    default:
      return '';
  }
}

function rejectionFrom(
  source: ModelSource,
  requested: string,
  failure: { code: ResolveErrorCode; message: string; suggestions: string[]; options?: string[] },
): ModelRejection {
  const tail = failure.suggestions.length > 0 ? ` Try: ${failure.suggestions.join(', ')}.` : '';
  return {
    ok: false,
    code: 'MODEL_UNAVAILABLE',
    reason: failure.code,
    source,
    requested,
    message: `${SOURCE_LABEL[source]} "${requested}" is unavailable. ${failure.message}${advice(source)}${tail}`,
    suggestions: failure.suggestions,
    ...(failure.options ? { options: failure.options } : {}),
  };
}

/**
 * Pick the model for one turn. Never throws and never substitutes a model for
 * one that was named.
 */
export function resolveChatModel(
  input: TurnModelInput,
  entries: readonly ModelEntry[],
): TurnModelResult {
  // The header wins over the session preference; either one, once named, is
  // final: success or a rejection, never a step down the chain.
  const header = nonEmpty(input.header);
  const session = nonEmpty(input.session);
  const named: { source: ModelSource; text: string } | null = header
    ? { source: 'header', text: qualify(header, input.headerProvider) }
    : session
      ? { source: 'session', text: session }
      : null;
  if (named) {
    const r = resolveModelRef(named.text, entries);
    return r.ok ? choice(r.entry, named.source) : rejectionFrom(named.source, named.text, r);
  }

  const installDefault = nonEmpty(input.installDefault);
  if (installDefault) {
    const r = resolveModelRef(installDefault, entries);
    if (r.ok) return choice(r.entry, 'default');
    // A default for a provider with no credentials is as good as unset.
    if (r.code !== 'PROVIDER_NOT_CONFIGURED') return rejectionFrom('default', installDefault, r);
  }

  const derived = deriveDefault(entries);
  if (derived.ok) return derived.choice;
  return {
    ok: false,
    code: 'MODEL_UNAVAILABLE',
    reason: derived.reason,
    source: 'derived',
    requested: '',
    message:
      derived.suggestions.length > 0
        ? `${derived.message} Try: ${derived.suggestions.join(', ')}.`
        : derived.message,
    suggestions: derived.suggestions,
  };
}

/** The install default as /models shows it: the ref, and whether it was derived. */
export function describeInstallDefault(
  installDefault: string | null | undefined,
  entries: readonly ModelEntry[],
): { ref: string | null; source: 'default' | 'derived' | 'none'; problem?: string } {
  const r = resolveChatModel({ installDefault }, entries);
  if (r.ok) return { ref: r.canonical, source: r.source === 'default' ? 'default' : 'derived' };
  return { ref: null, source: 'none', problem: r.message };
}

/* ─── /model <arg> ───────────────────────────────────────────── */

export type ModelCommand =
  | { kind: 'show' }
  | { kind: 'clear' }
  | { kind: 'set'; canonical: string }
  | { kind: 'reject'; message: string; suggestions: string[] };

/**
 * Decide what `/model <arg>` does. A name is checked against the registry
 * before anything is stored, and what gets stored is the canonical ref.
 */
export function interpretModelCommand(arg: string, entries: readonly ModelEntry[]): ModelCommand {
  const text = arg.trim();
  if (!text) return { kind: 'show' };
  const lowered = text.toLowerCase();
  if (lowered === 'auto' || lowered === 'default') return { kind: 'clear' };
  const r = resolveModelRef(text, entries);
  if (r.ok) return { kind: 'set', canonical: r.canonical };
  const tail = r.suggestions.length > 0 ? ` Try: ${r.suggestions.join(', ')}.` : '';
  return {
    kind: 'reject',
    message: `Not changed. ${r.message}${tail}`,
    suggestions: r.suggestions,
  };
}

const SOURCE_PHRASE: Record<ModelSource, string> = {
  header: 'chosen in the chat header',
  session: 'this session’s /model preference',
  default: "the install's default",
  derived: 'derived: no default is set for a configured provider, so the first configured provider’s recommended model serves',
};

/** The text of `/model` with no argument. */
export function renderModelStatus(
  state: { session?: string | null; installDefault?: string | null; header?: string | null },
  entries: readonly ModelEntry[],
): string {
  const turn = resolveChatModel(
    { header: state.header, session: state.session, installDefault: state.installDefault },
    entries,
  );
  const lines: string[] = [];
  lines.push(
    turn.ok
      ? `This session runs on \`${turn.canonical}\` (${SOURCE_PHRASE[turn.source]}).`
      : `This session cannot run: ${turn.message}`,
  );
  const session = nonEmpty(state.session);
  lines.push(session ? `Session preference: \`${session}\`. \`/model auto\` clears it.` : 'Session preference: none.');
  const def = describeInstallDefault(state.installDefault, entries);
  if (def.ref) {
    lines.push(
      def.source === 'derived'
        ? `Install default: \`${def.ref}\` (derived from the first configured provider; no usable default is set).`
        : `Install default: \`${def.ref}\` (set on the Models page).`,
    );
  } else {
    lines.push(`Install default: unavailable. ${def.problem ?? ''}`.trim());
  }
  return lines.join('\n');
}

/* ─── Validation at the REST proxies ─────────────────────────── */

export interface FieldRejection {
  ok: false;
  status: 400;
  body: {
    error: string;
    code: RejectionReason | 'INVALID_MODEL';
    field: string;
    suggestions: string[];
    options?: string[];
  };
}

export type FieldValidation = { ok: true; canonical: string } | FieldRejection;

/** A model written to a setting or a job must be a string the registry resolves, and is stored canonical. */
export function validateModelField(
  value: unknown,
  field: string,
  entries: readonly ModelEntry[],
): FieldValidation {
  if (typeof value !== 'string' || !value.trim()) {
    return {
      ok: false,
      status: 400,
      body: {
        error: `${field} must be a model name such as "vertex/gemini-3.1-pro-preview".`,
        code: 'INVALID_MODEL',
        field,
        suggestions: selectableRefs(entries),
      },
    };
  }
  const r = resolveModelRef(value, entries);
  if (r.ok) return { ok: true, canonical: r.canonical };
  const tail = r.suggestions.length > 0 ? ` Try: ${r.suggestions.join(', ')}.` : '';
  return {
    ok: false,
    status: 400,
    body: {
      error: `${field}: ${r.message}${tail}`,
      code: r.code,
      field,
      suggestions: r.suggestions,
      ...(r.options ? { options: r.options } : {}),
    },
  };
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

export type BodyValidation = { ok: true; body: unknown } | FieldRejection;

/**
 * PUT /api/agent/settings: if the body sets `defaultModel`, the value must
 * resolve and is rewritten canonical. Clearing it (`clear: ["defaultModel"]`)
 * and every other key pass through untouched; the MCP is the authority on
 * those.
 */
export function validateSettingsBody(body: unknown, entries: readonly ModelEntry[]): BodyValidation {
  if (!isObject(body) || !isObject(body.updates) || !('defaultModel' in body.updates)) {
    return { ok: true, body };
  }
  const v = validateModelField(body.updates.defaultModel, 'defaultModel', entries);
  if (!v.ok) return v;
  return { ok: true, body: { ...body, updates: { ...body.updates, defaultModel: v.canonical } } };
}

/**
 * POST /api/agent/jobs and PATCH /api/agent/jobs/{name}: an absent or null
 * `model_id` means "no override" / "no change", and "" clears the override.
 * Anything else must resolve and is rewritten canonical.
 */
export function validateJobBody(body: unknown, entries: readonly ModelEntry[]): BodyValidation {
  if (!isObject(body) || !('model_id' in body)) return { ok: true, body };
  const id = body.model_id;
  if (id === null || id === undefined || id === '') return { ok: true, body };
  const v = validateModelField(id, 'model_id', entries);
  if (!v.ok) return v;
  return { ok: true, body: { ...body, model_id: v.canonical } };
}

export type ModelWriteKind = 'settings' | 'job';

/** Does this request body write a model that has to be checked? */
export function bodyTouchesModel(kind: ModelWriteKind, body: unknown): boolean {
  if (!isObject(body)) return false;
  if (kind === 'settings') return isObject(body.updates) && 'defaultModel' in body.updates;
  const id = body.model_id;
  return id !== undefined && id !== null && id !== '';
}

/** Check and canonicalize the model in a request body; bodies that write none pass through. */
export function validateModelWrite(
  kind: ModelWriteKind,
  body: unknown,
  entries: readonly ModelEntry[],
): BodyValidation {
  return kind === 'settings' ? validateSettingsBody(body, entries) : validateJobBody(body, entries);
}
