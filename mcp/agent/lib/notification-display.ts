/**
 * Turn a notification row from the embedded MCP (`GET /api/v1/notifications`)
 * into what the /notifications page shows.
 *
 * The store row is `{ id, topic, severity, target, payload, created_at,
 * read_at, ... }`. The human-readable content lives in `payload`, whose shape
 * is owned by the publisher:
 *   - job-run-completed / job-run-failed  -> { job_name, summary, error, ... }
 *     (usecase/job_scheduler.py post-run hook)
 *   - coverage-cycle                      -> { title, body, ... }
 *   - cost-warning / context-warning      -> { title, body, ... }
 *     (published by the built-in hooks, hook-builtins/); shown as warnings
 *   - anything else                       -> free-form; we look for the common
 *     keys title / summary / body / message.
 *
 * Erasable-syntax TypeScript only, so scripts/test-notification-display.mjs can
 * import this file directly with Node's type stripping.
 */

export interface NotificationRow {
  id: string;
  topic?: string;
  severity?: string;
  payload?: unknown;
  // Legacy flat fields some callers still send; the store row itself carries
  // them inside `payload`.
  message?: string;
  body?: string;
  created_at?: string;
  read_at?: string | null;
  acked_at?: string | null;
}

export interface NotificationDisplay {
  title: string;
  description: string;
  /** In-app route the row opens on click, when the payload names a target. */
  href?: string;
  /** Coarse status used to pick the icon and colour. */
  tone: "success" | "failure" | "warning" | "neutral";
  read: boolean;
}

function asRecord(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {};
}

function str(v: unknown): string {
  return typeof v === "string" ? v.trim() : "";
}

/** Topics the built-in hooks publish (hook-builtins/notification-topics.ts). */
const WARNING_TOPICS = new Set(["cost-warning", "context-warning"]);

/** "simulation-complete" -> "Simulation complete". */
export function humanizeTopic(topic: string): string {
  const words = topic.replace(/[-_:]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Notification";
}

export function describeNotification(row: NotificationRow): NotificationDisplay {
  const topic = row.topic ?? "system";
  const payload = asRecord(row.payload);
  const read = Boolean(row.read_at ?? row.acked_at);

  const summary = str(payload.summary) || str(payload.body) || str(payload.message);
  const fallbackDescription = summary || str(row.message) || str(row.body);

  if (topic === "job-run-completed" || topic === "job-run-failed") {
    const jobName = str(payload.job_name);
    const failed = topic === "job-run-failed";
    const title = jobName
      ? `Job ${jobName} ${failed ? "failed" : "succeeded"}`
      : failed
      ? "Job run failed"
      : "Job run completed";
    return {
      title,
      description: fallbackDescription || str(payload.error),
      href: jobName ? `/jobs/${encodeURIComponent(jobName)}` : undefined,
      tone: failed ? "failure" : "success",
      read,
    };
  }

  const jobName = str(payload.job_name);
  return {
    title: str(payload.title) || humanizeTopic(topic),
    description: fallbackDescription,
    href: jobName ? `/jobs/${encodeURIComponent(jobName)}` : undefined,
    tone: WARNING_TOPICS.has(topic) ? "warning" : "neutral",
    read,
  };
}

// ── Date filter and paging for the /notifications page ──────────────────────

export type DateRange = "all" | "today" | "7d" | "30d";

export const DATE_RANGES: { value: DateRange; label: string }[] = [
  { value: "all", label: "All time" },
  { value: "today", label: "Today" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
];

/**
 * The `since` query value for a date range: an ISO-8601 UTC timestamp in the
 * same microsecond format the store writes to `created_at` (so the server's
 * string comparison is a time comparison), or undefined for "all". "today" is
 * the operator's local midnight.
 */
export function sinceForRange(range: DateRange, now: Date = new Date()): string | undefined {
  let start: Date;
  switch (range) {
    case "today":
      start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      break;
    case "7d":
      start = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      break;
    case "30d":
      start = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
      break;
    default:
      return undefined;
  }
  return start.toISOString().replace("Z", "000Z");
}

/**
 * Append a freshly loaded page to the rows already shown, dropping any row
 * whose id is already present (a notification published while paging shifts
 * the offsets, so the next page can repeat the last row).
 */
export function appendPage<T extends { id: string }>(existing: T[], incoming: T[]): T[] {
  const seen = new Set(existing.map((r) => r.id));
  return [...existing, ...incoming.filter((r) => !seen.has(r.id))];
}
