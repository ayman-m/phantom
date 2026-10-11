"use client";

/**
 * Phantom login screen.
 *
 * Ported from spark-platform's `services/ui/app/login/page.tsx`:
 * the animations, layout, robot character, wavy background,
 * animated divider, and FlippingText are kept as-is. Adapted three
 * pieces only:
 *
 *  1. Import path: `motion/react` (spark) → `framer-motion`
 *     (phantom). Same package; phantom's package.json pins
 *     `framer-motion ^11.3.6` while spark's pins `motion ^11.13.1`.
 *  2. Response shape: phantom's /api/auth/login returns
 *     `{ ok: true, credentialsChanged }`; spark returned the same
 *     shape but the original LoginScreen checked `data.success`.
 *     This file uses the `{ ok, credentialsChanged }` shape.
 *  3. Branding + copy: "Spark AI" / "Powered by Claude, GPT-4o, …"
 *     replaced with Phantom-relevant first-person capabilities
 *     ("Phantom can [simulate logs, simulate attacks, create
 *     workers, send logs, validate detections, orchestrate
 *     workflows]"). A cycle of third-party brand names would suggest
 *     Phantom was a thin shim over those products; the capability
 *     cycle communicates what Phantom actually does.
 *
 * # Interface contract
 *
 *   <LoginScreen onSuccess={() => void} />
 *
 * AuthGate renders this when /api/auth/status returns
 * `{ authenticated: false }`. On a successful login, the route sets
 * the phantom_session cookie and the component calls `onSuccess`,
 * which re-triggers AuthGate's status poll. Auth state then flips
 * to authenticated; AuthGate may further redirect to /profile if
 * `credentialsChanged === false` (default-credentials banner path).
 *
 * # Dependencies
 *
 *  - `@/components/ui/wavy-background` — canvas-based simplex-noise
 *    waves (already present in phantom, identical to spark).
 *  - `@/components/ui/tools-stack-card` — small showcase card below
 *    the form (already present in phantom, motion-import adapted).
 *  - `/img/myrobo.webp` — 1.6MB decorative character; ported to
 *    phantom's public/img/ from spark public/img/.
 *
 * # What this file does NOT do
 *
 *  - Setup-required redirect — spark had a setup wizard at /setup;
 *    phantom has no setup page, so that branch does not exist.
 *  - Direct window.location navigation — phantom uses the AuthGate
 *    callback so SPA routing handles the post-login flow (chat
 *    landing OR /profile for default-credentials path).
 */

import { FormEvent, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";

import { ToolsStackCard } from "@/components/ui/tools-stack-card";
import { WavyBackground } from "@/components/ui/wavy-background";

export const LoginScreen = ({ onSuccess }: { onSuccess: () => void }) => {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok || !payload.ok) {
        throw new Error(payload.error || "Invalid username or password");
      }
      // Hand back to AuthGate; it will poll /api/auth/status and
      // either land on chat OR redirect to /profile if the operator
      // still has credentialsChanged=false (default password path).
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  const friendlyError = useMemo(() => {
    if (!error) return null;
    const msg = error.toLowerCase();
    if (msg.includes("401") || msg.includes("invalid")) {
      return "Sign in failed. Check your username and password and try again.";
    }
    return error;
  }, [error]);

  return (
    <WavyBackground
      containerClassName="h-full min-h-screen w-full"
      className="h-full min-h-screen w-full text-slate-100"
      colors={["#2563eb", "#0ea5e9", "#14b8a6", "#1d4ed8"]}
      backgroundFill="#020617"
      blur={14}
      speed="slow"
      waveOpacity={0.25}
      waveWidth={42}
    >
      <div className="relative min-h-screen w-full overflow-hidden">
        {/* Robot character — left side, desktop only.
          * Ported verbatim from spark login page. The WebP is
          * encoded at q=82 (172 KB; PSNR 44.5 dB — visually identical
          * to human perception) at full 1365×2048 dimensions.
          * The original is kept as myrobo.webp.original alongside in
          * /public/img/. The mask-image gradient fades
          * the image out toward the right so the login card on the
          * right reads cleanly over the wave background. */}
        <div className="pointer-events-none absolute inset-y-0 left-0 z-[5] hidden w-[42vw] min-w-[320px] max-w-[760px] md:block">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/img/myrobo.webp"
            alt="Phantom assistant"
            className="absolute inset-0 h-full w-full object-contain object-left-bottom opacity-95 [mask-image:linear-gradient(to_right,black_72%,transparent_100%)]"
          />
        </div>

        {/* Login card.
          * 3-column inner grid: form | animated divider | description.
          * On mobile the divider hides and the description stacks
          * under the form. The card itself is offset to the right
          * on md+ so it sits in the negative space of the robot
          * (md:translate-x-36 = ~144px) — matches spark layout exactly. */}
        <div className="relative z-10 flex min-h-screen items-center justify-center px-4 py-8 md:px-8 lg:px-12">
          <div className="w-full max-w-[760px] space-y-4 md:translate-x-36 md:translate-y-14 lg:translate-x-40 lg:translate-y-16">
            <div className="rounded-xl border border-slate-700/70 bg-slate-900/80 p-8 shadow-[0_20px_80px_rgba(15,23,42,0.55)] backdrop-blur">
              <h1 className="text-2xl font-bold">Sign In</h1>
              <div className="mt-6 grid gap-6 md:grid-cols-[1fr_auto_1fr] md:items-start">
                {/* Form */}
                <form onSubmit={onSubmit} className="space-y-4" autoComplete="on">
                  <div>
                    <label className="mb-1 block text-sm text-slate-300">Username</label>
                    <input
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      name="username"
                      className="w-full rounded border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
                      required
                      minLength={3}
                      autoComplete="username"
                      autoCapitalize="none"
                      autoCorrect="off"
                      spellCheck={false}
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-sm text-slate-300">Password</label>
                    <input
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      name="password"
                      className="w-full rounded border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
                      required
                      minLength={3}
                      autoComplete="current-password"
                    />
                  </div>
                  {friendlyError ? (
                    <p className="text-sm text-red-400">{friendlyError}</p>
                  ) : null}
                  <button
                    type="submit"
                    className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-60"
                    disabled={loading}
                  >
                    {loading ? "Signing In..." : "Sign In"}
                  </button>
                </form>

                {/* Animated vertical divider — cyan glow scanning
                  * top-to-bottom on a 3.2s linear loop. Hidden on
                  * mobile (no divider when columns stack). Wave
                  * effect comes from a single motion.div whose y
                  * + opacity animate together. */}
                <div className="relative hidden h-52 w-px overflow-hidden md:block">
                  <motion.div
                    className="absolute inset-x-0 h-20 bg-gradient-to-b from-transparent via-cyan-300/90 to-transparent"
                    animate={{ y: ["-35%", "120%"], opacity: [0, 1, 0] }}
                    transition={{ duration: 3.2, repeat: Infinity, ease: "linear" }}
                  />
                  <div className="absolute inset-0 bg-slate-600/30" />
                </div>

                {/* Description column.
                  * "Phantom can [FlippingText]" framing: a typewriter
                  * cycle in cyan over 6 first-person capabilities.
                  * The cycle reads as "Phantom can
                  * simulate logs · Phantom can simulate attacks · …"
                  * so the operator sees what Phantom does rather
                  * than what it sits on top of. */}
                <div className="md:pl-2 md:pt-1">
                  <p className="text-lg font-semibold text-slate-200">
                    Phantom can{" "}
                    <FlippingText
                      words={[
                        "simulate logs",
                        "simulate attacks",
                        "create workers",
                        "send logs",
                        "validate detections",
                        "run workflows",
                      ]}
                      className="text-cyan-300"
                    />
                  </p>
                  <p className="mt-3 text-sm leading-6 text-slate-300">
                    Continuous SOC simulation. Synthetic security log
                    generation.
                    <br />
                    Scenario-based MITRE ATT&CK telemetry across
                    firewall, EDR, NDR, SaaS.
                    <br />
                    AI-orchestrated red/blue workflows with full audit
                    trail.
                  </p>
                </div>
              </div>
            </div>
            <div className="mt-6 flex justify-center">
              <ToolsStackCard />
            </div>
          </div>
        </div>
      </div>
    </WavyBackground>
  );
};

// ─── FlippingText ─────────────────────────────────────────────────
//
// Letter-by-letter typewriter that cycles a word list. Each character
// fades + rotates in on type; the trailing cursor pulses (blue) and
// flips to red while the word is deleting. Ported verbatim from
// spark login; the animation timings (45ms type, 45ms delete,
// 900ms pause) are unchanged because they look correct as-is.

function FlippingText({
  words,
  className,
}: {
  words: string[];
  className?: string;
}) {
  const [currentWordIndex, setCurrentWordIndex] = useState(0);
  const [visibleCharacters, setVisibleCharacters] = useState(0);
  const [isDeleting, setIsDeleting] = useState(false);
  const currentWord = words[currentWordIndex];

  useEffect(() => {
    const typingSpeed = 45;
    const deletingSpeed = 45;
    const pauseBeforeDelete = 900;
    let timeout: ReturnType<typeof setTimeout> | undefined;

    if (!isDeleting && visibleCharacters < currentWord.length) {
      timeout = setTimeout(
        () => setVisibleCharacters((prev) => prev + 1),
        typingSpeed,
      );
    } else if (!isDeleting && visibleCharacters === currentWord.length) {
      timeout = setTimeout(() => setIsDeleting(true), pauseBeforeDelete);
    } else if (isDeleting && visibleCharacters > 0) {
      timeout = setTimeout(
        () => setVisibleCharacters((prev) => prev - 1),
        deletingSpeed,
      );
    } else if (isDeleting && visibleCharacters === 0) {
      setIsDeleting(false);
      setCurrentWordIndex((prev) => (prev + 1) % words.length);
    }

    return () => {
      if (timeout) clearTimeout(timeout);
    };
  }, [currentWord, isDeleting, visibleCharacters, words.length]);

  return (
    <span className={className}>
      {currentWord
        .substring(0, visibleCharacters)
        .split("")
        .map((char, index) => (
          <motion.span
            key={`${index}-${char}`}
            initial={{ opacity: 0, rotateY: 90, y: 8, filter: "blur(8px)" }}
            animate={{ opacity: 1, rotateY: 0, y: 0, filter: "blur(0px)" }}
            transition={{ duration: 0.25 }}
            className="inline-block"
          >
            {char}
          </motion.span>
        ))}
      <motion.span
        className="ml-1 inline-block h-1.5 w-1.5 rounded-full"
        animate={{
          opacity: [1, 0.25, 1],
          backgroundColor: isDeleting ? "#ef4444" : "#60a5fa",
        }}
        transition={{ duration: 0.7, repeat: Infinity }}
      />
    </span>
  );
};
