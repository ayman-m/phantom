"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { useAuditStream, type AuditEvent } from "@/lib/use-audit-stream";
import { parseQuery, type ParsedQuery } from "@/lib/observability-query";
import { QueryBar } from "@/components/observability/query-bar";
import { listJobs } from "@/lib/api/jobs";

/**
 * Logs page — phantom version.
 *
 * Phantom doesn't ship Loki. The closest equivalent for "structured
 * application logs" is the audit log: every meaningful state change
 * (tool call, scenario started, secret rotated, settings changed,
 * approval resolved) is recorded with a timestamp, actor, action,
 * target, status, and JSON metadata. This page tails it live via
 * the SSE stream and renders one row per event in a familiar
 * tail-the-log feel.
 *
 * Filtering: same Lucene-light syntax as /observability/events. Since
 * the SSE stream doesn't accept server-side filters, we filter on the
 * client over the rolling ~100-event window the hook keeps in memory.
 * Operators looking for older rows narrow further or drop into /events
 * (which paginates the persisted backend).
 *
 * For deeper structured-stdout streaming (think: every container
 * stderr line in real time), wire a Loki collector at the agent's
 * stdout — phantom emits structured-JSON via standard logging.
 * That's an opt-in upgrade; this page works without it.
 */

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

/** Apply a parsed query to one event. AND-semantics across all set
 *  fields. Identical predicate to what the audit endpoint applies
 *  server-side, ported here for the live-tail case. */
function eventMatches(e: AuditEvent, q: ParsedQuery): boolean {
  if (q.action && e.action !== q.action) return false;
  if (q.actor && e.actor !== q.actor) return false;
  if (q.target && e.target !== q.target) return false;
  if (q.target_prefix && !(e.target ?? "").startsWith(q.target_prefix)) return false;
  // The audit_stream payload doesn't carry trigger today — when
  // present, gate on it; when absent, treat trigger filters as
  // "no rows match" so the operator gets honest empty results
  // rather than silent passes.
  const trigger =
    typeof (e as unknown as { trigger?: unknown }).trigger === "string"
      ? ((e as unknown as { trigger?: string }).trigger as string)
      : "";
  if (q.trigger && trigger !== q.trigger) return false;
  if (q.trigger_prefix && !trigger.startsWith(q.trigger_prefix)) return false;
  if (q.since && e.ts < q.since) return false;
  if (q.until && e.ts > q.until) return false;
  return true;
}

export default function LogsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialQuery = searchParams.get("q") ?? "";
  const [queryText, setQueryText] = useState(initialQuery);
  const [committedQuery, setCommittedQuery] = useState(initialQuery);

  const { events, status, error } = useAuditStream(100);

  // Fetch job names once on mount for the autocomplete dynamic source.
  // Cheap fetch (~3-10 jobs typical), no live updates needed for the
  // suggestion list — operators rarely create a job and immediately
  // search for it. If they do, refresh fixes it.
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
  const filteredEvents = useMemo(() => {
    if (!committedQuery) return events;
    return events.filter((e) => eventMatches(e, parsed));
  }, [events, parsed, committedQuery]);

  // URL → state sync (back/forward).
  useEffect(() => {
    const fromUrl = searchParams.get("q") ?? "";
    if (fromUrl !== committedQuery) {
      setCommittedQuery(fromUrl);
      setQueryText(fromUrl);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const commitQuery = (q: string) => {
    setCommittedQuery(q);
    const sp = new URLSearchParams(searchParams.toString());
    if (q) sp.set("q", q);
    else sp.delete("q");
    router.replace(`/observability/logs${sp.toString() ? `?${sp.toString()}` : ""}`);
  };

  const dotClass =
    status === "live" ? "bg-secondary" :
    status === "connecting" ? "bg-tertiary animate-pulse" :
    status === "reconnecting" ? "bg-tertiary" :
    "bg-error";

  return (
    <div className="p-8 max-w-[1400px] mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <span className="material-symbols-outlined text-2xl text-primary">terminal</span>
            <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">Logs</h1>
          </div>
          <p className="text-sm text-on-surface-variant ml-9">
            Live tail of phantom&apos;s structured event log (audit stream). Connection is SSE; reconnects with backoff if dropped.
          </p>
        </div>
        <span className="glass-panel flex items-center gap-2 rounded-full px-3 py-1 text-[11px] font-medium">
          <span className={`h-2 w-2 rounded-full ${dotClass}`} />
          {status}
        </span>
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
        placeholder='target:job:my-job*  action:tool_call  since:2026-05-02'
        dynamicSources={{ jobNames }}
      />

      {error && (
        <div className="rounded-xl border border-error/30 bg-error/10 p-3 text-xs text-error">{error}</div>
      )}

      <div className="rounded-2xl overflow-hidden" style={glassStyle}>
        {/* Column headers — same column widths as the rows below so
            the labels line up regardless of how the row content
            varies in length. Mirrors the /observability/events table
            so operators don't relearn the column order. */}
        <div className="grid grid-cols-[160px_120px_180px_1fr_60px] gap-3 px-5 py-3 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant/70 border-b border-outline-variant/10">
          <div>Timestamp</div>
          <div>Actor</div>
          <div>Action</div>
          <div>Target</div>
          <div>Status</div>
        </div>
        {filteredEvents.length === 0 ? (
          <div className="px-6 py-16 text-center text-sm text-on-surface-variant/60">
            {status === "connecting"
              ? "Connecting to log stream..."
              : committedQuery
                ? `No events match in the live window (${events.length} buffered). Try /observability/events for paginated history.`
                : "Waiting for events. Use the chat or trigger a job to populate."}
          </div>
        ) : (
          <ul className="divide-y divide-outline-variant/10 font-mono text-[11px] max-h-[70vh] overflow-y-auto custom-scrollbar">
            {filteredEvents.map((e: AuditEvent) => (
              <li key={String(e.id)} className="grid grid-cols-[160px_120px_180px_1fr_60px] gap-3 px-5 py-2 hover:bg-white/5 transition-colors">
                <span className="text-on-surface-variant/60">{e.ts}</span>
                <span className="text-on-surface-variant/80 truncate">{e.actor ?? "—"}</span>
                <span className="text-primary font-semibold truncate">{e.action}</span>
                <span className="text-on-surface-variant/70 truncate">{e.target ?? ""}</span>
                <span className={
                  e.status === "ok" || e.status === "success" ? "text-secondary" :
                  e.status === "failed" || e.status === "denied" ? "text-error" :
                  "text-on-surface-variant/50"
                }>
                  {e.status ?? "—"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {committedQuery && events.length > 0 && (
        <p className="text-[11px] text-on-surface-variant/50 text-right">
          Showing {filteredEvents.length} of {events.length} buffered events.
          For older rows, open{" "}
          <a
            href={`/observability/events${committedQuery ? `?q=${encodeURIComponent(committedQuery)}` : ""}`}
            className="text-primary hover:underline"
          >
            paginated history
          </a>
          .
        </p>
      )}
    </div>
  );
}
