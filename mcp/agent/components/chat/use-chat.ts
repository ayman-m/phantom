"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatMessage, ChatMeta, ChatSSEEvent } from "@/lib/api/chat";
import { parseSSEEvent } from "@/lib/api/chat";
import { getSessionTelemetry } from "@/lib/api/sessions";
import type { ApprovalRequest } from "@/lib/stores/chat";

/**
 * Parse a chat-input ^command into {name, args}.
 *
 * Syntax:
 *   ^toolname                                    → {name, args:{}}
 *   ^toolname key=value other=42                 → {name, args:{key:"value", other:42}}
 *   ^toolname k=true k2=null k3=3.14             → bool/null/number coercion
 *   ^toolname key="quoted value with spaces"     → quoted strings (single OR double)
 *   ^toolname {"a":1,"b":[1,2]}                  → JSON-literal args (entire remainder)
 *
 * Auto-typing rules (key=value):
 *   - "true" / "false"           → boolean
 *   - "null"                     → null
 *   - /^-?\d+$/ (integer)        → number
 *   - /^-?\d+\.\d+$/ (float)     → number
 *   - else                       → string (quoted or unquoted; quotes stripped)
 *
 * What NOT to coerce: ISO timestamps, UUIDs, IPv4/v6, anything that
 * has dots or hyphens but isn't pure numeric. These stay as strings
 * because operators paste them as-is and coercion would mangle them.
 *
 * Returns {ok:false, error} if the command is malformed.
 */
export function parseToolCommand(text: string): {
  ok: true;
  name: string;
  args: Record<string, unknown>;
} | {
  ok: false;
  error: string;
} {
  const trimmed = text.trim();
  if (!trimmed.startsWith("^")) {
    return { ok: false, error: "command must start with '^'" };
  }
  // Strip the leading ^ and any following whitespace.
  const body = trimmed.slice(1).trimStart();
  if (!body) {
    return { ok: false, error: "missing tool name after '^'" };
  }

  // Tool name is the first whitespace-delimited token; must match the
  // MCP tool-name char class ([a-zA-Z0-9_.-]+ — alphanumeric, underscore,
  // dot, hyphen). Reject anything outside that so a stray shell-meta
  // character doesn't slip through to the route.
  const nameMatch = body.match(/^([a-zA-Z][a-zA-Z0-9_.-]*)(?:\s+(.*))?$/s);
  if (!nameMatch) {
    return {
      ok: false,
      error: `invalid tool name; expected /[a-zA-Z][a-zA-Z0-9_.-]*/ got '${body.split(/\s/)[0]}'`,
    };
  }
  const name = nameMatch[1];
  const rest = (nameMatch[2] ?? "").trim();
  if (!rest) {
    return { ok: true, name, args: {} };
  }

  // JSON-literal path: if the first non-whitespace char is '{' or '[',
  // treat the entire rest as a JSON args literal. Catches the common
  // "I want to pass a structured arg" case without a flag.
  if (rest.startsWith("{") || rest.startsWith("[")) {
    try {
      const parsed = JSON.parse(rest);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        return {
          ok: false,
          error: "JSON-literal args must be an object (got array or scalar)",
        };
      }
      return { ok: true, name, args: parsed as Record<string, unknown> };
    } catch (e) {
      return {
        ok: false,
        error: `JSON-literal args failed to parse: ${e instanceof Error ? e.message : String(e)}`,
      };
    }
  }

  // key=value pairs. Tokenize respecting double-quoted and single-quoted
  // values so an XQL query string with spaces survives a single
  // key=value pair.
  const args: Record<string, unknown> = {};
  const tokens: string[] = [];
  let i = 0;
  while (i < rest.length) {
    // skip whitespace
    while (i < rest.length && /\s/.test(rest[i])) i++;
    if (i >= rest.length) break;
    // read until next whitespace, OR if we hit `=` followed by a quote,
    // read the quoted value as part of this token
    let start = i;
    let buf = "";
    let sawEquals = false;
    while (i < rest.length) {
      const ch = rest[i];
      if (ch === "=" && !sawEquals) {
        buf += rest.slice(start, i + 1);
        i++;
        start = i;
        sawEquals = true;
        // Look for opening quote
        if (i < rest.length && (rest[i] === '"' || rest[i] === "'")) {
          const quote = rest[i];
          const end = rest.indexOf(quote, i + 1);
          if (end < 0) {
            return {
              ok: false,
              error: `unclosed ${quote} in args`,
            };
          }
          buf += rest.slice(i, end + 1);
          i = end + 1;
          start = i;
        }
        continue;
      }
      if (/\s/.test(ch) && sawEquals) {
        buf += rest.slice(start, i);
        break;
      }
      i++;
    }
    if (i >= rest.length) {
      buf += rest.slice(start);
    }
    if (buf) tokens.push(buf);
  }

  for (const tok of tokens) {
    const eq = tok.indexOf("=");
    if (eq < 0) {
      return {
        ok: false,
        error: `argument "${tok}" must be key=value (no '=' found)`,
      };
    }
    const k = tok.slice(0, eq).trim();
    let v = tok.slice(eq + 1);
    if (!k) {
      return { ok: false, error: `empty argument name in "${tok}"` };
    }
    // Strip surrounding quotes for string args.
    if (
      (v.startsWith('"') && v.endsWith('"') && v.length >= 2) ||
      (v.startsWith("'") && v.endsWith("'") && v.length >= 2)
    ) {
      args[k] = v.slice(1, -1);
      continue;
    }
    // Auto-type bool/null/number; everything else stays string.
    if (v === "true") args[k] = true;
    else if (v === "false") args[k] = false;
    else if (v === "null") args[k] = null;
    else if (/^-?\d+$/.test(v)) args[k] = Number(v);
    else if (/^-?\d+\.\d+$/.test(v)) args[k] = Number(v);
    else args[k] = v;
  }
  return { ok: true, name, args };
}

export interface UseChatOptions {
  /** Default model ID to use for requests (from workspace config). */
  defaultModel?: string;
  /** Default provider for the model. */
  defaultProvider?: string;
}

/**
 * One tool dispatch + result pair, captured for the right-side debug
 * panel. Lifted from `ToolCall` in lib/stores/chat with extra timing
 * fields the panel uses to render duration pills.
 */
export interface TelemetryToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  status: "pending" | "success" | "error";
  result?: string;
  error?: string;
  startedAt: string;
  finishedAt?: string;
  durationMs?: number;
  /** Served from the turn-cache (no MCP round-trip). */
  cached?: boolean;
}

/**
 * Compact representation of a raw SSE event — the "what just came over
 * the wire" view in the debug panel. Truncated to keep the rolling
 * stream cheap to render.
 */
export interface TelemetryEvent {
  ts: string;
  type: string;
  preview: string;
}

/**
 * Running subagent activity in this turn.
 * Tracks lifecycle of EACH subagent dispatch so the chat UI can
 * render a sidechain activity card with live tool-call progress.
 * Cleared on the parent's done event (subagent's transcript is
 * persistent on its own session id; this struct is just the
 * live-render side).
 */
export interface SubagentActivity {
  /** Subagent's session id — links to the persistent transcript. */
  subagent_session_id: string;
  agent_name: string;
  prompt: string;
  status: "running" | "completed" | "failed" | "max_turns_exceeded" | "denied";
  tool_calls: Array<{ tool: string; status: "pending" | "success" | "error" }>;
  blocked_tools: Array<{ tool: string; reason: string }>;
  final_response?: string;
  duration_ms?: number;
  error?: string;
  task_id?: string;
}

/**
 * Semantic state extracted from the new SSE
 * event kinds (compaction, context guard, cache hit). The chat header
 * badge, model-chip cache indicator, and the
 * /compress-discoverability banner all read from this struct
 * instead of digging into the rolling events array.
 */
export interface SessionTelemetryStats {
  /** Most recent compaction event (operator
   *  /compress OR auto-compaction at the budget edge). null until the
   *  first compaction lands in this session. */
  lastCompaction: {
    /** Wall-clock when the compaction_end event arrived. */
    at: string;
    /** Number of prior messages folded into the checkpoint. */
    messagesSummarized: number;
    /** Length of the summary text (rough proxy for "how compact"). */
    summaryChars: number | null;
    /** True for the "Nothing to compact yet" no-op path. */
    skipped: boolean;
    /** 'manual' for /compress, 'auto' for the budget-edge auto pass. */
    kind: 'manual' | 'auto';
  } | null;
  /** Most recent context_warning. Drives the
   *  /compress auto-suggestion banner. */
  lastContextWarning: {
    at: string;
    /** input + reserved-output token estimate the guard saw. */
    tokensTotal: number;
    /** Model context cap the estimate was compared against. */
    tokensCap: number;
    /** Computed ratio (0..1). >=0.9 is the "you should /compress" zone. */
    utilization: number;
  } | null;
  /** Most recent Vertex cache hit. Drives the
   *  cache-hit dot on the model selector chip. */
  lastCacheHit: {
    at: string;
    /** cachedContentTokenCount Vertex reported on the hit. */
    cachedTokens: number;
    /** Total prompt token count for context (so UI can compute %
     *  "of the prompt was cached"). */
    promptTokens: number | null;
  } | null;
}

const EMPTY_TELEMETRY_STATS: SessionTelemetryStats = {
  lastCompaction: null,
  lastContextWarning: null,
  lastCacheHit: null,
};

export interface UseChatReturn {
  messages: ChatMessage[];
  isStreaming: boolean;
  sessionId: string | null;
  /** Run id from the most recent `meta` event — useful for tracing
   * a single turn across audit / metrics. */
  runId: string | null;
  /** Tool dispatches + results in this session, in arrival order. */
  toolCalls: TelemetryToolCall[];
  /** Raw SSE events for the debug panel's "wire stream" tab. */
  events: TelemetryEvent[];
  /**
   * Pending approval rows surfaced inline in chat. The
   * chat stream emits `approval_pending` events when a gated tool is
   * called; we accumulate them here and clear each on resolution.
   * Operator clicks Approve/Deny in the inline ApprovalCard, which
   * calls `resolveApproval(...)`. The MCP-side bus.wait_async then
   * unblocks the underlying tool call.
   */
  pendingApprovals: ApprovalRequest[];
  resolveApproval: (
    approvalId: string,
    decision: "approved" | "denied",
    reason?: string,
  ) => Promise<void>;
  /** Semantic stats extracted from the new SSE
   *  event kinds. UI components (chat header badge, model-chip cache
   *  dot, /compress auto-suggest banner) read from this. */
  telemetryStats: SessionTelemetryStats;
  /** Live subagent activity. One entry per
   *  subagent_create dispatch. MessageList renders a SubagentCard
   *  per active/recent entry inline in the chat thread. */
  subagents: SubagentActivity[];
  sendMessage: (text: string) => void;
  resetChat: () => void;
  /** Wipe just the right-panel telemetry without resetting the chat
   * (useful on long-running sessions where the event stream gets noisy). */
  clearTelemetry: () => void;
  loadSession: (id: string, history: ChatMessage[]) => void;
  currentModel?: string;
  currentProvider?: string;
  setModel: (provider: string, model: string) => void;
}

/**
 * React hook that manages chat state and SSE streaming against the
 * `/api/proxy/v1/chat` endpoint.
 *
 * - Maintains a message list, streaming flag, and session ID.
 * - Streams assistant responses via SSE text_delta events.
 * - Persists session_id across messages for conversation continuity.
 * - Uses defaultModel/defaultProvider when provided (from workspace config).
 */
// Cap the rolling raw-event log so the debug panel stays cheap to
// render across long sessions. Tool calls keep their full history;
// only the wire-event preview list is bounded.
const MAX_EVENT_LOG = 200;

export function useChat(options?: UseChatOptions): UseChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [toolCalls, setToolCalls] = useState<TelemetryToolCall[]>([]);
  const [events, setEvents] = useState<TelemetryEvent[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalRequest[]>([]);
  const [overrideModel, setOverrideModel] = useState<string | undefined>();
  const [overrideProvider, setOverrideProvider] = useState<string | undefined>();
  // Semantic stats from compaction_*,
  // context_warning, cache_hit events. Initialized empty per session.
  const [telemetryStats, setTelemetryStats] = useState<SessionTelemetryStats>(
    EMPTY_TELEMETRY_STATS,
  );
  // Live subagent activity tracker.
  const [subagents, setSubagents] = useState<SubagentActivity[]>([]);

  // Refs to avoid stale closures inside the async sendMessage callback.
  const abortRef = useRef<AbortController | null>(null);
  const streamingRef = useRef(false);
  const sessionRef = useRef<string | null>(null);
  const optionsRef = useRef(options);
  const overrideModelRef = useRef<string | undefined>(undefined);
  const overrideProviderRef = useRef<string | undefined>(undefined);

  // Keep refs in sync with state/props so sendMessage always reads the latest.
  sessionRef.current = sessionId;
  optionsRef.current = options;
  overrideModelRef.current = overrideModel;
  overrideProviderRef.current = overrideProvider;

  // Remove the stale `chat-route-mode` localStorage key once. Route
  // selection flows from the model dropdown's persistence path, so
  // nothing writes that key; this is a cheap defensive tidy so a
  // debug session doesn't show a dead key.
  useEffect(() => {
    try {
      localStorage.removeItem("chat-route-mode");
    } catch {
      /* localStorage disabled — nothing to clean. */
    }
  }, []);

  const resetChat = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    streamingRef.current = false;
    setMessages([]);
    setIsStreaming(false);
    setSessionId(null);
    sessionRef.current = null;
    setRunId(null);
    setToolCalls([]);
    setEvents([]);
    setPendingApprovals([]);
    setTelemetryStats(EMPTY_TELEMETRY_STATS);
    setSubagents([]);
  }, []);

  /**
   * Resolve a pending approval by POSTing to the agent's proxy at
   * /api/agent/approvals/{id}/resolve. On success, the MCP-side bus
   * unblocks the underlying tool call and the chat stream continues
   * with a tool_result event.
   *
   * The local card is updated optimistically (status flips to
   * approved/denied) so the UI gives instant feedback; if the request
   * actually fails we revert.
   */
  const resolveApproval = useCallback(
    async (
      approvalId: string,
      decision: "approved" | "denied",
      reason?: string,
    ) => {
      // Optimistic flip.
      setPendingApprovals((prev) =>
        prev.map((a) =>
          a.id === approvalId ? { ...a, status: decision } : a,
        ),
      );
      try {
        const r = await fetch(
          `/api/agent/approvals/${encodeURIComponent(approvalId)}/resolve`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              decision,
              reason: reason ?? null,
              actor: "user:operator",
            }),
          },
        );
        if (!r.ok) {
          // Revert.
          setPendingApprovals((prev) =>
            prev.map((a) =>
              a.id === approvalId ? { ...a, status: "pending" } : a,
            ),
          );
          throw new Error(`resolve ${r.status}`);
        }
        // Card lingers briefly (~2s) so the operator sees the
        // approved/denied state before the fade-out, then we drop it.
        setTimeout(() => {
          setPendingApprovals((prev) => prev.filter((a) => a.id !== approvalId));
        }, 2_000);
      } catch (err) {
        console.warn("approval resolution failed:", err);
        // The card stays visible in pending state; the operator can
        // retry.
      }
    },
    [],
  );

  const clearTelemetry = useCallback(() => {
    setToolCalls([]);
    setEvents([]);
    // Also reset semantic stats. Keep this in
    // step with the rolling-events reset so the chat header badge
    // / cache dot also disappear when the operator clicks "clear
    // telemetry" on the right panel.
    setTelemetryStats(EMPTY_TELEMETRY_STATS);
    setSubagents([]);
  }, []);

  /** Load an existing session with pre-built message history.
   *
   * Tool dispatches are persisted to the messages table by the chat
   * route on every turn (one row per round-trip), so we can rehydrate
   * the right-side telemetry panel from there. Per-token text deltas
   * are NOT persisted — those stay live-only — but the tool_call /
   * tool_result wire events the panel cares about most are fully
   * recoverable. Fetch is fire-and-forget so the chat content
   * appears instantly; telemetry fills in over the next round-trip.
   */
  const loadSession = useCallback(
    (id: string, history: ChatMessage[]) => {
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
      streamingRef.current = false;
      setIsStreaming(false);
      setMessages(history);
      setSessionId(id);
      sessionRef.current = id;
      setRunId(null);
      // Reset to empty first so the panel doesn't briefly show stale
      // rows from the previous session while the fetch is in flight.
      setToolCalls([]);
      setEvents([]);
      setTelemetryStats(EMPTY_TELEMETRY_STATS);
      setSubagents([]);
      // Then fire the rehydrate. If it fails, the panel just stays
      // empty — same observable behavior as before this change. We
      // log to console.warn for debuggability without spamming the UI.
      void (async () => {
        try {
          const r = await getSessionTelemetry(id);
          if (!r.ok) {
            console.warn(
              `loadSession(${id}): telemetry rehydrate failed:`,
              r.error.message,
            );
            return;
          }
          // Race guard: if the user already loaded a different session
          // (or started a new turn) by the time the fetch resolves,
          // discard the stale data rather than overwrite live state.
          if (sessionRef.current !== id) return;
          setToolCalls(r.data.toolCalls);
          setEvents(r.data.events.slice(-MAX_EVENT_LOG));
        } catch (err) {
          console.warn(
            `loadSession(${id}): telemetry rehydrate threw:`,
            err instanceof Error ? err.message : err,
          );
        }
      })();
    },
    [],
  );

  const sendMessage = useCallback((text: string) => {
    // Guard: don't send while already streaming.
    if (streamingRef.current) return;

    // ^-prefix is a direct tool-invocation
    // escape hatch. Bypasses the LLM entirely — parses `^name args`,
    // POSTs to /api/agent/tool/call, renders the JSON result as a
    // code block in the transcript. Works even when no provider is
    // configured (the whole point — first-class debug surface for
    // fresh installs). See app/api/agent/tool/call/route.ts.
    if (text.trim().startsWith("^")) {
      const userMsg: ChatMessage = {
        role: "user",
        content: text,
        timestamp: new Date().toISOString(),
        meta: { kind: "tool_command" },
      };
      setMessages((prev) => [...prev, userMsg]);

      const placeholder: ChatMessage = {
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
        meta: { kind: "tool_command_result", status: "pending" },
      };
      setMessages((prev) => [...prev, placeholder]);

      const parsed = parseToolCommand(text);
      if (!parsed.ok) {
        setMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1] = {
            ...placeholder,
            content: JSON.stringify({ error: parsed.error }, null, 2),
            meta: { kind: "tool_command_result", status: "error", error: parsed.error },
          };
          return updated;
        });
        return;
      }

      void (async () => {
        const t0 = performance.now();
        try {
          const resp = await fetch("/api/agent/tool/call", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: parsed.name, arguments: parsed.args }),
          });
          const data = (await resp.json().catch(() => null)) as
            | {
                ok?: boolean;
                resolved_name?: string;
                result?: unknown;
                error?: string;
                duration_ms?: number;
              }
            | null;
          const dur = Math.round(performance.now() - t0);
          if (!data) {
            setMessages((prev) => {
              const updated = [...prev];
              updated[updated.length - 1] = {
                ...placeholder,
                content: JSON.stringify(
                  { error: `Empty response (HTTP ${resp.status})` },
                  null,
                  2,
                ),
                meta: {
                  kind: "tool_command_result",
                  status: "error",
                  duration_ms: dur,
                },
              };
              return updated;
            });
            return;
          }
          setMessages((prev) => {
            const updated = [...prev];
            const display = data.ok
              ? data.result === undefined
                ? { ok: true }
                : data.result
              : { ok: false, error: data.error ?? "unknown error" };
            updated[updated.length - 1] = {
              ...placeholder,
              content: JSON.stringify(display, null, 2),
              meta: {
                kind: "tool_command_result",
                status: data.ok ? "success" : "error",
                resolved_name: data.resolved_name ?? parsed.name,
                duration_ms: data.duration_ms ?? dur,
                error: data.error,
              },
            };
            return updated;
          });
        } catch (e) {
          setMessages((prev) => {
            const updated = [...prev];
            updated[updated.length - 1] = {
              ...placeholder,
              content: JSON.stringify(
                { error: e instanceof Error ? e.message : String(e) },
                null,
                2,
              ),
              meta: { kind: "tool_command_result", status: "error" },
            };
            return updated;
          });
        }
      })();
      return;
    }

    const userMsg: ChatMessage = {
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMsg]);
    streamingRef.current = true;
    setIsStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    // Request body: { message, session_id?, model?, provider? }.
    // Read from optionsRef to avoid stale closure over initial empty options.
    const currentOptions = optionsRef.current;
    const url = "/api/chat";
    const body: Record<string, string> = { message: text };
    if (sessionRef.current) {
      body.session_id = sessionRef.current;
    }
    const effectiveModel = overrideModelRef.current || currentOptions?.defaultModel;
    const effectiveProvider = overrideProviderRef.current || currentOptions?.defaultProvider;
    if (effectiveModel) {
      body.model = effectiveModel;
    }
    if (effectiveProvider) {
      body.provider = effectiveProvider;
    }

    // Placeholder assistant message that we'll append deltas into.
    const assistantMsg: ChatMessage = {
      role: "assistant",
      content: "",
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, assistantMsg]);

    // Fire-and-forget async IIFE for streaming.
    void (async () => {
      try {
        const response = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: controller.signal,
        });

        if (!response.ok) {
          const errText = await response.text().catch(() => "Request failed");
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last && last.role === "assistant") {
              updated[updated.length - 1] = { ...last, content: errText };
            }
            return updated;
          });
          return;
        }

        // Check if response is JSON (sync fallback) vs SSE stream.
        const contentType = response.headers.get("Content-Type") || "";
        if (contentType.includes("application/json")) {
          // Sync response — parse JSON directly.
          const json = await response.json().catch(() => null) as Record<string, unknown> | null;
          if (json) {
            const reply = (typeof json.reply === "string" ? json.reply : "") || "No response";
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last && last.role === "assistant") {
                updated[updated.length - 1] = { ...last, content: reply };
              }
              return updated;
            });
            // Extract session_id from sync response.
            if (typeof json.session_id === "string" && json.session_id) {
              setSessionId(json.session_id);
              sessionRef.current = json.session_id;
            }
          }
          return;
        }

        const reader = response.body?.getReader();
        if (!reader) return;

        const decoder = new TextDecoder();
        let buffer = "";

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // SSE blocks are separated by double newlines.
          const blocks = buffer.split("\n\n");
          // Last element may be an incomplete block; keep it in the buffer.
          buffer = blocks.pop() ?? "";

          for (const block of blocks) {
            if (!block.trim()) continue;
            const event: ChatSSEEvent | null = parseSSEEvent(block);
            if (!event) continue;

            handleSSEEvent(event);
          }
        }

        // Process any remaining buffered data.
        if (buffer.trim()) {
          const event = parseSSEEvent(buffer);
          if (event) {
            handleSSEEvent(event);
          }
        }
      } catch (err: unknown) {
        // AbortError is expected when the user resets mid-stream.
        if (err instanceof DOMException && err.name === "AbortError") return;

        const errMsg =
          err instanceof Error ? err.message : "Unknown streaming error";
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last && last.role === "assistant") {
            updated[updated.length - 1] = { ...last, content: errMsg };
          }
          return updated;
        });
      } finally {
        streamingRef.current = false;
        setIsStreaming(false);
        abortRef.current = null;
      }
    })();

    /** Dispatch a single SSE event to the appropriate handler. */
    function handleSSEEvent(event: ChatSSEEvent): void {
      // Mirror every event into the rolling wire-stream log first
      // (so the debug panel can show "what came over the wire even
      // when it didn't drive a state update"). Truncate previews so
      // a 200-line text_delta doesn't blow up the renderer.
      const ts = new Date().toISOString();
      const flatPreview =
        typeof event.data === "string"
          ? event.data.replace(/\s+/g, " ").slice(0, 240)
          : JSON.stringify(event.data).slice(0, 240);
      setEvents((prev) => {
        const next = [...prev, { ts, type: event.type, preview: flatPreview }];
        // Trim from the head when over cap — keeps render cost bounded.
        return next.length > MAX_EVENT_LOG
          ? next.slice(next.length - MAX_EVENT_LOG)
          : next;
      });

      switch (event.type) {
        case "text_delta": {
          try {
            const parsed: { text?: string } = JSON.parse(event.data);
            if (parsed.text) {
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last && last.role === "assistant") {
                  updated[updated.length - 1] = {
                    ...last,
                    content: last.content + parsed.text,
                  };
                }
                return updated;
              });
            }
          } catch {
            // Malformed JSON delta — skip.
          }
          break;
        }
        case "thinking": {
          // Reasoning / extended-thinking deltas. Mirrors
          // text_delta but appends to message.reasoning instead of
          // message.content, so the UI renders the reasoning in a
          // separate (collapsed-by-default) ThinkingSection above the
          // bubble. Route emits these only for Gemini parts where
          // part.thought === true (engaged when thinkingConfig
          // .includeThoughts is on).
          try {
            const parsed: { text?: string } = JSON.parse(event.data);
            if (parsed.text) {
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last && last.role === "assistant") {
                  updated[updated.length - 1] = {
                    ...last,
                    reasoning: (last.reasoning ?? "") + parsed.text,
                  };
                }
                return updated;
              });
            }
          } catch {
            // Malformed JSON delta — skip.
          }
          break;
        }
        case "meta": {
          try {
            const meta: ChatMeta & { run_id?: string } = JSON.parse(event.data);
            if (meta.session_id) {
              setSessionId(meta.session_id);
              sessionRef.current = meta.session_id;
            }
            if (meta.run_id) {
              setRunId(meta.run_id);
            }
          } catch {
            // Malformed meta — skip.
          }
          break;
        }
        case "tool_call": {
          // Backend emits `{ id, name, arguments, status: "pending" }`
          // before invoking the MCP tool. Push as a pending row; the
          // matching tool_result event resolves it with status + result.
          try {
            const data: {
              id?: string;
              name?: string;
              arguments?: Record<string, unknown>;
            } = JSON.parse(event.data);
            if (data.name) {
              const id =
                data.id ??
                `tc_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
              setToolCalls((prev) => [
                ...prev,
                {
                  id,
                  name: data.name!,
                  arguments: data.arguments ?? {},
                  status: "pending",
                  startedAt: ts,
                },
              ]);
              // Record a boundary at the current content
              // length for the LIVE assistant message. The renderer
              // splits content into "narrative" (before the LAST
              // boundary) and "answer" (after) so the operator can
              // visually separate the agent's tool-call narration
              // from its final response. See lib/api/chat.ts
              // ChatMessage.boundaryIndices for the rationale.
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last && last.role === "assistant") {
                  const boundaries = last.boundaryIndices ?? [];
                  updated[updated.length - 1] = {
                    ...last,
                    boundaryIndices: [...boundaries, last.content.length],
                  };
                }
                return updated;
              });
            }
          } catch {
            // Malformed tool_call — skip.
          }
          break;
        }
        case "approval_pending": {
          // Gated tool fired by the agent created an
          // approval row on the MCP-side bus. The chat-route's
          // pollForNewApproval(...) detected the new pending row and
          // emitted this event so we can render an inline ApprovalCard
          // while the original tool call blocks on bus.wait_async.
          // Once the operator clicks Approve/Deny the resolveApproval
          // helper POSTs to the MCP, the bus unblocks, and the
          // matching tool_result event arrives.
          try {
            const data: {
              approval_id?: string;
              tool?: string;
              args?: Record<string, unknown>;
              risk_tier?: "soft" | "destructive" | "credential" | "unknown";
              created_at?: string;
              tool_call_id?: string;
            } = JSON.parse(event.data);
            if (!data.approval_id || !data.tool) break;
            setPendingApprovals((prev) => {
              // Defensive: don't double-add if the chat-route polled
              // the same row twice (e.g. transient network blip).
              if (prev.some((a) => a.id === data.approval_id)) return prev;
              return [
                ...prev,
                {
                  id: data.approval_id!,
                  tool: data.tool!,
                  description: "",
                  arguments: data.args ?? {},
                  status: "pending",
                  riskTier:
                    data.risk_tier === "soft" ||
                    data.risk_tier === "destructive" ||
                    data.risk_tier === "credential"
                      ? data.risk_tier
                      : "soft",
                  createdAt: data.created_at,
                  toolCallId: data.tool_call_id,
                },
              ];
            });
          } catch {
            // Malformed approval_pending — skip.
          }
          break;
        }
        case "tool_result": {
          // Match by name on the most recent pending entry. Today the
          // backend doesn't echo the tool_call id in the result event,
          // so we resolve "the latest pending row with this name." If
          // multiple parallel calls of the same tool happen in a future
          // turn, the backend should start including the id here.
          try {
            const data: {
              name?: string;
              status?: "success" | "error";
              result?: string;
              error?: string;
              cached?: boolean;
            } = JSON.parse(event.data);
            if (!data.name) break;
            const finishedAt = ts;
            setToolCalls((prev) => {
              // Walk backwards to find the most recent pending matching name.
              for (let i = prev.length - 1; i >= 0; i--) {
                const tc = prev[i];
                if (tc.name === data.name && tc.status === "pending") {
                  const startMs = Date.parse(tc.startedAt);
                  const endMs = Date.parse(finishedAt);
                  const durationMs = Number.isFinite(startMs) && Number.isFinite(endMs)
                    ? endMs - startMs
                    : undefined;
                  const next = [...prev];
                  next[i] = {
                    ...tc,
                    status: data.status ?? "success",
                    result: data.result,
                    error: data.error,
                    cached: data.cached,
                    finishedAt,
                    durationMs,
                  };
                  return next;
                }
              }
              return prev;
            });
          } catch {
            // Malformed tool_result — skip.
          }
          break;
        }
        case "error": {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last && last.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                content: event.data || "An error occurred",
              };
            }
            return updated;
          });
          break;
        }
        case "done":
        case "run_completed":
          // Stream finished — the `finally` block handles cleanup.
          break;
        // Extract semantic state from the new
        // SSE event kinds (compaction, context guard, cache hit).
        case "compaction_end": {
          try {
            const data: {
              messages_summarized?: number;
              summary_chars?: number;
              skipped?: boolean;
              kind?: 'manual' | 'auto';
              covers_until?: string;
            } = JSON.parse(event.data);
            setTelemetryStats((prev) => ({
              ...prev,
              lastCompaction: {
                at: ts,
                messagesSummarized: data.messages_summarized ?? 0,
                summaryChars: data.summary_chars ?? null,
                skipped: Boolean(data.skipped),
                // Server doesn't yet differentiate kind; we infer from
                // the route emitter (manual /compress vs auto-
                // compaction in loadSessionHistory). For now treat
                // missing as 'manual' since that's the known emitter.
                kind: data.kind === 'auto' ? 'auto' : 'manual',
              },
            }));
            // Inject a synthetic compaction
            // checkpoint into the message thread so the divider
            // appears in real time, not only after a reload. Skip the
            // no-op skipped path (that's a "nothing to compact"
            // bookkeeping ack, not a real boundary in the
            // conversation).
            if (!data.skipped) {
              setMessages((prev) => {
                const checkpoint: ChatMessage = {
                  role: "system",
                  content: "",
                  timestamp: ts,
                  meta: {
                    kind: "compaction-checkpoint",
                    messages_summarized: data.messages_summarized ?? 0,
                    summary_chars: data.summary_chars ?? null,
                    covers_until: data.covers_until,
                    compaction_kind: data.kind === 'auto' ? 'auto' : 'manual',
                  },
                };
                // Insert BEFORE the empty in-flight assistant bubble at
                // the tail (the /compress turn's placeholder is empty
                // and will get text_delta injected). This way the divider
                // sits between the prior assistant turns and the
                // /compress acknowledgment, not after it.
                const last = prev[prev.length - 1];
                if (
                  last &&
                  last.role === "assistant" &&
                  last.content === ""
                ) {
                  return [
                    ...prev.slice(0, -1),
                    checkpoint,
                    last,
                  ];
                }
                return [...prev, checkpoint];
              });
            }
          } catch {
            // Malformed compaction_end — skip.
          }
          break;
        }
        case "compaction_start":
        case "compaction_failed":
          // No semantic-state extraction yet — these are visual signals
          // only (handled by the events panel).
          break;
        case "context_warning": {
          try {
            const data: {
              tokens_total?: number;
              tokens_cap?: number;
              utilization?: number;
            } = JSON.parse(event.data);
            const cap = data.tokens_cap ?? 0;
            const total = data.tokens_total ?? 0;
            const util =
              typeof data.utilization === 'number'
                ? data.utilization
                : cap > 0
                  ? total / cap
                  : 0;
            setTelemetryStats((prev) => ({
              ...prev,
              lastContextWarning: {
                at: ts,
                tokensTotal: total,
                tokensCap: cap,
                utilization: util,
              },
            }));
          } catch {
            // Malformed context_warning — skip.
          }
          break;
        }
        case "cache_hit": {
          try {
            const data: {
              cached_tokens?: number;
              prompt_tokens?: number;
            } = JSON.parse(event.data);
            setTelemetryStats((prev) => ({
              ...prev,
              lastCacheHit: {
                at: ts,
                cachedTokens: data.cached_tokens ?? 0,
                promptTokens: data.prompt_tokens ?? null,
              },
            }));
          } catch {
            // Malformed cache_hit — skip.
          }
          break;
        }
        case "session_cleared": {
          // /clear command. Server creates a
          // fresh session and emits the new id; swap our session
          // pointer so subsequent turns target the new one. The
          // followup `done` event also carries the new session_id so
          // either path lands consistently. We DON'T wipe local
          // messages/telemetry — the operator still wants to see the
          // /clear acknowledgment text and the prior conversation
          // until they reload.
          try {
            const data: { session_id?: string } = JSON.parse(event.data);
            if (data.session_id) {
              setSessionId(data.session_id);
              sessionRef.current = data.session_id;
            }
          } catch {
            // Malformed session_cleared — skip.
          }
          break;
        }
        case "model_preference_changed":
          // /model handler persisted a new
          // preferred_model. The next turn's `model` SSE event will
          // surface it; no client-side state to update yet.
          break;
        case "subagent_started": {
          // Model spawned a subagent. Open a
          // fresh activity row.
          try {
            const data: {
              subagent_session_id?: string;
              agent_name?: string;
              prompt?: string;
              task_id?: string;
            } = JSON.parse(event.data);
            if (!data.subagent_session_id || !data.agent_name) break;
            setSubagents((prev) => [
              ...prev,
              {
                subagent_session_id: data.subagent_session_id!,
                agent_name: data.agent_name!,
                prompt: data.prompt ?? "",
                status: "running",
                tool_calls: [],
                blocked_tools: [],
                task_id: data.task_id,
              },
            ]);
          } catch {
            // Malformed — skip.
          }
          break;
        }
        case "subagent_tool_call": {
          // Append a pending tool-call entry to the matching
          // subagent activity row.
          try {
            const data: {
              subagent_session_id?: string;
              tool?: string;
            } = JSON.parse(event.data);
            if (!data.subagent_session_id || !data.tool) break;
            setSubagents((prev) =>
              prev.map((s) =>
                s.subagent_session_id === data.subagent_session_id
                  ? {
                      ...s,
                      tool_calls: [
                        ...s.tool_calls,
                        { tool: data.tool!, status: "pending" },
                      ],
                    }
                  : s,
              ),
            );
          } catch {
            // Malformed — skip.
          }
          break;
        }
        case "subagent_tool_result": {
          // Resolve the most recent pending entry with this tool name.
          try {
            const data: {
              subagent_session_id?: string;
              tool?: string;
              status?: "success" | "error";
            } = JSON.parse(event.data);
            if (!data.subagent_session_id || !data.tool) break;
            setSubagents((prev) =>
              prev.map((s) => {
                if (s.subagent_session_id !== data.subagent_session_id) return s;
                const next = [...s.tool_calls];
                for (let i = next.length - 1; i >= 0; i--) {
                  if (
                    next[i].tool === data.tool &&
                    next[i].status === "pending"
                  ) {
                    next[i] = {
                      ...next[i],
                      status: data.status === "error" ? "error" : "success",
                    };
                    break;
                  }
                }
                return { ...s, tool_calls: next };
              }),
            );
          } catch {
            // Malformed — skip.
          }
          break;
        }
        case "subagent_tool_blocked": {
          // The subagent's scope filter rejected a tool. Surface
          // it on the activity card.
          try {
            const data: {
              subagent_session_id?: string;
              tool?: string;
              reason?: string;
            } = JSON.parse(event.data);
            if (!data.subagent_session_id || !data.tool) break;
            setSubagents((prev) =>
              prev.map((s) =>
                s.subagent_session_id === data.subagent_session_id
                  ? {
                      ...s,
                      blocked_tools: [
                        ...s.blocked_tools,
                        { tool: data.tool!, reason: data.reason ?? "" },
                      ],
                    }
                  : s,
              ),
            );
          } catch {
            // Malformed — skip.
          }
          break;
        }
        case "subagent_completed": {
          // Final state for this subagent run.
          try {
            const data: {
              subagent_session_id?: string;
              status?: SubagentActivity["status"];
              final_response?: string;
              duration_ms?: number;
              error?: string;
            } = JSON.parse(event.data);
            if (!data.subagent_session_id) break;
            setSubagents((prev) =>
              prev.map((s) =>
                s.subagent_session_id === data.subagent_session_id
                  ? {
                      ...s,
                      status: data.status ?? "completed",
                      final_response: data.final_response,
                      duration_ms: data.duration_ms,
                      error: data.error,
                    }
                  : s,
              ),
            );
          } catch {
            // Malformed — skip.
          }
          break;
        }
        case "plan_started":
          // Plan generation kicked off. No
          // client state yet; the loading bubble in the assistant
          // pane is sufficient feedback.
          break;
        case "plan_proposed": {
          // Inject a synthetic 'plan-proposed'
          // system message into the thread so the chat shows a
          // distinct PlanCard between user prompt and any follow-up.
          // Mirrors the compaction-divider injection
          // pattern.
          try {
            const data: {
              plan_text?: string;
              source_prompt?: string;
            } = JSON.parse(event.data);
            if (!data.plan_text) break;
            setMessages((prev) => {
              const planMsg: ChatMessage = {
                role: "system",
                content: data.plan_text!,
                timestamp: ts,
                meta: {
                  kind: "plan-proposed",
                  source_prompt: data.source_prompt,
                },
              };
              const last = prev[prev.length - 1];
              // Replace the empty in-flight assistant placeholder
              // with the plan card; the /plan handler emits
              // text_delta after this so the assistant bubble
              // gets the prose explanation.
              if (
                last &&
                last.role === "assistant" &&
                last.content === ""
              ) {
                return [...prev.slice(0, -1), planMsg, last];
              }
              return [...prev, planMsg];
            });
          } catch {
            // Malformed plan_proposed — skip.
          }
          break;
        }
        default:
          // thinking, usage, model — no-op for now (mirrored in events).
          break;
      }
    }
  }, []);

  const setModel = useCallback((provider: string, model: string) => {
    setOverrideModel(model);
    setOverrideProvider(provider);
  }, []);

  return {
    messages,
    isStreaming,
    sessionId,
    runId,
    toolCalls,
    events,
    pendingApprovals,
    resolveApproval,
    telemetryStats,
    subagents,
    sendMessage,
    resetChat,
    clearTelemetry,
    loadSession,
    currentModel: overrideModel || options?.defaultModel,
    currentProvider: overrideProvider || options?.defaultProvider,
    setModel,
  };
}
