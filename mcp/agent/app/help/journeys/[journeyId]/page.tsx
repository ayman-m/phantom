"use client";

/**
 * /help/[journeyId] — full walkthrough page for one journey.
 *
 * Renders all six sections of the Journey type:
 *   1. Title + meta (category, difficulty, duration, tools-exercised count)
 *   2. Prompts (with copy-to-clipboard buttons — operator pastes into chat)
 *   3. Tools exercised (asserts; the agent SHOULD invoke these in order)
 *   4. API equivalents (for scripted / curl operators)
 *   5. How to test (numbered ordered steps)
 *   6. Expected result + Verify via (concrete success checks)
 *   7. Related journeys (cross-links)
 *
 * Click-to-copy on prompts uses the Clipboard API; falls back gracefully
 * via execCommand on browsers without clipboard write permission.
 */

import Link from "next/link";
import { notFound, useParams } from "next/navigation";
import { useState } from "react";

import {
  CATEGORY_META,
  COMPONENT_META,
  componentDocUrl,
  getJourneyById,
  type JourneyDifficulty,
} from "@/lib/journeys";
import { useTestedJourneys } from "@/lib/use-tested-journeys";

const glassStyle = {
  background: "var(--glass-bg)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

const difficultyClass: Record<JourneyDifficulty, string> = {
  starter: "bg-secondary/15 text-secondary border-secondary/30",
  intermediate: "bg-primary/15 text-primary border-primary/30",
  advanced: "bg-tertiary/15 text-tertiary border-tertiary/30",
};

const methodClass: Record<string, string> = {
  GET: "bg-secondary/15 text-secondary border-secondary/30",
  POST: "bg-primary/15 text-primary border-primary/30",
  PATCH: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
  DELETE: "bg-error/15 text-error border-error/30",
  PUT: "bg-tertiary/15 text-tertiary border-tertiary/30",
};

export default function JourneyDetailPage() {
  const params = useParams<{ journeyId: string }>();
  const journey = getJourneyById(params.journeyId);
  // Hook always called — even when the journey doesn't exist — to
  // satisfy React's rules-of-hooks. notFound() short-circuits below.
  const { tested, toggle, hydrated } = useTestedJourneys();

  if (!journey) {
    notFound();
  }

  const meta = CATEGORY_META[journey.category];
  const isTested = hydrated && tested.has(journey.id);

  return (
    <div className="p-8 pb-32 max-w-4xl mx-auto">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-2 text-on-surface-variant font-label text-xs uppercase tracking-widest mb-6">
        <Link href="/help/journeys" className="hover:text-primary transition-colors">
          User Journeys
        </Link>
        <span className="material-symbols-outlined text-[14px]">
          chevron_right
        </span>
        <Link
          href={`/help/journeys?category=${journey.category}`}
          className="hover:text-primary transition-colors"
        >
          {meta.label}
        </Link>
        <span className="material-symbols-outlined text-[14px]">
          chevron_right
        </span>
        <span className="text-primary font-bold truncate max-w-md">
          {journey.title}
        </span>
      </nav>

      {/* Header */}
      <header className="mb-10">
        <div className="flex items-start gap-4 mb-3">
          <div className="w-14 h-14 rounded-2xl bg-surface-container flex items-center justify-center shrink-0">
            <span className="material-symbols-outlined text-3xl text-primary">
              {journey.icon}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
              <span
                className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-tighter border ${
                  difficultyClass[journey.difficulty]
                }`}
              >
                {journey.difficulty}
              </span>
              <span className="px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-tighter border bg-white/5 border-white/15 text-on-surface-variant">
                ~{journey.durationMin} min
              </span>
              <span className="px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-tighter border bg-white/5 border-white/15 text-on-surface-variant">
                {meta.label}
              </span>
              {/* Tested badge mirrors the catalog page indicator. Hidden
                  pre-hydration so it doesn't show "Untested" briefly
                  on a journey the operator has actually marked. */}
              {hydrated && isTested && (
                <span className="px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-tighter border bg-secondary/15 text-secondary border-secondary/30 inline-flex items-center gap-1">
                  <span className="material-symbols-outlined text-[12px]">
                    check_circle
                  </span>
                  Tested
                </span>
              )}
            </div>
            <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface leading-tight">
              {journey.title}
            </h1>
            <p className="text-base text-on-surface-variant mt-2 leading-relaxed">
              {journey.summary}
            </p>
            {/* Mark-tested toggle. Sits below the summary so it reads
                as "verdict goes here after you've done the walkthrough"
                rather than competing with the title for attention. */}
            {hydrated && (
              <button
                type="button"
                onClick={() => toggle(journey.id)}
                aria-pressed={isTested}
                className={`mt-4 inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all ${
                  isTested
                    ? "bg-secondary/15 text-secondary border border-secondary/30 hover:bg-secondary/25"
                    : "bg-white/5 text-on-surface-variant border border-white/15 hover:bg-white/10 hover:text-on-surface"
                }`}
              >
                <span className="material-symbols-outlined text-lg">
                  {isTested ? "check_circle" : "radio_button_unchecked"}
                </span>
                {isTested ? "Tested — click to unmark" : "Mark as tested"}
              </button>
            )}
          </div>
        </div>
      </header>

      <div className="space-y-8">
        {/* Section: Architectural components — chips that link to the
            matching section in /help/architecture so an operator reading
            a journey can jump to "what is this subsystem?" Lives above
            the numbered sections because it's reference metadata about
            the journey's surface area, not part of the walkthrough
            itself. */}
        {journey.components.length > 0 && (
          <section
            className="rounded-2xl p-5 space-y-3"
            style={glassStyle}
          >
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-lg text-primary">
                schema
              </span>
              <h2 className="font-headline text-sm font-bold uppercase tracking-widest text-on-surface">
                Components exercised
              </h2>
            </div>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              Architectural subsystems this journey touches. Click a
              chip to read about the subsystem in the architecture
              guide.
            </p>
            <div className="flex flex-wrap gap-2">
              {journey.components.map((c) => {
                const cm = COMPONENT_META[c];
                const url = componentDocUrl(cm);
                return (
                  <Link
                    key={c}
                    href={url}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border bg-white/5 border-white/15 text-on-surface-variant hover:bg-primary/15 hover:border-primary/30 hover:text-primary transition-colors"
                    title={`Open ${url}`}
                  >
                    <span className="material-symbols-outlined text-[14px]">
                      {cm.icon}
                    </span>
                    {cm.label}
                  </Link>
                );
              })}
            </div>
          </section>
        )}

        {/* Prerequisites — guidance-only callout (not numbered).
            Renders before the numbered sections so an operator landing
            on this journey cold sees what setup they're likely missing.
            NOT a hard gate: Phantom doesn't block execution if the
            prerequisite hasn't been completed. */}
        {journey.prerequisites && journey.prerequisites.length > 0 && (
          <section className="rounded-2xl p-5 border border-tertiary/30 bg-tertiary/5">
            <div className="flex items-center gap-2 mb-3">
              <span className="material-symbols-outlined text-tertiary text-lg">
                checklist
              </span>
              <h2 className="text-sm font-bold text-tertiary uppercase tracking-wider">
                Before you start
              </h2>
            </div>
            <p className="text-xs text-on-surface-variant mb-3">
              These journeys set up state this walkthrough assumes is
              already in place. Not a hard requirement — Phantom won&apos;t
              block you — but skipping them usually means the example
              prompts don&apos;t work end-to-end.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {journey.prerequisites.map((preId) => {
                const pre = getJourneyById(preId);
                if (!pre) return null;
                return (
                  <Link
                    key={preId}
                    href={`/help/journeys/${preId}`}
                    className="rounded-xl p-3 flex items-center gap-3 transition-all border border-tertiary/20 bg-tertiary/5 hover:bg-tertiary/10 hover:-translate-y-0.5"
                  >
                    <span className="material-symbols-outlined text-tertiary">
                      {pre.icon}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-on-surface truncate">
                        {pre.title}
                      </p>
                      <p className="text-[10px] text-on-surface-variant/70 truncate">
                        {CATEGORY_META[pre.category].label} ·{" "}
                        {pre.difficulty} · ~{pre.durationMin}min
                      </p>
                    </div>
                    <span className="material-symbols-outlined text-tertiary/60 text-base">
                      arrow_forward
                    </span>
                  </Link>
                );
              })}
            </div>
          </section>
        )}

        {/* Section 1: Prompts */}
        {journey.prompts.length > 0 && (
          <Section
            number="01"
            title="Chat prompts"
            subtitle="Paste into a chat session in the order shown."
          >
            <div className="space-y-3">
              {journey.prompts.map((p, i) => (
                <PromptCard key={i} index={i + 1} prompt={p} />
              ))}
            </div>
          </Section>
        )}

        {/* Section 2: Tools exercised */}
        {journey.toolsExercised.length > 0 && (
          <Section
            number={journey.prompts.length > 0 ? "02" : "01"}
            title="Tools exercised"
            subtitle="The agent should invoke these MCP tools. Watch /observability/events to confirm."
          >
            <div className="rounded-2xl p-5" style={glassStyle}>
              <ol className="space-y-2">
                {journey.toolsExercised.map((t, i) => (
                  <li key={i} className="flex items-center gap-3 group">
                    <span className="font-mono text-[10px] text-on-surface-variant/50 w-6 text-right">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <code className="font-mono text-sm text-primary/90 bg-surface-container-lowest px-2.5 py-1 rounded">
                      {t}
                    </code>
                  </li>
                ))}
              </ol>
            </div>
          </Section>
        )}

        {/* Section 3: API equivalents */}
        {journey.apis.length > 0 && (
          <Section
            number={
              [journey.prompts.length, journey.toolsExercised.length].filter(
                (n) => n > 0,
              ).length === 2
                ? "03"
                : [journey.prompts.length, journey.toolsExercised.length].some(
                      (n) => n > 0,
                    )
                  ? "02"
                  : "01"
            }
            title="API equivalents"
            subtitle="For scripted / curl operators — the same actions over HTTP."
          >
            <div className="space-y-2">
              {journey.apis.map((api, i) => (
                <div
                  key={i}
                  className="rounded-xl p-3 flex items-start gap-3"
                  style={glassStyle}
                >
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-tighter border font-mono shrink-0 ${
                      methodClass[api.method] ?? methodClass.GET
                    }`}
                  >
                    {api.method}
                  </span>
                  <div className="min-w-0 flex-1">
                    <code className="font-mono text-xs text-on-surface block break-all">
                      {api.path}
                    </code>
                    <p className="text-xs text-on-surface-variant mt-1 leading-relaxed">
                      {api.description}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* Section 4: How to test */}
        <Section
          number="04"
          title="How to test"
          subtitle="Step-by-step walkthrough."
        >
          <div className="rounded-2xl p-5" style={glassStyle}>
            <ol className="space-y-3">
              {journey.howToTest.map((step, i) => (
                <li key={i} className="flex gap-3 text-sm leading-relaxed">
                  <span className="font-mono text-xs text-primary/80 w-6 shrink-0">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span className="text-on-surface">{step}</span>
                </li>
              ))}
            </ol>
          </div>
        </Section>

        {/* Section 5: Expected result */}
        <Section
          number="05"
          title="Expected result"
          subtitle="What success looks like."
        >
          <div
            className="rounded-2xl p-5 border-l-2 border-secondary/40 bg-surface-container-lowest"
            style={{ ...glassStyle, borderLeft: "2px solid rgba(123, 220, 123, 0.4)" }}
          >
            <p className="text-sm text-on-surface leading-relaxed">
              {journey.expectedResult}
            </p>
          </div>
        </Section>

        {/* Section 6: Verify via */}
        <Section
          number="06"
          title="Verify via"
          subtitle="Concrete probes that prove the outcome."
        >
          <div className="rounded-2xl p-5" style={glassStyle}>
            <ul className="space-y-2.5">
              {journey.verifyVia.map((step, i) => (
                <li key={i} className="flex gap-3 text-sm leading-relaxed">
                  <span className="material-symbols-outlined text-secondary text-base shrink-0 mt-0.5">
                    check_circle
                  </span>
                  <span className="text-on-surface-variant">
                    {renderInlineCode(step)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </Section>

        {/* Related journeys */}
        {journey.related && journey.related.length > 0 && (
          <Section
            number="07"
            title="Related journeys"
            subtitle="Build on this workflow or share state with it."
          >
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {journey.related.map((relId) => {
                const rel = getJourneyById(relId);
                if (!rel) return null;
                return (
                  <Link
                    key={relId}
                    href={`/help/journeys/${relId}`}
                    className="rounded-xl p-4 flex items-center gap-3 transition-all hover:shadow-[0_0_16px_rgba(25,99,179,0.1)] hover:-translate-y-0.5"
                    style={glassStyle}
                  >
                    <span className="material-symbols-outlined text-primary">
                      {rel.icon}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-on-surface truncate">
                        {rel.title}
                      </p>
                      <p className="text-[10px] text-on-surface-variant/70 truncate">
                        {CATEGORY_META[rel.category].label} ·{" "}
                        {rel.difficulty} · ~{rel.durationMin}min
                      </p>
                    </div>
                    <span className="material-symbols-outlined text-on-surface-variant/40 text-base">
                      chevron_right
                    </span>
                  </Link>
                );
              })}
            </div>
          </Section>
        )}
      </div>
    </div>
  );
}

// ─── Sub-components ─────────────────────────────────────────────────

function Section({
  number,
  title,
  subtitle,
  children,
}: {
  number: string;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-center gap-3">
        <div className="w-1 h-5 rounded-full bg-primary" />
        <h2 className="font-headline text-xs font-bold uppercase tracking-wider text-on-surface">
          {number} — {title}
        </h2>
      </div>
      {subtitle && (
        <p className="text-xs text-on-surface-variant/70 ml-4">{subtitle}</p>
      )}
      {children}
    </section>
  );
}

function PromptCard({
  index,
  prompt,
}: {
  index: number;
  prompt: { text: string; note?: string; newSession?: boolean };
}) {
  const [copied, setCopied] = useState(false);

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(prompt.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // Fallback — old browsers without clipboard API
      const ta = document.createElement("textarea");
      ta.value = prompt.text;
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        setCopied(true);
        setTimeout(() => setCopied(false), 1800);
      } catch {
        // last resort: do nothing — user can manually select + copy
      } finally {
        document.body.removeChild(ta);
      }
    }
  };

  return (
    <div className="rounded-xl p-4" style={glassStyle}>
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] text-on-surface-variant/60">
            Prompt {index}
          </span>
          {prompt.newSession && (
            <span className="px-1.5 py-0.5 rounded text-[9px] uppercase font-bold tracking-tighter bg-tertiary/15 text-tertiary border border-tertiary/30">
              New session
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={onCopy}
          className="flex items-center gap-1 text-[10px] uppercase font-label tracking-wider text-on-surface-variant hover:text-primary transition-colors"
        >
          <span className="material-symbols-outlined text-sm">
            {copied ? "check" : "content_copy"}
          </span>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="font-mono text-sm text-on-surface whitespace-pre-wrap break-words bg-surface-container-lowest p-3 rounded-lg leading-relaxed">
        {prompt.text}
      </pre>
      {prompt.note && (
        <p className="text-xs text-on-surface-variant/80 mt-2 italic leading-relaxed">
          {prompt.note}
        </p>
      )}
    </div>
  );
}

/**
 * Light markdown-style inline-code rendering: text wrapped in backticks
 * gets monospace-styled. Used so journey verifyVia entries can include
 * commands without each author writing JSX.
 */
function renderInlineCode(text: string): React.ReactNode {
  const parts = text.split(/(`[^`]+`)/g);
  return parts.map((part, i) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code
          key={i}
          className="font-mono text-xs text-primary/90 bg-surface-container-lowest px-1.5 py-0.5 rounded"
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    return <span key={i}>{part}</span>;
  });
}
