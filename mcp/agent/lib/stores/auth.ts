import { create } from "zustand";

export interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
}

export interface AuthActions {
  // NB: there is intentionally no `login` action here. The login form
  // (`components/auth/login-screen.tsx`) calls `/api/auth/login` directly
  // with `{username, password}` and updates the store via `checkAuth()`
  // on success. A previous version of this store had a `login(token)`
  // method that POSTed `{token}` — that shape never matched the route
  // handler (which expects `{username, password}`), and no caller ever
  // invoked it. Deleted to remove the foot-gun.
  logout: () => Promise<void>;
  checkAuth: () => Promise<void>;
}

export type AuthStore = AuthState & AuthActions;

export const useAuthStore = create<AuthStore>((set) => ({
  isAuthenticated: false,
  isLoading: false,

  logout: async () => {
    set({ isLoading: true });
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } catch {
      // Logout clears local state regardless of network errors.
    } finally {
      set({ isAuthenticated: false, isLoading: false });
    }
  },

  checkAuth: async () => {
    set({ isLoading: true });
    try {
      // /api/auth/status is the canonical session-status endpoint
      // (used by AuthGate too); /api/auth/session was a vestigial
      // URL from an older auth design that never had a route handler,
      // resulting in a 404 polling loop on every page mount.
      const response = await fetch("/api/auth/status");
      if (response.ok) {
        const data = await response.json();
        set({ isAuthenticated: data.authenticated === true, isLoading: false });
      } else {
        set({ isAuthenticated: false, isLoading: false });
      }
    } catch {
      set({ isAuthenticated: false, isLoading: false });
    }
  },
}));
