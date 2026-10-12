/**
 * Pure logic behind the /jobs/new form: cron building and parsing, the
 * mapping from a stored job to form values (Duplicate), the unique
 * "(copy)" name, and the submit-enabled rule.
 *
 * Kept free of imports and of non-erasable TypeScript so
 * scripts/test-job-form.mjs can load this file directly with Node's type
 * stripping. The form page imports every helper from here, so the test
 * exercises the same code the page runs.
 */

export type ScheduleMode = "now" | "once" | "repeating" | "custom";
export type IntervalUnit = "minutes" | "hours" | "days";
export type ActionType = "tool_call" | "prompt";

/** Inclusive upper bound per interval unit (cron resets each cycle). */
export const INTERVAL_MAX: Record<IntervalUnit, number> = {
  minutes: 59,
  hours: 23,
  days: 31,
};

// ─── Cron building ────────────────────────────────────────────────────

/** Cron that matches one specific minute on one specific date. */
export function buildOnceCron(d: Date): string {
  return `${d.getMinutes()} ${d.getHours()} ${d.getDate()} ${d.getMonth() + 1} *`;
}

/** Cron for "every N <unit>". */
export function buildIntervalCron(n: number, unit: IntervalUnit): string {
  const safe = Math.max(1, Math.floor(n));
  switch (unit) {
    case "minutes":
      return `*/${safe} * * * *`;
    case "hours":
      // Anchor at :00 of each hour so the cadence stays readable.
      return `0 */${safe} * * *`;
    case "days":
      // Anchor at 00:00 on day 1, 1+N, 1+2N, ... of each month.
      return `0 0 */${safe} * *`;
  }
}

export function buildCron(
  mode: ScheduleMode,
  intervalN: number,
  intervalUnit: IntervalUnit,
  customCron: string,
  onceAt: Date,
  now: Date,
): string {
  switch (mode) {
    case "now":
      // Defensive 1-minute-future cron in case the post-create /run
      // trigger fails; the cron tick is the second-best path to fire.
      return buildOnceCron(new Date(now.getTime() + 60_000));
    case "once":
      return buildOnceCron(onceAt);
    case "repeating":
      return buildIntervalCron(intervalN, intervalUnit);
    case "custom":
      return customCron.trim();
  }
}

// ─── Cron parsing (inverse of the builders above) ─────────────────────

export interface ParsedSchedule {
  mode: ScheduleMode;
  intervalN: number;
  intervalUnit: IntervalUnit;
  customCron: string;
  /** Set only when mode === "once". */
  onceAt: Date | null;
}

/** One hour ahead, on a whole minute: the form's default "Run at". */
export function defaultOnceAt(now: Date): Date {
  const d = new Date(now.getTime());
  d.setMinutes(d.getMinutes() + 60, 0, 0);
  return d;
}

function parseIntervalCron(
  cron: string,
): { n: number; unit: IntervalUnit } | null {
  const candidates: Array<[RegExp, IntervalUnit]> = [
    [/^\*\/(\d+) \* \* \* \*$/, "minutes"],
    [/^0 \*\/(\d+) \* \* \*$/, "hours"],
    [/^0 0 \*\/(\d+) \* \*$/, "days"],
  ];
  for (const [re, unit] of candidates) {
    const m = re.exec(cron);
    if (!m) continue;
    const n = Number(m[1]);
    if (n >= 1 && n <= INTERVAL_MAX[unit]) return { n, unit };
  }
  return null;
}

/**
 * Recover the form's schedule picker state from a stored cron string.
 *
 * Shapes the form itself can generate map back to their mode: "Every N
 * minutes/hours/days" to Repeating, and a run-once job's
 * "M H D Mo *" to Run at. Anything else stays Custom with the raw cron,
 * which is always a faithful copy of the schedule.
 *
 * A run-once job's stored date is usually in the past by the time it is
 * duplicated (a "Run now" job always is), and the form refuses a Run at
 * in the past, so a past date falls back to the form's default (one
 * hour ahead). The copy is still a one-shot.
 */
export function parseCronSchedule(
  cron: string,
  runOnce: boolean,
  now: Date,
): ParsedSchedule {
  const norm = cron.trim().replace(/\s+/g, " ");
  const base: ParsedSchedule = {
    mode: "custom",
    intervalN: 5,
    intervalUnit: "minutes",
    customCron: cron.trim(),
    onceAt: null,
  };

  if (runOnce) {
    const m = /^(\d+) (\d+) (\d+) (\d+) \*$/.exec(norm);
    if (m) {
      const [minute, hour, day, month] = m.slice(1).map(Number);
      const candidate = new Date(
        now.getFullYear(),
        month - 1,
        day,
        hour,
        minute,
        0,
        0,
      );
      const usable =
        !Number.isNaN(candidate.getTime()) &&
        candidate.getMonth() === month - 1 &&
        candidate.getTime() > now.getTime() + 60_000;
      return {
        ...base,
        mode: "once",
        onceAt: usable ? candidate : defaultOnceAt(now),
      };
    }
    return base;
  }

  const interval = parseIntervalCron(norm);
  if (interval) {
    return {
      ...base,
      mode: "repeating",
      intervalN: interval.n,
      intervalUnit: interval.unit,
    };
  }
  return base;
}

// ─── Job to form values (Duplicate) ───────────────────────────────────

/** The fields of a stored job the form reads. Structural, so the helper
 *  needs no import of the API client's `Job` type. */
export interface JobLike {
  name: string;
  schedule: string;
  timezone?: string;
  state?: string;
  run_once?: boolean;
  bypass_approvals?: boolean;
  action?: Record<string, unknown>;
  model_id?: string | null;
  thinking_enabled?: boolean;
  permission_policy?: Record<string, string[]> | null;
  description?: string | null;
}

export interface JobFormValues {
  name: string;
  description: string;
  actionType: ActionType;
  promptMessage: string;
  skillBinding: string;
  toolName: string;
  toolArgsJson: string;
  schedule: ParsedSchedule;
  timezone: string;
  enabled: boolean;
  bypassApprovals: boolean;
  modelId: string;
  thinkingEnabled: boolean;
  allowedTools: string;
  deniedTools: string;
}

function globList(v: unknown): string {
  return Array.isArray(v) ? v.filter((x) => typeof x === "string").join(", ") : "";
}

/**
 * Every form field a stored job defines. Used by Duplicate (name gets the
 * "(copy)" suffix from the caller) and shared with Edit.
 *
 * `enabled` is true for a job that is Active OR Completed: a completed
 * run-once job is disabled only because it already fired, so its copy
 * should be enabled. Only an operator-paused job copies as disabled.
 */
export function jobToFormValues(job: JobLike, now: Date): JobFormValues {
  const action = job.action ?? {};
  const isToolCall = action.type === "tool_call";
  const policy = job.permission_policy ?? {};
  const schedule = parseCronSchedule(
    job.schedule || "",
    Boolean(job.run_once),
    now,
  );
  return {
    name: job.name,
    description: job.description ?? "",
    // Legacy `chat` is an alias for `prompt`; anything unfamiliar opens
    // as a prompt so the operator sees something sensible to edit.
    actionType: isToolCall ? "tool_call" : "prompt",
    promptMessage: typeof action.message === "string" ? action.message : "",
    skillBinding: typeof action.skill === "string" ? action.skill : "",
    toolName: isToolCall && typeof action.name === "string" ? action.name : "",
    toolArgsJson:
      isToolCall && action.args && typeof action.args === "object"
        ? JSON.stringify(action.args, null, 2)
        : "{}",
    schedule,
    timezone: job.timezone || "UTC",
    enabled: job.state !== "JOB_STATE_PAUSED",
    bypassApprovals: Boolean(job.bypass_approvals),
    modelId: job.model_id || "",
    thinkingEnabled: Boolean(job.thinking_enabled),
    allowedTools: globList(policy.allowed_tools),
    deniedTools: globList(policy.denied_tools),
  };
}

/**
 * "<base> (copy)", or "<base> (copy 2)", "(copy 3)" ... when that name is
 * taken. Comparison is case-sensitive, like the backend's name key.
 */
export function uniqueCopyName(base: string, existing: Iterable<string>): string {
  const taken = new Set(existing);
  let candidate = `${base} (copy)`;
  for (let i = 2; taken.has(candidate); i++) {
    candidate = `${base} (copy ${i})`;
  }
  return candidate;
}

// ─── Submit rule ──────────────────────────────────────────────────────

export interface SubmitInput {
  name: string;
  actionType: ActionType;
  toolName: string;
  promptMessage: string;
  mode: ScheduleMode;
  intervalN: number;
  intervalUnit: IntervalUnit;
  customCron: string;
  onceAt: Date;
}

export function intervalOutOfRange(
  mode: ScheduleMode,
  intervalN: number,
  intervalUnit: IntervalUnit,
): boolean {
  return (
    mode === "repeating" &&
    (intervalN < 1 || intervalN > INTERVAL_MAX[intervalUnit])
  );
}

/** Whether the Create / Save button is enabled. */
export function canSubmitJobForm(v: SubmitInput, now: Date): boolean {
  const cron = buildCron(
    v.mode,
    v.intervalN,
    v.intervalUnit,
    v.customCron,
    v.onceAt,
    now,
  );
  return (
    v.name.trim() !== "" &&
    cron !== "" &&
    (v.actionType !== "tool_call" || v.toolName.trim() !== "") &&
    (v.actionType !== "prompt" || v.promptMessage.trim() !== "") &&
    // Run at needs a future datetime; the 60-second buffer keeps a
    // borderline-now pick from racing the cron tick.
    (v.mode !== "once" || v.onceAt.getTime() > now.getTime() + 60_000) &&
    !intervalOutOfRange(v.mode, v.intervalN, v.intervalUnit)
  );
}
