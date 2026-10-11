import { apiRequest, listRequest } from "./client";
import type { ApiRequestOptions } from "./client";
import type { Session, Run } from "./types";

/** List sessions for an agent from GET /api/v1/agents/:agentId/sessions. */
export function listSessions(agentId: string, options?: ApiRequestOptions) {
  return listRequest<Session>(
    `/api/v1/agents/${encodeURIComponent(agentId)}/sessions`,
    options,
  );
}

/** Fetch a single session by ID from GET /api/v1/sessions/:id. */
export function getSession(id: string, options?: ApiRequestOptions) {
  return apiRequest<Session>(
    `/api/v1/sessions/${encodeURIComponent(id)}`,
    options,
  );
}

/** Delete a session by ID via DELETE /api/v1/sessions/:id. */
export function deleteSession(id: string, options?: ApiRequestOptions) {
  return apiRequest<void>(
    `/api/v1/sessions/${encodeURIComponent(id)}`,
    { ...options, method: "DELETE" },
  );
}

/** Reset a session by ID via POST /api/v1/sessions/:id/reset. */
export function resetSession(id: string, options?: ApiRequestOptions) {
  return apiRequest<Session>(
    `/api/v1/sessions/${encodeURIComponent(id)}/reset`,
    { ...options, method: "POST" },
  );
}

// ─── Chat-specific session helpers ───────────────────────────────────────────

/**
 * List all chat sessions (no agent filter) from GET /api/v1/sessions.
 * Falls back to empty array when the endpoint is not yet implemented.
 *
 * Optional filters:
 *   - excludeScheduled: when true, drops sessions tagged
 *     `meta.scheduled_by=<job-name>` (recurring-job-driven sessions).
 *     The chat sidebar uses this so operator-driven conversations
 *     aren't buried under scheduled-job churn on busy installs. Server-
 *     side filtering matters because a client-side filter applied
 *     after the fetch breaks when the default row window is 100%
 *     scheduled (the fetch returns only scheduled sessions, the
 *     filter drops them all, and the sidebar is empty).
 *   - limit: maximum rows. Optional pagination opt-in. The server
 *     returns ALL sessions by default.
 *     Pass an explicit `limit` only when paginating; omit for a complete
 *     list.
 */
export interface ListChatSessionsParams {
  excludeScheduled?: boolean;
  limit?: number;
}

export function listChatSessions(
  params: ListChatSessionsParams = {},
  options?: ApiRequestOptions,
) {
  const qs = new URLSearchParams();
  if (params.excludeScheduled) qs.set("exclude_scheduled", "true");
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  const path = qs.toString()
    ? `/api/v1/sessions?${qs.toString()}`
    : "/api/v1/sessions";
  return listRequest<Session>(path, options);
}

/**
 * Export a session transcript in the given format.
 * GET /api/v1/sessions/:id/export?format=yaml|json|markdown|events
 *
 * Uses fetch directly (through the Next.js proxy) and reads response.text()
 * because the export endpoint returns raw text (YAML/Markdown), not a JSON
 * envelope. The standard apiRequest would fail trying to JSON.parse the body.
 *
 * Path goes through `/api/agent/sessions/:id/export` — the phantom-agent
 * proxy. (Phantom doesn't run an api-gateway hop; everything is proxied
 * directly by the Next.js route handlers.)
 *
 * The `events` format returns a JSON array of wire-event-shaped
 * objects derived from the session's persisted messages + meta
 * blobs. Different from `json` (which is the full session snapshot
 * with all messages); `events` is a flat event-list timeline mirroring
 * what the live telemetry panel reconstructs after a session reload.
 */
export async function exportSession(
  id: string,
  format: "yaml" | "json" | "markdown" | "events",
): Promise<{ ok: true; data: string } | { ok: false; error: string }> {
  try {
    const path = `/api/agent/sessions/${encodeURIComponent(id)}/export?format=${encodeURIComponent(format)}`;
    const response = await fetch(path, {
      method: "GET",
      headers: { Accept: "text/plain" },
    });

    if (!response.ok) {
      const errText = await response.text().catch(() => "Export failed");
      return { ok: false, error: errText };
    }

    const data = await response.text();
    return { ok: true, data };
  } catch {
    return { ok: false, error: "Export failed" };
  }
}

/** Patch a session by ID via PATCH /api/v1/sessions/:id. */
export function patchSession(
  id: string,
  body: Record<string, unknown>,
  options?: ApiRequestOptions,
) {
  return apiRequest<Session>(
    `/api/v1/sessions/${encodeURIComponent(id)}`,
    { ...options, method: "PATCH", body },
  );
}

/** List runs belonging to a session from GET /api/v1/sessions/:id/runs. */
export function listSessionRuns(id: string, options?: ApiRequestOptions) {
  return listRequest<Run>(
    `/api/v1/sessions/${encodeURIComponent(id)}/runs`,
    options,
  );
}

/** Transcript message returned to the chat page.
 *
 * `meta` carries `kind`, `messages_summarized`, `summary_chars`,
 * etc. for the `compaction-checkpoint` system rows.
 * Bubble-rendered messages (user/assistant) leave `meta` undefined.
 *
 * `mcpId` carries the MCP-side message id when the row
 * was loaded from persistence (vs streamed live). Per-message
 * Fork-from-here uses this id as `from_message_id` on POST
 * /api/v1/sessions/{id}/fork. Streaming messages have no
 * mcpId until session reload; the Fork button is hidden for those.
 */
export interface TranscriptMessage {
  role: string;
  content: string;
  timestamp: string;
  meta?: Record<string, unknown>;
  mcpId?: string;
}

/** Tool call captured from a session's persisted messages. Shape matches
 *  the chat hook's `TelemetryToolCall` so loadSession can drop these
 *  straight into state without extra mapping. */
export interface SessionToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  status: "success" | "error";
  result?: string;
  error?: string;
  startedAt: string;
  finishedAt?: string;
  durationMs?: number;
}

/** Synthetic SSE-shaped event reconstructed from one persisted tool
 *  message. We emit two per tool — a `tool_call` row (the dispatch) and
 *  a `tool_result` row (the response) — so the wire-stream panel reads
 *  the same as a live session, just without the per-token text deltas
 *  the model emits during streaming. */
export interface SessionEvent {
  ts: string;
  type: string;
  preview: string;
}

/**
 * Fetch the full message transcript for a session.
 *
 * The phantom MCP doesn't expose a `/transcript` endpoint (Spark did);
 * we hit `/api/v1/sessions/:id/messages` instead and map the MCP's
 * Message shape (`{id, session_id, ts, role, content, tool_call_id, meta}`)
 * into the simpler `{role, content, timestamp}` the chat hook expects.
 *
 * Tool messages are filtered out for replay — they were tool round-trips
 * that the model has already collapsed into its reply, so re-rendering
 * them as separate bubbles would double-show information. Tools remain
 * in the export (Markdown/YAML/JSON include all roles).
 */
export async function getSessionTranscript(
  id: string,
  options?: ApiRequestOptions,
): Promise<
  | { ok: true; data: { messages: TranscriptMessage[] } }
  | { ok: false; error: { code: string; message: string } }
> {
  type RawMessage = {
    // The MCP-side messages table primary key (uuid) is surfaced so
    // the chat page can bind a "Fork from here" button to a specific
    // persisted row.
    id?: string;
    role: string;
    content: string;
    ts?: string;
    timestamp?: string;
    meta?: Record<string, unknown>;
  };
  // Explicit `?ascending=true`, no `limit`: the MCP-side default limit
  // of 100 would silently truncate long transcripts on session reload.
  // Compaction is the legitimate context-window manager; the transcript
  // loader always returns every bubble.
  const result = await apiRequest<{ messages: RawMessage[] }>(
    `/api/v1/sessions/${encodeURIComponent(id)}/messages?ascending=true`,
    options,
  );
  if (!result.ok) return result;
  const mapped: TranscriptMessage[] = (result.data.messages ?? [])
    .filter((m) => {
      // User + assistant bubbles always render.
      if (m.role === "user" || m.role === "assistant") return true;
      // Keep `system` messages whose meta marks
      // them as compaction checkpoints. They render as a horizontal
      // divider in the chat thread, so the operator can see WHEN the
      // session got compacted (and what got rolled up). All other
      // system messages are internal markers and stay hidden.
      if (
        m.role === "system" &&
        m.meta &&
        m.meta["kind"] === "compaction-checkpoint"
      ) {
        return true;
      }
      // Keep `plan-proposed` system rows. The
      // chat thread renders these as a distinct PlanCard so on
      // session reload the operator sees the plan they had open
      // mid-session.
      if (
        m.role === "system" &&
        m.meta &&
        m.meta["kind"] === "plan-proposed"
      ) {
        return true;
      }
      return false;
    })
    .map((m) => ({
      role: m.role,
      content: m.content,
      timestamp: m.ts ?? m.timestamp ?? "",
      meta: m.meta,
      mcpId: m.id,
    }));
  return { ok: true, data: { messages: mapped } };
}

/**
 * Fetch persisted tool messages for a session and reshape them into the
 * telemetry panel's wire shape. Each `role='tool'` message becomes one
 * `SessionToolCall` plus two `SessionEvent` rows (call + result) so the
 * Wire Stream panel reads identically to a live turn.
 *
 * Why this exists: per-token text deltas are not stored, but tool
 * dispatches are: they land in the messages table via `chat/route.ts`'s
 * `safePersist({role:'tool', tool_call_id:<name>, meta:{tool,args},
 * content:<result>}, ...)` block, so `loadSession()` in
 * `components/chat/use-chat.ts` can query for them on session load.
 *
 * Notes / limitations:
 *   - We can't recover real durations because per-call timing isn't
 *     persisted. We approximate by pairing consecutive tool messages —
 *     `finishedAt` of call N becomes `startedAt` of call N+1's window;
 *     the displayed duration is "—" rather than wrong.
 *   - Status is always `success` for replayed calls. The chat-route
 *     wraps tool results in `safePersist` only on the success path
 *     (the model already saw the error and responded; we don't keep
 *     a separate persisted error row). If we ever start persisting
 *     `role='tool',meta.status='error'`, this helper will pick that
 *     up automatically (the field is already read below).
 *   - Persisted `tool_call_id` is the tool name, not a per-call UUID
 *     (that's a quirk of the chat-route's persistence shape — see
 *     mcp/agent/app/api/chat/route.ts:1613). We mint a synthetic id
 *     `<sessionId>-<index>` so React keys stay stable across renders.
 */
export async function getSessionTelemetry(
  id: string,
  options?: ApiRequestOptions,
): Promise<
  | {
      ok: true;
      data: { toolCalls: SessionToolCall[]; events: SessionEvent[] };
    }
  | { ok: false; error: { code: string; message: string } }
> {
  type RawMessage = {
    id?: string;
    role: string;
    content: string;
    ts?: string;
    tool_call_id?: string | null;
    meta?: Record<string, unknown> | null;
  };
  // No `?limit=` passed. The MCP endpoint returns every persisted
  // message in the session by default; every call site aligns on
  // "no implicit limit." Compaction is the only legitimate
  // context-window manager.
  const result = await apiRequest<{ messages: RawMessage[] }>(
    `/api/v1/sessions/${encodeURIComponent(id)}/messages?ascending=true`,
    options,
  );
  if (!result.ok) return result;

  const all = result.data.messages ?? [];
  const toolMsgs = all.filter((m) => m.role === "tool");

  const toolCalls: SessionToolCall[] = [];
  const events: SessionEvent[] = [];

  toolMsgs.forEach((m, idx) => {
    const meta = (m.meta ?? {}) as {
      tool?: string;
      args?: Record<string, unknown>;
      status?: "success" | "error";
      error?: string;
      duration_ms?: number;
    };
    const name = meta.tool ?? m.tool_call_id ?? "(unknown)";
    const args = meta.args ?? {};
    const status: "success" | "error" =
      meta.status === "error" ? "error" : "success";
    const ts = m.ts ?? "";
    const callId = m.id ?? `${id}-${idx}`;

    toolCalls.push({
      id: callId,
      name,
      arguments: args,
      status,
      result: status === "success" ? m.content : undefined,
      error: status === "error" ? meta.error ?? m.content : undefined,
      startedAt: ts,
      finishedAt: ts,
      durationMs: typeof meta.duration_ms === "number" ? meta.duration_ms : undefined,
    });

    // Synthesize the two wire events the live stream would emit. The
    // preview field is bounded so the panel stays cheap to render even
    // on sessions with many tool round-trips.
    const argsPreview = JSON.stringify(args).slice(0, 200);
    events.push({
      ts,
      type: "tool_call",
      preview: `${name}(${argsPreview})`,
    });
    const resultPreview = (
      status === "error" ? meta.error ?? m.content : m.content
    ).slice(0, 200);
    events.push({
      ts,
      type: status === "error" ? "tool_error" : "tool_result",
      preview: `${name} → ${resultPreview}`,
    });
  });

  return { ok: true, data: { toolCalls, events } };
}
