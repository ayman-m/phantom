"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { ApprovalCard } from "@/components/chat/approval-card";
import { ChatInput } from "@/components/chat/chat-input";
import { MessageList } from "@/components/chat/message-list";
import { ChatHeader } from "@/components/chat/chat-header";
import { DebugPanel } from "@/components/chat/debug-panel";
import {
  SessionSidebar,
  type SessionSummary,
} from "@/components/chat/session-sidebar";
import { useChat } from "@/components/chat/use-chat";

// Stable localStorage key for the debug panel toggle. Lives at module
// scope so the constant doesn't re-allocate per render and stays
// trivially greppable from elsewhere.
const DEBUG_PANEL_KEY = "phantom.chat.debug-panel.open";
import type { ChatMessage } from "@/lib/api/chat";
import {
  listChatSessions,
  deleteSession,
  exportSession,
  patchSession,
  getSessionTranscript,
  type TranscriptMessage,
} from "@/lib/api/sessions";
import { listModels } from "@/lib/api/models";
import type { ModelInfo, Session } from "@/lib/api/types";
import { SparkLogo } from "@/components/sidebar";
import { confirmAction } from "@/lib/stores/confirm";
import { notify } from "@/lib/stores/notifications";

// ─── Quick Action Chips (phantom-flavored) ──────────────────────────────────

const QUICK_ACTIONS = [
  { label: "Health Check", icon: "monitor_heart", prompt: "Run a system health check across xlog, MCP, and CALDERA" },
  { label: "List Skills", icon: "auto_awesome", prompt: "Show me available simulation skills" },
  { label: "Generate Logs", icon: "data_object", prompt: "Generate 20 firewall logs with src IP 10.0.0.12" },
  { label: "Port Scan", icon: "scanner", prompt: "Create a port scan scenario against 10.10.20.5" },
  { label: "XQL Coverage", icon: "query_stats", prompt: "Run a coverage report for the last simulation batch" },
  { label: "List Connectors", icon: "cable", prompt: "Show me the active connector instances and their status" },
] as const;

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * The Spark-ported `Session` type expects `session_id` / `last_active_at`
 * / `last_model` / `total_input_tokens` / `metadata` — none of which our
 * phantom MCP returns. The MCP shape is `{id, user, started_at, ended_at,
 * title, meta, message_count}`. Rather than coerce both servers into one
 * type (the Spark type is used by other Spark-port pages we may revive),
 * we read fields off a permissive `Record<string, unknown>` and fall
 * through Spark → phantom names. This keeps the chat page working today
 * without touching every other consumer of the Spark Session type.
 */
function readStr(obj: Record<string, unknown>, ...keys: string[]): string {
  for (const k of keys) {
    const v = obj[k];
    if (typeof v === "string" && v) return v;
  }
  return "";
}

function toSessionSummary(
  session: Session | Record<string, unknown>,
  model: string,
): SessionSummary {
  const s = session as Record<string, unknown>;
  // Title comes from MCP's top-level `title`, then `meta.title`, then
  // (Spark fallback) metadata.title, finally session_key.
  const meta = (s.meta ?? s.metadata) as Record<string, unknown> | null;
  const title =
    readStr(s, "title") ||
    (typeof meta?.title === "string" ? meta.title : "") ||
    readStr(s, "session_key");
  const id = readStr(s, "id", "session_id");
  const tokensStr = readStr(s, "total_input_tokens");
  // parent_id from the sessions schema. Forked sessions render under
  // their parent.
  // Non-fork rows have parent_id NULL / undefined.
  const parentId =
    typeof s.parent_id === "string" && s.parent_id ? s.parent_id : null;
  return {
    id,
    firstMessage: title || (id ? `${id.slice(0, 12)}...` : "(untitled)"),
    // Also surface the title on the dedicated field so optimistic
    // rename updates stay coherent across reload (rename writes
    // session.title locally; toSessionSummary writes the same thing
    // when the page reloads from MCP).
    title: title || undefined,
    timestamp:
      readStr(s, "last_active_at", "updated_at", "started_at", "created_at"),
    modelBadge: readStr(s, "last_model") || model || "auto",
    tokenCount: tokensStr ? parseInt(tokensStr, 10) || 0 : 0,
    parentId,
  };
}

/**
 * Raw transcript message (as returned by getSessionTranscript) → the
 * ChatMessage shape the chat UI renders. Shared by handleSelectSession
 * and pollForPendingResponse so both paths stay
 * in sync.
 */
function mapTranscriptMessages(
  rawMessages: TranscriptMessage[],
): ChatMessage[] {
  // Keep system rows that are compaction
  // checkpoints (the transcript loader filtered to user/asst + these)
  // so MessageList can render them as in-thread dividers.
  return rawMessages.map((msg) => {
    if (msg.role === "system") {
      return {
        role: "system" as const,
        content: msg.content,
        timestamp: msg.timestamp,
        meta: msg.meta,
        // MCP message id propagation; surfaces on ChatMessage
        // so per-message Fork-from-here can bind.
        mcpId: msg.mcpId,
      };
    }
    return {
      role: msg.role === "assistant" ? ("assistant" as const) : ("user" as const),
      content: msg.content,
      timestamp: msg.timestamp,
      mcpId: msg.mcpId,
    };
  });
}

function downloadBlob(content: string, filename: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

const MIME_TYPES: Record<string, string> = {
  yaml: "text/yaml",
  json: "application/json",
  markdown: "text/markdown",
  // Wire-event trace export (JSON-shaped event-list timeline
  // derived from messages + meta). Distinct mime-type record from
  // `json` so a future UI distinction (e.g. icon, viewer) has hooks.
  events: "application/json",
};

const FILE_EXTS: Record<string, string> = {
  yaml: "yml",
  json: "json",
  markdown: "md",
  // `.events.json` so operators can tell the trace export
  // apart from the full-session `json` export at a glance in their
  // downloads folder.
  events: "events.json",
};

// ─── Page Component ──────────────────────────────────────────────────────────

export default function ChatPage() {
  // Session sidebar state
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [isLoadingSession, setIsLoadingSession] = useState(false);

  // Available models
  const [availableModels, setAvailableModels] = useState<ModelInfo[]>([]);

  // Chat hook — phantom is single-tenant, so no workspace defaults; the
  // chat handler picks the model from the runtime config (Vertex/Gemini).
  const {
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
    currentModel,
    currentProvider,
    setModel,
    // chatRoute is exposed by useChat (derived from
    // overrideProvider) but not destructured here. Selecting
    // claude-code from the model dropdown drives the route.
  } = useChat();

  // Right-side debug panel — defaults to closed; persisted in
  // localStorage so the operator's preference survives a reload.
  const [debugPanelOpen, setDebugPanelOpen] = useState(false);
  useEffect(() => {
    const stored = localStorage.getItem(DEBUG_PANEL_KEY);
    if (stored === "true") setDebugPanelOpen(true);
  }, []);
  const toggleDebugPanel = useCallback(() => {
    setDebugPanelOpen((prev) => {
      const next = !prev;
      localStorage.setItem(DEBUG_PANEL_KEY, String(next));
      return next;
    });
  }, []);

  // Subagent toggle. Defaults to true; persisted to
  // operator_state.db (NOT localStorage) per CLAUDE.md three-category
  // state model: this is operator-personal progress (a workflow
  // preference) that should follow them across devices. Optimistic
  // update + fire-and-forget PUT for snappy UX; on PUT failure we
  // log but don't revert (the next mount fetch will reconcile).
  const [subagentsEnabled, setSubagentsEnabled] = useState(true);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(
          "/api/agent/operator-state/chat_subagents_enabled",
          { method: "GET", cache: "no-store" },
        );
        if (cancelled) return;
        if (resp.status === 404) {
          // Never set — default to enabled. Don't write; let the first
          // toggle persist the explicit choice.
          return;
        }
        if (resp.ok) {
          const body = await resp.json().catch(() => null);
          if (cancelled) return;
          const raw = body?.value;
          if (typeof raw === "boolean") setSubagentsEnabled(raw);
          else if (raw && typeof raw === "object" && "enabled" in raw)
            setSubagentsEnabled(Boolean(raw.enabled));
        }
      } catch {
        // network blip — keep default ON.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);
  const toggleSubagents = useCallback(() => {
    setSubagentsEnabled((prev) => {
      const next = !prev;
      void fetch("/api/agent/operator-state/chat_subagents_enabled", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: next }),
      }).catch((err) => {
        // eslint-disable-next-line no-console
        console.warn("[chat] failed to persist subagents toggle:", err);
      });
      return next;
    });
  }, []);

  // Fetch available models on mount
  useEffect(() => {
    listModels().then((result) => {
      if (result.ok) setAvailableModels(result.data);
    });
  }, []);

  // Fetch sessions list on mount.
  //
  // Server-side filter via `exclude_scheduled=true` drops
  // job-driven sessions (rows tagged `meta.scheduled_by=<job-name>` by
  // the chat-route when X-Phantom-Trigger is `job:*`) at the SQL layer.
  // A client-side filter applied AFTER the fetch would break
  // on busy installs whose 50-row default window is 100% scheduled
  // sessions — the filter would drop all 50 and the sidebar would show empty
  // even though the operator has dozens of human sessions further back
  // in history. The server-side filter uses sqlite's json_extract
  // (`json_extract(meta_json, '$.scheduled_by') IS NULL`) so the 500-
  // row cap is filled with operator-relevant rows, not scheduler churn.
  useEffect(() => {
    void (async () => {
      const result = await listChatSessions({ excludeScheduled: true });
      if (result.ok) {
        const sorted = [...result.data].sort(
          (a, b) =>
            new Date(b.last_active_at || b.created_at).getTime() -
            new Date(a.last_active_at || a.created_at).getTime()
        );
        setSessions(sorted.map((s) => toSessionSummary(s, "auto")));
      }
    })();
  }, []);

  // Track current sessionId
  //
  // Also persists to operator_state.db (chat_last_session_id)
  // so the conversation can be restored on remount. Navigating
  // away from an in-progress or just-completed turn (e.g. via the sidebar's
  // static "Chat" link, which always points at bare "/" — see
  // components/sidebar.tsx) and back would otherwise remount ChatPage into a
  // blank "New Chat": activeSessionId resets to null on mount and the only
  // other restore path is the one-shot ?session= deep link. The completed
  // turn is saved server-side (safePersist in api/chat/route.ts) either way.
  // operator_state.db, not localStorage, per
  // CLAUDE.md's three-category state model: which conversation you were in
  // is operator-personal progress (same category as the subagent toggle
  // above, chat compose drafts, etc.), not a device-local UI preference.
  useEffect(() => {
    if (!sessionId) return;
    setActiveSessionId(sessionId);
    void fetch("/api/agent/operator-state/chat_last_session_id", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value: sessionId }),
    }).catch((err) => {
      // eslint-disable-next-line no-console
      console.warn("[chat] failed to persist last-session state:", err);
    });
  }, [sessionId]);

  // Clears the persisted last-session pointer above — called whenever the
  // operator explicitly leaves a session behind (new chat, or deleting the
  // active session) so a later restore doesn't bring back a stale/gone id.
  //
  // The DELETE call itself can occasionally 503
  // ("MCP_TOKEN not configured" from resolveMcp()), so correctness
  // must not depend on it. The restore effect below re-checks on every arrival
  // at "/" with no active session, INCLUDING right after this clear —
  // so a failed DELETE would otherwise make "New Chat" immediately
  // resurrect the old conversation. suppressRestoreRef decouples
  // correctness from that endpoint's reliability: it's set here,
  // client-side, before the (possibly-failing) network call even goes
  // out, and consumed by the very next restore-effect evaluation
  // regardless of what the DELETE actually returns.
  const suppressRestoreRef = useRef(false);
  const clearLastSessionState = useCallback(() => {
    suppressRestoreRef.current = true;
    void fetch("/api/agent/operator-state/chat_last_session_id", {
      method: "DELETE",
    }).catch(() => {
      // best-effort beyond the client-side suppression above — a stale
      // server-side pointer surviving this call only matters if the
      // operator later arrives at "/" some other way (e.g. a fresh tab)
      // with no client-side state at all, which handleSelectSession
      // already handles gracefully (falls back to an empty transcript
      // if the id turns out to be gone).
    });
  }, []);

  // Per-session approval mode. Persisted in
  // session.metadata.approval_mode via PATCH /api/agent/sessions/[id].
  // The chat handler reads it on each turn (30s server-side cache);
  // when 'bypass' it forwards X-Phantom-Approval-Bypass to MCP, which
  // makes the gate auto-approve gated tools. Default 'manual' is
  // safe: every gated tool needs operator confirmation.
  const [approvalMode, setApprovalMode] = useState<"manual" | "bypass">(
    "manual",
  );
  // Track whether the operator touched the dropdown BEFORE a
  // session existed. If they did, the next-session-creation effect
  // writes the chosen mode to the new session's metadata rather than
  // overwriting state with the GET response (which would be empty for
  // a brand-new session and revert the pre-session choice to manual).
  const preSessionApprovalIntentRef = useRef<"manual" | "bypass" | null>(null);

  // Sync approvalMode when sessionId changes — hit the per-session
  // proxy directly (not patchSession, which is for writes). Best-
  // effort; on failure we fall back to 'manual' which is the safe
  // default.
  //
  // If the operator pre-selected a mode (via the dropdown
  // BEFORE sending their first message — sessionId was null at the
  // time), this effect WRITES that intent to the new session's
  // metadata instead of reading-and-overwriting. Without that the
  // operator's pre-session choice would race with the GET and lose.
  useEffect(() => {
    if (!sessionId) {
      // No active session: reset state to the safe default, but keep
      // the pre-session intent ref so a subsequent session-creation
      // applies it.
      setApprovalMode("manual");
      return;
    }
    let cancelled = false;
    const pending = preSessionApprovalIntentRef.current;
    if (pending !== null) {
      // Operator pre-chose a mode before this session existed; write
      // it through, then clear the ref so subsequent session-switches
      // resume the GET-and-sync behaviour.
      preSessionApprovalIntentRef.current = null;
      setApprovalMode(pending);
      void (async () => {
        try {
          await fetch(
            `/api/agent/sessions/${encodeURIComponent(sessionId)}`,
            {
              method: "PATCH",
              credentials: "same-origin",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                metadata: { approval_mode: pending },
              }),
            },
          );
        } catch (err) {
          console.warn("Failed to persist pre-session approval_mode:", err);
        }
      })();
      return;
    }
    void (async () => {
      try {
        const resp = await fetch(
          `/api/agent/sessions/${encodeURIComponent(sessionId)}`,
          { method: "GET", credentials: "same-origin" },
        );
        if (!resp.ok) return;
        const data = (await resp.json()) as {
          session?: { meta?: Record<string, unknown> };
        };
        if (cancelled) return;
        const raw = data?.session?.meta?.["approval_mode"];
        setApprovalMode(raw === "bypass" ? "bypass" : "manual");
      } catch {
        // Best-effort; keep current value on error.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const handleApprovalModeChange = useCallback(
    (next: "manual" | "bypass") => {
      // Dropdown is interactive pre-session too. If no
      // sessionId yet, stash the intent in the ref and update local
      // state so the dropdown reflects the chosen mode; the session-
      // creation effect above will PATCH it once the first message
      // creates a session.
      setApprovalMode(next);
      if (!sessionId) {
        preSessionApprovalIntentRef.current = next;
        return;
      }
      // Optimistic update — the PATCH below is fire-and-forget. Worst
      // case: the server rejects (e.g. session was deleted while the
      // dropdown was open), and the next session refresh corrects.
      void (async () => {
        try {
          await fetch(
            `/api/agent/sessions/${encodeURIComponent(sessionId)}`,
            {
              method: "PATCH",
              credentials: "same-origin",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                metadata: { approval_mode: next },
              }),
            },
          );
        } catch (err) {
          console.warn("Failed to persist approval_mode:", err);
        }
      })();
    },
    [sessionId],
  );

  // Refresh sessions. Uses the same server-side `exclude_scheduled`
  // filter as the initial mount fetch above — see that hook's comment
  // for the architectural background.
  const refreshSessions = useCallback(() => {
    void (async () => {
      const result = await listChatSessions({ excludeScheduled: true });
      if (result.ok) {
        const sorted = [...result.data].sort(
          (a, b) =>
            new Date(b.last_active_at || b.created_at).getTime() -
            new Date(a.last_active_at || a.created_at).getTime()
        );
        setSessions(sorted.map((s) => toSessionSummary(s, "auto")));
      }
    })();
  }, []);

  // ── Real-time session list ──────────────────────────────────────
  //
  // The list refreshes on mount, on this tab's own actions (finishing a
  // turn, rename, delete), and on activity from anywhere else — the REST
  // API, a scheduled job, a second browser tab — so a chat created
  // elsewhere appears without a reload.
  //
  // Rather than add a server surface, this subscribes to the audit SSE
  // feed that already exists (/api/agent/audit/stream, proxied so the
  // browser never holds MCP_TOKEN). Chat activity already emits audit
  // rows there — `message_appended` per persisted message and
  // `chat_turn_cost` targeting `session:<id>` — so the events needed are
  // already flowing.
  //
  // `initial=0` is load-bearing: the stream replays its most recent 50
  // rows on connect by default, which would fire a refresh burst every
  // time this mounts.
  //
  // NOTE: initial=0 suppresses the replay because the MCP special-cases
  // it (a `limit <= 0` would otherwise become SQL `LIMIT -1`, which is
  // unlimited). Keep this in step with api/audit.py.
  useEffect(() => {
    let es: EventSource | null = null;
    let debounce: ReturnType<typeof setTimeout> | null = null;
    let closed = false;
    let backoff = 1000;

    // Coalesce bursts: one chat turn emits several audit rows, and we
    // only ever need one list refresh for the lot.
    const scheduleRefresh = () => {
      if (debounce) clearTimeout(debounce);
      debounce = setTimeout(() => refreshSessions(), 800);
    };

    const isSessionRelevant = (action: string, target: string) =>
      action === "message_appended" ||
      action === "chat_turn_cost" ||
      action.startsWith("session_") ||
      target.startsWith("session:");

    const connect = () => {
      if (closed) return;
      try {
        es = new EventSource("/api/agent/audit/stream?initial=0");
      } catch {
        return; // EventSource unavailable — focus/visibility below still covers us
      }
      es.onmessage = (ev) => {
        try {
          const row = JSON.parse(ev.data) as {
            action?: string;
            target?: string;
          };
          if (isSessionRelevant(row.action || "", row.target || "")) {
            scheduleRefresh();
          }
        } catch {
          // Heartbeats and non-JSON frames are expected; ignore.
        }
      };
      es.onopen = () => {
        backoff = 1000;
      };
      es.onerror = () => {
        // EventSource auto-reconnects, but a proxy that closes the
        // stream outright can leave it dead. Rebuild with backoff.
        es?.close();
        es = null;
        if (closed) return;
        setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, 30000);
      };
    };
    connect();

    // Safety net, and the cheap fix on its own merits: if the stream is
    // ever down, coming back to the tab still reconciles the list.
    const onVisible = () => {
      if (document.visibilityState === "visible") scheduleRefresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);

    return () => {
      closed = true;
      if (debounce) clearTimeout(debounce);
      es?.close();
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
  }, [refreshSessions]);

  // Auto-save session title on first user message. The server already
  // does this on lazy-create (see /api/chat route), but doing it client-
  // side too means: (a) the sidebar refreshes immediately rather than
  // waiting for the next manual list, and (b) if the operator typed a
  // longer first message than 60 chars, we still get a clean preview.
  // Field is top-level `title` (MCP's update_session accepts it directly);
  // earlier this set `metadata.title` which the MCP didn't read, so
  // titles were never persisted.
  const titleSavedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!sessionId) return;
    if (titleSavedRef.current === sessionId) return;
    const firstUserMsg = messages.find((m) => m.role === "user");
    if (!firstUserMsg) return;
    titleSavedRef.current = sessionId;
    const trimmed = firstUserMsg.content.trim();
    const title =
      trimmed.length > 60 ? `${trimmed.slice(0, 60).trimEnd()}…` : trimmed;
    if (!title) return;
    void (async () => {
      await patchSession(sessionId, { title });
      refreshSessions();
    })();
  }, [sessionId, messages, refreshSessions]);

  // Derived values
  const modelLabel = currentModel
    ? `${currentProvider ?? "auto"}/${currentModel}`
    : "auto";

  const firstUserMessage = messages.find((m) => m.role === "user");
  const sessionTitle = firstUserMessage
    ? firstUserMessage.content.slice(0, 60)
    : "New Chat";

  // Live reconnect for a session whose last
  // turn was still generating when the operator navigated away. The
  // session restore loads whatever was persisted
  // AT THE MOMENT of the fetch — if that's mid-generation, the
  // transcript's last message is the operator's own (no assistant
  // reply yet), and without this, it just stays that way: no error, no
  // indicator, nothing, until the operator manually reselects or
  // reloads. This polls the transcript every few seconds until the
  // assistant's reply lands, then loads the complete history and stops
  // — capped so a genuinely failed/abandoned turn doesn't poll forever.
  //
  // isAwaitingLiveResponse drives a small pulse indicator (below, in
  // the JSX) styled to match MessageList's own streaming-dots — not
  // wired through useChat's isStreaming because loadSession always
  // resets that to false (it's meant for THIS page's own live sends,
  // not a reconnect to a turn some other tab/session-visit started).
  const [isAwaitingLiveResponse, setIsAwaitingLiveResponse] = useState(false);
  const pollGenerationRef = useRef<{ id: string; cancelled: boolean } | null>(
    null,
  );
  const stopPolling = useCallback(() => {
    if (pollGenerationRef.current) pollGenerationRef.current.cancelled = true;
    pollGenerationRef.current = null;
    setIsAwaitingLiveResponse(false);
  }, []);
  const pollForPendingResponse = useCallback(
    (id: string) => {
      if (pollGenerationRef.current) pollGenerationRef.current.cancelled = true;
      const token = { id, cancelled: false };
      pollGenerationRef.current = token;
      setIsAwaitingLiveResponse(true);

      const POLL_INTERVAL_MS = 3000;
      const MAX_ATTEMPTS = 30; // ~90s ceiling — then quietly give up.
      let attempts = 0;

      const tick = async () => {
        if (token.cancelled) return;
        attempts += 1;
        try {
          const result = await getSessionTranscript(id);
          if (token.cancelled) return;
          if (result.ok) {
            const rawMessages = result.data?.messages ?? [];
            const last = rawMessages[rawMessages.length - 1];
            if (last && last.role === "assistant") {
              loadSession(id, mapTranscriptMessages(rawMessages));
              if (pollGenerationRef.current === token) {
                pollGenerationRef.current = null;
                setIsAwaitingLiveResponse(false);
              }
              return;
            }
          }
        } catch {
          // transient — keep polling until the attempt ceiling below
        }
        if (token.cancelled || attempts >= MAX_ATTEMPTS) {
          if (pollGenerationRef.current === token) {
            pollGenerationRef.current = null;
            setIsAwaitingLiveResponse(false);
          }
          return;
        }
        setTimeout(tick, POLL_INTERVAL_MS);
      };
      setTimeout(tick, POLL_INTERVAL_MS);
    },
    [loadSession],
  );

  // Handlers
  const handleNewChat = useCallback(() => {
    stopPolling();
    resetChat();
    setActiveSessionId(null);
    clearLastSessionState();
  }, [resetChat, clearLastSessionState, stopPolling]);

  const handleSelectSession = useCallback(
    (id: string) => {
      if (id === activeSessionId) return;
      stopPolling();
      setActiveSessionId(id);
      setIsLoadingSession(true);
      void (async () => {
        try {
          const result = await getSessionTranscript(id);
          if (!result.ok) {
            loadSession(id, []);
            return;
          }
          const rawMessages = result.data?.messages ?? [];
          const history = mapTranscriptMessages(rawMessages);
          loadSession(id, history);
          const last = rawMessages[rawMessages.length - 1];
          if (last && last.role === "user") {
            pollForPendingResponse(id);
          }
        } catch {
          loadSession(id, []);
        } finally {
          setIsLoadingSession(false);
        }
      })();
    },
    [activeSessionId, loadSession, stopPolling, pollForPendingResponse]
  );

  // Deep-link support: /?session=<id> selects + loads that session.
  // Used by the job detail page's "Open conversation" link, which hands
  // the operator from a chat-job run to the underlying transcript. When
  // there's no explicit ?session= param, falls back to the last-active
  // session persisted in operator_state.db (see the "Track current
  // sessionId" effect above) — this is what restores your conversation
  // after navigating away and back.
  //
  // This must not be gated on a useRef "have I run once" guard, which
  // assumes that leaving "/" and coming back always remounts ChatPage
  // fresh. That assumption is wrong: Next.js App Router's client-side
  // navigation (clicking a sidebar link, the normal way an operator
  // moves around the product) does NOT reliably tear down and recreate
  // this component — it can keep the same instance alive across the
  // round trip. A mount-scoped ref only ever fires ONCE for the tab's
  // entire lifetime in that case, so the restore would silently stop
  // working after the first navigation away and back.
  //
  // The effect is reactive on pathname + activeSessionId: usePathname()'s
  // VALUE updates on every navigation regardless of whether the
  // component itself remounts, so this effect re-evaluates every time
  // the operator arrives back at "/" — not just on a component's first
  // mount ever. Only fires when activeSessionId is currently empty, so
  // it can never clobber a session the operator is actively viewing or
  // just explicitly switched to. suppressRestoreRef (set by
  // clearLastSessionState, consumed here) stops this from immediately
  // undoing an explicit "New Chat" / delete-active-session action —
  // see that callback's comment.
  const pathname = usePathname();
  const searchParams = useSearchParams();
  useEffect(() => {
    if (pathname !== "/") return;
    if (activeSessionId) return;
    if (suppressRestoreRef.current) {
      suppressRestoreRef.current = false;
      return;
    }
    const urlTarget = searchParams.get("session");
    if (urlTarget) {
      handleSelectSession(urlTarget);
      return;
    }
    void (async () => {
      try {
        const resp = await fetch(
          "/api/agent/operator-state/chat_last_session_id",
          { cache: "no-store" },
        );
        if (!resp.ok) return; // 404 = never set — stay on empty New Chat
        const body = await resp.json().catch(() => null);
        const target = typeof body?.value === "string" ? body.value : "";
        if (target) handleSelectSession(target);
      } catch {
        // network blip — stay on the empty New Chat state
      }
    })();
  }, [pathname, activeSessionId, searchParams, handleSelectSession]);

  const handleDeleteSession = useCallback(
    (id: string) => {
      void (async () => {
        // One in-app confirmation for every delete entry point (the sidebar
        // row menu and the chat header's trash button).
        const target = sessions.find((x) => x.id === id);
        const label = target?.title || target?.firstMessage || "this session";
        const accepted = await confirmAction({
          title: `Delete "${label}"?`,
          message:
            "The conversation and its messages are removed. This cannot be undone.",
          confirmLabel: "Delete",
          tone: "danger",
        });
        if (!accepted) return;
        const result = await deleteSession(id);
        if (result.ok) {
          setSessions((prev) => prev.filter((s) => s.id !== id));
          if (activeSessionId === id) {
            resetChat();
            setActiveSessionId(null);
            clearLastSessionState();
          }
        } else {
          notify("error", "Could not delete the session", result.error.message);
        }
      })();
    },
    [sessions, activeSessionId, resetChat, clearLastSessionState]
  );

  // Rename an existing session.
  // The MCP exposes PATCH /api/v1/sessions/{id} that accepts {title}
  // (see lib/api/sessions.ts:patchSession). This handler:
  //   1. Optimistically updates local state so the sidebar reflects
  //      the change immediately.
  //   2. Fires the PATCH; on failure, reverts the local state and
  //      shows an error toast.
  const handleRenameSession = useCallback(
    (id: string, title: string) => {
      const trimmed = title.trim();
      if (!trimmed) return;
      let prevTitle: string | undefined;
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== id) return s;
          prevTitle = s.title;
          return { ...s, title: trimmed };
        }),
      );
      void (async () => {
        const result = await patchSession(id, { title: trimmed });
        if (!result.ok) {
          console.warn(
            `rename session ${id}: PATCH failed:`,
            result.error.message,
          );
          // Revert optimistic update on failure.
          setSessions((prev) =>
            prev.map((s) => (s.id === id ? { ...s, title: prevTitle } : s)),
          );
          notify("error", "Could not rename the session", result.error.message);
        }
      })();
    },
    [],
  );

  // Fork-from-here per-message. Same
  // backend path as handleForkSession but passes from_message_id so
  // the MCP-side fork_session() cut-off is precise (vs forking the
  // full conversation). Uses the active session id implicitly + the
  // message's MCP id from the AssistantMessage's onFork callback.
  const handleForkFromMessage = useCallback(
    (mcpMessageId: string) => {
      const parentId = activeSessionId;
      if (!parentId) return;
      void (async () => {
        try {
          const r = await fetch(
            `/api/agent/sessions/${encodeURIComponent(parentId)}/fork`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ from_message_id: mcpMessageId }),
            },
          );
          if (!r.ok) {
            const text = await r.text();
            console.warn(
              `fork-from-message ${parentId}/${mcpMessageId} failed:`,
              r.status,
              text.slice(0, 200),
            );
            return;
          }
          const data = (await r.json()) as {
            session?: { id?: string };
          };
          const newId = data.session?.id;
          if (!newId) {
            console.warn(
              `fork-from-message ${parentId}/${mcpMessageId}: response missing session.id`,
            );
            return;
          }
          await refreshSessions();
          handleSelectSession(newId);
        } catch (err) {
          console.warn(
            `fork-from-message ${parentId}/${mcpMessageId} crashed:`,
            err,
          );
        }
      })();
    },
    [activeSessionId, refreshSessions, handleSelectSession],
  );

  // Fork session. POSTs to the
  // agent's fork proxy (which proxies to MCP's fork API which copies
  // the parent's message history into the new session). On success,
  // refreshes the session list + switches to the new session.
  const handleForkSession = useCallback(
    (id: string) => {
      void (async () => {
        try {
          const r = await fetch(
            `/api/agent/sessions/${encodeURIComponent(id)}/fork`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({}),
            },
          );
          if (!r.ok) {
            const text = await r.text();
            console.warn(
              `fork session ${id} failed:`,
              r.status,
              text.slice(0, 200),
            );
            return;
          }
          const data = (await r.json()) as {
            session?: { id?: string; title?: string };
          };
          const newId = data.session?.id;
          if (!newId) {
            console.warn(`fork session ${id}: response missing session.id`);
            return;
          }
          // Refresh the session list so the new fork appears in the
          // sidebar, then switch to it.
          await refreshSessions();
          handleSelectSession(newId);
        } catch (err) {
          console.warn(`fork session ${id} crashed:`, err);
        }
      })();
    },
    [refreshSessions, handleSelectSession],
  );

  const handleExportSession = useCallback(
    (id: string, format: "yaml" | "json" | "markdown" | "events") => {
      void (async () => {
        const result = await exportSession(id, format);
        if (result.ok) {
          const ext = FILE_EXTS[format] ?? format;
          const mime = MIME_TYPES[format] ?? "text/plain";
          downloadBlob(result.data, `session-${id.slice(0, 8)}.${ext}`, mime);
          return;
        }
        // Surface failure to the operator. Silently swallowing
        // `result.ok === false` would make a failing export look
        // identical to "the feature is missing": the operator clicks
        // Export, nothing happens, no error appears anywhere.
        const detail = result.error || "Unknown error";
        // console.error so the failure is captured for devtools / log
        // capture, in addition to the operator-facing toast.
        // eslint-disable-next-line no-console
        console.error(
          `[chat] session export failed (id=${id.slice(0, 8)} format=${format}):`,
          detail,
        );
        notify("error", `Export failed (format=${format})`, detail);
      })();
    },
    []
  );

  const handleExportCurrent = useCallback(
    (format: "yaml" | "json" | "markdown" | "events") => {
      if (!sessionId) return;
      handleExportSession(sessionId, format);
    },
    [sessionId, handleExportSession]
  );

  const handleDeleteCurrentSession = useCallback(() => {
    if (!sessionId) return;
    handleDeleteSession(sessionId);
  }, [sessionId, handleDeleteSession]);

  const handleQuickAction = useCallback(
    (prompt: string) => {
      sendMessage(prompt);
    },
    [sendMessage]
  );

  const showEmptyState = messages.length === 0 && !isLoadingSession;

  return (
    <div className="flex h-screen overflow-hidden">
      <SessionSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
        onDeleteSession={handleDeleteSession}
        onExportSession={handleExportSession}
        onRenameSession={handleRenameSession}
        onForkSession={handleForkSession}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed((prev) => !prev)}
      />

      <div className="flex-1 flex flex-col min-w-0">
        <ChatHeader
          sessionTitle={sessionTitle}
          modelLabel={modelLabel}
          modelOnline={Boolean(currentModel)}
          sessionId={sessionId}
          onToggleSidebar={() => setSidebarCollapsed((prev) => !prev)}
          onExport={sessionId ? handleExportCurrent : undefined}
          onDeleteSession={sessionId ? handleDeleteCurrentSession : undefined}
          models={availableModels}
          selectedModel={currentModel}
          selectedProvider={currentProvider}
          onModelChange={setModel}
          debugPanelOpen={debugPanelOpen}
          onToggleDebugPanel={toggleDebugPanel}
          // Subagent toggle. Operator-personal preference,
          // persisted to operator_state.db. Defaults ON.
          subagentsEnabled={subagentsEnabled}
          onToggleSubagents={toggleSubagents}
          // Semantic stats from the new
          // SSE event kinds (compaction_end, cache_hit). null until
          // the first event lands; the header components hide
          // themselves cleanly when nullish.
          compactionStats={telemetryStats.lastCompaction}
          cacheHit={telemetryStats.lastCacheHit}
          // Per-session approval mode dropdown. Reads
          // from session.metadata.approval_mode; writes via PATCH.
          approvalMode={approvalMode}
          onApprovalModeChange={handleApprovalModeChange}
          // Claude Code selection flows through the model
          // dropdown. chatRoute
          // is derived in useChat for the send-time URL switch.
        />

        <div className="flex-1 overflow-hidden">
          {showEmptyState ? (
            <EmptyState onQuickAction={handleQuickAction} />
          ) : (
            <MessageList
              messages={messages}
              isStreaming={isStreaming}
              isLoading={isLoadingSession}
              // Live subagent activity cards
              // pinned below the thread.
              subagents={subagents}
              // Per-message Fork-from-here. Renders a
              // hover-revealed button on assistant bubbles that have
              // an mcpId (loaded from MCP persistence). Click branches
              // a new session from that exact message.
              onForkFromMessage={handleForkFromMessage}
            />
          )}
          {/* "Still generating" indicator for a
              restored session whose last message has no assistant reply
              yet. Visually mirrors MessageList's own streaming-dots
              bubble, but driven by isAwaitingLiveResponse (this page's
              poll state) rather than useChat's isStreaming, which
              loadSession always resets to false. */}
          {isAwaitingLiveResponse && (
            <div className="px-6 pb-3 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse [animation-delay:150ms]" />
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse [animation-delay:300ms]" />
              <span className="text-xs text-on-surface-variant/60 ml-1">
                Waiting for the response still in progress…
              </span>
            </div>
          )}
        </div>

        {/* Pending approval cards. Rendered between the
            chat thread and the input bar so they're always visible
            without scrolling. Each card resolves itself when the
            operator clicks Approve/Deny. */}
        {pendingApprovals.length > 0 && (
          <div className="px-6 py-3 space-y-3 border-t border-on-surface/10 bg-surface-container-lowest/30 max-h-[60vh] overflow-y-auto">
            {pendingApprovals.map((approval) => (
              <ApprovalCard
                key={approval.id}
                approval={approval}
                onResolve={resolveApproval}
              />
            ))}
          </div>
        )}

        <ChatInput
          onSend={sendMessage}
          isStreaming={isStreaming}
          // Wire the most-recent context_warning
          // utilization through so the input renders the /compress
          // auto-suggest banner at >=80%.
          contextUtilization={telemetryStats.lastContextWarning?.utilization}
        />
      </div>

      {/* Right-side telemetry panel — collapsed by default; toggle in
          the chat header. The panel itself returns null when !open so
          the flex column doesn't reserve space when hidden. */}
      <DebugPanel
        open={debugPanelOpen}
        onClose={toggleDebugPanel}
        onClear={clearTelemetry}
        sessionId={sessionId}
        runId={runId}
        toolCalls={toolCalls}
        events={events}
        isStreaming={isStreaming}
      />
    </div>
  );
}

// ─── Empty State ─────────────────────────────────────────────────────────────

function EmptyState({ onQuickAction }: { onQuickAction: (prompt: string) => void }) {
  return (
    <div className="h-full flex flex-col items-center justify-center gap-8 px-8">
      <div className="flex flex-col items-center gap-4">
        <div
          className="w-20 h-20 rounded-3xl flex items-center justify-center shadow-lg"
          style={{
            background: "var(--glass-bg-strong)",
            border: "0.5px solid var(--glass-border)",
            boxShadow: "0 0 40px rgba(25, 99, 179, 0.12)",
          }}
        >
          <SparkLogo size={48} />
        </div>
        <div className="text-center">
          <h2 className="text-xl font-headline font-bold text-on-surface">
            Talk to Phantom
          </h2>
          <p className="text-sm text-on-surface-variant/70 mt-1 font-body max-w-sm">
            Continuous SOC simulation — log generation, scenario orchestration,
            and live tool telemetry over MCP.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap justify-center gap-2 max-w-lg">
        {QUICK_ACTIONS.map((action) => (
          <button
            key={action.label}
            type="button"
            onClick={() => onQuickAction(action.prompt)}
            className="group flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-label font-medium text-on-surface-variant hover:text-on-surface transition-all hover:scale-[1.02] active:scale-[0.98]"
            style={{
              background: "var(--glass-bg)",
              backdropFilter: "blur(12px)",
              border: "0.5px solid var(--glass-border)",
            }}
          >
            <span className="material-symbols-outlined text-sm text-secondary/70 group-hover:text-secondary transition-colors">
              {action.icon}
            </span>
            {action.label}
          </button>
        ))}
      </div>

      <p className="text-[11px] text-outline/50 font-label">
        Or type anything below to start a conversation
      </p>
    </div>
  );
}
