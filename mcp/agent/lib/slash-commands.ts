/**
 * Slash command framework for the chat handler.
 *
 * Slash commands (/compress, /clear, /help, /model, /plan) plug in
 * via a single registry-table entry. An ad-hoc per-command branch in
 * the route handler grows linearly and gets harder to reason about;
 * this module is the registry pattern that avoids it.
 *
 * Architecture:
 *
 *   - `SlashCommand` describes one command: name, optional arg
 *     hint, one-line description (for /help), and an async handler.
 *   - `parseSlashCommand(text)` returns { name, args } or null.
 *     Recognizes `/<word>[ <rest>]`. Whitespace tolerant. Returns
 *     null for plain text so the handler falls through to the
 *     normal chat-turn path.
 *   - Handlers run inside the chat-route's stream. They get a
 *     context object with everything the chat handler exposes:
 *     sessionId, sendEvent, controller, runtime config, etc.
 *   - Handlers MUST close the controller before returning (the
 *     framework doesn't auto-close — handlers may want to leave
 *     the stream open for follow-up events).
 *
 * Adding a new command: define a `SlashCommand` and pass it to
 * `dispatchSlashCommand` (the registry lookup is built from the
 * handlers list the route handler passes in). The list lives in
 * route.ts so handlers can close over chat-route helpers
 * (safePersist, summarizeViaGemini, etc.) that aren't naturally
 * available to a separate module.
 */

import type { EffectiveRuntimeConfig } from '@/lib/runtime-config';

/**
 * Per-command context passed to handlers. Includes everything a
 * handler typically needs without having to plumb individual fields
 * through call sites. Most handlers only use a subset.
 */
export interface SlashCommandContext {
  /** Text after the command name. `/model gemini-2.5-pro` becomes
   *  args = "gemini-2.5-pro". Empty string for `/help`. */
  args: string;
  /** The MCP session id. Resolved by route.ts before dispatch
   *  (lazy-created if no incoming session_id). */
  sessionId: string;
  /** Was this session created on this turn? Influences /clear
   *  semantics — clearing a brand-new session is a no-op. */
  isNewSession: boolean;
  /** X-Phantom-Trigger header value, propagated to MCP audit rows. */
  trigger: string | undefined;
  /** Resolved runtime config (Gemini key, Vertex creds, MCP URL).
   *  Async-fetched once by route.ts before dispatch. */
  runtimeConfig: EffectiveRuntimeConfig;
  /** Operator-selected model override from the chat header dropdown.
   *  Undefined means handler should use the runtime default. */
  requestedModel: string | undefined;
  /** Operator-selected provider override (rare; typically `auto`). */
  requestedProvider: string | undefined;
  /** SSE event emitter. Same shape route.ts uses for normal turns. */
  sendEvent: (kind: string, data: unknown) => void;
  /** The underlying stream controller. Handlers must call `close()`
   *  before returning unless they want the stream to stay open. */
  controller: ReadableStreamDefaultController<Uint8Array>;
}

/**
 * One slash command. Registered with the dispatcher by route.ts.
 */
export interface SlashCommand {
  /** Name without leading slash. `compress`, `clear`, `help`, etc. */
  name: string;
  /** Optional shape hint shown in /help. e.g., `<model-name>` for
   *  /model. Omit for arg-less commands. */
  argHint?: string;
  /** One-line description shown in /help. Keep under ~80 chars. */
  description: string;
  /** Handler. Must `controller.close()` before returning. */
  handler: (ctx: SlashCommandContext) => Promise<void>;
}

/**
 * Parsed slash-command shape. `name` is lowercased so commands
 * are case-insensitive (`/Compress` becomes `compress`). `args` is
 * the raw text after the command, trimmed.
 */
export interface ParsedSlashCommand {
  name: string;
  args: string;
}

/**
 * Detect a slash command in the inbound message. Returns the parsed
 * shape if the message starts with `/<word>` (alphanumeric + `-_`),
 * else null. Whitespace tolerant on both sides.
 *
 * Examples:
 *   "/compress"               returns { name: "compress", args: "" }
 *   "  /clear  "              returns { name: "clear", args: "" }
 *   "/model gemini-2.5-pro"   returns { name: "model", args: "gemini-2.5-pro" }
 *   "/help compress"          returns { name: "help", args: "compress" }
 *   "what's /compress?"       returns null  (must be at the very start)
 *   "/"                       returns null  (no name)
 *   "//foo"                   returns null  (double slash, looks like a path)
 */
export function parseSlashCommand(text: string): ParsedSlashCommand | null {
  if (!text) return null;
  const trimmed = text.trim();
  // Single leading slash followed by a word char, no second slash.
  const match = /^\/([a-zA-Z][\w-]*)\s*(.*)$/.exec(trimmed);
  if (!match) return null;
  return {
    name: match[1].toLowerCase(),
    args: match[2].trim(),
  };
}

/**
 * Dispatch a parsed slash command to its handler. If `parsed.name`
 * doesn't match any registered command, emits an error event
 * suggesting /help and closes the stream.
 *
 * Returns when the handler completes (or errors). The framework
 * owns the stream lifecycle for slash-command turns: route.ts
 * should `return` after this call.
 */
export async function dispatchSlashCommand(
  parsed: ParsedSlashCommand,
  commands: readonly SlashCommand[],
  ctx: SlashCommandContext,
): Promise<void> {
  const handler = commands.find((c) => c.name === parsed.name);
  if (!handler) {
    ctx.sendEvent('error', {
      error: `Unknown slash command: /${parsed.name}. Try /help for the list.`,
      code: 'UNKNOWN_SLASH_COMMAND',
    });
    ctx.controller.close();
    return;
  }
  try {
    await handler.handler(ctx);
  } catch (err) {
    // Handler-level errors shouldn't crash the stream silently.
    // Emit error + close so the chat UI surfaces something useful.
    ctx.sendEvent('error', {
      error: `Slash command /${parsed.name} failed: ${err instanceof Error ? err.message : String(err)}`,
      code: 'SLASH_COMMAND_FAILED',
    });
    try {
      ctx.controller.close();
    } catch {
      // already closed by the handler before throwing — fine.
    }
  }
}

/**
 * Render the /help output: list available commands with one-liners.
 * Returned as a multi-line string the /help handler emits as a
 * `text_delta` event.
 *
 * Format:
 *   **Available slash commands:**
 *
 *   `/compress`              — summarize prior turns into a checkpoint
 *   `/clear`                 — end this session and start a fresh one
 *   `/help`                  — show this list
 *   `/model <name>`          — override model for the rest of this session
 *
 *   Type any command at the start of your next message.
 */
export function renderSlashHelp(commands: readonly SlashCommand[]): string {
  const sorted = [...commands].sort((a, b) => a.name.localeCompare(b.name));
  // Compute padding so the descriptions align in the rendered text.
  const usages = sorted.map((c) =>
    c.argHint ? `\`/${c.name} ${c.argHint}\`` : `\`/${c.name}\``,
  );
  const maxLen = usages.reduce((m, u) => Math.max(m, u.length), 0);
  const lines = sorted.map((c, i) => {
    const usage = usages[i].padEnd(maxLen, ' ');
    return `${usage}  — ${c.description}`;
  });
  return [
    '**Available slash commands:**',
    '',
    ...lines,
    '',
    '_Type any command at the very start of your next message._',
  ].join('\n');
}
