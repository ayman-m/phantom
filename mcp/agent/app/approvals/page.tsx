"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchApprovalGating, listApprovals, resolveApproval } from "@/lib/api/approvals";
import { useNotificationsStore } from "@/lib/stores/notifications";
import type { Approval } from "@/lib/api/types";

type TabValue = "pending" | "resolved";

function getRiskLevel(toolName: string): "HIGH" | "MEDIUM" | "LOW" {
  const high = ["send_email", "delete", "drop", "remove", "execute_command"];
  const medium = ["write_file", "post", "update", "modify"];
  const lower = toolName.toLowerCase();
  if (high.some((k) => lower.includes(k))) return "HIGH";
  if (medium.some((k) => lower.includes(k))) return "MEDIUM";
  return "LOW";
}

const RISK_COLORS: Record<string, { border: string; badge: string; codeBg: string; codeText: string }> = {
  HIGH: {
    border: "border-[#B72721]",
    badge: "bg-[#B72721] text-on-surface",
    codeBg: "bg-error-container/20",
    codeText: "text-error",
  },
  MEDIUM: {
    border: "border-[#E2A614]",
    badge: "bg-[#E2A614] text-on-surface",
    codeBg: "bg-tertiary-container/20",
    codeText: "text-tertiary",
  },
  LOW: {
    border: "border-[#56B55A]",
    badge: "bg-[#56B55A] text-on-surface",
    codeBg: "bg-secondary-container/20",
    codeText: "text-secondary",
  },
};

// Chat-origin approvals are resolved INLINE in the chat
// where they were requested, so /approvals shouldn't actively
// surface them as actionable items to operators (would create a
// double-resolve race between the chat card and this page). We
// still RECORD them for audit — the "Show chat-origin too" toggle
// reveals them on demand. Predicate centralizes the rule.
function isChatOrigin(a: Approval): boolean {
  return typeof a.origin === "string" && a.origin.startsWith("chat:");
}

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resolvingIds, setResolvingIds] = useState<Set<string>>(new Set());
  const [activeTab, setActiveTab] = useState<TabValue>("pending");
  const [searchQuery, setSearchQuery] = useState("");
  // Include chat-origin approvals in the Pending tab too?
  // Default off — chat-origin is meant to resolve inline. Toggle on
  // for audit / "I want to override the chat resolution from here".
  const [includeChatOrigin, setIncludeChatOrigin] = useState(false);

  const pending = useMemo(
    () =>
      approvals.filter(
        (a) =>
          a.status === "pending" &&
          (includeChatOrigin || !isChatOrigin(a)),
      ),
    [approvals, includeChatOrigin],
  );

  // Count of chat-origin pending rows that are HIDDEN by the default
  // filter, so the toggle label can show "(N hidden)" — gives the
  // operator a reason to flip it.
  const hiddenChatPending = useMemo(
    () =>
      approvals.filter(
        (a) => a.status === "pending" && isChatOrigin(a),
      ).length,
    [approvals],
  );

  const resolved = useMemo(
    () =>
      approvals
        .filter((a) => a.status !== "pending")
        .sort(
          (a, b) =>
            new Date(b.resolvedAt ?? b.createdAt).getTime() -
            new Date(a.resolvedAt ?? a.createdAt).getTime(),
        ),
    [approvals],
  );

  const deniedCount = useMemo(
    () => approvals.filter((a) => a.status === "denied").length,
    [approvals],
  );

  const approvedCount = useMemo(
    () => approvals.filter((a) => a.status === "approved").length,
    [approvals],
  );

  const displayedItems = useMemo(() => {
    const items = activeTab === "pending" ? pending : resolved;
    if (!searchQuery) return items;
    const q = searchQuery.toLowerCase();
    return items.filter(
      (a) =>
        a.agentId.toLowerCase().includes(q) ||
        a.toolName.toLowerCase().includes(q) ||
        a.description.toLowerCase().includes(q),
    );
  }, [activeTab, pending, resolved, searchQuery]);

  const fetchApprovals = useCallback(async () => {
    const result = await listApprovals();
    if (result.ok) {
      setApprovals(result.data);
      setError(null);
      const pendingCount = result.data.filter(
        (a) => a.status === "pending",
      ).length;
      useNotificationsStore.setState({ pendingApprovals: pendingCount });
    } else {
      setError(result.error.message);
    }
    setIsLoading(false);
  }, []);

  const handleResolve = useCallback(
    async (id: string, decision: "approved" | "denied") => {
      setResolvingIds((prev) => new Set(prev).add(id));
      const result = await resolveApproval(id, { resolution: decision });
      if (result.ok) {
        setApprovals((prev) =>
          prev.map((a) => (a.id === id ? result.data : a)),
        );
        useNotificationsStore.getState().decrementApprovals();
      }
      setResolvingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    },
    [],
  );

  const handleApprove = useCallback(
    (id: string) => handleResolve(id, "approved"),
    [handleResolve],
  );

  const handleDeny = useCallback(
    (id: string) => handleResolve(id, "denied"),
    [handleResolve],
  );

  useEffect(() => {
    fetchApprovals();
  }, [fetchApprovals]);

  // TODO: migrate to per-run SSE streaming for real-time approval updates
  useEffect(() => {
    const interval = setInterval(fetchApprovals, 30_000);
    return () => clearInterval(interval);
  }, [fetchApprovals]);

  // How many tools the install gates (manifest approvals.humanRequired).
  // 0 = nothing waits here; null = not loaded or unreadable (no notice).
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

  if (isLoading) {
    return (
      <div className="p-8 min-h-screen flex items-center justify-center text-on-surface-variant">
        Loading approvals…
      </div>
    );
  }

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-8 space-y-6">
        {/* Page Header — matches /skills layout pattern */}
        <header>
          <div className="flex items-center gap-3 mb-1">
            <span className="material-symbols-outlined text-2xl text-primary">
              verified_user
            </span>
            <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
              Approvals
            </h1>
          </div>
          <p className="text-sm text-on-surface-variant ml-9">
            Review and resolve agent tool-call approval requests.
          </p>
        </header>

        {gatedCount === 0 && (
          <div className="rounded-xl glass-panel border-l-4 border-primary px-5 py-4 text-sm text-on-surface-variant">
            No tool on this install waits for approval, so nothing new will
            appear here. Calls run at once and are recorded in the audit log;
            requests resolved earlier stay in the Resolved tab.
          </div>
        )}

      {error && (
        <div className="rounded-xl glass-panel border-l-4 border-error px-5 py-4 text-sm text-error mb-6">
          {error}
        </div>
      )}

      {/* Tabs and Filters */}
      <section className="space-y-6">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b border-white/5 pb-1">
          <div className="flex gap-8">
            <button
              type="button"
              onClick={() => setActiveTab("pending")}
              className={`pb-4 font-bold text-sm relative ${
                activeTab === "pending"
                  ? "text-secondary border-b-2 border-secondary"
                  : "text-on-surface/50 hover:text-on-surface font-medium transition-all"
              }`}
            >
              Pending ({pending.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("resolved")}
              className={`pb-4 font-medium text-sm transition-all ${
                activeTab === "resolved"
                  ? "text-secondary border-b-2 border-secondary font-bold"
                  : "text-on-surface/50 hover:text-on-surface"
              }`}
            >
              Resolved
            </button>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex-1 min-w-[300px] relative">
            <span className="material-symbols-outlined absolute left-4 top-1/2 -translate-y-1/2 text-on-surface/30">
              search
            </span>
            <input
              className="w-full bg-surface-container-high border-none rounded-xl py-3 pl-12 pr-4 text-sm focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface/30"
              placeholder="Search by agent, tool, or description..."
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
          {/* Chat-origin filter toggle. Default off (chat
              approvals are resolved inline in their chat session;
              showing them here too creates double-resolve races).
              Operators can flip it on for audit / cross-session
              override use cases. */}
          {activeTab === "pending" && (
            <label
              className="flex items-center gap-2 text-sm text-on-surface-variant cursor-pointer select-none"
              title="Chat-origin approvals normally resolve inline in the chat session that requested them. Enable to show them here too."
            >
              <input
                type="checkbox"
                checked={includeChatOrigin}
                onChange={(e) => setIncludeChatOrigin(e.target.checked)}
                className="rounded border-on-surface/20 text-primary focus:ring-primary/40"
              />
              <span>
                Include chat-origin
                {hiddenChatPending > 0 && !includeChatOrigin && (
                  <span className="ml-1 text-on-surface/60">
                    ({hiddenChatPending} hidden)
                  </span>
                )}
              </span>
            </label>
          )}
        </div>
        <p className="text-xs text-on-surface-variant/70 mt-3">
          By default, the Pending tab hides approvals that originated
          from a live chat session — those resolve inline in the chat
          itself. The Resolved tab below shows everything for audit,
          including chat-resolved rows.
        </p>
      </section>

      {/* Approvals Grid */}
      <section className="mt-8 grid grid-cols-1 gap-4">
        {displayedItems.length === 0 ? (
          <div className="glass-panel rounded-2xl p-12 text-center text-on-surface-variant">
            {activeTab === "pending"
              ? "No pending approvals. When agents request tool approvals, they will appear here."
              : "No resolved approvals yet."}
          </div>
        ) : activeTab === "pending" ? (
          displayedItems.map((approval) => {
            const risk = getRiskLevel(approval.toolName);
            const colors = RISK_COLORS[risk];
            const isResolving = resolvingIds.has(approval.id);
            return (
              <div
                key={approval.id}
                className={`glass-panel rounded-2xl p-5 border-l-4 ${colors.border} flex items-start gap-6 group hover:bg-white/[0.05] transition-all`}
              >
                <div className="flex-1 grid grid-cols-1 md:grid-cols-4 gap-6 items-center">
                  <div className="md:col-span-1">
                    <div className="flex items-center gap-3 mb-1">
                      <span className="text-xs font-bold font-headline uppercase tracking-tighter text-on-surface/40">
                        Agent
                      </span>
                    </div>
                    <p className="font-bold text-on-surface">{approval.agentId}</p>
                    <p className="text-[10px] text-on-surface/40">Run #{approval.runId}</p>
                  </div>
                  <div className="md:col-span-1">
                    <div className="flex items-center gap-3 mb-1">
                      <span className="text-xs font-bold font-headline uppercase tracking-tighter text-on-surface/40">
                        Tool
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <code className={`text-xs ${colors.codeBg} ${colors.codeText} px-2 py-1 rounded`}>
                        {approval.toolName}
                      </code>
                      <span className={`${colors.badge} text-[9px] font-black px-1.5 py-0.5 rounded italic`}>
                        {risk}
                      </span>
                    </div>
                  </div>
                  <div className="md:col-span-1">
                    <div className="flex items-center gap-3 mb-1">
                      <span className="text-xs font-bold font-headline uppercase tracking-tighter text-on-surface/40">
                        Description
                      </span>
                    </div>
                    <p className="text-sm line-clamp-1">{approval.description}</p>
                  </div>
                  <div className="flex justify-end items-center gap-3">
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => handleDeny(approval.id)}
                        disabled={isResolving}
                        className="w-10 h-10 rounded-lg border border-error/20 text-error flex items-center justify-center hover:bg-error/10 transition-colors disabled:opacity-50"
                        aria-label={`Deny ${approval.toolName}`}
                      >
                        <span className="material-symbols-outlined text-xl">close</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleApprove(approval.id)}
                        disabled={isResolving}
                        className="px-5 py-2 rounded-lg bg-[#56B55A] text-on-surface font-bold text-sm shadow-lg shadow-[#56B55A]/10 hover:brightness-110 transition-all disabled:opacity-50"
                        aria-label={`Approve ${approval.toolName}`}
                      >
                        {isResolving ? "…" : "Approve"}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            );
          })
        ) : (
          displayedItems.map((approval) => {
            const statusStyles: Record<string, string> = {
              approved: "text-secondary bg-secondary/10",
              denied: "text-error bg-error/10",
              expired: "text-outline bg-outline/10",
            };
            const style = statusStyles[approval.status] ?? "text-on-surface-variant bg-white/5";
            return (
              <div
                key={approval.id}
                className="glass-panel rounded-2xl p-5 flex items-center gap-6 group hover:bg-white/[0.05] transition-all"
              >
                <div className="flex-1 grid grid-cols-1 md:grid-cols-5 gap-6 items-center">
                  <div>
                    <span className="text-[10px] font-headline uppercase tracking-tighter text-on-surface/40">
                      Agent
                    </span>
                    <p className="font-bold text-on-surface">{approval.agentId}</p>
                  </div>
                  <div>
                    <span className="text-[10px] font-headline uppercase tracking-tighter text-on-surface/40">
                      Tool
                    </span>
                    <p className="text-sm font-medium">{approval.toolName}</p>
                  </div>
                  <div>
                    <span className="text-[10px] font-headline uppercase tracking-tighter text-on-surface/40">
                      Description
                    </span>
                    <p className="text-sm line-clamp-1 text-on-surface-variant">
                      {approval.description}
                    </p>
                  </div>
                  <div>
                    <span className="text-[10px] font-headline uppercase tracking-tighter text-on-surface/40">
                      Decision
                    </span>
                    <span className={`inline-flex text-[10px] font-bold px-2 py-0.5 rounded capitalize ${style}`}>
                      {approval.status}
                    </span>
                  </div>
                  <div>
                    <span className="text-[10px] font-headline uppercase tracking-tighter text-on-surface/40">
                      Resolved
                    </span>
                    <p className="text-xs font-mono text-on-surface-variant">
                      {approval.resolvedAt
                        ? new Date(approval.resolvedAt).toLocaleString()
                        : "—"}
                    </p>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </section>

      {/* Footer stats */}
      <footer className="mt-10 flex items-center justify-between text-on-surface/40 pb-8">
        <p className="text-sm">
          Showing <span className="text-on-surface font-bold">{displayedItems.length}</span> of{" "}
          <span className="text-on-surface font-bold">
            {activeTab === "pending" ? pending.length : resolved.length}
          </span>{" "}
          {activeTab} approvals
        </p>
      </footer>
      </div>
    </div>
  );
}
