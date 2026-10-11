"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import type { LogLevel, ParsedLogLine } from "@/lib/observability/transform";

/**
 * Live-tail logs table for the Logs tab.
 *
 * Receives the initial 50-100 lines from the server component as a
 * prop, then polls /api/observability/logs/recent every 2s to fetch
 * any newer lines and prepends them. The user can pause/resume
 * tailing — when paused, the table is frozen and the polling stops.
 *
 * The "live" indicator pulses while polling and goes grey when paused.
 *
 * The table rendering lives here (rather than the server component)
 * because the row list needs to be stateful — server-rendered HTML
 * can't be mutated from outside React.
 */

const POLL_INTERVAL_MS = 2000;
const MAX_LINES = 500;

type LineWithTs = ParsedLogLine & { tsNano: string };

type FetchResponse = {
  ok: true;
  lines: LineWithTs[];
  fetchedAt: number;
} | {
  ok: false;
  error: { code: string; message: string; retryable: boolean };
};

type Props = {
  initialLines: LineWithTs[];
  services: string[];
  levels: LogLevel[];
};

export function LogsLiveTail({ initialLines, services, levels }: Props) {
  const [lines, setLines] = useState<LineWithTs[]>(initialLines);
  const [paused, setPaused] = useState(false);
  const [error, setError] = useState<string | undefined>(undefined);
  const [lastFetched, setLastFetched] = useState<number | undefined>(undefined);
  // Use a ref for the cursor so the polling closure always reads the
  // freshest value without being re-created on every state update.
  const cursorRef = useRef<string>(initialLines[0]?.tsNano ?? "0");

  // Hoist filter strings out of the dependency array so the linter
  // can see they're stable primitives.
  const servicesKey = services.join(",");
  const levelsKey = levels.join(",");

  useEffect(() => {
    if (paused) return;

    let cancelled = false;
    let abortCtrl: AbortController | undefined;

    async function tick() {
      abortCtrl = new AbortController();
      const params = new URLSearchParams();
      if (servicesKey) params.set("services", servicesKey);
      if (levelsKey && levels.length < 4) {
        params.set("levels", levelsKey);
      }
      // Only send `since` once we have a real cursor — never "0".
      // The server falls back to a 30-second window when `since` is
      // omitted, which is what we want on the very first poll when
      // initialLines was empty.
      if (cursorRef.current && cursorRef.current !== "0") {
        params.set("since", cursorRef.current);
      }

      try {
        const response = await fetch(
          `/api/observability/logs/recent?${params.toString()}`,
          { signal: abortCtrl.signal, cache: "no-store" },
        );
        if (!response.ok) {
          if (!cancelled) setError(`HTTP ${response.status}`);
          return;
        }
        const body = (await response.json()) as FetchResponse;
        if (cancelled) return;
        if (!body.ok) {
          setError(body.error.message);
          return;
        }
        setError(undefined);
        setLastFetched(body.fetchedAt);
        if (body.lines.length === 0) return;
        // Newest line moves the cursor forward.
        const newest = body.lines[0]!;
        cursorRef.current = newest.tsNano;
        setLines((prev) => mergeLines(body.lines, prev));
      } catch (err: unknown) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(err instanceof Error ? err.message : "fetch failed");
      }
    }

    // Fire immediately, then on interval — operators expect the first
    // tick to land before the 2s timer would expire.
    void tick();
    const interval = setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      abortCtrl?.abort();
      clearInterval(interval);
    };
    // levels.length is included via levelsKey + the filter; intentional.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paused, servicesKey, levelsKey]);

  return (
    <>
      {/* Live-tail control bar — replaces the static dot in the parent */}
      <div className="flex items-center gap-3 mb-4">
        <button
          aria-label={paused ? "Resume live tail" : "Pause live tail"}
          className={cn(
            "flex items-center gap-1.5 px-3 py-1 rounded text-[10px] font-bold uppercase tracking-wider transition-colors border",
            paused
              ? "bg-surface-container border-white/10 text-on-surface-variant hover:bg-surface-bright"
              : "bg-[#7bdc7b]/10 border-[#7bdc7b]/30 text-[#7bdc7b]",
          )}
          onClick={() => setPaused((p) => !p)}
          type="button"
        >
          <span aria-hidden="true" className="material-symbols-outlined text-sm">
            {paused ? "play_arrow" : "pause"}
          </span>
          {paused ? "Paused" : "Live"}
          {!paused && (
            <span className="w-1.5 h-1.5 rounded-full bg-[#7bdc7b] animate-pulse" />
          )}
        </button>
        <span className="text-[10px] font-mono text-on-surface-variant/60">
          {lines.length} lines · poll {POLL_INTERVAL_MS / 1000}s
          {lastFetched && ` · last ${formatAgo(lastFetched)}`}
        </span>
        {error && (
          <span className="text-[10px] font-mono text-error">tail error: {error}</span>
        )}
      </div>

      {/* The log table itself */}
      <div className="glass-panel rounded-xl overflow-hidden" style={glassPanelStyle}>
        <div className="grid grid-cols-[24px_190px_160px_70px_minmax(0,1fr)_120px] items-center gap-3 px-4 py-2 bg-white/5 text-[10px] font-mono font-bold uppercase tracking-[0.2em] text-on-surface-variant border-b border-white/5">
          <div />
          <div>Time</div>
          <div>Service</div>
          <div>Level</div>
          <div>Message</div>
          <div className="text-right pr-2">Context</div>
        </div>

        {lines.length === 0 ? (
          <div className="p-10 text-center text-xs text-on-surface-variant">
            No log lines match the current filter.
          </div>
        ) : (
          lines.map((row, idx) => <LogRowComponent key={`${row.tsNano}-${idx}`} row={row} />)
        )}
      </div>
    </>
  );
}

/**
 * Merge new lines (newest first) with the existing list, deduping on
 * tsNano and capping the total to MAX_LINES.
 */
function mergeLines(
  incoming: LineWithTs[],
  existing: LineWithTs[],
): LineWithTs[] {
  const seen = new Set<string>(existing.map((l) => l.tsNano));
  const fresh = incoming.filter((l) => !seen.has(l.tsNano));
  return [...fresh, ...existing].slice(0, MAX_LINES);
}

function formatAgo(unixSec: number): string {
  const diff = Math.max(0, Math.floor(Date.now() / 1000) - unixSec);
  if (diff < 2) return "just now";
  if (diff < 60) return `${diff}s ago`;
  return `${Math.floor(diff / 60)}m ago`;
}

// ─── Subcomponents (kept here so the table styling stays self-contained) ────

const glassPanelStyle: React.CSSProperties = {
  background: "var(--glass-bg)",
  backdropFilter: "blur(20px)",
  border: "1px solid var(--glass-border)",
  borderRadius: "1rem",
};

const LEVEL_STYLES: Record<LogLevel, string> = {
  DEBUG: "bg-on-surface-variant/10 text-on-surface-variant/80",
  INFO: "bg-[#4ea2ff]/15 text-[#4ea2ff]",
  WARN: "bg-tertiary/15 text-tertiary",
  ERROR: "bg-error/15 text-error",
};

function LogRowComponent({ row }: { row: ParsedLogLine }) {
  const [expanded, setExpanded] = useState(false);
  const isError = row.level === "ERROR";

  // Pretty-print JSON when present so the expanded panel shows
  // structured logs in their natural form. Falls back to the raw
  // message string for non-JSON lines.
  const prettyJson = row.rawJson
    ? JSON.stringify(row.rawJson, null, 2)
    : undefined;

  return (
    <div
      className={cn(
        "border-b border-white/5",
        isError && "border-l-2 border-l-error",
        expanded && "bg-white/[0.02]",
      )}
    >
      {/* Row header is a real <button> so the entire bar is keyboard- and
          screen-reader-clickable, not just the chevron. The grid layout
          lives on the button itself; min-w-0 on the message cell is the
          key fix that lets `truncate` actually clip long lines. */}
      <button
        aria-controls={`logrow-${row.timestamp}-detail`}
        aria-expanded={expanded}
        className="grid grid-cols-[24px_190px_160px_70px_minmax(0,1fr)_120px] items-center gap-3 px-4 py-1.5 w-full text-left hover:bg-white/5 transition-colors cursor-pointer"
        onClick={() => setExpanded((e) => !e)}
        type="button"
      >
        <span
          aria-hidden="true"
          className={cn(
            "material-symbols-outlined text-on-surface-variant text-lg transition-transform shrink-0",
            expanded && "rotate-90",
          )}
        >
          chevron_right
        </span>
        <span className="font-mono text-[11px] text-on-surface-variant/70 truncate">
          {row.timestamp}
        </span>
        <span className="min-w-0 truncate">
          <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-surface-container text-on-surface">
            {row.service}
          </span>
        </span>
        <span className="min-w-0">
          <span
            className={cn(
              "inline-block px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider",
              LEVEL_STYLES[row.level],
            )}
          >
            {row.level}
          </span>
        </span>
        {/* CRITICAL: min-w-0 + block + truncate. Without min-w-0 a grid
            item refuses to shrink below its content's intrinsic width
            and the column blows out. */}
        <span className="block min-w-0 text-xs text-on-surface/80 font-mono truncate">
          {row.message}
        </span>
        <div
          className="flex justify-end min-w-0"
          onClick={(e) => e.stopPropagation()}
        >
          {row.traceId ? (
            <a
              href={`/observability/traces?trace=${row.traceId}`}
              className="flex items-center gap-1 px-2 py-0.5 bg-primary/10 border border-primary/30 rounded-full text-[10px] text-primary hover:bg-primary hover:text-on-primary transition-colors"
            >
              <span
                aria-hidden="true"
                className="material-symbols-outlined text-[14px]"
              >
                link
              </span>
              <span className="font-mono">{row.traceId.slice(0, 8)}</span>
            </a>
          ) : (
            <span className="text-on-surface-variant/40 text-[10px] font-mono">
              —
            </span>
          )}
        </div>
      </button>

      {expanded && (
        <div
          className="px-4 pt-1 pb-4 ml-9 border-l border-white/10 mb-2"
          id={`logrow-${row.timestamp}-detail`}
        >
          <div className="space-y-3 pl-4">
            <div>
              <span className="text-[9px] font-mono uppercase tracking-[0.2em] text-on-surface-variant/60">
                Full message
              </span>
              <pre className="mt-1 text-xs font-mono text-on-surface/90 whitespace-pre-wrap break-words bg-black/30 rounded p-3 max-h-96 overflow-auto">
                {row.message}
              </pre>
            </div>

            {prettyJson && prettyJson !== `"${row.message}"` && (
              <div>
                <span className="text-[9px] font-mono uppercase tracking-[0.2em] text-on-surface-variant/60">
                  Structured fields
                </span>
                <pre className="mt-1 text-xs font-mono text-primary-fixed-dim whitespace-pre-wrap break-words bg-black/30 rounded p-3 max-h-96 overflow-auto">
                  {prettyJson}
                </pre>
              </div>
            )}

            {row.traceId && (
              <div className="text-[10px] font-mono text-on-surface-variant/70">
                <span className="text-on-surface-variant/50">trace_id: </span>
                <a
                  className="text-primary hover:underline"
                  href={`/observability/traces?trace=${row.traceId}`}
                >
                  {row.traceId}
                </a>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
