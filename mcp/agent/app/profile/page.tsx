/**
 * Profile page — operator account settings.
 *
 * Sections:
 *   1. First-login banner — non-dismissible when credentialsChanged
 *      is false (operator still on baked default password). The
 *      banner explains the situation and the Change-Password form
 *      below is the resolution.
 *   2. Account — read-only display of the username (locked to
 *      "admin" — multi-user is on the roadmap).
 *   3. Change Password — form that POSTs to /api/auth/change-password,
 *      which calls auth-store.changePassword → MCP → SecretStore.
 *      On success the server revokes ALL sessions (including this
 *      one) and clears the cookie; the page hard-redirects to "/"
 *      so AuthGate re-renders as the LoginScreen for the operator
 *      to sign in with the new password.
 *   4. Sign-out — standalone end-this-session action.
 */

"use client";

import { useEffect, useState } from "react";

import { useNotificationsStore } from "@/lib/stores/notifications";

const glassPanel: React.CSSProperties = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(20px)",
  border: "1px solid rgba(255,255,255,0.05)",
};

interface StatusResponse {
  authenticated: boolean;
  credentialsChanged: boolean;
  username: string | null;
}

async function fetchStatus(): Promise<{
  username: string;
  credentialsChanged: boolean;
}> {
  try {
    const r = await fetch("/api/auth/status", { cache: "no-store" });
    if (!r.ok) return { username: "admin", credentialsChanged: true };
    const data = (await r.json()) as StatusResponse;
    return {
      username: data.username ?? "admin",
      credentialsChanged: Boolean(data.credentialsChanged),
    };
  } catch {
    return { username: "admin", credentialsChanged: true };
  }
}

export default function ProfilePage() {
  const addToast = useNotificationsStore((s) => s.addToast);

  const [username, setUsername] = useState<string>("…");
  // When false, the first-login banner shows above the form
  // and the operator is gated on rotating before doing anything else.
  // AuthGate also auto-redirects them here from any other page when
  // this is false, so the operator can't navigate away.
  const [credentialsChanged, setCredentialsChanged] = useState<boolean>(true);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchStatus().then((s) => {
      if (!cancelled) {
        setUsername(s.username);
        setCredentialsChanged(s.credentialsChanged);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Client-side form gate. The server re-validates everything; this
  // is purely a UX nicety so the operator sees the submit button
  // light up only when the form is "submittable-looking."
  const canSubmit =
    !submitting &&
    currentPassword.length > 0 &&
    newPassword.length >= 8 &&
    newPassword === confirmPassword &&
    newPassword !== currentPassword;

  // Specific failure-mode hints below the new-password field. We
  // surface them as muted text rather than red errors because the
  // form is in a "you're typing" state, not a "you submitted bad
  // data" state. Real errors come from the server via toasts.
  const newPasswordHint = (() => {
    if (newPassword.length === 0) return null;
    if (newPassword.length < 8) return "Must be at least 8 characters.";
    if (newPassword === currentPassword)
      return "Must differ from current password.";
    if (confirmPassword.length > 0 && newPassword !== confirmPassword)
      return "Doesn't match confirmation.";
    return null;
  })();

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const r = await fetch("/api/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
          confirm_password: confirmPassword,
        }),
      });
      if (r.ok) {
        addToast({
          variant: "success",
          title: "Password updated",
          description:
            "All sessions were signed out. Sign in again with your new password.",
        });
        setCurrentPassword("");
        setNewPassword("");
        setConfirmPassword("");
        // The server revoked ALL sessions for this user
        // (including the one we used to authorize this change) and
        // cleared the cookie. Hard-navigate to "/" so AuthGate
        // re-renders with no cookie → LoginScreen prompts for new
        // password.
        window.location.href = "/";
        return;
      } else {
        let detail = `Server returned ${r.status}`;
        try {
          const data = (await r.json()) as { error?: string };
          if (data.error) detail = data.error;
        } catch {
          // non-JSON body
        }
        addToast({
          variant: "error",
          title: "Could not change password",
          description: detail,
        });
      }
    } catch (err) {
      addToast({
        variant: "error",
        title: "Could not change password",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setSubmitting(false);
    }
  }

  /**
   * Sign-out flow: POST /api/auth/logout to clear the phantom_session
   * cookie server-side, then hard-navigate to "/" (root).
   *
   * Why "/" and NOT "/login": there's no /login route in this app.
   * AuthGate (mounted at the layout level) intercepts every page
   * for unauthenticated users and renders <LoginScreen> directly
   * regardless of the URL. So the LoginScreen shows up at any URL
   * when there's no cookie — what matters is what's UNDERNEATH it,
   * because AuthGate flips to AppShell after sign-in and the
   * children prop is whatever Next.js routed for the URL. Pre-fix
   * we sent the browser to "/login", which 404'd; AuthGate showed
   * LoginScreen on top of the 404, sign-in flipped to authenticated,
   * and the visible page underneath was still the 404 → operator
   * sees "Page not found" right after a successful login.
   *
   * "/" is the chat page, which is the right default landing.
   *
   * Why hard navigate (window.location) vs. router.push: AuthGate's
   * authenticated state is component-local. A soft client-side
   * navigation keeps the authenticated React tree mounted with all
   * its in-flight SSE streams + approval polls. window.location
   * unmounts everything; AuthGate re-mounts with no cookie and
   * shows the LoginScreen fresh. Cleanest tear-down.
   */
  async function handleSignOut() {
    setSigningOut(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } catch {
      // Even if the request errors, we still clear local state and
      // redirect — the cookie may have been cleared on a previous
      // attempt, or the server may be reachable but slow. Either way
      // a logged-out client is the safe destination.
    }
    window.location.href = "/";
  }

  return (
    <div className="min-h-screen p-10 max-w-3xl mx-auto space-y-8">
      <header>
        <h1 className="text-3xl font-headline font-bold text-on-surface">
          Profile
        </h1>
        <p className="text-on-surface-variant/70 mt-1 text-sm">
          Manage your account credentials.
        </p>
      </header>

      {/* Non-dismissible banner when the operator is still
        * using the baked default password. Renders above everything
        * else on the page. AuthGate's effect auto-redirects from
        * any other route to /profile while credentialsChanged===false,
        * so the operator effectively cannot navigate away until they
        * rotate. Amber instead of red — directive but not destructive. */}
      {!credentialsChanged && (
        <section
          className="rounded-2xl p-6 space-y-2"
          style={{
            ...glassPanel,
            border:
              "1px solid color-mix(in srgb, var(--accent-amber) 60%, transparent)",
            background:
              "color-mix(in srgb, var(--accent-amber) 12%, var(--glass-bg-strong))",
          }}
        >
          <h2 className="font-headline font-semibold text-base text-on-surface flex items-center gap-2">
            <span
              className="material-symbols-outlined text-xl"
              style={{ color: "var(--accent-amber)" }}
            >
              warning
            </span>
            Change your default password
          </h2>
          <p className="text-sm text-on-surface-variant/85 leading-relaxed">
            You&apos;re signed in with the bootstrap default password
            (random per-install, sourced from{" "}
            <code className="font-mono">PHANTOM_DEFAULT_ADMIN_PASSWORD</code>{" "}
            in your <code className="font-mono">.env</code>).
            Change it below before doing anything else. After you save,
            all current sessions will sign out and you&apos;ll be asked
            to sign in again with your new password.
          </p>
        </section>
      )}

      {/* Account section */}
      <section
        className="rounded-2xl p-8 space-y-4"
        style={glassPanel}
      >
        <h2 className="font-headline font-semibold text-lg text-on-surface">
          Account
        </h2>
        <div className="flex items-center gap-5">
          <div
            className="w-14 h-14 rounded-full flex items-center justify-center"
            style={{ background: "rgba(45, 141, 240, 0.15)" }}
          >
            <span className="material-symbols-outlined text-2xl text-primary">
              person
            </span>
          </div>
          <div>
            <p className="text-base font-medium text-on-surface">{username}</p>
            <p className="text-xs uppercase tracking-wider text-on-surface-variant/70 mt-0.5">
              Platform Admin
            </p>
          </div>
        </div>
        {/*
          NOTE (intentionally NOT shown on this page): the system is
          single-user — username is fixed. Additional access is via API
          keys minted at /settings/api-keys. The forgot-password CLI
          path is documented at /help/user#authentication. Keep these
          notes as code comments: this UI is for the admin's day-to-day.
        */}
      </section>

      {/* Change password section */}
      <section
        className="rounded-2xl p-8 space-y-6"
        style={glassPanel}
      >
        <div>
          <h2 className="font-headline font-semibold text-lg text-on-surface">
            Change password
          </h2>
          <p className="text-xs text-on-surface-variant/70 mt-1">
            Your password is hashed with PBKDF2-HMAC-SHA256 and stored
            encrypted at rest in the agent&apos;s SecretStore.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Current password */}
          <div>
            <label
              htmlFor="current-password"
              className="block text-xs font-medium uppercase tracking-wider text-on-surface-variant/80 mb-2"
            >
              Current password
            </label>
            <div className="relative">
              <input
                id="current-password"
                type={showCurrent ? "text" : "password"}
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                autoComplete="current-password"
                className="w-full bg-surface-container-highest border-none rounded-xl px-4 py-3 pr-12 text-sm focus:ring-1 focus:ring-primary/40 transition-all outline-none text-on-surface"
                style={{ border: "0.5px solid var(--glass-border)" }}
                disabled={submitting}
              />
              <button
                type="button"
                onClick={() => setShowCurrent((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-on-surface-variant/70 hover:text-on-surface transition-colors"
                aria-label={showCurrent ? "Hide password" : "Show password"}
                tabIndex={-1}
              >
                <span className="material-symbols-outlined text-[20px]">
                  {showCurrent ? "visibility_off" : "visibility"}
                </span>
              </button>
            </div>
          </div>

          {/* New password */}
          <div>
            <label
              htmlFor="new-password"
              className="block text-xs font-medium uppercase tracking-wider text-on-surface-variant/80 mb-2"
            >
              New password
            </label>
            <div className="relative">
              <input
                id="new-password"
                type={showNew ? "text" : "password"}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoComplete="new-password"
                className="w-full bg-surface-container-highest border-none rounded-xl px-4 py-3 pr-12 text-sm focus:ring-1 focus:ring-primary/40 transition-all outline-none text-on-surface"
                style={{ border: "0.5px solid var(--glass-border)" }}
                disabled={submitting}
              />
              <button
                type="button"
                onClick={() => setShowNew((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-on-surface-variant/70 hover:text-on-surface transition-colors"
                aria-label={showNew ? "Hide password" : "Show password"}
                tabIndex={-1}
              >
                <span className="material-symbols-outlined text-[20px]">
                  {showNew ? "visibility_off" : "visibility"}
                </span>
              </button>
            </div>
            {newPasswordHint && (
              <p className="text-xs text-on-surface-variant/60 mt-2">
                {newPasswordHint}
              </p>
            )}
          </div>

          {/* Confirm new password */}
          <div>
            <label
              htmlFor="confirm-password"
              className="block text-xs font-medium uppercase tracking-wider text-on-surface-variant/80 mb-2"
            >
              Confirm new password
            </label>
            <input
              id="confirm-password"
              type={showNew ? "text" : "password"}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
              className="w-full bg-surface-container-highest border-none rounded-xl px-4 py-3 text-sm focus:ring-1 focus:ring-primary/40 transition-all outline-none text-on-surface"
              style={{ border: "0.5px solid var(--glass-border)" }}
              disabled={submitting}
            />
          </div>

          <div className="flex gap-4 pt-2">
            <button
              type="submit"
              disabled={!canSubmit}
              className="px-8 py-3 rounded-xl font-semibold flex items-center gap-2 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              style={{
                background: canSubmit
                  ? "linear-gradient(to right, #1963b3, #2D8DF0)"
                  : "rgba(52, 51, 64, 0.6)",
                color: canSubmit ? "white" : "rgba(255, 255, 255, 0.3)",
                boxShadow: canSubmit
                  ? "0px 0px 20px rgba(25, 99, 179, 0.3)"
                  : "none",
              }}
            >
              {submitting ? (
                <>
                  <span className="material-symbols-outlined text-[20px] animate-spin">
                    progress_activity
                  </span>
                  Updating…
                </>
              ) : (
                <>
                  <span className="material-symbols-outlined text-[20px]">
                    lock_reset
                  </span>
                  Update password
                </>
              )}
            </button>
          </div>
        </form>
      </section>

      {/* Sign-out section.
        *
        * Visually separated from the credentials block — this is a
        * destructive action by intent (you are deliberately ending
        * your session and will lose any in-flight chat / approval
        * state). Amber accent signals "consequential but reversible"
        * without escalating to red (which we reserve for irreversible
        * actions like password reset).
        *
        * Theme-awareness: all amber tints derive from var(--accent-amber)
        * via color-mix, so the section reads correctly in BOTH themes:
        *   - dark:  --accent-amber = #ffc05f (bright yellow-orange,
        *            shows up against navy bg)
        *   - light: --accent-amber = #b45309 (rust orange, has enough
        *            saturation to stay legible on white bg — the
        *            previous hardcoded #fbca04 looked washed out)
        * Same component, two distinct visual identities. No theme
        * branching needed in JSX. */}
      <section
        className="rounded-2xl p-8 space-y-4"
        style={{
          ...glassPanel,
          border:
            "1px solid color-mix(in srgb, var(--accent-amber) 35%, transparent)",
        }}
      >
        <div className="flex items-start justify-between gap-6">
          <div className="flex-1">
            <h2 className="font-headline font-semibold text-lg text-on-surface flex items-center gap-2">
              <span
                className="material-symbols-outlined text-xl"
                style={{ color: "var(--accent-amber)" }}
              >
                logout
              </span>
              Sign out
            </h2>
            <p className="text-sm text-on-surface-variant/70 mt-2 leading-relaxed">
              End your current session on this device. The
              <code className="font-mono mx-1">phantom_session</code>
              cookie is cleared and the matching server-side session is
              revoked. Other devices that share this session will sign
              out on their next request. In-flight chat streams and
              approval polls will be torn down.
            </p>
          </div>
          <button
            type="button"
            onClick={handleSignOut}
            disabled={signingOut}
            className="px-6 py-3 rounded-xl font-semibold flex items-center gap-2 transition-all disabled:opacity-40 disabled:cursor-not-allowed shrink-0 hover:brightness-110 active:scale-95"
            style={{
              // Tinted-amber background that contrasts in BOTH themes.
              // 18% mix on dark gives a visible warm wash; 22% on light
              // is needed because rust on white is lower-contrast than
              // bright yellow on navy. Single value via color-mix that
              // happens to read well in both — chosen by eyeballing a
              // Stitch comparison of the two themes side-by-side.
              background:
                "color-mix(in srgb, var(--accent-amber) 22%, transparent)",
              color: "var(--accent-amber)",
              border:
                "1px solid color-mix(in srgb, var(--accent-amber) 55%, transparent)",
            }}
          >
            {signingOut ? (
              <>
                <span className="material-symbols-outlined text-[20px] animate-spin">
                  progress_activity
                </span>
                Signing out…
              </>
            ) : (
              <>
                <span className="material-symbols-outlined text-[20px]">
                  logout
                </span>
                Sign out
              </>
            )}
          </button>
        </div>
      </section>
    </div>
  );
}
