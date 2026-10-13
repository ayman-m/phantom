"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import {
  DATE_RANGES,
  appendPage,
  describeNotification,
  sinceForRange,
  type DateRange,
  type NotificationRow,
} from "@/lib/notification-display";
import { notify } from "@/lib/stores/notifications";

// Adapter — translate the phantom MCP's notification row shape
// (id/topic/severity/payload/created_at/read_at) into the Spark UI's
// Notification interface (title/description/icon/iconBg/iconColor/etc.).
// Title, description and the click target come from the payload via
// lib/notification-display.ts. Topic conventions:
//   job-run-*  → job card (success = system tab, failed = alerts tab)
//   cost-warning / context-warning → warning card (alerts tab)
//   approval:* → approval card (orange-ish)
//   error:*    → error variant (red)
//   security:* → security variant (red, shield icon)
//   channel:*  → connector fan-out
//   else       → generic system (blue)
function adaptNotif(row: NotificationRow): Notification {
  const topic = row.topic ?? "system";
  const isError = topic.startsWith("error");
  const isSecurity = topic.startsWith("security");
  const isApproval = topic.startsWith("approval");
  const isChannel = topic.startsWith("channel");
  const display = describeNotification(row);
  const isJob = topic === "job-run-completed" || topic === "job-run-failed";
  const isWarning = display.tone === "warning";
  const inferredType: Notification["type"] = isApproval
    ? "approval"
    : isWarning
    ? "warning"
    : isJob
    ? display.tone === "failure"
      ? "error"
      : "success"
    : isSecurity
    ? "security"
    : isError
    ? "error"
    : isChannel
    ? "connector"
    : "config";
  const icon = isApproval
    ? "verified_user"
    : isWarning
    ? "warning"
    : isJob
    ? display.tone === "failure"
      ? "error"
      : "check_circle"
    : isError
    ? "error"
    : isSecurity
    ? "gpp_maybe"
    : isChannel
    ? "cable"
    : "info";
  const palette = isApproval
    ? { iconBg: "bg-tertiary-container/30", iconColor: "text-tertiary" }
    : isWarning
    ? { iconBg: "bg-tertiary-container/30", iconColor: "text-tertiary" }
    : isJob && display.tone === "success"
    ? { iconBg: "bg-secondary-container/30", iconColor: "text-secondary" }
    : isError || (isJob && display.tone === "failure")
    ? { iconBg: "bg-error-container/30", iconColor: "text-error" }
    : isSecurity
    ? { iconBg: "bg-error-container/30", iconColor: "text-error" }
    : isChannel
    ? { iconBg: "bg-primary-container/30", iconColor: "text-primary" }
    : { iconBg: "bg-surface-container-high/50", iconColor: "text-on-surface-variant" };
  return {
    id: row.id,
    type: inferredType,
    title: display.title,
    description: display.description,
    href: display.href,
    timestamp: row.created_at
      ? new Date(row.created_at).toLocaleString()
      : "—",
    read: display.read,
    icon,
    iconBg: palette.iconBg,
    iconColor: palette.iconColor,
    actions: isApproval ? { approve: true, deny: true } : undefined,
  };
}

// ── Types ────────────────────────────────────────────────────────────────────

type FilterTab = "all" | "unread" | "approvals" | "alerts" | "system";

interface Notification {
  id: string;
  type: "approval" | "error" | "success" | "security" | "config" | "member" | "warning" | "job" | "offline" | "connector" | "resolved";
  title: string;
  description: string;
  timestamp: string;
  read: boolean;
  icon: string;
  iconFill?: boolean;
  iconBg: string;
  iconColor: string;
  avatarUrl?: string;
  /** In-app route opened when the row is clicked. */
  href?: string;
  actions?: { approve?: boolean; deny?: boolean };
  badge?: { label: string; color: string };
}

// ── Tab Defs ─────────────────────────────────────────────────────────────────
// Counts are derived from live notification state at render time, not
// hardcoded — fresh installs correctly read "0" across every tab and
// the footer's "Showing X of Y" reflects the actual store size.

const TAB_DEFS: { value: FilterTab; label: string }[] = [
  { value: "all", label: "All" },
  { value: "unread", label: "Unread" },
  { value: "approvals", label: "Approvals" },
  { value: "alerts", label: "Alerts" },
  { value: "system", label: "System" },
];

// ── Helpers ──────────────────────────────────────────────────────────────────

function matchesTab(n: Notification, tab: FilterTab): boolean {
  if (tab === "all") return true;
  if (tab === "unread") return !n.read;
  if (tab === "approvals") return n.type === "approval" || n.type === "resolved";
  if (tab === "alerts") return n.type === "error" || n.type === "security" || n.type === "warning" || n.type === "job" || n.type === "offline" || n.type === "connector";
  if (tab === "system") return n.type === "config" || n.type === "member" || n.type === "success";
  return true;
}

function matchesSearch(n: Notification, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    n.title.toLowerCase().includes(q) ||
    n.description.toLowerCase().includes(q)
  );
}

// ── Component ────────────────────────────────────────────────────────────────

const PAGE_SIZE = 50;

export default function NotificationsPage() {
  const [activeTab, setActiveTab] = useState<FilterTab>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [dateFilter, setDateFilter] = useState<DateRange>("all");
  const [dateMenuOpen, setDateMenuOpen] = useState(false);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  // Rows the store holds for the current date filter (not just the loaded
  // page); drives "Load more".
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // How many rows the server has handed back for the current filter: the
  // offset of the next page. Kept apart from notifications.length because a
  // repeated row is dropped when pages are appended.
  const fetchedRef = useRef(0);
  const router = useRouter();

  const fetchPage = useCallback(async (range: DateRange, offset: number) => {
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(offset),
    });
    const since = sinceForRange(range);
    if (since) params.set("since", since);
    const r = await fetch(`/api/agent/notifications?${params}`, {
      cache: "no-store",
    });
    if (!r.ok) throw new Error(`notifications fetch ${r.status}`);
    const data = (await r.json()) as { notifications?: unknown[]; total?: number };
    const rows = (data.notifications ?? []).map((row) =>
      adaptNotif(row as NotificationRow),
    );
    return { rows, total: typeof data.total === "number" ? data.total : offset + rows.length };
  }, []);

  // Live load from the phantom MCP's notification store via the
  // /api/agent/* proxy, again whenever the date filter changes. Empty store
  // → empty UI ("0 of 0"); no demo fallback so the page reflects real
  // operator state at all times.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const page = await fetchPage(dateFilter, 0);
        if (cancelled) return;
        fetchedRef.current = page.rows.length;
        setNotifications(page.rows);
        setTotal(page.total);
        setError(null);
      } catch (err) {
        if (!cancelled) setError(String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [dateFilter, fetchPage]);

  const loadMore = async () => {
    setLoadingMore(true);
    try {
      const page = await fetchPage(dateFilter, fetchedRef.current);
      fetchedRef.current += page.rows.length;
      setNotifications((prev) => appendPage(prev, page.rows));
      setTotal(page.total);
    } catch (err) {
      notify("error", "Could not load more notifications", String(err));
    } finally {
      setLoadingMore(false);
    }
  };

  // Mark one notification read: optimistic, rolled back if the store call
  // fails. A 404 means it was already read (or is gone), which is fine.
  const markRead = async (id: string) => {
    setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)));
    try {
      const r = await fetch(`/api/agent/notifications/${encodeURIComponent(id)}/ack`, {
        method: "POST",
      });
      if (!r.ok && r.status !== 404) throw new Error(`HTTP ${r.status}`);
    } catch (err) {
      setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, read: false } : n)));
      notify("error", "Could not mark the notification read", String(err));
    }
  };

  const markAllRead = async () => {
    setMarkingAll(true);
    try {
      const r = await fetch("/api/agent/notifications/ack-all", { method: "POST" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
    } catch (err) {
      notify("error", "Could not mark all notifications read", String(err));
    } finally {
      setMarkingAll(false);
    }
  };

  const source = notifications;
  const filtered = source.filter(
    (n) => matchesTab(n, activeTab) && matchesSearch(n, searchQuery),
  );
  // Derive per-tab counts from the live notification list so a fresh
  // install reads "0" across every tab (not the legacy hardcoded
  // demo numbers that misled operators into thinking the store had
  // pre-seeded rows).
  const tabCount = (tab: FilterTab): number =>
    source.filter((n) => matchesTab(n, tab)).length;
  const hasMore = source.length < total;

  return (
    <div className="p-8 min-h-screen space-y-6">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-on-surface">
            Notifications
          </h1>
          <p className="text-sm text-on-surface-variant mt-1">
            Platform alerts, approvals, and system events
          </p>
          {error ? (
            <p className="text-xs text-error mt-2">{error}</p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void markAllRead()}
            disabled={markingAll || !(source.some((n) => !n.read) || hasMore)}
            className="glass-panel flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-medium text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            aria-label="Mark all as read"
          >
            <span className="material-symbols-outlined text-base">done_all</span>
            {markingAll ? "Marking…" : "Mark All Read"}
          </button>
        </div>
      </div>

      {/* ── Filter Bar ─────────────────────────────────────────────────── */}
      <div className="glass-panel rounded-xl p-3 flex items-center justify-between gap-3">
        {/* Tab pills */}
        <div className="flex items-center gap-1 bg-surface-container-lowest/50 rounded-lg p-1">
          {TAB_DEFS.map((tab) => (
            <button
              key={tab.value}
              onClick={() => setActiveTab(tab.value)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors whitespace-nowrap",
                activeTab === tab.value
                  ? "bg-primary-container text-on-primary-container"
                  : "text-on-surface-variant hover:text-on-surface",
              )}
            >
              {tab.label} ({tabCount(tab.value)})
            </button>
          ))}
        </div>

        {/* Right controls */}
        <div className="flex items-center gap-2">
          {/* Search */}
          <div className="relative">
            <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-base text-on-surface-variant/60">
              search
            </span>
            <input
              type="text"
              placeholder="Search notifications..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-64 h-8 pl-8 pr-3 rounded-lg bg-surface-container-low border border-outline-variant/30 text-xs text-on-surface placeholder:text-on-surface-variant/50 focus:outline-none focus:border-primary/40 transition-colors"
            />
          </div>

          {/* Divider */}
          <div className="w-px h-6 bg-outline-variant/20" />

          {/* Date dropdown */}
          <div className="relative">
            <button
              onClick={() => setDateMenuOpen((o) => !o)}
              aria-haspopup="listbox"
              aria-expanded={dateMenuOpen}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-on-surface-variant hover:text-on-surface transition-colors"
            >
              <span className="material-symbols-outlined text-sm">calendar_today</span>
              {DATE_RANGES.find((d) => d.value === dateFilter)?.label}
              <span className="material-symbols-outlined text-sm">expand_more</span>
            </button>
            {dateMenuOpen && (
              <div
                role="listbox"
                className="glass-panel absolute right-0 top-full mt-1 z-20 min-w-36 rounded-lg p-1 shadow-lg"
              >
                {DATE_RANGES.map((d) => (
                  <button
                    key={d.value}
                    role="option"
                    aria-selected={dateFilter === d.value}
                    onClick={() => {
                      setDateFilter(d.value);
                      setDateMenuOpen(false);
                    }}
                    className={cn(
                      "block w-full text-left px-3 py-1.5 rounded-md text-xs transition-colors",
                      dateFilter === d.value
                        ? "bg-primary-container text-on-primary-container"
                        : "text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high/40",
                    )}
                  >
                    {d.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Notification Feed ──────────────────────────────────────────── */}
      <div className="space-y-3">
        {filtered.map((n) => (
          <div
            key={n.id}
            // Clicking a card marks it read and, when it names a target,
            // opens it.
            onClick={() => {
              if (!n.read) void markRead(n.id);
              if (n.href) router.push(n.href);
            }}
            onKeyDown={(e) => {
              if (e.target !== e.currentTarget) return;
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                if (!n.read) void markRead(n.id);
                if (n.href) router.push(n.href);
              }
            }}
            role={n.href ? "link" : "button"}
            tabIndex={0}
            className={cn(
              "glass-panel p-4 rounded-xl relative group transition-opacity cursor-pointer hover:bg-surface-container-high/30",
              n.read && n.type === "resolved" && "opacity-40",
              n.read && n.type !== "resolved" && n.type !== "offline" && n.type !== "connector" && "opacity-80",
              n.read && (n.type === "offline" || n.type === "connector" || n.type === "success") && n.timestamp.includes("hr") && "opacity-60",
            )}
          >
            {/* Unread indicator bar */}
            {!n.read && (
              <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-8 bg-primary rounded-r-full shadow-[0_0_8px_rgba(167,200,255,0.4)]" />
            )}

            <div className="flex items-start gap-4">
              {/* Icon */}
              {n.avatarUrl ? (
                <div className="w-10 h-10 rounded-xl overflow-hidden flex-shrink-0">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={n.avatarUrl}
                    alt=""
                    className="w-full h-full object-cover"
                  />
                </div>
              ) : (
                <div
                  className={cn(
                    "w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0",
                    n.iconBg,
                  )}
                >
                  <span
                    className={cn(
                      "material-symbols-outlined text-xl",
                      n.iconColor,
                    )}
                    style={n.iconFill ? { fontVariationSettings: "'FILL' 1" } : undefined}
                  >
                    {n.icon}
                  </span>
                </div>
              )}

              {/* Content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <h3 className="text-sm font-semibold text-on-surface truncate">
                      {n.title}
                    </h3>
                    <p className="text-xs text-on-surface-variant mt-0.5 line-clamp-2">
                      {n.description}
                    </p>
                    {n.badge && (
                      <div className="flex items-center gap-2 mt-2">
                        <span className={cn("text-[10px] font-mono px-2 py-0.5 rounded bg-surface-container-lowest/50", n.badge.color)}>
                          {n.badge.label}
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Timestamp */}
                  <span className="text-[10px] font-mono text-on-surface-variant/60 whitespace-nowrap flex-shrink-0">
                    {n.timestamp}
                  </span>
                </div>

                {/* Action buttons for approvals */}
                {n.actions && (
                  <div className="flex items-center gap-2 mt-3">
                    {n.actions.approve && (
                      <button className="px-4 py-1.5 rounded-lg bg-secondary/20 text-secondary text-xs font-medium hover:bg-secondary/30 transition-colors">
                        Approve
                      </button>
                    )}
                    {n.actions.deny && (
                      <button className="px-4 py-1.5 rounded-lg bg-error/10 text-error text-xs font-medium hover:bg-error/20 transition-colors">
                        Deny
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* ── Footer ─────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between pt-2">
        <span className="text-xs text-on-surface-variant/60 font-mono">
          Showing {filtered.length} of {source.length}{" "}
          {hasMore ? `loaded (${total} in the store)` : "notifications"}
        </span>
        {hasMore && (
          <button
            onClick={() => void loadMore()}
            disabled={loadingMore}
            className="glass-panel px-4 py-2 rounded-xl text-xs font-medium text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loadingMore ? "Loading…" : `Load more (${total - source.length} remaining)`}
          </button>
        )}
      </div>
    </div>
  );
}
