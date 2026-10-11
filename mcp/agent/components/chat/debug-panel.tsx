"use client";

/**
 * DebugPanel — right-side collapsible telemetry view for the chat.
 *
 * Renders the tool-call timeline + raw SSE event stream + run/session
 * metadata for the active chat. Mirrors the "Live telemetry" affordance
 * from the old xlog UI, restyled to phantom's Ocean Navy + glassmorphism
 * aesthetic to match /jobs and /providers.
 *
 * Layout: ~360px wide column, sibling to the message list. The parent
 * controls visibility (open prop) so the toggle state can be persisted
 * in localStorage at the page level.
 *
 * Two tabs:
 *   - Tool calls — chronological timeline of tool dispatches with status
 *     pill, duration, and collapsible args/result. Reuses the visual
 *     vocabulary of `tool-call-card.tsx` (status icons via Material
 *     Symbols + monospace tool names).
 *   - Wire events — raw SSE event stream (timestamped, one line per event,
 *     monospace). The "what just came over the wire" view useful when a
 *     tool call seems stuck or the model is silently looping.
 */

import { useState } from "react";

import { cn } from "@/lib/utils";

import type { TelemetryEvent, TelemetryToolCall } from "./use-chat";

const glassStyle = {
  // Theme-aware glass — was hardcoded rgba(20, 20, 45, 0.5) which
  // rendered as a dim translucent navy on light theme. The
  // `--glass-bg-strong` token is rgba(20, 20, 45, 0.4) in dark theme
  // (visually identical to the previous value) and
  // rgba(255, 255, 255, 0.86) in light theme (a clean off-white that
  // reads as "elevated panel" rather than "dim-grey overlay" against
  // the pale-azure page bg).
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(14px)",
  borderLeft: "0.5px solid var(--glass-border)",
} as const;

interface DebugPanelProps {
  open: boolean;
  onClose: () => void;
  onClear: () => void;
  sessionId: string | null;
  runId: string | null;
  toolCalls: TelemetryToolCall[];
  events: TelemetryEvent[];
  isStreaming: boolean;
}

type Tab = "tools" | "events";

export function DebugPanel({
  open,
  onClose,
  onClear,
  sessionId,
  runId,
  toolCalls,
  events,
  isStreaming,
}: DebugPanelProps) {
  const [tab, setTab] = useState<Tab>("tools");

  if (!open) return null;

  return (
    <aside
      className="w-[360px] shrink-0 flex flex-col h-full"
      style={glassStyle}
      aria-label="Live telemetry panel"
    >
      {/* Header */}
      <div className="px-4 py-3 flex items-center justify-between border-b border-white/5 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className={cn(
              "w-1.5 h-1.5 rounded-full shrink-0",
              isStreaming ? "bg-secondary animate-pulse" : "bg-outline",
            )}
          />
          <h2 className="font-headline text-sm font-bold text-on-surface">
            Live telemetry
          </h2>
        </div>
        <div className="flex items-center gap-1">
          {/* Export the live in-memory panel state. This
              captures streaming-only events (text_delta cadence,
              run-id boundaries) that the session-export `events`
              format CAN'T see because they aren't persisted.
              JSON-only — the panel's shape is already a tagged
              event list, so the file mirrors it 1:1 without
              transformation. */}
          <button
            type="button"
            onClick={() => {
              const payload = {
                schema_version: 1,
                exported_at: new Date().toISOString(),
                session_id: sessionId,
                run_id: runId,
                tool_calls_count: toolCalls.length,
                events_count: events.length,
                tool_calls: toolCalls,
                events,
                note:
                  "Live in-memory telemetry from the chat DebugPanel. " +
                  "Includes streaming-only signals (text_delta cadence, " +
                  "run-id boundaries) that the session 'events' export " +
                  "can't see because those aren't persisted to messages. " +
                  "For the post-hoc forensic view from messages + meta, " +
                  "use the session Export → Events (JSON) menu instead.",
              };
              const ts = new Date().toISOString().replace(/[:.]/g, "-");
              const sidSuffix = sessionId ? sessionId.slice(0, 8) : "unbound";
              const filename = `live-telemetry-${sidSuffix}-${ts}.json`;
              const blob = new Blob([JSON.stringify(payload, null, 2)], {
                type: "application/json",
              });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = filename;
              document.body.appendChild(a);
              a.click();
              a.remove();
              URL.revokeObjectURL(url);
            }}
            disabled={toolCalls.length === 0 && events.length === 0}
            className="p-1.5 rounded-lg hover:bg-white/5 transition-colors text-on-surface-variant hover:text-on-surface disabled:opacity-40 disabled:cursor-not-allowed"
            title="Export the live in-memory wire trace (JSON) — includes per-token text_delta events and the run-id/model/done control events that are visible in this panel but not persisted server-side. The session sidebar's 'Export Events' captures everything else (cache_hit, turn_cost, tool calls, messages) from the database. Use this one ONLY when you need per-token streaming forensics; for everything else, prefer the session export — it's the post-hoc-friendly path that doesn't require capturing during the run."
            aria-label="Export live telemetry (per-token wire trace)"
          >
            <span className="material-symbols-outlined text-base">
              download
            </span>
          </button>
          <button
            type="button"
            onClick={onClear}
            className="p-1.5 rounded-lg hover:bg-white/5 transition-colors text-on-surface-variant hover:text-on-surface"
            title="Clear telemetry"
            aria-label="Clear telemetry"
          >
            <span className="material-symbols-outlined text-base">
              delete_sweep
            </span>
          </button>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/5 transition-colors text-on-surface-variant hover:text-on-surface"
            title="Hide panel"
            aria-label="Hide telemetry panel"
          >
            <span className="material-symbols-outlined text-base">close</span>
          </button>
        </div>
      </div>

      {/* Run/session meta */}
      <div className="px-4 py-3 border-b border-white/5 shrink-0 space-y-1.5">
        <MetaRow label="Session" value={sessionId} />
        <MetaRow label="Run" value={runId} />
        <MetaRow
          label="Tool calls"
          value={`${toolCalls.length}`}
          valueClass="text-primary font-mono"
        />
        <MetaRow
          label="Events"
          value={`${events.length}`}
          valueClass="text-primary font-mono"
        />
      </div>

      {/* Tabs */}
      <div className="flex border-b border-white/5 shrink-0">
        <TabButton
          active={tab === "tools"}
          onClick={() => setTab("tools")}
          label="Tool calls"
          count={toolCalls.length}
          icon="build"
        />
        <TabButton
          active={tab === "events"}
          onClick={() => setTab("events")}
          label="Wire events"
          count={events.length}
          icon="cable"
        />
      </div>

      {/* Body */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {tab === "tools" ? (
          <ToolCallList toolCalls={toolCalls} />
        ) : (
          <EventStream events={events} />
        )}
      </div>
    </aside>
  );
}

// ─── Sub-components ─────────────────────────────────────────────────

function MetaRow({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string | null;
  valueClass?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 text-[11px]">
      <span className="font-label uppercase tracking-wider text-on-surface-variant/60">
        {label}
      </span>
      <span
        className={cn(
          "truncate font-mono",
          valueClass ?? "text-on-surface-variant",
        )}
        title={value ?? undefined}
      >
        {value ? (value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value) : "—"}
      </span>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  label,
  count,
  icon,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
  icon: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex-1 flex items-center justify-center gap-1.5 py-2.5 text-[11px] font-label uppercase tracking-wider transition-colors",
        active
          ? "text-secondary border-b-2 border-secondary -mb-[2px]"
          : "text-on-surface-variant/70 hover:text-on-surface hover:bg-white/[0.02]",
      )}
    >
      <span className="material-symbols-outlined text-sm">{icon}</span>
      {label}
      <span
        className={cn(
          "text-[10px] font-mono px-1 rounded",
          active
            ? "bg-primary/15 text-primary"
            : "bg-white/5 text-on-surface-variant",
        )}
      >
        {count}
      </span>
    </button>
  );
}

function ToolCallList({ toolCalls }: { toolCalls: TelemetryToolCall[] }) {
  if (toolCalls.length === 0) {
    return (
      <EmptyState
        icon="build_circle"
        title="No tool calls yet"
        body="Send a prompt that exercises an MCP tool — phantom_get_technology_stack, memory_store, caldera_get_all_abilities, etc. They'll appear here in real time."
      />
    );
  }
  return (
    <ol className="p-3 space-y-2">
      {toolCalls.map((tc, i) => (
        <ToolCallRow key={tc.id} call={tc} index={i + 1} />
      ))}
    </ol>
  );
}

function ToolCallRow({ call, index }: { call: TelemetryToolCall; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const status = call.status;
  const statusMeta =
    status === "pending"
      ? { icon: "hourglass_top", className: "text-primary animate-spin" }
      : status === "success"
        ? { icon: "check_circle", className: "text-secondary" }
        : { icon: "error", className: "text-error" };

  return (
    <li className="rounded-xl bg-surface-container/40 border border-white/5 overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full px-3 py-2 flex items-center gap-2 text-left hover:bg-white/[0.03] transition-colors"
      >
        <span className="font-mono text-[10px] text-on-surface-variant/50 w-5 shrink-0 text-right">
          {String(index).padStart(2, "0")}
        </span>
        <span
          className={cn(
            "material-symbols-outlined text-base shrink-0",
            statusMeta.className,
          )}
          style={{ fontVariationSettings: "'FILL' 1" }}
        >
          {statusMeta.icon}
        </span>
        <code className="font-mono text-xs text-on-surface flex-1 truncate">
          {call.name}
        </code>
        {call.cached && (
          <span
            className="text-[9px] font-mono uppercase tracking-wide text-on-surface-variant/60 border border-outline-variant/40 rounded px-1 shrink-0"
            title="Reused from this turn's cache (no MCP round-trip)"
          >
            cached
          </span>
        )}
        {call.durationMs != null && (
          <span className="text-[10px] font-mono text-on-surface-variant/70 shrink-0">
            {call.durationMs}ms
          </span>
        )}
        <span className="material-symbols-outlined text-on-surface-variant/50 text-sm shrink-0">
          {expanded ? "expand_less" : "expand_more"}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-white/5 p-3 space-y-2 text-[11px]">
          {Object.keys(call.arguments).length > 0 && (
            <Field label="Arguments">
              <pre className="font-mono text-[10px] text-on-surface-variant whitespace-pre-wrap break-all max-h-40 overflow-y-auto bg-surface-container-lowest/60 rounded-md p-2">
                {JSON.stringify(call.arguments, null, 2)}
              </pre>
            </Field>
          )}
          {status === "success" && call.result != null && (
            <Field label="Result" labelClass="text-secondary/80">
              <pre className="font-mono text-[10px] text-on-surface-variant whitespace-pre-wrap break-all max-h-40 overflow-y-auto bg-surface-container-lowest/60 rounded-md p-2">
                {call.result}
              </pre>
            </Field>
          )}
          {status === "error" && call.error != null && (
            <Field label="Error" labelClass="text-error/80">
              <pre className="font-mono text-[10px] text-error whitespace-pre-wrap break-all max-h-40 overflow-y-auto bg-error-container/10 rounded-md p-2">
                {call.error}
              </pre>
            </Field>
          )}
          <div className="flex justify-between text-[9px] text-on-surface-variant/50 font-mono pt-1">
            <span>started {timeOnly(call.startedAt)}</span>
            {call.finishedAt && <span>finished {timeOnly(call.finishedAt)}</span>}
          </div>
        </div>
      )}
    </li>
  );
}

function Field({
  label,
  labelClass,
  children,
}: {
  label: string;
  labelClass?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p
        className={cn(
          "font-label text-[9px] uppercase tracking-widest mb-1",
          labelClass ?? "text-on-surface-variant/60",
        )}
      >
        {label}
      </p>
      {children}
    </div>
  );
}

function EventStream({ events }: { events: TelemetryEvent[] }) {
  if (events.length === 0) {
    return (
      <EmptyState
        icon="cable"
        title="No wire events yet"
        body="Every SSE frame from /api/chat lands here as it arrives — text deltas, tool dispatches, run completion. Useful when something seems stuck."
      />
    );
  }
  return (
    <ul className="p-3 space-y-1 font-mono text-[10px]">
      {events.map((e, i) => {
        const icon = eventTypeIcon(e.type);
        return (
          // Hovering must show the entire preview, not a truncated
          // one. A native HTML `title` tooltip would be
          // OS-truncated and slow, so the
          // row clips by default with `truncate` but switches
          // to `whitespace-pre-wrap break-all` on hover so the full
          // preview wraps inline. `group` + `group-hover` is the
          // Tailwind idiom for "parent-controlled child state."
          // Higher z-index + relative positioning ensures the
          // expanding row floats above siblings without reflowing
          // the list.
          <li
            key={i}
            className="group flex gap-2 leading-snug relative hover:z-10 hover:bg-surface-container-lowest/60 hover:rounded-md hover:px-1 hover:-mx-1 transition-colors"
          >
            <span className="text-on-surface-variant/40 shrink-0">
              {timeOnly(e.ts)}
            </span>
            <span
              className={cn(
                "shrink-0 px-1 rounded inline-flex items-center gap-1",
                eventTypeClass(e.type),
              )}
            >
              {icon && (
                <span
                  className="material-symbols-outlined text-[11px] leading-none"
                  aria-hidden="true"
                >
                  {icon}
                </span>
              )}
              {e.type}
            </span>
            <span className="text-on-surface-variant truncate group-hover:overflow-visible group-hover:whitespace-pre-wrap group-hover:break-all">
              {e.preview}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function EmptyState({
  icon,
  title,
  body,
}: {
  icon: string;
  title: string;
  body: string;
}) {
  return (
    <div className="p-6 text-center">
      <span className="material-symbols-outlined text-3xl text-on-surface-variant/40 mb-2 inline-block">
        {icon}
      </span>
      <p className="text-sm font-medium text-on-surface mb-1">{title}</p>
      <p className="text-[11px] text-on-surface-variant/70 leading-relaxed">
        {body}
      </p>
    </div>
  );
}

// ─── Helpers ─────────────────────────────────────────────────────────

function timeOnly(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso.slice(0, 8);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  const ms = String(d.getMilliseconds()).padStart(3, "0");
  return `${hh}:${mm}:${ss}.${ms}`;
}

function eventTypeClass(type: string): string {
  switch (type) {
    case "meta":
      return "bg-tertiary/15 text-tertiary";
    case "text_delta":
      return "bg-white/5 text-on-surface-variant/70";
    case "tool_call":
      return "bg-primary/15 text-primary";
    case "tool_result":
      return "bg-secondary/15 text-secondary";
    case "done":
    case "run_completed":
      return "bg-secondary/15 text-secondary";
    case "error":
      return "bg-error/15 text-error";
    // Operator + auto compaction.
    // Start: in-flight (primary). End: success (secondary). Failed:
    // error. Same color vocabulary as tool_call/tool_result so the
    // operator's visual scan ("did this thing succeed?") works the
    // same way for compactions as it does for tool dispatches.
    case "compaction_start":
      return "bg-primary/15 text-primary";
    case "compaction_end":
      return "bg-secondary/15 text-secondary";
    case "compaction_failed":
      return "bg-error/15 text-error";
    // Context-window guard. Tertiary (amber)
    // shares the "this matters but it's not broken" visual lane with
    // /meta. Both are "informational", neither is "in-progress" or
    // "succeeded".
    case "context_warning":
      return "bg-tertiary/15 text-tertiary";
    // Vertex cachedContents hit. Tertiary tint
    // because this is a cost-savings signal, not a state change. The
    // operator should be able to glance at the wire stream and see
    // cache_hit pulses to know caching is doing its job.
    case "cache_hit":
      return "bg-tertiary/15 text-tertiary";
    // Slash-command lifecycle events.
    case "session_cleared":
      return "bg-tertiary/15 text-tertiary";
    case "model_preference_changed":
      return "bg-primary/15 text-primary";
    // Model resolution event (which model handled this
    // turn). Was missing from this switch; defaulting was fine but
    // since /model selection is an operator-relevant signal, give it
    // a subtle but distinct tint.
    case "model":
      return "bg-tertiary/15 text-tertiary";
    case "approval_pending":
      return "bg-tertiary/15 text-tertiary";
    // turn_cost is the per-turn billing summary (input + output
    // tokens, USD, model breakdown). The /cost slash-command also
    // surfaces this. Tertiary tint shares the cost-savings lane with
    // cache_hit — both are "your wallet should care about this".
    case "turn_cost":
      return "bg-tertiary/15 text-tertiary";
    default:
      return "bg-white/5 text-on-surface-variant";
  }
}

/**
 * Per-event-type Material Symbols icon shown
 * inside the event-row pill. Helps operators visually scan the wire
 * stream for "what kind of thing happened" without reading the type
 * name. Same color as the pill (inherited).
 *
 * Returns null for events that don't get an icon (text_delta is too
 * frequent — would clutter the column).
 */
function eventTypeIcon(type: string): string | null {
  switch (type) {
    case "meta":
      return "info";
    case "tool_call":
      return "build";
    case "tool_result":
      return "check_circle";
    case "done":
    case "run_completed":
      return "task_alt";
    case "error":
      return "error";
    case "compaction_start":
      return "compress";
    case "compaction_end":
      return "compress";
    case "compaction_failed":
      return "error";
    case "context_warning":
      return "warning";
    case "cache_hit":
      return "bolt";
    case "session_cleared":
      return "restart_alt";
    case "model_preference_changed":
      return "tune";
    case "model":
      return "smart_toy";
    case "approval_pending":
      return "pan_tool";
    // Every event type needs an icon so the operator can scan the
    // stream. turn_cost uses `payments`, the Material Symbols cost/billing
    // glyph; visually distinct from `bolt` (cache_hit) so the
    // operator can scan both at once.
    case "turn_cost":
      return "payments";
    // text_delta is intentionally NOT given an icon (it streams
    // many-per-second; an icon would visually saturate the
    // column). The neutral pill styling above is sufficient — the
    // type-name in the pill carries the meaning.
    default:
      return null;
  }
}
