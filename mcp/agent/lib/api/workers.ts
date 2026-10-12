/**
 * Data-worker list client.
 *
 * Wraps `/api/agent/workers` (-> MCP `/api/v1/workers` -> xlog `listWorkers`),
 * the same list the agent's `xlog.list_workers` tool returns. The /tasks page
 * shows it beside the task registry: a data worker is owned and run by xlog,
 * not by the task registry, so it is read from xlog rather than copied into a
 * second store.
 */

export interface DataWorker {
  worker: string;
  /** Wire format, e.g. CEF, SYSLOG, JSON. */
  type: string;
  /** xlog reports "Running" or "Stopped" (case varies). */
  status: string;
  count: string;
  interval: string;
  /** Credentials and query strings are already stripped server-side. */
  destination: string;
  created_at: string;
}

export interface DataWorkersResult {
  workers: DataWorker[];
  /** Set when xlog could not be asked; `workers` is then empty. */
  error: string | null;
}

export function isWorkerRunning(w: DataWorker): boolean {
  return w.status.toLowerCase() === "running";
}

export async function listDataWorkers(): Promise<DataWorkersResult> {
  try {
    const r = await fetch("/api/agent/workers", { cache: "no-store" });
    if (!r.ok) {
      let detail = "";
      try {
        const body = (await r.json()) as { detail?: string; error?: string };
        detail = body.detail || body.error || "";
      } catch {
        // Non-JSON body; the status alone is reported below.
      }
      return {
        workers: [],
        error: detail || `workers list ${r.status}`,
      };
    }
    const data = (await r.json()) as { workers?: DataWorker[] };
    return { workers: data.workers ?? [], error: null };
  } catch (err) {
    return {
      workers: [],
      error: err instanceof Error ? err.message : String(err),
    };
  }
}
