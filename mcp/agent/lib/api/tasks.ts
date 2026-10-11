/**
 * Task registry client
 *
 * Wraps the agent's `/api/agent/tasks` proxy (which forwards to
 * the MCP's `/api/v1/tasks`). Used by:
 *   - /tasks page (list + abort)
 *   - chat-header live drawer (active tasks)
 *   - /tasks slash command in chat
 */

export type TaskStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "aborted";

export const TASK_TERMINAL_STATUS: ReadonlySet<TaskStatus> = new Set([
  "succeeded",
  "failed",
  "aborted",
]);

export interface Task {
  id: string;
  /** What kind of work this task does. Common kinds:
   *    'scenario_worker'   — xlog scenario emulation worker
   *    'caldera_operation' — caldera red-team op
   *    'xsiam_xql'         — long-running XQL detection query
   *    'compaction'        — budget-edge compaction
   *    'hook_command'      — subprocess hook
   *  Free-form; the UI groups by kind for visual scanning. */
  kind: string;
  status: TaskStatus;
  title: string;
  /** Chat session that spawned this task (if any). NULL for
   *  cron-fired or system-spawned tasks. */
  parent_session_id: string | null;
  /** 0.0..1.0. Workers update via PATCH /tasks/{id}/progress. */
  progress: number;
  /** Operator-friendly progress label, e.g. "step 3 of 10:
   *  generating IOCs". */
  progress_label: string | null;
  /** Final result on success or error message on failure/abort.
   *  NULL while running. */
  output: string | null;
  /** Free-form per-kind metadata. Examples:
   *    scenario_worker → { worker_id, format, destination }
   *    caldera_operation → { operation_id, agent_count }
   *    compaction → { messages_summarized, summary_chars } */
  meta: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface TaskListResponse {
  tasks: Task[];
  count: number;
}

/** Fetch a paginated list of tasks. */
export async function listTasks(params: {
  status?: TaskStatus;
  kind?: string;
  session?: string;
  active_only?: boolean;
  limit?: number;
  offset?: number;
} = {}): Promise<TaskListResponse> {
  const sp = new URLSearchParams();
  if (params.status) sp.set("status", params.status);
  if (params.kind) sp.set("kind", params.kind);
  if (params.session) sp.set("session", params.session);
  if (params.active_only) sp.set("active_only", "1");
  if (params.limit != null) sp.set("limit", String(params.limit));
  if (params.offset != null) sp.set("offset", String(params.offset));
  const qs = sp.toString();
  const r = await fetch(`/api/agent/tasks${qs ? `?${qs}` : ""}`, {
    cache: "no-store",
  });
  if (!r.ok) {
    throw new Error(`tasks list ${r.status}`);
  }
  return (await r.json()) as TaskListResponse;
}

/** Fetch one task by id. */
export async function getTask(id: string): Promise<Task | null> {
  const r = await fetch(`/api/agent/tasks/${encodeURIComponent(id)}`, {
    cache: "no-store",
  });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`task get ${r.status}`);
  const data = (await r.json()) as { task: Task };
  return data.task;
}

/** Abort a running task. The worker must poll status to actually stop. */
export async function abortTask(
  id: string,
  reason?: string,
): Promise<Task> {
  const r = await fetch(
    `/api/agent/tasks/${encodeURIComponent(id)}/abort`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(reason ? { reason } : {}),
    },
  );
  if (!r.ok) throw new Error(`task abort ${r.status}`);
  const data = (await r.json()) as { task: Task };
  return data.task;
}

/** Format progress as "45%" or "—" when not started. */
export function formatProgress(t: Task): string {
  if (t.status === "pending") return "—";
  if (t.status === "succeeded") return "100%";
  return `${Math.round(t.progress * 100)}%`;
}

/** Human-readable elapsed string. */
export function formatElapsed(t: Task): string {
  const start = Date.parse(t.created_at);
  const end = t.completed_at
    ? Date.parse(t.completed_at)
    : Date.now();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "—";
  const ms = Math.max(0, end - start);
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m`;
  return `${(ms / 3_600_000).toFixed(1)}h`;
}

/** Tailwind / token-friendly tone class for a task status. */
export function statusTone(s: TaskStatus): {
  bg: string;
  fg: string;
  icon: string;
  label: string;
} {
  switch (s) {
    case "pending":
      return {
        bg: "bg-white/5",
        fg: "text-on-surface-variant",
        icon: "schedule",
        label: "Pending",
      };
    case "running":
      return {
        bg: "bg-primary/15",
        fg: "text-primary",
        icon: "play_circle",
        label: "Running",
      };
    case "succeeded":
      return {
        bg: "bg-secondary/15",
        fg: "text-secondary",
        icon: "check_circle",
        label: "Succeeded",
      };
    case "failed":
      return {
        bg: "bg-error/15",
        fg: "text-error",
        icon: "error",
        label: "Failed",
      };
    case "aborted":
      return {
        bg: "bg-tertiary/15",
        fg: "text-tertiary",
        icon: "cancel",
        label: "Aborted",
      };
  }
}
