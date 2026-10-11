"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

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
   *  from another, parentId names the source session. The sidebar
   *  groups forks visually under their parents (one level of
   *  indentation; deeper tree rendering is a future enhancement). */
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

// ─── Date Grouping ───────────────────────────────────────────────────────────

type DateGroup = "Today" | "Yesterday" | "Previous 7 Days" | "Older";

function getDateGroup(timestamp: string): DateGroup {
  const date = new Date(timestamp);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const sevenDaysAgo = new Date(today);
  sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);

  if (date >= today) return "Today";
  if (date >= yesterday) return "Yesterday";
  if (date >= sevenDaysAgo) return "Previous 7 Days";
  return "Older";
}

function groupSessionsByDate(
  sessions: SessionSummary[],
): Map<DateGroup, SessionSummary[]> {
  const groups = new Map<DateGroup, SessionSummary[]>();
  const order: DateGroup[] = ["Today", "Yesterday", "Previous 7 Days", "Older"];

  for (const group of order) {
    groups.set(group, []);
  }

  // Forks join the ROOT ancestor's
  // date group instead of their own creation-time group. This keeps
  // a parent + its forks visually adjacent even when the fork was
  // created on a different day. Within a group, ordering is parent first, then
  // forks in DFS order. Cycle-defended via a seen-set.
  const byId = new Map(sessions.map((s) => [s.id, s]));
  function rootAncestor(s: SessionSummary): SessionSummary {
    const seen = new Set<string>();
    let cur: SessionSummary = s;
    while (cur.parentId && !seen.has(cur.parentId)) {
      seen.add(cur.parentId);
      const parent = byId.get(cur.parentId);
      if (!parent) break;
      cur = parent;
    }
    return cur;
  }
  // Bucket sessions by their root ancestor's date group, preserving
  // the natural parent-first DFS order WITHIN a bucket. We sort the
  // list once on (rootGroup, rootTimestampDesc, depthAsc, ownTimestampDesc)
  // — rootGroup keeps a tree together, rootTimestampDesc puts newer
  // trees first within a group, depthAsc renders the root before its
  // children, ownTimestampDesc orders siblings newest-first.
  function depthOf(s: SessionSummary): number {
    const seen = new Set<string>();
    let depth = 0;
    let curId: string | null | undefined = s.parentId;
    while (curId && !seen.has(curId) && depth < 8) {
      seen.add(curId);
      depth += 1;
      curId = byId.get(curId)?.parentId ?? null;
    }
    return depth;
  }
  const decorated = sessions.map((s) => {
    const root = rootAncestor(s);
    return {
      session: s,
      rootGroup: getDateGroup(root.timestamp),
      rootTime: root.timestamp,
      depth: depthOf(s),
      ownTime: s.timestamp,
    };
  });
  decorated.sort((a, b) => {
    const ai = order.indexOf(a.rootGroup);
    const bi = order.indexOf(b.rootGroup);
    if (ai !== bi) return ai - bi;
    if (a.rootTime !== b.rootTime) {
      return a.rootTime < b.rootTime ? 1 : -1; // newer root first
    }
    if (a.depth !== b.depth) return a.depth - b.depth; // root before children
    return a.ownTime < b.ownTime ? 1 : -1; // newer sibling first
  });
  for (const d of decorated) {
    groups.get(d.rootGroup)?.push(d.session);
  }

  // Remove empty groups
  for (const [key, value] of groups) {
    if (value.length === 0) groups.delete(key);
  }

  return groups;
}

/** Compute the depth of a session in the fork tree.
 *  Walks parentId chain; defends against cycles + missing parents
 *  (returns the current depth instead of looping forever). */
function forkDepth(session: SessionSummary, allSessions: SessionSummary[]): number {
  if (!session.parentId) return 0;
  const byId = new Map(allSessions.map((s) => [s.id, s]));
  let depth = 0;
  const seen = new Set<string>();
  let curId: string | null | undefined = session.parentId;
  while (curId && !seen.has(curId) && depth < 8) {
    seen.add(curId);
    depth += 1;
    const parent = byId.get(curId);
    curId = parent?.parentId ?? null;
  }
  return depth;
}

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

// ─── Session Menu ────────────────────────────────────────────────────────────

interface SessionMenuProps {
  sessionId: string;
  currentTitle: string;
  onDelete: (id: string) => void;
  onExport: (id: string, format: ExportFormat) => void;
  onRename?: (id: string, title: string) => void;
  // Fork session. Optional: the /chat page wires this up; callers
  // without fork support get the menu without the Fork entry.
  onFork?: (id: string) => void;
}

function SessionMenu({
  sessionId,
  currentTitle,
  onDelete,
  onExport,
  onRename,
  onFork,
}: SessionMenuProps) {
  const [open, setOpen] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
        setConfirmingDelete(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const handleDelete = useCallback(() => {
    if (!confirmingDelete) {
      setConfirmingDelete(true);
      return;
    }
    onDelete(sessionId);
    setOpen(false);
    setConfirmingDelete(false);
  }, [confirmingDelete, onDelete, sessionId]);

  return (
    <div ref={menuRef} className="relative">
      <button
        type="button"
        aria-label="Session options"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((prev) => !prev);
          setConfirmingDelete(false);
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
          {onRename && (
            <>
              <div className="border-t border-white/5 my-1" />
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  // Simplest possible rename UX: a window.prompt with
                  // the current title pre-filled. An inline-edit
                  // affordance can come later.
                  const next = window.prompt(
                    "Rename chat session:",
                    currentTitle,
                  );
                  setOpen(false);
                  if (next == null) return; // cancelled
                  const trimmed = next.trim();
                  if (!trimmed || trimmed === currentTitle) return;
                  onRename(sessionId, trimmed);
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
              handleDelete();
            }}
            className={cn(
              "w-full text-left px-3 py-2 text-xs flex items-center gap-2 transition-colors",
              confirmingDelete
                ? "text-error bg-error/10"
                : "text-error/70 hover:bg-error/5",
            )}
          >
            <span className="material-symbols-outlined text-sm">delete</span>
            {confirmingDelete ? "Click again to confirm" : "Delete"}
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
  const grouped = groupSessionsByDate(sessions);

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

        {Array.from(grouped.entries()).map(([group, groupSessions]) => (
          <div key={group}>
            <h3 className="px-2 pb-1 text-[10px] font-headline uppercase tracking-widest text-on-surface-variant/60">
              {group}
            </h3>
            <div className="space-y-0.5">
              {groupSessions.map((session) => {
                const isActive = session.id === activeSessionId;
                // Visual fork
                // indicator. When session.parentId is set, indent
                // the row + render a fork glyph (call_split icon) to
                // make the parent → child relationship visible at
                // a glance.
                // Multi-level depth: walk parentId chain
                // to compute the indent depth. Cycle-defended (max
                // 8 levels — beyond that, render at the cap).
                const isFork = Boolean(session.parentId);
                const depth = forkDepth(session, sessions);
                return (
                  <button
                    key={session.id}
                    type="button"
                    onClick={() => onSelectSession(session.id)}
                    style={{ marginLeft: depth > 0 ? `${Math.min(depth, 8) * 16}px` : undefined }}
                    className={cn(
                      "group w-full text-left px-3 py-2.5 rounded-lg transition-all flex items-start gap-2",
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
                      {/* Title */}
                      <p
                        className={cn(
                          "text-xs leading-snug truncate",
                          isActive
                            ? "text-on-surface font-medium"
                            : "text-on-surface-variant",
                        )}
                      >
                        {session.title || session.firstMessage || "New conversation"}
                      </p>
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
                      currentTitle={
                        session.title ||
                        session.firstMessage ||
                        "New conversation"
                      }
                      onDelete={onDeleteSession}
                      onExport={onExportSession}
                      onRename={onRenameSession}
                      onFork={onForkSession}
                    />
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
