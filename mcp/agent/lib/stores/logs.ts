import { create } from "zustand";
import type { LogEntry } from "../api/types";
import type { EventMessage } from "../ws/types";
import { getManager } from "./websocket";

const MAX_ENTRIES = 500;

export interface LogFilters {
  level: string;
  source: string;
  search: string;
}

export interface LogsState {
  entries: LogEntry[];
  filters: LogFilters;
  isPaused: boolean;
}

export interface LogsActions {
  addEntry: (entry: LogEntry) => void;
  setFilter: (filter: Partial<LogFilters>) => void;
  clearLogs: () => void;
  togglePause: () => void;
  startSubscription: () => void;
  stopSubscription: () => void;
}

export type LogsStore = LogsState & LogsActions;

const DEFAULT_FILTERS: LogFilters = {
  level: "",
  source: "",
  search: "",
};

/** Event handler reference for cleanup. */
let wsHandler: ((msg: EventMessage) => void) | null = null;

/** Parse a WebSocket event message into a LogEntry. */
function parseLogEvent(msg: EventMessage): LogEntry {
  const data = msg.data;
  return {
    timestamp: msg.timestamp || (data.timestamp as string) || new Date().toISOString(),
    level: (data.level as string) || "info",
    source: msg.channel || (data.source as string) || "unknown",
    runId: data.runId as string | undefined,
    message: (data.message as string) || JSON.stringify(data),
  };
}

/** Apply the ring buffer constraint: keep only the newest MAX_ENTRIES. */
function enforceRingBuffer(entries: LogEntry[]): LogEntry[] {
  if (entries.length <= MAX_ENTRIES) return entries;
  return entries.slice(entries.length - MAX_ENTRIES);
}

export const useLogsStore = create<LogsStore>((set, get) => ({
  entries: [],
  filters: { ...DEFAULT_FILTERS },
  isPaused: false,

  addEntry: (entry: LogEntry) => {
    if (get().isPaused) return;
    set((state) => ({
      entries: enforceRingBuffer([...state.entries, entry]),
    }));
  },

  setFilter: (filter: Partial<LogFilters>) => {
    set((state) => ({
      filters: { ...state.filters, ...filter },
    }));
  },

  clearLogs: () => {
    set({ entries: [] });
  },

  togglePause: () => {
    set((state) => ({ isPaused: !state.isPaused }));
  },

  startSubscription: () => {
    const mgr = getManager();

    wsHandler = (msg: EventMessage) => {
      const entry = parseLogEvent(msg);
      useLogsStore.getState().addEntry(entry);
    };

    mgr.subscribe(["system", "runs"]);
    mgr.on("log", wsHandler);
    mgr.on("system.log", wsHandler);
    mgr.on("run.log", wsHandler);
  },

  stopSubscription: () => {
    if (!wsHandler) return;
    const mgr = getManager();

    mgr.off("log", wsHandler);
    mgr.off("system.log", wsHandler);
    mgr.off("run.log", wsHandler);
    mgr.unsubscribe(["system", "runs"]);
    wsHandler = null;
  },
}));

/** Get filtered entries from the store (selector for components). */
export function selectFilteredEntries(state: LogsStore): LogEntry[] {
  const { entries, filters } = state;
  return entries.filter((entry) => {
    if (filters.level && entry.level !== filters.level) return false;
    if (filters.source && entry.source !== filters.source) return false;
    if (
      filters.search &&
      !entry.message.toLowerCase().includes(filters.search.toLowerCase())
    ) {
      return false;
    }
    return true;
  });
}
