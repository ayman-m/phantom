"use client";

/**
 * /help — operator-facing journey catalog.
 *
 * Lists every entry in lib/journeys.ts as an interactive grid. Click a
 * card to navigate to /help/[journeyId] for the full walkthrough. Search
 * filters on title, summary, tool names, and prompts; category tabs
 * narrow the list when you want to focus on one workflow.
 *
 * Pattern lifted from spark_ui/app/testing/journeys/page.tsx but
 * restyled for phantom's Ocean Navy + glassmorphism aesthetic — same
 * card pattern as /jobs and /providers. No external UI deps; purely
 * Tailwind classes + inline glass styles.
 */

import Link from "next/link";
import { useMemo, useState } from "react";

import {
  CATEGORY_META,
  COMPONENT_META,
  JOURNEYS,
  type Journey,
  type JourneyCategory,
  type JourneyDifficulty,
  searchJourneys,
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

const CATEGORIES: ("all" | JourneyCategory)[] = [
  "all",
  "onboarding",
  "chat",
  "memory",
  "simulation",
  "redteam",
  "validation",
  "ops",
];

type TestedFilter = "all" | "tested" | "untested";

const TESTED_FILTERS: { value: TestedFilter; label: string; icon: string }[] = [
  { value: "all", label: "All", icon: "list" },
  { value: "tested", label: "Tested", icon: "check_circle" },
  { value: "untested", label: "Untested", icon: "radio_button_unchecked" },
];

export default function HelpPage() {
  const [query, setQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState<
    "all" | JourneyCategory
  >("all");
  const [testedFilter, setTestedFilter] = useState<TestedFilter>("all");
  const { tested, toggle, reset, count: testedCount, hydrated } =
    useTestedJourneys();

  const filtered = useMemo<Journey[]>(() => {
    let result = searchJourneys(query);
    if (activeCategory !== "all") {
      result = result.filter((j) => j.category === activeCategory);
    }
    // The tested-filter is gated on `hydrated` — before localStorage
    // has been read, the in-memory Set is empty, so applying
    // testedFilter="tested" would briefly show "no results" on every
    // page load. Treating pre-hydrate as "all" avoids that flicker.
    if (hydrated) {
      if (testedFilter === "tested") {
        result = result.filter((j) => tested.has(j.id));
      } else if (testedFilter === "untested") {
        result = result.filter((j) => !tested.has(j.id));
      }
    }
    return result;
  }, [query, activeCategory, testedFilter, tested, hydrated]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: JOURNEYS.length };
    for (const j of JOURNEYS) {
      c[j.category] = (c[j.category] ?? 0) + 1;
    }
    return c;
  }, []);

  const untestedCount = JOURNEYS.length - testedCount;

  return (
    <div className="p-8 pb-32 max-w-[1400px] mx-auto">
      {/* Page Header */}
      <header className="mb-8">
        <div className="flex items-center justify-between gap-4 flex-wrap mb-1">
          <div className="flex items-center gap-3">
            <span className="material-symbols-outlined text-2xl text-primary">
              help_outline
            </span>
            <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
              User Journeys
            </h1>
          </div>
          <Link
            href="/help/api"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-on-surface-variant hover:text-on-surface transition-colors border border-on-surface/10 hover:border-on-surface/20"
          >
            <span className="material-symbols-outlined text-lg">api</span>
            REST API Reference
            <span className="material-symbols-outlined text-base">arrow_outward</span>
          </Link>
        </div>
        <p className="text-sm text-on-surface-variant ml-9">
          Reproducible walkthroughs for every Phantom capability — paste a
          prompt, watch what the agent does, verify the outcome. Each journey
          is an end-to-end test you can run today.
        </p>
        {/* Per-operator progress indicator. Stays empty pre-hydration so
            the "0 / N tested" doesn't flash before localStorage loads. */}
        {hydrated && (
          <div className="ml-9 mt-3 flex items-center gap-3 text-xs">
            <div className="flex items-center gap-1.5 text-on-surface-variant">
              <span className="material-symbols-outlined text-base text-secondary">
                check_circle
              </span>
              <span>
                <span className="text-on-surface font-bold">{testedCount}</span>
                <span className="text-on-surface-variant/60">
                  {" "}
                  / {JOURNEYS.length} tested
                </span>
              </span>
            </div>
            {testedCount > 0 && (
              <button
                type="button"
                onClick={() => {
                  if (
                    window.confirm(
                      `Reset all ${testedCount} tested marks? This only affects your browser.`,
                    )
                  ) {
                    reset();
                  }
                }}
                className="text-[10px] uppercase tracking-widest text-on-surface-variant/50 hover:text-error transition-colors"
                title="Clear your local tested marks"
              >
                Reset
              </button>
            )}
          </div>
        )}
      </header>

      {/* Search + category tabs */}
      <div className="mb-8 space-y-4">
        <div className="flex items-center bg-surface-container-highest rounded-xl px-4 py-2.5">
          <span className="material-symbols-outlined text-on-surface-variant/60 text-lg mr-2">
            search
          </span>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by title, tool name, or prompt..."
            className="bg-transparent border-none focus:ring-0 text-sm w-full p-0 text-on-surface placeholder:text-on-surface-variant/40"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              className="text-on-surface-variant/60 hover:text-on-surface text-xs font-label uppercase tracking-wider"
            >
              clear
            </button>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          {CATEGORIES.map((cat) => {
            const meta =
              cat === "all"
                ? { label: "All", icon: "apps" }
                : CATEGORY_META[cat];
            const isActive = activeCategory === cat;
            const count = counts[cat] ?? 0;
            return (
              <button
                key={cat}
                type="button"
                onClick={() => setActiveCategory(cat)}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg font-label text-[11px] uppercase tracking-wider transition-all ${
                  isActive
                    ? "bg-secondary-container/30 border border-secondary/40 text-secondary"
                    : "bg-white/5 border border-white/10 text-on-surface-variant hover:bg-white/10"
                }`}
              >
                <span className="material-symbols-outlined text-base">
                  {meta.icon}
                </span>
                {meta.label}
                <span
                  className={`text-[10px] font-mono ${
                    isActive ? "text-primary/70" : "text-on-surface-variant/50"
                  }`}
                >
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        {/* Tested-status filter — separate row from category tabs so
            the two dimensions compose. "All" is the default; clicking
            "Tested" / "Untested" narrows whatever the category filter
            already produced. Counts shown in chip badge so the operator
            knows what they're about to filter to without clicking. */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[10px] uppercase tracking-widest text-on-surface-variant/60 mr-1">
            Status:
          </span>
          {TESTED_FILTERS.map((opt) => {
            const isActive = testedFilter === opt.value;
            const chipCount =
              opt.value === "tested"
                ? testedCount
                : opt.value === "untested"
                  ? untestedCount
                  : JOURNEYS.length;
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => setTestedFilter(opt.value)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-label text-[10px] uppercase tracking-wider transition-all ${
                  isActive
                    ? "bg-secondary-container/20 border border-secondary/40 text-secondary"
                    : "bg-white/5 border border-white/10 text-on-surface-variant hover:bg-white/10"
                }`}
              >
                <span className="material-symbols-outlined text-sm">
                  {opt.icon}
                </span>
                {opt.label}
                <span
                  className={`text-[9px] font-mono ${
                    isActive ? "text-secondary/70" : "text-on-surface-variant/50"
                  }`}
                >
                  {chipCount}
                </span>
              </button>
            );
          })}
        </div>

        {/* Active category description (shown for non-"all") */}
        {activeCategory !== "all" && (
          <p className="text-xs text-on-surface-variant/70 italic">
            {CATEGORY_META[activeCategory].description}
          </p>
        )}
      </div>

      {/* Journey grid */}
      {filtered.length === 0 ? (
        <div
          className="rounded-2xl p-12 flex flex-col items-center gap-3 text-center"
          style={glassStyle}
        >
          <span className="material-symbols-outlined text-4xl text-on-surface-variant">
            search_off
          </span>
          <p className="text-base font-medium">No journeys match your filters</p>
          <p className="max-w-xl text-sm text-on-surface-variant">
            Try a different category or clear the search box. The catalog has{" "}
            {JOURNEYS.length} journeys across {Object.keys(CATEGORY_META).length}{" "}
            categories.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((journey) => (
            <JourneyCard
              key={journey.id}
              journey={journey}
              isTested={hydrated && tested.has(journey.id)}
              onToggleTested={() => toggle(journey.id)}
            />
          ))}
        </div>
      )}

      {/* Footer hint */}
      <div className="mt-12 rounded-xl p-4 text-xs text-on-surface-variant/70 text-center" style={glassStyle}>
        <span className="material-symbols-outlined text-sm align-middle mr-1">
          tips_and_updates
        </span>
        Adding a new feature? Drop a journey definition into{" "}
        <code className="font-mono text-primary/80 bg-surface-container-lowest px-1.5 py-0.5 rounded">
          mcp/agent/lib/journeys.ts
        </code>{" "}
        — it appears here automatically with no other registration step.
      </div>
    </div>
  );
}

function JourneyCard({
  journey,
  isTested,
  onToggleTested,
}: {
  journey: Journey;
  isTested: boolean;
  onToggleTested: () => void;
}) {
  const meta = CATEGORY_META[journey.category];
  return (
    // Wrapper is a relative <div> so the absolutely-positioned tested
    // toggle (top-right) can intercept clicks before they bubble up to
    // the <Link> wrapper. The Link itself stays the whole-card click
    // target for navigation.
    <div className="relative group">
      <Link
        href={`/help/journeys/${journey.id}`}
        className={`block p-5 rounded-2xl transition-all hover:shadow-[0_0_24px_rgba(25,99,179,0.12)] cursor-pointer hover:-translate-y-0.5 ${
          isTested ? "ring-1 ring-secondary/30" : ""
        }`}
        style={glassStyle}
      >
      {/* Top row: icon + difficulty + duration */}
      <div className="flex items-start justify-between mb-3">
        <div className="w-12 h-12 rounded-xl bg-surface-container flex items-center justify-center">
          <span className="material-symbols-outlined text-primary">
            {journey.icon}
          </span>
        </div>
        <div className="flex flex-col items-end gap-1 mr-9">
          <span
            className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-tighter border ${
              difficultyClass[journey.difficulty]
            }`}
          >
            {journey.difficulty}
          </span>
          <span className="text-[10px] text-on-surface-variant/70 font-mono">
            ~{journey.durationMin}min
          </span>
        </div>
      </div>

      {/* Title + summary */}
      <h3 className="font-headline font-bold text-base text-on-surface mb-1.5 leading-snug">
        {journey.title}
      </h3>
      <p className="text-xs text-on-surface-variant leading-relaxed mb-3 line-clamp-3">
        {journey.summary}
      </p>

      {/* Components row — small chips advertising which architectural
          subsystems the journey exercises. Operator can click through to
          the matching architecture-page anchor for the deep dive. The
          chips render as plain text inside the card-level <Link>; they
          aren't clickable individually because nested links would
          break navigation. The list is shown on the architecture page
          + on the journey detail page where chips ARE links. */}
      {journey.components.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
          {journey.components.slice(0, 5).map((c) => {
            const cm = COMPONENT_META[c];
            return (
              <span
                key={c}
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] uppercase tracking-tighter font-bold border bg-white/5 border-white/10 text-on-surface-variant/80"
                title={cm.label}
              >
                <span className="material-symbols-outlined text-[11px]">
                  {cm.icon}
                </span>
                {cm.label}
              </span>
            );
          })}
          {journey.components.length > 5 && (
            <span className="text-[10px] text-on-surface-variant/60 self-center">
              +{journey.components.length - 5}
            </span>
          )}
        </div>
      )}

      {/* Bottom row: category tag + tool count */}
      <div className="flex items-center justify-between pt-3 border-t border-white/5">
        <div className="flex items-center gap-1.5">
          <span className="material-symbols-outlined text-on-surface-variant/60 text-sm">
            {meta.icon}
          </span>
          <span className="text-[10px] uppercase tracking-wider text-on-surface-variant/70 font-label">
            {meta.label}
          </span>
        </div>
        {journey.toolsExercised.length > 0 && (
          <span className="text-[10px] text-on-surface-variant/60 font-mono">
            {journey.toolsExercised.length} tool
            {journey.toolsExercised.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>
      </Link>

      {/* Tested-toggle: a small clickable circle in the top-right
          corner. preventDefault + stopPropagation prevent the click
          from bubbling to the parent <Link> and navigating away.
          Tested state shows as a filled green check; untested shows
          a subtle empty circle that brightens on hover. */}
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onToggleTested();
        }}
        aria-pressed={isTested}
        aria-label={
          isTested
            ? `Mark "${journey.title}" as untested`
            : `Mark "${journey.title}" as tested`
        }
        title={isTested ? "Tested — click to unmark" : "Mark as tested"}
        className={`absolute top-4 right-4 w-7 h-7 rounded-full flex items-center justify-center transition-all ${
          isTested
            ? "bg-secondary/20 text-secondary hover:bg-secondary/30"
            : "bg-white/5 text-on-surface-variant/40 hover:bg-white/10 hover:text-on-surface-variant opacity-60 group-hover:opacity-100"
        }`}
      >
        <span className="material-symbols-outlined text-[18px]">
          {isTested ? "check_circle" : "radio_button_unchecked"}
        </span>
      </button>
    </div>
  );
}
