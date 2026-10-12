"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { groupSessionTree } from "@/lib/session-tree";

// ─── Types ───────────────────────────────────────────────────────────────────

export interface SessionSummary {
  id: string;
  firstMessage: string;
  timestamp: string;
  modelBadge: string;
  tokenCount: number;
  /** Optional operator-set title that overrides the firstMessage in
   *  the sidebar display. Set via the Rename action in SessionMenu. */
  title?: string;
  /** When this session was forked
   *  from another, parentId names the source session. The sidebar lists
   *  a fork directly under its parent, indented one level per
   *  generation (see lib/session-tree.ts). */
  parentId?: string | null;
}

// The "events" format exports a wire-event trace.
// Backed by the same endpoint with ?format=events.
type ExportFormat = "yaml" | "json" | "markdown" | "events";

export interface SessionSidebarProps {
  sessions: SessionSummary[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onDeleteSession: (id: string) => void;
  onExportSession: (id: string, format: ExportFormat) => void;
  /** Rename a session. Receives the new title (already trimmed,
   *  non-empty); the parent handles persistence + local state update. */
  onRenameSession?: (id: string, title: string) => void;
  /** Fork a session from its full message
   *  history. Parent POSTs to /api/agent/sessions/{id}/fork, then
   *  switches to the new session. */
  onForkSession?: (id: string) => void;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

// ─── Glass Panel Style ───────────────────────────────────────────────────────

const glassPanel = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  borderRight: "0.5px solid var(--glass-border)",
} as const;

function formatTime(timestamp: string): string {
  const date = new Date(timestamp);
  return date.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatTokenCount(count: number): string {
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1)}k`;
  }
  return String(count);
}

// ─── Inline rename editor ────────────────────────────────────────────────────

/**
 * Replaces a row's title while it is being renamed. Enter saves, Escape
 * cancels, and leaving the field saves (the same as Enter). An empty or
 * unchanged name is a cancel.
 */
function RenameField({
  initial,
  onSave,
  onCancel,
}: {
  initial: string;
  onSave: (title: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  const inputRef = useRef<HTMLInputElement>(null);
  // Enter/Escape finish the edit; the blur that follows must not finish it again.
  const finished = useRef(false);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  function commit() {
    if (finished.current) return;
    finished.current = true;
    const next = value.trim();
    if (!next || next === initial.trim()) onCancel();
    else onSave(next);
  }

  return (
    <input
      ref={inputRef}
      type="text"
      value={value}
      maxLength={200}
      aria-label="Session name"
      onChange={(e) => setValue(e.target.value)}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === "Enter") {
          e.preventDefault();
          commit();
        } else if (e.key === "Escape") {
          e.preventDefault();
          finished.current = true;
          onCancel();
        }
      }}
      onBlur={commit}
      className="w-full rounded-md px-1.5 py-1 text-xs text-on-surface bg-surface-container-low border border-primary/60 focus:outline-none focus:ring-1 focus:ring-primary"
    />
  );
}

// ─── Session Menu ────────────────────────────────────────────────────────────

interface SessionMenuProps {
  sessionId: string;
  /** Delete the session. The parent asks for confirmation (in-app modal). */
  onDelete: (id: string) => void;
  onExport: (id: string, format: ExportFormat) => void;
  /** Start inline rename: the row's title becomes an editor. */
  onStartRename?: (id: string) => void;
  // Fork session. Optional: the /chat page wires this up; callers
  // without fork support get the menu without the Fork entry.
  onFork?: (id: string) => void;
}

function SessionMenu({
  sessionId,
  onDelete,
  onExport,
  onStartRename,
  onFork,
}: SessionMenuProps) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  return (
    <div ref={menuRef} className="relative">
      <button
        type="button"
        aria-label="Session options"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((prev) => !prev);
        }}
        className="p-1 rounded-md hover:bg-white/10 opacity-0 group-hover:opacity-100 transition-opacity"
      >
        <span className="material-symbols-outlined text-sm text-on-surface-variant">
          more_vert
        </span>
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1 w-48 py-1 rounded-xl z-50 shadow-xl"
          style={{
            // Theme-aware popover surface — was hardcoded
            // rgba(30, 30, 55, 0.95) which read as a dim near-black
            // overlay against the pale-azure sidebar in light theme.
            // glass-bg-elev is a stronger-elevation variant (95-94%
            // opaque in both themes) that contrasts cleanly with
            // either page bg.
            background: "var(--glass-bg-elev)",
            backdropFilter: "blur(16px)",
            border: "0.5px solid var(--glass-border)",
          }}
        >
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onExport(sessionId, "yaml");
              setOpen(false);
            }}
            className="w-full text-left px-3 py-2 text-xs text-on-surface-variant hover:bg-white/5 flex items-center gap-2 transition-colors"
          >
            <span className="material-symbols-outlined text-sm">
              data_object
            </span>
            Export YAML
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onExport(sessionId, "json");
              setOpen(false);
            }}
            className="w-full text-left px-3 py-2 text-xs text-on-surface-variant hover:bg-white/5 flex items-center gap-2 transition-colors"
          >
            <span className="material-symbols-outlined text-sm">code</span>
            Export JSON
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onExport(sessionId, "markdown");
              setOpen(false);
            }}
            className="w-full text-left px-3 py-2 text-xs text-on-surface-variant hover:bg-white/5 flex items-center gap-2 transition-colors"
          >
            <span className="material-symbols-outlined text-sm">
              description
            </span>
            Export Markdown
          </button>
          {/* Wire-event trace export. JSON-shaped event
              timeline derived from messages + meta — operator-facing
              forensic view of the run. Distinct from the JSON option
              above (which is the full session+messages snapshot). */}
          <div className="my-1 border-t border-white/5" />
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onExport(sessionId, "events");
              setOpen(false);
            }}
            className="w-full text-left px-3 py-2 text-xs text-on-surface-variant hover:bg-white/5 flex items-center gap-2 transition-colors"
            title="Export the full session event timeline (JSON). Unified format: includes both persisted messages (user_message, tool_call, tool_result, assistant_text) AND chat_* audit events (cache_hit, turn_cost, compaction_*, context_warning, plan_proposed, subagent_*). Only per-token text_delta events are not included — those live in the live-telemetry panel's export only (we don't persist them; would inflate row count 100×). This is the export to share with someone reviewing a session post-hoc."
          >
            <span className="material-symbols-outlined text-sm">
              timeline
            </span>
            Export Events (JSON)
          </button>
          {onStartRename && (
            <>
              <div className="border-t border-white/5 my-1" />
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setOpen(false);
                  onStartRename(sessionId);
                }}
                className="w-full text-left px-3 py-2 text-xs text-on-surface-variant hover:bg-white/5 flex items-center gap-2 transition-colors"
              >
                <span className="material-symbols-outlined text-sm">
                  edit
                </span>
                Rename
              </button>
            </>
          )}
          {onFork && (
            <>
              <div className="border-t border-white/5 my-1" />
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onFork(sessionId);
                  setOpen(false);
                }}
                className="w-full text-left px-3 py-2 text-xs text-on-surface-variant hover:bg-white/5 flex items-center gap-2 transition-colors"
                title="Branch a new session from this one's full message history. Useful for hypothetical-exploration: 'what if we hadn't blocked the IP?' branches without losing the original."
              >
                <span className="material-symbols-outlined text-sm">
                  call_split
                </span>
                Fork session
              </button>
            </>
          )}
          <div className="border-t border-white/5 my-1" />
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setOpen(false);
              onDelete(sessionId);
            }}
            className="w-full text-left px-3 py-2 text-xs flex items-center gap-2 transition-colors text-error/70 hover:bg-error/5 hover:text-error"
          >
            <span className="material-symbols-outlined text-sm">delete</span>
            Delete
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Session Sidebar ─────────────────────────────────────────────────────────

export function SessionSidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  onExportSession,
  onRenameSession,
  onForkSession,
  collapsed = false,
  onToggleCollapse,
}: SessionSidebarProps) {
  const grouped = groupSessionTree(sessions, new Date());
  // The session whose title is being edited inline (null when none).
  const [renamingId, setRenamingId] = useState<string | null>(null);

  if (collapsed) {
    return (
      <div
        className="w-12 shrink-0 flex flex-col items-center pt-4 border-r border-white/5"
        style={glassPanel}
      >
        <button
          type="button"
          aria-label="Expand session panel"
          onClick={onToggleCollapse}
          className="p-2 rounded-lg hover:bg-white/10 transition-colors"
        >
          <span className="material-symbols-outlined text-on-surface-variant text-lg">
            chevron_right
          </span>
        </button>
        <button
          type="button"
          aria-label="New chat"
          onClick={onNewChat}
          className="mt-2 p-2 rounded-lg hover:bg-white/10 transition-colors"
        >
          <span className="material-symbols-outlined text-primary text-lg">
            add
          </span>
        </button>
      </div>
    );
  }

  return (
    <div
      className="w-[280px] shrink-0 flex flex-col h-full overflow-hidden"
      style={glassPanel}
    >
      {/* Header */}
      <div className="px-4 py-4 flex items-center justify-between border-b border-white/5">
        <h2 className="text-xs font-headline uppercase tracking-widest text-on-surface-variant">
          Sessions
        </h2>
        <button
          type="button"
          aria-label="Collapse session panel"
          onClick={onToggleCollapse}
          className="p-1 rounded-md hover:bg-white/10 transition-colors"
        >
          <span className="material-symbols-outlined text-on-surface-variant text-sm">
            chevron_left
          </span>
        </button>
      </div>

      {/* New Chat Button — matches the "Create Skill" CTA on /skills:
          white text, bold headline, primary blue gradient, soft drop
          shadow. `text-on-surface` would flip with
          theme — dark navy text over a blue gradient in light
          mode (low contrast). Hard-coding `text-white` is correct here
          because the gradient is theme-invariant. */}
      <div className="px-4 pt-4 pb-2">
        <button
          type="button"
          onClick={onNewChat}
          className="w-full px-6 py-2.5 rounded-xl text-sm font-bold font-headline text-white flex items-center justify-center gap-2 shadow-[0px_20px_40px_rgba(25,99,179,0.15)] active:scale-95 transition-transform"
          style={{
            background: "linear-gradient(135deg, #1963b3 0%, #2d8df0 100%)",
          }}
        >
          <span className="material-symbols-outlined text-base">add</span>
          New Chat
        </button>
      </div>

      {/* Session List */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-4 custom-scrollbar">
        {sessions.length === 0 && (
          <div className="text-center py-8">
            <span className="material-symbols-outlined text-3xl text-on-surface-variant/30">
              chat_bubble_outline
            </span>
            <p className="text-xs text-on-surface-variant/50 mt-2 font-label">
              No sessions yet
            </p>
          </div>
        )}

        {grouped.map(({ group, rows }) => (
          <div key={group}>
            <h3 className="px-2 pb-1 text-[10px] font-headline uppercase tracking-widest text-on-surface-variant/60">
              {group}
            </h3>
            <div className="space-y-0.5">
              {rows.map(({ session, depth }) => {
                const isActive = session.id === activeSessionId;
                // A fork is listed directly under its parent (the tree
                // ordering is lib/session-tree.ts), indented 16px per
                // generation (capped at 8) and marked with the branch
                // glyph. A fork whose parent is no longer in the list
                // keeps the glyph but renders as a root.
                const isFork = Boolean(session.parentId);
                const isRenaming = renamingId === session.id;
                const displayTitle =
                  session.title || session.firstMessage || "New conversation";
                return (
                  <div
                    key={session.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => {
                      if (!isRenaming) onSelectSession(session.id);
                    }}
                    onKeyDown={(e) => {
                      // Only the row itself: keys typed in the rename field or
                      // pressed on the menu buttons must not select the row.
                      if (e.target !== e.currentTarget) return;
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onSelectSession(session.id);
                      }
                    }}
                    style={{ marginLeft: depth > 0 ? `${Math.min(depth, 8) * 16}px` : undefined }}
                    className={cn(
                      "group w-full text-left px-3 py-2.5 rounded-lg transition-all flex items-start gap-2 cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary",
                      isActive
                        ? "bg-secondary-container/15 border-l-2 border-secondary"
                        : "hover:bg-white/5 border-l-2 border-transparent",
                    )}
                  >
                    <div className="flex-1 min-w-0">
                      {/* Model + (when forked) fork-from badge */}
                      <div className="flex items-center gap-1.5 mb-0.5">
                        <span className="inline-block px-1.5 py-0.5 rounded text-[9px] font-mono bg-[#ffc05f]/15 text-[#ffc05f] truncate max-w-[120px]">
                          {session.modelBadge}
                        </span>
                        {isFork && (
                          <span
                            className="material-symbols-outlined text-[12px] text-secondary"
                            title={`Forked from ${session.parentId?.slice(0, 12) ?? ""}…`}
                          >
                            call_split
                          </span>
                        )}
                      </div>
                      {/* Title (an inline editor while renaming) */}
                      {isRenaming ? (
                        <RenameField
                          initial={displayTitle}
                          onSave={(next) => {
                            setRenamingId(null);
                            onRenameSession?.(session.id, next);
                          }}
                          onCancel={() => setRenamingId(null)}
                        />
                      ) : (
                        <p
                          className={cn(
                            "text-xs leading-snug truncate",
                            isActive
                              ? "text-on-surface font-medium"
                              : "text-on-surface-variant",
                          )}
                        >
                          {displayTitle}
                        </p>
                      )}
                      {/* Meta: time + tokens */}
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-[10px] text-outline">
                          {formatTime(session.timestamp)}
                        </span>
                        {session.tokenCount > 0 && (
                          <span className="text-[10px] text-outline flex items-center gap-0.5">
                            <span className="material-symbols-outlined text-[10px]">
                              token
                            </span>
                            {formatTokenCount(session.tokenCount)}
                          </span>
                        )}
                      </div>
                    </div>
                    {/* Menu */}
                    <SessionMenu
                      sessionId={session.id}
                      onDelete={onDeleteSession}
                      onExport={onExportSession}
                      onStartRename={
                        onRenameSession ? (id) => setRenamingId(id) : undefined
                      }
                      onFork={onForkSession}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
