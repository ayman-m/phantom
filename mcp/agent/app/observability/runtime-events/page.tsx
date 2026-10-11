"use client";

/**
 * Runtime events page — UI surface for the manifest-declared
 * observability event feed (rt.simulation.*, rt.caldera.*,
 * rt.coverage.*, rt.validation.*, rt.tool.failed).
 *
 * NOT to be confused with /observability/events, which queries the
 * audit log. They overlap on tool failures but exist for
 * different consumers — audit is forensic detail, runtime events are
 * the high-signal stream you wire alerts/dashboards to.
 *
 * This page is a minimal-viable surface so the recorded events can
 * be inspected.
 *
 * Future polish:
 *   * Filter by event name (currently shows all)
 *   * Live tail via SSE (audit/stream pattern)
 *   * Payload field-explorer (the `payload` shape is per-event-name)
 */

import { useEffect, useState, useCallback } from "react";

interface RuntimeEvent {
  id: string;
  ts: string;
  event_name: string;
  actor?: string | null;
  payload?: Record<string, unknown>;
}

interface SummaryRow {
  event_name: string;
  count: number;
}

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

export default function RuntimeEventsPage() {
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [declared, setDeclared] = useState<string[]>([]);
  const [summary, setSummary] = useState<SummaryRow[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = filter ? `?event=${encodeURIComponent(filter)}&limit=100` : "?limit=100";
      const [eventsRes, summaryRes] = await Promise.all([
        fetch(`/api/agent/observability/events${qs}`, { cache: "no-store" }),
        fetch(`/api/agent/observability/events/summary`, { cache: "no-store" }),
      ]);
      if (!eventsRes.ok) throw new Error(`events fetch ${eventsRes.status}`);
      const eventsBody = await eventsRes.json();
      setEvents(eventsBody.events ?? []);
      setDeclared(eventsBody.declared_events ?? []);
      if (summaryRes.ok) {
        const summaryBody = await summaryRes.json();
        // Endpoint returns { counts: {event_name: count}, declared_events: [...] }
        const counts = (summaryBody.counts ?? {}) as Record<string, number>;
        setSummary(
          Object.entries(counts)
            .map(([event_name, count]) => ({ event_name, count }))
            .sort((a, b) => b.count - a.count),
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "fetch failed");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-8 space-y-6">
        <header>
          <div className="flex items-center gap-3 mb-1">
            <span className="material-symbols-outlined text-2xl text-primary">
              sensors
            </span>
            <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
              Runtime events
            </h1>
          </div>
          <p className="text-sm text-on-surface-variant ml-9">
            High-signal event stream — for forensic detail see <a className="text-primary hover:underline" href="/observability/events">/observability/events</a>.
          </p>
        </header>

      {/* Summary cards */}
      <section className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        {summary.length === 0 ? (
          <div className="col-span-full rounded-xl p-4 text-sm text-on-surface-variant" style={glassStyle}>
            No runtime events recorded yet.
          </div>
        ) : (
          summary.map((s) => (
            <button
              key={s.event_name}
              type="button"
              onClick={() => setFilter(s.event_name === filter ? "" : s.event_name)}
              className={`text-left rounded-xl p-3 transition-colors ${
                filter === s.event_name
                  ? "bg-primary-container/30 border border-primary/40"
                  : "bg-white/5 border border-white/10 hover:border-white/20"
              }`}
              style={filter === s.event_name ? undefined : glassStyle}
            >
              <p className="font-mono text-[10px] text-on-surface-variant truncate" title={s.event_name}>
                {s.event_name}
              </p>
              <p className="font-headline text-2xl font-bold text-on-surface">{s.count}</p>
            </button>
          ))
        )}
      </section>

      {/* Filter bar */}
      <div className="flex items-center gap-3">
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter by event name (e.g. rt.tool.failed) — empty = all"
          list="declared-events"
          className="flex-1 bg-surface-container-highest border-none rounded-xl py-2.5 px-4 text-sm text-on-surface placeholder:text-on-surface-variant/40 focus:ring-1 focus:ring-primary font-mono"
        />
        <datalist id="declared-events">
          {declared.map((d) => <option key={d} value={d} />)}
        </datalist>
        <button
          type="button"
          onClick={refresh}
          disabled={loading}
          className="px-4 py-2.5 rounded-xl bg-primary/15 border border-primary/30 text-primary text-sm font-medium hover:bg-primary/25 disabled:opacity-50"
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="rounded-xl bg-error-container/20 border border-error/30 px-4 py-3 text-sm text-error">
          {error}
        </div>
      )}

      {/* Events list */}
      <section className="rounded-2xl overflow-hidden" style={glassStyle}>
        {events.length === 0 ? (
          <div className="p-6 text-sm text-on-surface-variant text-center">
            {filter ? `No events for "${filter}"` : "No events recorded"}
          </div>
        ) : (
          <table className="w-full text-xs">
            <thead className="bg-white/5 text-on-surface-variant font-label uppercase tracking-widest">
              <tr>
                <th className="text-left px-4 py-2 w-44">When</th>
                <th className="text-left px-4 py-2 w-64">Event</th>
                <th className="text-left px-4 py-2 w-32">Actor</th>
                <th className="text-left px-4 py-2">Payload</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id} className="border-t border-white/5 hover:bg-white/5">
                  <td className="px-4 py-2 font-mono text-on-surface-variant">
                    {new Date(e.ts).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 font-mono text-tertiary">{e.event_name}</td>
                  <td className="px-4 py-2 text-on-surface-variant">{e.actor || "—"}</td>
                  <td className="px-4 py-2 font-mono text-on-surface text-[10px]">
                    {Object.keys(e.payload ?? {}).length === 0
                      ? "—"
                      : JSON.stringify(e.payload).slice(0, 200)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      </div>
    </div>
  );
}
