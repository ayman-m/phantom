/**
 * Hook framework
 *
 * Lifecycle policy hooks for the chat handler. Adapted from SnowAgent's
 * `coreTypes.ts:HOOK_EVENTS` (`/home/user/Documents/Coding/phantom/
 * snow-agent-complete/snow-agent/10-hooks/coreTypes.ts`), filtered to
 * the events Phantom's chat-route actually fires today.
 *
 * Why hooks (vs. modifying tools):
 *
 * Enterprise SOC ops need policy that doesn't fit inside any one tool:
 *
 *   - "Block any caldera_start_operation against production hosts
 *      until #soc-ops approves" — needs PreToolUse + external comms.
 *   - "Inject the active incident's ticket id into every chat as
 *      context" — needs UserPromptSubmit.
 *   - "Notify the on-call when XSIAM detection_validation_recorded
 *      fires" — needs PostToolUse.
 *   - "Don't run /compress between 9-5 in tenant-X session" — needs
 *      PreCompact.
 *
 * Hard-coding any of those into a tool means every tool needs its own
 * policy plumbing, or we end up with 12 if-branches inside the chat-
 * route. Hooks decouple the policy from the tool: registration is
 * data, not code.
 *
 * Architecture:
 *
 *   - `HOOK_EVENTS` — closed list of fire-sites. Adding an event
 *     requires (a) appending here, (b) adding a `runHooks(event=...)`
 *     call at the corresponding chat-route point. Hooks against an
 *     unknown event name are stored but never fire.
 *   - `Hook` — a registered hook entry. Carries identity + matcher
 *     + transport + behavior config.
 *   - `HookContext` — what the dispatcher passes to each hook on
 *     fire. Per-event shape is documented inline; hooks receive a
 *     JSON payload, return a JSON `HookResult`.
 *   - `HookResult.decision` lets a hook **deny / allow / ask** for
 *     PreToolUse + PermissionRequest events; for other events the
 *     decision is informational ("succeed / fail").
 *   - Transports: `command` (subprocess), `http` (POST to a
 *     webhook), `builtin` (an in-process TypeScript handler shipped
 *     with the agent image, selected from `/settings/hooks` by name
 *     from the registry in `lib/hook-builtins/`), and `plugin` (a
 *     handler contributed by an installed entry-point package and
 *     invoked through the MCP). `agent` is reserved for invoking a
 *     tool as a hook handler and is not implemented. `command` and
 *     `http` cover bring-your-own integrations; `builtin` covers
 *     framework-side primitives (slack approval, rate-limit,
 *     memory-inject) that don't justify the subprocess / HTTP
 *     round-trip cost.
 *   - Failure policy per hook: `block` (treat hook error as deny),
 *     `allow` (treat hook error as no-op), `warn` (log + allow).
 *
 * Dispatcher: see `lib/hook-runner.ts`.
 */

import { getBuiltinHook } from "@/lib/hook-builtins";

/** Closed list of lifecycle fire-sites the chat-route emits.
 *
 * Eight events have concrete fire sites today. The remaining
 * SnowAgent events (Setup, ConfigChange, FileChanged, etc.) are
 * reserved: Setup→plan-mode hand-off, ConfigChange→/settings PUT
 * hooks, etc.
 */
export const HOOK_EVENTS = [
  /** Fired before every tool invocation. Hook may deny/allow/ask
   *  the tool call, replace the tool input, or no-op. */
  "PreToolUse",
  /** Fired after a successful tool invocation. Hook may replace the
   *  tool output, append context, or no-op. */
  "PostToolUse",
  /** Fired after a failed tool invocation. Hook may suppress the
   *  error from the model (replace with friendlier message) or
   *  no-op. */
  "PostToolUseFailure",
  /** Fired immediately after the operator submits a prompt, before
   *  the chat-route resolves history or fires the model. Hook may
   *  inject context, modify the prompt, or stop the turn entirely. */
  "UserPromptSubmit",
  /** Fired before /compress or auto-compaction starts. Hook may
   *  veto the compaction (skip-on-policy: e.g. "don't compact this
   *  session, audit needs the full transcript"). */
  "PreCompact",
  /** Fired after compaction finishes (success or failure). Hook
   *  receives the summary text + stats; may forward to an external
   *  archive. */
  "PostCompact",
  /** Fired at the start of a chat turn (after user msg persistence,
   *  before history load). Hook may abort the turn. */
  "RunStart",
  /** Fired at the end of a chat turn (after final response sent,
   *  before stream close). Hook receives turn summary; may emit
   *  notifications. */
  "RunEnd",
  /** Fired BEFORE a subagent dispatch. A hook
   *  may deny the spawn (e.g. "no red-team subagent against
   *  production tenant"). Receives parent session id, agent name,
   *  the subagent's prompt. */
  "SubagentStart",
  /** Fired AFTER a subagent run. Non-decisional;
   *  hooks typically forward result to a notification channel.
   *  Receives subagent session id, status, tool-call count. */
  "SubagentEnd",
  /** Fired whenever a notification is created on the MCP side. Lets
   *  operators route notifications externally (Slack mirror,
   *  PagerDuty webhook, etc.) without touching the agent's
   *  notification code. The MCP emits the event through the agent's
   *  internal fire-hook endpoint because the hook dispatcher lives
   *  TS-side. */
  "Notification",
  /** Fired whenever the approval queue requests operator action (a
   *  gated destructive tool, a bypass_approvals=false job's first
   *  humanRequired call). Lets operators route approvals through
   *  Slack / PagerDuty / custom approval bots. Emitted by the MCP
   *  through the same internal fire-hook endpoint as Notification. */
  "PermissionRequest",
] as const;

export type HookEvent = (typeof HOOK_EVENTS)[number];

/** Transport for a hook implementation. */
export type HookTransport =
  | {
      type: "command";
      /** Shell command to execute. The hook payload is piped to
       *  stdin as JSON; the hook's stdout is parsed as JSON for the
       *  HookResult. Non-zero exit codes follow the failure policy. */
      command: string;
      /** Working directory; absolute path or undefined for the
       *  agent's pwd. */
      cwd?: string;
      /** Extra env vars merged onto the hook's environment. Useful
       *  for passing API tokens that shouldn't be in the command
       *  string itself. Values can be `secret:<path>` to resolve
       *  via the secret store. */
      env?: Record<string, string>;
    }
  | {
      type: "http";
      /** URL to POST to. The hook payload is the body; the response
       *  body is parsed as the HookResult. */
      url: string;
      /** Extra headers merged onto the request. Same `secret:<path>`
       *  resolution as `env`. */
      headers?: Record<string, string>;
    }
  | {
      type: "agent";
      /** Name of an MCP tool to invoke. The tool's args are the
       *  hook payload; the tool's result is the HookResult.
       *  Reserved: not implemented. Plugin-contributed handlers use
       *  the `plugin` transport. */
      toolName: string;
    }
  | {
      type: "builtin";
      /** Name of a builtin spec registered in `lib/hook-builtins/`.
       *  Stored verbatim (no `builtin:` prefix — the `type` field
       *  carries that discriminator). The hook-runner dispatches via
       *  `getBuiltinHook(name)` at fire time. */
      name: string;
      /** Operator-supplied configuration for this builtin. Shape is
       *  defined by the builtin's `configFields` + validated by its
       *  `validateConfig()` at write time (in `validateHook`) and
       *  re-validated at read time before dispatch (defense-in-depth
       *  against schema-drift across releases). */
      config: Record<string, unknown>;
    }
  | {
      type: "plugin";
      /** Name of a plugin-contributed handler in the `phantom.hooks`
       *  entry-point group. Resolved + invoked server-side in MCP
       *  via `POST /api/v1/plugin-hooks/{name}/invoke` — see
       *  `usecase/plugin_hook_runner.py`. Plugin authors register
       *  these via their `pyproject.toml`:
       *
       *    [project.entry-points."phantom.hooks"]
       *    my-handler = "my_pkg.hooks:my_handler"
       *
       *  Discovery: GET /api/v1/plugin-hooks lists currently
       *  registered names; this is what the /settings/hooks UI
       *  populates the dropdown from. */
      handlerName: string;
      /** Operator-supplied config dict passed to the plugin handler.
       *  Schema is plugin-defined (no agent-side validation since
       *  we can't introspect Python entry-points from TS). The
       *  hook-runner passes it through verbatim; plugin authors
       *  document their own contract. */
      config?: Record<string, unknown>;
      /** Per-hook invocation timeout in seconds. Defaults to 5s
       *  (matches the hook's own timeoutMs default in ms units).
       *  Hard-capped at 60s server-side. */
      timeoutS?: number;
    };

/** Failure policy when the hook errors (timeout / non-zero exit /
 *  HTTP non-2xx / malformed result JSON). */
export type HookFailurePolicy =
  /** Treat as deny (PreToolUse) or stop (UserPromptSubmit/RunStart).
   *  Most paranoid; default for production policy hooks. */
  | "block"
  /** Treat as no-op (allow). Most lenient; right for "best-effort
   *  notification" hooks where a missed notification shouldn't
   *  break the chat. */
  | "allow"
  /** Treat as no-op + log a warning. Same observable behavior as
   *  `allow` from the chat's perspective. */
  | "warn";

/** Optional matcher to scope a hook to specific tools, sessions,
 *  triggers. Hook fires only when ALL non-undefined matchers pass.
 *  An empty matcher object matches every fire of the registered
 *  event. */
export interface HookMatcher {
  /** Comma-separated glob patterns over tool names. PreToolUse +
   *  PostToolUse only. Examples: `caldera_*`, `xsiam_*`,
   *  `phantom_get_*`. */
  toolGlob?: string;
  /** Substring match on the trigger header (e.g. "job:scenario-fire"
   *  matches "job:*"). For policy that only applies to scheduled
   *  runs vs. interactive chat. */
  triggerPrefix?: string;
  /** Only fire for sessions whose meta.tenant_id matches.
   *  Useful when running multi-tenant. */
  tenantId?: string;
}

/** A registered hook. Stored in the hooks JSON file and loaded at
 *  every chat-route turn (no in-process memoization yet — file is
 *  small). */
export interface Hook {
  /** Stable id (uuid). Used to update/delete via API. */
  id: string;
  /** Human-readable name shown in /settings/hooks. */
  name: string;
  /** Optional one-line description. */
  description?: string;
  /** Which lifecycle event triggers this hook. */
  event: HookEvent;
  /** When in the matcher-evaluated firing list this hook runs.
   *  Lower runs first; tie-broken by id. Default 100. */
  priority?: number;
  /** Optional scoping. Empty matcher fires for every event of
   *  this type. */
  matcher?: HookMatcher;
  /** Implementation. */
  transport: HookTransport;
  /** Hard timeout in milliseconds. Hook is killed (command) or
   *  aborted (http) past this. Default 5000. */
  timeoutMs?: number;
  /** Failure policy. Default 'warn'. */
  failurePolicy?: HookFailurePolicy;
  /** When false, the hook is skipped without running. Useful for
   *  temporary toggle without deletion. Default true. */
  enabled?: boolean;
  /** Wall-clock when the hook was created. ISO-8601. */
  createdAt: string;
  /** Wall-clock when the hook was last edited. */
  updatedAt: string;
}

/** Per-event payload the dispatcher passes to each hook. The shape
 *  is intentionally serializable (JSON) so command-transport hooks
 *  can pipe it to stdin and HTTP hooks can use it as the body.
 *
 *  Discriminated by `event`. Sub-types are documented inline. */
export type HookPayload =
  | {
      event: "PreToolUse";
      /** Session id of the chat turn invoking the tool. */
      sessionId: string;
      /** MCP tool name. */
      toolName: string;
      /** Tool arguments the model produced. Hooks may inspect
       *  these (e.g. "is the target host in production?"). */
      args: Record<string, unknown>;
      /** Operator trigger header (interactive chat is null/undefined;
       *  job-driven runs carry `job:<name>`). */
      trigger?: string;
    }
  | {
      event: "PostToolUse";
      sessionId: string;
      toolName: string;
      args: Record<string, unknown>;
      /** Tool result (may be large; hooks should not rely on full
       *  contents — use the args + status to decide). */
      result: unknown;
      durationMs: number;
      trigger?: string;
    }
  | {
      event: "PostToolUseFailure";
      sessionId: string;
      toolName: string;
      args: Record<string, unknown>;
      error: string;
      durationMs: number;
      trigger?: string;
    }
  | {
      event: "UserPromptSubmit";
      sessionId: string;
      message: string;
      trigger?: string;
    }
  | {
      event: "PreCompact";
      sessionId: string;
      kind: "manual" | "auto";
      messageCount: number;
      trigger?: string;
    }
  | {
      event: "PostCompact";
      sessionId: string;
      kind: "manual" | "auto";
      messagesSummarized: number;
      summaryChars: number | null;
      durationMs: number;
      trigger?: string;
    }
  | {
      event: "RunStart";
      sessionId: string;
      trigger?: string;
    }
  | {
      event: "RunEnd";
      sessionId: string;
      finalResponseChars: number;
      toolCallCount: number;
      durationMs: number;
      trigger?: string;
    }
  | {
      event: "SubagentStart";
      /** PARENT session id. The subagent's session id doesn't
       *  exist yet — the runner mints it after this hook approves. */
      sessionId: string;
      agentName: string;
      prompt: string;
      trigger?: string;
    }
  | {
      event: "SubagentEnd";
      /** PARENT session id. */
      sessionId: string;
      subagentSessionId: string;
      agentName: string;
      status: "completed" | "max_turns_exceeded" | "failed" | "denied";
      finalResponseChars: number;
      toolCallCount: number;
      durationMs: number;
      trigger?: string;
    }
  | {
      event: "Notification";
      /** Notification's unique id. */
      notificationId: string;
      /** Severity: info / warn / error / critical (matches the
       *  notification store's severity enum). */
      severity: string;
      /** Operator-readable category (e.g. "context-warning",
       *  "job-failed", "approval-pending"). */
      category: string;
      title: string;
      body: string;
      createdAt: string;
      /** Whichever object the notification was about, if any. */
      related?: {
        sessionId?: string;
        jobId?: string;
        instanceId?: string;
      };
    }
  | {
      event: "PermissionRequest";
      /** Approval request id (also surfaced on the approvals card). */
      requestId: string;
      /** Source of the gated tool call: chat turn vs job vs skill. */
      source: "chat-tool-call" | "job-run" | "skill-invocation";
      /** Identifiers of whichever surface drove the request. */
      actor: {
        sessionId?: string;
        jobId?: string;
        skillId?: string;
      };
      /** What the agent wanted to do. */
      requestedAction: {
        toolName: string;
        arguments: Record<string, unknown>;
      };
      /** Risk classification from the MCP-side approval gate. */
      riskTier: "read" | "write" | "destructive";
      createdAt: string;
    };

/** Hook result. The dispatcher reads this from the hook's stdout
 *  (command) / response body (http) / tool return (agent). Malformed
 *  JSON falls back to the failure policy.
 *
 *  All fields optional. The dispatcher applies per-event semantics:
 *  - For PreToolUse: `decision: 'deny'` blocks the tool call;
 *    `decision: 'ask'` triggers the standard inline approval card;
 *    `decision: 'allow'` skips the tier-gating (use sparingly!).
 *  - For UserPromptSubmit + RunStart: `decision: 'deny'` aborts
 *    the turn with `reason` as the message.
 *  - For PreCompact: `decision: 'deny'` skips compaction silently.
 *  - For other events: only `injectContext` + `metadata` are honored.
 */
export interface HookResult {
  /** Allow/deny/ask the gated action. */
  decision?: "allow" | "deny" | "ask";
  /** Operator-visible reason for the decision. Surfaced in the
   *  approval card body or the abort message. */
  reason?: string;
  /** Replace the tool's input (PreToolUse) or output (PostToolUse).
   *  When set, the chat-route uses this in place of the original
   *  shape. */
  replace?: unknown;
  /** Inject extra system-context lines into the next model turn.
   *  Used by hooks that want to "tell the model about something it
   *  didn't ask for" — e.g. injecting the active incident id on
   *  UserPromptSubmit. */
  injectContext?: string;
  /** Free-form metadata recorded on the resulting audit row.
   *  Useful for hooks that track their own counters / decisions. */
  metadata?: Record<string, unknown>;
}

/** Lightweight schema validator for hooks loaded from the JSON file.
 *  Returns a normalized hook (with defaults applied) or null on
 *  malformed input. Strict-but-forgiving: missing optional fields
 *  get defaults; unknown fields are ignored.
 *
 *  For `builtin` transports the registry's per-builtin
 *  `validateConfig()` is invoked AND a normalized config is written
 *  back into `transport.config` — meaning hooks stored before a
 *  builtin's schema changed get their stale fields stripped on the
 *  next load. Builtins that DON'T resolve in this image (renamed /
 *  removed in a later release) are rejected; the operator sees the
 *  stored hook disappear from `/settings/hooks` with a console
 *  warning, which is the right shape — silently running with stale
 *  config is the worse failure mode. */
export function validateHook(raw: unknown): Hook | null {
  if (!raw || typeof raw !== "object") return null;
  const h = raw as Partial<Hook>;
  if (
    typeof h.id !== "string" ||
    typeof h.name !== "string" ||
    typeof h.event !== "string" ||
    !HOOK_EVENTS.includes(h.event as HookEvent) ||
    !h.transport ||
    typeof h.transport !== "object" ||
    typeof h.createdAt !== "string" ||
    typeof h.updatedAt !== "string"
  ) {
    return null;
  }
  // Transport-specific minimum field check.
  let transport = h.transport as HookTransport;
  if (transport.type === "command" && typeof transport.command !== "string") {
    return null;
  }
  if (transport.type === "http" && typeof transport.url !== "string") {
    return null;
  }
  if (transport.type === "agent" && typeof transport.toolName !== "string") {
    return null;
  }
  if (transport.type === "builtin") {
    if (typeof transport.name !== "string" || !transport.name.trim()) {
      return null;
    }
    if (!transport.config || typeof transport.config !== "object") {
      return null;
    }
    // `lib/hook-builtins/types.ts` imports `HookPayload` / `HookResult`
    // from this file as TYPES ONLY (erased at runtime), so this is a
    // one-way value dependency, not a runtime cycle. The TS bundler
    // resolves the order correctly.
    const spec = getBuiltinHook(transport.name);
    if (!spec) {
      console.warn(
        `hooks: hook ${h.id} references unknown builtin '${transport.name}'; dropping`,
      );
      return null;
    }
    const result = spec.validateConfig(transport.config);
    if (!result.ok) {
      console.warn(
        `hooks: hook ${h.id} (builtin ${transport.name}) failed config validation: ${result.error}; dropping`,
      );
      return null;
    }
    transport = { type: "builtin", name: transport.name, config: result.config };
  }
  if (transport.type === "plugin") {
    // Plugin-handler transport. Lighter validation than
    // builtin: we can't introspect the Python handler's config
    // schema from TS, so we accept any JSON-object config. The MCP
    // side validates payload shape; the plugin author validates
    // their config inside the handler.
    if (
      typeof transport.handlerName !== "string" ||
      !transport.handlerName.trim()
    ) {
      console.warn(
        `hooks: hook ${h.id} has plugin transport without a handlerName; dropping`,
      );
      return null;
    }
    if (
      transport.config !== undefined &&
      (transport.config === null || typeof transport.config !== "object")
    ) {
      console.warn(
        `hooks: hook ${h.id} (plugin ${transport.handlerName}) config must be object or omitted; dropping`,
      );
      return null;
    }
    if (
      transport.timeoutS !== undefined &&
      (typeof transport.timeoutS !== "number" || transport.timeoutS <= 0)
    ) {
      console.warn(
        `hooks: hook ${h.id} (plugin ${transport.handlerName}) timeoutS must be positive number or omitted; dropping`,
      );
      return null;
    }
  }
  return {
    id: h.id,
    name: h.name,
    description: h.description,
    event: h.event as HookEvent,
    priority: typeof h.priority === "number" ? h.priority : 100,
    matcher: h.matcher,
    transport,
    timeoutMs: typeof h.timeoutMs === "number" ? h.timeoutMs : 5000,
    failurePolicy: h.failurePolicy ?? "warn",
    enabled: h.enabled !== false,
    createdAt: h.createdAt,
    updatedAt: h.updatedAt,
  };
}

/**
 * Match-or-skip a hook against an event payload's matcher fields.
 * Returns true when the hook should fire (matcher is empty or all
 * non-undefined matcher fields pass). Pure function — no I/O.
 */
export function matchesHook(hook: Hook, payload: HookPayload): boolean {
  if (hook.enabled === false) return false;
  if (hook.event !== payload.event) return false;
  const m = hook.matcher ?? {};
  if (m.toolGlob) {
    const toolName =
      payload.event === "PreToolUse" ||
      payload.event === "PostToolUse" ||
      payload.event === "PostToolUseFailure"
        ? payload.toolName
        : null;
    if (!toolName) return false;
    if (!globMatch(toolName, m.toolGlob)) return false;
  }
  if (m.triggerPrefix) {
    // `trigger` is on most payload variants but not on the
    // Notification / PermissionRequest shapes. Narrow defensively:
    // events without a trigger field never match a triggerPrefix.
    const trigger =
      "trigger" in payload && typeof payload.trigger === "string"
        ? payload.trigger
        : "";
    if (!trigger.startsWith(m.triggerPrefix)) return false;
  }
  // tenantId matching needs session-meta plumbing; punted to a
  // follow-up. For now treat it as no-op (matches everything).
  return true;
}

/**
 * Tiny glob matcher — supports `*` (any sequence) and `?` (single
 * char). Backtracking-free linear scan; safe for short tool names.
 * Returns true if `subject` matches any pattern in the
 * comma-separated list.
 */
export function globMatch(subject: string, patternList: string): boolean {
  return patternList
    .split(",")
    .map((p) => p.trim())
    .filter((p) => p.length > 0)
    .some((p) => globMatchOne(subject, p));
}

function globMatchOne(subject: string, pattern: string): boolean {
  // Convert glob to regex: escape regex chars, then `.*` for `*`,
  // `.` for `?`. Anchor.
  const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(
    "^" + escaped.replace(/\*/g, ".*").replace(/\?/g, ".") + "$",
  );
  return re.test(subject);
}
