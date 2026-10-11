"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * Bookmarks panel for the Metrics tab.
 *
 * Bookmarks persist to the MCP-side operator-state store at
 *   `operator_state.key='metrics_bookmarks'`, via the Next.js proxy
 *   /api/agent/operator-state/metrics_bookmarks.
 *
 * The server store is the single source of truth: volume wipes clear
 * it, bookmarks follow the operator across devices, and backups
 * include them. Bookmarks left in browser localStorage under
 * `spark.observability.metrics.bookmarks.v1` are migrated once on
 * first mount and then cleared.
 *
 * Same client-only component shape — the surrounding /observability
 * /metrics page is server-rendered, this island handles the
 * operator's saved-query workflow.
 */

const SERVER_KEY = "metrics_bookmarks";
const LEGACY_LOCAL_STORAGE_KEY = "spark.observability.metrics.bookmarks.v1";
const SERVER_URL = `/api/agent/operator-state/${SERVER_KEY}`;
const MAX_BOOKMARKS = 12;

type Bookmark = {
  /** Display label, derived from the query if not user-provided. */
  label: string;
  /** Raw PromQL string. */
  query: string;
  /** Unix ms when bookmarked. Used as the key. */
  savedAt: number;
};

type Props = {
  /** Currently-active query, used by the "Save" button. */
  currentQuery: string;
};

async function loadFromServer(): Promise<Bookmark[] | null> {
  try {
    const resp = await fetch(SERVER_URL, { cache: "no-store" });
    if (resp.status === 404) return null;
    if (!resp.ok) {
      console.warn(
        `[metrics-bookmarks] server load returned ${resp.status}; using empty list`,
      );
      return [];
    }
    const data = (await resp.json()) as { value?: unknown };
    if (Array.isArray(data.value)) {
      return data.value.filter(isBookmark);
    }
    return [];
  } catch (err) {
    console.warn(
      "[metrics-bookmarks] server load failed:",
      err instanceof Error ? err.message : err,
    );
    return [];
  }
}

async function persistToServer(value: Bookmark[]): Promise<void> {
  try {
    await fetch(SERVER_URL, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    });
  } catch (err) {
    console.warn(
      "[metrics-bookmarks] server persist failed:",
      err instanceof Error ? err.message : err,
    );
  }
}

function readLegacyLocalStorage(): Bookmark[] | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(LEGACY_LOCAL_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (Array.isArray(parsed)) {
      return parsed.filter(isBookmark);
    }
    return null;
  } catch {
    return null;
  }
}

function clearLegacyLocalStorage(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(LEGACY_LOCAL_STORAGE_KEY);
  } catch {
    // Storage write blocked — orphan key, harmless (never read again).
  }
}

export function MetricsBookmarks({ currentQuery }: Props) {
  const [bookmarks, setBookmarks] = useState<Bookmark[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const migrationDoneRef = useRef(false);

  useEffect(() => {
    if (migrationDoneRef.current) return;
    migrationDoneRef.current = true;

    (async () => {
      const serverList = await loadFromServer();
      if (serverList === null) {
        const legacy = readLegacyLocalStorage();
        if (legacy && legacy.length > 0) {
          await persistToServer(legacy);
          clearLegacyLocalStorage();
          setBookmarks(legacy);
        } else {
          setBookmarks([]);
        }
      } else {
        setBookmarks(serverList);
        if (readLegacyLocalStorage() !== null) {
          clearLegacyLocalStorage();
        }
      }
      setHydrated(true);
    })();
  }, []);

  const persist = useCallback((next: Bookmark[]) => {
    setBookmarks(next);
    void persistToServer(next);
  }, []);

  function addCurrent() {
    if (!currentQuery) return;
    if (bookmarks.some((b) => b.query === currentQuery)) return;
    const label = deriveLabel(currentQuery);
    const next = [
      { label, query: currentQuery, savedAt: Date.now() },
      ...bookmarks,
    ].slice(0, MAX_BOOKMARKS);
    persist(next);
  }

  function remove(savedAt: number) {
    persist(bookmarks.filter((b) => b.savedAt !== savedAt));
  }

  // Avoid hydration mismatch — render a "loading" state until the
  // server fetch (or migration) completes.
  if (!hydrated) {
    return (
      <div className="mx-2 my-2 p-3 rounded-lg border border-dashed border-white/10 text-center">
        <p className="text-[10px] text-on-surface-variant/50">Loading…</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between px-2">
        <span className="text-[10px] font-mono text-on-surface-variant/60">
          {bookmarks.length} / {MAX_BOOKMARKS}
        </span>
        <button
          aria-label="Bookmark current query"
          className={cn(
            "flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider transition-colors",
            currentQuery
              ? "bg-primary/10 text-primary hover:bg-primary/20"
              : "bg-surface-container text-on-surface-variant/40 cursor-not-allowed",
          )}
          disabled={!currentQuery}
          onClick={addCurrent}
          type="button"
        >
          <span aria-hidden="true" className="material-symbols-outlined text-xs">
            add
          </span>
          Save
        </button>
      </div>

      {bookmarks.length === 0 ? (
        <div className="mx-2 p-3 rounded-lg border border-dashed border-white/10 text-center">
          <span
            aria-hidden="true"
            className="material-symbols-outlined text-sm text-on-surface-variant/40"
          >
            bookmark
          </span>
          <p className="text-[10px] text-on-surface-variant/50 mt-1">
            Click <span className="text-primary">Save</span> to bookmark a query
          </p>
        </div>
      ) : (
        <ul className="space-y-1">
          {bookmarks.map((b) => (
            <li
              key={b.savedAt}
              className="group flex items-stretch gap-1"
            >
              <a
                className="flex-1 flex items-center gap-2 px-2 py-1.5 text-xs rounded transition-colors text-left text-on-surface-variant hover:text-on-surface hover:bg-white/5 truncate"
                href={`/observability/metrics?q=${encodeURIComponent(b.query)}`}
                title={b.query}
              >
                <span
                  aria-hidden="true"
                  className="material-symbols-outlined text-sm text-tertiary"
                >
                  bookmark
                </span>
                <span className="truncate">{b.label}</span>
              </a>
              <button
                aria-label={`Remove bookmark ${b.label}`}
                className="opacity-0 group-hover:opacity-100 text-on-surface-variant/40 hover:text-error px-1 transition-opacity"
                onClick={() => remove(b.savedAt)}
                type="button"
              >
                <span
                  aria-hidden="true"
                  className="material-symbols-outlined text-sm"
                >
                  close
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function isBookmark(value: unknown): value is Bookmark {
  if (typeof value !== "object" || value === null) return false;
  const obj = value as Record<string, unknown>;
  return (
    typeof obj.label === "string" &&
    typeof obj.query === "string" &&
    typeof obj.savedAt === "number"
  );
}

/**
 * Derive a human-readable label from a PromQL query. Picks the first
 * 5+ char identifier-looking token in the query and truncates to 40
 * chars.
 */
function deriveLabel(query: string): string {
  const cleaned = query.replace(/\s+/g, " ").trim();
  const matches = query.match(/[a-z_][a-z0-9_]{4,}/i);
  const metric = matches?.[0] ?? cleaned.slice(0, 40);
  return metric.length > 40 ? `${metric.slice(0, 37)}…` : metric;
}
