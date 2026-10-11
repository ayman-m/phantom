/**
 * Worker-rate API client.
 *
 * xlog admits generation workers against ceilings (per-worker sustained rate,
 * declared-burst allowance, aggregate rate, worker population). This reads the
 * live consumption so an operator can see what is using the budget instead of
 * only finding out when a worker is refused.
 */

import { apiRequest } from "./client";

/**
 * One live worker.
 *
 * `events_per_second` is the ADMITTED rate — count/interval as declared at
 * creation — not measured throughput. It is what the ceilings are enforced
 * against, which is why the panel shows it, but it is not a claim about how
 * many events actually reached the destination.
 *
 * It is `null` when the rate is unbounded (a non-positive interval, or a
 * sender class that declares no rate). xlog sends null rather than `Infinity`
 * because the latter is not valid JSON and would break parsing of the whole
 * response. `events_per_second_unbounded` disambiguates null-as-unbounded from
 * null-as-missing.
 */
export interface WorkerRate {
  worker: string;
  status: string;
  events_per_second: number | null;
  events_per_second_unbounded: boolean;
  burst: boolean;
}

export interface WorkerRateCeilings {
  worker_eps: number;
  burst_eps: number;
  burst_events: number;
  concurrent_bursts: number;
  total_eps: number;
  population: number;
}

export interface WorkerRatesSnapshot {
  workers: WorkerRate[];
  sustained_events_per_second: number | null;
  sustained_events_per_second_unbounded: boolean;
  concurrent_bursts: number;
  ceilings: WorkerRateCeilings;
  /**
   * The xlog process this snapshot came from. xlog runs several uvicorn
   * workers when TLS is off, and the registry is per-process — so a snapshot
   * can legitimately describe only some of the live workers.
   */
  pid?: number;
}

/** Why a fetch failed, so the panel can say something specific. */
export type WorkerRatesError = "unreachable" | "auth_error" | "unknown";

export interface WorkerRatesResult {
  snapshot: WorkerRatesSnapshot | null;
  error: WorkerRatesError | null;
}

export async function listWorkerRates(): Promise<WorkerRatesResult> {
  const result = await apiRequest<
    WorkerRatesSnapshot & { error?: string }
  >("/api/v1/worker-rates");

  // The MCP signals BOTH failure kinds with HTTP 502 and a typed body, so the
  // discriminator lives on the FAILURE branch, not the success one. Returning
  // "unreachable" for every !ok made the auth_error and unknown cases dead
  // code — and auth_error is the one most likely to fire, since xlog began
  // requiring a bearer token. The operator would be told "xlog did not
  // respond", go inspect a container that is perfectly healthy, and never be
  // pointed at the token mismatch that actually caused it.
  //
  // parseError() preserves a `{error: "..."}` body into ApiError.code, so the
  // kind survives on failures.
  if (!result.ok) {
    const code = result.error?.code ?? "";
    if (code === "auth_error") return { snapshot: null, error: "auth_error" };
    if (code === "unreachable") return { snapshot: null, error: "unreachable" };
    // A 401 from middleware means the operator's session lapsed, which is an
    // auth problem from their point of view even though xlog is fine.
    if (code === "unauthenticated" || code === "401") {
      return { snapshot: null, error: "auth_error" };
    }
    return { snapshot: null, error: code ? "unknown" : "unreachable" };
  }
  const maybeErr = (result.data as { error?: string })?.error;
  if (maybeErr === "auth_error") return { snapshot: null, error: "auth_error" };
  if (maybeErr === "unreachable") return { snapshot: null, error: "unreachable" };
  if (maybeErr) return { snapshot: null, error: "unknown" };

  return { snapshot: result.data, error: null };
}

export async function stopWorker(worker: string): Promise<boolean> {
  const result = await apiRequest(
    `/api/v1/worker-rates/${encodeURIComponent(worker)}/stop`,
    { method: "POST" },
  );
  return result.ok;
}

/** Format a rate for display, keeping "unbounded" distinct from "0". */
export function formatRate(
  eps: number | null,
  unbounded: boolean,
): string {
  if (unbounded) return "unbounded";
  if (eps === null) return "—";
  if (eps === 0) return "0";
  return eps < 0.01 ? "<0.01" : eps.toFixed(2);
}

/** Events/day implied by a sustained rate — the figure that makes a rate real. */
export function perDay(eps: number | null, unbounded: boolean): string | null {
  if (unbounded || eps === null || eps <= 0) return null;
  return Math.round(eps * 86400).toLocaleString();
}
