"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { fetchApprovalGating } from "@/lib/api/approvals";

// ─── Types ───────────────────────────────────────────────────────────────────

// The "events" format exports a wire-event trace.
// Backed by the same /api/v1/sessions/{id}/export endpoint with
// ?format=events. Events are derived from persisted messages + meta.
type ExportFormat = "yaml" | "json" | "markdown" | "events";

export interface ModelOption {
  provider: string;
  model: string;
  displayName?: string;
  contextWindow: number;
  supportsThinking: boolean;
  supportsTools: boolean;
  // When true, hide from the dropdown. Source of truth is
  // the /api/agent/models route; see lib/api/types.ts ModelInfo.wip.
  wip?: boolean;
}

export interface ChatHeaderProps {
  sessionTitle: string;
  modelLabel: string;
  modelOnline: boolean;
  sessionId: string | null;
  onToggleSidebar: () => void;
  onExport?: (format: ExportFormat) => void;
  onDeleteSession?: () => void;
  models?: ModelOption[];
  selectedModel?: string;
  selectedProvider?: string;
  onModelChange?: (provider: string, model: string) => void;
  /** Whether the right-side debug panel is open. */
  debugPanelOpen?: boolean;
  /** Toggle handler for the debug panel. Omit to hide the button entirely. */
  onToggleDebugPanel?: () => void;
  /**
   * Operator preference for `subagent_create`. When true (default),
   * the model sees subagent_create in its catalog. When false, the spec
   * is omitted and the chat-route gates any dispatch defensively.
   * Use the toggle when testing chat flows where you want deterministic
   * single-agent execution.
   */
  subagentsEnabled?: boolean;
  onToggleSubagents?: () => void;
  /**
   * Most-recent compaction (operator
   * /compress or auto-budget-edge). Renders as a badge between the
   * title and model row showing "compacted N msgs"; click expands a
   * popover with the summary char count + timestamp. Omit when
   * the session has no compaction yet.
   */
  compactionStats?: {
    messagesSummarized: number;
    summaryChars: number | null;
    at: string;
    skipped: boolean;
  } | null;
  /**
   * Most-recent Vertex cache hit. Drives a
   * cyan dot on the model-selector chip + a tooltip showing
   * "cached N tokens of M (~25% billing)". Omit / null = no
   * cache hit observed yet on this session.
   */
  cacheHit?: {
    cachedTokens: number;
    promptTokens: number | null;
    at: string;
  } | null;
  /**
   * Per-session approval mode. 'manual' (default) shows
   * the inline approval card on every gated tool; 'bypass' auto-
   * approves with audit row. Persisted in session.metadata via
   * /api/agent/sessions/[id] PATCH; the chat handler reads it on
   * each turn and forwards X-Phantom-Approval-Bypass when active.
   */
  approvalMode?: "manual" | "bypass";
  onApprovalModeChange?: (mode: "manual" | "bypass") => void;
  // There is no Claude Code toggle: chatRoute is derived
  // from the selected model's `provider` in useChat (anthropic-cli →
  // CLI shell-out at /api/chat/cli, else → default Gemini chat-route).
  // Operators select claude-code in the model dropdown.
}

// ─── Approval Mode Dropdown ────────────────────────────────────────
//
// Two-option pill: "Manual approvals" (default — every gated tool
// shows an inline card) or "Bypass approvals" (auto-approve with
// audit row). Persisted in session.metadata.approval_mode via
// PATCH /api/agent/sessions/[id]. The chat handler picks up the new
// value on the next turn (30s cache TTL on the server, immediate
// re-read after the PATCH because the chat handler invalidates the
// cache when it writes the new value).
//
// Bypass shows a small yellow ⚠ icon in the pill and a fuller
// "Bypass ON" badge inline so the operator can't miss the state at
// a glance — bypass is a footgun if forgotten on a chat that ends
// up calling destructive tools.

function ApprovalModeDropdown({
  mode,
  onChange,
}: {
  mode: "manual" | "bypass";
  onChange: (next: "manual" | "bypass") => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  // How many tools the install gates (manifest approvals.humanRequired).
  // null = not loaded yet or unreadable: show the normal menu.
  const [gatedCount, setGatedCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchApprovalGating().then((g) => {
      if (!cancelled && g) setGatedCount(g.count);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  // Nothing is gated: Manual and Bypass behave the same, so the menu
  // would offer a choice that changes nothing. Say so instead.
  if (gatedCount === 0) {
    return (
      <div
        title="No tool on this install waits for an approval card, so there is nothing to switch. Which tools are gated comes from the bundle manifest."
        className="px-2.5 py-1.5 rounded-lg flex items-center gap-1.5 text-[11px] font-label text-on-surface-variant"
      >
        <span className="material-symbols-outlined text-base">lock_open</span>
        <span className="hidden sm:inline">No approvals</span>
      </div>
    );
  }

  const isBypass = mode === "bypass";
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label="Approval mode"
        title={
          isBypass
            ? "Approval bypass is ON — gated tools auto-execute. Click to change."
            : "Approval mode: manual. Click to change."
        }
        onClick={() => setOpen((prev) => !prev)}
        className={cn(
          "px-2.5 py-1.5 rounded-lg flex items-center gap-1.5 text-[11px] font-label transition-colors",
          isBypass
            ? "bg-tertiary/20 text-tertiary hover:bg-tertiary/30"
            : "hover:bg-white/5 text-on-surface-variant",
        )}
      >
        <span className="material-symbols-outlined text-base">
          {isBypass ? "bolt" : "verified_user"}
        </span>
        <span className="hidden sm:inline">
          {isBypass ? "Bypass ON" : "Approvals"}
        </span>
        <span className="material-symbols-outlined text-sm">
          arrow_drop_down
        </span>
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1 w-64 rounded-lg border border-white/10 bg-surface-container shadow-lg z-50 py-1"
          role="menu"
        >
          <button
            type="button"
            onClick={() => {
              onChange("manual");
              setOpen(false);
            }}
            className={cn(
              "w-full text-left px-3 py-2 text-xs flex items-start gap-2 hover:bg-white/5 transition-colors",
              mode === "manual" && "bg-white/5",
            )}
            role="menuitem"
          >
            <span className="material-symbols-outlined text-base text-on-surface-variant mt-0.5">
              verified_user
            </span>
            <span className="flex-1">
              <span className="block font-semibold text-on-surface">
                Manual approvals
              </span>
              <span className="block text-[10px] text-on-surface-variant mt-0.5">
                Default. Every gated tool shows an inline approval
                card.
              </span>
            </span>
            {mode === "manual" && (
              <span className="material-symbols-outlined text-sm text-primary">
                check
              </span>
            )}
          </button>
          <button
            type="button"
            onClick={() => {
              onChange("bypass");
              setOpen(false);
            }}
            className={cn(
              "w-full text-left px-3 py-2 text-xs flex items-start gap-2 hover:bg-white/5 transition-colors",
              mode === "bypass" && "bg-tertiary/10",
            )}
            role="menuitem"
          >
            <span className="material-symbols-outlined text-base text-tertiary mt-0.5">
              bolt
            </span>
            <span className="flex-1">
              <span className="block font-semibold text-on-surface">
                Bypass approvals
              </span>
              <span className="block text-[10px] text-on-surface-variant mt-0.5">
                Auto-approve gated tools. Audit rows still record
                every fired tool.
              </span>
            </span>
            {mode === "bypass" && (
              <span className="material-symbols-outlined text-sm text-tertiary">
                check
              </span>
            )}
          </button>
        </div>
      )}
    </div>
  );
}


// ─── Export Dropdown ─────────────────────────────────────────────────────────

function ExportDropdown({
  onExport,
}: {
  onExport: (format: ExportFormat) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label="Export conversation"
        onClick={() => setOpen((prev) => !prev)}
        className="p-2 rounded-lg hover:bg-white/5 transition-colors"
      >
        <span className="material-symbols-outlined text-on-surface-variant text-lg">
          download
        </span>
      </button>
      {open && (
        <div
          className="absolute right-0 top-full mt-1 w-44 py-1 rounded-xl z-50 shadow-xl"
          style={{
            // Theme-aware popover surface (was hardcoded
            // rgba(30, 30, 55, 0.95) — fine on dark, near-black on
            // light). glass-bg-elev is white-94% in light, navy-70%
            // in dark.
            background: "var(--glass-bg-elev)",
            backdropFilter: "blur(16px)",
            border: "0.5px solid var(--glass-border)",
          }}
        >
          {/* Session transcript exports (existing) — yaml/json/markdown
              of the operator-visible message turns (user / assistant /
              tool). What you'd send a colleague to read. */}
          <div className="px-3 pt-2 pb-1 text-[10px] uppercase tracking-wider text-on-surface-variant/60">
            Session transcript
          </div>
          {(
            [
              { format: "yaml" as const, icon: "data_object", label: "YAML" },
              { format: "json" as const, icon: "code", label: "JSON" },
              {
                format: "markdown" as const,
                icon: "description",
                label: "Markdown",
              },
            ] as const
          ).map((item) => (
            <button
              key={item.format}
              type="button"
              onClick={() => {
                onExport(item.format);
                setOpen(false);
              }}
              className="w-full text-left px-3 py-2 text-xs text-on-surface-variant hover:bg-white/5 flex items-center gap-2 transition-colors"
            >
              <span className="material-symbols-outlined text-sm">
                {item.icon}
              </span>
              {item.label}
            </button>
          ))}
          {/* Divider + trace export. Wire-event timeline
              derived from messages + their meta — operator-facing
              forensic view of the run, mirroring what the live
              telemetry panel shows after a session reload. Different
              data shape from the transcript: flat list of events with
              tool_call / tool_result / user_message / assistant_text
              entries, one row per event, JSON. */}
          <div className="my-1 border-t border-white/5" />
          <div className="px-3 pt-2 pb-1 text-[10px] uppercase tracking-wider text-on-surface-variant/60">
            Wire-event trace
          </div>
          <button
            type="button"
            onClick={() => {
              onExport("events");
              setOpen(false);
            }}
            className="w-full text-left px-3 py-2 text-xs text-on-surface-variant hover:bg-white/5 flex items-center gap-2 transition-colors"
            title="Flat event timeline derived from messages + meta. Includes tool_call, tool_result, user_message, assistant_text events. Streaming-only events (text_delta, cache_hit) are NOT included — capture from live SSE for those."
          >
            <span className="material-symbols-outlined text-sm">
              timeline
            </span>
            Events (JSON)
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Model Selector Dropdown ────────────────────────────────────────────────

function ModelSelectorDropdown({
  models,
  selectedModel,
  selectedProvider,
  currentLabel,
  online,
  sessionId,
  onModelChange,
  cacheHit,
}: {
  models: ModelOption[];
  selectedModel?: string;
  selectedProvider?: string;
  currentLabel: string;
  online: boolean;
  sessionId: string | null;
  onModelChange: (provider: string, model: string) => void;
  /** Vertex cache-hit signal. */
  cacheHit?: ChatHeaderProps["cacheHit"];
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  // Filter out WIP entries before grouping. The catalog
  // route still returns them so /services can render them as
  // "coming soon," but the chat dropdown stays operator-actionable —
  // only models that route end-to-end appear here.
  const pickable = models.filter((m) => !m.wip);

  // Group models by provider
  const grouped = pickable.reduce<Record<string, ModelOption[]>>((acc, m) => {
    const key = m.provider;
    if (!acc[key]) acc[key] = [];
    acc[key].push(m);
    return acc;
  }, {});

  const formatContext = (ctx: number): string => {
    if (ctx >= 1000) return `${Math.round(ctx / 1000)}K`;
    return String(ctx);
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex items-center gap-1.5 group"
        aria-label="Select model"
      >
        <span
          className={cn(
            "w-1.5 h-1.5 rounded-full shrink-0",
            online ? "bg-secondary" : "bg-outline",
          )}
        />
        {/* Vertex cache-hit indicator. Cyan
            dot adjacent to the green online dot tells the operator
            "this turn was billed at ~25% on the cached portion".
            Tooltip shows the cachedTokens / promptTokens ratio so
            they can quantify the savings. Hidden until the first
            cache_hit event lands. */}
        {cacheHit && (
          <span
            className="w-1.5 h-1.5 rounded-full shrink-0 bg-tertiary"
            title={
              cacheHit.promptTokens != null && cacheHit.promptTokens > 0
                ? `Vertex cache hit: ${cacheHit.cachedTokens.toLocaleString()} of ${cacheHit.promptTokens.toLocaleString()} prompt tokens cached (~${Math.round((cacheHit.cachedTokens / cacheHit.promptTokens) * 100)}% billed at ~25%)`
                : `Vertex cache hit: ${cacheHit.cachedTokens.toLocaleString()} cached tokens (~25% billing)`
            }
            aria-label="Vertex cache hit"
          />
        )}
        <span className="text-[11px] text-on-surface-variant font-label truncate group-hover:text-on-surface transition-colors">
          {currentLabel}
        </span>
        <span className="material-symbols-outlined text-on-surface-variant text-xs group-hover:text-on-surface transition-colors">
          expand_more
        </span>
        {sessionId && (
          <span className="text-[10px] text-outline font-mono">
            {sessionId.slice(0, 8)}
          </span>
        )}
      </button>

      {open && (
        <div
          className="absolute left-0 top-full mt-1 w-72 py-1 rounded-xl z-50 shadow-xl"
          style={{
            // Theme-aware: same pattern as the export popover above.
            // Was hardcoded rgba(40, 39, 55, 1) which read as a dark
            // overlay against the pale-azure light bg.
            background: "var(--glass-bg-elev)",
            border: "0.5px solid var(--glass-border)",
          }}
        >
          {Object.entries(grouped).map(([provider, providerModels]) => (
            <div key={provider}>
              <div className="px-3 py-1.5 text-[10px] font-label font-bold uppercase tracking-wider text-on-surface-variant/60">
                {provider}
              </div>
              {providerModels.map((m) => {
                const isSelected =
                  m.model === selectedModel && m.provider === selectedProvider;
                return (
                  <button
                    key={`${m.provider}/${m.model}`}
                    type="button"
                    onClick={() => {
                      onModelChange(m.provider, m.model);
                      setOpen(false);
                    }}
                    className={cn(
                      "w-full text-left px-3 py-2 text-xs flex items-center gap-2 transition-colors",
                      isSelected
                        ? "text-on-surface bg-white/5"
                        : "text-on-surface-variant hover:bg-white/5 hover:text-on-surface",
                    )}
                  >
                    <span
                      className={cn(
                        "material-symbols-outlined text-sm w-4",
                        isSelected ? "text-primary" : "invisible",
                      )}
                    >
                      check
                    </span>
                    <span className="flex-1 truncate">
                      {m.displayName || m.model}
                    </span>
                    <span className="flex items-center gap-1">
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/5 text-on-surface-variant">
                        {formatContext(m.contextWindow)}
                      </span>
                      {m.supportsThinking && (
                        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-primary/10 text-primary/80">
                          think
                        </span>
                      )}
                    </span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Compaction Badge ─────────────────────────────────────────────────────

/**
 * Tiny badge under the chat title showing the most-recent compaction
 * (operator /compress or auto-budget-edge). Click expands a popover
 * with the message count, summary char count, and timestamp.
 *
 * Hidden when there's no compaction yet (the parent passes
 * `compactionStats` only after a compaction_end event lands).
 *
 * Non-skipped compactions get the primary tint ("real work happened").
 * Skipped ones (the "nothing to compact yet" no-op) render in a quieter
 * outline-tone — same shape so the eye doesn't miss "wait, did I run
 * /compress?" but visually distinct so the operator knows it didn't do
 * anything.
 */
function CompactionBadge({
  stats,
}: {
  stats: NonNullable<ChatHeaderProps["compactionStats"]>;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const tone = stats.skipped
    ? "bg-white/5 text-on-surface-variant/70 hover:bg-white/10"
    : "bg-primary/10 text-primary hover:bg-primary/15";
  const label = stats.skipped
    ? "Nothing compacted"
    : `Compacted ${stats.messagesSummarized} ${
        stats.messagesSummarized === 1 ? "message" : "messages"
      }`;

  return (
    <div ref={ref} className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        className={cn(
          "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-label transition-colors",
          tone,
        )}
        aria-label={`${label} — click for details`}
        aria-expanded={open}
      >
        <span
          className="material-symbols-outlined text-[12px]"
          aria-hidden="true"
        >
          compress
        </span>
        {label}
      </button>

      {open && (
        <div
          className="absolute left-0 top-full mt-1 w-64 p-3 rounded-xl z-50 shadow-xl text-[11px] space-y-1.5"
          style={{
            background: "var(--glass-bg-elev)",
            backdropFilter: "blur(16px)",
            border: "0.5px solid var(--glass-border)",
          }}
          role="dialog"
        >
          <div className="font-headline text-[12px] font-bold text-on-surface">
            {stats.skipped ? "No compaction performed" : "Compaction summary"}
          </div>
          {stats.skipped ? (
            <p className="text-on-surface-variant leading-relaxed">
              The session had no prior turns to roll up — try
              <code className="font-mono mx-1 px-1 rounded bg-white/5">
                /compress
              </code>
              again after a few turns.
            </p>
          ) : (
            <>
              <Row
                label="Messages summarized"
                value={String(stats.messagesSummarized)}
              />
              <Row
                label="Summary chars"
                value={
                  stats.summaryChars != null
                    ? stats.summaryChars.toLocaleString()
                    : "—"
                }
              />
              <Row label="At" value={timeOnly(stats.at)} />
              <p className="text-on-surface-variant/70 pt-1 leading-relaxed">
                Future turns start from the summary instead of the
                full transcript. The original messages stay
                exportable.
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-on-surface-variant/60 font-label uppercase tracking-wider text-[9px]">
        {label}
      </span>
      <span className="text-on-surface font-mono">{value}</span>
    </div>
  );
}

function timeOnly(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso.slice(0, 8);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

// ─── Delete Button ───────────────────────────────────────────────────────────

/** The page's delete handler asks for confirmation in an in-app modal. */
function DeleteButton({ onDelete }: { onDelete: () => void }) {
  return (
    <button
      type="button"
      aria-label="Delete session"
      onClick={onDelete}
      className="p-2 rounded-lg transition-all hover:bg-white/5 text-on-surface-variant hover:text-red-400"
      title="Delete session"
    >
      <span className="material-symbols-outlined text-lg">delete</span>
    </button>
  );
}

// ─── Chat Header ─────────────────────────────────────────────────────────────

export function ChatHeader({
  sessionTitle,
  modelLabel,
  modelOnline,
  sessionId,
  onToggleSidebar,
  onExport,
  onDeleteSession,
  models,
  selectedModel,
  selectedProvider,
  onModelChange,
  debugPanelOpen,
  onToggleDebugPanel,
  subagentsEnabled,
  onToggleSubagents,
  compactionStats,
  cacheHit,
  approvalMode,
  onApprovalModeChange,
}: ChatHeaderProps) {
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleValue, setTitleValue] = useState(sessionTitle);
  const inputRef = useRef<HTMLInputElement>(null);

  // Sync external title changes
  useEffect(() => {
    setTitleValue(sessionTitle);
  }, [sessionTitle]);

  useEffect(() => {
    if (editingTitle && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editingTitle]);

  const commitTitle = useCallback(() => {
    setEditingTitle(false);
    // Title editing is cosmetic for now; the value is already set via state.
  }, []);

  return (
    <header className="px-6 py-3 flex items-center justify-between border-b border-white/5 shrink-0">
      {/* Left side */}
      <div className="flex items-center gap-3 min-w-0">
        <button
          type="button"
          aria-label="Toggle session panel"
          onClick={onToggleSidebar}
          className="p-2 rounded-lg hover:bg-white/5 transition-colors shrink-0"
        >
          <span className="material-symbols-outlined text-on-surface-variant text-lg">
            menu
          </span>
        </button>

        <div className="min-w-0">
          {/* Editable title */}
          {editingTitle ? (
            <input
              ref={inputRef}
              type="text"
              value={titleValue}
              onChange={(e) => setTitleValue(e.target.value)}
              onBlur={commitTitle}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitTitle();
                if (e.key === "Escape") {
                  setTitleValue(sessionTitle);
                  setEditingTitle(false);
                }
              }}
              className="bg-transparent text-on-surface font-headline text-base font-semibold outline-none border-b border-primary/50 w-full max-w-[300px]"
              aria-label="Session title"
            />
          ) : (
            <button
              type="button"
              onClick={() => setEditingTitle(true)}
              className="text-left"
              aria-label="Edit session title"
            >
              <h1 className="font-headline text-base font-semibold text-on-surface truncate max-w-[300px]">
                {titleValue || "New Chat"}
              </h1>
            </button>
          )}

          {/* Model info / selector + compaction
              badge. The badge sits inline with the model row so the
              eye sweep "title → status line" picks both up at once. */}
          <div className="mt-0.5 flex items-center gap-2 flex-wrap">
            {models && models.length > 0 && onModelChange ? (
              <ModelSelectorDropdown
                models={models}
                selectedModel={selectedModel}
                selectedProvider={selectedProvider}
                currentLabel={modelLabel}
                online={modelOnline}
                sessionId={sessionId}
                onModelChange={onModelChange}
                cacheHit={cacheHit}
              />
            ) : (
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "w-1.5 h-1.5 rounded-full shrink-0",
                    modelOnline ? "bg-secondary" : "bg-outline",
                  )}
                />
                {/* Cache-hit dot when the dropdown variant isn't
                    rendered (e.g., no models config). */}
                {cacheHit && (
                  <span
                    className="w-1.5 h-1.5 rounded-full shrink-0 bg-tertiary"
                    title={
                      cacheHit.promptTokens != null && cacheHit.promptTokens > 0
                        ? `Vertex cache hit: ${cacheHit.cachedTokens.toLocaleString()} of ${cacheHit.promptTokens.toLocaleString()} tokens cached`
                        : `Vertex cache hit: ${cacheHit.cachedTokens.toLocaleString()} cached tokens`
                    }
                    aria-label="Vertex cache hit"
                  />
                )}
                <span className="text-[11px] text-on-surface-variant font-label truncate">
                  {modelLabel}
                </span>
                {sessionId && (
                  <span className="text-[10px] text-outline font-mono">
                    {sessionId.slice(0, 8)}
                  </span>
                )}
              </div>
            )}
            {compactionStats && <CompactionBadge stats={compactionStats} />}
          </div>
        </div>
      </div>

      {/* Right side — explicit buttons, no hidden menus */}
      <div className="flex items-center gap-1 shrink-0">
        {/* Approval-mode dropdown. Renders pre-session too, so
            operators can preconfigure "bypass" mode before sending their
            first message. The page.tsx state lifecycle captures a pre-session intent in a ref and writes it
            to the new session's metadata once one is created. */}
        {onApprovalModeChange && (
          <ApprovalModeDropdown
            mode={approvalMode ?? "manual"}
            onChange={onApprovalModeChange}
          />
        )}
        {/* Selecting `claude-code` in the model dropdown
            (provider="anthropic-cli") drives the routing. See useChat's derivation
            of `chatRoute` from `overrideProvider`. */}
        {/* Subagent toggle. Defaults ON. Operator can disable
            while testing chat flows where they want deterministic
            single-agent execution. State persists to operator_state.db
            (so it survives page reload + cross-device). */}
        {onToggleSubagents && (
          <button
            type="button"
            onClick={onToggleSubagents}
            aria-label={
              subagentsEnabled
                ? "Disable subagent spawning"
                : "Enable subagent spawning"
            }
            aria-pressed={Boolean(subagentsEnabled)}
            className={cn(
              "p-2 rounded-lg transition-colors",
              subagentsEnabled
                ? "bg-primary/15 text-primary hover:bg-primary/20"
                : "hover:bg-white/5 text-on-surface-variant hover:text-on-surface opacity-60",
            )}
            title={
              subagentsEnabled
                ? "Subagents: ON — model may invoke subagent_create. Click to disable."
                : "Subagents: OFF — model can't spawn subagents this session. Click to enable."
            }
          >
            <span className="material-symbols-outlined text-lg">
              {subagentsEnabled ? "group" : "person"}
            </span>
          </button>
        )}
        {onToggleDebugPanel && (
          <button
            type="button"
            onClick={onToggleDebugPanel}
            aria-label={
              debugPanelOpen
                ? "Hide live telemetry panel"
                : "Show live telemetry panel"
            }
            aria-pressed={Boolean(debugPanelOpen)}
            className={cn(
              "p-2 rounded-lg transition-colors",
              debugPanelOpen
                ? "bg-primary/15 text-primary hover:bg-primary/20"
                : "hover:bg-white/5 text-on-surface-variant hover:text-on-surface",
            )}
            title="Live telemetry"
          >
            <span className="material-symbols-outlined text-lg">
              monitoring
            </span>
          </button>
        )}
        {onExport && sessionId && <ExportDropdown onExport={onExport} />}
        {onDeleteSession && sessionId && (
          <DeleteButton onDelete={onDeleteSession} />
        )}
      </div>
    </header>
  );
}
