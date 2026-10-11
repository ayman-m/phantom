"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { cn } from "@/lib/utils";
import {
  parseQuery,
  parsedQueryToParams,
} from "@/lib/observability-query";
import { QueryBar } from "@/components/observability/query-bar";
import { listJobs } from "@/lib/api/jobs";

/**
 * Events page — paginated query against the phantom MCP's audit log.
 * Lives under /observability with the rest of the observability
 * surfaces. The live (SSE-streamed) version is at /activity.
 *
 * Each row is one phantom audit_events row (tool_call, simulation_*,
 * setup_completed, settings_changed, …). Filters via a single
 * Lucene-light query bar — see lib/observability-query.ts for syntax.
 * URL-syncs `?q=...` so deep-links from /jobs/[id] (and operator
 * bookmarks) survive a refresh.
 */

interface AuditEvent {
  id: number | string;
  ts: string;
  actor?: string;
  action: string;
  target?: string;
  status?: string;
  duration_ms?: number | null;
  metadata?: Record<string, unknown>;
}

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

const PAGE_SIZE = 50;

export default function EventsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // The query bar's text. Initialized from `?q=...` so deep-links land
  // pre-filtered. We ALSO keep a "committed" form of the same string
  // — the parser only runs on submit (Enter / blur) so typing doesn't
  // refire the audit fetch on every keystroke.
  const initialQuery = searchParams.get("q") ?? "";
  const [queryText, setQueryText] = useState(initialQuery);
  const [committedQuery, setCommittedQuery] = useState(initialQuery);

  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);

  // Job names for autocomplete dynamic source. Same pattern as
  // /observability/{logs,traces} — fetched once, passed through to
  // the QueryBar so target:job:my-job and trigger:job:my-job
  // suggestions are live.
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
  const [error, setError] = useState<string | null>(null);

  const parsed = useMemo(() => parseQuery(committedQuery), [committedQuery]);

  // Keep state synced with URL changes (e.g. when the operator hits
  // back/forward, or another in-app link sets ?q=...).
  useEffect(() => {
    const fromUrl = searchParams.get("q") ?? "";
    if (fromUrl !== committedQuery) {
      setCommittedQuery(fromUrl);
      setQueryText(fromUrl);
      setOffset(0);
    }
    // We intentionally don't depend on `committedQuery` here — that
    // would create a loop where committing updates the URL, the URL
    // change re-fires this effect, etc.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    const params = parsedQueryToParams(parsed);
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String(offset));
    try {
      const r = await fetch(`/api/agent/audit?${params.toString()}`, {
        cache: "no-store",
      });
      if (!r.ok) throw new Error(`audit fetch ${r.status}`);
      const data = (await r.json()) as { events?: AuditEvent[]; count?: number };
      setEvents(data.events ?? []);
      setTotal(data.count ?? 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [offset, parsed]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const commitQuery = useCallback(
    (q: string) => {
      setCommittedQuery(q);
      setOffset(0);
      // Reflect in URL so the page is shareable. `replace` not `push`
      // because successive refinements shouldn't clutter history.
      const sp = new URLSearchParams(searchParams.toString());
      if (q) sp.set("q", q);
      else sp.delete("q");
      router.replace(`/observability/events${sp.toString() ? `?${sp.toString()}` : ""}`);
    },
    [router, searchParams],
  );

  const clearQuery = useCallback(() => {
    setQueryText("");
    commitQuery("");
  }, [commitQuery]);

  return (
    <div className="p-8 max-w-[1400px] mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <span className="material-symbols-outlined text-2xl text-primary">policy</span>
            <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
              Audit events
            </h1>
          </div>
          <p className="text-sm text-on-surface-variant ml-9">
            Phantom audit log — every tool call, scenario run, approval decision, settings change. Append-only.
            For the high-signal runtime telemetry stream (<code>rt.tool.failed</code>,{" "}
            <code>rt.simulation.*</code>, etc.), see{" "}
            <a className="text-primary hover:underline" href="/observability/runtime-events">
              /observability/runtime-events
            </a>.
          </p>
        </div>
        <button
          onClick={() => void refresh()}
          disabled={loading}
          className="glass-panel px-4 py-2 rounded-xl text-xs font-medium text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-50"
        >
          <span className="material-symbols-outlined text-base align-middle mr-1">refresh</span>
          Refresh
        </button>
      </div>

      <QueryBar
        value={queryText}
        onChange={setQueryText}
        onSubmit={() => commitQuery(queryText.trim())}
        onClear={clearQuery}
        parsed={parsed}
        dynamicSources={{ jobNames }}
      />

      {/* Pre-fab quick-filter chips for the
          chat-route audit families. Click pre-populates the
          query bar AND commits the filter, so a one-click drill into
          "show me all compactions in the last hour" works without
          knowing the Lucene syntax. */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[10px] font-label uppercase tracking-wider text-on-surface-variant/60 mr-1">
          Quick filters
        </span>
        {(
          [
            {
              label: "Compactions",
              icon: "compress",
              query: "action:chat_compaction_*",
            },
            {
              label: "Context warnings",
              icon: "warning",
              query: "action:chat_context_warning",
            },
            {
              label: "Cache hits",
              icon: "bolt",
              query: "action:chat_cache_hit",
            },
            {
              label: "Failed compactions",
              icon: "error",
              query: "action:chat_compaction_failed",
            },
            {
              label: "Tool calls",
              icon: "build",
              query: "action:tool_call",
            },
            // Action-type chips for the audit surfaces. Each one corresponds to a specific behavior
            // operators want to audit at-a-glance.
            {
              label: "Tool denied by policy",
              icon: "block",
              query: "action:tool_denied_by_policy",
            },
            {
              label: "Tool output truncated",
              icon: "content_cut",
              query: "action:tool_output_truncated",
            },
            {
              label: "Session forked",
              icon: "call_split",
              query: "action:session_forked",
            },
            {
              label: "Hook dispatched",
              icon: "webhook",
              query: "action:hook_dispatched",
            },
            {
              label: "Memory stored",
              icon: "psychology",
              query: "action:memory_stored",
            },
            // Boot refresh of installed data sources from a newer
            // bundled schema; lists what was refreshed and what was skipped.
            {
              label: "Data source refreshes",
              icon: "sync",
              query: "action:data_sources_refreshed",
            },
          ] as const
        ).map((chip) => {
          const active = queryText.trim() === chip.query;
          return (
            <button
              key={chip.label}
              type="button"
              onClick={() => {
                setQueryText(chip.query);
                commitQuery(chip.query);
              }}
              className={cn(
                "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] transition-colors",
                active
                  ? "bg-primary/15 text-primary border border-primary/30"
                  : "bg-white/5 text-on-surface-variant hover:text-on-surface hover:bg-white/10 border border-transparent",
              )}
              aria-pressed={active}
            >
              <span
                className="material-symbols-outlined text-[14px]"
                aria-hidden="true"
              >
                {chip.icon}
              </span>
              {chip.label}
            </button>
          );
        })}
      </div>


      {/* Error */}
      {error && (
        <div className="rounded-xl border border-error/30 bg-error/10 p-3 text-xs text-error">
          {error}
        </div>
      )}

      {/* Table */}
      <div className="rounded-2xl overflow-hidden" style={glassStyle}>
        <div className="grid grid-cols-12 gap-2 px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant/70 border-b border-outline-variant/10">
          <div className="col-span-2">Timestamp</div>
          <div className="col-span-2">Actor</div>
          <div className="col-span-2">Action</div>
          <div className="col-span-3">Target</div>
          <div className="col-span-1">Status</div>
          <div className="col-span-1 text-right">Duration</div>
          <div className="col-span-1 text-right">Meta</div>
        </div>
        {loading ? (
          <div className="px-4 py-12 text-center text-sm text-on-surface-variant/60">Loading…</div>
        ) : events.length === 0 ? (
          <div className="px-4 py-12 text-center text-sm text-on-surface-variant/60">
            No events match the filter.
          </div>
        ) : (
          <ul className="divide-y divide-outline-variant/10">
            {events.map((e) => (
              <li key={String(e.id)} className="grid grid-cols-12 gap-2 px-4 py-2.5 text-xs items-center hover:bg-white/5 transition-colors">
                <div className="col-span-2 font-mono text-[11px] text-on-surface-variant/80">{e.ts}</div>
                <div className="col-span-2 truncate">{e.actor ?? "—"}</div>
                <div className="col-span-2 font-mono font-semibold text-primary truncate">{e.action}</div>
                <div className="col-span-3 font-mono text-[11px] text-on-surface-variant truncate">{e.target ?? "—"}</div>
                <div className="col-span-1">
                  <span className={cn(
                    "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
                    e.status === "success" || e.status === "ok" ? "bg-secondary/15 text-secondary" :
                    e.status === "failed" || e.status === "denied" ? "bg-error/15 text-error" :
                    "bg-surface-container-high/50 text-on-surface-variant"
                  )}>
                    {e.status ?? "—"}
                  </span>
                </div>
                <div className="col-span-1 text-right font-mono text-[11px] text-on-surface-variant/60">
                  {e.duration_ms ? `${e.duration_ms}ms` : "—"}
                </div>
                <div className="col-span-1 text-right">
                  {e.metadata && Object.keys(e.metadata).length > 0 ? (
                    <details className="inline-block">
                      <summary className="cursor-pointer text-[11px] text-on-surface-variant/60 hover:text-on-surface">
                        view
                      </summary>
                      <pre className="absolute right-8 mt-1 max-w-md overflow-auto rounded-lg p-2 text-[10px] font-mono text-on-surface-variant z-10" style={glassStyle}>
                        {JSON.stringify(e.metadata, null, 2)}
                      </pre>
                    </details>
                  ) : "—"}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between text-xs text-on-surface-variant/60">
        <div>
          Showing {events.length} of {total} events (page {Math.floor(offset / PAGE_SIZE) + 1})
        </div>
        <div className="flex gap-2">
          <button
            disabled={offset === 0 || loading}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            className="glass-panel px-3 py-1.5 rounded-lg text-xs font-medium hover:text-on-surface disabled:opacity-40"
          >
            ← Previous
          </button>
          <button
            disabled={events.length < PAGE_SIZE || loading}
            onClick={() => setOffset(offset + PAGE_SIZE)}
            className="glass-panel px-3 py-1.5 rounded-lg text-xs font-medium hover:text-on-surface disabled:opacity-40"
          >
            Next →
          </button>
        </div>
      </div>
    </div>
  );
}

