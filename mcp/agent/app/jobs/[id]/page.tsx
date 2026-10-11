/**
 * Job detail page — /jobs/{id}.
 *
 * Renders the full state of one scheduler row plus its recent run
 * history. Reachable from the click target on each card in the list
 * view.
 *
 * The path param is the job's opaque UUID (assigned at insert by the
 * MCP scheduler). UUIDs are URL-safe (no encoding needed), stable
 * across rename, and unambiguous. The MCP route accepts EITHER an id
 * or a name (sched.resolve_ident — see bundles/spark/mcp/src/api/jobs.py),
 * so old links pasted from before the migration still work; new links
 * the UI generates use id exclusively.
 */

import { cookies } from "next/headers";
import Link from "next/link";
import { notFound } from "next/navigation";

import { JobActions } from "../job-actions";
import { RunsExportButton } from "../runs-export-button";
import { getJob, listJobRuns } from "@/lib/api/jobs";
import type { Job, JobRun } from "@/lib/api/jobs";
import { getToken } from "@/lib/auth";
import { buildQuery } from "@/lib/observability-query";

const glassStyle = {
  background: "var(--glass-bg)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

function statusColor(status: string | undefined): string {
  switch (status) {
    case "success":
      return "text-secondary bg-secondary/15 border-secondary/25";
    case "failure":
      return "text-error bg-error/15 border-error/25";
    case "skipped":
      return "text-yellow-400 bg-yellow-500/15 border-yellow-500/25";
    default:
      return "text-on-surface-variant bg-white/10 border-white/20";
  }
}

function formatTime(ts: string | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatDuration(ms: number | undefined): string {
  if (ms === undefined || ms === null) return "—";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m}m ${s}s`;
}

/** Best-effort label for the job's action — what will it actually do
 *  when it fires? The list-view "Agent" cell was empty for tool_call
 *  + log jobs because action.agent_id is only set on type=chat. Now
 *  we describe each shape concretely. */
function describeAction(action: Job["action"] | undefined): string {
  if (!action) return "—";
  const t = action.type ?? "(unknown)";
  if (t === "chat") {
    const aid = action.agent_id ?? "(this agent)";
    const msg =
      typeof action.message === "string" && action.message.length > 0
        ? `: "${action.message.slice(0, 60)}${action.message.length > 60 ? "…" : ""}"`
        : "";
    return `chat → ${aid}${msg}`;
  }
  if (t === "tool_call") {
    return `tool_call → ${action.name ?? "(unnamed)"}`;
  }
  if (t === "log") {
    const fmt = (action as { format?: string; log_type?: string }).format
      ?? (action as { log_type?: string }).log_type
      ?? "?";
    const count = (action as { count?: number }).count ?? "?";
    return `log → ${fmt} × ${count}`;
  }
  return t;
}

interface PageProps {
  // Folder is `[id]` so Next.js puts the path segment under `params.id`.
  // Semantically this is an "ident": UUIDs are the new norm, but the MCP
  // resolver also accepts legacy names so pre-migration links keep working.
  params: Promise<{ id: string }>;
}

export default async function JobDetailPage({ params }: PageProps) {
  const { id: rawIdent } = await params;
  // decodeURIComponent is a no-op on UUIDs (no special chars) but does
  // the right thing for back-compat name-based paths.
  const ident = decodeURIComponent(rawIdent);

  const cookieStore = await cookies();
  const token = getToken(cookieStore);

  // Fetch row + runs in parallel — both are read-only and independent.
  // getJob/listJobRuns both call the MCP via the resolve_ident path so
  // either a UUID or a legacy name lands the same row.
  const [jobResult, runsResult] = await Promise.all([
    getJob(ident, { sessionToken: token }),
    listJobRuns(ident, { sessionToken: token, limit: 20 }),
  ]);

  if (!jobResult.ok) {
    if (jobResult.error.code === "HTTP_404") notFound();
    return (
      <div className="p-8 max-w-5xl mx-auto">
        <ErrorPanel title="Unable to load job" message={jobResult.error.message} />
      </div>
    );
  }

  const job = jobResult.data;
  const runs: JobRun[] = runsResult.ok ? runsResult.data : [];
  const runsError = !runsResult.ok ? runsResult.error.message : null;

  // ‟Last status” at the top doubles as a status summary so the operator
  // can tell at a glance "is this thing working?" without scrolling.
  const headerStatus = job.last_status ?? (job.last_run_at ? "—" : "never run");

  return (
    <div className="p-8 pb-32 max-w-5xl mx-auto">
      {/* Breadcrumb */}
      <Link
        href="/jobs"
        className="inline-flex items-center gap-1 text-xs uppercase tracking-widest text-on-surface-variant hover:text-on-surface transition-colors mb-4"
      >
        <span className="material-symbols-outlined text-base">arrow_back</span>
        All jobs
      </Link>

      {/* Header */}
      <header className="flex items-start justify-between mb-8">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-2 flex-wrap">
            <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface truncate">
              {job.name}
            </h1>
            <span
              className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-tighter border ${statusColor(headerStatus)}`}
              title={`last_status: ${headerStatus}`}
            >
              {headerStatus}
            </span>
            {job.source === "runtime" && (
              <span className="px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-tighter border bg-tertiary/15 text-tertiary border-tertiary/25">
                Runtime
              </span>
            )}
            {job.run_once && (
              <span className="px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-tighter border bg-primary/15 text-primary border-primary/25">
                Run once
              </span>
            )}
            {/* Bypass badge. Same yellow accent as the
                chat-header dropdown when bypass is ON, for visual
                consistency. Toggle via the kebab menu's "Bypass
                approvals" entry (job-actions.tsx). */}
            {(job as { bypass_approvals?: boolean }).bypass_approvals && (
              <span
                className="px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-tighter border bg-tertiary/15 text-tertiary border-tertiary/25 inline-flex items-center gap-1"
                title="This job auto-approves gated tools instead of waiting for operator confirmation. Audit rows still record every fired tool with auto_approved=true."
              >
                <span className="material-symbols-outlined text-[10px]">
                  bolt
                </span>
                Bypass ON
              </span>
            )}
          </div>
          <p className="text-sm text-on-surface-variant font-mono">
            {job.schedule}{" "}
            <span className="text-on-surface-variant/60">
              ({job.timezone || "UTC"})
            </span>
          </p>
        </div>
        {/* Job-level deep-links into observability surfaces. Each
            opens the corresponding /observability/* page pre-filtered
            to `target:job:<name>*` (catches every audit row touching
            this job — registration, every fire, enable/disable,
            deletes). Icon-only; hover reveals the destination via
            the title attribute, same convention as the kebab. */}
        <div className="flex items-center gap-1">
          <IconLinkButton
            href={`/observability/events?q=${encodeURIComponent(
              buildQuery({ targetPrefix: `job:${job.name}` }),
            )}`}
            icon="policy"
            label="View events for this job"
          />
          <IconLinkButton
            href={`/observability/logs?q=${encodeURIComponent(
              buildQuery({ targetPrefix: `job:${job.name}` }),
            )}`}
            icon="terminal"
            label="View logs for this job"
          />
          <IconLinkButton
            href={`/observability/traces?q=${encodeURIComponent(
              buildQuery({ triggerPrefix: `job:${job.name}` }),
            )}`}
            icon="lan"
            label="View traces for this job"
          />
          <JobActions
            jobId={job.id}
            jobName={job.name}
            isPaused={job.state === "JOB_STATE_PAUSED"}
            bypassApprovals={Boolean(job.bypass_approvals)}
            job={job}
            runs={runs}
            redirectOnDeleteTo="/jobs"
          />
        </div>
      </header>

      {/* Status grid */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCell label="Action" value={describeAction(job.action)} mono />
        <StatCell label="Last Run" value={formatTime(job.last_run_at)} />
        <StatCell label="Next Run" value={formatTime(job.next_run_at)} />
        <StatCell
          label="Total Runs"
          value={job.run_count ?? "0"}
          accent={runs.length > 0}
        />
      </section>

      {/* Last error (only when relevant) */}
      {job.last_error && (
        <section
          className="rounded-2xl p-5 mb-8 border-l-4 border-error"
          style={glassStyle}
        >
          <div className="flex items-start gap-3">
            <span className="material-symbols-outlined text-error">error</span>
            <div className="flex-1 min-w-0">
              <h3 className="font-headline font-bold text-error text-sm uppercase tracking-widest mb-1">
                Last error
              </h3>
              <pre className="text-xs font-mono text-error/90 whitespace-pre-wrap break-words leading-relaxed">
                {job.last_error}
              </pre>
            </div>
          </div>
        </section>
      )}

      {/* Action body — the literal payload that fires */}
      <section className="rounded-2xl p-5 mb-8" style={glassStyle}>
        <h3 className="font-headline font-bold text-sm uppercase tracking-widest text-on-surface-variant mb-3">
          Action body
        </h3>
        <pre className="text-xs font-mono text-on-surface bg-surface-container-lowest/50 rounded-lg p-3 overflow-auto max-h-64 leading-relaxed">
          {JSON.stringify(job.action ?? {}, null, 2)}
        </pre>
      </section>

      {/* Run history */}
      <section className="rounded-2xl p-5" style={glassStyle}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-headline font-bold text-sm uppercase tracking-widest text-on-surface-variant">
            Recent runs
          </h3>
          <div className="flex items-center gap-3">
            <span className="text-xs text-on-surface-variant/60">
              {runs.length} {runs.length === 1 ? "run" : "runs"}
            </span>
            <RunsExportButton job={job} runs={runs} />
          </div>
        </div>
        {runsError && (
          <p className="text-xs text-error mb-2">
            Could not load run history: {runsError}
          </p>
        )}
        {runs.length === 0 ? (
          <p className="text-sm text-on-surface-variant py-6 text-center">
            No runs yet. Use the kebab menu&rsquo;s &ldquo;Trigger Now&rdquo; to fire it manually.
          </p>
        ) : (
          <div className="space-y-2">
            {runs.map((run, idx) => (
              <RunRow
                key={run.id}
                run={run}
                actionType={typeof job.action?.type === "string" ? job.action.type : ""}
                jobName={job.name}
                defaultOpen={idx === 0}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

// ─── Run row ────────────────────────────────────────────────────────────────
//
// Native <details>/<summary> for expand/collapse — no client component, no
// hydration cost. The most-recent run defaults to open so the operator sees
// the latest output without an extra click; older ones stay collapsed.
//
// The body content is dispatched on `actionType` because chat / tool_call /
// log runs each carry meaningfully different result shapes:
//
//   chat       → {session_id, run_id, response, tool_calls[], tool_call_count}
//                Render the model's reply prominently, list tool calls, and
//                deep-link to /chat?session=<id> so the operator can open the
//                full conversation.
//   tool_call  → arbitrary JSON returned by the dispatched tool. Pretty-print
//                it under a disclosure since these can be large (e.g. a
//                coverage report can be MBs).
//   log        → {worker_id, count, destination, ...} — extract the headline
//                fields, fall back to JSON for the rest.
//   default    → JSON pretty-print.

function RunRow({
  run,
  actionType,
  jobName,
  defaultOpen,
}: {
  run: JobRun;
  actionType: string;
  jobName: string;
  defaultOpen: boolean;
}) {
  // Per-run telemetry uses `trigger:job:<name>` rather than `target:`
  // because the audit endpoint records target=job:<name> for the row
  // about the JOB itself, while every downstream effect (tool calls,
  // approval requests, MCP API hits during the run) carries the
  // trigger header. The icon links below build queries for the
  // run's wallclock window so adjacent runs don't overlap.
  return (
    <details
      open={defaultOpen}
      className="rounded-xl bg-surface-container-lowest/40 border border-white/5 overflow-hidden group"
    >
      <summary className="cursor-pointer px-4 py-3 flex items-center gap-4 hover:bg-white/[0.03] transition-colors">
        <span className="material-symbols-outlined text-base text-on-surface-variant transition-transform group-open:rotate-90">
          chevron_right
        </span>
        <span className="font-mono text-xs text-on-surface min-w-[180px]">
          {formatTime(run.fired_at)}
        </span>
        <span
          className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-tighter border ${statusColor(run.status)}`}
        >
          {run.status ?? "—"}
        </span>
        <span className="font-mono text-xs text-on-surface-variant">
          {run.trigger ?? "—"}
        </span>
        <span className="ml-auto font-mono text-xs text-on-surface-variant">
          {formatDuration(run.duration_ms)}
        </span>
      </summary>
      <div className="px-4 pb-4 pt-1 border-t border-white/5">
        {run.error && (
          <div className="rounded-md bg-error/10 border border-error/30 px-3 py-2 mb-3">
            <p className="text-[10px] font-headline uppercase tracking-widest text-error mb-1">
              Error
            </p>
            <pre className="text-xs font-mono text-error/90 whitespace-pre-wrap break-words leading-relaxed">
              {run.error}
            </pre>
          </div>
        )}
        <RunResultBody result={run.result} actionType={actionType} />
        {/* Per-run telemetry deep-links. Same query-bar syntax as the
            destination page, so the operator can refine the filter
            once they land — they're not locked into "just this run". */}
        {run.fired_at && (
          <div className="mt-3 pt-3 border-t border-white/5 flex items-center justify-end gap-1">
            <IconLinkButton
              href={`/observability/events?q=${encodeURIComponent(
                buildQuery({
                  triggerPrefix: `job:${jobName}`,
                  since: run.fired_at,
                  until: run.finished_at ?? undefined,
                }),
              )}`}
              icon="policy"
              label="View this run's events"
            />
            <IconLinkButton
              href={`/observability/logs?q=${encodeURIComponent(
                buildQuery({
                  triggerPrefix: `job:${jobName}`,
                  since: run.fired_at,
                  until: run.finished_at ?? undefined,
                }),
              )}`}
              icon="terminal"
              label="View this run's logs"
            />
            <IconLinkButton
              href={`/observability/traces?q=${encodeURIComponent(
                buildQuery({
                  triggerPrefix: `job:${jobName}`,
                  since: run.fired_at,
                  until: run.finished_at ?? undefined,
                }),
              )}`}
              icon="lan"
              label="View this run's traces"
            />
          </div>
        )}
      </div>
    </details>
  );
}

/** Small icon-only link with a hover tooltip via `title`. Used for the
 *  cluster of "view in observability" buttons on /jobs/[id] so they
 *  don't dominate visually with text labels — the operator hovers to
 *  see what each button does. Same density as the JobActions kebab. */
function IconLinkButton({
  href,
  icon,
  label,
}: {
  href: string;
  icon: string;
  label: string;
}) {
  return (
    <Link
      href={href}
      title={label}
      aria-label={label}
      className="w-9 h-9 rounded-lg flex items-center justify-center text-on-surface-variant hover:bg-white/10 hover:text-on-surface transition-colors"
    >
      <span className="material-symbols-outlined text-lg">{icon}</span>
    </Link>
  );
}

// ─── Result body — action-type-aware rendering ──────────────────────────────

function RunResultBody({
  result,
  actionType,
}: {
  result: unknown;
  actionType: string;
}) {
  if (result === null || result === undefined) {
    return (
      <p className="text-xs text-on-surface-variant/60 italic py-2">
        No result body recorded.
      </p>
    );
  }

  if (actionType === "chat" && typeof result === "object") {
    return <ChatResultBody result={result as Record<string, unknown>} />;
  }
  if (actionType === "log" && typeof result === "object") {
    return <LogResultBody result={result as Record<string, unknown>} />;
  }

  // tool_call + unknown: pretty-print JSON in a scrollable box.
  return (
    <pre className="text-xs font-mono text-on-surface bg-surface-container-lowest/60 rounded-md p-3 overflow-auto max-h-64 leading-relaxed whitespace-pre-wrap break-words">
      {typeof result === "string"
        ? result
        : JSON.stringify(result, null, 2)}
    </pre>
  );
}

function ChatResultBody({ result }: { result: Record<string, unknown> }) {
  const response =
    typeof result.response === "string" ? result.response : "";
  const toolCalls = Array.isArray(result.tool_calls)
    ? (result.tool_calls as Array<{
        name?: string;
        args?: unknown;
        result_status?: string;
        result_preview?: string;
      }>)
    : [];

  return (
    <div className="space-y-3">
      {/* Model's reply — the headline output of a chat job. */}
      {response ? (
        <div>
          <p className="text-[10px] font-headline uppercase tracking-widest text-on-surface-variant mb-1.5">
            Model response
          </p>
          <div className="rounded-md bg-primary/5 border border-primary/20 px-3 py-2">
            <p className="text-sm text-on-surface whitespace-pre-wrap leading-relaxed">
              {response}
            </p>
          </div>
        </div>
      ) : (
        <p className="text-xs text-on-surface-variant/60 italic">
          The model returned no text for this run (it may have only called tools).
        </p>
      )}

      {/* Tool calls the model made during the run. */}
      {toolCalls.length > 0 && (
        <div>
          <p className="text-[10px] font-headline uppercase tracking-widest text-on-surface-variant mb-1.5">
            Tool calls ({toolCalls.length})
          </p>
          <div className="space-y-1.5">
            {toolCalls.map((tc, i) => (
              <div
                key={i}
                className="rounded-md bg-surface-container-lowest/60 px-3 py-2 text-xs font-mono"
              >
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-primary font-bold">
                    {tc.name ?? "(unnamed)"}
                  </span>
                  {tc.result_status && (
                    <span
                      className={`px-1.5 py-0.5 rounded text-[9px] uppercase font-bold tracking-tighter border ${statusColor(tc.result_status)}`}
                    >
                      {tc.result_status}
                    </span>
                  )}
                </div>
                {tc.args !== undefined && (
                  <p className="text-on-surface-variant/80 mt-1 truncate">
                    args:{" "}
                    {typeof tc.args === "string"
                      ? tc.args
                      : JSON.stringify(tc.args)}
                  </p>
                )}
                {tc.result_preview && (
                  <p className="text-on-surface-variant mt-0.5 line-clamp-2">
                    → {tc.result_preview}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Raw result body — collapsed by default, expandable inline.
          Replaces the previous "Open conversation" deep-link to /chat,
          which leaked job runs into the human chat-session sidebar.
          Job runs stay self-contained on this page; raw JSON is here
          when the operator needs the full payload. */}
      <details className="text-xs">
        <summary className="cursor-pointer text-[10px] uppercase tracking-widest text-on-surface-variant/60 hover:text-on-surface-variant inline-flex items-center gap-1">
          <span className="material-symbols-outlined text-[14px]">
            data_object
          </span>
          Raw result
        </summary>
        <pre className="text-xs font-mono text-on-surface bg-surface-container-lowest/60 rounded-md p-3 mt-2 overflow-auto max-h-64 leading-relaxed whitespace-pre-wrap break-words">
          {JSON.stringify(result, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function LogResultBody({ result }: { result: Record<string, unknown> }) {
  const workerId =
    typeof result.worker_id === "string" ? result.worker_id : null;
  const count = typeof result.count === "number" ? result.count : null;
  const destination =
    typeof result.destination === "string" ? result.destination : null;
  const logType = typeof result.log_type === "string" ? result.log_type : null;

  // If we recognized headline fields, render them in a compact grid; the
  // rest of the JSON falls into the "Full result" disclosure.
  const hasHeadlines = workerId !== null || count !== null || destination !== null;

  return (
    <div className="space-y-3">
      {hasHeadlines && (
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
          {count !== null && (
            <Field label="Logs sent" value={String(count)} accent />
          )}
          {logType && <Field label="Format" value={logType} mono />}
          {destination && <Field label="Destination" value={destination} mono />}
          {workerId && (
            <Field label="Worker" value={workerId.slice(0, 8) + "…"} mono />
          )}
        </dl>
      )}
      <details className="text-xs">
        <summary className="cursor-pointer text-[10px] uppercase tracking-widest text-on-surface-variant/60 hover:text-on-surface-variant">
          Full result
        </summary>
        <pre className="text-xs font-mono text-on-surface bg-surface-container-lowest/60 rounded-md p-3 mt-2 overflow-auto max-h-64 leading-relaxed whitespace-pre-wrap break-words">
          {JSON.stringify(result, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function Field({
  label,
  value,
  mono = false,
  accent = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
  accent?: boolean;
}) {
  return (
    <div>
      <dt className="text-[9px] uppercase tracking-widest text-outline mb-0.5">
        {label}
      </dt>
      <dd
        className={`${mono ? "font-mono" : "font-medium"} ${accent ? "text-primary font-bold" : "text-on-surface"} truncate`}
        title={value}
      >
        {value}
      </dd>
    </div>
  );
}

// ─── Subcomponents ──────────────────────────────────────────────────────────

function StatCell({
  label,
  value,
  mono = false,
  accent = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
  accent?: boolean;
}) {
  return (
    <div className="rounded-xl p-4" style={glassStyle}>
      <div className="text-[10px] uppercase tracking-widest text-outline mb-1">
        {label}
      </div>
      <div
        className={`text-sm ${mono ? "font-mono" : "font-medium"} ${accent ? "text-primary font-bold" : "text-on-surface"} truncate`}
        title={value}
      >
        {value}
      </div>
    </div>
  );
}

function ErrorPanel({ title, message }: { title: string; message: string }) {
  return (
    <div className="rounded-2xl p-8" style={glassStyle}>
      <h2 className="font-headline text-lg font-bold mb-2">{title}</h2>
      <p className="text-sm text-on-surface-variant">{message}</p>
    </div>
  );
}
