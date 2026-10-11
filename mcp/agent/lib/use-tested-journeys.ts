"use client";

/**
 * useTestedJourneys — per-operator "I've tested this journey" tracking.
 *
 * Persists to the MCP-side operator-state store at
 *   `operator_state.key='tested_journeys'`, via the Next.js proxy
 *   /api/agent/operator-state/tested_journeys.
 *
 * The server store is the single source of truth: volume wipes clear
 * it, progress follows the operator across devices and browsers, and
 * backups include it.
 *
 * # One-shot migration on first mount
 *
 * Marks left in browser localStorage under
 * `phantom.help.tested-journeys` are migrated once. On first mount the hook:
 *   1. Fetches from server. If server returns the list → use it.
 *   2. If server 404 + localStorage has data → POST the localStorage
 *      data to server (one PUT), then DELETE the localStorage key.
 *      Operator's marks are preserved + the localStorage key never
 *      gets re-read again on future loads.
 *   3. If server 404 + no localStorage → empty set.
 *
 * Subsequent reads / writes go through the server only. The
 * localStorage key is gone after the one-shot migration runs.
 *
 * # Optimistic UI + fire-and-forget persist
 *
 * `toggle` / `setTested` / `reset` update local state IMMEDIATELY
 * (no waiting for the network) then fire a PUT/DELETE to the server.
 * If the network call fails, the local state stays (the operator's
 * intent was clear) and we log a console.warn. Same pattern Gmail's
 * "star" + most modern UI checkbox state uses — the server is
 * authoritative for cold-load reads, but mid-session reads come
 * from React state.
 */

import { useCallback, useEffect, useRef, useState } from "react";

const SERVER_KEY = "tested_journeys";
const LEGACY_LOCAL_STORAGE_KEY = "phantom.help.tested-journeys";
const SERVER_URL = `/api/agent/operator-state/${SERVER_KEY}`;

export interface UseTestedJourneysReturn {
  /** True after the first server-fetch round-trip (or migration) completes. */
  hydrated: boolean;
  /** Set of journey ids the operator has marked tested. */
  tested: Set<string>;
  /** Toggle the tested flag for one journey. */
  toggle: (id: string) => void;
  /** Set the tested flag explicitly. */
  setTested: (id: string, value: boolean) => void;
  /** Clear all tested flags. */
  reset: () => void;
  /** Convenience: how many are tested right now. */
  count: number;
}

async function loadFromServer(): Promise<string[] | null> {
  try {
    const resp = await fetch(SERVER_URL, { cache: "no-store" });
    if (resp.status === 404) return null;
    if (!resp.ok) {
      console.warn(
        `[use-tested-journeys] server load returned ${resp.status}; using empty set`,
      );
      return [];
    }
    const data = (await resp.json()) as { value?: unknown };
    if (Array.isArray(data.value)) {
      return data.value.filter((x): x is string => typeof x === "string");
    }
    return [];
  } catch (err) {
    console.warn(
      "[use-tested-journeys] server load failed:",
      err instanceof Error ? err.message : err,
    );
    return [];
  }
}

async function persistToServer(value: string[]): Promise<void> {
  try {
    await fetch(SERVER_URL, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    });
  } catch (err) {
    console.warn(
      "[use-tested-journeys] server persist failed:",
      err instanceof Error ? err.message : err,
    );
  }
}

async function deleteFromServer(): Promise<void> {
  try {
    await fetch(SERVER_URL, { method: "DELETE" });
  } catch (err) {
    console.warn(
      "[use-tested-journeys] server delete failed:",
      err instanceof Error ? err.message : err,
    );
  }
}

function readLegacyLocalStorage(): string[] | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(LEGACY_LOCAL_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (Array.isArray(parsed) && parsed.every((x) => typeof x === "string")) {
      return parsed as string[];
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
    // Storage write blocked — accept the orphan key; it'll just be
    // ignored on future loads since we never read it after migration.
  }
}

export function useTestedJourneys(): UseTestedJourneysReturn {
  const [tested, setTestedState] = useState<Set<string>>(new Set());
  const [hydrated, setHydrated] = useState(false);
  // Used to avoid re-running migration on hot reloads in dev.
  const migrationDoneRef = useRef(false);

  useEffect(() => {
    if (migrationDoneRef.current) return;
    migrationDoneRef.current = true;

    (async () => {
      const serverList = await loadFromServer();

      if (serverList === null) {
        // Server has no row yet. Check for legacy localStorage data.
        const legacy = readLegacyLocalStorage();
        if (legacy && legacy.length > 0) {
          // One-shot migration: persist legacy data to server then
          // clear the local key. After this, subsequent mounts on
          // the same browser hit the "server returns the list"
          // happy path.
          await persistToServer(legacy);
          clearLegacyLocalStorage();
          setTestedState(new Set(legacy));
        } else {
          // Server empty + no legacy. Genuine fresh state.
          setTestedState(new Set());
        }
      } else {
        // Server returned the list (possibly empty). Treat as
        // authoritative; clear any stale legacy localStorage that
        // somehow lingers (e.g. another browser already migrated).
        setTestedState(new Set(serverList));
        if (readLegacyLocalStorage() !== null) {
          clearLegacyLocalStorage();
        }
      }
      setHydrated(true);
    })();
  }, []);

  const persistInBackground = useCallback((next: Set<string>) => {
    void persistToServer([...next]);
  }, []);

  const toggle = useCallback(
    (id: string) => {
      setTestedState((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        persistInBackground(next);
        return next;
      });
    },
    [persistInBackground],
  );

  const setTested = useCallback(
    (id: string, value: boolean) => {
      setTestedState((prev) => {
        if (value === prev.has(id)) return prev;
        const next = new Set(prev);
        if (value) next.add(id);
        else next.delete(id);
        persistInBackground(next);
        return next;
      });
    },
    [persistInBackground],
  );

  const reset = useCallback(() => {
    setTestedState(new Set());
    void deleteFromServer();
  }, []);

  return {
    hydrated,
    tested,
    toggle,
    setTested,
    reset,
    count: tested.size,
  };
}
