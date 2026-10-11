"use client";

/**
 * RunsExportButton — small client-side download button for run history.
 *
 * Lives at the top of the "Recent runs" section on the job detail page.
 * Same CSV export the JobActions kebab uses, surfaced as a primary
 * affordance because the operator's most common ask is "give me a
 * spreadsheet of recent runs for this job." Disabled state when there
 * are no runs to export — keeps the affordance visible (so the
 * operator knows the option exists) without misleading them.
 */

import { useCallback } from "react";

import type { Job, JobRun } from "@/lib/api/jobs";

interface Props {
  job: Job;
  runs: JobRun[];
}

export function RunsExportButton({ job, runs }: Props) {
  const enabled = runs.length > 0;

  const handleClick = useCallback(() => {
    if (!enabled) return;
    const csvCell = (raw: unknown): string => {
      const s = raw === null || raw === undefined ? "" : String(raw);
      // RFC 4180: quote anything containing the delimiter, quote, or
      // newline; double up internal quotes.
      if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
      return s;
    };
    const header = [
      "id",
      "fired_at",
      "finished_at",
      "status",
      "duration_ms",
      "trigger",
      "error",
      "result_summary",
    ];
    const rows = runs.map((r) => [
      r.id,
      r.fired_at,
      r.finished_at ?? "",
      r.status,
      r.duration_ms ?? "",
      r.trigger,
      r.error ?? "",
      r.result ? JSON.stringify(r.result).slice(0, 240) : "",
    ]);
    const csv =
      [header, ...rows]
        .map((row) => row.map(csvCell).join(","))
        .join("\n") + "\n";
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${job.name}-runs.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, [enabled, runs, job.name]);

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={!enabled}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-outline-variant/40 text-on-surface-variant hover:bg-white/5 hover:text-on-surface transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      title={enabled ? "Download run history as CSV" : "No runs yet"}
    >
      <span className="material-symbols-outlined text-[14px]">download</span>
      Export CSV
    </button>
  );
}
