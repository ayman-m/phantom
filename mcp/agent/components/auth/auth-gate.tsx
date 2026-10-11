"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { LoginScreen } from "@/components/auth/login-screen";
import { AppShell } from "@/components/app-shell";

/**
 * Top-level auth gate. Three states only:
 *
 *   1. !authenticated         → LoginScreen
 *   2. credentialsChanged===false → AppShell, but auto-redirect to
 *                                /profile if we're not already there.
 *                                The /profile page renders the
 *                                "change your default password"
 *                                banner non-dismissibly until the
 *                                operator rotates.
 *   3. authenticated + credentials changed → AppShell with the
 *                                page contents
 *
 * There is no setup wizard: the entrypoint seeds defaults so login
 * works from first boot.
 *
 * Server-side validation: /api/auth/status calls
 * lib/auth-store.validateSession which hits the MCP's
 * /api/v1/ui/auth/session. The MCP is the source of truth; this
 * component just polls + branches.
 */
export const AuthGate = ({ children }: { children: React.ReactNode }) => {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [credentialsChanged, setCredentialsChanged] = useState<
    boolean | null
  >(null);
  const router = useRouter();
  const pathname = usePathname();

  const checkStatus = async () => {
    try {
      const response = await fetch("/api/auth/status", { cache: "no-store" });
      const data = await response.json();
      setAuthenticated(Boolean(data.authenticated));
      setCredentialsChanged(Boolean(data.credentialsChanged));
    } catch {
      setAuthenticated(false);
      setCredentialsChanged(false);
    }
  };

  useEffect(() => {
    checkStatus();

    // Re-validate auth on browser back/forward navigation and when the
    // tab becomes visible again. This closes the bfcache hole: hitting
    // Back after sign-out would otherwise restore the previous page
    // from the browser's back-forward cache with stale React state
    // (authenticated: true), and the operator could click around
    // authenticated pages without the server ever being asked.
    const handlePageShow = (e: PageTransitionEvent) => {
      if (e.persisted) {
        setAuthenticated(null);
        setCredentialsChanged(null);
        checkStatus();
      }
    };
    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        checkStatus();
      }
    };
    window.addEventListener("pageshow", handlePageShow);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      window.removeEventListener("pageshow", handlePageShow);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, []);

  // When authenticated with un-rotated default credentials,
  // redirect any non-/profile page to /profile. The profile page
  // itself renders the "change your password" banner. We do this in
  // an effect (not during render) so React's strict-mode + the
  // initial paint don't fight over the redirect.
  useEffect(() => {
    if (authenticated === true && credentialsChanged === false) {
      if (pathname !== "/profile") {
        router.replace("/profile");
      }
    }
  }, [authenticated, credentialsChanged, pathname, router]);

  if (authenticated === null || credentialsChanged === null) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-slate-950">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/logo.svg"
          alt="Phantom"
          width={96}
          height={96}
          className="drop-shadow-[0_0_20px_rgba(45,141,240,0.35)]"
        />
        <div className="text-base font-medium text-slate-200 tracking-wide">
          Starting up Phantom
          <span className="ml-1 inline-block animate-pulse">…</span>
        </div>
      </div>
    );
  }

  if (!authenticated) {
    return <LoginScreen onSuccess={checkStatus} />;
  }

  // authenticated === true here; AppShell renders the page.
  // The redirect-to-/profile effect above handles the "must change
  // password" path — at this point either we're on /profile (correct
  // page for the banner) or we've already started the redirect.
  return <AppShell>{children}</AppShell>;
};
