"use client";

/**
 * Live generation rate — what is currently consuming xlog's admission budget.
 *
 * xlog refuses workers that would exceed its ceilings. Before this panel the
 * ceilings were enforced with no way to see current consumption, so an
 * operator hitting a refusal had to read container logs to find out what was
 * using the budget.
 *
 * The rates shown are ADMITTED rates (count/interval as declared at creation),
 * which is what the ceilings are enforced against — not measured throughput.
 * The panel says so, because conflating the two is exactly how a runaway
 * worker stayed invisible: its declared rate was correct and nobody was
 * looking at it.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  listWorkerRates,
  stopWorker,
  formatRate,
  perDay,
  type WorkerRatesSnapshot,
  type WorkerRatesError,
} from "@/lib/api/worker-rates";

const POLL_MS = 5000;

function Meter({
  label,
  value,
  ceiling,
  unit,
  unbounded,
}: {
  label: string;
  value: number | null;
  ceiling: number;
  unit: string;
  unbounded?: boolean;
}) {
  // A disabled ceiling (0) has no bar to fill — show the reading alone rather
  // than a meaningless 0%-of-0 gauge.
  const disabled = ceiling <= 0;
  const pct =
    disabled || value === null || unbounded
      ? 0
      : Math.min(100, (value / ceiling) * 100);
  const hot = pct >= 80;

  return (
    <div className="flex-1 min-w-[150px]">
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="text-[11px] uppercase tracking-wider text-on-surface-variant">
          {label}
        </span>
        <span className="text-[11px] text-on-surface-variant tabular-nums">
          {disabled ? "no limit" : `${ceiling}${unit}`}
        </span>
      </div>
      <div className="text-lg font-medium text-on-surface tabular-nums leading-none mb-2">
        {unbounded ? "unbounded" : value === null ? "—" : value}
        {!unbounded && value !== null && (
          <span className="text-xs text-on-surface-variant ml-1">{unit}</span>
        )}
      </div>
      <div className="h-1 rounded-full bg-surface-container-highest overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{
            width: `${pct}%`,
            // --primary is an HSL TRIPLET ("220 100% 56%") for Tailwind, not a
            // color, so it must be wrapped. --m3-error is a real colour and is
            // theme-aware, unlike a hardcoded hex.
            background: hot ? "var(--m3-error)" : "hsl(var(--primary))",
          }}
        />
      </div>
    </div>
  );
}

export default function GenerationAdmissionPanel() {
  const [snap, setSnap] = useState<WorkerRatesSnapshot | null>(null);
  const [err, setErr] = useState<WorkerRatesError | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [stopping, setStopping] = useState<string | null>(null);

  // In-flight guard. A refresh can take ~27s against a down xlog (retries x
  // the MCP's 5s timeout) while the 5s interval keeps firing, so without this
  // five or six chains overlap and hammer an already-failing service forever.
  const inFlight = useRef(false);

  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const { snapshot, error } = await listWorkerRates();
      setSnap(snapshot);
      setErr(error);
      setLoaded(true);
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(() => {
      // Don't poll a tab nobody is looking at.
      if (!document.hidden) refresh();
    }, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const onStop = async (worker: string) => {
    setStopping(worker);
    await stopWorker(worker);
    await refresh();
    setStopping(null);
  };

  if (!loaded) {
    // Do NOT render nothing here. apiRequest retries a 5xx three times with
    // backoff, and each attempt waits on the MCP's 5s timeout to xlog, so a
    // down xlog leaves this blank for ~27 seconds — long enough for an
    // operator to conclude the panel never shipped and go debug the release.
    return (
      <div
        className="rounded-xl px-4 py-3 mb-6 text-sm text-on-surface-variant"
        style={{ border: "0.5px solid var(--glass-border)" }}
      >
        Loading live generation rate…
      </div>
    );
  }

  // Three distinct failure states — they have different fixes, and a single
  // generic error would send an operator looking in the wrong place.
  if (err) {
    const msg =
      err === "auth_error"
        ? "xlog refused the request. Check that XLOG_API_TOKEN on the agent matches XLOG_API_KEY on xlog."
        : err === "unreachable"
          ? "xlog did not respond. It may be restarting."
          : "xlog returned an unexpected response.";
    return (
      <div
        className="rounded-xl px-4 py-3 mb-6 text-sm text-on-surface-variant flex items-center gap-2"
        style={{ border: "0.5px solid var(--glass-border)" }}
      >
        <span className="material-symbols-outlined text-lg">error</span>
        <span>Live generation rate unavailable — {msg}</span>
      </div>
    );
  }

  if (!snap) return null;

  const running = snap.workers.filter((w) => w.status === "Running");
  const c = snap.ceilings;
  const daily = perDay(
    snap.sustained_events_per_second,
    snap.sustained_events_per_second_unbounded,
  );

  return (
    <div
      className="rounded-xl p-5 mb-6 bg-surface-container"
      style={{ border: "0.5px solid var(--glass-border)" }}
    >
      <div className="flex items-baseline justify-between mb-1">
        <h2 className="text-sm font-medium text-on-surface flex items-center gap-2">
          <span className="material-symbols-outlined text-lg">speed</span>
          Live generation rate
        </h2>
        <span className="text-[11px] text-on-surface-variant">
          {running.length} running
          {snap.pid ? ` · xlog pid ${snap.pid}` : ""}
        </span>
      </div>
      <p className="text-[11px] text-on-surface-variant mb-4 max-w-prose">
        Admitted rates — each worker&rsquo;s declared events per second, which is
        what the ceilings are enforced against. Not measured throughput.
      </p>

      <div className="flex flex-wrap gap-5 mb-5">
        <Meter
          label="Sustained total"
          value={snap.sustained_events_per_second}
          ceiling={c.total_eps}
          unit="/s"
          unbounded={snap.sustained_events_per_second_unbounded}
        />
        <Meter
          label="Workers"
          value={running.length}
          ceiling={c.population}
          unit=""
        />
        <Meter
          label="Bursts"
          value={snap.concurrent_bursts}
          ceiling={c.concurrent_bursts}
          unit=""
        />
      </div>

      {daily && (
        <p className="text-[11px] text-on-surface-variant mb-4 tabular-nums">
          At the current rate that is ~{daily} events/day, sustained.
        </p>
      )}

      {running.length === 0 ? (
        <p className="text-xs text-on-surface-variant py-2">
          No workers running. Generation is idle.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-on-surface-variant">
                <th className="text-left font-medium pb-2 pr-4">Worker</th>
                <th className="text-left font-medium pb-2 pr-4">Admitted rate</th>
                <th className="text-left font-medium pb-2 pr-4">Kind</th>
                <th className="pb-2" />
              </tr>
            </thead>
            <tbody>
              {running.map((w) => {
                const over =
                  c.worker_eps > 0 &&
                  !w.burst &&
                  (w.events_per_second_unbounded ||
                    (w.events_per_second ?? 0) > c.worker_eps);
                return (
                  <tr
                    key={w.worker}
                    className="border-t"
                    style={{ borderColor: "var(--glass-border)" }}
                  >
                    <td className="py-2 pr-4 font-mono text-on-surface">
                      {w.worker}
                    </td>
                    <td
                      className={`py-2 pr-4 tabular-nums ${
                        over ? "text-error" : "text-on-surface"
                      }`}
                    >
                      {formatRate(
                        w.events_per_second,
                        w.events_per_second_unbounded,
                      )}
                      {!w.events_per_second_unbounded && " /s"}
                    </td>
                    <td className="py-2 pr-4 text-on-surface-variant">
                      {w.burst ? "burst" : "sustained"}
                    </td>
                    <td className="py-2 text-right">
                      <button
                        onClick={() => onStop(w.worker)}
                        disabled={stopping === w.worker}
                        className="px-2.5 py-1 rounded-lg text-[11px] text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-50"
                        style={{ border: "0.5px solid var(--glass-border)" }}
                      >
                        {stopping === w.worker ? "Stopping…" : "Stop"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
