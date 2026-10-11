"use client";

/**
 * useTheme — read/write the operator's theme preference.
 *
 * Persistence: localStorage key `phantom.theme`. Possible values:
 *   "dark"   (default; the navy-blue look we ship today)
 *   "light"  (white surface variant — full implementation lands in
 *             the next commit; for now the toggle persists the
 *             preference and exposes it via the hook + a
 *             `data-theme="light"` attribute on <html>, but the
 *             actual color tokens haven't been remapped yet, so
 *             flipping to light renders mostly the same dark theme).
 *
 * Why not next-themes: that library wraps NEXT_PUBLIC env var checks
 * and adds a 5KB bundle for two lines of localStorage logic. For one
 * binary toggle on a single-tenant app, a tiny hook is plenty.
 *
 * SSR / hydration: the hook returns "dark" until the client mounts +
 * reads localStorage. The toggle component should render an idle
 * state (or skip the active highlight) until `hydrated` flips true,
 * same pattern as useTestedJourneys.
 */

import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "light";

const STORAGE_KEY = "phantom.theme";
const ATTR = "data-theme";

function applyTheme(theme: Theme) {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute(ATTR, theme);
}

export function useTheme(): {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggle: () => void;
  hydrated: boolean;
} {
  const [theme, setThemeState] = useState<Theme>("dark");
  const [hydrated, setHydrated] = useState(false);

  // Hydrate from localStorage on mount + apply the data-theme attr so
  // any CSS-vars that select on [data-theme="light"] activate.
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      const next: Theme = raw === "light" ? "light" : "dark";
      setThemeState(next);
      applyTheme(next);
    } catch {
      // Storage blocked — fall back to default dark, no persistence.
      applyTheme("dark");
    }
    setHydrated(true);
  }, []);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    applyTheme(t);
    try {
      window.localStorage.setItem(STORAGE_KEY, t);
    } catch {
      // ignore
    }
  }, []);

  const toggle = useCallback(() => {
    setThemeState((prev) => {
      const next: Theme = prev === "dark" ? "light" : "dark";
      applyTheme(next);
      try {
        window.localStorage.setItem(STORAGE_KEY, next);
      } catch {
        // ignore
      }
      return next;
    });
  }, []);

  return { theme, setTheme, toggle, hydrated };
}
