"use client";

/**
 * Create Job — phantom-flavored port of spark_ui/ui/app/jobs/new/page.tsx.
 *
 * Three sections:
 *
 *   01 Identity    — name (required), description (optional, stored on the job)
 *   02 Action      — type picker (tool_call | log | chat) + body
 *   03 Schedule    — 4-mode picker: now | once | repeating | custom
 *
 * Schedule UX:
 *
 *   * Run now       — fires immediately on save, then auto-disables.
 *   * Run at        — datetime-local picker; fires once at that moment,
 *                     then auto-disables.
 *   * Repeating     — "Every N <unit>" where unit ∈ {minutes, hours,
 *                     days}. Anchored to the cron clock, not to "now"
 *                     (e.g. every 5 minutes fires at :00, :05, :10…).
 *   * Custom        — raw 5-field cron expression for power users who
 *                     need day-of-week, specific dates, etc.
 *
 * The previous hourly/daily/weekly/monthly presets collapse into the
 * Repeating mode. Day-of-week + day-of-month selectors are dropped —
 * those exotic patterns belong in Custom now. Operators consistently
 * preferred "every N units" over the calendar-style presets in
 * feedback.
 *
 * Backend note: croniter (the scheduler's parser) is 5-field, 1-minute
 * granularity. Sub-minute ("every N seconds") would need a separate
 * scheduler path, so it's NOT exposed here. The UI surfaces this with
 * an inline note rather than silently disabling.
 *
 * Submit posts to /api/agent/jobs which proxies POST /api/v1/jobs on
 * the embedded MCP. The MCP tags the job with source='runtime' so it
 * survives boot reconciliation untouched.
 *
 * Three entry points share this form:
 *
 *   /jobs/new              blank create
 *   /jobs/new?edit=<name>  Save form for an existing job (PATCH, name locked)
 *   /jobs/new?from=<name>  Duplicate: create form pre-filled from an
 *                          existing job (action, schedule kind, model,
 *                          flags), name "<name> (copy)"
 *
 * The edit and duplicate entries load the source job through the jobs
 * API rather than carrying fields in the URL; lib/job-form.ts holds the
 * pure mapping from a stored job to the form's fields.
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";

import { getJob, listJobs } from "@/lib/api/jobs";
import {
  buildCron,
  canSubmitJobForm,
  defaultOnceAt,
  INTERVAL_MAX,
  intervalOutOfRange as isIntervalOutOfRange,
  jobToFormValues,
  uniqueCopyName,
} from "@/lib/job-form";
import type {
  ActionType,
  IntervalUnit,
  JobFormValues,
  ScheduleMode,
} from "@/lib/job-form";
import {
  compareProviders,
  fetchModelCatalog,
  refForStoredModel,
  lifecycleBadge,
  providerName,
  selectableChatModels,
} from "@/lib/model-catalog";

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

// ─── Types ────────────────────────────────────────────────────────────

// Action types are {prompt, tool_call}. The legacy
// `chat` and `log` types existed before; the backend's boot migration
// rewrites old DB rows to the new shape. The UI now offers exactly
// these two options. (ScheduleMode / IntervalUnit / ActionType live in
// lib/job-form.ts with the cron helpers.)

const MODES: { id: ScheduleMode; label: string; icon: string; help: string }[] = [
  {
    id: "now",
    label: "Run now",
    icon: "play_arrow",
    help: "Fires immediately, then disables.",
  },
  {
    id: "once",
    label: "Run at",
    icon: "event",
    help: "Fires once at a chosen date+time, then disables.",
  },
  {
    id: "repeating",
    label: "Repeating",
    icon: "replay",
    help: "Fires every N minutes/hours/days until disabled.",
  },
  {
    id: "custom",
    label: "Custom cron",
    icon: "code",
    help: "Raw 5-field cron expression for advanced patterns.",
  },
];

const UNITS: { id: IntervalUnit; label: string; max: number; help?: string }[] = [
  // 1-59 — cron's `*/N * * * *` resets hourly, so non-divisors of 60
  // produce uneven gaps at the hour boundary. We allow them anyway and
  // describe the actual cadence in the preview.
  { id: "minutes", label: "Minutes", max: INTERVAL_MAX.minutes },
  // 1-23 — same caveat applies for hours not dividing 24.
  { id: "hours", label: "Hours", max: INTERVAL_MAX.hours },
  // 1-31 — `*/N * * *` over day-of-month resets monthly. For most use
  // cases pick 1, 2, 3, 4, or 7 to avoid stepwise drift across months.
  { id: "days", label: "Days", max: INTERVAL_MAX.days },
];

/** True for one-shot modes that auto-disable after first fire. */
function isOneShot(m: ScheduleMode): boolean {
  return m === "now" || m === "once";
}

const ACTIONS: {
  id: ActionType;
  label: string;
  desc: string;
  icon: string;
}[] = [
  {
    id: "prompt",
    label: "Prompt",
    desc:
      "Send a natural-language message to the agent on a schedule. " +
      "Runs through the same pipeline as interactive chat — personality, " +
      "memory, audit, tool dispatch all apply.",
    icon: "chat",
  },
  {
    id: "tool_call",
    label: "Tool Call",
    desc:
      "Invoke an MCP tool directly with explicit arguments. No LLM " +
      "involvement; deterministic. Best for log generation, recurring " +
      "queries, anything where the args are known up-front.",
    icon: "build",
  },
];

// ─── Schedule description ─────────────────────────────────────────────
// (Cron building and parsing live in lib/job-form.ts.)

function describeSchedule(
  mode: ScheduleMode,
  intervalN: number,
  intervalUnit: IntervalUnit,
  onceAt: Date,
): string {
  switch (mode) {
    case "now":
      return "Fires immediately on save, then disables.";
    case "once":
      return `Fires once at ${onceAt.toLocaleString()} (${Intl.DateTimeFormat().resolvedOptions().timeZone}), then disables.`;
    case "repeating": {
      // Singular vs plural: "Every 1 minute" not "Every 1 minutes".
      const word =
        intervalN === 1 ? intervalUnit.slice(0, -1) : intervalUnit;
      return `Every ${intervalN} ${word}`;
    }
    case "custom":
      return "Custom cron expression";
  }
}

/** True when the interval doesn't divide evenly into its unit's natural
 * cycle — informs an inline note about uneven cadence at the wrap. */
function hasUnevenInterval(n: number, unit: IntervalUnit): boolean {
  if (n < 2) return false;
  switch (unit) {
    case "minutes":
      return 60 % n !== 0;
    case "hours":
      return 24 % n !== 0;
    case "days":
      // Day-of-month wraps monthly (28/29/30/31 days). Anything other
      // than 1 risks a wrap mismatch; flag everything > 1 conservatively
      // unless N is one we know is clean enough for typical operator
      // expectations (1, 2, 3, 4, 7 — divisors of 28 or "weekly").
      return ![1, 2, 3, 4, 7].includes(n);
  }
}

// ─── Page ─────────────────────────────────────────────────────────────

export default function CreateJobPageWrapper() {
  return (
    <Suspense
      fallback={
        <div className="p-8 text-on-surface-variant">Loading…</div>
      }
    >
      <CreateJobPage />
    </Suspense>
  );
}

function CreateJobPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Edit mode. When the URL carries ?edit=<jobName>, the
  // page becomes a Save form for that existing job: fetches the row
  // on mount, pre-populates every field, locks the name (PATCH endpoint
  // is name-keyed and the MCP doesn't support rename), and changes
  // submit from POST to PATCH. Same component handles both modes
  // because the form layout is identical — duplicating it as
  // /jobs/[id]/edit/page.tsx would be ~700 lines of pure copy.
  const editName = searchParams.get("edit");
  const isEditMode = Boolean(editName);
  // Duplicate mode. ?from=<jobName> opens the create form pre-filled from
  // that job. ?edit wins if both are present.
  const fromName = isEditMode ? null : searchParams.get("from");
  const isDuplicateMode = Boolean(fromName);
  const sourceName = editName ?? fromName;
  const [editLoading, setEditLoading] = useState(Boolean(sourceName));
  const [editLoadError, setEditLoadError] = useState<string | null>(null);

  // ── Identity ──
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  // ── Action ──
  const [actionType, setActionType] = useState<ActionType>("prompt");

  // tool_call
  const [toolName, setToolName] = useState("");
  const [toolArgsJson, setToolArgsJson] = useState("{}");

  // prompt (the legacy "chat" action type is an alias with the same
  // on-the-wire shape — `{type: "chat", message}` and
  // `{type: "prompt", message}` are both accepted by the scheduler
  // dispatch).
  const [promptMessage, setPromptMessage] = useState("");

  // Optional skill binding for prompt actions. When
  // set, the scheduled prompt prepends the skill's MD body to the
  // user message before dispatching to chat. Empty string means
  // "let the agent decide which skill (if any) to apply" — same
  // behavior as a normal interactive chat turn (the skills registry
  // is in the system prompt, agent picks based on intent). Operator
  // overrides this when they want a deterministic-skill-binding job
  // rather than relying on the model's judgment.
  const [skillBinding, setSkillBinding] = useState<string>("");

  // Skills registry — fetched once on mount for the picker dropdown.
  // Empty array if /api/skills hasn't responded yet OR returns
  // nothing; the dropdown still renders "Let agent decide" so the
  // operator isn't blocked.
  const [availableSkills, setAvailableSkills] = useState<
    Array<{
      name: string;
      displayName: string;
      category: string;
      description: string;
    }>
  >([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/skills", { cache: "no-store" });
        if (!res.ok) return;
        const body = (await res.json()) as {
          skills?: Array<{
            name: string;
            displayName?: string;
            category: string;
            description?: string;
          }>;
        };
        if (cancelled) return;
        const rows = (body.skills || []).map((s) => ({
          name: s.name,
          displayName: s.displayName || s.name,
          category: s.category,
          description: s.description || "",
        }));
        setAvailableSkills(rows);
      } catch {
        // Empty skills registry is the fallback — picker just shows
        // "Let agent decide" and operators can still write any
        // freeform prompt.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // ── Schedule ──
  const [mode, setMode] = useState<ScheduleMode>("repeating");
  const [intervalN, setIntervalN] = useState(5);
  const [intervalUnit, setIntervalUnit] = useState<IntervalUnit>("minutes");
  const [customCron, setCustomCron] = useState("0 9 * * 1-5");
  const [timezone, setTimezone] = useState("UTC");
  const [enabled, setEnabled] = useState(true);
  // Per-job approval bypass. When true, the scheduler sets
  // `X-Phantom-Approval-Bypass: 1` on every chat dispatch for this job
  // so the MCP-side gate auto-approves any humanRequired tools the
  // agent calls. Default false — operator opts in explicitly. Audit
  // rows still record every fired tool with auto_approved=true so
  // post-hoc review surfaces what ran without confirmation.
  const [bypassApprovals, setBypassApprovals] = useState(false);
  // Per-job model override.
  //   - modelId: "" means "use the install default" (no override).
  //     Any non-empty value is a canonical model ref ("provider/model")
  //     sent as body.model on the chat dispatch. A job saved before refs
  //     existed holds a bare id; it is shown as the ref it resolves to.
  //   - thinkingEnabled: extended-thinking toggle. Dispatched as
  //     body.thinking = true, which the chat route maps to Gemini's
  //     thinkingConfig.
  //   - availableModels: catalog fetched from /api/agent/models; used
  //     to populate the dropdown + decide whether Thinking is
  //     enableable for the picked model (supportsThinking flag).
  const [modelId, setModelId] = useState<string>("");
  const [thinkingEnabled, setThinkingEnabled] = useState(false);
  // Per-job permission policy. Two comma-separated glob fields the
  // operator edits as raw strings; the request body parses into
  // arrays. Empty fields mean "no constraint on that dimension."
  // Both empty = no policy.
  const [allowedTools, setAllowedTools] = useState<string>("");
  const [deniedTools, setDeniedTools] = useState<string>("");
  const [availableModels, setAvailableModels] = useState<
    Array<{
      provider: string;
      model: string;
      ref: string;
      displayName?: string;
      availability?: string;
      supportsThinking: boolean;
    }>
  >([]);
  // loading -> ready | error. The "no models registered" hint shows only
  // for a registry that loaded and is truly empty, never while the fetch
  // is in flight or after it failed.
  const [modelsStatus, setModelsStatus] = useState<
    "loading" | "ready" | "error"
  >("loading");
  useEffect(() => {
    const ctrl = new AbortController();
    void (async () => {
      try {
        // Same registry, same fetcher as the /models page.
        const catalog = await fetchModelCatalog(ctrl.signal);
        setAvailableModels(
          selectableChatModels(catalog).map((m) => ({
            provider: m.provider,
            model: m.model,
            ref: m.ref ?? `${m.provider}/${m.model}`,
            displayName: m.displayName,
            availability: m.availability,
            supportsThinking: Boolean(m.supportsThinking),
          })),
        );
        setModelsStatus("ready");
      } catch (err) {
        if (ctrl.signal.aborted) return;
        console.warn("jobs/new: failed to load model catalog:", err);
        setModelsStatus("error");
      }
    })();
    return () => ctrl.abort();
  }, []);

  // A job saved before refs existed holds a bare model id. Once the registry
  // has loaded, show it as the canonical ref it resolves to, so saving the
  // form writes the canonical form.
  useEffect(() => {
    if (modelsStatus !== "ready" || !modelId) return;
    const ref = refForStoredModel(availableModels, modelId);
    if (ref && ref !== modelId) setModelId(ref);
  }, [availableModels, modelsStatus, modelId]);

  // "Run at" datetime — defaults to 1 hour from now (a sensible future
  // point that doesn't require the operator to fight the datetime-local
  // input every time). Stored as a Date for math; the form's
  // <input type="datetime-local"> exchanges via formatDatetimeLocal /
  // parseDatetimeLocal helpers below.
  const [onceAt, setOnceAt] = useState<Date>(() => defaultOnceAt(new Date()));

  // ── Submit state ──
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── Derived ──
  const cron = useMemo(
    () => buildCron(mode, intervalN, intervalUnit, customCron, onceAt, new Date()),
    [mode, intervalN, intervalUnit, customCron, onceAt],
  );

  const scheduleLabel = useMemo(
    () => describeSchedule(mode, intervalN, intervalUnit, onceAt),
    [mode, intervalN, intervalUnit, onceAt],
  );

  const oneShot = isOneShot(mode);

  const currentUnit = useMemo(
    () => UNITS.find((u) => u.id === intervalUnit) ?? UNITS[0],
    [intervalUnit],
  );

  const intervalOutOfRange = isIntervalOutOfRange(
    mode,
    intervalN,
    intervalUnit,
  );

  const intervalUneven =
    mode === "repeating" &&
    !intervalOutOfRange &&
    hasUnevenInterval(intervalN, intervalUnit);

  const canSubmit = canSubmitJobForm(
    {
      name,
      actionType,
      toolName,
      promptMessage,
      mode,
      intervalN,
      intervalUnit,
      customCron,
      onceAt,
    },
    new Date(),
  );

  // ── Handlers ──
  const buildAction = useCallback((): Record<string, unknown> | null => {
    if (actionType === "tool_call") {
      let args: unknown = {};
      try {
        args = toolArgsJson.trim() ? JSON.parse(toolArgsJson) : {};
      } catch (err) {
        setError(
          `Tool args is not valid JSON: ${err instanceof Error ? err.message : "parse error"}`,
        );
        return null;
      }
      return { type: "tool_call", name: toolName.trim(), args };
    }
    if (actionType === "prompt") {
      const action: Record<string, unknown> = {
        type: "prompt",
        message: promptMessage.trim(),
      };
      // Optional skill binding. Only attach the
      // field when the operator actually picked a specific skill —
      // empty/auto means "no binding, agent decides", which is the
      // scheduler's default behavior.
      if (skillBinding && skillBinding.trim()) {
        action.skill = skillBinding.trim();
      }
      return action;
    }
    return null;
  }, [
    actionType,
    toolName,
    toolArgsJson,
    promptMessage,
    skillBinding,
  ]);

  // Populate every field from an existing job: the job being edited
  // (?edit=) or the job being duplicated (?from=). The mapping from a
  // stored job to form fields is lib/job-form.ts:jobToFormValues, so the
  // two entry points cannot drift. Differences between them:
  //
  //   edit       name locked to the job's, schedule shown as Custom +
  //              raw cron (an edit should not silently re-derive it),
  //              enabled mirrors the job's state.
  //   duplicate  name becomes a unique "<name> (copy)", schedule keeps
  //              its real kind (Repeating / Run at / Custom), enabled is
  //              true unless the operator had paused the source.
  //
  // The dependency array intentionally lists only the source name: this
  // runs ONCE per mount, after which the form is owned by the operator's
  // edits.
  useEffect(() => {
    if (!sourceName) return;
    let cancelled = false;
    void (async () => {
      const [result, siblings] = await Promise.all([
        getJob(sourceName),
        // Existing names make the copy's name unique; best effort (the
        // backend still rejects a clash with a readable error).
        isDuplicateMode ? listJobs() : Promise.resolve(null),
      ]);
      if (cancelled) return;
      if (!result.ok) {
        setEditLoadError(result.error.message);
        setEditLoading(false);
        return;
      }
      const job = result.data;
      const v: JobFormValues = jobToFormValues(job, new Date());
      setName(
        isEditMode
          ? job.name
          : uniqueCopyName(
              job.name,
              siblings && siblings.ok ? siblings.data.map((j) => j.name) : [],
            ),
      );
      setDescription(v.description);
      setTimezone(v.timezone);
      setEnabled(isEditMode ? job.state === "JOB_STATE_ACTIVE" : v.enabled);
      setBypassApprovals(v.bypassApprovals);
      setModelId(v.modelId);
      setThinkingEnabled(v.thinkingEnabled);
      setAllowedTools(v.allowedTools);
      setDeniedTools(v.deniedTools);
      setActionType(v.actionType);
      if (v.actionType === "tool_call") {
        setToolName(v.toolName);
        setToolArgsJson(v.toolArgsJson);
      } else {
        setPromptMessage(v.promptMessage);
        setSkillBinding(v.skillBinding);
      }
      if (isEditMode) {
        setMode("custom");
        setCustomCron(job.schedule || "0 9 * * *");
      } else {
        setMode(v.schedule.mode);
        setIntervalN(v.schedule.intervalN);
        setIntervalUnit(v.schedule.intervalUnit);
        setCustomCron(v.schedule.customCron || "0 9 * * *");
        if (v.schedule.onceAt) setOnceAt(v.schedule.onceAt);
      }
      setEditLoading(false);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceName]);

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return;
    setError(null);
    const action = buildAction();
    if (action === null) return; // buildAction already set error
    setSubmitting(true);
    try {
      const trimmedName = name.trim();
      // Branch on edit mode. POST creates a new job;
      // PATCH updates an existing one. The PATCH endpoint accepts
      // partial bodies and is name-keyed (no rename), so we send
      // every field the form owns and the MCP applies them in
      // place.
      const url = isEditMode
        ? `/api/agent/jobs/${encodeURIComponent(editName as string)}`
        : "/api/agent/jobs";
      const method = isEditMode ? "PATCH" : "POST";
      const resp = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: trimmedName,
          cron,
          timezone: timezone.trim() || "UTC",
          action,
          enabled,
          // run_once auto-disables after first fire (success or failure).
          // Set for "Run now" and "Run at" modes; recurring modes leave
          // it false so they keep ticking until the operator disables.
          run_once: oneShot,
          bypass_approvals: bypassApprovals,
          // Per-job model + thinking overrides.
          // Empty modelId means "use runtime default" — we still send
          // it (as "") on PATCH so the backend's sentinel clears any
          // prior override; on POST it's also fine (the API normalizes
          // "" → None at write time).
          model_id: modelId,
          thinking_enabled: thinkingEnabled,
          // Permission policy. Parse the two comma-separated glob
          // strings into arrays. Both empty → send {} so the backend's
          // sentinel CLEARS any prior policy. Otherwise send the
          // populated dict.
          permission_policy: (() => {
            const parse = (s: string) =>
              s
                .split(",")
                .map((x) => x.trim())
                .filter((x) => x.length > 0);
            const a = parse(allowedTools);
            const d = parse(deniedTools);
            if (a.length === 0 && d.length === 0) {
              return {};
            }
            return {
              ...(a.length ? { allowed_tools: a } : {}),
              ...(d.length ? { denied_tools: d } : {}),
            };
          })(),
          // Always sent: "" on PATCH clears a stored description.
          description: description.trim(),
        }),
      });
      const text = await resp.text();
      if (!resp.ok) {
        let parsed: { error?: string } = {};
        try {
          parsed = JSON.parse(text);
        } catch {
          // fall through to raw text
        }
        throw new Error(
          parsed.error ?? `HTTP ${resp.status}: ${text.slice(0, 200)}`,
        );
      }

      // For "Run now", trigger the job manually right after create so
      // it fires immediately rather than waiting for the cron's next
      // minute tick. The run_once flag still auto-disables after the
      // first fire. Best-effort — if the trigger fails we still
      // navigate to /jobs (the cron will catch it within ~60s).
      if (mode === "now") {
        try {
          await fetch(
            `/api/agent/jobs/${encodeURIComponent(trimmedName)}/run`,
            { method: "POST" },
          );
        } catch (err) {
          console.warn(
            "Run now: manual trigger failed (cron will fire within ~60s)",
            err,
          );
        }
      }

      router.push("/jobs");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create job");
      setSubmitting(false);
    }
  }, [
    canSubmit,
    buildAction,
    name,
    cron,
    timezone,
    enabled,
    description,
    router,
    mode,
    oneShot,
    bypassApprovals,
    modelId,
    thinkingEnabled,
    allowedTools,
    deniedTools,
    isEditMode,
    editName,
  ]);

  // ── Render ──
  return (
    <div className="flex flex-col h-screen">
      <div className="flex-1 overflow-y-auto p-8 pb-32">
        {/* Breadcrumb */}
        <nav className="flex items-center gap-2 text-on-surface-variant font-label text-xs uppercase tracking-widest mb-6">
          <Link href="/jobs" className="hover:text-primary transition-colors">
            Jobs
          </Link>
          <span className="material-symbols-outlined text-[14px]">
            chevron_right
          </span>
          <span className="text-primary font-bold">
            {isEditMode ? "Edit Job" : "Create Job"}
          </span>
        </nav>

        {/* Header */}
        <header className="mb-10">
          <div className="flex items-center gap-3 mb-1">
            <span className="material-symbols-outlined text-2xl text-primary">
              schedule
            </span>
            <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
              {isEditMode ? `Edit Job — ${editName}` : "Create Job"}
            </h1>
          </div>
          <p className="text-sm text-on-surface-variant ml-9">
            {isEditMode
              ? "Update an existing job's schedule, action, or runtime flags. Name is fixed."
              : isDuplicateMode
                ? `Copy of ${fromName}. Review the name and schedule, then create it — the original stays untouched.`
                : "Schedule an automated task — runs at runtime, separate from manifest-declared jobs."}
          </p>
          {editLoading && (
            <p className="text-xs text-on-surface-variant/70 ml-9 mt-2 flex items-center gap-2">
              <span className="material-symbols-outlined text-[14px] animate-spin">
                progress_activity
              </span>
              Loading current values…
            </p>
          )}
          {editLoadError && (
            <p className="text-xs text-error ml-9 mt-2">
              Could not load {isDuplicateMode ? "the job to duplicate" : "job"}: {editLoadError}
            </p>
          )}
        </header>

        {/* 3-Column Grid */}
        <div className="max-w-6xl mx-auto grid grid-cols-12 gap-8">
          {/* Section 01: Identity */}
          <section className="col-span-12 lg:col-span-4 space-y-5">
            <SectionHeader number="01" title="Identity" />

            <div className="rounded-2xl p-5 space-y-4" style={glassStyle}>
              <div>
                <label className="block font-label text-[10px] text-on-surface-variant uppercase tracking-widest mb-1.5">
                  Job Name <span className="text-error">*</span>
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. nightly-port-scan"
                  // Name is the immutable identifier; the
                  // PATCH endpoint is name-keyed and the MCP doesn't
                  // support rename. Lock the field in edit mode so the
                  // operator doesn't expect a rename to work.
                  readOnly={isEditMode}
                  disabled={isEditMode}
                  className="w-full bg-surface-container-highest border-none rounded-xl py-2.5 px-4 text-sm text-on-surface placeholder:text-on-surface-variant/40 focus:ring-1 focus:ring-primary disabled:opacity-50 disabled:cursor-not-allowed"
                />
                <p className="mt-1 text-[10px] text-on-surface-variant/60">
                  {isEditMode
                    ? "Job name is fixed after creation. Delete + recreate to rename."
                    : "Must be unique. Used as the URL path and in audit logs."}
                </p>
              </div>

              <div>
                <label className="block font-label text-[10px] text-on-surface-variant uppercase tracking-widest mb-1.5">
                  Description
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="What does this job do? Who owns it?"
                  rows={3}
                  className="w-full bg-surface-container-highest border-none rounded-xl py-2.5 px-4 text-sm text-on-surface placeholder:text-on-surface-variant/40 focus:ring-1 focus:ring-primary resize-none"
                />
              </div>

              <div className="flex items-center justify-between py-2 border-t border-white/5 pt-4">
                <div>
                  <p className="text-sm text-on-surface">Enabled at start</p>
                  <p className="text-[10px] text-on-surface-variant">
                    Disabled jobs can still be triggered manually.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setEnabled(!enabled)}
                  className={`w-10 h-5 rounded-full relative transition-colors ${
                    enabled ? "bg-primary" : "bg-surface-container-highest"
                  }`}
                  aria-label="Toggle enabled"
                >
                  <div
                    className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                      enabled ? "translate-x-5" : "translate-x-0.5"
                    }`}
                  />
                </button>
              </div>

              {/* Bypass-approvals slider. Sits below the
                  enabled toggle since it's a similar "ambient policy
                  for this job" concept. The yellow accent matches the
                  chat-header dropdown when bypass is ON, so the
                  visual language is consistent across surfaces. */}
              <div className="flex items-center justify-between py-2 border-t border-white/5 pt-4">
                <div>
                  <p className="text-sm text-on-surface">
                    Bypass approval prompts
                    {bypassApprovals && (
                      <span className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] uppercase font-bold tracking-tighter border bg-tertiary/15 text-tertiary border-tertiary/25 align-middle">
                        <span className="material-symbols-outlined text-[10px]">
                          bolt
                        </span>
                        ON
                      </span>
                    )}
                  </p>
                  <p className="text-[10px] text-on-surface-variant max-w-md">
                    When ON, this job auto-approves any tools listed in
                    the manifest&apos;s humanRequired (e.g.
                    personality_patch, jobs_create, web.navigate)
                    instead of waiting for operator confirmation. Audit
                    rows still record every fired tool with{" "}
                    <code className="font-mono text-[10px]">
                      auto_approved=true
                    </code>{" "}
                    so post-hoc review surfaces what ran. Use this for
                    routine recurring jobs where you trust the agent;
                    leave OFF for jobs that mutate operator state.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setBypassApprovals(!bypassApprovals)}
                  className={`w-10 h-5 rounded-full relative transition-colors shrink-0 ${
                    bypassApprovals
                      ? "bg-tertiary"
                      : "bg-surface-container-highest"
                  }`}
                  aria-label="Toggle approval bypass"
                  aria-pressed={bypassApprovals}
                >
                  <div
                    className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                      bypassApprovals ? "translate-x-5" : "translate-x-0.5"
                    }`}
                  />
                </button>
              </div>

              {/* Per-job model override. Default is the install default
                  (empty string → no override). Operator picks a specific
                  model when they want to override cost (flash) or
                  quality (pro + thinking) for this job's dispatches. */}
              <div className="py-2 border-t border-white/5 pt-4 space-y-3">
                <div>
                  <p className="text-sm text-on-surface">
                    Model
                    {modelId && (
                      <span className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] uppercase font-bold tracking-tighter border bg-primary/15 text-primary border-primary/25 align-middle">
                        <span className="material-symbols-outlined text-[10px]">
                          tune
                        </span>
                        OVERRIDE
                      </span>
                    )}
                  </p>
                  <p className="text-[10px] text-on-surface-variant max-w-md">
                    Pick a specific model for this job&apos;s dispatches.
                    Leave on <code className="font-mono text-[10px]">Install default</code> to
                    use the default model chosen on the Models page at
                    dispatch time. Override with a cheap model
                    (e.g. <code className="font-mono text-[10px]">vertex/gemini-3.7-flash</code>) for
                    routine / volume work, or a Pro variant when this
                    job needs the deeper reasoning path. If the model is
                    retired or its provider is removed, the job fails with
                    a clear error rather than running on another model.
                  </p>
                </div>
                <select
                  value={modelId}
                  onChange={(e) => {
                    const next = e.target.value;
                    setModelId(next);
                    // If the newly-picked model doesn't support thinking,
                    // force-disable the Thinking toggle so we don't ship
                    // a payload the chat-route's Gemini wrapper will
                    // silently ignore.
                    if (next) {
                      const spec = availableModels.find((m) => m.ref === next);
                      if (spec && !spec.supportsThinking) setThinkingEnabled(false);
                    }
                  }}
                  className="w-full px-3 py-2 rounded-xl text-sm bg-surface-container-low border border-white/10 text-on-surface"
                >
                  <option value="">Install default (no override)</option>
                  {/* A job can be pinned to a model the registry no longer
                      lists (provider removed, model retired). Keep it
                      selectable so opening the form does not silently
                      drop the override. */}
                  {modelId &&
                    modelsStatus === "ready" &&
                    !availableModels.some((m) => m.ref === modelId) && (
                      <option value={modelId}>
                        {modelId} (not in the registry)
                      </option>
                    )}
                  {/* The option value is the canonical ref, which is what the
                      job stores and the dispatch sends. */}
                  {[...new Set(availableModels.map((m) => m.provider))]
                    .sort(compareProviders)
                    .map((provider) => (
                      <optgroup key={provider} label={providerName(provider)}>
                        {availableModels
                          .filter((m) => m.provider === provider)
                          .map((m) => (
                            <option key={m.ref} value={m.ref}>
                              {m.displayName || m.model}
                              {m.supportsThinking ? " · thinking" : ""}
                              {lifecycleBadge(m) ? ` · ${lifecycleBadge(m)}` : ""}
                            </option>
                          ))}
                      </optgroup>
                    ))}
                </select>
                {modelsStatus === "ready" && availableModels.length === 0 && (
                  <p className="text-[10px] text-on-surface-variant/60 italic">
                    No models registered yet — configure a provider at{" "}
                    <code className="font-mono text-[10px]">/providers</code>{" "}
                    to populate this list.
                  </p>
                )}
                {modelsStatus === "error" && (
                  <p className="text-[10px] text-error">
                    Could not load the model list. Reload the page to retry;
                    the job will use the router default until you pick a model.
                  </p>
                )}
              </div>

              {/* Extended thinking toggle. Disabled when the picked
                  model doesn't supportsThinking (such models ignore
                  the thinking config). Dispatched as body.thinking. */}
              <div className="flex items-center justify-between py-2 border-t border-white/5 pt-4">
                <div>
                  <p className="text-sm text-on-surface">
                    Extended thinking
                    {thinkingEnabled && (
                      <span className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] uppercase font-bold tracking-tighter border bg-primary/15 text-primary border-primary/25 align-middle">
                        <span className="material-symbols-outlined text-[10px]">
                          psychology
                        </span>
                        ON
                      </span>
                    )}
                  </p>
                  <p className="text-[10px] text-on-surface-variant max-w-md">
                    Ask the model to use its extended-reasoning path
                    (Gemini&apos;s thinkingConfig). Models without
                    thinking support ignore it. Extended thinking is
                    on by default, so leaving this off does not turn
                    it off.
                  </p>
                </div>
                {(() => {
                  const picked = modelId
                    ? availableModels.find((m) => m.ref === modelId)
                    : undefined;
                  // Only disable when operator has picked a specific
                  // model AND that model lacks thinking support. "Router
                  // default" stays togglable since the routed model is
                  // unknown until dispatch.
                  const disabled = picked ? !picked.supportsThinking : false;
                  return (
                    <button
                      type="button"
                      onClick={() => !disabled && setThinkingEnabled(!thinkingEnabled)}
                      className={`w-10 h-5 rounded-full relative transition-colors shrink-0 ${
                        thinkingEnabled
                          ? "bg-primary"
                          : "bg-surface-container-highest"
                      } ${disabled ? "opacity-40 cursor-not-allowed" : ""}`}
                      aria-label="Toggle extended thinking"
                      aria-pressed={thinkingEnabled}
                      aria-disabled={disabled}
                      title={
                        disabled
                          ? "This model doesn't support extended thinking"
                          : undefined
                      }
                    >
                      <div
                        className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                          thinkingEnabled ? "translate-x-5" : "translate-x-0.5"
                        }`}
                      />
                    </button>
                  );
                })()}
              </div>

              {/* Permission policy editor.
                  Two comma-separated globs the operator edits raw.
                  Below each input, a tiny example helps. Empty fields
                  mean "no constraint on that dimension"; both empty
                  means no policy (revert to unrestricted). */}
              <div className="py-2 border-t border-white/5 pt-4 space-y-3">
                <div>
                  <p className="text-sm text-on-surface">
                    Permission policy
                    {(allowedTools || deniedTools) && (
                      <span className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] uppercase font-bold tracking-tighter border bg-secondary/15 text-secondary border-secondary/25 align-middle">
                        <span className="material-symbols-outlined text-[10px]">
                          shield_lock
                        </span>
                        ACTIVE
                      </span>
                    )}
                  </p>
                  <p className="text-[10px] text-on-surface-variant max-w-md">
                    Declarative tool allowlist enforced by the chat
                    route before each tool fires. Glob syntax:{" "}
                    <code className="font-mono text-[10px]">*</code> matches
                    anything, comma-separated for OR. Evaluation precedence:
                    denied → allowed (whitelist when non-empty) →
                    allow-by-default. Leave both empty to impose no policy.
                    Whether a tool needs an approval card is decided by
                    the install&apos;s approval list, not by the job.
                  </p>
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-on-surface-variant">Allowed tools (whitelist when non-empty)</label>
                  <input
                    type="text"
                    value={allowedTools}
                    onChange={(e) => setAllowedTools(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl text-sm bg-surface-container-low border border-white/10 text-on-surface font-mono"
                    placeholder="e.g. phantom_*, xlog.*"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-on-surface-variant">Denied tools (blocks even if matched by allowed)</label>
                  <input
                    type="text"
                    value={deniedTools}
                    onChange={(e) => setDeniedTools(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl text-sm bg-surface-container-low border border-white/10 text-on-surface font-mono"
                    placeholder="e.g. *_delete, caldera_create_operation"
                  />
                </div>
              </div>
            </div>
          </section>

          {/* Section 02: Action */}
          <section className="col-span-12 lg:col-span-4 space-y-5">
            <SectionHeader number="02" title="Action" />

            <div className="rounded-2xl p-5 space-y-4" style={glassStyle}>
              {/* Type picker */}
              <div className="space-y-2">
                {ACTIONS.map((opt) => (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => setActionType(opt.id)}
                    className={`w-full text-left flex items-start gap-3 p-3 rounded-xl transition-all ${
                      actionType === opt.id
                        ? "bg-primary-container/15 border border-primary/35"
                        : "bg-white/5 border border-white/10 hover:border-white/20"
                    }`}
                  >
                    <span className="material-symbols-outlined text-primary mt-0.5">
                      {opt.icon}
                    </span>
                    <div>
                      <p className="text-sm font-bold text-on-surface">
                        {opt.label}
                      </p>
                      <p className="text-[10px] text-on-surface-variant">
                        {opt.desc}
                      </p>
                    </div>
                  </button>
                ))}
              </div>

              {/* Type-specific fields */}
              {actionType === "tool_call" && (
                <div className="space-y-3 pt-3 border-t border-white/5">
                  <div>
                    <label className="block font-label text-[10px] text-on-surface-variant uppercase tracking-widest mb-1.5">
                      Tool Name <span className="text-error">*</span>
                    </label>
                    <input
                      type="text"
                      value={toolName}
                      onChange={(e) => setToolName(e.target.value)}
                      placeholder="phantom_create_data_worker"
                      className="w-full bg-surface-container-highest border-none rounded-xl py-2.5 px-4 text-sm text-on-surface placeholder:text-on-surface-variant/40 focus:ring-1 focus:ring-primary font-mono"
                    />
                  </div>
                  <div>
                    <label className="block font-label text-[10px] text-on-surface-variant uppercase tracking-widest mb-1.5">
                      Arguments (JSON)
                    </label>
                    <textarea
                      value={toolArgsJson}
                      onChange={(e) => setToolArgsJson(e.target.value)}
                      placeholder='{"vendor": "Cisco", "count": 10}'
                      rows={5}
                      className="w-full bg-surface-container-highest border-none rounded-xl py-2.5 px-4 text-xs text-on-surface placeholder:text-on-surface-variant/40 focus:ring-1 focus:ring-primary font-mono resize-none"
                    />
                  </div>
                </div>
              )}

              {actionType === "prompt" && (
                <div className="pt-3 border-t border-white/5 space-y-4">
                  <div>
                    <label className="block font-label text-[10px] text-on-surface-variant uppercase tracking-widest mb-1.5">
                      Prompt <span className="text-error">*</span>
                    </label>
                    <textarea
                      value={promptMessage}
                      onChange={(e) => setPromptMessage(e.target.value)}
                      placeholder="Run a port scan against 10.0.0.8 and report results."
                      rows={6}
                      className="w-full bg-surface-container-highest border-none rounded-xl py-2.5 px-4 text-sm text-on-surface placeholder:text-on-surface-variant/40 focus:ring-1 focus:ring-primary resize-none leading-relaxed"
                    />
                    <p className="mt-2 text-[10px] text-on-surface-variant/60 leading-relaxed">
                      Runs through the same chat pipeline as interactive
                      chat — your personality from{" "}
                      <Link href="/settings/personality" className="link">
                        /settings/personality
                      </Link>
                      {" "}is applied, the agent can call{" "}
                      <code className="font-mono">memory_search</code> /{" "}
                      <code className="font-mono">knowledge_search</code>{" "}
                      on demand, and every fired tool is audited.
                    </p>
                  </div>

                  {/* Optional skill binding for the
                      job. Default "Let agent decide" mirrors the
                      interactive-chat behavior — the model sees the
                      skills registry in its system prompt and picks
                      one if the prompt matches. Choosing a specific
                      skill from the dropdown forces that skill's MD
                      body to prepend the prompt at dispatch time, so
                      the run is deterministic regardless of model
                      drift. */}
                  <div>
                    <label className="block font-label text-[10px] text-on-surface-variant uppercase tracking-widest mb-1.5">
                      Skill (optional)
                    </label>
                    <select
                      value={skillBinding}
                      onChange={(e) => setSkillBinding(e.target.value)}
                      className="w-full bg-surface-container-highest border-none rounded-xl py-2.5 px-4 text-sm text-on-surface focus:ring-1 focus:ring-primary appearance-none cursor-pointer"
                    >
                      <option value="">
                        — Let agent decide —
                      </option>
                      {(["foundation", "scenarios", "validation", "workflows"] as const).map(
                        (cat) => {
                          const inCat = availableSkills.filter(
                            (s) => s.category === cat,
                          );
                          if (inCat.length === 0) return null;
                          return (
                            <optgroup key={cat} label={cat.toUpperCase()}>
                              {inCat.map((s) => (
                                <option key={s.name} value={s.name}>
                                  {s.displayName}
                                </option>
                              ))}
                            </optgroup>
                          );
                        },
                      )}
                    </select>
                    <p className="mt-2 text-[10px] text-on-surface-variant/60 leading-relaxed">
                      <strong>Let agent decide</strong> (default) —
                      the model sees the full skills registry in its
                      system prompt and picks one based on intent.{" "}
                      <strong>Specific skill</strong> — prepends the
                      skill&apos;s MD body to the prompt at dispatch
                      time so the run follows that skill&apos;s
                      runbook regardless of model drift. Useful for
                      reproducible scheduled exercises.
                    </p>
                    {skillBinding && (
                      <div className="mt-2 px-3 py-2 bg-primary/5 border border-primary/20 rounded-lg text-[10px] text-on-surface-variant">
                        <span className="material-symbols-outlined text-[12px] align-middle mr-1 text-primary-fixed-dim">
                          extension
                        </span>
                        {availableSkills.find((s) => s.name === skillBinding)
                          ?.description ||
                          "(skill description unavailable)"}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </section>

          {/* Section 03: Schedule */}
          <section className="col-span-12 lg:col-span-4 space-y-5">
            <SectionHeader number="03" title="Schedule" />

            <div className="rounded-2xl p-5 space-y-5" style={glassStyle}>
              {/* Mode picker — 2x2 grid */}
              <div className="grid grid-cols-2 gap-2">
                {MODES.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => setMode(m.id)}
                    className={`text-left p-3 rounded-xl transition-all flex items-start gap-2.5 ${
                      mode === m.id
                        ? "bg-secondary-container/30 border border-secondary/40"
                        : "bg-white/5 border border-white/10 hover:bg-white/10"
                    }`}
                  >
                    <span
                      className={`material-symbols-outlined text-base mt-0.5 ${
                        mode === m.id ? "text-secondary" : "text-on-surface-variant"
                      }`}
                    >
                      {m.icon}
                    </span>
                    <div className="min-w-0">
                      <p
                        className={`text-sm font-bold ${
                          mode === m.id ? "text-secondary" : "text-on-surface"
                        }`}
                      >
                        {m.label}
                      </p>
                      <p className="text-[10px] text-on-surface-variant leading-snug">
                        {m.help}
                      </p>
                    </div>
                  </button>
                ))}
              </div>

              {/* Run now — informational, no inputs. The job fires
                  immediately on save (manual trigger right after the
                  POST), then auto-disables via run_once. */}
              {mode === "now" && (
                <div
                  className="rounded-xl p-3 text-xs leading-relaxed flex gap-2 items-start"
                  style={{
                    background: "rgba(86, 181, 90, 0.08)",
                    border: "0.5px solid rgba(86, 181, 90, 0.25)",
                  }}
                >
                  <span className="material-symbols-outlined text-secondary text-base shrink-0 mt-0.5">
                    info
                  </span>
                  <span className="text-on-surface-variant">
                    Job will fire immediately on save and then disable
                    itself. Stays in the jobs list with full run history;
                    re-enable to fire again.
                  </span>
                </div>
              )}

              {/* Run at <datetime> — operator picks a future datetime
                  via the native datetime-local input. The cron expression
                  is generated from that exact minute; run_once auto-
                  disables after the fire. */}
              {mode === "once" && (
                <div>
                  <label className="block font-label text-[10px] text-on-surface-variant uppercase tracking-widest mb-1.5">
                    Run At <span className="text-error">*</span>
                  </label>
                  <input
                    type="datetime-local"
                    value={formatDatetimeLocal(onceAt)}
                    onChange={(e) => {
                      const parsed = parseDatetimeLocal(e.target.value);
                      if (parsed) setOnceAt(parsed);
                    }}
                    min={formatDatetimeLocal(
                      new Date(Date.now() + 60_000),
                    )}
                    className="w-full bg-surface-container-highest border-none rounded-xl py-2.5 px-4 text-sm text-on-surface focus:ring-1 focus:ring-primary font-mono"
                  />
                  <p className="mt-1 text-[10px] text-on-surface-variant/60">
                    Browser local time ({Intl.DateTimeFormat().resolvedOptions().timeZone}).
                    Must be at least 1 minute in the future.
                    {onceAt.getTime() <= Date.now() + 60_000 && (
                      <span className="block text-error mt-0.5">
                        Selected datetime is in the past or too soon — pick a future moment.
                      </span>
                    )}
                  </p>
                </div>
              )}

              {/* Repeating — number + unit picker. */}
              {mode === "repeating" && (
                <div>
                  <label className="block font-label text-[10px] text-on-surface-variant uppercase tracking-widest mb-1.5">
                    Every
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="number"
                      min={1}
                      max={currentUnit.max}
                      value={intervalN}
                      onChange={(e) => {
                        const v = parseInt(e.target.value);
                        setIntervalN(Number.isNaN(v) ? 1 : v);
                      }}
                      className={`w-24 bg-surface-container-highest border-none rounded-xl py-2.5 px-4 text-sm text-on-surface focus:ring-1 ${
                        intervalOutOfRange
                          ? "ring-1 ring-error"
                          : "focus:ring-primary"
                      }`}
                    />
                    <select
                      value={intervalUnit}
                      onChange={(e) => {
                        const u = e.target.value as IntervalUnit;
                        setIntervalUnit(u);
                        // Clamp the number to the new unit's range so
                        // switching from "30 minutes" to "hours" doesn't
                        // leave an invalid 30 hours value (max 23).
                        const max = UNITS.find((x) => x.id === u)?.max ?? 1;
                        if (intervalN > max) setIntervalN(max);
                      }}
                      className="flex-1 bg-surface-container-highest border-none rounded-xl py-2.5 px-4 text-sm text-on-surface focus:ring-1 focus:ring-primary"
                    >
                      {UNITS.map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <p className="mt-1 text-[10px] text-on-surface-variant/60">
                    Minimum interval is 1 minute (cron limitation).
                    {intervalOutOfRange && (
                      <span className="block text-error mt-0.5">
                        Out of range — {currentUnit.label.toLowerCase()} must be 1–{currentUnit.max}.
                      </span>
                    )}
                    {intervalUneven && (
                      <span className="block text-on-surface-variant mt-0.5">
                        ⚠ {intervalN} doesn&apos;t divide evenly into {intervalUnit === "minutes" ? "60" : intervalUnit === "hours" ? "24" : "the month"} — gaps will appear at the {intervalUnit === "days" ? "month" : intervalUnit === "hours" ? "day" : "hour"} boundary.
                      </span>
                    )}
                  </p>
                </div>
              )}

              {/* Custom cron — power-user escape hatch for patterns the
                  simple picker can't express (specific weekdays, ranges,
                  complex cadences, etc.). */}
              {mode === "custom" && (
                <div>
                  <label className="block font-label text-[10px] text-on-surface-variant uppercase tracking-widest mb-1.5">
                    Cron Expression <span className="text-error">*</span>
                  </label>
                  <input
                    type="text"
                    value={customCron}
                    onChange={(e) => setCustomCron(e.target.value)}
                    placeholder="0 9 * * 1-5"
                    className="w-full bg-surface-container-highest border-none rounded-xl py-2.5 px-4 text-sm text-on-surface focus:ring-1 focus:ring-primary font-mono"
                  />
                  <p className="mt-1 text-[10px] text-on-surface-variant/60">
                    5-field cron: minute hour day-of-month month day-of-week.
                    Example <code>0 9 * * 1-5</code> = weekdays at 09:00.
                  </p>
                </div>
              )}

              <div>
                <label className="block font-label text-[10px] text-on-surface-variant uppercase tracking-widest mb-1.5">
                  Timezone
                </label>
                <input
                  type="text"
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  placeholder="UTC"
                  className="w-full bg-surface-container-highest border-none rounded-xl py-2.5 px-4 text-sm text-on-surface focus:ring-1 focus:ring-primary font-mono"
                />
                <p className="mt-1 text-[10px] text-on-surface-variant/60">
                  IANA name (e.g. America/New_York). Defaults to UTC.
                </p>
              </div>

              {/* Cron preview */}
              <div className="rounded-xl bg-surface-container-lowest p-3 border-l-2 border-tertiary/40 space-y-1.5">
                <p className="font-label text-[10px] text-on-surface-variant uppercase tracking-widest">
                  Cron Expression
                </p>
                <code className="block font-mono text-xs text-tertiary break-all">
                  {cron || "—"}
                </code>
                <p className="font-label text-[10px] text-on-surface-variant uppercase tracking-widest pt-2">
                  Reads as
                </p>
                <p className="text-xs text-on-surface">{scheduleLabel}</p>
              </div>
            </div>
          </section>
        </div>

        {error && (
          <div className="max-w-6xl mx-auto mt-6 rounded-xl bg-error-container/20 border border-error/30 px-4 py-3 text-sm text-error">
            {error}
          </div>
        )}
      </div>

      {/* Sticky Footer */}
      <footer
        className="border-t border-white/5 px-8 py-4 flex items-center justify-between"
        style={{
          background: "rgba(18, 18, 30, 0.9)",
          backdropFilter: "blur(16px)",
        }}
      >
        <div className="flex items-center gap-6">
          <FooterMeta label="Job Name" value={name || "—"} />
          <div className="h-6 w-px bg-white/10" />
          <FooterMeta
            label="Action"
            value={
              ACTIONS.find((a) => a.id === actionType)?.label ?? actionType
            }
          />
          <div className="h-6 w-px bg-white/10" />
          <FooterMeta label="Schedule" value={scheduleLabel} />
        </div>

        <div className="flex items-center gap-4">
          <Link
            href="/jobs"
            className="px-5 py-2.5 rounded-xl text-sm font-medium text-on-surface-variant hover:bg-white/5 transition-colors"
          >
            Cancel
          </Link>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!canSubmit || submitting}
            // Use the dedicated `--job-cta-text` token so the foreground
            // flips with the theme: white on dark mode (against the saturated
            // blue gradient), near-black on light mode (so the button still
            // reads as a button against the lighter footer surface).
            className="job-cta flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-bold shadow-lg active:scale-95 transition-transform disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110"
          >
            {submitting ? (
              <>
                <span className="material-symbols-outlined text-lg animate-spin">
                  progress_activity
                </span>
                {isEditMode ? "Saving…" : "Creating…"}
              </>
            ) : (
              <>
                <span className="material-symbols-outlined text-lg">check</span>
                {isEditMode ? "Save Changes" : "Create Job"}
              </>
            )}
          </button>
        </div>
      </footer>
    </div>
  );
}

// ─── Sub-components ───────────────────────────────────────────────────

function SectionHeader({
  number,
  title,
}: {
  number: string;
  title: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <div className="w-1 h-5 rounded-full bg-primary" />
      <h2 className="font-headline text-xs font-bold uppercase tracking-wider text-on-surface">
        {number} — {title}
      </h2>
    </div>
  );
}

// ─── Datetime-local helpers ─────────────────────────────────────────
//
// `<input type="datetime-local">` exchanges values as
// "YYYY-MM-DDTHH:mm" without timezone — interpreted in browser-local
// time. Native Date.toISOString() returns UTC, which would feed the
// input the wrong wall-clock time. These helpers do the round-trip
// in browser-local time so the operator's "8pm tonight" means 8pm
// to them, not 8pm UTC.

function formatDatetimeLocal(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

function parseDatetimeLocal(s: string): Date | null {
  if (!s) return null;
  // Native Date can parse "YYYY-MM-DDTHH:mm" but interprets it as
  // local time (which is what we want for datetime-local). Validate
  // that the result is sane before returning.
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

function FooterMeta({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="font-label text-[10px] text-on-surface-variant/50 uppercase tracking-widest">
        {label}
      </span>
      <span className="text-xs font-bold text-on-surface truncate max-w-40">
        {value}
      </span>
    </div>
  );
}
