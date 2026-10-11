"use client";

/**
 * Jobs list — client-side filter + sort over the server-fetched
 * snapshot. The page (server component) renders the header, summary
 * bar, and error/empty states; we render the filterable card grid.
 *
 * Filter dimensions (chips):
 *
 *   All       — every non-removed job (default).
 *   Active    — effectiveState=ACTIVE: enabled and either non-one-shot
 *               or hasn't fired yet. These are the jobs that will fire
 *               on their next cron tick.
 *   Paused    — operator-disabled (state=PAUSED). Won't fire until
 *               re-enabled.
 *   Completed — run_once that has fired and has no future next_run_at.
 *   Never run — last_run_at is unset. Brand-new jobs land here.
 *   Failed    — most recent run had status=failure. Useful for "what
 *               did we break with the last manifest reload?"
 *
 * Sort dimensions:
 *
 *   Last run (default, descending)  — most recently fired at top
 *   Next run (ascending)            — closest upcoming fire at top
 *   Name (alphabetical)
 *   Created (descending)            — newest jobs at top
 *
 * State is local (useState) — the URL is not synced. Filter+sort is a
 * "view preference" not a sharable artifact; if/when operators want
 * deep-links of "show me my failed jobs", we'll add ?status=&sort=.
 */

import { useMemo, useState } from "react";
import Link from "next/link";

import type { Job, JobAction, JobSource, JobState } from "@/lib/api/jobs";
import { JobActions } from "./job-actions";

// ─── Glass style ─────────────────────────────────────────────────────────────
const glassStyle = {
  background: "var(--glass-bg)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

// ─── Filter / sort domain ────────────────────────────────────────────────────

type StatusFilter = "all" | "active" | "paused" | "completed" | "never" | "failed";
type SortKey = "last_run" | "next_run" | "name" | "created";

const STATUS_OPTIONS: { value: StatusFilter; label: string; icon: string }[] = [
  { value: "all", label: "All", icon: "list" },
  { value: "active", label: "Active", icon: "play_circle" },
  { value: "paused", label: "Paused", icon: "pause_circle" },
  { value: "completed", label: "Completed", icon: "check_circle" },
  { value: "never", label: "Never run", icon: "schedule" },
  { value: "failed", label: "Failed", icon: "error" },
];

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: "last_run", label: "Last run (newest first)" },
  { value: "next_run", label: "Next run (soonest first)" },
  { value: "name", label: "Name (A → Z)" },
  { value: "created", label: "Created (newest first)" },
];

// ─── Helpers ─────────────────────────────────────────────────────────────────

function effectiveState(job: Job): JobState {
  if (
    job.kind === "JOB_KIND_ONCE" &&
    job.state === "JOB_STATE_ACTIVE" &&
    job.last_run_at
  ) {
    const nextRun = job.next_run_at ? new Date(job.next_run_at) : null;
    if (!nextRun || isNaN(nextRun.getTime()) || nextRun.getTime() < Date.now()) {
      return "JOB_STATE_COMPLETED";
    }
  }
  return job.state;
}

function matchesStatus(job: Job, filter: StatusFilter): boolean {
  if (filter === "all") return true;
  const s = effectiveState(job);
  switch (filter) {
    case "active":
      return s === "JOB_STATE_ACTIVE";
    case "paused":
      return s === "JOB_STATE_PAUSED";
    case "completed":
      return s === "JOB_STATE_COMPLETED";
    case "never":
      return !job.last_run_at;
    case "failed":
      return job.last_status === "failure";
    default:
      return true;
  }
}

function compareJobs(a: Job, b: Job, key: SortKey): number {
  switch (key) {
    case "last_run": {
      // Sort newest first. Jobs with no last_run_at sort to the bottom.
      const at = a.last_run_at ? new Date(a.last_run_at).getTime() : 0;
      const bt = b.last_run_at ? new Date(b.last_run_at).getTime() : 0;
      if (at === 0 && bt === 0) return a.name.localeCompare(b.name);
      if (at === 0) return 1;
      if (bt === 0) return -1;
      return bt - at;
    }
    case "next_run": {
      // Soonest first. Jobs with no next_run_at sort to the bottom
      // (they have nothing upcoming).
      const at = a.next_run_at ? new Date(a.next_run_at).getTime() : Infinity;
      const bt = b.next_run_at ? new Date(b.next_run_at).getTime() : Infinity;
      if (at === Infinity && bt === Infinity) return a.name.localeCompare(b.name);
      return at - bt;
    }
    case "name":
      return a.name.localeCompare(b.name);
    case "created": {
      // Newest first. Jobs without a created_at fall through to name.
      const at = a.created_at ? new Date(a.created_at).getTime() : 0;
      const bt = b.created_at ? new Date(b.created_at).getTime() : 0;
      if (at === 0 && bt === 0) return a.name.localeCompare(b.name);
      return bt - at;
    }
    default:
      return 0;
  }
}

function humanSchedule(schedule: string, kind: string): string {
  if (kind === "JOB_KIND_INTERVAL") {
    const match = schedule.match(/^(\d+)([smhd])$/);
    if (match) {
      const value = match[1];
      const unitMap: Record<string, string> = { s: "second", m: "minute", h: "hour", d: "day" };
      const unit = unitMap[match[2]] ?? match[2];
      return `Every ${value} ${unit}${Number(value) !== 1 ? "s" : ""}`;
    }
    return `Every ${schedule}`;
  }
  if (kind === "JOB_KIND_ONCE") return "One-time";
  const parts = schedule.trim().split(/\s+/);
  if (parts.length === 5) {
    const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;
    if (minute.startsWith("*/") && hour === "*" && dayOfMonth === "*" && month === "*" && dayOfWeek === "*") {
      const interval = minute.slice(2);
      return `Every ${interval} minute${interval !== "1" ? "s" : ""}`;
    }
    if (dayOfMonth === "*" && month === "*" && dayOfWeek === "*" && !hour.includes("/") && !minute.includes("/")) {
      return `Daily at ${formatTime(hour, minute)}`;
    }
    if (dayOfMonth === "*" && month === "*" && dayOfWeek !== "*" && !hour.includes("/") && !minute.includes("/")) {
      const days = dayOfWeek.split(",").map(dayName).join(", ");
      return `${days} at ${formatTime(hour, minute)}`;
    }
  }
  return schedule;
}

function formatTime(hour: string, minute: string): string {
  const h = parseInt(hour, 10);
  const m = parseInt(minute, 10);
  if (isNaN(h)) return `${hour}:${minute.padStart(2, "0")}`;
  const period = h >= 12 ? "PM" : "AM";
  const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
  return `${h12}:${String(m).padStart(2, "0")} ${period}`;
}

const DAY_NAMES: Record<string, string> = {
  "0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed",
  "4": "Thu", "5": "Fri", "6": "Sat", "7": "Sun",
  SUN: "Sun", MON: "Mon", TUE: "Tue", WED: "Wed",
  THU: "Thu", FRI: "Fri", SAT: "Sat",
};

function dayName(d: string): string {
  return DAY_NAMES[d.toUpperCase()] ?? d;
}

function relativeTime(isoString: string | undefined): string {
  if (!isoString) return "—";
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return "—";
  const now = new Date();
  const diffMs = date.getTime() - now.getTime();
  const absDiffMs = Math.abs(diffMs);
  const isFuture = diffMs > 0;
  if (absDiffMs < 60_000) return isFuture ? "in less than a minute" : "just now";
  if (absDiffMs < 3_600_000) {
    const mins = Math.round(absDiffMs / 60_000);
    return isFuture ? `in ${mins} min` : `${mins} min ago`;
  }
  if (absDiffMs < 86_400_000) {
    const hrs = Math.round(absDiffMs / 3_600_000);
    return isFuture ? `in ${hrs}h` : `${hrs}h ago`;
  }
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function actionLabel(
  action: JobAction | undefined,
  agentNameMap: Record<string, string>,
): string {
  if (!action) return "—";
  const t = action.type ?? "";
  if (t === "chat") {
    const aid = action.agent_id ?? "";
    return (aid && agentNameMap[aid]) || aid || "chat";
  }
  if (t === "tool_call") {
    return action.name ?? "tool_call";
  }
  if (t === "log") {
    const fmt = (action as { format?: string; log_type?: string }).format
      ?? (action as { log_type?: string }).log_type;
    return fmt ? `log:${fmt}` : "log";
  }
  return t || "—";
}

function buildDuplicateQuery(job: Job): string {
  const params = new URLSearchParams();
  params.set("name", `${job.name} (copy)`);
  params.set("schedule", job.schedule);
  if (job.kind === "JOB_KIND_ONCE") params.set("kind", "once");
  else params.set("kind", "weekly");
  if (job.action?.agent_id) params.set("agent_id", job.action.agent_id);
  if (job.action?.message) params.set("input", job.action.message);
  return params.toString();
}

function stateLabel(state: JobState): string {
  switch (state) {
    case "JOB_STATE_ACTIVE":
      return "Active";
    case "JOB_STATE_PAUSED":
      return "Paused";
    case "JOB_STATE_COMPLETED":
      return "Completed";
    default:
      return "Unknown";
  }
}

function stateBadge(state: JobState): string {
  switch (state) {
    case "JOB_STATE_ACTIVE":
      return "bg-secondary/15 text-secondary border-secondary/25";
    case "JOB_STATE_PAUSED":
      return "bg-yellow-500/15 text-yellow-400 border-yellow-500/25";
    case "JOB_STATE_COMPLETED":
      return "bg-outline/15 text-outline border-outline/25";
    default:
      return "bg-outline/15 text-outline border-outline/25";
  }
}

// ─── Component ───────────────────────────────────────────────────────────────

export interface JobsListClientProps {
  jobs: Job[];
  agentNameMap: Record<string, string>;
}

export function JobsListClient({ jobs, agentNameMap }: JobsListClientProps) {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("last_run");

  const counts = useMemo(() => {
    const c: Record<StatusFilter, number> = {
      all: jobs.length,
      active: 0,
      paused: 0,
      completed: 0,
      never: 0,
      failed: 0,
    };
    for (const j of jobs) {
      if (matchesStatus(j, "active")) c.active++;
      if (matchesStatus(j, "paused")) c.paused++;
      if (matchesStatus(j, "completed")) c.completed++;
      if (matchesStatus(j, "never")) c.never++;
      if (matchesStatus(j, "failed")) c.failed++;
    }
    return c;
  }, [jobs]);

  const visible = useMemo(() => {
    const filtered = jobs.filter((j) => matchesStatus(j, statusFilter));
    return [...filtered].sort((a, b) => compareJobs(a, b, sortKey));
  }, [jobs, statusFilter, sortKey]);

  return (
    <>
      {/* Filter + sort row */}
      <div className="flex flex-wrap items-center gap-3 mb-6">
        <div className="flex flex-wrap gap-2">
          {STATUS_OPTIONS.map((opt) => {
            const isActive = statusFilter === opt.value;
            const count = counts[opt.value];
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => setStatusFilter(opt.value)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-label text-[10px] uppercase tracking-wider transition-all ${
                  isActive
                    ? "bg-secondary-container/30 border border-secondary/40 text-secondary"
                    : "bg-white/5 border border-white/10 text-on-surface-variant hover:bg-white/10"
                }`}
              >
                <span className="material-symbols-outlined text-sm">
                  {opt.icon}
                </span>
                {opt.label}
                <span
                  className={`text-[9px] font-mono ${
                    isActive ? "text-primary/70" : "text-on-surface-variant/50"
                  }`}
                >
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        <div className="ml-auto flex items-center gap-2">
          <label
            htmlFor="jobs-sort"
            className="text-[10px] uppercase tracking-widest text-on-surface-variant/60"
          >
            Sort:
          </label>
          <select
            id="jobs-sort"
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            className="bg-surface-container-lowest text-xs text-on-surface rounded-lg px-3 py-1.5 border border-white/10 focus:border-primary/40 outline-none cursor-pointer"
          >
            {SORT_OPTIONS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Card grid */}
      {visible.length === 0 ? (
        <div
          className="rounded-2xl p-12 flex flex-col items-center gap-3 text-center"
          style={glassStyle}
        >
          <span className="material-symbols-outlined text-4xl text-on-surface-variant">
            filter_alt_off
          </span>
          <p className="text-base font-medium">No jobs match this filter</p>
          <p className="max-w-xl text-sm text-on-surface-variant">
            Try a different status filter, or click{" "}
            <button
              type="button"
              onClick={() => setStatusFilter("all")}
              className="text-primary hover:underline"
            >
              All
            </button>{" "}
            to see every job.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {visible.map((job) => (
            <JobCard key={job.id} job={job} agentNameMap={agentNameMap} />
          ))}
        </div>
      )}
    </>
  );
}

// ─── Card (moved here from page.tsx so the client component owns it) ────────

function JobCard({
  job,
  agentNameMap,
}: {
  job: Job;
  agentNameMap: Record<string, string>;
}) {
  const agentName = actionLabel(job.action, agentNameMap);
  const scheduleText = humanSchedule(job.schedule, job.kind);
  const displayState = effectiveState(job);
  const showNextRun = displayState !== "JOB_STATE_COMPLETED";
  const nextRun = showNextRun ? relativeTime(job.next_run_at) : "—";
  const lastRun = relativeTime(job.last_run_at);

  return (
    <div className="relative">
      <Link
        href={`/jobs/${encodeURIComponent(job.id)}`}
        className="block p-5 rounded-xl flex items-center justify-between transition-all hover:shadow-[0_0_20px_rgba(25,99,179,0.1)] cursor-pointer"
        style={glassStyle}
      >
        <div className="flex items-center gap-5 flex-1 min-w-0">
          <div className="w-12 h-12 rounded-lg bg-surface-container flex items-center justify-center relative shrink-0">
            <span className="material-symbols-outlined text-primary">
              schedule
            </span>
            {displayState === "JOB_STATE_ACTIVE" && (
              <div className="absolute -top-1 -right-1 w-3 h-3 bg-secondary rounded-full shadow-[0_0_8px_#7bdc7b]" />
            )}
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-3 flex-wrap">
              <h3 className="font-headline font-bold text-lg text-on-surface truncate">
                {job.name}
              </h3>
              <span
                className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-tighter border ${stateBadge(displayState)}`}
              >
                {stateLabel(displayState)}
              </span>
              {job.source === "runtime" && (
                <SourceBadge source="runtime" />
              )}
            </div>
            <p className="text-sm text-on-surface-variant mt-0.5 truncate">
              {scheduleText}
              {job.timezone && job.timezone !== "UTC" ? ` (${job.timezone})` : ""}
            </p>
          </div>
        </div>

        <div className="hidden md:flex items-center gap-8 text-sm text-on-surface-variant flex-[1.5] justify-center">
          <div className="flex flex-col items-center">
            <span className="text-[10px] uppercase text-outline">Action</span>
            <span
              className="font-mono text-xs text-on-surface truncate max-w-[180px]"
              title={agentName}
            >
              {agentName}
            </span>
          </div>

          <div className="flex flex-col items-center">
            <span className="text-[10px] uppercase text-outline">Next Run</span>
            <span className="font-medium text-on-surface">{nextRun}</span>
          </div>

          <div className="flex flex-col items-center">
            <span className="text-[10px] uppercase text-outline">Last Run</span>
            <span className="font-medium text-on-surface">{lastRun}</span>
          </div>

          <div className="flex flex-col items-center">
            <span className="text-[10px] uppercase text-outline">Runs</span>
            <span className="font-medium text-on-surface">
              {job.run_count ?? "—"}
            </span>
          </div>
        </div>

        <div className="shrink-0 ml-4 w-9" />
      </Link>

      <div className="absolute right-5 top-1/2 -translate-y-1/2 z-50">
        <JobActions
          jobId={job.id}
          jobName={job.name}
          isPaused={job.state === "JOB_STATE_PAUSED"}
          duplicateQuery={buildDuplicateQuery(job)}
          // Pass the full Job object so JobActions can render
          // "Export definition (.json)" from the list view too.
          // We deliberately DO NOT pass `runs` here — listing the
          // runs for every job would N-round-trip the page; the
          // runs export stays detail-page-only by design.
          job={job}
        />
      </div>
    </div>
  );
}

function SourceBadge({ source }: { source: JobSource }) {
  if (source !== "runtime") return null;
  return (
    <span
      className="px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-tighter border bg-tertiary/15 text-tertiary border-tertiary/25"
      title="Created at runtime via the Create Job form. Survives boot reconciliation."
    >
      Runtime
    </span>
  );
}
