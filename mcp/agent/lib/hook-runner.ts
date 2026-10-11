/**
 * Hook dispatcher
 *
 * Loads registered hooks from the MCP-backed store, filters by
 * event + matcher, runs each through its declared transport
 * (command / http / agent), and aggregates the results into a
 * single decision the chat-route consumes.
 *
 * Design notes:
 *
 *   - The runner is **best-effort** by default. A hook that times
 *     out / errors falls through per its `failurePolicy`. The
 *     chat stream NEVER hangs on a hook.
 *   - Hooks run **serially within an event** (priority order),
 *     not in parallel. Reasoning: a low-priority "log to slack"
 *     hook and a high-priority "deny if production target" hook
 *     should NOT both run when the high-priority one denies. In
 *     parallel we'd waste the slack call on a denied turn.
 *   - The first hook that returns `decision: 'deny'` short-
 *     circuits the chain. `'ask'` short-circuits but still runs
 *     subsequent `injectContext`-only hooks (a "deny" beats "ask"
 *     beats "allow" beats "no-op" precedence). For non-decisional
 *     events (PostToolUse, PostCompact, etc.) every hook runs.
 *   - Hooks are loaded fresh from MCP every event firing — no
 *     in-process memoization. A 30s TTL cache could be added
 *     later, but the file is small (~1KB per hook) and the MCP
 *     round-trip is well under 100ms.
 */

import { callMcpServer } from "@/lib/mcp-proxy";
import { deriveMcpBaseUrl } from "@/lib/runtime-config";
import {
  HOOK_EVENTS,
  type Hook,
  type HookEvent,
  type HookPayload,
  type HookResult,
  matchesHook,
  validateHook,
} from "@/lib/hooks";
import { getBuiltinHook } from "@/lib/hook-builtins";

/**
 * The dispatcher's aggregate result. Reflects the highest-precedence
 * decision across all hooks that fired for the event:
 *
 *   `deny` > `ask` > `allow` > undefined
 *
 * The chat-route uses this to decide whether to proceed, surface
 * an approval card, or abort with a reason.
 */
export interface HookAggregateResult {
  decision: "allow" | "deny" | "ask" | undefined;
  /** Reason from the deciding hook (deny > ask > allow precedence).
   *  Surfaced in approval cards / abort messages. */
  reason?: string;
  /** When the deciding hook returned `replace`, the chat-route
   *  swaps this in for the original input/output. Only meaningful
   *  for PreToolUse + PostToolUse. */
  replace?: unknown;
  /** Concatenation of every fired hook's `injectContext`. The
   *  chat-route appends this to the next model turn. */
  injectContext?: string;
  /** Per-hook decisions, useful for audit logging. */
  decisions: Array<{
    hookId: string;
    name: string;
    decision: HookResult["decision"];
    reason?: string;
    durationMs: number;
    error?: string;
  }>;
}

/** Fetch all hooks for one event from the MCP store. Returns
 *  empty array when no hooks are registered or the fetch fails. */
async function loadHooks(event: HookEvent): Promise<Hook[]> {
  try {
    const data = await callMcpServer<{ hooks?: unknown[] }>(
      `/api/v1/hooks?event=${encodeURIComponent(event)}`,
      { method: "GET" },
    );
    if (!Array.isArray(data?.hooks)) return [];
    const validated: Hook[] = [];
    for (const raw of data.hooks) {
      const h = validateHook(raw);
      if (h) validated.push(h);
    }
    // Sort by priority asc (low number runs first), tie-break by id.
    validated.sort(
      (a, b) =>
        (a.priority ?? 100) - (b.priority ?? 100) || a.id.localeCompare(b.id),
    );
    return validated;
  } catch (err) {
    console.warn(
      `hooks: failed to load hooks for event ${event}:`,
      err instanceof Error ? err.message : err,
    );
    return [];
  }
}

/** Run one hook through its transport. Returns the parsed result or
 *  an error. Honors the hook's timeout. Never throws. */
async function runHook(
  hook: Hook,
  payload: HookPayload,
): Promise<{ result: HookResult | null; error?: string; durationMs: number }> {
  const startedAt = Date.now();
  const timeoutMs = hook.timeoutMs ?? 5000;
  try {
    if (hook.transport.type === "command") {
      const r = await runCommandHook(hook.transport, payload, timeoutMs);
      return { result: r, durationMs: Date.now() - startedAt };
    }
    if (hook.transport.type === "http") {
      const r = await runHttpHook(hook.transport, payload, timeoutMs);
      return { result: r, durationMs: Date.now() - startedAt };
    }
    if (hook.transport.type === "builtin") {
      const r = await runBuiltinHook(hook.transport, payload, timeoutMs);
      return { result: r, durationMs: Date.now() - startedAt };
    }
    if (hook.transport.type === "plugin") {
      const r = await runPluginHook(hook.transport, payload, timeoutMs);
      return { result: r, durationMs: Date.now() - startedAt };
    }
    // agent transport — reserved for invoking an MCP tool as a hook
    // handler. Not implemented today; plugin-contributed handlers
    // use the `plugin` transport above.
    return {
      result: null,
      error: "agent transport not implemented (reserved for MCP-tool dispatch)",
      durationMs: Date.now() - startedAt,
    };
  } catch (err) {
    return {
      result: null,
      error: err instanceof Error ? err.message : String(err),
      durationMs: Date.now() - startedAt,
    };
  }
}

/** Apply the failure policy when a hook errored / timed out. Returns
 *  the synthesized HookResult the dispatcher should treat as the
 *  hook's output. */
function applyFailurePolicy(hook: Hook, error: string): HookResult {
  const policy = hook.failurePolicy ?? "warn";
  if (policy === "block") {
    return {
      decision: "deny",
      reason: `Hook \`${hook.name}\` failed: ${error}. Blocking on policy.`,
    };
  }
  if (policy === "warn") {
    console.warn(
      `hooks: hook ${hook.name} (${hook.id}) errored, warn-allow:`,
      error,
    );
  }
  return {};
}

/**
 * Notification + PermissionRequest hook recursion defense.
 *
 * Caveat: if an operator installs a Notification
 * hook whose handler creates more notifications (e.g. a Slack-mirror
 * hook that doesn't realize the agent re-fires the hook on its own
 * mirror), the chain can recurse infinitely. A simple
 * in-process suppression prevents this: per-event, track the dispatch's id (when
 * available) and skip re-dispatch within a short window.
 *
 * Implementation:
 *   - We key by event + payload-id when one is present
 *     (Notification.notificationId, PermissionRequest.requestId).
 *   - First dispatch fires normally.
 *   - Repeat dispatches with the same key within
 *     `RECURSION_SUPPRESS_MS` get suppressed (silent no-op return,
 *     console.warn to surface the recursion to operators reading the
 *     server logs).
 *   - Keys expire after `RECURSION_SUPPRESS_MS` so the map doesn't
 *     grow unbounded.
 *
 * Not a sophisticated defense — operators who genuinely want a hook
 * to fire 10 times in 100ms on different notifications can disable
 * suppression by setting `HOOK_RECURSION_SUPPRESS_MS=0` in env.
 */
const RECURSION_SUPPRESS_MS = Number(
  globalThis.process?.env?.HOOK_RECURSION_SUPPRESS_MS ?? 5000,
);
const RECENT_DISPATCH_KEYS = new Map<string, number>();

function recursionKey(event: HookEvent, payload: HookPayload): string | null {
  if (event === "Notification") {
    const n = (payload as Extract<HookPayload, { event: "Notification" }>).notificationId;
    return n ? `Notification:${n}` : null;
  }
  if (event === "PermissionRequest") {
    const r = (payload as Extract<HookPayload, { event: "PermissionRequest" }>).requestId;
    return r ? `PermissionRequest:${r}` : null;
  }
  return null; // other events not subject to suppression
}

function pruneOldKeys(now: number): void {
  for (const [k, ts] of RECENT_DISPATCH_KEYS) {
    if (now - ts > RECURSION_SUPPRESS_MS) {
      RECENT_DISPATCH_KEYS.delete(k);
    }
  }
}

/**
 * Execute every hook registered for `event`, aggregate results.
 * Returns `decision: undefined` when no hooks fired or all
 * returned no-op.
 */
export async function dispatchHooks(
  event: HookEvent,
  payload: HookPayload,
): Promise<HookAggregateResult> {
  if (!HOOK_EVENTS.includes(event)) {
    // Defensive: an unknown event name. Treat as no hooks.
    return { decision: undefined, decisions: [] };
  }

  // Recursion suppression for Notification + PermissionRequest.
  if (RECURSION_SUPPRESS_MS > 0) {
    const key = recursionKey(event, payload);
    if (key !== null) {
      const now = Date.now();
      pruneOldKeys(now);
      const last = RECENT_DISPATCH_KEYS.get(key);
      if (last !== undefined && now - last < RECURSION_SUPPRESS_MS) {
        console.warn(
          `hooks: suppressing recursive dispatch of ${event} for ${key} ` +
            `(last fired ${now - last}ms ago; threshold ${RECURSION_SUPPRESS_MS}ms). ` +
            `If this isn't recursion, set HOOK_RECURSION_SUPPRESS_MS=0 to disable.`,
        );
        return { decision: undefined, decisions: [] };
      }
      RECENT_DISPATCH_KEYS.set(key, now);
    }
  }
  const hooks = await loadHooks(event);
  // Filter by matcher BEFORE running so we don't waste subprocess
  // spawns on hooks that don't match.
  const eligible = hooks.filter((h) => matchesHook(h, payload));

  let decision: HookAggregateResult["decision"] = undefined;
  let reason: string | undefined;
  let replace: unknown;
  const injectContextChunks: string[] = [];
  const decisions: HookAggregateResult["decisions"] = [];

  for (const hook of eligible) {
    const { result, error, durationMs } = await runHook(hook, payload);
    const effective = result ?? (error ? applyFailurePolicy(hook, error) : {});
    decisions.push({
      hookId: hook.id,
      name: hook.name,
      decision: effective.decision,
      reason: effective.reason,
      durationMs,
      error,
    });
    if (effective.injectContext) {
      injectContextChunks.push(effective.injectContext);
    }
    // Decision precedence: deny > ask > allow > undefined.
    if (effective.decision === "deny") {
      decision = "deny";
      reason = effective.reason;
      replace = effective.replace;
      break; // Short-circuit on deny; subsequent hooks would
      // be wasted work AND can't override a deny.
    }
    // Past this point a `deny` would have broken out; TS narrows
    // `decision` to "allow" | "ask" | undefined, so the redundant
    // !== "deny" checks were rejected.
    if (effective.decision === "ask") {
      decision = "ask";
      reason = effective.reason ?? reason;
      replace = effective.replace ?? replace;
      // Don't break — let injectContext-only hooks behind us still run.
    }
    if (effective.decision === "allow" && decision !== "ask") {
      decision = "allow";
      reason = effective.reason ?? reason;
      replace = effective.replace ?? replace;
    }
  }

  return {
    decision,
    reason,
    replace,
    injectContext: injectContextChunks.join("\n").trim() || undefined,
    decisions,
  };
}

// ─── Command transport ──────────────────────────────────────────────

async function runCommandHook(
  transport: Extract<Hook["transport"], { type: "command" }>,
  payload: HookPayload,
  timeoutMs: number,
): Promise<HookResult | null> {
  // Lazy import — `child_process` isn't available on the Edge
  // runtime. Phantom's chat route uses Node runtime (default).
  const { spawn } = await import("node:child_process");
  return new Promise((resolve, reject) => {
    const env = { ...process.env, ...resolveSecretEnv(transport.env ?? {}) };
    const proc = spawn(transport.command, {
      shell: true,
      cwd: transport.cwd,
      env,
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const settle = (fn: () => void) => {
      if (settled) return;
      settled = true;
      fn();
    };
    const timer = setTimeout(() => {
      proc.kill("SIGKILL");
      settle(() =>
        reject(new Error(`hook command timed out after ${timeoutMs}ms`)),
      );
    }, timeoutMs);
    proc.stdout.on("data", (b) => (stdout += b.toString()));
    proc.stderr.on("data", (b) => (stderr += b.toString()));
    proc.on("error", (err) => {
      clearTimeout(timer);
      settle(() => reject(err));
    });
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        settle(() =>
          reject(
            new Error(
              `hook command exited ${code}: ${stderr.slice(0, 200)}`,
            ),
          ),
        );
        return;
      }
      // Empty stdout = no-op (treat as {}). Otherwise parse JSON.
      const trimmed = stdout.trim();
      if (!trimmed) {
        settle(() => resolve({}));
        return;
      }
      try {
        settle(() => resolve(JSON.parse(trimmed) as HookResult));
      } catch (err) {
        settle(() =>
          reject(
            new Error(
              `hook stdout was not valid JSON: ${err instanceof Error ? err.message : err}`,
            ),
          ),
        );
      }
    });
    proc.stdin.write(JSON.stringify(payload));
    proc.stdin.end();
  });
}

// ─── HTTP transport ─────────────────────────────────────────────────

async function runHttpHook(
  transport: Extract<Hook["transport"], { type: "http" }>,
  payload: HookPayload,
  timeoutMs: number,
): Promise<HookResult | null> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...resolveSecretEnv(transport.headers ?? {}),
  };
  const resp = await fetch(transport.url, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`hook HTTP ${resp.status}: ${text.slice(0, 200)}`);
  }
  // Empty body is no-op.
  const text = await resp.text();
  if (!text.trim()) return {};
  try {
    return JSON.parse(text) as HookResult;
  } catch (err) {
    throw new Error(
      `hook HTTP body was not valid JSON: ${err instanceof Error ? err.message : err}`,
    );
  }
}

// ─── Builtin transport ──────────────────────────────────────────────

/**
 * Dispatch a builtin hook by name through the registry in
 * `lib/hook-builtins/`. Builtins run in-process — no subprocess spawn,
 * no HTTP round-trip — so we still honor the hook's `timeoutMs` via an
 * AbortController the spec receives in its `options`. Specs that ignore
 * the signal are still bounded by Promise.race against the timer.
 *
 * Defense-in-depth re-validation: even though `validateHook` re-validated
 * the config at load time, we re-check here before dispatch so a spec
 * whose schema changed between releases doesn't silently run with stale
 * fields. The cost is microseconds; the protection is real.
 */
async function runBuiltinHook(
  transport: Extract<Hook["transport"], { type: "builtin" }>,
  payload: HookPayload,
  timeoutMs: number,
): Promise<HookResult | null> {
  const spec = getBuiltinHook(transport.name);
  if (!spec) {
    throw new Error(
      `builtin '${transport.name}' is not registered in this image`,
    );
  }
  const validated = spec.validateConfig(transport.config);
  if (!validated.ok) {
    throw new Error(
      `builtin '${transport.name}' config invalid: ${validated.error}`,
    );
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const handlePromise = spec.handle(payload, validated.config, {
      signal: controller.signal,
      timeoutMs,
    });
    // Race against the timer in case the spec ignores the signal.
    const timeoutPromise = new Promise<HookResult | null>((_, reject) => {
      controller.signal.addEventListener(
        "abort",
        () =>
          reject(
            new Error(`builtin '${transport.name}' timed out after ${timeoutMs}ms`),
          ),
        { once: true },
      );
    });
    return await Promise.race([handlePromise, timeoutPromise]);
  } finally {
    clearTimeout(timer);
  }
}

// ─── Plugin-transport runner ──────────────────────────────

/**
 * Invoke a plugin-contributed handler via the MCP-side bridge.
 *
 * Plugin handlers live in Python (entry-point `phantom.hooks`). The
 * hook-runner is TypeScript. We bridge by HTTP: POST the payload + the
 * operator's config to `/api/v1/plugin-hooks/{name}/invoke` on the
 * MCP, get back `{ok, result, duration_ms, ...}`, and translate that
 * into the standard HookResult shape.
 *
 * Wire: agent's internal loopback to MCP runs over the same env vars
 * the rest of `lib/mcp-proxy.ts` uses (MCP_URL + MCP_TOKEN). We can't
 * reuse `mcp-proxy.ts` directly because it's designed for the agent →
 * MCP request-response of /api/agent/* surface; the hook bridge is a
 * different shape (raw POST with a bearer header).
 *
 * Timeout: the agent passes `timeoutMs / 1000` as the MCP's
 * `timeout_s` and ALSO arms an AbortController on the fetch so a hung
 * connection doesn't outlive the hook's own bound.
 *
 * Result translation:
 *   - ok=true, result=null   → null (no-op, same as not registering)
 *   - ok=true, result=dict   → dict cast to HookResult
 *   - ok=false               → throw with the error string; the
 *                              outer runner converts that into the
 *                              failure-policy response.
 */
async function runPluginHook(
  transport: Extract<Hook["transport"], { type: "plugin" }>,
  payload: HookPayload,
  timeoutMs: number,
): Promise<HookResult | null> {
  const mcpUrl = process.env.MCP_URL?.trim();
  const mcpToken = process.env.MCP_TOKEN?.trim();
  if (!mcpUrl || !mcpToken) {
    throw new Error(
      "plugin hook transport requires MCP_URL and MCP_TOKEN env vars",
    );
  }
  // deriveMcpBaseUrl extracts the origin (e.g. http://localhost:8080)
  // from MCP_URL=http://localhost:8080/api/v1/stream/mcp. We add the
  // /api/v1 prefix ourselves so we don't depend on MCP_URL's path.
  const origin = deriveMcpBaseUrl(mcpUrl);
  if (!origin) throw new Error(`bad MCP_URL: ${mcpUrl}`);
  const url = `${origin}/api/v1/plugin-hooks/${encodeURIComponent(transport.handlerName)}/invoke`;
  const timeoutS = transport.timeoutS ?? Math.max(1, Math.floor(timeoutMs / 1000));

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let resp: Response;
  try {
    resp = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${mcpToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        payload,
        config: transport.config ?? {},
        timeout_s: timeoutS,
      }),
      signal: controller.signal,
    });
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new Error(
        `plugin '${transport.handlerName}' fetch aborted after ${timeoutMs}ms`,
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }

  // Parse body even on non-2xx — MCP returns structured errors.
  let body: {
    ok?: boolean;
    result?: HookResult | null;
    error?: string;
    duration_ms?: number;
    handler?: string;
  };
  try {
    body = await resp.json();
  } catch {
    throw new Error(
      `plugin '${transport.handlerName}' returned non-JSON response (HTTP ${resp.status})`,
    );
  }

  if (!body.ok) {
    throw new Error(
      body.error || `plugin '${transport.handlerName}' invoke failed (HTTP ${resp.status})`,
    );
  }
  return body.result ?? null;
}

// ─── Secret resolution ──────────────────────────────────────────────

/**
 * Resolve `secret:<path>` values in env / headers maps. Secrets
 * are looked up via Phantom's runtime config (which already proxies
 * to MCP secret store / setup.json). Values that don't start with
 * `secret:` are passed through verbatim.
 *
 * Pass-through for now: hook authors embed plain env values or pull
 * from container env at runtime.
 */
function resolveSecretEnv(
  raw: Record<string, string>,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(raw)) {
    if (typeof v === "string" && v.startsWith("secret:")) {
      // Secret-store resolution is not wired here.
      // Allow pass-through to env interpolation by the
      // spawned shell.
      const envKey = v.slice("secret:".length);
      out[k] = process.env[envKey] ?? "";
    } else {
      out[k] = v;
    }
  }
  return out;
}
