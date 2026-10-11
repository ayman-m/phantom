"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import {
  parseQuery,
  parsedQueryToParams,
} from "@/lib/observability-query";
import { QueryBar } from "@/components/observability/query-bar";
import { listJobs } from "@/lib/api/jobs";

/**
 * Traces page — phantom version.
 *
 * Until phantom ships a real OTel collector + span ring buffer, this
 * page is a "spans-flavored" view over the audit log. Filterable by
 * the same Lucene-light syntax as /observability/{events,logs}; rows
 * with duration_ms populated render as spans, rows without are still
 * shown but with "—" duration (they're discrete events that happened
 * inside the trigger window).
 *
 * Why no default `action=tool_call` filter (anymore): only connector-
 * wrapped tools emit `action=tool_call` audits — see
 * connector_loader.py:_wrap_with_instance. Builtin tools that the
 * agent dispatches during a chat-action job (instances_list,
 * memory_search, jobs_list, phantom_get_*, …) don't go through that
 * wrapper and aren't recorded under tool_call. The user-reported
 * symptom: "View this run's traces" from a job that called
 * `instances_list` returned 0 entries because the action filter
 * excluded everything the run actually did. Dropping the default
 * shows every audited operation in the run's window — closer to
 * what an operator means by "what did this run do?"
 */

interface AuditEvent {
  id: number | string;
  ts: string;
  actor?: string;
  action: string;
  target?: string;
  status?: string;
  duration_ms?: number | null;
}

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

export default function TracesPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialQuery = searchParams.get("q") ?? "";
  const [queryText, setQueryText] = useState(initialQuery);
  const [committedQuery, setCommittedQuery] = useState(initialQuery);

  const [recent, setRecent] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);

  // Fetch job names once for the query-bar autocomplete dynamic
  // source. Same pattern as /observability/logs.
  const [jobNames, setJobNames] = useState<string[]>([]);
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const r = await listJobs();
      if (!cancelled && r.ok) {
        setJobNames(r.data.map((j) => j.name));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const parsed = useMemo(() => parseQuery(committedQuery), [committedQuery]);

  useEffect(() => {
    const fromUrl = searchParams.get("q") ?? "";
    if (fromUrl !== committedQuery) {
      setCommittedQuery(fromUrl);
      setQueryText(fromUrl);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const params = parsedQueryToParams(parsed);
      params.set("limit", "50");
      const r = await fetch(`/api/agent/audit?${params.toString()}`, {
        cache: "no-store",
      });
      if (r.ok) {
        const data = (await r.json()) as { events?: AuditEvent[] };
        setRecent(data.events ?? []);
      }
    } catch {
      // empty — UI shows the no-spans message when the array stays empty
    } finally {
      setLoading(false);
    }
  }, [parsed]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const commitQuery = (q: string) => {
    setCommittedQuery(q);
    const sp = new URLSearchParams(searchParams.toString());
    if (q) sp.set("q", q);
    else sp.delete("q");
    router.replace(`/observability/traces${sp.toString() ? `?${sp.toString()}` : ""}`);
  };

  // Stats — the "with duration" count is the closest thing to
  // "actual spans"; the rest are discrete events that happened in
  // the same window.
  const withDuration = recent.filter(
    (e) => typeof e.duration_ms === "number" && e.duration_ms > 0,
  );

  return (
    <div className="p-8 max-w-[1400px] mx-auto space-y-6">
      <div>
        <div className="flex items-center gap-3 mb-1">
          <span className="material-symbols-outlined text-2xl text-primary">timeline</span>
          <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">Traces</h1>
        </div>
        <p className="text-sm text-on-surface-variant ml-9">
          Spans-flavored view over the audit log. Rows with measurable duration are real spans; the rest are discrete events that happened in the same window.
        </p>
      </div>

      <QueryBar
        value={queryText}
        onChange={setQueryText}
        onSubmit={() => commitQuery(queryText.trim())}
        onClear={() => {
          setQueryText("");
          commitQuery("");
        }}
        parsed={parsed}
        placeholder='trigger:job:my-job*  target:tool:xsiam_*  since:2026-05-02'
        dynamicSources={{ jobNames }}
      />

      <section className="rounded-2xl overflow-hidden" style={glassStyle}>
        <div className="px-5 py-3 flex items-center justify-between border-b border-outline-variant/10">
          <h2 className="font-headline text-sm font-bold text-on-surface flex items-center gap-2">
            <span className="material-symbols-outlined text-primary">build</span>
            Spans
          </h2>
          <span className="text-xs text-on-surface-variant/60 font-mono">
            {recent.length} entries
            {withDuration.length > 0 && (
              <span className="text-secondary/80">
                {" "}· {withDuration.length} with duration
              </span>
            )}
          </span>
        </div>
        {/* Column headers — same 12-column grid as the rows below.
            Stays out of the empty-state branch so the operator always
            sees what shape the data takes, even when filtered down
            to zero rows. */}
        <div className="grid grid-cols-12 gap-2 px-5 py-3 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant/70 border-b border-outline-variant/10">
          <div className="col-span-2">Timestamp</div>
          <div className="col-span-2">Action</div>
          <div className="col-span-5">Target</div>
          <div className="col-span-1">Status</div>
          <div className="col-span-2 text-right">Duration</div>
        </div>
        {loading ? (
          <div className="px-5 py-12 text-center text-sm text-on-surface-variant/60">Loading...</div>
        ) : recent.length === 0 ? (
          <div className="px-5 py-12 text-center text-sm text-on-surface-variant/60">
            {committedQuery
              ? "No spans match the filter."
              : "No spans yet. Trigger a chat or fire a job to populate."}
          </div>
        ) : (
          <ul className="divide-y divide-outline-variant/10">
            {recent.map((e) => (
              <li
                key={String(e.id)}
                className="grid grid-cols-12 gap-2 px-5 py-2.5 text-xs items-center hover:bg-white/5 transition-colors"
              >
                <div className="col-span-2 font-mono text-[11px] text-on-surface-variant/80">
                  {e.ts}
                </div>
                <div className="col-span-2 font-mono font-semibold text-primary truncate">
                  {e.action}
                </div>
                <div className="col-span-5 font-mono text-on-surface-variant truncate">
                  {e.target ?? "—"}
                </div>
                <div className="col-span-1">
                  <span
                    className={
                      e.status === "ok" || e.status === "success"
                        ? "rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-secondary/15 text-secondary"
                        : e.status === "failed" || e.status === "failure"
                          ? "rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-error/15 text-error"
                          : "rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-surface-container-high/50 text-on-surface-variant"
                    }
                  >
                    {e.status ?? "—"}
                  </span>
                </div>
                <div
                  className={`col-span-2 text-right font-mono text-[11px] ${
                    typeof e.duration_ms === "number" && e.duration_ms > 0
                      ? "text-on-surface"
                      : "text-on-surface-variant/40"
                  }`}
                >
                  {typeof e.duration_ms === "number" && e.duration_ms > 0
                    ? `${e.duration_ms}ms`
                    : "—"}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
