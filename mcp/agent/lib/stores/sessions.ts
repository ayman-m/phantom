import { create } from "zustand";
import { listSessions, getSession } from "../api/sessions";
import { createAgentRun } from "../api/runs";
import type { Session } from "../api/types";

export interface SessionsState {
  sessions: Session[];
  selectedSession: Session | null;
  isLoading: boolean;
}

export interface SessionsActions {
  fetchSessions: (agentId: string) => Promise<void>;
  fetchSession: (id: string) => Promise<void>;
  createSession: (agentId: string) => Promise<void>;
}

export type SessionsStore = SessionsState & SessionsActions;

export const useSessionsStore = create<SessionsStore>((set) => ({
  sessions: [],
  selectedSession: null,
  isLoading: false,

  fetchSessions: async (agentId: string) => {
    set({ isLoading: true });
    const result = await listSessions(agentId);
    if (result.ok) {
      set({ sessions: result.data, isLoading: false });
    } else {
      set({ isLoading: false });
    }
  },

  fetchSession: async (id: string) => {
    set({ isLoading: true });
    const result = await getSession(id);
    if (result.ok) {
      set({ selectedSession: result.data, isLoading: false });
    } else {
      set({ isLoading: false });
    }
  },

  createSession: async (agentId: string) => {
    set({ isLoading: true });
    const result = await createAgentRun(agentId, "");
    if (result.ok) {
      const newSession: Session = {
        session_id: result.data.sessionId,
        session_key: "",
        agent_id: agentId,
        run_count: "1",
        total_input_tokens: "0",
        total_output_tokens: "0",
        last_model: "",
        metadata: null,
        version: "1",
        created_at: result.data.startedAt,
        updated_at: result.data.startedAt,
        last_active_at: result.data.startedAt,
      };
      set((state) => ({
        sessions: [...state.sessions, newSession],
        selectedSession: newSession,
        isLoading: false,
      }));
    } else {
      set({ isLoading: false });
    }
  },
}));
