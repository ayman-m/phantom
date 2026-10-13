/**
 * Backup and restore of the operator's hooks (Settings -> Hooks). A hook is
 * operator configuration, not a credential and not platform catalogue, so it
 * travels in its own section of the backup zip:
 *
 *   hooks.json   { count, hooks: [<hook as GET /api/v1/hooks returns it>],
 *                  redacted: { "<hook id>": ["transport.headers.X-Auth", ...] } }
 *
 * The one storage home is the MCP's hooks.db; the backup reads it through
 * `GET /api/v1/hooks` (every hook, disabled ones included) and restore writes
 * each hook back with `POST /api/v1/hooks`, which upserts on the hook id.
 *
 * Secrets. A hook definition can carry a secret in three places, and the
 * backup strips all three rather than writing them to the zip:
 *   - `transport.env` and `transport.headers` (command / http transports):
 *     every value that is not a `secret:<ENV_NAME>` reference;
 *   - the config fields a builtin declares as `secret-ref` (for example the
 *     slack-approval auth header value), unless they are `secret:` references;
 *   - secret-looking keys inside a plugin transport's config, whose schema the
 *     agent cannot see (matched by key name, so this one is a heuristic).
 * A `secret:<ENV_NAME>` value is a pointer to an environment variable of the
 * agent, not a secret, and is kept. What cannot be stripped without breaking
 * the hook is left alone and is a residual risk: the URL of an http hook or a
 * builtin's webhookUrl (an incoming-webhook URL can itself be a bearer token)
 * and the text of a `command`. The zip is already treated as sensitive.
 *
 * A hook that lost values is restored DISABLED, with a warning naming the
 * fields, because a blocking PreToolUse hook missing its auth header would
 * otherwise deny every tool call it matches. Under force, such a hook never
 * replaces a hook the destination already holds (the replacement would wipe
 * the destination's working secret); it is skipped with a warning instead.
 *
 * Erasable-syntax TypeScript only, and no `@/` imports, so
 * scripts/test-hooks-backup.mjs can import this file directly with Node's type
 * stripping. The route passes in what needs the builtin registry.
 */

export const HOOKS_FILE = "hooks.json";

/** A hook as the MCP returns it. Only the fields this file touches are typed. */
export interface BackedUpHook {
  id: string;
  transport?: unknown;
  enabled?: boolean;
  [k: string]: unknown;
}

export interface HooksSection {
  count: number;
  hooks: BackedUpHook[];
  /** Hook id -> dotted paths of the values that were removed. */
  redacted: Record<string, string[]>;
}

/** Names of the `secret-ref` config fields of a builtin (empty if unknown). */
export type SecretKeysForBuiltin = (builtinName: string) => readonly string[];

const SECRET_KEY_RE = /secret|token|passw|credential|api[-_]?key|auth|bearer|private/i;
const SECRET_REF_PREFIX = "secret:";

function asRecord(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {};
}

function isSecretRef(v: unknown): boolean {
  return typeof v === "string" && v.startsWith(SECRET_REF_PREFIX);
}

/** A literal (non-reference) value that is worth stripping. Empty values are not. */
function isLiteralValue(v: unknown): boolean {
  if (v === null || v === undefined) return false;
  if (typeof v === "string") return v.trim() !== "" && !isSecretRef(v);
  return true;
}

/** Copy of `map` without its literal values; removed keys are pushed to `paths`. */
function stripMap(
  map: unknown,
  prefix: string,
  paths: string[],
): Record<string, unknown> | undefined {
  if (map === undefined) return undefined;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(asRecord(map))) {
    if (isLiteralValue(v)) paths.push(`${prefix}.${k}`);
    else out[k] = v;
  }
  return out;
}

/** Recursively strip secret-looking keys that hold literal values. */
function stripByKeyName(
  value: unknown,
  prefix: string,
  paths: string[],
): unknown {
  if (Array.isArray(value)) {
    return value.map((item, i) => stripByKeyName(item, `${prefix}[${i}]`, paths));
  }
  if (value !== null && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (SECRET_KEY_RE.test(k) && typeof v === "string" && isLiteralValue(v)) {
        paths.push(`${prefix}.${k}`);
        continue;
      }
      out[k] = stripByKeyName(v, `${prefix}.${k}`, paths);
    }
    return out;
  }
  return value;
}

/**
 * The hook without its secret values, plus the dotted paths that were removed.
 * Pure; never mutates its input.
 */
export function stripHookSecrets(
  hook: BackedUpHook,
  secretKeysFor: SecretKeysForBuiltin,
): { hook: BackedUpHook; redacted: string[] } {
  const redacted: string[] = [];
  const transport = asRecord(hook.transport);
  const type = transport.type;
  let nextTransport: Record<string, unknown> = { ...transport };

  if (type === "command" && "env" in transport) {
    nextTransport.env = stripMap(transport.env, "transport.env", redacted);
  } else if (type === "http" && "headers" in transport) {
    nextTransport.headers = stripMap(transport.headers, "transport.headers", redacted);
  } else if (type === "builtin" && typeof transport.name === "string") {
    const secretKeys = new Set(secretKeysFor(transport.name));
    const config: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(asRecord(transport.config))) {
      if (secretKeys.has(k) && isLiteralValue(v)) {
        redacted.push(`transport.config.${k}`);
      } else {
        config[k] = v;
      }
    }
    nextTransport = { ...transport, config };
  } else if (type === "plugin" && "config" in transport) {
    nextTransport.config = stripByKeyName(
      transport.config,
      "transport.config",
      redacted,
    );
  }

  return { hook: { ...hook, transport: nextTransport }, redacted };
}

/** The body of hooks.json, from the MCP's list response. */
export function buildHooksSection(
  listResponse: unknown,
  secretKeysFor: SecretKeysForBuiltin,
): HooksSection {
  const list = asRecord(listResponse).hooks;
  const hooks: BackedUpHook[] = [];
  const redacted: Record<string, string[]> = {};
  if (Array.isArray(list)) {
    for (const item of list) {
      const h = asRecord(item);
      if (typeof h.id !== "string" || h.id === "") continue;
      const stripped = stripHookSecrets(h as BackedUpHook, secretKeysFor);
      hooks.push(stripped.hook);
      if (stripped.redacted.length) redacted[h.id] = stripped.redacted;
    }
  }
  return { count: hooks.length, hooks, redacted };
}

export interface HooksRestorePlan {
  /** Hook bodies to POST (the id travels in the body; the store upserts on it). */
  posts: BackedUpHook[];
  /** Hooks left alone: already on the destination, or unsafe to overwrite. */
  skipped: number;
  /** Entries in the file that could not be used. */
  invalid: number;
  /** Ids restored disabled because secret values were stripped from them. */
  disabledForSecrets: string[];
  warnings: string[];
}

function describeFields(paths: readonly string[]): string {
  return paths.join(", ");
}

/**
 * What to write on the destination. A hook the destination already holds (same
 * id) is kept unless `force` is set, like every other section. Under force a
 * hook that lost secret values still does not replace an existing hook.
 */
export function planHooksRestore(
  file: unknown,
  existingIds: Iterable<string>,
  force: boolean,
): HooksRestorePlan {
  const root = asRecord(file);
  const rawList = root.hooks;
  const total = Array.isArray(rawList) ? rawList.length : 0;
  const redactedMap = asRecord(root.redacted);
  const existing = new Set(existingIds);
  const byId = new Map<string, BackedUpHook>();
  if (Array.isArray(rawList)) {
    for (const item of rawList) {
      const h = asRecord(item);
      if (typeof h.id !== "string" || h.id === "") continue;
      if (typeof h.event !== "string" || typeof h.name !== "string") continue;
      if (Object.keys(asRecord(h.transport)).length === 0) continue;
      byId.set(h.id, h as BackedUpHook); // the last entry wins
    }
  }
  const plan: HooksRestorePlan = {
    posts: [],
    skipped: 0,
    invalid: total - byId.size,
    disabledForSecrets: [],
    warnings: [],
  };
  for (const [id, hook] of byId) {
    const lost = Array.isArray(redactedMap[id])
      ? (redactedMap[id] as unknown[]).filter((p): p is string => typeof p === "string")
      : [];
    const label = typeof hook.name === "string" ? `${hook.name} (${id})` : id;
    if (existing.has(id)) {
      if (!force) {
        plan.skipped += 1;
        continue;
      }
      if (lost.length) {
        plan.skipped += 1;
        plan.warnings.push(
          `hooks: ${label} kept as it is on the destination even with Overwrite, ` +
            `because the backup does not hold its secret values (${describeFields(lost)}) ` +
            "and overwriting would erase the ones the destination has.",
        );
        continue;
      }
    }
    if (lost.length) {
      plan.posts.push({ ...hook, enabled: false });
      plan.disabledForSecrets.push(id);
      plan.warnings.push(
        `hooks: ${label} restored disabled; the backup does not hold its secret ` +
          `values (${describeFields(lost)}). Edit the hook in Settings -> Hooks, ` +
          "enter them again, then enable it.",
      );
    } else {
      plan.posts.push(hook);
    }
  }
  return plan;
}
