import { create } from "zustand";
import { listAgents, getAgent, createAgent } from "../api/agents";
import type { Agent, CreateAgentRequest } from "../api/types";

export interface AgentsState {
  agents: Agent[];
  selectedAgent: Agent | null;
  isLoading: boolean;
}

export interface AgentsActions {
  fetchAgents: () => Promise<void>;
  fetchAgent: (id: string) => Promise<void>;
  createAgent: (data: CreateAgentRequest) => Promise<void>;
}

export type AgentsStore = AgentsState & AgentsActions;

export const useAgentsStore = create<AgentsStore>((set) => ({
  agents: [],
  selectedAgent: null,
  isLoading: false,

  fetchAgents: async () => {
    set({ isLoading: true });
    const result = await listAgents();
    if (result.ok) {
      set({ agents: result.data, isLoading: false });
    } else {
      set({ isLoading: false });
    }
  },

  fetchAgent: async (id: string) => {
    set({ isLoading: true });
    const result = await getAgent(id);
    if (result.ok) {
      set({ selectedAgent: result.data, isLoading: false });
    } else {
      set({ isLoading: false });
    }
  },

  createAgent: async (data: CreateAgentRequest) => {
    set({ isLoading: true });
    const result = await createAgent(data);
    if (result.ok) {
      set((state) => ({
        agents: [...state.agents, result.data],
        isLoading: false,
      }));
    } else {
      set({ isLoading: false });
    }
  },
}));
