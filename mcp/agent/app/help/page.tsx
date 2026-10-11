/**
 * /help — landing page for the documentation hub.
 *
 * The documentation is split into two focused guides:
 *   /help/user           — operator daily-driver tasks, surface walks,
 *                          slash commands, hook installs, plan mode,
 *                          cost reading, plugin installs, troubleshooting.
 *   /help/architecture   — system internals: 5-service topology,
 *                          chat-route lifecycle, MCP registration,
 *                          subsystem implementation patterns, audit-row
 *                          schemas, REST-endpoint internals, design
 *                          decisions.
 *
 * This page is deliberately tiny: a banner explaining the split + two
 * picker cards. Server-rendered (no "use client"), so the route ships
 * zero JS and statically pre-renders. Operators landing on /help see
 * the choice immediately and pick their path.
 *
 * Specialty pages stay under /help/:
 *   /help/journeys      — task-oriented walkthroughs
 *   /help/journeys/[id] — single journey detail
 *   /help/api           — REST endpoint reference
 *   /help/api/[id]      — single endpoint detail
 */

import Link from "next/link";

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

interface GuideCardProps {
  href: string;
  icon: string;
  title: string;
  audience: string;
  description: string;
  highlights: string[];
  cta: string;
  accent: "primary" | "tertiary";
}

export default function HelpLandingPage() {
  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-16 pb-32 space-y-10">
        {/* Header */}
        <header className="space-y-3">
          <div className="flex items-center gap-3">
            <span className="material-symbols-outlined text-3xl text-primary">
              menu_book
            </span>
            <h1 className="font-headline text-4xl font-bold tracking-tight text-on-surface">
              Help &amp; Documentation
            </h1>
          </div>
          <p className="text-base text-on-surface-variant leading-relaxed max-w-3xl">
            Phantom is a continuous SOC simulation platform: synthetic
            security log generation, MITRE ATT&amp;CK scenario execution,
            detection validation, and AI-orchestrated red/blue workflows.
            The documentation is split into two focused guides so you
            land where you need to be.
          </p>
        </header>

        {/* Two guide cards */}
        <div className="grid md:grid-cols-2 gap-5">
          <GuideCard
            href="/help/user"
            icon="person"
            title="User Guide"
            audience="Operators · daily drivers · SOC analysts"
            description="Walks every operator surface end-to-end. Use this when you're driving the platform: chat, slash commands, plan mode, hooks, tasks, agents, cost rollup, plugins, connector reauth, and the troubleshooting decision tree."
            highlights={[
              "First-run setup walkthrough",
              "Daily workflow (chat → jobs → observability loop)",
              "Slash command + plan-mode UX",
              "Hooks, plugins, agents, connector health",
              "Where-to-look-when troubleshooting tree",
            ]}
            cta="Open User Guide"
            accent="primary"
          />
          <GuideCard
            href="/help/architecture"
            icon="schema"
            title="Architecture Guide"
            audience="Architects · plugin authors · platform extenders"
            description="Deep technical reference for how Phantom is built. Use this when you're extending the platform: the 5-service stack, boot lifecycle, chat-route pipeline, every subsystem (memory, knowledge, skills, hooks, tasks, plan mode, subagents, plugins, jobs, notifications, approvals, models, providers, secret store), the seven external connectors (xlog / CALDERA / XSIAM / Cortex XDR / Cortex Docs / Cortex Content / Web Browser), audit-row schemas, and the design decisions that shaped each substrate."
            highlights={[
              "5-service stack + boot lifecycle + setup wiring",
              "Chat pipeline: lifecycle, fire-sites, tool dispatch, SSE",
              "Context, memory, knowledge, skills",
              "External connectors (7 total: xlog / CALDERA / XSIAM / Cortex XDR / Cortex Docs / Cortex Content / Web Browser)",
              "Auth, secret store, approvals, API keys",
              "Models, providers, jobs, notifications",
              "Substrate composition + design decisions",
            ]}
            cta="Open Architecture Guide"
            accent="tertiary"
          />
        </div>

        {/* Specialty references */}
        <section className="space-y-3">
          <h2 className="font-headline text-xl font-bold tracking-tight text-on-surface flex items-center gap-2">
            <span className="material-symbols-outlined text-xl text-primary">
              bookmarks
            </span>
            Specialty references
          </h2>
          <div className="grid sm:grid-cols-2 gap-3">
            <SpecialtyCard
              href="/help/journeys"
              icon="tour"
              title="User Journeys"
              description="Hands-on, step-by-step walkthroughs for common tasks — onboarding a connector, running a full attack simulation, validating detections, installing a Slack policy hook, spawning red/blue subagents."
            />
            <SpecialtyCard
              href="/help/api"
              icon="api"
              title="REST API Reference"
              description="Wire-format reference for every /api/agent/* endpoint — request schema, response shape, auth requirements, cURL examples, downloadable OpenAPI 3.0 spec."
            />
          </div>
        </section>

        {/* Footnote */}
        <p className="text-xs text-on-surface-variant/70 leading-relaxed">
          Architecture-deep anchors (e.g.,{" "}
          <code className="font-mono text-[0.85em] px-1 py-0.5 rounded bg-surface-container-low border border-outline-variant/30">
            #stack
          </code>
          ,{" "}
          <code className="font-mono text-[0.85em] px-1 py-0.5 rounded bg-surface-container-low border border-outline-variant/30">
            #chat-lifecycle
          </code>
          ,{" "}
          <code className="font-mono text-[0.85em] px-1 py-0.5 rounded bg-surface-container-low border border-outline-variant/30">
            #hooks
          </code>
          ) live in{" "}
          <Link
            href="/help/architecture"
            className="text-primary hover:underline"
          >
            /help/architecture
          </Link>
          ; operator-task anchors live in{" "}
          <Link href="/help/user" className="text-primary hover:underline">
            /help/user
          </Link>
          .
        </p>
      </div>
    </div>
  );
}

function GuideCard({
  href,
  icon,
  title,
  audience,
  description,
  highlights,
  cta,
  accent,
}: GuideCardProps) {
  const accentText =
    accent === "tertiary" ? "text-tertiary" : "text-primary";
  return (
    <Link
      href={href}
      className="group rounded-2xl p-6 flex flex-col gap-4 transition-all hover:scale-[1.01]"
      style={glassStyle}
    >
      <div className="flex items-start gap-3">
        <span
          className={`material-symbols-outlined text-3xl ${accentText} shrink-0`}
        >
          {icon}
        </span>
        <div className="space-y-1">
          <h2 className="font-headline text-2xl font-bold tracking-tight text-on-surface">
            {title}
          </h2>
          <div className="text-[11px] uppercase font-semibold tracking-widest text-on-surface-variant/60">
            {audience}
          </div>
        </div>
      </div>
      <p className="text-sm text-on-surface-variant leading-relaxed">
        {description}
      </p>
      <ul className="space-y-1 text-sm text-on-surface-variant flex-1">
        {highlights.map((h) => (
          <li key={h} className="flex items-start gap-2">
            <span
              className={`material-symbols-outlined text-base ${accentText} shrink-0 mt-0.5`}
            >
              chevron_right
            </span>
            <span>{h}</span>
          </li>
        ))}
      </ul>
      <div
        className={`mt-2 inline-flex items-center gap-1.5 text-sm font-semibold ${accentText} group-hover:gap-2.5 transition-all`}
      >
        {cta}
        <span className="material-symbols-outlined text-base">
          arrow_forward
        </span>
      </div>
    </Link>
  );
}

function SpecialtyCard({
  href,
  icon,
  title,
  description,
}: {
  href: string;
  icon: string;
  title: string;
  description: string;
}) {
  return (
    <Link
      href={href}
      className="group rounded-xl p-4 flex items-start gap-3 transition-all hover:scale-[1.01]"
      style={glassStyle}
    >
      <span className="material-symbols-outlined text-2xl text-primary shrink-0">
        {icon}
      </span>
      <div className="flex-1 space-y-1">
        <div className="flex items-center justify-between">
          <h3 className="font-headline text-base font-bold tracking-tight text-on-surface">
            {title}
          </h3>
          <span className="material-symbols-outlined text-base text-on-surface-variant/60 group-hover:text-primary transition-colors">
            arrow_outward
          </span>
        </div>
        <p className="text-xs text-on-surface-variant leading-relaxed">
          {description}
        </p>
      </div>
    </Link>
  );
}
