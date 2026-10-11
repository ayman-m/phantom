import { create } from "zustand";
import { getConfig, setConfigPath } from "../api/config";

export interface ConfigState {
  config: Record<string, unknown> | null;
  configHash: string;
  isLoading: boolean;
  isDirty: boolean;
  error: string | null;
}

export interface ConfigActions {
  loadConfig: () => Promise<void>;
  updatePath: (path: string, value: unknown) => void;
  saveConfig: (path: string) => Promise<void>;
}

export type ConfigStore = ConfigState & ConfigActions;

export const useConfigStore = create<ConfigStore>((set, get) => ({
  config: null,
  configHash: "",
  isLoading: false,
  isDirty: false,
  error: null,

  loadConfig: async () => {
    set({ isLoading: true, error: null });
    const result = await getConfig();
    if (result.ok) {
      const data = result.data as Record<string, unknown> & { _hash?: string };
      const hash =
        typeof data._hash === "string" ? data._hash : get().configHash;
      const { _hash: _, ...config } = data;
      set({ config, configHash: hash, isLoading: false, isDirty: false });
    } else {
      set({ isLoading: false, error: result.error.message });
    }
  },

  updatePath: (path: string, value: unknown) => {
    const current = get().config;
    if (!current) return;
    set({
      config: { ...current, [path]: value },
      isDirty: true,
    });
  },

  saveConfig: async (path: string) => {
    const state = get();
    if (!state.config) return;

    const value = state.config[path];
    set({ isLoading: true, error: null });

    const result = await setConfigPath(path, value, state.configHash);
    if (result.ok) {
      set({
        configHash: result.data.hash,
        isLoading: false,
        isDirty: false,
      });
    } else {
      set({ isLoading: false, error: result.error.message });
    }
  },
}));
