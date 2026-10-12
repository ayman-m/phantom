"use client";

import { useCallback, useRef, useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { triggerJob, updateJob, deleteJob } from "@/lib/api/jobs";
import type { Job, JobRun } from "@/lib/api/jobs";

interface JobActionsProps {
  jobId: string;
  jobName: string;
  isPaused: boolean;
  /** A run-once job that already ran. Its stored Run-at time has no year,
   * so Resume would arm it for the same date next year; the menu hides
   * Pause/Resume and leaves Trigger Now, Edit (new Run-at time) and
   * Duplicate. */
  isCompleted?: boolean;
  /** Current bypass-approvals state. When undefined, the
   * "Bypass approvals" menu item is omitted (older callers / list
   * page that don't fetch the full job row don't get the toggle —
   * operators can flip it from the detail page instead). */
  bypassApprovals?: boolean;
  /** Optional — when provided, enables the Export submenu. The job
   * detail page passes the row + recent runs already fetched server-
   * side so the export is a free client-side download (no extra API
   * round-trip). The list page omits these props so Export simply
   * doesn't render there. */
  job?: Job;
  runs?: JobRun[];
  /** Where to navigate after a successful delete. Set by
   * the job-details page (/jobs/[id]) to "/jobs" so the operator
   * doesn't get left on a 404'd detail view after the row is gone.
   * The list page omits this prop and the handler falls through to
   * the legacy `router.refresh()` behaviour (which is correct for
   * the list view — the row simply disappears from the rendered
   * list). */
  redirectOnDeleteTo?: string;
}

/** Three-dot dropdown menu for job actions (Trigger, Pause/Resume, Delete). */
export function JobActions({
  jobId,
  jobName,
  isPaused,
  isCompleted = false,
  bypassApprovals,
  job,
  runs,
  redirectOnDeleteTo,
}: JobActionsProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  // Close menu on outside click
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const handleTrigger = useCallback(async () => {
    setBusy(true);
    setOpen(false);
    try {
      await triggerJob(jobId);
      // Server-component refresh re-pulls the row; if the trigger
      // already finished, last_status flips here. If still in flight,
      // the row's `enabled`/`last_fired_at` will update on the next
      // refresh tick (cards show "Running…" via the busy state below
      // until then).
      router.refresh();
    } finally {
      setBusy(false);
    }
  }, [jobId, router]);

  const handleTogglePause = useCallback(async () => {
    setBusy(true);
    setOpen(false);
    try {
      // MCP PATCH accepts {enabled: bool}. The old proto-style
      // {state: 1|2} silently no-op'd on the server — that's why
      // Pause/Resume looked broken even on jobs that loaded.
      await updateJob(jobId, { enabled: isPaused });
      router.refresh();
    } finally {
      setBusy(false);
    }
  }, [jobId, isPaused, router]);

  // Toggle the per-job approval bypass. Sends the new
  // value via PATCH; the scheduler picks it up on the NEXT fire (in-
  // flight runs keep their original setting). Caller passes
  // `bypassApprovals` so we can flip rather than always-set.
  const handleToggleBypass = useCallback(async () => {
    if (bypassApprovals === undefined) return;
    setBusy(true);
    setOpen(false);
    try {
      await updateJob(jobId, { bypass_approvals: !bypassApprovals });
      router.refresh();
    } finally {
      setBusy(false);
    }
  }, [jobId, bypassApprovals, router]);

  // Duplicate lives at /jobs/new?from=<name>. The form loads the source
  // job itself, so the copy carries every field (action, schedule kind,
  // model, bypass, ...) without any of it travelling in the URL.
  const handleDuplicate = useCallback(() => {
    setOpen(false);
    router.push(`/jobs/new?from=${encodeURIComponent(jobName)}`);
  }, [jobName, router]);

  // Edit lives at /jobs/new?edit=<name>. Same form as
  // Create but populated from the existing job and submitting via
  // PATCH instead of POST. We pass the job NAME (not id) because the
  // MCP's PATCH endpoint is name-keyed.
  const handleEdit = useCallback(() => {
    setOpen(false);
    router.push(`/jobs/new?edit=${encodeURIComponent(jobName)}`);
  }, [jobName, router]);

  const handleDelete = useCallback(async () => {
    setBusy(true);
    setOpen(false);
    await deleteJob(jobId);
    setBusy(false);
    // When called from the job-details view, navigate away
    // to the list page — staying on /jobs/[id] after the row is gone
    // leaves the operator looking at a 404'd or stale detail view.
    // The list view passes no redirect and falls through to refresh()
    // which is correct there (row just disappears from the rendered
    // list).
    if (redirectOnDeleteTo) {
      router.push(redirectOnDeleteTo);
    } else {
      router.refresh();
    }
  }, [jobId, router, redirectOnDeleteTo]);

  // Trigger a client-side file download for the given Blob. Builds a
  // hidden <a download> rather than navigating because we want to keep
  // the operator on the job detail page.
  const downloadBlob = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    // Defer revoke so the download has time to start (Safari quirk).
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  /**
   * Build a definition-only JSON envelope.
   *
   * Shape (importable as-is via POST /api/agent/jobs):
   *   {
   *     exported_at: ISO-8601,
   *     schema_version: 1,
   *     job: {
   *       name, cron, timezone, action, enabled, run_once,
   *       bypass_approvals, [meta]
   *     }
   *   }
   *
   * We deliberately drop runtime-only fields (id, last_fired_at,
   * last_status, last_error, run_count, next_due_at, registered_at,
   * source) — those describe the running INSTANCE, not the
   * definition. The whole point of "export definition" is "the
   * minimal blob I need to re-create this job somewhere else."
   *
   * Field-name choice: the create endpoint expects `cron` (not
   * `schedule`), so we surface `cron` here too. That way an export
   * file imports without translation.
   */
  const buildDefinitionEnvelope = useCallback(() => {
    if (!job) return null;
    const definition: Record<string, unknown> = {
      name: job.name,
      cron: job.schedule, // proto-style `schedule` → wire-shape `cron`
      timezone: job.timezone || "UTC",
      action: job.action ?? {},
      enabled: job.state === "JOB_STATE_ACTIVE",
      run_once: job.run_once ?? false,
      bypass_approvals: job.bypass_approvals ?? false,
    };
    // `meta` may not be on the public Job type but the API does
    // round-trip a meta blob (description, etc.); preserve it
    // opportunistically.
    const maybeMeta = (job as unknown as { meta?: Record<string, unknown> })
      .meta;
    if (maybeMeta && typeof maybeMeta === "object") {
      definition.meta = maybeMeta;
    }
    return {
      exported_at: new Date().toISOString(),
      schema_version: 1,
      job: definition,
    };
  }, [job]);

  /** Export definition only — works from any view that has the Job
   *  object. Available in the list-view kebab as well as detail. */
  const handleExportDefinition = useCallback(() => {
    if (!job) return;
    setOpen(false);
    const envelope = buildDefinitionEnvelope();
    if (!envelope) return;
    const blob = new Blob([JSON.stringify(envelope, null, 2)], {
      type: "application/json",
    });
    downloadBlob(blob, `${jobName}.json`);
  }, [buildDefinitionEnvelope, job, jobName]);

  /** Export definition + run history. Detail-page only — the list
   *  view doesn't load runs, so this menu item is hidden there. */
  const handleExportRuns = useCallback(() => {
    if (!job) return;
    if (!runs || runs.length === 0) return;
    setOpen(false);
    const definitionEnvelope = buildDefinitionEnvelope();
    if (!definitionEnvelope) return;
    const envelope = {
      ...definitionEnvelope,
      // Preserve every run as the API returns it — id, fired_at,
      // finished_at, status, duration_ms, trigger, error, result.
      // No filtering / no slicing; the operator wants the full
      // history, not a summary.
      runs,
    };
    const blob = new Blob([JSON.stringify(envelope, null, 2)], {
      type: "application/json",
    });
    downloadBlob(blob, `${jobName}-with-runs.json`);
  }, [buildDefinitionEnvelope, job, runs, jobName]);

  const definitionExportEnabled = job !== undefined;
  const runsExportEnabled = job !== undefined && (runs?.length ?? 0) > 0;

  return (
    <div className="relative" ref={menuRef}>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        disabled={busy}
        className="w-9 h-9 rounded-lg flex items-center justify-center text-on-surface-variant hover:bg-white/10 hover:text-on-surface transition-colors disabled:opacity-50"
        aria-label={`Actions for ${jobName}`}
      >
        {/* While an action is in flight, swap the kebab for a spinning
            ring so the operator sees something happened. Pure CSS
            animation — no JS interval, no layout shift (same 36×36
            footprint as the icon below). */}
        {busy ? (
          <span
            className="block w-4 h-4 rounded-full border-2 border-primary border-t-transparent animate-spin"
            aria-label="Working…"
          />
        ) : (
          <span className="material-symbols-outlined text-lg">more_vert</span>
        )}
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-50 w-44 rounded-xl py-1 shadow-xl"
          style={{
            background: "var(--glass-bg-elev)",
            backdropFilter: "blur(16px)",
            border: "0.5px solid var(--glass-border)",
          }}
        >
          <MenuItem
            icon="play_arrow"
            label="Trigger Now"
            onClick={handleTrigger}
          />
          {!isCompleted && (
            <MenuItem
              icon={isPaused ? "play_circle" : "pause_circle"}
              label={isPaused ? "Resume" : "Pause"}
              onClick={handleTogglePause}
            />
          )}
          {bypassApprovals !== undefined && (
            <MenuItem
              icon={bypassApprovals ? "verified_user" : "bolt"}
              label={
                bypassApprovals
                  ? "Disable approval bypass"
                  : "Enable approval bypass"
              }
              onClick={handleToggleBypass}
            />
          )}
          <MenuItem
            icon="edit"
            label="Edit"
            onClick={handleEdit}
          />
          <MenuItem
            icon="content_copy"
            label="Duplicate"
            onClick={handleDuplicate}
          />
          {definitionExportEnabled && (
            <>
              <div className="my-1 h-px bg-white/10" />
              <MenuItem
                icon="download"
                label="Export definition (.json)"
                onClick={handleExportDefinition}
              />
              {/* Runs export is detail-page only — the list-view
                  kebab doesn't load runs, so showing this disabled
                  on every row would just be visual noise. Hide
                  entirely when runs are absent OR empty. */}
              {runs !== undefined && (
                <MenuItem
                  icon="history"
                  label="Export runs (.json)"
                  onClick={handleExportRuns}
                  disabled={!runsExportEnabled}
                />
              )}
            </>
          )}
          <div className="my-1 h-px bg-white/10" />
          <MenuItem
            icon="delete"
            label="Delete"
            onClick={handleDelete}
            destructive
          />
        </div>
      )}
    </div>
  );
}

function MenuItem({
  icon,
  label,
  onClick,
  destructive = false,
  disabled = false,
}: {
  icon: string;
  label: string;
  onClick: () => void;
  destructive?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`w-full flex items-center gap-3 px-4 py-2 text-sm transition-colors ${
        disabled
          ? "text-on-surface-variant/40 cursor-not-allowed"
          : destructive
            ? "text-error hover:bg-error/10"
            : "text-on-surface hover:bg-white/10"
      }`}
    >
      <span className="material-symbols-outlined text-base">{icon}</span>
      {label}
    </button>
  );
}
