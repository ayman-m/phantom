"use client";

/**
 * /tasks page
 *
 * Operator surface for the durable task registry. Lists every
 * task (active + recent terminal) with status, progress, kind,
 * elapsed time, and a one-click Abort for running tasks.
 *
 * Auto-refreshes active tasks every 3s so progress stays live
 * without forcing the operator to hit refresh. Terminal tasks
 * stick around so the operator can review what happened.
 *
 * Two sources, deliberately not merged into one store:
 *   - the task registry (/api/agent/tasks) for work the platform tracks as
 *     tasks, and
 *   - the xlog data workers (/api/agent/workers -> xlog listWorkers), the
 *     synthetic-log generators the agent starts with xlog.create_data_worker.
 *     xlog owns those, so they are read from xlog and shown in their own
 *     section, with a Stop button that goes through the worker-rates API.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { confirmAction } from "@/lib/stores/confirm";
import Link from "next/link";
import { cn } from "@/lib/utils";
import {
  abortTask,
  formatElapsed,
  formatProgress,
  listTasks,
  statusTone,
  TASK_TERMINAL_STATUS,
  type Task,
  type TaskStatus,
} from "@/lib/api/tasks";
import {
  isWorkerRunning,
  listDataWorkers,
  type DataWorker,
} from "@/lib/api/workers";
import { stopWorker } from "@/lib/api/worker-rates";

type Filter = "all" | "active" | "succeeded" | "failed" | "aborted";

const glassCard = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

const REFRESH_MS = 3000;

export default function TasksPage() {
  const [filter, setFilter] = useState<Filter>("all");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [workers, setWorkers] = useState<DataWorker[]>([]);
  const [workersError, setWorkersError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchTasks = useCallback(async () => {
    setError(null);
    try {
      const params: Parameters<typeof listTasks>[0] = { limit: 200 };
      if (filter === "active") params.active_only = true;
      else if (filter !== "all") {
        params.status = filter as TaskStatus;
      }
      const [data, workerResult] = await Promise.all([
        listTasks(params),
        listDataWorkers(),
      ]);
      setTasks(data.tasks);
      setWorkers(workerResult.workers);
      setWorkersError(workerResult.error);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    setLoading(true);
    void fetchTasks();
  }, [fetchTasks]);

  // Auto-refresh: only poll when there are active tasks (otherwise
  // the data is stable and we'd be wasting cycles).
  useEffect(() => {
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    const hasActive =
      tasks.some((t) => !TASK_TERMINAL_STATUS.has(t.status)) ||
      workers.some(isWorkerRunning);
    if (!hasActive) return;
    refreshTimerRef.current = setTimeout(() => {
      void fetchTasks();
    }, REFRESH_MS);
    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    };
  }, [tasks, workers, fetchTasks]);

  const handleStopWorker = useCallback(
    async (worker: string) => {
      const accepted = await confirmAction({
        title: `Stop data worker ${worker.slice(0, 8)}?`,
        message:
          "An explicit stop is permanent: the worker is not restored after a restart.",
        confirmLabel: "Stop worker",
        tone: "danger",
      });
      if (!accepted) return;
      const ok = await stopWorker(worker);
      if (!ok) setError(`Could not stop worker ${worker.slice(0, 8)}.`);
      void fetchTasks();
    },
    [fetchTasks],
  );

  const handleAbort = useCallback(
    async (id: string, title: string) => {
      const accepted = await confirmAction({
        title: `Abort task "${title}"?`,
        message: "The worker will stop at its next checkpoint.",
        confirmLabel: "Abort task",
        tone: "danger",
      });
      if (!accepted) return;
      try {
        await abortTask(id, "operator-requested");
        void fetchTasks();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [fetchTasks],
  );

  // Group by kind for visual scanning.
  const grouped = (() => {
    const map = new Map<string, Task[]>();
    for (const t of tasks) {
      const list = map.get(t.kind) ?? [];
      list.push(t);
      map.set(t.kind, list);
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  })();

  // Workers are not task-registry rows, so only the "all" and "active" chips
  // include them (a worker has no succeeded/failed/aborted state).
  const shownWorkers =
    filter === "all"
      ? workers
      : filter === "active"
        ? workers.filter(isWorkerRunning)
        : [];
  const activeCount =
    tasks.filter((t) => !TASK_TERMINAL_STATUS.has(t.status)).length +
    workers.filter(isWorkerRunning).length;

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-8 space-y-6">
        {/* Header — matches /skills layout pattern */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <span className="material-symbols-outlined text-2xl text-primary">
                pending_actions
              </span>
              <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
                Tasks
              </h1>
              {activeCount > 0 && (
                <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-primary/15 text-primary">
                  {activeCount} active
                </span>
              )}
            </div>
            <p className="text-sm text-on-surface-variant ml-9">
              Long-running work the agent has spawned, including the log
              generators it started — auto-refreshes every {REFRESH_MS / 1000}s while anything is running.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void fetchTasks()}
            disabled={loading}
            className="px-4 py-2 rounded-xl text-xs font-medium text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-50"
            style={glassCard}
          >
            <span className="material-symbols-outlined text-base align-middle mr-1">
              refresh
            </span>
            Refresh
          </button>
        </div>

        {/* Filter chips */}
        <div className="flex flex-wrap items-center gap-2">
          {(
            [
              { key: "all" as const, label: "All" },
              { key: "active" as const, label: "Active" },
              { key: "succeeded" as const, label: "Succeeded" },
              { key: "failed" as const, label: "Failed" },
              { key: "aborted" as const, label: "Aborted" },
            ] as const
          ).map((opt) => (
            <button
              key={opt.key}
              type="button"
              onClick={() => setFilter(opt.key)}
              className={cn(
                "px-3 py-1 rounded-full text-[11px] transition-colors",
                filter === opt.key
                  ? "bg-primary/15 text-primary border border-primary/30"
                  : "bg-white/5 text-on-surface-variant hover:text-on-surface border border-transparent",
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {error && (
          <div className="rounded-xl border border-error/30 bg-error/10 p-3 text-xs text-error">
            {error}
          </div>
        )}

        {workersError && (
          <div className="rounded-xl border border-error/30 bg-error/10 p-3 text-xs text-error">
            Could not read the log generators from xlog: {workersError}
          </div>
        )}

        {loading && tasks.length === 0 && shownWorkers.length === 0 ? (
          <div className="text-center py-16 text-sm text-on-surface-variant/60">
            Loading tasks…
          </div>
        ) : tasks.length === 0 && shownWorkers.length === 0 ? (
          <div
            className="text-center py-12 rounded-2xl"
            style={glassCard}
          >
            <span className="material-symbols-outlined text-4xl text-on-surface-variant/40 mb-2 inline-block">
              inbox
            </span>
            <p className="text-sm font-medium text-on-surface mb-1">
              {filter === "all" ? "No tasks yet." : `No ${filter} tasks.`}
            </p>
            <p className="text-xs text-on-surface-variant/60 max-w-md mx-auto">
              Tasks appear here when the agent or operator spawns
              long-running work — log generators, scenario emulation,
              CALDERA operations, etc.
            </p>
          </div>
        ) : (
          <div className="space-y-5">
            {shownWorkers.length > 0 && (
              <div className="space-y-2">
                <h3 className="text-xs font-label uppercase tracking-widest text-on-surface-variant/60">
                  Log generators <span className="font-mono">·</span>{" "}
                  <span className="font-mono">{shownWorkers.length}</span>
                </h3>
                <div className="grid gap-2">
                  {shownWorkers.map((w) => (
                    <WorkerRow
                      key={w.worker}
                      worker={w}
                      onStop={handleStopWorker}
                    />
                  ))}
                </div>
              </div>
            )}
            {grouped.map(([kind, kindTasks]) => (
              <div key={kind} className="space-y-2">
                <h3 className="text-xs font-label uppercase tracking-widest text-on-surface-variant/60">
                  {kind} <span className="font-mono">·</span>{" "}
                  <span className="font-mono">{kindTasks.length}</span>
                </h3>
                <div className="grid gap-2">
                  {kindTasks.map((t) => (
                    <TaskRow
                      key={t.id}
                      task={t}
                      onAbort={handleAbort}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Data worker row ────────────────────────────────────────────────

function WorkerRow({
  worker,
  onStop,
}: {
  worker: DataWorker;
  onStop: (worker: string) => void;
}) {
  const running = isWorkerRunning(worker);
  return (
    <div
      className="rounded-2xl p-4 flex items-start gap-3"
      style={glassCard}
    >
      <span
        className={cn(
          "material-symbols-outlined text-base shrink-0 mt-0.5",
          running ? "text-primary" : "text-on-surface-variant/60",
        )}
      >
        {running ? "sync" : "stop_circle"}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1 flex-wrap">
          <span className="font-mono text-sm font-semibold text-on-surface truncate">
            {worker.type || "worker"} to {worker.destination || "—"}
          </span>
          <span
            className={cn(
              "text-[10px] font-mono px-1.5 py-0.5 rounded uppercase tracking-wider",
              running
                ? "bg-primary/15 text-primary"
                : "bg-white/5 text-on-surface-variant",
            )}
          >
            {worker.status || "unknown"}
          </span>
        </div>
        <p className="text-xs text-on-surface-variant">
          {worker.count} events every {worker.interval}s
          {worker.created_at ? ` · started ${worker.created_at}` : ""}
        </p>
        <p className="text-[10px] font-mono text-on-surface-variant/60 mt-0.5">
          worker {worker.worker}
        </p>
      </div>
      {running && (
        <button
          type="button"
          onClick={() => onStop(worker.worker)}
          aria-label="Stop worker"
          className="p-1.5 rounded hover:bg-error/10 text-on-surface-variant hover:text-error transition-colors shrink-0"
          title="Stop"
        >
          <span className="material-symbols-outlined text-base">cancel</span>
        </button>
      )}
    </div>
  );
}

// ─── Row ────────────────────────────────────────────────────────────

function TaskRow({
  task,
  onAbort,
}: {
  task: Task;
  onAbort: (id: string, title: string) => void;
}) {
  const tone = statusTone(task.status);
  const isActive = !TASK_TERMINAL_STATUS.has(task.status);
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className="rounded-2xl p-4 flex flex-col gap-2"
      style={glassCard}
    >
      <div className="flex items-start gap-3">
        <span
          className={cn(
            "material-symbols-outlined text-base shrink-0 mt-0.5",
            tone.fg,
          )}
        >
          {tone.icon}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className="font-mono text-sm font-semibold text-on-surface truncate">
              {task.title}
            </span>
            <span
              className={cn(
                "text-[10px] font-mono px-1.5 py-0.5 rounded uppercase tracking-wider",
                tone.bg,
                tone.fg,
              )}
            >
              {tone.label}
            </span>
            {task.parent_session_id && (
              <Link
                href={`/?session=${task.parent_session_id}`}
                className="text-[10px] font-mono text-on-surface-variant/60 hover:text-on-surface transition-colors"
                title="Open the chat session that spawned this task"
              >
                session {task.parent_session_id.slice(0, 8)}
              </Link>
            )}
          </div>
          {task.progress_label && (
            <p className="text-xs text-on-surface-variant mb-1.5">
              {task.progress_label}
            </p>
          )}
          {/* Progress bar — shown when active or reached 1.0 */}
          {(isActive || task.status === "succeeded") && (
            <div
              className="w-full h-1.5 rounded-full overflow-hidden"
              style={{ background: "rgba(140, 145, 157, 0.15)" }}
              aria-hidden="true"
            >
              <div
                className={cn(
                  "h-full transition-[width] duration-500 rounded-full",
                  tone.fg.replace("text-", "bg-"),
                )}
                style={{
                  width: `${Math.round(task.progress * 100)}%`,
                  background:
                    task.status === "running"
                      ? "var(--m3-primary)"
                      : task.status === "succeeded"
                        ? "var(--m3-secondary)"
                        : undefined,
                }}
              />
            </div>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0 text-[11px] font-mono text-on-surface-variant/70">
          <span className="text-right" title="Progress">
            {formatProgress(task)}
          </span>
          <span className="w-12 text-right" title="Elapsed">
            {formatElapsed(task)}
          </span>
          {isActive && (
            <button
              type="button"
              onClick={() => onAbort(task.id, task.title)}
              aria-label="Abort task"
              className="p-1.5 rounded hover:bg-error/10 text-on-surface-variant hover:text-error transition-colors"
              title="Abort"
            >
              <span className="material-symbols-outlined text-base">
                cancel
              </span>
            </button>
          )}
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            className="p-1.5 rounded hover:bg-white/5 text-on-surface-variant/70 hover:text-on-surface transition-colors"
            title={expanded ? "Collapse" : "Expand"}
          >
            <span className="material-symbols-outlined text-base">
              {expanded ? "expand_less" : "expand_more"}
            </span>
          </button>
        </div>
      </div>

      {expanded && (
        <div className="mt-2 pt-2 border-t border-white/5 grid grid-cols-2 gap-3 text-[11px]">
          <Detail label="Created" value={task.created_at} mono />
          <Detail
            label="Updated"
            value={
              task.updated_at !== task.created_at
                ? task.updated_at
                : "—"
            }
            mono
          />
          {task.completed_at && (
            <Detail label="Completed" value={task.completed_at} mono />
          )}
          <Detail label="Task id" value={task.id} mono />
          {task.output && (
            <div className="col-span-2">
              <p className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant/60 mb-1">
                Output
              </p>
              <pre className="font-mono text-[11px] text-on-surface-variant whitespace-pre-wrap break-all max-h-40 overflow-y-auto rounded-md p-2 bg-surface-container-lowest/50">
                {task.output}
              </pre>
            </div>
          )}
          {Object.keys(task.meta).length > 0 && (
            <div className="col-span-2">
              <p className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant/60 mb-1">
                Metadata
              </p>
              <pre className="font-mono text-[10px] text-on-surface-variant whitespace-pre-wrap break-all max-h-40 overflow-y-auto rounded-md p-2 bg-surface-container-lowest/50">
                {JSON.stringify(task.meta, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Detail({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <p className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant/60">
        {label}
      </p>
      <p
        className={cn(
          "text-on-surface-variant",
          mono && "font-mono text-[11px]",
        )}
      >
        {value || "—"}
      </p>
    </div>
  );
}
