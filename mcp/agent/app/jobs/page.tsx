/**
 * /jobs — server component that fetches the snapshot, then hands off
 * to <JobsListClient> for filter + sort UX. The summary bar (Total /
 * Active / Paused) is computed server-side from the full list so it's
 * present in the initial HTML.
 */

import { cookies } from "next/headers";
import Link from "next/link";

import { RetryButton } from "@/components/retry-button";
import { getToken } from "@/lib/auth";
import { SESSION_COOKIE_NAME } from "@/lib/auth-defaults";
import { listJobs } from "@/lib/api/jobs";
import type { Job } from "@/lib/api/jobs";
import { listAgents } from "@/lib/api/agents";
import { ImportJobButton } from "./import-button";
import { JobsListClient } from "./jobs-list-client";

const glassStyle = {
  background: "var(--glass-bg)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

/** Lightweight effectiveState for the server-side summary counts.
 *  Mirrors the client-side helper in jobs-list-client.tsx — duplicated
 *  rather than shared because pulling a "use client" file's exports
 *  into a server file forces the client boundary to bleed. Keep the
 *  copy small and deliberate. */
function isActiveServerSide(job: Job): boolean {
  if (
    job.kind === "JOB_KIND_ONCE" &&
    job.state === "JOB_STATE_ACTIVE" &&
    job.last_run_at
  ) {
    const nextRun = job.next_run_at ? new Date(job.next_run_at) : null;
    if (!nextRun || isNaN(nextRun.getTime()) || nextRun.getTime() < Date.now()) {
      return false; // completed
    }
  }
  return job.state === "JOB_STATE_ACTIVE";
}

type YamlIssue = {
  path: string;
  basename: string;
  error: string;
  mtime: number;
};

async function fetchYamlIssues(token: string | undefined): Promise<YamlIssue[]> {
  // Surface YAML-load failures inline on /jobs rather than
  // burying them in docker compose logs. Read-only fetch — failure
  // here is non-fatal (we just don't show the banner).
  if (!token) return [];
  try {
    const r = await fetch("http://localhost:3000/api/agent/jobs/yaml-issues", {
      headers: { cookie: `${SESSION_COOKIE_NAME}=${token}` },
      cache: "no-store",
    });
    if (!r.ok) return [];
    const data = await r.json();
    return Array.isArray(data.issues) ? data.issues : [];
  } catch {
    return [];
  }
}

export default async function JobsPage() {
  const cookieStore = await cookies();
  const token = getToken(cookieStore);

  const [jobsResult, agentsResult, yamlIssues] = await Promise.all([
    listJobs({ sessionToken: token }),
    listAgents({ sessionToken: token }),
    fetchYamlIssues(token),
  ]);

  const jobs: Job[] = jobsResult.ok ? jobsResult.data : [];
  const error = jobsResult.ok ? null : jobsResult.error;

  const agentNameMap: Record<string, string> = {};
  if (agentsResult.ok) {
    for (const agent of agentsResult.data) {
      agentNameMap[agent.agent_id] = agent.name;
    }
  }

  const activeCount = jobs.filter(isActiveServerSide).length;
  const pausedCount = jobs.filter((j) => j.state === "JOB_STATE_PAUSED").length;

  return (
    <div className="p-8 pb-32 max-w-[1400px] mx-auto">
      <header className="mb-8">
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <span className="material-symbols-outlined text-2xl text-primary">
                schedule
              </span>
              <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
                Jobs
              </h1>
            </div>
            <p className="text-sm text-on-surface-variant ml-9">
              Scheduled automation tasks and triggers
            </p>
          </div>
          {/*
            Two creation paths coexist by design:
              1. Manifest-declared (source='manifest') — defined in
                 bundles/spark/manifest.yaml:jobs[]. Reconciled at boot.
                 Edits here are reverted; the manifest is source of truth.
              2. Runtime (source='runtime') — created via this button.
                 Survive boot reconciliation untouched. Operator-owned.
          */}
          <div className="flex items-center gap-3">
            {/* Import sits alongside Create. Operator workflow:
                export from one deployment → import into another (or
                back into a fresh local). Run history is NOT carried
                across — definition only. */}
            <ImportJobButton />
            <Link
              href="/jobs/new"
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-on-surface text-sm font-bold shadow-lg active:scale-95 transition-transform hover:brightness-110"
              style={{
                background: "linear-gradient(135deg, #1963B3 0%, #2D8DF0 100%)",
              }}
            >
              <span className="material-symbols-outlined text-lg">add</span>
              Create Job
            </Link>
          </div>
        </div>
      </header>

      {/* YAML-load issues banner. Renders only when one or
          more files in /app/data/jobs/*.yaml failed to load at boot.
          Operator can either fix the YAML in place (docker exec
          phantom_agent vi /app/data/jobs/<basename>) or delete the
          file. Surfacing these failures in the UI follows the platform's
          "issues belong in /observability + UI" contract. */}
      {yamlIssues.length > 0 && (
        <div
          className="mb-6 rounded-xl p-4"
          style={{
            background: "rgba(245, 158, 11, 0.08)",
            border: "1px solid rgba(245, 158, 11, 0.25)",
          }}
        >
          <div className="flex items-start gap-3">
            <span className="material-symbols-outlined text-yellow-400 mt-0.5">
              warning
            </span>
            <div className="flex-1 min-w-0">
              <div className="font-headline text-sm font-bold text-on-surface mb-1">
                {yamlIssues.length} job YAML file
                {yamlIssues.length !== 1 ? "s" : ""} failed to load at boot
              </div>
              <div className="text-xs text-on-surface-variant mb-2">
                These files in <code className="font-mono">/app/data/jobs/</code>{" "}
                couldn&apos;t be parsed or had invalid action types. Fix the
                YAML in place or delete the file if it&apos;s stale.
              </div>
              <details className="text-xs">
                <summary className="cursor-pointer text-yellow-400 font-medium select-none hover:text-yellow-300">
                  Show {yamlIssues.length}{" "}
                  {yamlIssues.length === 1 ? "issue" : "issues"}
                </summary>
                <div className="mt-2 space-y-1 max-h-56 overflow-y-auto rounded-md bg-surface-container-lowest/50 p-2 font-mono">
                  {yamlIssues.map((issue, idx) => (
                    <div
                      key={idx}
                      className="flex flex-col py-1 px-2 rounded hover:bg-surface-container-lowest"
                    >
                      <div className="text-on-surface font-semibold truncate">
                        {issue.basename}
                      </div>
                      <div
                        className="text-on-surface-variant truncate"
                        title={issue.error}
                      >
                        {issue.error}
                      </div>
                    </div>
                  ))}
                </div>
              </details>
            </div>
          </div>
        </div>
      )}

      {/* Summary Bar */}
      <div className="flex gap-4 mb-8">
        <SummaryCard
          icon="work"
          iconBg="bg-primary-container/20"
          iconColor="text-primary"
          label="Total Jobs"
          value={`${jobs.length} Job${jobs.length !== 1 ? "s" : ""}`}
        />
        <SummaryCard
          icon="play_circle"
          iconBg="bg-secondary-container/20"
          iconColor="text-secondary"
          label="Active"
          value={`${activeCount} Active`}
        />
        <SummaryCard
          icon="pause_circle"
          iconBg="bg-yellow-500/10"
          iconColor="text-yellow-400"
          label="Paused"
          value={`${pausedCount} Paused`}
        />
      </div>

      {/* Content */}
      {error ? (
        <div className="rounded-2xl p-8" style={glassStyle}>
          <h2 className="font-headline text-lg font-bold mb-2">
            Unable to load jobs
          </h2>
          <div className="flex flex-col gap-4 text-sm text-on-surface-variant sm:flex-row sm:items-center sm:justify-between">
            <p>{error.message}</p>
            <RetryButton />
          </div>
        </div>
      ) : jobs.length === 0 ? (
        <div
          className="rounded-2xl p-12 flex flex-col items-center gap-3 text-center"
          style={glassStyle}
        >
          <span className="material-symbols-outlined text-4xl text-on-surface-variant">
            schedule
          </span>
          <p className="text-base font-medium">No jobs configured</p>
          <p className="max-w-xl text-sm text-on-surface-variant">
            Automation jobs let you run agents on a schedule or trigger them
            manually. Create your first job to get started.
          </p>
        </div>
      ) : (
        <JobsListClient jobs={jobs} agentNameMap={agentNameMap} />
      )}
    </div>
  );
}

// ─── Summary Card ────────────────────────────────────────────────────────────

function SummaryCard({
  icon,
  iconBg,
  iconColor,
  label,
  value,
}: {
  icon: string;
  iconBg: string;
  iconColor: string;
  label: string;
  value: string;
}) {
  return (
    <div
      className="flex-1 p-6 rounded-2xl flex items-center gap-4 hover:shadow-[0_0_20px_rgba(25,99,179,0.1)] transition-shadow"
      style={glassStyle}
    >
      <div
        className={`h-12 w-12 rounded-xl ${iconBg} flex items-center justify-center ${iconColor}`}
      >
        <span className="material-symbols-outlined">{icon}</span>
      </div>
      <div>
        <p className="text-[10px] uppercase tracking-wider text-outline">
          {label}
        </p>
        <p className="text-2xl font-bold font-headline">{value}</p>
      </div>
    </div>
  );
}
