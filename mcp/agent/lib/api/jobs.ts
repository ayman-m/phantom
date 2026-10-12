import { apiRequest, listRequest } from "./client";
import type { ApiRequestOptions, ApiResult } from "./client";

// ─── Types ────────────────────────────────────────────────────────────────────

/** Proto-style Job kind enum values (the UI-facing form). */
export type JobKind = "JOB_KIND_UNSPECIFIED" | "JOB_KIND_CRON" | "JOB_KIND_INTERVAL" | "JOB_KIND_ONCE";

/** Proto-style Job state enum values (the UI-facing form). */
export type JobState = "JOB_STATE_UNSPECIFIED" | "JOB_STATE_ACTIVE" | "JOB_STATE_PAUSED" | "JOB_STATE_COMPLETED";

/** Action performed when a job fires. */
/** Jobs have exactly two action types.
 *
 *   - "prompt" — natural-language message that runs through the same
 *     chat pipeline as interactive chat (personality applied, memory
 *     tools available, audit + session persistence). Body: {type,
 *     message}.
 *   - "tool_call" — direct MCP tool invocation. No LLM. Body: {type,
 *     name, args}.
 *
 * Legacy `chat` is accepted as an alias for `prompt` on dispatch
 * (for in-flight rows during the migration window or older API
 * clients). Legacy `log` is removed; the boot migration in the
 * scheduler converts existing log-type rows to tool_call(
 * phantom_create_data_worker, …) shape. */
export type JobActionType = "prompt" | "tool_call";

export interface JobAction {
  agent_id?: string;
  /** type=prompt action's message body. */
  message?: string;
  /** type=tool_call action's underlying tool name. */
  name?: string;
  /** type=tool_call action's args bag. */
  args?: Record<string, unknown>;
  /** Action discriminator. */
  type?: string;
  delivery_context?: Record<string, unknown>;
  /** Anything else the action object carried; preserved for the detail page. */
  [extra: string]: unknown;
}

/**
 * Provenance of a job — declared in the bundle manifest at boot, or
 * created by an operator at runtime via POST /api/v1/jobs. Affects:
 *   - whether DELETE hard-deletes (runtime) or just marks removed=1
 *     (manifest, since the manifest will recreate it next boot)
 *   - whether boot reconciliation touches it (manifest only)
 *   - what badge the UI shows
 */
export type JobSource = "manifest" | "runtime";

/** Job entity as the UI sees it. Wire shape from MCP is normalized via
 *  `normalizeJob()` below — the MCP returns `{name, cron, enabled,
 *  next_due_at, last_fired_at, …}` and the UI consumes proto-style
 *  field names. The id is set to `name` (jobs are name-keyed in MCP). */
export interface Job {
  id: string;
  name: string;
  kind: JobKind;
  schedule: string;
  timezone: string;
  state: JobState;
  source?: JobSource;
  /**
   * One-shot fire flag. Backend disables the job after its first
   * fire (success OR failure). The /jobs/new form sets this for
   * "Run Now" + "Run Once at <datetime>" frequencies; recurring
   * frequencies (Hourly / Daily / Weekly / Monthly / Custom) leave
   * it false.
   */
  run_once?: boolean;
  /** When true, the scheduler sends
   *  `X-Phantom-Approval-Bypass: 1` on every chat dispatch so the
   *  MCP-side gate auto-approves any humanRequired tools the agent
   *  calls. Audit rows still record each fired tool with
   *  `auto_approved=true`. Toggleable via the kebab menu (existing
   *  jobs) or the bypass slider in the new-job form. */
  bypass_approvals?: boolean;
  action?: JobAction;
  /** Per-job model override; empty/absent means the runtime default. */
  model_id?: string | null;
  /** Extended-thinking toggle sent with each dispatch. */
  thinking_enabled?: boolean;
  /** Declarative tool policy: glob lists under allowed_tools and
   *  denied_tools. Absent = no policy. */
  permission_policy?: Record<string, string[]> | null;
  /** Operator-written note about what the job is for. Empty when none. */
  description?: string;
  /** Only set while the job is Active; a paused or completed job has no
   *  next run. */
  next_run_at?: string;
  last_run_at?: string;
  last_status?: string;
  last_error?: string;
  run_count?: string;
  created_at?: string;
  updated_at?: string;
}

/** Single row from `/api/v1/jobs/{name}/runs` — one historical fire. */
export interface JobRun {
  id: string;
  job_name?: string;
  /** Legacy alias kept for the trigger response shape. */
  job_id?: string;
  /** Optional alias kept for the trigger response shape. */
  run_id?: string;
  /** Trigger response only: whether the fire succeeded. */
  success?: boolean;
  /** Trigger response only: error string when success=false. */
  error_message?: string;
  /** Historical run only: ISO timestamp the fire began. */
  fired_at?: string;
  /** Historical run only: ISO timestamp the fire completed. */
  finished_at?: string;
  /** Historical run only: "success" | "failure" | "skipped". */
  status?: string;
  /** Historical run only: wallclock ms of the fire. */
  duration_ms?: number;
  /** Historical run only: parsed JSON result body (or string if unparseable). */
  result?: unknown;
  /** Historical run only: raw error message. */
  error?: string;
  /** Historical run only: "cron" | "manual" — what fired this. */
  trigger?: string;
  /** Trigger response only — kept for back-compat. */
  started_at?: string;
  /** Trigger response only — kept for back-compat. */
  completed_at?: string;
}

/** Payload for creating a job. */
export interface CreateJobPayload {
  name: string;
  kind: number;
  schedule: string;
  timezone?: string;
  action?: {
    agent_id: string;
    message?: string;
  };
  description?: string;
}

/** Payload for PATCH /api/v1/jobs/:name. The MCP scheduler exposes
 *  `enabled` directly (boolean); the proto-style `state` enum is a UI
 *  legacy from the old gateway and is silently dropped server-side. */
export interface UpdateJobPayload {
  cron?: string;
  timezone?: string;
  enabled?: boolean;
  action?: Record<string, unknown>;
  /** Toggle the per-job approval bypass. Server falls
   *  through to the existing value when undefined; only patches when
   *  the field is present in the body. */
  bypass_approvals?: boolean;
  /** Omit to keep the stored note; "" clears it. */
  description?: string;
}

// ─── Wire-shape normalizer ────────────────────────────────────────────────────
//
// The phantom MCP (FastMCP, see bundles/spark/mcp/src/api/jobs.py + the
// JobRow.to_dict() in usecase/job_scheduler.py) uses cron-native names:
//
//   { name, cron, timezone, action, enabled, removed,
//     last_fired_at, last_status, last_error,
//     next_due_at, registered_at, source, run_once }
//
// The UI components were built against an older proto-style JobRow
// shape (id / kind / schedule / state / next_run_at / last_run_at).
// Rather than rip up every consumer, we normalize at the API boundary.
// `kind` is inferred from the cron expression; `state` from the
// `enabled` boolean (run_once + last_fired_at flips it to COMPLETED).

interface MCPJobRow {
  /** Opaque UUID minted at insert. Stable across rename. The UI uses
   *  this in URLs because UUIDs don't need path encoding. Older MCP
   *  builds didn't ship it — when missing we fall back to `name` so
   *  links still work, just with the encoding caveat. */
  id?: string;
  name: string;
  cron: string;
  timezone?: string;
  action?: Record<string, unknown> | null;
  enabled?: boolean;
  removed?: boolean;
  last_fired_at?: string | null;
  last_status?: string | null;
  last_error?: string | null;
  next_due_at?: string | null;
  registered_at?: string;
  source?: JobSource;
  run_once?: boolean;
  /** Wire shape for the new bypass column. */
  bypass_approvals?: boolean;
  model_id?: string | null;
  thinking_enabled?: boolean;
  permission_policy?: Record<string, string[]> | null;
  description?: string | null;
  /** Lifetime fire count, populated by the scheduler's correlated
   *  subquery against job_runs. Absent when the MCP does not report
   *  it; left undefined so the UI renders "—" rather than a
   *  misleading "0". */
  run_count?: number;
}

/** Heuristic mapping from a cron-ish string to the UI's JobKind. */
function inferKind(cron: string, runOnce: boolean): JobKind {
  if (runOnce) return "JOB_KIND_ONCE";
  // "5m", "1h" etc. — interval shorthand the /jobs/new form accepts
  if (/^\d+[smhd]$/.test(cron.trim())) return "JOB_KIND_INTERVAL";
  return "JOB_KIND_CRON";
}

/**
 * Normalize one MCP JobRow into the UI's proto-style Job shape. Falls
 * back gracefully when the input already looks proto-style (e.g. tests
 * and existing fixtures).
 */
export function normalizeJob(row: unknown): Job {
  const r = (row ?? {}) as Partial<Job> & Partial<MCPJobRow> & Record<string, unknown>;

  // Already-normalized rows (have `id` and `state`) pass through —
  // useful for tests and for the create/update endpoints that return
  // the row in the same envelope as list.
  if (typeof r.id === "string" && typeof r.state === "string") {
    return r as Job;
  }

  const name = (r.name as string) ?? (r.id as string) ?? "";
  const cron = (r.cron as string) ?? (r.schedule as string) ?? "";
  const runOnce = Boolean(r.run_once);
  const enabled = r.enabled !== undefined ? Boolean(r.enabled) : true;
  const lastFiredAt = (r.last_fired_at as string | null | undefined) ?? null;
  const nextDueAt = (r.next_due_at as string | null | undefined) ?? null;

  // Effective state: if a run_once job has fired and there's no next
  // due, it's completed; otherwise enabled→active, !enabled→paused.
  let state: JobState;
  if (runOnce && lastFiredAt && !nextDueAt) {
    state = "JOB_STATE_COMPLETED";
  } else if (enabled) {
    state = "JOB_STATE_ACTIVE";
  } else {
    state = "JOB_STATE_PAUSED";
  }

  // Prefer the MCP-issued opaque UUID (`r.id`); fall back to the
  // operator-facing name for back-compat with older MCP builds that
  // pre-date the id column. Once everyone's on the new schema this
  // fallback can go.
  const id =
    typeof r.id === "string" && r.id.length > 0
      ? r.id
      : name;

  return {
    id,
    name,
    kind: inferKind(cron, runOnce),
    schedule: cron,
    timezone: (r.timezone as string) ?? "UTC",
    state,
    source: (r.source as JobSource | undefined) ?? "manifest",
    run_once: runOnce,
    bypass_approvals: Boolean(r.bypass_approvals),
    action: (r.action as JobAction | undefined) ?? undefined,
    // Carried through so Edit and Duplicate see the stored overrides;
    // dropping them made an Edit save PATCH model_id "" and wipe them.
    model_id: (r.model_id as string | null | undefined) ?? null,
    thinking_enabled: Boolean(r.thinking_enabled),
    permission_policy:
      (r.permission_policy as Record<string, string[]> | null | undefined) ??
      null,
    // Rows stored before the column existed read as empty.
    description: typeof r.description === "string" ? r.description : "",
    // Only an enabled job has a next run (the MCP already omits it for
    // paused/completed jobs; this keeps a stale value from older builds
    // out of the UI too).
    next_run_at: enabled ? (nextDueAt ?? undefined) : undefined,
    last_run_at: lastFiredAt ?? undefined,
    last_status: (r.last_status as string | undefined) ?? undefined,
    last_error: (r.last_error as string | undefined) ?? undefined,
    created_at: (r.registered_at as string | undefined) ?? undefined,
    // String-encoded for parity with the existing UI consumer that
    // does `{job.run_count ?? "0"}`. Number → string conversion is
    // explicit so a count of 0 stays "0" (not falsy → "0"-via-??).
    run_count:
      typeof r.run_count === "number" ? String(r.run_count) : undefined,
  };
}

// ─── API Helpers ──────────────────────────────────────────────────────────────

/** List jobs from GET /api/v1/jobs. Wire shape `{jobs: [...], count}` is
 *  normalized to the UI's proto-style Job array. */
export async function listJobs(options?: ApiRequestOptions): Promise<ApiResult<Job[]>> {
  const result = await listRequest<unknown>("/api/v1/jobs", options);
  if (!result.ok) return result;
  return { ok: true, data: result.data.map(normalizeJob) };
}

/** Get a single job by ID from GET /api/v1/jobs/:id. */
export async function getJob(
  id: string,
  options?: ApiRequestOptions,
): Promise<ApiResult<Job>> {
  const result = await apiRequest<{ job?: unknown } | unknown>(
    `/api/v1/jobs/${encodeURIComponent(id)}`,
    options,
  );
  if (!result.ok) return result;
  // MCP wraps single-row responses in `{job: {...}}`.
  const raw =
    typeof result.data === "object" &&
    result.data !== null &&
    "job" in result.data
      ? (result.data as { job: unknown }).job
      : result.data;
  return { ok: true, data: normalizeJob(raw) };
}

/** Create a new job via POST /api/v1/jobs. */
export function createJob(payload: CreateJobPayload, options?: ApiRequestOptions) {
  return apiRequest<Job>("/api/v1/jobs", {
    ...options,
    method: "POST",
    body: payload,
  });
}

/** Update an existing job via PATCH /api/v1/jobs/:name. The MCP route
 *  is PATCH (not PUT) and accepts a partial body — see
 *  bundles/spark/mcp/src/api/jobs.py:patch_job. */
export function updateJob(name: string, payload: UpdateJobPayload, options?: ApiRequestOptions) {
  return apiRequest<{ job: unknown }>(
    `/api/v1/jobs/${encodeURIComponent(name)}`,
    { ...options, method: "PATCH", body: payload },
  );
}

/** Delete a job via DELETE /api/v1/jobs/:id. */
export function deleteJob(id: string, options?: ApiRequestOptions) {
  return apiRequest<void>(
    `/api/v1/jobs/${encodeURIComponent(id)}`,
    { ...options, method: "DELETE" },
  );
}

/** Trigger a job manually via POST /api/v1/jobs/:name/run.
 *
 * MCP path is /run (not /trigger) — see bundles/spark/mcp/src/api/jobs.py.
 * Returns 202 with a `run` envelope; we just hand back the response data
 * since callers typically `router.refresh()` after to re-pull the row. */
export function triggerJob(name: string, options?: ApiRequestOptions) {
  return apiRequest<{ run: JobRun }>(
    `/api/v1/jobs/${encodeURIComponent(name)}/run`,
    { ...options, method: "POST" },
  );
}

/** List historical runs for a job from GET /api/v1/jobs/:name/runs. */
export async function listJobRuns(
  name: string,
  opts?: ApiRequestOptions & { limit?: number },
): Promise<ApiResult<JobRun[]>> {
  const limit = opts?.limit ?? 20;
  const result = await listRequest<JobRun>(
    `/api/v1/jobs/${encodeURIComponent(name)}/runs?limit=${limit}`,
    opts,
  );
  return result;
}
