"use client";

/**
 * /help/user — operator-focused user guide.
 *
 * Companion to /help/architecture. Operators driving Phantom land here
 * for surface walks; architects extending Phantom go to /help/architecture
 * for the system-internals view. The split keeps each guide useful to
 * its audience without bloating either:
 *
 *   /help                — landing with two cards (User / Architecture)
 *   /help/user           — THIS page; daily-driver operator tasks only
 *   /help/architecture   — system-internals reference for architects
 *
 * What lives here: how to use each operator surface, common workflows,
 * slash commands, hook installation, plan mode, cost reading, plugin
 * install, agents page, connector reauth, troubleshooting decision tree.
 *
 * What lives in /help/architecture: 5-service stack topology, MCP
 * tool-registration internals, bundle layout, audit-row schema, REST
 * endpoint reference, the chat-route lifecycle, every subsystem&apos;s
 * implementation pattern, design decisions.
 *
 * Specialty pages live underneath:
 *   /help/journeys      — task-oriented walkthroughs
 *   /help/journeys/[id] — single journey detail
 *   /help/api           — REST endpoint reference
 *   /help/api/[id]      — single endpoint detail
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import {
  AuthLoginFlow,
  AuthChangePasswordFlow,
  AuthCliResetFlow,
} from "@/components/diagrams/auth-flows";
import { OperatorDailyLoop } from "@/components/diagrams/operator-daily-loop";

interface SectionDef {
  id: string;
  label: string;
  group: string;
  icon: string;
}

const SECTIONS: SectionDef[] = [
  { id: "overview", label: "What Phantom is", group: "Welcome", icon: "explore" },
  { id: "daily-workflow", label: "Daily Workflow", group: "Welcome", icon: "loop" },
  { id: "authentication", label: "Authentication", group: "Welcome", icon: "lock_person" },
  { id: "profile", label: "Your Profile", group: "Welcome", icon: "person" },
  { id: "upgrades", label: "Upgrading Phantom", group: "Welcome", icon: "system_update" },
  { id: "ui-tour", label: "Operator UI Tour", group: "Welcome", icon: "tour" },

  { id: "chat", label: "Chat", group: "Command", icon: "chat_bubble" },
  { id: "slash-commands", label: "Slash Commands", group: "Command", icon: "terminal" },
  { id: "plan-mode-ux", label: "Plan Mode", group: "Command", icon: "checklist" },
  { id: "tasks-ux", label: "Tasks", group: "Command", icon: "task_alt" },
  { id: "skills", label: "Skills", group: "Command", icon: "auto_awesome" },
  { id: "agents-ux", label: "Agents", group: "Command", icon: "smart_toy" },
  { id: "memory", label: "Memory", group: "Command", icon: "database" },
  { id: "knowledge", label: "Knowledge Bases", group: "Command", icon: "menu_book" },
  { id: "jobs", label: "Jobs", group: "Command", icon: "schedule" },
  { id: "models-providers", label: "Models & Providers", group: "Command", icon: "psychology" },

  { id: "connectors", label: "Connectors & Instances", group: "Integration", icon: "cable" },
  { id: "connector-health-ux", label: "Connector Health", group: "Integration", icon: "monitor_heart" },
  { id: "marketplace", label: "Marketplace", group: "Integration", icon: "storefront" },
  { id: "data-sources", label: "Data Sources", group: "Integration", icon: "dataset" },
  { id: "log-destinations-ux", label: "Log Destinations", group: "Integration", icon: "cloud_upload" },
  { id: "plugins-ux", label: "Plugins", group: "Integration", icon: "extension" },
  { id: "hooks-ux", label: "Hooks", group: "Integration", icon: "webhook" },
  { id: "approvals", label: "Approvals", group: "Integration", icon: "fact_check" },
  { id: "notifications", label: "Notifications", group: "Integration", icon: "notifications" },
  { id: "api-keys", label: "API Keys", group: "Integration", icon: "vpn_key" },

  { id: "obs-pipeline", label: "Pipeline Health", group: "Observability", icon: "account_tree" },
  { id: "obs-metrics", label: "Metrics & Traces", group: "Observability", icon: "monitoring" },
  { id: "obs-logs", label: "Logs & Events", group: "Observability", icon: "terminal" },
  { id: "cost-ux", label: "Cost Rollup", group: "Observability", icon: "payments" },
  { id: "obs-activity", label: "Live Activity", group: "Observability", icon: "history_toggle_off" },
  { id: "detection-inventory", label: "Detection Inventory", group: "Observability", icon: "dashboard" },

  { id: "settings-services", label: "Services", group: "Settings", icon: "tune" },
  { id: "settings-personality", label: "Personality", group: "Settings", icon: "psychology_alt" },
  { id: "backup-restore", label: "Backup & Restore", group: "Settings", icon: "save" },
  { id: "settings-precedence", label: "Where Settings Live", group: "Settings", icon: "layers" },

  { id: "troubleshoot", label: "Where to Look When…", group: "Troubleshooting", icon: "support" },

  { id: "ref-architecture", label: "Architecture Guide", group: "References", icon: "schema" },
  { id: "ref-journeys", label: "User Journeys", group: "References", icon: "tour" },
  { id: "ref-api", label: "REST API", group: "References", icon: "api" },
];

const GROUP_ORDER = [
  "Welcome",
  "Command",
  "Integration",
  "Observability",
  "Settings",
  "Troubleshooting",
  "References",
] as const;

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

export default function HelpPage() {
  const [active, setActive] = useState<string>(SECTIONS[0]?.id ?? "");
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const visible = new Map<string, number>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            visible.set(e.target.id, e.intersectionRatio);
          } else {
            visible.delete(e.target.id);
          }
        }
        let chosen: string | null = null;
        for (const s of SECTIONS) {
          if (visible.has(s.id)) {
            chosen = s.id;
            break;
          }
        }
        if (chosen) setActive(chosen);
      },
      {
        rootMargin: "-20% 0px -60% 0px",
        threshold: [0, 0.25, 0.5, 1],
      },
    );

    for (const s of SECTIONS) {
      const el = document.getElementById(s.id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);

  function handleNavClick(id: string) {
    const el = document.getElementById(id);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    setActive(id);
  }

  // Section nav collapses INDEPENDENTLY of route navigation.
  // Same shape as the architecture page's collapse toggle. Operators
  // who want more horizontal room get it without losing their place.
  // Persisted in localStorage so the preference survives page reloads.
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(
        "phantom.help.user.sidebar-collapsed",
      );
      if (stored === "true") setSidebarCollapsed(true);
    } catch {
      // localStorage unavailable — accept default (expanded)
    }
  }, []);
  useEffect(() => {
    try {
      window.localStorage.setItem(
        "phantom.help.user.sidebar-collapsed",
        sidebarCollapsed ? "true" : "false",
      );
    } catch {
      // silent skip
    }
  }, [sidebarCollapsed]);

  return (
    <div className="h-screen overflow-hidden flex">
      {/* ── Left rail: sticky table of contents (expanded) ───── */}
      {!sidebarCollapsed && (
        <aside
          className="hidden lg:block w-80 shrink-0 border-r border-outline-variant/20 overflow-y-auto custom-scrollbar"
          aria-label="Help navigation"
        >
          <div className="p-6 sticky top-0">
            <div className="flex items-center justify-between gap-2 mb-1">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-2xl text-primary">
                  help_outline
                </span>
                <h2 className="font-headline text-xl font-bold tracking-tight text-on-surface">
                  Help
                </h2>
              </div>
              <button
                type="button"
                onClick={() => setSidebarCollapsed(true)}
                className="w-7 h-7 flex items-center justify-center rounded-md text-on-surface-variant/70 hover:text-on-surface hover:bg-white/5 transition-colors"
                aria-label="Collapse section navigation"
                title="Collapse navigation (stays on this page)"
              >
                <span className="material-symbols-outlined text-lg">
                  chevron_left
                </span>
              </button>
            </div>
            <p className="text-sm text-on-surface-variant/80 mb-5 leading-relaxed">
              Operator guide to every Phantom capability. Click a section to
              jump.
            </p>

            <nav className="space-y-5">
              {GROUP_ORDER.map((group) => {
                const items = SECTIONS.filter((s) => s.group === group);
                if (items.length === 0) return null;
                return (
                  <div key={group}>
                    <div className="text-xs font-bold uppercase tracking-widest text-on-surface-variant/70 mb-2 px-2">
                      {group}
                    </div>
                    <div className="space-y-0.5">
                      {items.map((s) => {
                        const isActive = active === s.id;
                        return (
                          <button
                            key={s.id}
                            type="button"
                            onClick={() => handleNavClick(s.id)}
                            className={
                              "w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-sm text-left transition-colors " +
                              (isActive
                                ? "bg-secondary-container/30 text-secondary font-semibold"
                                : "text-on-surface-variant hover:bg-surface-container-low/50 hover:text-on-surface")
                            }
                            aria-current={isActive ? "true" : undefined}
                          >
                            <span className="material-symbols-outlined text-base">
                              {s.icon}
                            </span>
                            <span className="truncate">{s.label}</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </nav>
          </div>
        </aside>
      )}

      {/* ── Left rail: collapsed mini-rail ────────────────────── */}
      {sidebarCollapsed && (
        <aside
          className="hidden lg:flex w-10 shrink-0 flex-col items-center pt-5 border-r border-outline-variant/20"
          aria-label="Help navigation (collapsed)"
        >
          <button
            type="button"
            onClick={() => setSidebarCollapsed(false)}
            className="w-7 h-7 flex items-center justify-center rounded-md text-on-surface-variant/70 hover:text-on-surface hover:bg-white/5 transition-colors"
            aria-label="Expand section navigation"
            title="Expand navigation"
          >
            <span className="material-symbols-outlined text-lg">
              chevron_right
            </span>
          </button>
        </aside>
      )}

      {/* ── Main content
          Content uses the full viewport width up to a 1400px ceiling
          (typography is still readable at that width because the
          inner reading-flow elements wrap naturally; pre-formatted
          blocks scroll inside their own boxes). Body text uses
          text-base for the same readability reasons. */}
      <div
        ref={containerRef}
        className="flex-1 overflow-y-auto custom-scrollbar text-base"
      >
        <div className="px-10 py-12 pb-32 space-y-16 max-w-[1400px]">
          {/* Header */}
          <header>
            <div className="flex items-center gap-3 mb-2">
              <span className="material-symbols-outlined text-3xl text-primary">
                menu_book
              </span>
              <h1 className="font-headline text-4xl font-bold tracking-tight text-on-surface">
                User Guide
              </h1>
            </div>
            <p className="text-base text-on-surface-variant leading-relaxed">
              Phantom is a continuous SOC simulation platform: it generates
              synthetic security telemetry, runs MITRE ATT&amp;CK scenarios,
              validates detections, and orchestrates red/blue workflows
              through an AI agent surface. This guide walks every operator
              surface end-to-end — what it does, where it lives in the UI,
              and how to drive it day-to-day.
            </p>
            <div
              className="mt-4 rounded-xl p-4 flex items-start gap-3"
              style={glassStyle}
            >
              <span className="material-symbols-outlined text-base text-tertiary shrink-0 mt-0.5">
                schema
              </span>
              <div className="text-sm text-on-surface leading-relaxed flex-1">
                <span className="font-semibold">Looking for technical
                depth?</span>{" "}
                The 5-service stack, boot lifecycle, chat-route
                pipeline, every subsystem&apos;s implementation
                (memory, knowledge, skills, hooks, tasks, plan mode,
                subagents, plugins, jobs, notifications, approvals,
                models, providers, secret store, audit log), and the
                nine external connectors (xlog / CALDERA / XSIAM / Cortex XDR / Cortex Docs / Cortex Content / Web Browser / HTTP Sender / WEC Sender)
                live in the dedicated{" "}
                <Link
                  href="/help/architecture"
                  className="text-primary hover:underline font-semibold"
                >
                  Architecture Guide
                </Link>
                . This page focuses on operator tasks.
              </div>
            </div>
          </header>

          {/* ============================================================
                                   WELCOME
              ============================================================ */}

          <Section id="overview" icon="explore" title="What Phantom is">
            <p>
              Phantom packages a SOC adversary lab into a four-container
              Docker stack. The agent is the human-facing surface — a
              Next.js UI where you chat, run jobs, configure connectors,
              and watch telemetry. Behind it sits an MCP server that
              aggregates roughly 80 tools from three connectors:{" "}
              <Term>xlog</Term> for synthetic log generation,{" "}
              <Term>caldera</Term> for MITRE ATT&amp;CK adversary
              emulation, and <Term>xsiam</Term> for Cortex XSIAM
              detection validation. A red-team backend (Caldera 5.3) runs
              alongside, dispatched to via the caldera connector.
            </p>
            <p>
              The intended workflow is: synthesize realistic-looking
              telemetry → run an adversary scenario against it → check
              whether your detection content fired correctly → iterate.
              The agent orchestrates all of that through natural-language
              chat plus optional scheduled jobs. You don&apos;t need to
              wait for real attacks to pressure-test detection content;
              Phantom gives you a repeatable lab on demand.
            </p>
            <p>
              Who&apos;s it for? <Term>SOC tier-1 / tier-2 analysts</Term>{" "}
              who want practice at running playbooks end-to-end without
              waiting for a real incident. <Term>Red-team operators</Term>{" "}
              iterating on ATT&amp;CK chains and looking for a fast way to
              materialize them in telemetry.{" "}
              <Term>Detection engineers</Term> who need to validate that a
              new SIEM rule actually fires when its pre-conditions are met
              — and continue firing as the platform evolves underneath.
            </p>
            <p>
              What it&apos;s not: a SIEM (it produces telemetry, doesn&apos;t
              consume real telemetry); a real attack platform (every
              connector is sandboxed); or a turnkey MSSP (it requires an
              operator to design what to test). Think of it as the
              <em> repeatable rehearsal space</em> between your detection
              authoring tools and your production SOC.
            </p>
            <Callout tone="info">
              Phantom ships zero native tools — every capability comes from
              the bundled connectors or runtime built-ins (memory,
              sessions, knowledge search). That keeps the surface honest:
              what you see in <Link href="/skills" className="link">/skills</Link>{" "}
              is what the agent can actually do.
            </Callout>
          </Section>

          <Section id="daily-workflow" icon="loop" title="Your Daily Workflow">
            <p>
              Three surfaces handle most of what you do day-to-day. The
              diagram below shows the typical loop and the side-branches
              that automate or gate parts of it.
            </p>

            <OperatorDailyLoop />

            <SubSection icon="chat_bubble" title="Chat — for ad-hoc work">
              <p>
                Type a request — &ldquo;send 5 firewall logs to
                udp:10.0.0.8:514&rdquo; or &ldquo;run a port scan against
                10.10.20.5&rdquo; — and the agent dispatches the right tool.
                For sensitive operations (creating jobs, deleting
                instances), an approval card appears inline when the
                install gates that tool (see{" "}
                <Link href="#approvals" className="link">Approvals</Link>;
                none are gated in this release); click Approve to unblock
                the call. Every chat session is
                browseable in the left sidebar; sessions persist for 30
                days.
              </p>
            </SubSection>

            <SubSection icon="schedule" title="Jobs — for scheduled work">
              <p>
                A job has a name, a cron, an action (chat / tool_call /
                log), and persists across restarts. Click a card to see its
                run history with the model&apos;s reply for chat actions or
                the tool result for tool_call. Two creation paths: declared
                in <Code>manifest.yaml:jobs[]</Code> (reconciled at boot,
                manifest is source of truth) or via the{" "}
                <Link href="/jobs/new" className="link">
                  Create Job form
                </Link>{" "}
                (operator-owned, survives boot).
              </p>
            </SubSection>

            <SubSection icon="monitoring" title="Observability — when something looks off">
              <p>
                Six surfaces share a unified Lucene-light query bar:{" "}
                <Term>Pipeline</Term> (component health graph),{" "}
                <Term>Events</Term> (paginated audit log), <Term>Logs</Term>{" "}
                (live SSE tail), <Term>Traces</Term> (span-flavored audit
                view), <Term>Metrics</Term> (Prometheus text), and{" "}
                <Term>Live Activity</Term> (streaming recent events). Every
                job card has icon buttons that deep-link with the right
                filter pre-applied.
              </p>
            </SubSection>

            <p className="pt-2">
              The loop in practice: you author a detection in your SIEM →
              switch to chat and ask the agent to run the matching attack
              scenario → watch the pipeline graph turn briefly amber as
              the connectors fire → check Events for the audit trail →
              confirm in your SIEM that the rule matched → if not, iterate.
              When you have a workflow that&apos;s working, promote it to a
              job for scheduled, repeatable runs.
            </p>
          </Section>

          <Section id="authentication" icon="lock_person" title="Authentication">
            <p>
              First boot drops you at a sign-in screen — no setup
              wizard, no questionnaire, just a username + password
              form. Sign in with the default credentials shown below,
              change them on first use, and you&apos;re in.
            </p>

            <SubSection icon="login" title="First-time login">
              <p>
                The installer auto-generates a random admin
                password per install and writes it to{" "}
                <Code>/opt/phantom/.env</Code> as{" "}
                <Code>PHANTOM_DEFAULT_ADMIN_PASSWORD</Code>. No
                credential is baked into the phantom-agent image. You
                see the value in three places:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>The installer&apos;s &ldquo;First-time login&rdquo; banner at the end of <Code>sudo ./phantom-installer</Code>.</li>
                <li>Inside <Code>/opt/phantom/.env</Code> under <Code>PHANTOM_DEFAULT_ADMIN_PASSWORD</Code> (mode 0600; root or installer-user only).</li>
                <li>Docker logs of the agent on the FIRST boot only — the entrypoint prints a credentials banner once when it seeds. Subsequent boots stay quiet (already-initialized branch).</li>
              </ul>
              <Pre>{`username:  admin
password:  <value of PHANTOM_DEFAULT_ADMIN_PASSWORD from .env>`}</Pre>
              <p>
                Sign in. The UI will show a non-dismissible amber
                banner and auto-redirect you to <Code>/profile</Code>{" "}
                to change the password. You can&apos;t navigate
                anywhere else until you do. After you complete the
                change, the value in <Code>.env</Code> is never
                consulted again — your operator-set password lives
                in <Code>SecretStore</Code>, encrypted at rest with{" "}
                <Code>PHANTOM_SECRET_KEK</Code>.
              </p>
              <p>
                If you lose the random value before completing the forced first-login change, run{" "}
                <Code>sudo /opt/phantom/phantom-reset-admin-password</Code> from the host to set a new one interactively.
              </p>
              <AuthLoginFlow />
            </SubSection>

            <SubSection icon="key" title="Authenticate with an API key">
              <p>
                For scripts, schedulers, CI, or any tool that drives the
                agent without a browser session, mint an{" "}
                <strong>API key</strong> instead of using your password.
                Go to <Code>/api-keys</Code>, click <strong>Create Key</strong>,
                pick a scope, and copy the key (shown once).
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>Send it as <Code>Authorization: Bearer phantom_ak_…</Code> to <Code>/api/chat</Code> or any <Code>/api/agent/*</Code> route.</li>
                <li>Scopes: <Code>agent:read</Code> (read-only), <Code>agent:write</Code> (includes running chat turns + mutations), <Code>agent:*</Code> (full non-credential access).</li>
                <li>Keys can never reach credential settings (providers, connector instances, API-key management) — those always require a logged-in session, so a leaked key stays bounded.</li>
                <li>Revoke any key instantly from <Code>/api-keys</Code>; it stops working within ~30 seconds.</li>
              </ul>
            </SubSection>

            <SubSection icon="lock_reset" title="Changing your password">
              <p>
                Go to <Code>/profile</Code> (linked in the sidebar
                under your username, or auto-redirected on first login).
                The form asks for your current password, new password,
                and confirm. Save:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>The server overwrites your password hash in the SecretStore (PBKDF2-HMAC-SHA256 at 600k iterations, encrypted at rest).</li>
                <li>All your active sessions are revoked server-side — including the one you used to make the change. Other tabs / devices sign out on their next API call.</li>
                <li>A security notification gets posted to <Code>/notifications</Code>: <em>&ldquo;Your password was changed at &lt;timestamp&gt;&rdquo;</em>. Canary if someone else ever changes it.</li>
                <li>You&apos;re force-logged-out and bounced back to the sign-in screen. Use your new password.</li>
              </ul>
              <p>
                The username (<Code>admin</Code>) is fixed.
                Share access via per-integration API keys minted at{" "}
                <Code>/api-keys</Code> — wired to the real MCP{" "}
                <Code>api_keys</Code> store, scoped by advisory
                scopes like <Code>audit:read</Code> or{" "}
                <Code>tools:call</Code>.
              </p>
              <AuthChangePasswordFlow />
            </SubSection>

            <SubSection icon="terminal" title="Forgot your password (host utility)">
              <p>
                If you can&apos;t log in (forgot the password, no
                browser session), reset from the host shell. No old
                password needed — the trust boundary is shell access
                to the machine running Phantom. A host script for
                this is installed at <Code>/opt/phantom/</Code>{" "}
                by every fresh installer run:
              </p>
              <Pre>{`# From the host running phantom-agent:
sudo /opt/phantom/phantom-reset-admin-password`}</Pre>
              <p>
                The wrapper validates the agent container is running,
                then exec-replaces itself with the in-container CLI.
                The CLI asks you to type <Code>RESET</Code> to confirm
                (prevents fat-finger triggers), then prompts for a new
                password twice. On success it tells you to restart the
                agent container so any in-memory caches get flushed:
              </p>
              <Pre>{`docker compose restart phantom-agent`}</Pre>
              <p>
                Then sign in with the new password as usual. The
                legacy invocation <Code>docker exec -it phantom_agent node /app/cli/reset-admin.mjs</Code>{" "}
                still works — the host script is just a thin wrapper
                around exactly that command. Use whichever is in your
                muscle memory.
              </p>
              <p className="text-sm text-on-surface-variant">
                <strong>Non-interactive mode (scripted /
                remote SSH / no-TTY contexts):</strong> the CLI accepts
                a <Code>--password-stdin --skip-confirm</Code> flag pair.{" "}
                <Code>--password-stdin</Code> reads the new password from
                stdin (the whole stream, with one trailing newline
                removed) instead of prompting, and refuses to run without{" "}
                <Code>--skip-confirm</Code>, which skips the typed{" "}
                <Code>RESET</Code> confirmation. There is no retype
                prompt, so check the password before you pipe it; it must
                be at least 8 characters. On success the CLI prints the
                number of sessions revoked and exits 0; on any error it
                prints <Code>ERROR:</Code> and exits non-zero. Unlike the
                interactive run it does not print the restart reminder,
                so restart the agent container as shown above:
              </p>
              <Pre>{`echo -n 'NewPassword' | docker exec -i phantom_agent \\
  node /app/cli/reset-admin.mjs --password-stdin --skip-confirm`}</Pre>
              <AuthCliResetFlow />
            </SubSection>

            <SubSection icon="restart_alt" title="Factory reset (host utility)">
              <p>
                If you want to start over from the customer-fresh
                shipped state — same blank-canvas Phantom a brand-new
                install boots into — use the factory-reset script.
                It&apos;s host-side by physical necessity (a container
                can&apos;t delete the docker volume it&apos;s mounting),
                ships in every install kit at{" "}
                <Code>/opt/phantom/</Code>, and asks for typed
                confirmation before wiping anything:
              </p>
              <Pre>{`# Show the plan without doing anything:
sudo /opt/phantom/phantom-factory-reset --dry-run

# Actually wipe + re-install:
sudo /opt/phantom/phantom-factory-reset

# Skip the 'Type FACTORY RESET' prompt (scripted use only):
sudo /opt/phantom/phantom-factory-reset --yes`}</Pre>
              <p>
                What gets wiped: every <Code>phantom_*</Code> docker
                volume (memories, instances + their secrets, API keys,
                audit log, sessions, jobs, notifications, journey-tested
                marks, metrics bookmarks, TLS certs, skills volume).
                After the wipe the script re-runs the installer so the
                stack comes back up healthy with shipped defaults.
              </p>
              <p>
                What survives: <Code>/opt/phantom/.env</Code> (so your{" "}
                <Code>PHANTOM_SECRET_KEK</Code>
                + any operator-managed env vars are intact across the
                reset), the docker images already on disk (no image
                pulls needed for the recovery install), and both
                recovery scripts themselves.
              </p>
              <p>
                When the script returns, the UI shows the default
                first-login screen again — sign in with{" "}
                <Code>admin</Code> and the value of{" "}
                <Code>PHANTOM_DEFAULT_ADMIN_PASSWORD</Code> from{" "}
                <Code>/opt/phantom/.env</Code>. The installer&apos;s
                output banner shows this on screen, and you can{" "}
                <Code>grep PHANTOM_DEFAULT</Code>{" "}
                <Code>/opt/phantom/.env</Code> any time to retrieve
                it. The agent walks you through changing the
                password at <Code>/profile</Code> just like a fresh
                install.
              </p>
            </SubSection>

            <SubSection icon="visibility" title="Checking auth events in observability">
              <p>
                Every login, every password change, every session
                lifecycle event is recorded in Phantom&apos;s audit
                log. You don&apos;t have to trust that things worked —
                you can see them. Two places to look:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Code>/observability/events</Code> — the structured
                  audit stream. Filter or scroll to find your action.
                  Each row shows <em>when</em>, <em>who</em> (you, the
                  CLI, or the system), and <em>what</em> happened.
                </li>
                <li>
                  <Code>/notifications</Code> — the security canary.
                  Every password change posts a notification
                  &ldquo;Your password was changed at &lt;timestamp&gt;.&rdquo;
                  If you see one you didn&apos;t make, that&apos;s the
                  signal to investigate.
                </li>
              </ul>
              <p>
                What to expect to see for each path you&apos;ve walked:
              </p>
              <Pre>{`After a successful first-time login (default credentials):
  login_success        user:admin        user:admin

After changing your password from /profile:
  password_changed_ui  user:admin        user:admin
  session_revoked      system            session:<id>     × (N revoked sessions)
  + a /notifications entry about the change

After a CLI reset (forgot-password path):
  password_changed_cli cli:<hostname>    user:admin
  session_revoked      system            session:<id>     × (N revoked sessions)
  + a /notifications entry about the change

After a failed login attempt:
  login_failed         ip:<source>       user:admin
  (if you cross the 5-fails/60s threshold, you'll see one more
   row marking the rate-limit lockout)`}</Pre>
              <p>
                If the action you took doesn&apos;t show up in{" "}
                <Code>/observability/events</Code>, that&apos;s a real
                problem to report — every auth path is supposed to be
                auditable. Conversely, if you see events you{" "}
                <em>didn&apos;t</em> make (especially{" "}
                <Code>password_changed_cli</Code> with an unfamiliar
                hostname), treat it as a host-compromise signal and
                investigate.
              </p>
            </SubSection>

            <SubSection icon="help" title="What if&hellip;">
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li><strong>The default credentials banner doesn&apos;t go away after changing the password.</strong> Hard-refresh the page (clears the AuthGate&apos;s cached state). If it persists, check the docker logs for entrypoint errors during the auth seed.</li>
                <li><strong>Login says &ldquo;Authentication service unavailable.&rdquo;</strong> The agent can&apos;t reach the MCP. Check <Code>docker compose ps</Code> — phantom-agent should be <Code>Up (healthy)</Code>.</li>
                <li><strong>Login says &ldquo;Too many failed attempts. Try again in Ns.&rdquo;</strong> Per-IP rate limit fired (5 failures in 60s). Wait it out; the lockout is 60s.</li>
                <li><strong>You changed your password and another tab still loads.</strong> The server-side cache is up to 30s. Click around — the next API call will get 401 and bounce you to sign in. (Or wait 30s.)</li>
                <li><strong>You upgrade Phantom and your password stops working.</strong> Auth state lives on the persistent <Code>phantom_data</Code> volume. As long as the volume isn&apos;t dropped (<Code>docker compose down -v</Code> would do that), credentials survive upgrades. If you DID drop the volume, you&apos;re back to the default credentials banner.</li>
              </ul>
            </SubSection>

            <SubSection icon="security" title="Where credentials live">
              <p>
                Phantom&apos;s admin password lives in EXACTLY one
                place: the SecretStore at{" "}
                <Code>/app/data/secrets/ui/auth/admin/</Code>{" "}
                inside the agent container (mapped to the{" "}
                <Code>phantom_data</Code> docker volume). It&apos;s
                stored as a PBKDF2-HMAC-SHA256 hash with a 32-byte
                random salt and 600,000 iterations, then encrypted at
                rest with the SecretStore&apos;s KEK-derived AES-256-GCM
                cipher.
              </p>
              <p>
                Session cookies are random 32-byte tokens. The server
                stores their SHA-256 hash + metadata (username, expiry,
                user-agent fingerprint) in{" "}
                <Code>auth_sessions.db</Code>, never the raw token.
                Cookies are <Code>HttpOnly</Code> +{" "}
                <Code>Secure</Code> + <Code>SameSite=Strict</Code> with
                a 2-hour absolute expiry, no remember-me. Each session
                is independently revocable; a successful password
                change revokes them all.
              </p>
            </SubSection>

            <SubSection
              icon="shield"
              title="API surface is server-side gated"
            >
              <p>
                Every <Code>/api/agent/*</Code> endpoint, plus{" "}
                <Code>/api/chat</Code> and <Code>/api/skills/*</Code>,
                requires a valid <Code>phantom_session</Code> cookie on
                EVERY request. The check happens at a Next.js
                middleware layer before any route handler runs — same
                cookie the UI uses, same validation path{" "}
                <Code>/api/auth/status</Code> uses.
              </p>
              <p>
                If you script against the Phantom API (curl, Python
                requests, etc.), include the session cookie in every
                call:
              </p>
              <Pre>{`# 1. Log in to get the session cookie
curl -c /tmp/cookies.txt -k -X POST https://localhost:3001/api/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"username":"admin","password":"<your password>"}'

# 2. Use the cookie on every subsequent call
curl -b /tmp/cookies.txt -k https://localhost:3001/api/agent/memory`}</Pre>
              <p className="text-sm text-on-surface-variant">
                Two endpoints are exempt by design:{" "}
                <Code>GET /api/agent/health</Code> (Docker compose
                healthcheck) and{" "}
                <Code>POST /api/agent/internal/fire-hook</Code> (called
                by the embedded MCP subprocess with bearer auth, not
                the session cookie). All other endpoints — read or
                write — require login.
              </p>
            </SubSection>
          </Section>

          <Section id="upgrades" icon="upload" title="Upgrading Phantom">
            <p>
              Phantom updates ship as numbered releases on{" "}
              <a
                href="https://github.com/ayman-m/phantom/releases"
                className="link"
                target="_blank"
                rel="noopener noreferrer"
              >
                GitHub Releases
              </a>
              . Each release includes a <Code>phantom-installer</Code>{" "}
              binary stamped at that version, plus the docker images on
              GHCR. Customer-side upgrades go through the installer.
            </p>

            <SubSection icon="auto_awesome" title="Recommended upgrade flow">
              <ol className="list-decimal pl-5 space-y-1.5 text-sm">
                <li>
                  Download the <Code>phantom-installer</Code> binary
                  for the version you want from the releases page.
                  Each binary is sealed to a single version.
                </li>
                <li>
                  <Code>chmod +x phantom-installer</Code>
                </li>
                <li>
                  <Code>sudo ./phantom-installer</Code>
                </li>
              </ol>
              <p className="text-sm text-on-surface-variant mt-2">
                The installer preserves <Code>/opt/phantom/.env</Code>{" "}
                secrets (KEK, UI password), strips the
                stale <Code>PHANTOM_VERSION</Code> +{" "}
                <Code>DIGEST_PHANTOM_*</Code> lines, appends the new
                manifest, and runs <Code>docker compose pull / up -d</Code>.
                Only services whose image content actually changed
                get recreated.
              </p>
            </SubSection>

            <SubSection icon="visibility" title="Auditing image versions">
              <p>
                Two operator surfaces show running image digests:
              </p>
              <ul className="list-disc pl-5 space-y-1 text-sm">
                <li>
                  <Term>About modal:</Term> click the version chip in
                  the sidebar, expand &quot;Image versions&quot; — shows
                  PHANTOM_VERSION + 5 stack-tier digests.
                </li>
                <li>
                  <Term>Observability panel:</Term>{" "}
                  <Code>/observability/connectors</Code> has an{" "}
                  &quot;Image digests&quot; section with the 5 stack
                  rows + per-instance connector rows. Each row carries
                  a digest-vs-legacy-tag badge so operators can spot
                  any drift at a glance.
                </li>
              </ul>
              <p className="text-sm">
                For programmatic audit (e.g. piping into an incident
                report), hit <Code>GET /api/agent/digests</Code> — same
                content as the observability panel, structured JSON.
              </p>
            </SubSection>

            <SubSection icon="tune" title="Pinning a specific version">
              <p>
                Each <Code>phantom-installer</Code> binary is sealed
                to one version (its embedded digest manifest is only
                valid for that version). To install a specific
                version, download that version&apos;s installer binary
                from the GitHub Release. The{" "}
                <Code>--upgrade-to N.N.N</Code> flag is preserved for
                backward compat but only accepted when N.N.N matches
                the binary&apos;s stamp:
              </p>
              <pre className="text-xs bg-surface-container-low p-3 rounded">
{`# Download the binary for the version you want:
gh release download vX.Y.Z --repo ayman-m/phantom \\
  --pattern phantom-installer
chmod +x phantom-installer
sudo ./phantom-installer`}
              </pre>
              <Callout tone="info">
                Each installer embeds a per-version digest manifest,
                so one binary equals one installable version. The
                mental model maps directly to production-grade
                container deployment patterns (Kubernetes manifest
                pinning, ECS task-def digest refs, Nomad job spec
                digests).
              </Callout>
            </SubSection>

            <SubSection icon="error" title="Troubleshooting">
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>
                    &ldquo;invalid reference format&rdquo; on{" "}
                    <Code>compose up</Code>
                  </Term>{" "}
                  → <Code>.env</Code> is missing{" "}
                  <Code>DIGEST_PHANTOM_*</Code> values. Re-run the
                  installer; the strip + append logic is idempotent.
                </li>
                <li>
                  <Term>Installer rejects --upgrade-to N.N.N</Term>{" "}
                  with &quot;doesn&apos;t match this binary&apos;s
                  version&quot; → expected behaviour. Download
                  the installer for the version you want.
                </li>
                <li>
                  <Term>
                    Yellow &quot;tag (legacy)&quot; badge in
                    /observability/connectors
                  </Term>{" "}
                  → an env var (e.g.{" "}
                  <Code>DIGEST_PHANTOM_CONNECTOR_XLOG</Code>) is
                  missing from{" "}
                  <Code>/opt/phantom/.env</Code> or wasn&apos;t
                  forwarded into the affected service&apos;s container.
                  Re-run installer to refresh; if still showing,
                  inspect the running container&apos;s env to confirm
                  the value made it through.
                </li>
              </ul>
            </SubSection>
          </Section>

          <Section id="ui-tour" icon="tour" title="Operator UI Tour">
            <p>
              The sidebar groups every page under five top-level sections,
              expandable / collapsible via the chevron in each header:
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-sm">
              <li>
                <Term>Command</Term> — the daily-driver surfaces (chat,
                skills, memory, knowledge, jobs, models, providers).
              </li>
              <li>
                <Term>Integration</Term> — external connections (connectors,
                approvals, notifications, API keys).
              </li>
              <li>
                <Term>Observability</Term> — runtime visibility (overview,
                metrics, traces, logs, events, pipeline, live activity).
              </li>
              <li>
                <Term>Settings</Term> — service configuration and the
                agent&apos;s personality.
              </li>
              <li>
                <Term>Learn</Term> — this hub plus User Journeys and the
                REST API reference.
              </li>
            </ul>
            <p>
              The whole sidebar collapses to icons via the chevron at the
              top. Below the nav lives a theme toggle (dark Ocean Navy ↔
              light Pale Azure), the Notifications shortcut (with a count
              badge for unread / pending approvals), and an Operator user
              card.
            </p>
            <p>
              Most pages share a common shape: a <Term>page header</Term>{" "}
              with icon + title + subtitle (jobs-style — icon directly on
              the surface, no boxed background), an optional{" "}
              <Term>action button</Term> on the right, a{" "}
              <Term>filter / search bar</Term> below the header, and a{" "}
              <Term>content area</Term> using glass panels for cards and
              tables. Tabs (where used) are green when active, matching
              the sidebar&apos;s active-link color.
            </p>
          </Section>

          {/* ============================================================
                                 COMMAND
              ============================================================ */}

          <Section id="chat" icon="chat_bubble" title="Chat">
            <p>
              The default landing page (<Link href="/" className="link">/</Link>) is
              the chat interface. The left rail lists every session in
              date-grouped buckets (Today, Yesterday, Last Week, Older),
              with a New Chat button at the top. Sessions persist for 30
              days; each has its own conversation history, memory scope,
              and pending tool-call state.
            </p>

            <SubSection icon="account_tree" title="Session lifecycle">
              <p>
                A session is created when you start a new chat. The agent
                writes one row to <Code>sessions</Code> sqlite, and
                appends every user/assistant/tool message to the{" "}
                <Code>messages</Code> table. On reload, the right-side
                telemetry panel rehydrates from messages — but only
                tool-round-trips, not raw model deltas (those aren&apos;t
                persisted to keep storage tractable).
              </p>
            </SubSection>

            <SubSection icon="bolt" title="Tool calls in chat">
              <p>
                When the agent decides to call a tool, you see an inline
                tool-call card with the tool name, arguments, and a status
                spinner. A tool the install gates (jobs_create,
                personality_update, jobs_delete, … — see{" "}
                <Link href="#approvals" className="link">Approvals</Link>)
                blocks server-side on an approval card, and the agent
                resumes once you click Approve. Every other tool executes
                immediately without prompt, and no tool is gated in this
                release.
              </p>
            </SubSection>

            <SubSection icon="lightbulb" title="Common patterns">
              <p>Useful prompts to try:</p>
              <ul className="list-disc pl-5 space-y-1 text-sm">
                <li>
                  <em>&quot;Run the FortiGate auth-spray scenario for 5
                  minutes against the playground&quot;</em> — picks the
                  right scenario by name + the right connector tools.
                </li>
                <li>
                  <em>&quot;What does the
                  <Code>generate_shared_iocs</Code> skill do?&quot;</em>{" "}
                  — pulls from the skill catalog and explains.
                </li>
                <li>
                  <em>&quot;Remember that I prefer JSON output for
                  detection rules&quot;</em> — writes to memory under
                  scope <Code>user</Code>.
                </li>
                <li>
                  <em>&quot;What did I tell you about output format?&quot;</em>{" "}
                  — searches memory semantically.
                </li>
              </ul>
            </SubSection>

            <SubSection icon="auto_awesome_motion" title="Auto-compaction & context guard">
              <p>
                Long sessions can outgrow the model&apos;s context window.
                Phantom guards against this in two ways. First, the chat
                handler estimates input + reserved-output tokens before each
                turn; at &gt;= 90% of the model cap it emits a{" "}
                <Code>context_warning</Code> event and the chat input shows
                a yellow banner with a one-click <Code>/compress</Code>{" "}
                action. Second, when token-budgeted history walking would
                drop more than ~5 prior messages (tunable in{" "}
                <Link href="/settings/personality" className="link">
                  Personality &rarr; Tuning
                </Link>
                ), the dropped portion is summarized into a checkpoint
                automatically — the operator sees the &ldquo;auto-compacted
                N messages&rdquo; divider in the message thread.
              </p>
            </SubSection>

            <SubSection icon="bolt" title="Vertex prompt caching">
              <p>
                When using a Vertex Gemini model, the chat route can cache
                the stable system prompt with Vertex&apos;s{" "}
                <Code>cachedContents</Code> API — cached input tokens bill
                at ~25% of the standard rate. The model selector chip
                shows a small amber dot when the previous turn registered
                a cache hit; hover for the cached/prompt token ratio.
                Disable per session via{" "}
                <Link href="/settings/personality" className="link">
                  Personality &rarr; Tuning &rarr; Vertex prompt caching
                </Link>
                .
              </p>
            </SubSection>

            <SubSection icon="terminal" title="Slash commands">
              <p>
                Type <Code>/help</Code> at the start of any message for the
                full list. Quick reference: <Code>/compress</Code> rolls
                prior turns into a checkpoint; <Code>/clear</Code> ends the
                session and starts a fresh one (transcript stays
                exportable); <Code>/model &lt;name&gt;</Code> overrides the
                model for this session. See the dedicated{" "}
                <a href="#slash-commands" className="link">
                  Slash Commands
                </a>{" "}
                section for the full behavior + side effects.
              </p>
            </SubSection>

            <SubSection icon="data_object" title="Direct tool invocation">
              <p>
                Type <Code>^toolname arg=value</Code> at the start of any
                message to call a connector tool directly &mdash; bypassing
                the model entirely. The result renders as a JSON code block
                in the chat transcript, visually distinct from a normal
                model reply.
              </p>
              <p className="text-sm leading-relaxed">
                Examples:
              </p>
              <ul className="list-disc pl-5 space-y-1 text-sm">
                <li>
                  <Code>^get_cases_and_issues limit=10</Code> &mdash;
                  bare name resolves to <Code>xdr_get_cases_and_issues</Code>{" "}
                  (the only registered tool with that suffix). Returns the
                  raw incident list.
                </li>
                <li>
                  <Code>
                    ^xdr_run_xql_query query=&quot;dataset = xdr_data | limit 5&quot;
                  </Code>{" "}
                  &mdash; quoted strings support whitespace.
                </li>
                <li>
                  <Code>
                    ^get_cases_and_issues &#123;&quot;limit&quot;:3, &quot;severity&quot;:[&quot;high&quot;]&#125;
                  </Code>{" "}
                  &mdash; JSON-literal args for structured shapes (arrays,
                  nested objects).
                </li>
                <li>
                  <Code>^cortex-docs.search query=&quot;Broker VM Azure&quot; product=xdr</Code>{" "}
                  &mdash; fully-qualified <Code>connector.tool</Code> form
                  also works.
                </li>
              </ul>
              <p className="text-sm leading-relaxed mt-2">
                Auto-typing on key=value args: <Code>true</Code> /
                <Code> false</Code> become booleans, <Code>null</Code>{" "}
                becomes null, <Code>10</Code> / <Code>3.14</Code> become
                numbers, everything else is a string. ISO timestamps,
                UUIDs, IPs, hostnames: pass them as-is &mdash; they stay
                strings (no mangling).
              </p>
              <p className="text-sm leading-relaxed mt-2">
                <strong>Critical property:</strong> direct tool invocation
                works <em>even without a provider configured</em>. On a
                fresh install before you&apos;ve set up Gemini or Vertex,
                you can still <Code>^xdr_run_xql_query query=&quot;...&quot;</Code>{" "}
                to validate the connector. The model is never called; the
                tool dispatches through the embedded MCP&apos;s JSON-RPC
                surface (POST <Code>/api/agent/tool/call</Code>) which
                requires only your UI session cookie.
              </p>
              <p className="text-sm leading-relaxed mt-2">
                Use cases:
              </p>
              <ul className="list-disc pl-5 space-y-1 text-sm">
                <li>
                  Validating a connector instance you just created (does it
                  actually return rows?).
                </li>
                <li>
                  Testing arg shapes before authoring chat prompts the
                  model would dispatch.
                </li>
                <li>
                  Pre-LLM smoke on a fresh install (deterministic, free,
                  doesn&apos;t consume model tokens).
                </li>
                <li>
                  Debugging connector container state (
                  <Code>^xdr_get_cases_and_issues</Code> with no args
                  proves the container is reachable + auth is valid).
                </li>
              </ul>
            </SubSection>
          </Section>

          {/* Slash commands reference. Lives between the Chat overview
              and the Skills page so the navigation flow goes "what is
              chat → what can I type → what skills can I invoke". */}
          <Section id="slash-commands" icon="terminal" title="Slash Commands">
            <p>
              Slash commands let you control the chat session itself
              (&ldquo;meta&rdquo; actions) instead of asking the model
              to do something. Type at the very start of your message;
              everything else is sent to the model normally.
            </p>

            <SubSection icon="compress" title="/compress">
              <p>
                Roll all prior turns in this session into a single summary
                checkpoint. Use it when the chat is getting long and the
                model is having trouble remembering early context.
              </p>
              <ul className="list-disc pl-5 space-y-1 text-sm">
                <li>
                  <Term>What it does</Term> — fetches the session history,
                  summarizes it via the same model you&apos;re chatting
                  with, persists the summary as a{" "}
                  <Code>system</Code> message tagged{" "}
                  <Code>kind:&quot;compaction-checkpoint&quot;</Code>.
                </li>
                <li>
                  <Term>Side effects</Term> — emits{" "}
                  <Code>compaction_start</Code> and{" "}
                  <Code>compaction_end</Code> SSE events; the message
                  thread gets a horizontal divider at the checkpoint
                  position; the chat header shows a &ldquo;Compacted N
                  messages&rdquo; badge.
                </li>
                <li>
                  <Term>Audit</Term> — durable rows under{" "}
                  <Code>action:chat_compaction_*</Code> in{" "}
                  <Link href="/observability/events" className="link">
                    /observability/events
                  </Link>
                  .
                </li>
                <li>
                  <Term>When to use</Term> — manually before a long
                  research session, or when the auto-suggest banner fires
                  at 80% context utilization.
                </li>
              </ul>
            </SubSection>

            <SubSection icon="restart_alt" title="/clear">
              <p>
                End the current session and start a fresh one in the same
                window. The previous transcript is preserved (still
                listed in the sidebar, still exportable) — you just won&apos;t
                accidentally continue from it.
              </p>
              <ul className="list-disc pl-5 space-y-1 text-sm">
                <li>
                  <Term>What it does</Term> — POSTs to the MCP&apos;s{" "}
                  <Code>/api/v1/sessions/&#123;id&#125;/end</Code>, then
                  creates a new session, then emits a{" "}
                  <Code>session_cleared</Code> SSE event so the chat UI
                  can swap its active session pointer without a page
                  reload.
                </li>
                <li>
                  <Term>Idempotent on new sessions</Term> — running
                  <Code>/clear</Code> on a brand-new session is a no-op
                  (there&apos;s nothing to clear).
                </li>
                <li>
                  <Term>When to use</Term> — when you want a fresh
                  context budget without losing the history of what
                  you&apos;ve done.
                </li>
              </ul>
            </SubSection>

            <SubSection icon="help" title="/help">
              <p>
                List the registered slash commands with their one-line
                descriptions. Built from the same{" "}
                <Code>SLASH_COMMANDS</Code> table the chat handler
                dispatches against, so the help output stays in sync
                automatically.
              </p>
            </SubSection>

            <SubSection icon="tune" title="/model &lt;name&gt;">
              <p>
                Override the model for THIS session. Persists into{" "}
                <Code>session.metadata.preferred_model</Code>; subsequent
                turns read it on entry. The header dropdown still wins
                if you also pick a model there.
              </p>
              <ul className="list-disc pl-5 space-y-1 text-sm">
                <li>
                  <Code>/model</Code> (no args) — show the current
                  preference (or the runtime default).
                </li>
                <li>
                  <Code>/model gemini-2.5-pro</Code> — set the
                  preference.
                </li>
                <li>
                  <Code>/model auto</Code> — clear the override; future
                  turns use the runtime default.
                </li>
                <li>
                  <Term>SSE</Term> — emits{" "}
                  <Code>model_preference_changed</Code> when set; the
                  next turn&apos;s <Code>model</Code> event includes{" "}
                  <Code>override_source: &quot;session&quot;</Code> so
                  the UI can distinguish header vs session overrides.
                </li>
              </ul>
            </SubSection>

            <SubSection icon="add_circle" title="Adding a new slash command">
              <p>
                Slash commands are a registry pattern. Each command is one
                entry in <Code>SLASH_COMMANDS</Code> at the top of{" "}
                <Code>app/api/chat/route.ts</Code> with a name,
                description, and async handler. The handler runs inside
                the SSE stream and owns its own controller close. See{" "}
                <Code>lib/slash-commands.ts</Code> for the framework.
              </p>
            </SubSection>
          </Section>

          {/* Plan mode operator workflow. */}
          <Section id="plan-mode-ux" icon="checklist" title="Plan Mode">
            <p>
              Plan mode lets you ask the agent to <em>propose</em> a
              multi-step plan before running anything — useful when a
              request is ambiguous, cross-system, or destructive enough
              that you want to review the steps before tools fire. Type{" "}
              <Code>/plan</Code> at the start of a chat message and the
              agent switches into proposal mode for that turn.
            </p>

            <SubSection icon="play_circle" title="Triggering">
              <p>
                Three entry points, same effect:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Code>/plan run the FortiGate scenario, then validate
                  the matching XSIAM rule</Code> — explicit slash command.
                </li>
                <li>
                  Type your request normally and click the{" "}
                  <Term>Plan first</Term> chip on the chat input — same
                  outcome, lower friction.
                </li>
                <li>
                  Set <Code>plan_mode_default: true</Code> in{" "}
                  <Link href="/settings/personality" className="link">
                    Personality
                  </Link>{" "}
                  for sessions where you always want a plan first.
                </li>
              </ul>
            </SubSection>

            <SubSection icon="reviews" title="Reviewing the proposal">
              <p>
                The agent renders an inline plan card with one row per
                step: tool, target, rationale, and an estimated cost
                (tokens + connector calls). Each step has a checkbox; un-tick
                anything you want to skip. The card&apos;s footer has three
                actions:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>Approve &amp; run</Term> — fires the remaining
                  steps in order; subsequent tool cards stream into the
                  thread as they execute.
                </li>
                <li>
                  <Term>Revise</Term> — types a follow-up so you can ask
                  for changes (&quot;swap step 3 for the staged variant&quot;,
                  &quot;skip step 5&quot;).
                </li>
                <li>
                  <Term>Discard</Term> — drops the proposal entirely.
                </li>
              </ul>
            </SubSection>

            <SubSection icon="article" title="Audit + observability">
              <p>
                Each proposal writes a <Code>chat_plan_proposed</Code>{" "}
                audit row; failures (model couldn&apos;t produce a valid
                plan) write <Code>chat_plan_failed</Code>. Filter on
                <Code>action:chat_plan_*</Code> in{" "}
                <Link href="/observability/events" className="link">
                  /observability/events
                </Link>{" "}
                to see proposals across sessions — useful for tracking
                which workflows are commonly planned vs run direct.
              </p>
            </SubSection>

            <Callout tone="info">
              Plans don&apos;t bypass the approval list — a tool the install
              gates still surfaces its own approval card when it executes
              inside an approved plan. Plan mode only adds a
              proposal-first layer; the existing safety rails remain in
              place.
            </Callout>
          </Section>

          {/* Tasks page + /tasks command. */}
          <Section id="tasks-ux" icon="task_alt" title="Tasks">
            <p>
              Long-running operations the agent kicks off (a scenario
              worker, a multi-step subagent, a deferred job dispatch) land
              in the <Term>tasks registry</Term> rather than blocking the
              chat. View them at{" "}
              <Link href="/tasks" className="link">/tasks</Link> or list
              the active set inline with <Code>/tasks</Code> in any chat.
            </p>

            <SubSection icon="account_tree" title="Lifecycle">
              <p>
                Every task moves through the same state machine. The
                tasks page color-codes each row by current state:
              </p>
              <Pre>{`pending      ── created, not yet picked up by a worker
running      ── worker is actively executing
completed    ── finished successfully
failed       ── worker raised an unrecoverable error
aborted      ── operator clicked Cancel before completion`}</Pre>
              <p>
                Each transition writes an audit row{" "}
                (<Code>action:task_started</Code>,{" "}
                <Code>action:task_completed</Code>, etc.). Long-lived
                tasks emit <Code>task_transitioned</Code> on every
                intermediate hop, so you can replay precisely when state
                changed.
              </p>
            </SubSection>

            <SubSection icon="timeline" title="The /tasks page">
              <p>
                Three tabs: <Term>Active</Term> (pending + running),{" "}
                <Term>Recent</Term> (last 24h, all states), and{" "}
                <Term>All</Term> (full history with date filter). Each
                row shows: task ID, kind (scenario / subagent / job /
                tool), target (the thing being acted on), elapsed time,
                originating session, and a status pill.
              </p>
              <p>
                Click any row to open the detail drawer with: the
                originating chat link, the full audit-row trail (all
                state transitions), the worker&apos;s last heartbeat,
                and the output preview where applicable.
              </p>
            </SubSection>

            <SubSection icon="cancel" title="Cancelling + retrying">
              <p>
                Active tasks have a <Term>Cancel</Term> button in the
                detail drawer. Cancel signals the worker to abort at its
                next checkpoint; the task transitions to{" "}
                <Code>aborted</Code> and any partially-applied side
                effects are documented in the run output. Failed tasks
                show a <Term>Retry</Term> button that re-creates the
                task with the same inputs.
              </p>
            </SubSection>

            <SubSection icon="terminal" title="The /tasks slash command">
              <p>
                Inside a chat, <Code>/tasks</Code> renders a compact
                inline table of active tasks (same data as the page&apos;s
                Active tab). Each row links to the task detail. Useful
                when you want to keep working in chat while monitoring
                in-flight work without switching tabs.
              </p>
            </SubSection>
          </Section>

          <Section id="skills" icon="auto_awesome" title="Skills">
            <p>
              <Link href="/skills" className="link">/skills</Link> is the
              registry of every behavior Phantom knows about. Skills are
              markdown documents the agent reads at the start of relevant
              sessions to bias its tool selection — think &quot;procedural
              recipes&quot; rather than runnable code.
            </p>

            <SubSection icon="category" title="Four categories">
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>Foundation</Term> — reusable building blocks
                  (generate IOCs, populate observable catalogs, baseline a
                  workspace). The agent draws on these to compose larger
                  flows.
                </li>
                <li>
                  <Term>Scenarios</Term> — full attack chains
                  (initial-access → discovery → privilege-escalation →
                  exfil sequences). Each scenario references specific
                  ATT&amp;CK techniques. Ships{" "}
                  <Term>12 heavy-volume kill chains</Term> alongside the
                  original 7: ransomware double-extortion, APT
                  long-dwell espionage, insider threat, supply-chain
                  npm compromise, M365 OAuth takeover, mass phishing
                  campaign, web-app SQLi → RCE, living-off-the-land
                  LOLBin, cryptojacking botnet, business-email
                  compromise, Kubernetes container escape, and DDoS
                  multi-vector. Each generates 1k-13k synthetic events
                  designed to stress-test correlation rules end-to-end.
                </li>
                <li>
                  <Term>Validation</Term> — detection-validation flows
                  (run-and-check, coverage analysis, repeat sweeps).
                </li>
                <li>
                  <Term>Workflows</Term> — multi-step orchestration
                  (scheduled simulations, weekly reports, dashboard
                  updates).
                </li>
              </ul>
            </SubSection>

            <SubSection icon="article" title="Skill anatomy">
              <p>
                Each skill is a markdown file with optional YAML
                front-matter:
              </p>
              <Pre>{`---
name: generate_shared_iocs
displayName: Generate Shared IOCs
category: foundation
locked: true               # platform-enforced; can't be disabled
loadingMode: always        # vs "on_demand"
---

# Generate Shared IOCs

Pre-generates the indicators (IPs, domains, hashes, users) that
downstream scenarios reuse — keeps cross-scenario telemetry coherent.

## When to use
...

## Steps
1. Call \`xlog.populate_observable_catalog\` with seed=42
2. ...`}</Pre>
            </SubSection>

            <SubSection icon="lock" title="Lock state and overrides">
              <p>
                Each card shows a lock icon (platform-enforced skills
                can&apos;t be disabled by the operator), a toggle for
                enable/disable, and click-through to a detail panel with
                the full markdown content and analytics (calls in last
                24h / 7d / 30d). Skills are global to the install —
                Phantom is single-tenant, so a skill is either on or off
                for the whole agent.
              </p>
            </SubSection>

            <SubSection icon="edit" title="Create / Edit / Download / Delete / Import">
              <p>
                Every skill card&apos;s detail panel has three header
                actions: <Term>Download</Term> grabs the live MD as a
                .md file (handy for offline edits or sharing);{" "}
                <Term>Save</Term> commits textarea edits — click into
                the body editor first to lazy-load the live MD, then
                Save calls <Code>PUT /api/skills</Code>. The backend
                writes a <Code>.md.bak</Code> next to the original
                before overwriting, so a one-line shell fix recovers
                an unwanted change. <Term>Delete</Term> soft-deletes:
                the MD moves to <Code>/app/skills/.deleted/</Code> on
                the volume, recoverable via <Code>docker exec</Code>{" "}
                + <Code>mv</Code>. Locked skills (e.g.{" "}
                <Code>generate_shared_iocs</Code>) render Delete as
                disabled — they&apos;re foundational and breaking
                them breaks the agent.
              </p>
              <p>
                <Term>Create</Term>: button in the page header opens
                the editor. Display name auto-derives the on-disk
                filename via slugify (e.g. &ldquo;SQL Injection
                Scenario&rdquo; → <Code>sql_injection_scenario.md</Code>);
                you can override the filename if needed. Pick a
                category (foundation / scenarios / validation /
                workflows), write a description (this is what the chat
                agent sees in <Code>&lt;available_skills&gt;</Code> —
                be concise and specific), then write the body. Submit
                composes minimal frontmatter and POSTs.
              </p>
              <p>
                <Term>Import</Term>: button next to Create.
                Pick a <Code>.md</Code> file from your local machine —
                if the file has a YAML frontmatter block, the import
                pulls <Code>name</Code> and <Code>category</Code> from
                it; otherwise the filename becomes the canonical name
                and category defaults to <Code>scenarios</Code>. Useful
                for porting skills between deployments (export with
                Download → Import on the target). Imports of an
                already-existing skill name fail with an explicit
                &ldquo;already exists&rdquo; error so you can&apos;t
                accidentally overwrite — delete the existing skill
                first or rename the import.
              </p>
              <p>
                Operator edits land on the volume immediately — the
                next chat turn picks them up because the system prompt
                fetches the skills registry per turn. No restart required.
              </p>
            </SubSection>

            <SubSection icon="psychology" title="Chat agent skill awareness">
              <p>
                The chat system prompt now includes an{" "}
                <Code>## AVAILABLE SKILLS</Code> block listing every
                installed skill&apos;s name, display name, category,
                description, and ATT&amp;CK tactics. The{" "}
                <em>bodies</em> stay out of the prompt — that&apos;d
                be 50-150KB for our 23 skills, breaking the prompt
                cache every time anyone edits a skill. Instead, the
                model decides which skill (if any) to apply based on
                metadata, then calls <Code>skills_read</Code> to pull
                the full body when it&apos;s actually going to use it.
              </p>
              <p>
                Practical effect: ask the agent to &ldquo;run a
                ransomware double-extortion exercise against the test
                fleet&rdquo; and it picks{" "}
                <Code>scenarios/ransomware_double_extortion.md</Code>{" "}
                from the registry on its own. You don&apos;t have to
                tell it where to look. The metadata is also fresh per
                turn — adding a new skill via the UI makes it
                immediately discoverable in the next chat message.
              </p>
            </SubSection>

            <Callout tone="warn">
              Editing skills under{" "}
              <Code>bundles/spark/mcp/skills/*.md</Code> in the repo
              only reaches the running container after a build +{" "}
              <Code>FORCE_SKILLS_SYNC=1</Code> on the next run, or
              after a <Code>docker compose down -v</Code> drops the
              volume. <strong>UI-driven CRUD bypasses this</strong> —
              creates / edits / deletes go straight to the volume via
              the MCP, so the in-flight container picks them up
              without a restart. The repo→volume drift only matters
              for source-tracked skills the operator wants to ship to
              fresh installs. See{" "}
              <Link href="/help/architecture#manifest" className="link">
                Architecture &rarr; Manifest &amp; Bundle
              </Link>{" "}
              for the why.
            </Callout>
          </Section>

          {/* Agents page (subagents + operator-authored definitions). */}
          <Section id="agents-ux" icon="smart_toy" title="Agents">
            <p>
              <Link href="/agents" className="link">/agents</Link> lists
              every agent definition the runtime knows about — built-in
              subagents, plugin-contributed agents, and ones you author
              yourself. Each agent is a scoped persona: its own system
              prompt, tool/skill allow-list, model preference, and origin.
            </p>

            <SubSection icon="badge" title="Origin badges">
              <p>
                Three badges distinguish where a definition came from:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>built-in</Term> — ships with the bundle (red-team,
                  blue-team, purple-team triage). Cannot be deleted, but
                  can be disabled via the agent toggle on the card.
                </li>
                <li>
                  <Term>plugin</Term> — contributed by an installed plugin
                  (see <a href="#plugins-ux" className="link">Plugins</a>).
                  Reloaded when the plugin reloads.
                </li>
                <li>
                  <Term>operator</Term> — authored by you via the{" "}
                  <Term>New agent</Term> button or duplicated from an
                  existing definition. Stored in the runtime DB and
                  survives restarts.
                </li>
              </ul>
            </SubSection>

            <SubSection icon="edit_note" title="The edit drawer">
              <p>
                Click any agent row to open the edit drawer. Built-in /
                plugin agents are read-only at the source level but can be
                forked into operator-owned copies. Editable fields:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>Display name + description</Term> — what surfaces
                  in <Code>/spawn</Code> typeahead and chat references.
                </li>
                <li>
                  <Term>System prompt</Term> — the persona&apos;s base
                  instructions. Markdown-friendly; supports the same
                  template variables the chat persona uses
                  (<Code>$&#123;workspace&#125;</Code>,{" "}
                  <Code>$&#123;operator&#125;</Code>).
                </li>
                <li>
                  <Term>Allowed tools / skills</Term> — scoped catalogs.
                  An agent only sees the intersection of its allow-list
                  and the runtime&apos;s active set. Wildcards supported
                  (<Code>caldera.*</Code>, <Code>xsiam.run_xql</Code>).
                </li>
                <li>
                  <Term>Model preference</Term> — overrides the runtime
                  default for this agent. Useful when a focused agent
                  benefits from a smaller faster model
                  (<Code>gemini-2.5-flash</Code>) vs the chat
                  default&apos;s <Code>gemini-2.5-pro</Code>.
                </li>
              </ul>
            </SubSection>

            <SubSection icon="rocket_launch" title="Spawning from chat">
              <p>
                Type <Code>/spawn red-team-recon target=10.0.0.0/24</Code>{" "}
                to dispatch a subagent. The chat shows an inline{" "}
                <Term>subagent panel</Term> with the agent&apos;s
                streaming output, tool calls, and final summary. Multiple
                subagents can run in parallel — each gets its own panel.
                The parent chat resumes once all dispatched subagents
                report back.
              </p>
              <p>
                Subagents run in the foreground (their output streams
                back into the parent thread) rather than as background
                tasks — see{" "}
                <Link
                  href="/help/architecture#design-decisions"
                  className="link"
                >
                  Architecture &rarr; Design Decisions
                </Link>{" "}
                for the rationale.
              </p>
            </SubSection>

            <SubSection icon="article" title="Audit trail">
              <p>
                Lifecycle audit rows: <Code>chat_subagent_started</Code>,{" "}
                <Code>chat_subagent_completed</Code>,{" "}
                <Code>chat_subagent_failed</Code>. Edits to agent
                definitions write <Code>agent_definition_upsert</Code>{" "}
                /<Code>_enabled</Code>/<Code>_disabled</Code>/
                <Code>_deleted</Code>. Filter on{" "}
                <Code>action:agent_definition_*</Code> in{" "}
                <Link href="/observability/events" className="link">
                  /observability/events
                </Link>{" "}
                to audit who changed what.
              </p>
            </SubSection>

            <SubSection icon="route" title="When to spawn vs ask the parent">
              <p>
                Subagents are a delegation tool, not a default. They
                cost an extra Gemini call cycle (system-prompt
                tokens + tool-catalogue tokens for the scoped child),
                they don&apos;t share the parent&apos;s short-term
                memory, and their transcript doesn&apos;t bubble up
                to the parent&apos;s context. Use them when the cost
                buys you something concrete:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>Different persona / tighter tool scope</Term>
                  {" "}— the parent is a general-purpose assistant;
                  the red-team subagent needs CALDERA-specific
                  framing and a tool list that excludes XSIAM. The
                  scoped tool catalogue is the security argument: a
                  tool not in the catalogue can&apos;t be called
                  through a hook injection or a prompt-injection
                  attempt.
                </li>
                <li>
                  <Term>Long sub-task you don&apos;t want polluting
                  parent context</Term> — the parent already has 80%
                  of its context window full; you don&apos;t want a
                  150-tool-call adversary chain to consume the rest.
                  The subagent runs in its own session; only the
                  final summary returns to the parent.
                </li>
                <li>
                  <Term>Parallel exploration</Term> — dispatch two
                  subagents at once (e.g. red-team-recon +
                  blue-team-detection) to look at the same scenario
                  from two angles. Each gets its own panel; their
                  summaries arrive independently.
                </li>
              </ul>
              <p className="text-sm text-on-surface-variant">
                When you DON&apos;T need a subagent: short follow-up
                questions, debugging the parent&apos;s last tool
                call, anything that needs the parent&apos;s working
                memory of the current incident. A subagent
                won&apos;t see the parent&apos;s recent context — it
                starts fresh with only its system prompt + your{" "}
                <Code>/spawn</Code> argument.
              </p>
            </SubSection>

            <SubSection icon="bug_report" title="Debugging subagents">
              <p>
                When a subagent isn&apos;t doing what you expect,
                walk this ladder:
              </p>
              <ol className="list-decimal pl-5 space-y-1.5 text-sm">
                <li>
                  Open the <Term>sidechain</Term> link in the
                  subagent panel. The full subagent transcript opens
                  in a new tab — every tool call, every model reply,
                  the final summary. The parent panel only shows the
                  summary by design; sidechain has the detail.
                </li>
                <li>
                  Open{" "}
                  <Link href="/observability/events" className="link">
                    /observability/events
                  </Link>{" "}
                  and filter <Code>action:chat_subagent_*</Code>. You
                  get the lifecycle audit (started / completed /
                  failed) plus per-tool-call rows tagged with the
                  subagent session id. A subagent that finished{" "}
                  <em>failed</em> shows the failure reason in the row
                  metadata.
                </li>
                <li>
                  Check <Term>blocked tool</Term> events. If the
                  subagent tried a tool outside its scope, the
                  sidechain shows a <Code>subagent_tool_blocked</Code>{" "}
                  SSE event. Either widen the allow-list (on{" "}
                  <Link href="/agents" className="link">/agents</Link>{" "}
                  edit drawer) OR refine the system prompt so the
                  model doesn&apos;t reach for that tool.
                </li>
                <li>
                  Check the <Term>max_turns</Term> cap on the agent
                  definition. A subagent that returns a thin summary
                  may simply have run out of turns before completing
                  its task. The audit row carries{" "}
                  <Code>statusReason: &apos;max-turns-reached&apos;</Code>{" "}
                  when this happens.
                </li>
                <li>
                  Cost rollup — the per-subagent cost shows up in{" "}
                  <Link href="/observability/cost" className="link">
                    /observability/cost
                  </Link>{" "}
                  filtered to that session id. Subagents inherit the
                  parent&apos;s model unless the agent definition
                  overrides; switching a heavy subagent to a smaller
                  model (e.g. <Code>gemini-2.5-flash</Code>) is the
                  fastest cost lever.
                </li>
              </ol>
            </SubSection>
          </Section>

          <Section id="memory" icon="database" title="Memory">
            <p>
              <Link href="/memory" className="link">/memory</Link> is a
              vector-indexed key/value store. The agent writes here when
              the operator says &quot;remember X&quot; or when it captures
              durable context across sessions. Each row carries a key,
              value, scope, timestamps, optional TTL, and free-form
              metadata.
            </p>

            <SubSection icon="layers" title="Four scopes">
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>agent</Term> — applies to every session. Use for
                  &quot;facts the agent should always know.&quot;
                </li>
                <li>
                  <Term>session</Term> — current chat only
                  (<Code>session:&lt;id&gt;</Code> under the hood).{" "}
                  <em>Not</em> automatically cleared when the session
                  ends — set an explicit TTL on the entry if you want it
                  to expire with the conversation. Use for &quot;don&apos;t
                  pollute the agent scope, just remember this for
                  now.&quot;
                </li>
                <li>
                  <Term>user</Term> and <Term>system</Term> — reserved
                  scopes in the filter UI. No built-in write path uses
                  them today, so these tabs are typically empty; nothing
                  stops you from writing to them yourself via the REST
                  API if you want the namespace.
                </li>
              </ul>
            </SubSection>

            <SubSection icon="verified_user" title="Provenance">
              <p>
                Every row is tagged <Code>meta.source</Code>:{" "}
                <Code>operator</Code> for anything written through the
                REST API (including this page), <Code>agent</Code> for
                anything the agent stored itself via its{" "}
                <Code>memory_store</Code> tool, or{" "}
                <Code>plugin:&lt;name&gt;</Code> for a marketplace
                plugin&apos;s seeded defaults — and it isn&apos;t
                caller-chosen: the write path decides it, so the agent
                can&apos;t claim operator provenance for its own
                conclusions. The agent treats operator-sourced rows as
                settled fact and its own rows as prior conclusions to
                double-check before repeating — the same way an analyst
                trusts a colleague&apos;s note more than their own
                six-month-old guess. Expand a row&apos;s{" "}
                <Code>meta</Code> field below to see the tag.
              </p>
            </SubSection>

            <SubSection icon="search" title="Semantic search">
              <p>
                The search bar runs vector similarity (Vertex
                <Code>text-embedding-004</Code>, 768 dims). So{" "}
                <em>&quot;detection rules I prefer&quot;</em> matches an
                entry literally written{" "}
                <em>&quot;output JSON for detections&quot;</em> — same
                meaning, different words.
              </p>
            </SubSection>

            <SubSection icon="diversity_3" title="MMR + temporal decay + FTS hybrid">
              <p>
                Three ranking improvements layer over the base vector
                similarity:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>MMR (maximal marginal relevance)</Term> — after
                  the top-K is pulled by similarity, each candidate is
                  re-scored with{" "}
                  <Code>λ × similarity − (1 − λ) × max_pairwise_sim</Code>.
                  λ near 1 favors relevance; λ near 0 favors diversity.
                  Default 0.7. Prevents the result list from being
                  dominated by 5 near-duplicate rows.
                </li>
                <li>
                  <Term>Temporal decay</Term> — exponential decay applied
                  to row age in days:{" "}
                  <Code>exp(−age_days × λ)</Code>. Default λ = 0.01 means
                  a 10-day-old row keeps ~90% of its score; a 100-day-old
                  row keeps ~37%. The <em>fresh / recent / old</em>{" "}
                  bucket badge on each result row shows the rough decay
                  bucket the row falls into.
                </li>
                <li>
                  <Term>FTS5 keyword promotion</Term> — for queries with
                  literal terms (UUIDs, hostnames, IP addresses), the
                  pure-similarity recall sometimes misses obvious matches.
                  An FTS5 index (porter stemmer + unicode61 tokenizer)
                  promotes literal hits into the result set with an{" "}
                  <Term>FTS hit</Term> badge. Useful for{" "}
                  <em>&quot;find the entry mentioning UUID
                  abc-123&quot;</em>.
                </li>
              </ul>
              <p className="mt-2">
                Defaults are configured in{" "}
                <Link
                  href="/settings/personality"
                  className="link"
                >
                  Personality &rarr; Tuning
                </Link>
                . For one-off tuning, use the <Term>Advanced</Term>{" "}
                disclosure on{" "}
                <Link href="/memory" className="link">/memory</Link> —
                lambda overrides apply to the next search and reset on
                close.
              </p>
            </SubSection>

            <SubSection icon="schedule" title="TTL and cleanup">
              <p>
                Optional <Code>ttl_seconds</Code> per entry. Expiry is
                enforced on every read (get, list, search) — an entry
                becomes unreachable the instant its TTL elapses, so a
                60-second TTL means exactly 60 seconds. A separate hourly
                sweep reclaims the disk space for already-expired rows;
                it is cleanup, not what makes the TTL take effect.
                Scope <Code>session</Code> (<Code>session:&lt;id&gt;</Code>)
                is <em>not</em> automatically cleared when a session ends —
                set an explicit <Code>ttl_seconds</Code> if you want
                entries to expire even within an active session.
              </p>
            </SubSection>
          </Section>

          <Section id="knowledge" icon="menu_book" title="Knowledge Bases">
            <p>
              <Link href="/knowledge" className="link">/knowledge</Link>{" "}
              browses the bundle&apos;s loaded knowledge bases — curated,
              schema-validated, semantically searchable reference content.
              KBs differ from memory in three ways: read-only at the agent
              surface, sourced from the bundle (not chat), and indexed at
              boot rather than on-write.
            </p>

            <SubSection icon="library_books" title="Bundled KBs">
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>phantom-soc</Term> — main reference content:
                  architecture notes, scenario design rationale, run-book
                  entries, post-mortem templates. The agent retrieves from
                  this KB whenever you ask conceptual questions about
                  Phantom.
                </li>
                <li>
                  <Term>xql-examples</Term> — curated Cortex XQL / XSIAM
                  queries indexed for natural-language retrieval,
                  spanning many datasets, MITRE techniques and XQL
                  stages. The agent
                  retrieves via the universal <Code>knowledge_search</Code>
                  tool (one call covers all loaded KBs); both the XSIAM
                  connector&apos;s <Code>find_xql_examples_rag</Code> and
                  the XQL skill chain consume this corpus.
                  Validated against the live tenant before each entry
                  ships — every query in the KB is guaranteed to return{" "}
                  <Code>status: SUCCESS</Code> when executed.
                </li>
              </ul>
            </SubSection>

            <SubSection icon="search" title="How the agent uses the KB">
              <p>
                When you ask the agent &ldquo;show me X&rdquo; where X
                involves XDR/XSIAM telemetry, the chain is:
                (1)&nbsp;<Code>knowledge_search</Code> over{" "}
                <Code>xql-examples</Code> to find a template matching your
                question; (2)&nbsp;adapt the template&apos;s SQL block to
                your specific parameters (hostnames, time windows, etc.);
                (3)&nbsp;run via <Code>xdr_run_xql_query</Code> or{" "}
                <Code>xsiam_run_xql</Code>; (4)&nbsp;return the table.
                Combined with the{" "}
                <Code>xdr_list_datasets</Code> tool (which empirically
                enumerates the datasets available in your specific
                tenant), this gives operators a low-friction path from
                natural-language question to validated query result —
                no XQL fluency required.
              </p>
            </SubSection>

            <SubSection icon="settings" title="Adding entries">
              <p>
                The boot loader reads{" "}
                <Code>bundles/spark/kbs/&lt;name&gt;/entries/*.md</Code>,
                validates each against the KB&apos;s{" "}
                <Code>schema.json</Code>, and writes one row per entry
                into a per-KB SQLite database with the embedding cached
                alongside. Source-hash detection means re-running boot
                without changes is a no-op (no Vertex calls). Adding an
                entry is therefore: drop a markdown file, redeploy. Future
                Tier-3 will add runtime CRUD — the page is currently
                read-only by design.
              </p>
            </SubSection>
          </Section>

          <Section id="jobs" icon="schedule" title="Jobs">
            <p>
              <Link href="/jobs" className="link">/jobs</Link> manages
              recurring scheduled work — the same prompts you&apos;d type
              in chat, but fired on cron. Each job card shows a name,
              schedule, action type, last-run status, and a quick-link to
              run history.
            </p>

            <SubSection icon="alarm" title="Cron syntax">
              <p>
                Standard 5-field cron (minute / hour / day-of-month /
                month / day-of-week). Common cadences:
              </p>
              <Pre>{`*/5 * * * *      every 5 minutes
0 */1 * * *      every hour on the hour
0 9 * * 1-5      9am Mon–Fri (workday morning)
0 0 */7 * *      every 7 days at midnight
0 6 * * 0        Sunday 6am (weekly report)`}</Pre>
            </SubSection>

            <SubSection icon="add_circle" title="Two creation paths">
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>Manifest-declared</Term> — listed in{" "}
                  <Code>manifest.yaml:jobs[]</Code>. Reconciled at boot:
                  the manifest is the source of truth, so editing a
                  manifest job and redeploying overwrites whatever&apos;s
                  in the runtime DB. Use for jobs that come with the
                  bundle.
                </li>
                <li>
                  <Term>Operator-created</Term> — via{" "}
                  <Link href="/jobs/new" className="link">/jobs/new</Link>.
                  Persists to the runtime DB and survives boot. Use for
                  ad-hoc schedules (a one-off weekly demo, an experimental
                  cadence).
                </li>
              </ul>
            </SubSection>

            <SubSection icon="history" title="Run history">
              <p>
                Click any job to see its run history table — one row per
                fire, with status (succeeded / failed / running), trigger
                source (cron / manual), duration, and a link to the run
                detail page. The detail page renders the model&apos;s
                full reply (for chat actions) or the tool result (for
                tool_call actions). Telemetry from the run is preserved
                so you can replay what happened minutes or weeks later.
              </p>
            </SubSection>

            <SubSection id="permission-policies" icon="shield_lock" title="Permission policy">
              <p>
                Each job carries a declarative <Term>permission policy</Term>{" "}
                — a tool allowlist enforced by the chat route&apos;s
                tool-dispatch loop. Without a policy a job&apos;s chat turn
                can call ANY tool the agent has access to; a scheduled
                &quot;fire-bulk-logs&quot; job could technically also
                call <Code>caldera_start_operation</Code>{" "}
                if the model decided to. Permission policies let you
                scope what each job can touch.
              </p>
              <p>
                The form (Section 01, below Extended-thinking) has three
                comma-separated glob inputs:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>Allowed tools</Term> — whitelist when non-empty.
                  Tools not matching any pattern are denied. Example:{" "}
                  <Code>xlog_*, scenarios_*</Code> restricts the job to
                  the xlog and scenarios tool families.
                </li>
                <li>
                  <Term>Denied tools</Term> — blacklist. Denies even
                  tools that matched the allowed list (denied wins).
                  Example: <Code>*_delete, caldera_start_operation</Code>{" "}
                  forbids destructive tools.
                </li>
                <li>
                  <Term>Require approval</Term> — forces the standard
                  approval card for matching tools, regardless of the
                  job&apos;s <Code>bypass_approvals</Code> setting.
                  Example: <Code>xsiam_write_*, api_keys_*</Code>{" "}
                  routes credential-touching tools through operator
                  confirmation.
                </li>
              </ul>
              <p>
                Empty all three = no policy (no restrictions). Glob
                syntax: <Code>*</Code> matches any sequence,{" "}
                <Code>?</Code> matches one char, comma-separated for OR.
                When a tool is denied, the chat thread surfaces a tool-
                error response with the denial reason; the model
                continues with that signal.
              </p>
              <Callout tone="info">
                Permission policies are <strong>not a security
                boundary</strong> by themselves — the MCP-side approval
                gate stays the authoritative defense for destructive
                tools. The policy is an operator-facing scope check
                that runs BEFORE the approval gate. Defense in depth.
              </Callout>
              <Callout tone="info">
                Permission policies apply to scheduled jobs only. Skills
                affect chat-turn dispatches, which take a different code
                path, so there are no per-skill permission policies.
              </Callout>
            </SubSection>

            <SubSection id="model-routing" icon="psychology" title="Model override">
              <p>
                Each job picks its own model + extended-thinking
                preference, independent of the runtime default. The
                form&apos;s <Term>Model</Term> dropdown (Section 01,
                below Bypass-approvals) defaults to{" "}
                <strong>Router default (no override)</strong> — meaning
                &ldquo;use whatever <Code>runtimeConfig.GEMINI_MODEL</Code>{" "}
                is at dispatch time.&rdquo; Pick a specific model when:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <strong>You want cheaper dispatches</strong> on a
                  routine / high-volume job (e.g.{" "}
                  <Code>gemini-2.5-flash</Code> for a job that fires
                  every 5 minutes generating bulk log volume — Flash is
                  ~10× cheaper and the work doesn&apos;t need Pro
                  reasoning).
                </li>
                <li>
                  <strong>You want better quality</strong> on a job
                  that does real analysis (e.g.{" "}
                  <Code>gemini-3.1-pro-preview</Code> on a nightly
                  &ldquo;summarize the alert backlog&rdquo; job where
                  cost-per-fire is amortized over real insight).
                </li>
                <li>
                  <strong>You want to test a model</strong> against a
                  specific scheduled workload before promoting it to
                  the runtime default. Set the override on the job,
                  watch a week of runs in <Code>/observability/cost</Code>,
                  then make an informed change.
                </li>
              </ul>
              <p>
                The <Term>Extended thinking</Term> toggle right below
                the dropdown asks the model to use its deeper
                reasoning path (Gemini&apos;s thinkingConfig). The UI
                disables the toggle when the picked model doesn&apos;t
                support thinking; a model without thinking support
                ignores the setting.
                <em>Note:</em> the toggle is stored and sent with each
                run as <Code>body.thinking</Code>, which the chat route
                maps to <Code>thinkingConfig</Code>. Extended thinking
                is on by default for every chat turn and job run unless
                a request explicitly sends <Code>thinking: false</Code>,
                so leaving the toggle off does not turn it off.
              </p>
              <Callout tone="info">
                The override is per-job, not per-skill. If you invoke a
                skill from a job&apos;s prompt, the skill runs under
                the job&apos;s model override. Per-skill overrides apply
                to chat-turn dispatches only, not scheduled-job
                dispatches (a separate code path).
              </Callout>
            </SubSection>

            <SubSection icon="edit" title="Edit a job">
              <p>
                The <Code>⋯</Code> kebab on each job row has an{" "}
                <Term>Edit</Term> item between Pause and Duplicate. Click
                it → the new-job form opens with every field
                pre-populated from the existing row: schedule (loaded as
                Custom + raw cron — switch to Repeating to re-derive),
                timezone, action type and body, enabled flag, approval
                bypass.
              </p>
              <p>
                The <Term>name is locked</Term> — the backend PATCH
                endpoint is name-keyed and there&apos;s no rename today.
                If you need to rename, delete the job and create a new
                one (you&apos;ll lose run history). Submit changes from
                the &quot;Save Changes&quot; button at the bottom of the
                form (label flips from &quot;Create Job&quot; in
                edit mode).
              </p>
              <p>
                Manifest-source jobs accept the patch but the next
                manifest reconciliation (boot) reverts it; a runtime
                source badge tells you which is which.
              </p>
            </SubSection>

            <SubSection icon="layers" title="Two action types">
              <p>
                Every job runs as one of exactly two types — chosen at
                create time, switchable on edit:
              </p>
              <ul className="list-disc pl-5 space-y-2 text-sm">
                <li>
                  <Term>Prompt</Term> — a natural-language message
                  (&quot;send a port-scan simulation against 10.0.0.8
                  and tell me what got logged&quot;). Runs through the
                  same chat pipeline as your interactive sessions:
                  personality from{" "}
                  <Link href="/settings/personality" className="link">
                    /settings/personality
                  </Link>{" "}
                  is applied to the system prompt, the agent can call{" "}
                  <Code>memory_search</Code> /{" "}
                  <Code>knowledge_search</Code> on demand, every fired
                  tool is audited, and any{" "}
                  <Code>humanRequired</Code> tool surfaces the same
                  approval card flow (or auto-approves when the
                  job&apos;s &quot;bypass approvals&quot; toggle is on).
                  Best for fuzzy intent, multi-step reasoning, and
                  anything where the exact tool sequence isn&apos;t
                  known up-front.
                </li>
                <li>
                  <Term>Tool call</Term> — direct MCP tool invocation
                  with explicit args (<Code>name</Code> +{" "}
                  <Code>args</Code>). No LLM, no chat handler.
                  Deterministic. Best for log generation, recurring
                  queries, anything where the args are known and the
                  same exact call needs to fire on schedule.
                </li>
              </ul>
            </SubSection>

            <SubSection icon="extension" title="Bind a job to a specific skill">
              <p>
                Prompt-action jobs grew an optional{" "}
                <Term>Skill</Term> dropdown below the prompt textarea.
                Default is <em>Let agent decide</em> — the model
                sees the full skills registry in its system prompt
                (every chat turn fetches it live, including scheduled
                runs) and picks one based on intent. Pick a specific
                skill instead if you want the run to be deterministic
                regardless of model drift: at fire time, the
                scheduler resolves the skill MD body and prepends it
                to your prompt inside{" "}
                <Code>&lt;skill name=&quot;…&quot;&gt;</Code> tags so
                the agent treats it as authoritative runbook context.
              </p>
              <p>
                Useful for reproducible scheduled exercises — &ldquo;run
                the ransomware double-extortion scenario every Sunday
                at 06:00&rdquo; should always run the same scenario,
                not whatever the model thinks fits the prompt that
                week. The dropdown is grouped by category and
                populated live from the skills registry, so newly
                created skills appear in it without restart.
              </p>
              <p>
                If a skill is later deleted but a job still references
                it, the run logs a warning and falls back to the plain
                prompt — the job doesn&apos;t fail. Edit the job to
                pick a different skill (or none) when you see the
                warning.
              </p>
            </SubSection>

            <SubSection icon="notifications_active" title="Notifications on every run">
              <p>
                Every scheduled job run now publishes a notification
                on completion. Two topics:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Code>job-run-completed</Code> (severity{" "}
                  <Term>info</Term>) — fired on success.
                </li>
                <li>
                  <Code>job-run-failed</Code> (severity{" "}
                  <Term>warning</Term>) — fired on failure; the
                  payload includes the error string and a one-line
                  summary so the bell card has something readable
                  without parsing result_json.
                </li>
              </ul>
              <p>
                Skipped runs (cron-cap squelching, paused jobs)
                don&apos;t emit — they&apos;re scheduling noise.
                Notifications appear on{" "}
                <Link href="/notifications" className="link">
                  /notifications
                </Link>{" "}
                and update the bell badge in the top nav. The
                payload also carries{" "}
                <Code>{`{job_name, run_id, trigger, action_name, duration_ms, next_due_at}`}</Code>{" "}
                so a click-through can route back to the run detail
                page.
              </p>
            </SubSection>

            <SubSection icon="import_export" title="Export + Import">
              <p>
                Two export options, both JSON, both surfaced under the{" "}
                <Code>⋯</Code> kebab:
              </p>
              <ul className="list-disc pl-5 space-y-2 text-sm">
                <li>
                  <Term>Export definition (.json)</Term> — pure
                  definition. The blob is exactly what{" "}
                  <Code>POST /api/v1/jobs</Code> accepts, so it imports
                  cleanly into another deployment. Available on every
                  row in the list view AND on the detail page.
                </li>
                <li>
                  <Term>Export runs (.json)</Term> — definition +
                  every run from the run-history table. Detail page
                  only (the list view doesn&apos;t load runs). Filename
                  ends in <Code>-with-runs.json</Code>. For forensic
                  snapshots — the runs are NOT importable as run history
                  (per policy below).
                </li>
              </ul>
              <p>
                The <Term>Import</Term> button on the{" "}
                <Link href="/jobs" className="link">/jobs</Link> page
                (next to Create Job) accepts either export shape.
                Behavior:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  Pick a <Code>.json</Code> file → the import button
                  reads it, extracts the <Code>job</Code> block,
                  validates the envelope&apos;s <Code>schema_version</Code>,
                  POSTs to the create endpoint.
                </li>
                <li>
                  If the file came from a <Code>-with-runs.json</Code>{" "}
                  export, the <Code>runs</Code> array is silently
                  dropped — only the definition is imported. Run
                  history is read-only ground truth, not portable
                  state.
                </li>
                <li>
                  On a name conflict (the imported job&apos;s name is
                  already taken), the create endpoint returns 400 with
                  the exact error: &quot;job &apos;X&apos; already
                  exists&quot;. Edit the JSON&apos;s <Code>name</Code>{" "}
                  field and re-import.
                </li>
                <li>
                  The MCP&apos;s create endpoint also rejects unknown
                  action types — if you import an old export with{" "}
                  <Code>type: log</Code>, you&apos;ll get &quot;must be
                  one of tool_call|prompt&quot;. Export-then-import a
                  fresh definition (boot migration normalizes legacy
                  shapes) and it&apos;ll round-trip.
                </li>
              </ul>
            </SubSection>
          </Section>

          <Section
            id="models-providers"
            icon="psychology"
            title="Models & Providers"
          >
            <p>
              <Link href="/models" className="link">/models</Link> shows every
              model the agent can route to, grouped by interaction kind
              (Chat, CLI, Embedding, Image, Voice). Each model card lists
              its provider, capability flags (streaming, tool_use), and
              context window. The active tab uses the same green-active
              treatment as the sidebar.
            </p>
            <p>
              <Link href="/providers" className="link">/providers</Link> manages
              credentials. Vertex AI is the default — the setup form
              writes the service-account JSON into the secret store, and
              the bundle&apos;s <Code>requiredSecrets</Code> declares
              where it lands.
            </p>

            <SubSection icon="route" title="Resolution logic">
              <p>
                The bundle&apos;s <Code>modelRequirements</Code> in{" "}
                <Code>manifest.yaml</Code> declares minimum capabilities:
              </p>
              <Pre>{`modelRequirements:
  primary:
    kind: chat
    mustSupport: [streaming, tool_use]
    contextWindowMin: 100000
    preferFamily: [gemini-3, gemini-2.5, gpt-4o]
  fallback:
    kind: chat
    mustSupport: [streaming, tool_use]
    contextWindowMin: 32000`}</Pre>
              <p>
                At chat time, the resolver scans available providers,
                picks the first model that meets <Code>primary</Code>
                requirements, and falls back to <Code>fallback</Code> if
                primary is unavailable. The chosen model shows in the
                chat&apos;s telemetry panel.
              </p>
            </SubSection>
          </Section>

          {/* ============================================================
                               INTEGRATION
              ============================================================ */}

          <Section id="connectors" icon="cable" title="Connectors & Instances">
            <p>
              <Link href="/connectors" className="link">/connectors</Link> is
              where you manage two related concepts:
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-sm">
              <li>
                A <Term>connector</Term> is the catalogue entry — an id,
                config schema, secret slots, tool list, and the OCI
                container image that runs when an instance is created.
                Two flavors:{" "}
                <Code>origin: bundle</Code> (the 9 connectors shipped in
                the release: caldera, cortex-content, cortex-docs,
                cortex-xdr, http-sender, web, wec-sender, xlog, xsiam) and{" "}
                <Code>origin: user</Code> (connectors you upload via
                the marketplace).
              </li>
              <li>
                An <Term>instance</Term> is a configured copy of a
                connector — credentials bound, target URL set, ready
                to dispatch tool calls. Fresh installs come up with{" "}
                <Term>zero</Term> instances. Instance creation
                requires you to install the connector from the
                marketplace first; tool registration requires both
                installed AND at least one enabled instance. The
                install gate is functional, not decorative.
              </li>
            </ul>
            <p className="text-sm text-on-surface-variant">
              Universal container-mode: every instance runs as its own{" "}
              <Code>phantom-connector-&lt;id&gt;-&lt;name&gt;</Code>{" "}
              container, started by phantom-updater when the instance
              row is created. Tool calls flow from the agent&apos;s MCP
              to the container over loopback HTTPS.
            </p>

            <SubSection icon="dynamic_form" title="The instance creation form">
              <p>
                Click <strong>Create Instance</strong> on any installed
                connector card. The form has two sections:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <strong>Instance Identity</strong> — instance name +
                  optional description.
                </li>
                <li>
                  <strong>Configuration</strong> — one input per field
                  declared by the connector. The widget type is picked
                  by the connector schema (text, masked password,
                  multiline textarea, dropdown, radio buttons, chip
                  list, toggle switch). Required fields are marked with
                  a red asterisk; the <strong>Create Instance</strong>{" "}
                  button stays disabled until every required field has
                  a value.
                </li>
              </ul>
              <p className="text-sm leading-relaxed mt-2">
                The form supports multiple widget types from the
                connector schema (<Code>type: &quot;url&quot;</Code>,{" "}
                <Code>type: &quot;string&quot;</Code>, and so on). Every
                field renders in one unified Configuration section in
                the order the connector declares them. Sensitive fields (API keys, passwords)
                render masked with an eye-toggle to reveal; non-sensitive
                fields (URLs, IDs, hostnames) render in clear text.
              </p>
            </SubSection>

            <SubSection icon="cable" title="The three connectors">
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>caldera</Term> — MITRE ATT&amp;CK adversary
                  emulation. Tools include <Code>start_operation</Code>,{" "}
                  <Code>list_abilities</Code>, <Code>get_results</Code>,{" "}
                  <Code>list_agents</Code>.
                </li>
                <li>
                  <Term>xlog</Term> — synthetic telemetry generator. Tools
                  include <Code>create_worker</Code>,{" "}
                  <Code>create_scenario_worker</Code>,{" "}
                  <Code>send_observable</Code>,{" "}
                  <Code>list_workers</Code>.
                </li>
                <li>
                  <Term>xsiam</Term> — Cortex XSIAM PAPI gateway. Tools
                  include <Code>run_xql</Code>,{" "}
                  <Code>find_xql_examples_rag</Code>, detection content
                  CRUD, and issue stream readers.
                </li>
              </ul>
            </SubSection>

            <SubSection icon="lock" title="Secret storage">
              <p>
                Per-instance credentials live encrypted at rest under a
                <Code>PHANTOM_SECRET_KEK</Code> envelope (AES-256-GCM).
                Secrets never leave the MCP container; the API redacts
                them as <Code>***</Code> on read. Rotating a credential
                writes a new envelope; the old one is GC&apos;d on the
                next sweep.
              </p>
            </SubSection>

            <SubSection icon="settings_backup_restore" title="Caldera password — setup form to caldera handoff">
              <p>
                The caldera password from your setup form flows
                directly into the running caldera container, no manual
                <Code> docker compose restart caldera</Code> needed:
              </p>
              <ol className="list-decimal pl-5 space-y-1.5 text-sm">
                <li>
                  You type a new <Code>calderaRedPassword</Code> in
                  <Link href="/setup" className="link"> /setup</Link> and
                  click Save.
                </li>
                <li>
                  Agent writes the password to a shared docker volume
                  (<Code>phantom_operator_creds:/operator-creds/caldera.yaml</Code>).
                </li>
                <li>
                  Agent POSTs to phantom-updater asking it to restart caldera.
                </li>
                <li>
                  Caldera&apos;s entrypoint reads the bridge file on startup
                  and regenerates its <Code>local.yml</Code> with your
                  typed password (logs:{" "}
                  <Code>[caldera-init] applied operator creds from /operator-creds/caldera.yaml</Code>).
                </li>
              </ol>
            </SubSection>

            <SubSection icon="verified_user" title="Per-instance trusted flag">
              <p>
                Each instance config supports a <Code>trusted</Code>{" "}
                boolean. Default is <Code>false</Code>; set
                to <Code>true</Code> to mark the instance as a trusted
                lab connector — tool calls against it bypass the
                approval gate even if the manifest re-adds those tools to
                the gate list. Untrusted instances respect whatever the
                manifest says.
              </p>
              <p className="text-sm text-on-surface-variant mt-2">
                Set via PATCH:
              </p>
              <pre className="text-xs bg-surface-container-low p-3 rounded">
{`curl -X PATCH /api/v1/agent/instances/<id> \\
  -H 'Content-Type: application/json' \\
  -d '{"config": {"trusted": true}}'`}
              </pre>
              <p className="text-sm text-on-surface-variant mt-2">
                There is no UI checkbox for this flag; use the call above. The
                manifest&apos;s <Code>humanRequired</Code> list is
                already empty for connector tools (caldera, xsiam),
                making the trusted flag less critical for default
                deployments.
              </p>
            </SubSection>
          </Section>

          {/* Connector health page operator UX. */}
          <Section
            id="connector-health-ux"
            icon="monitor_heart"
            title="Connector Health"
          >
            <p>
              <Link
                href="/observability/connectors"
                className="link"
              >
                /observability/connectors
              </Link>{" "}
              is the per-instance state-machine view. While{" "}
              <a href="#connectors" className="link">/connectors</a> shows
              you the static catalog and credentials, this page shows the
              live state of each instance — last probe result, current
              state, and a reauth shortcut when credentials have expired.
            </p>

            <SubSection icon="account_tree" title="The five states">
              <Pre>{`enabled         ── healthy + reachable; tools dispatch normally
disabled        ── operator-paused; tools refuse to dispatch
failed          ── last probe returned an error; auto-retried with backoff
auth_required   ── 401 / token-expired; needs operator credential refresh
probed          ── transient state during an in-flight probe`}</Pre>
              <p>
                State transitions write{" "}
                <Code>connector_enabled</Code>,{" "}
                <Code>connector_disabled</Code>,{" "}
                <Code>connector_failed</Code>,{" "}
                <Code>connector_auth_required</Code>,{" "}
                <Code>connector_probed</Code> audit rows so the page can
                reconstruct full state history.
              </p>
            </SubSection>

            <SubSection icon="key" title="Reauth flow">
              <p>
                When an instance hits <Code>auth_required</Code> (the
                most common cause: XSIAM PAPI tokens expiring after 90
                days), the row turns amber and a <Term>Reauth</Term>{" "}
                button appears. Click it → the setup form opens with that
                instance&apos;s fields prefilled (URL, auth ID, etc.) and
                only the secret slots empty. Submit → the instance flips
                back to <Code>enabled</Code> on the next probe (within
                30s).
              </p>
              <p>
                You can also reauth proactively from the connector detail
                drawer — useful before a long-running scenario where
                you&apos;d rather not have a token expire mid-run.
              </p>
            </SubSection>

            <SubSection icon="history" title="Probe history">
              <p>
                Each row expands into a <Term>last 50 probes</Term>{" "}
                table: timestamp, HTTP code, latency, error message (if
                any). Useful for distinguishing &quot;intermittent
                network blip&quot; from &quot;the connector has been
                degraded for 4 hours and we just noticed.&quot;
              </p>
            </SubSection>

            <Callout tone="info">
              Disabled instances are <em>operator-paused</em>, not broken —
              tools just refuse to dispatch. Use this when running
              maintenance on a downstream system you don&apos;t want the
              agent calling. Re-enable from the same page; nothing else
              changes.
            </Callout>
          </Section>

          <Section
            id="detection-inventory"
            icon="radar"
            title="Detection inventory"
          >
            <p>
              <Link
                href="/observability/detections"
                className="link"
              >
                /observability/detections
              </Link>{" "}
              is the operator-browsable view of your SIEM&apos;s detection
              rules + fire history. The same data is available through
              the <Code>detections_list</Code> chat tool; this page
              lets you browse the inventory and MITRE coverage without
              typing a chat command.
            </p>

            <SubSection icon="table_chart" title="Two tabs">
              <p>
                <strong>Rules tab</strong> — table of detection rules
                with severity badge, MITRE technique chips, fire counts
                in standard windows (24h / 7d / 30d / total), and last-
                fire timestamp. Filter by severity bucket or MITRE
                T-code.
              </p>
              <p>
                <strong>Coverage tab</strong> — per-MITRE-T-code
                aggregation showing how many rules + total fires hit
                each technique. Useful for spotting coverage gaps in
                your detection content.
              </p>
            </SubSection>

            <SubSection icon="sync" title="Seeding the inventory">
              <p>
                Empty page on first visit is expected — detection data
                isn&apos;t auto-pulled. Seed it via:
              </p>
              <ul>
                <li>
                  Ask Phantom to run the coverage cycle
                  (<Code>coverage_cycle_run</Code>) via chat — it queries
                  your SIEM, bulk-upserts the rules, and takes a coverage
                  snapshot in one pass
                </li>
                <li>
                  Or POST a pre-fetched issues array to{" "}
                  <Code>/api/agent/detections/sync</Code> for external
                  tooling integration
                </li>
                <li>
                  Add <Code>coverage_cycle_run</Code> as a recurring job
                  via <Link href="/jobs/new" className="link">/jobs/new</Link>{" "}
                  for automatic daily syncing — it isn&apos;t seeded by
                  default
                </li>
              </ul>
            </SubSection>
          </Section>

          <Section id="marketplace" icon="storefront" title="Marketplace">
            <p>
              The Marketplace tab on{" "}
              <Link href="/connectors" className="link">/connectors</Link>{" "}
              shows the connector catalogue: 9 bundle-shipped connectors
              (caldera, cortex-content, cortex-docs, cortex-xdr,
              http-sender, web, wec-sender, xlog, xsiam)
              plus any user-uploaded connectors. Every card shows
              version, tool count, install state, origin (bundle or
              user), tags, and instances count.
            </p>
            <p>
              Fresh installs come up with all 9 bundle connectors in
              the catalogue marked &quot;available, not installed.&quot;
              No instances exist yet. The marketplace is the explicit
              first-step entry point — you install, then you create
              instances from the Instances tab.
            </p>

            <SubSection icon="install_desktop" title="Install + Uninstall">
              <p>
                Click a marketplace card → a drawer opens with the
                connector&apos;s tool list, config schema, and the
                Install button (or Installed badge + Uninstall button
                when already installed).
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>Install Connector</Term> — flips the install
                  state row in{" "}
                  <Code>/app/data/marketplace.db</Code>. Makes the
                  connector AVAILABLE for instance creation. Does NOT
                  create an instance yet — that&apos;s a separate
                  step in the Instances tab where you wire up
                  credentials and config.
                </li>
                <li>
                  <Term>Uninstall</Term> — removes the install state
                  row. Refuses with a 409 toast if any instances
                  exist for the connector — delete the instances
                  first. The connector stays in the catalogue (bundle
                  ones are image-baked, can&apos;t actually be
                  removed); future Install clicks succeed without
                  re-downloading anything.
                </li>
              </ul>
              <p className="text-sm">
                Install state is a real gate: instance creation
                against an uninstalled connector returns 409{" "}
                <Code>connector_not_installed</Code>. Both actions
                emit audit events (<Code>marketplace_install</Code> /{" "}
                <Code>marketplace_uninstall</Code>) visible in{" "}
                <Link href="/observability/events" className="link">
                  /observability/events
                </Link>.
              </p>
            </SubSection>

            <SubSection icon="upload_file" title="Upload your own connector">
              <p>
                You can upload custom <Code>connector.yaml</Code> files
                to add your own connectors to the marketplace alongside
                the 9 bundle-shipped ones. Workflow:
              </p>
              <ol className="list-decimal pl-5 space-y-1.5 text-sm">
                <li>
                  Build + publish your connector container image to any
                  OCI registry phantom-updater can pull from (GHCR,
                  Docker Hub, ECR, your private registry, etc.). The
                  image must run the{" "}
                  <Code>phantom-connector-runtime</Code> entrypoint
                  (FROM <Code>ghcr.io/ayman-m/phantom-connector-runtime-oss:latest</Code>{" "}
                  is the supported base — see{" "}
                  <Code>bundles/spark/connectors/_runtime/Dockerfile</Code>{" "}
                  for the pattern).
                </li>
                <li>
                  Write your <Code>connector.yaml</Code> with{" "}
                  <Code>runtimeMapping.style: container</Code> + an{" "}
                  <Code>image</Code> field carrying the published
                  reference (e.g.{" "}
                  <Code>image: ghcr.io/your-org/your-connector:v1.0</Code>).
                  See{" "}
                  <Code>bundles/spark/connectors/connector.schema.json</Code>{" "}
                  for the full schema. The schema validator runs at
                  upload time + at boot; drift fails fast with a
                  path-into-the-field error.
                </li>
                <li>
                  Click the{" "}
                  <Term>Upload Connector</Term> button on the
                  Marketplace tab → file picker → select your YAML →
                  submit. (Or use curl with bearer{" "}
                  <Code>MCP_TOKEN</Code>:{" "}
                  <Code>curl -F connector_yaml=@your-connector.yaml https://&lt;host&gt;:8080/api/v1/marketplace/upload</Code>.)
                </li>
                <li>
                  The connector appears in the marketplace with{" "}
                  <Code>origin: user</Code>. Install it, then create
                  an instance from the Instances tab. Same flow as
                  any bundle connector from there on.
                </li>
              </ol>
              <p className="text-sm text-on-surface-variant">
                User connectors are deletable via DELETE{" "}
                <Code>/api/v1/marketplace/&lt;id&gt;</Code> (refuses if
                instances exist). Bundle connectors are 403-rejected
                on DELETE — they&apos;re image-baked and can&apos;t be
                removed at runtime; use Uninstall to hide them from
                instance creation.
              </p>
            </SubSection>

            <SubSection icon="smart_toy" title="Ask the agent to manage the marketplace">
              <p>
                The chat agent has 4 marketplace tools in its
                catalogue:{" "}
                <Code>marketplace_list</Code> (read-only catalogue +
                install state),{" "}
                <Code>marketplace_install(connector_id)</Code>,{" "}
                <Code>marketplace_uninstall(connector_id)</Code>, and{" "}
                <Code>connector_upload(yaml_content)</Code>. So you
                can say things like &ldquo;install the web
                connector,&rdquo; &ldquo;what connectors do I have
                installed?,&rdquo; or &ldquo;upload this connector
                YAML&rdquo; and the agent will do the catalogue
                management.
              </p>
              <p className="text-sm">
                Instance creation stays operator-only by design — the
                instance form takes credentials (API keys, service
                URLs, etc.), and the agent credential guardrail
                keeps the agent away from anything that writes a
                secret. The agent can hand you a fully-installed
                connector but you fill in the credentials yourself.
              </p>
              <p className="text-sm">
                Once you have created an instance of a connector you
                uploaded, its tools work exactly like a bundled
                connector&apos;s: the chat agent can call them, the
                connector shows up on{" "}
                <Link href="/observability/connectors" className="link">
                  /observability/connectors
                </Link>{" "}
                with an &quot;uploaded&quot; tag, and its Tools tab
                lists each tool so you can switch individual ones
                off. No restart is needed.
              </p>
            </SubSection>

            <SubSection icon="apps" title="Container-style vs module-style connectors">
              <p>
                Connectors come in two runtime flavors, set by{" "}
                <Code>connector.yaml:runtimeMapping.style</Code>:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>module</Term> (legacy default, used by xlog +
                  caldera + xsiam today) — connector code runs in-process
                  inside the agent. Tool calls are direct Python function
                  invocations.
                </li>
                <li>
                  <Term>container</Term> (used by web today) — each
                  instance gets its own Docker container that{" "}
                  phantom-updater starts when you create the instance and
                  stops when you delete it. The agent&apos;s tool-dispatch
                  loader becomes a routing proxy that forwards calls over
                  MCP-over-HTTP to{" "}
                  <Code>http://phantom-connector-&lt;id&gt;-&lt;name&gt;:9000</Code>.
                  Crash isolation, resource isolation, independent
                  versioning. See the{" "}
                  <Link
                    href="/help/architecture#connector-containers"
                    className="link"
                  >
                    Connector Containers architecture section
                  </Link>{" "}
                  for the full design.
                </li>
              </ul>
              <p className="text-sm text-on-surface-variant/80">
                Operator-facing experience is identical regardless of
                style — Install + Create Instance work the same way. The
                only operational difference: container-style connectors
                need <Code>phantom-updater</Code> running and need pull
                access to the connector&apos;s GHCR image. For
                disconnected installs, see the{" "}
                <Link
                  href="/help/architecture#phantom-updater"
                  className="link"
                >
                  phantom-updater
                </Link>{" "}
                section&apos;s &quot;cached&quot; pull-fallback note.
              </p>
            </SubSection>

            <SubSection icon="toggle_on" title="Per-instance tool toggle">
              <p>
                Each connector ships a defined set of tools the agent
                can call. By default every tool the connector exposes
                is enabled. For instances with large tool catalogs
                (the Cortex XDR connector ships 51 tools),
                you can selectively disable tools to bound the agent&apos;s
                catalog noise OR to lock down destructive actions.
              </p>
              <ol className="list-decimal pl-5 space-y-1.5 text-sm">
                <li>
                  Expand any instance row in <Term>Instances</Term> tab,
                  click <Term>Show Tools</Term>.
                </li>
                <li>
                  A grid of checkboxes appears, one per tool. The
                  header shows &quot;N/M tools enabled for the agent.&quot;
                </li>
                <li>
                  Uncheck a tool to hide it from the agent. The change
                  PATCH-es to the instance, audit-logs as{" "}
                  <Code>instance_tool_toggle</Code>, and takes effect
                  on the next tool call.
                </li>
                <li>
                  Mass actions: <Term>Enable all</Term> /{" "}
                  <Term>Disable all</Term> apply to every tool the
                  connector ships.
                </li>
              </ol>
              <p className="text-sm">
                Use cases: hide{" "}
                <Code>xdr_endpoints_scan_all</Code> (high-impact),
                disable IoC mutators (<Code>xdr_ioc_disable</Code>,
                <Code>xdr_ioc_enable</Code>) on a hardened tenant,
                trim agent context budget by disabling tools you
                never use.
              </p>
              <p className="text-sm text-on-surface-variant">
                Toggle state is per-instance. Two XDR tenants (two
                instances) can have different sets of tools enabled
                — the agent picks the right set based on which
                instance handles the request.
              </p>
            </SubSection>

            <SubSection icon="dashboard" title="Instance state + tabs">
              <p>
                The Instances tab next to Marketplace lists configured
                connector instances with health status and last-edit
                timestamps. Clicking an instance opens a config panel
                where you can rotate credentials or edit the
                wire-up. The agent automatically picks the right instance
                when you mention a system by name in chat (&quot;run X on
                caldera&quot; → primary-caldera).
              </p>
              <p className="text-sm">
                Install state has two sources today, union&apos;d server-side:
              </p>
              <ul className="list-disc pl-5 space-y-1 text-sm">
                <li>
                  Explicit operator clicks (the JSON store written by the
                  Install button).
                </li>
                <li>
                  Instance presence — any connector with ≥1 instance
                  counts as installed even without the explicit ack.
                  Covers the env-var bootstrap path: a fresh install
                  whose <Code>.env</Code> has{" "}
                  <Code>XSIAM_API_KEY</Code> auto-creates an xsiam
                  instance at boot, and the marketplace card shows
                  &quot;Installed&quot; without the operator ever
                  clicking the button.
                </li>
              </ul>
            </SubSection>
          </Section>

          {/* Data Sources marketplace — vendor schemas. */}
          <Section id="data-sources" icon="dataset" title="Data Sources">
            <p>
              The Data Sources page at{" "}
              <Link href="/data-sources" className="link">/data-sources</Link>{" "}
              is a separate marketplace from{" "}
              <Link href="/connectors" className="link">/connectors</Link>.
              Where the connector marketplace controls{" "}
              <em>which systems Phantom can talk to</em>, Data Sources
              controls <em>which vendor log shapes Phantom can synthesize</em>.
              They&apos;re independent — install one without the other,
              uninstall one without the other.
            </p>
            <p>
              When you install a data source, Phantom learns the
              vendor&apos;s actual field schema (e.g. FortiGate emits{" "}
              <Code>srcip</Code> / <Code>dstport</Code> / <Code>sentbyte</Code>,
              not <Code>local_ip</Code> / <Code>remote_port</Code>). The
              chat agent can then generate synthetic logs whose
              top-level keys match what the vendor actually sends —
              so any downstream system that already knows the vendor
              parses them cleanly. That includes the vendor&apos;s
              own SIEM connector, a Splunk technology add-on, a
              Sentinel parser, an Elastic ingest pipeline, or
              whatever bespoke parsing you run on your destination
              platform. Without an installed data source, the agent
              falls back to Phantom&apos;s generic synthesis (works
              for dashboards, doesn&apos;t parse cleanly through any
              vendor-specific pipeline).
            </p>
            <p className="text-sm text-on-surface-variant">
              Fresh installs come up with Data Sources Installed (0).
              The catalog ships bundled with Phantom — 130+ vendors
              cover the major SIEM/EDR/firewall/identity products. Every
              bundled source is a real Cortex XSIAM ingest+parse path, not
              an action-only integration. No setup, no external accounts,
              no internet.
            </p>

            <SubSection icon="library_books" title="Installed — manage what's loaded">
              <p>
                The default <Term>Installed</Term> tab shows what you
                already have. Each card carries: vendor logo, pack +
                rule + dataset name, field count, supported modules
                chips, version tag, and the install date.
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>Click a card</Term> → a detail drawer slides
                  in from the right with 4 stat tiles (field count,
                  meta vs vendor split, pack version, install date),
                  the supported-modules chip row, the full XDM
                  mapping table (if any), and a sortable field-list
                  table grouped into meta fields (faded;{" "}
                  <Code>_id</Code> / <Code>_time</Code> /{" "}
                  <Code>_raw_log</Code> / etc.) and vendor-specific
                  fields. Type into the filter box to narrow the
                  field list without a server round-trip.
                </li>
                <li>
                  <Term>Uninstall</Term> — the trash icon on each card
                  opens a ruby-red confirmation modal. Removal drops
                  the install row + all field rows + all XDM mapping
                  rows (FK cascade). The bundled catalog row stays in
                  Browse — uninstalling just removes your local install
                  state; a future Install click re-creates it without
                  re-downloading anything.
                </li>
              </ul>
              <p className="text-sm text-on-surface-variant">
                Uninstall is destructive in the sense that any
                in-flight skill or chat thread referencing the
                installed schema will fall back to Phantom&apos;s
                generic synthesis on its next invocation. If you
                accidentally uninstall, the simplest recovery is to
                re-install from Browse — the catalog row is still
                there.
              </p>
              <p className="text-sm">
                <strong>Upgrades keep installed sources current.</strong> When a new Phantom version ships
                a corrected schema for a data source you already have
                installed, the installed copy is updated the next time
                Phantom starts. You don&apos;t need to re-install it.
                A source you&apos;ve <em>pinned</em> is left as it is.
                A source you&apos;ve <em>edited</em> keeps your edit:
                your changes reach the schema Phantom
                actually generates from the moment you save them, and
                aren&apos;t overwritten by an upgrade. To see what was
                updated, open{" "}
                <Link href="/observability/events" className="link">
                  Observability → Events
                </Link>{" "}
                and pick <Term>Data source refreshes</Term>.
              </p>
            </SubSection>

            <SubSection icon="smart_toy" title="Ask the agent — vendor-faithful simulation">
              <p>
                Once a data source is installed, mention the vendor
                name in chat and the agent matches the{" "}
                <Code>simulate_vendor_logs</Code> skill. Examples:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>&ldquo;Simulate 50 FortiGate traffic logs&rdquo;</li>
                <li>&ldquo;Generate Okta authentication events with these IPs: 192.168.1.100&rdquo;</li>
                <li>&ldquo;Create some PaloAlto firewall logs to udp:10.0.0.8:514&rdquo;</li>
                <li>&ldquo;I need 100 CrowdStrike detection events for my dashboard&rdquo;</li>
              </ul>
              <p>
                The agent looks up the installed schema, asks xlog to
                synthesize records using the vendor&apos;s actual
                field names, then either streams the records back
                (default) or forwards them to your configured sink
                (syslog UDP, HTTPS webhook, etc.). If no installed
                schema matches the vendor you mentioned, the agent
                tells you so and points you back to{" "}
                <Link href="/data-sources" className="link">/data-sources</Link> →
                Browse — it never auto-installs.
              </p>
              <p className="text-sm">
                The agent has 3 data-sources tools available:{" "}
                <Code>data_sources_list(filter)</Code> (read-only
                listing of what you have installed),{" "}
                <Code>data_sources_get_schema(id)</Code> (full field
                inventory for one data source), and{" "}
                <Code>data_sources_install(pack, rule, dataset?)</Code>{" "}
                (idempotent install, used when you say &ldquo;yes,
                install it&rdquo; in chat). All three are on the
                catalog side of the agent guardrail — no secrets, no
                credentials. Uninstall stays UI-only by design.
              </p>
            </SubSection>

            <SubSection icon="psychology" title="What 'vendor-faithful' means under the hood">
              <p>
                Phantom&apos;s generic synthesis emits records with
                generic field names like <Code>local_ip</Code> /{" "}
                <Code>remote_port</Code>. Those work for charts that
                count records but DON&apos;T parse cleanly through
                any vendor-specific pipeline downstream — the
                receiving SIEM, EDR, or log platform expects the
                vendor&apos;s native field names. Any
                parser-by-vendor-name lookup misses fields it
                can&apos;t find.
              </p>
              <p>
                Installing a data source teaches xlog the
                vendor&apos;s actual field names, types, and
                observable patterns. When you ask for FortiGate logs
                after install, generated records have{" "}
                <Code>srcip</Code> + <Code>srcport</Code> +{" "}
                <Code>dstip</Code> + <Code>dstport</Code> +{" "}
                <Code>proto</Code> + <Code>action</Code> +{" "}
                <Code>sentbyte</Code> + <Code>rcvdbyte</Code> at the
                top level. Any downstream system that already knows
                FortiGate — its vendor-supplied SIEM connector, a
                Splunk technology add-on, a Sentinel parser, an
                Elastic ingest pipeline, a Cortex XSIAM modeling
                rule — ingests them cleanly. End result: simulated
                FortiGate traffic looks identical to real traffic
                from a live FortiGate, no matter which platform is
                doing the parsing.
              </p>
              <p className="text-sm">
                See the{" "}
                <Link href="/help/architecture#data-sources" className="link">
                  architecture page&apos;s Data Sources section
                </Link>{" "}
                for the storage model + REST surface + skill chain
                details.
              </p>
            </SubSection>

            <SubSection icon="filter_alt" title="Browse, filter, install">
              <p>
                The Browse tab groups the catalog by <em>vendor</em>{" "}
                — one card per vendor across all the vendor&apos;s
                packs. Each card carries <em>product-type</em>{" "}
                use-case labels like <Code>WAF</Code>,{" "}
                <Code>LoadBalancer</Code>, <Code>Identity</Code>,{" "}
                <Code>MFA</Code>, <Code>PAM</Code>, <Code>Email</Code>,{" "}
                <Code>Storage</Code>, <Code>Cloud</Code>. The taxonomy
                covers 44 labels across 8 domains (Network, Endpoint,
                Identity, Data, Cloud, Apps, SecOps, Specialty) —
                see the{" "}
                <Link href="/help/architecture#data-sources" className="link">
                  architecture spec
                </Link>{" "}
                for the canonical list.
              </p>
              <p>
                <strong>Use-case filter dropdown</strong>: above the
                catalog grid, the <Term>Use case</Term> trigger opens
                a multi-select dropdown panel. Tick checkboxes to
                narrow the grid: pick <Code>WAF</Code> → the grid
                narrows to F5, Cloudflare, Imperva, Barracuda,
                Radware, Akamai, Fortinet. Multi-select via
                additional checkboxes — vendors matching <em>any</em>{" "}
                of the selected use cases survive (OR semantics). One
                data source can have multiple use cases (Cisco
                appears under both <Code>Firewall</Code> and{" "}
                <Code>EDR</Code>). The panel includes a
                search-within-panel input plus <Term>All</Term> and{" "}
                <Term>Clear</Term> shortcuts. Selected use cases also
                render as inline removable pills next to the trigger
                so the active filter set is visible at a glance — click
                any pill to remove that one filter without opening
                the panel.
              </p>
              <p>
                <strong>Install flow</strong>:
              </p>
              <ol className="list-decimal pl-5 space-y-1.5 text-sm">
                <li>
                  Click a vendor card → it expands inline to show the
                  vendor&apos;s individual packs (each a separate
                  pack/rule/dataset triple).
                </li>
                <li>
                  Each pack row carries a pill-shaped <Term>Install</Term>{" "}
                  button. Click it to install just that one pack.
                </li>
                <li>
                  Or click anywhere on a pack&apos;s name → opens
                  the side drawer with the full field inventory + XDM
                  mappings + a primary <Term>Install data source</Term>{" "}
                  CTA at the footer. This works for uninstalled packs
                  too — the drawer renders in <Term>Preview</Term>{" "}
                  mode with the Install button at the bottom.
                </li>
                <li>
                  Installed packs show on the <Term>Installed</Term>{" "}
                  tab with the vendor logo (consistent across siblings
                  — F5ASM, F5LTM, F5APM all carry the F5 mark).
                </li>
              </ol>
              <p className="text-sm text-on-surface-variant">
                Install writes a row in{" "}
                <Code>/app/data/data_sources.db</Code> with the full
                field inventory and per-field metadata (name, type,
                description, and — for composite fields — a concrete
                example shape so generated records match what
                downstream parsers expect). Reinstalling an
                already-installed data source is idempotent.
              </p>
              <p className="text-sm text-on-surface-variant">
                <strong>Validation pills.</strong> Some
                Browse cards carry a small pill telling you how far we
                proved the source against a live XSIAM tenant. A green{" "}
                <Term>Mapping Validated</Term> pill means we streamed
                synthetic logs end-to-end and confirmed the vendor&apos;s
                modeling rule populates the unified data model
                (<Code>xdm.*</Code>) — the source maps. An amber{" "}
                <Term>Raw Validated</Term> pill means the vendor&apos;s
                content pack wasn&apos;t installed on our test tenant
                (so mapping couldn&apos;t be exercised), but a raw query
                confirmed our synthetic data lands the exact field names
                the rule reads — proven-correct shape that will map the
                moment you install the pack. A card with no pill simply
                hasn&apos;t been live-tested yet; it still generates
                wire-faithful logs.
              </p>
            </SubSection>

            <SubSection icon="upload_file" title="Upload a custom data source">
              <p>
                For vendors not in the bundled catalog, operators
                upload their own <Code>data_source.yaml</Code>:
              </p>
              <ol className="list-decimal pl-5 space-y-1.5 text-sm">
                <li>
                  On <Link href="/data-sources" className="link">/data-sources</Link>{" "}
                  → click <Term>Upload</Term> in the toolbar.
                </li>
                <li>
                  Paste YAML text or drop a file. The dialog{" "}
                  <em>previews</em> the parsed contents and runs a
                  similarity check against the existing vendor list.
                </li>
                <li>
                  If the uploaded vendor name resembles a known one
                  (Levenshtein-2 or substring match — e.g. typing{" "}
                  <em>&quot;Forinet&quot;</em> against bundled{" "}
                  <em>&quot;Fortinet&quot;</em>), the dialog suggests{" "}
                  <Term>Group under Fortinet</Term> or{" "}
                  <Term>Create new vendor</Term>. Pick one. The
                  dialog re-previews to bind a fresh accept-token to
                  the rewritten bytes.
                </li>
                <li>
                  Hit <Term>Upload</Term> to commit. The YAML lands
                  at <Code>/app/data/user_data_sources/&lt;id&gt;/data_source.yaml</Code>
                  {" "}and persists across container restart.
                </li>
                <li>
                  The new card appears in the Browse view tagged{" "}
                  <Term>User upload</Term>.
                </li>
              </ol>
              <p className="text-sm">
                <strong>Why two-phase upload?</strong> The preview
                round-trip catches typos in the vendor name before
                committing — so you don&apos;t end up with{" "}
                <em>Forinet</em> and <em>Fortinet</em> as two separate
                vendor cards on the page.
              </p>
              <p className="text-sm">
                <strong>Bundle-vs-user precedence</strong>: bundle
                YAMLs always win on id collision. Operators
                can&apos;t override bundled packs; their custom
                sources must use new ids.
              </p>
              <p className="text-sm">
                <strong>Removing a user upload</strong>:{" "}
                <Code>DELETE /api/v1/data-sources/user/&lt;id&gt;</Code>.
                Cascades through the install store, so deleting the
                YAML also uninstalls any installed datasets it
                contributed. (Bundled packs cannot be deleted —
                they&apos;re part of the image; uninstalling marks
                them as not-installed in the store but the YAML
                stays.)
              </p>
              <p className="text-sm">
                <strong>Editing</strong> — any user-uploaded data
                source has an <Term>Edit</Term> affordance in three
                places: an inline button on the <Term>Browse</Term>{" "}
                tab&apos;s expanded vendor row, a pencil icon on the{" "}
                <Term>Installed</Term> tab card, and a pill button in
                the Detail Drawer footer. The Edit dialog opens
                pre-filled with the current YAML. The same{" "}
                <Term>preview → vendor-choice → save</Term> flow as
                upload applies; you must re-preview after any edit to
                bind a fresh accept-token. The <Code>id</Code> field
                is locked — to rename, delete + re-upload with the
                new id. This flow edits your <em>own</em> uploaded
                YAML. To edit a bundled (system) data source, use the{" "}
                <Term>Edit guidance</Term> flow described next — system
                sources are editable too.
              </p>
            </SubSection>

            <SubSection icon="edit_note" title="Edit a system data source's guidance">
              <p>
                You can edit a <strong>system (bundled)</strong>{" "}
                data source&apos;s &ldquo;How to simulate&rdquo;
                guidance directly from the card — useful for tailoring
                the simulation notes to your environment (e.g. your own
                broker address, your routing conventions, vendor quirks
                you&apos;ve discovered).
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  Open any system data source&apos;s detail drawer and
                  click <Term>Edit guidance</Term> in the footer (it
                  sits where user uploads show <Term>Edit</Term>). It
                  appears for system sources in both the Browse-preview
                  and Installed states.
                </li>
                <li>
                  The editor pre-fills the current{" "}
                  <Code>how_to_use</Code> markdown. Make your changes,
                  optionally add a <Term>change note</Term>, and click{" "}
                  <Term>Save new version</Term>.
                </li>
                <li>
                  A banner reminds you this creates an{" "}
                  <em>operator override</em>: the original is preserved
                  as <strong>version 1</strong> and the shipped file is
                  never modified, so you can roll back later from the
                  History panel. There is{" "}
                  <strong>no delete</strong> — editing is always
                  additive.
                </li>
              </ul>
              <p className="text-sm text-on-surface-variant">
                Behind the scenes, every save is a versioned snapshot
                served as an overlay on top of the bundled file. The
                edited guidance shows immediately in the drawer and
                feeds the chat agent when it simulates that vendor. The
                chat agent can make the same edits on your behalf
                (&ldquo;update the ServiceNow how-to-use to mention our
                broker&rdquo;). Editing the field <em>schema</em> from
                the UI is not available; to change a schema, Export
                the YAML, edit it, and re-upload.
              </p>
              <p className="text-sm">
                <strong>Version history + rollback.</strong>{" "}
                Next to <Term>Edit guidance</Term>, a <Term>History</Term>{" "}
                button opens the version panel: every saved version with
                its author, change note, and timestamp (the newest tagged{" "}
                <em>Current</em>). <Term>View</Term> shows any version&apos;s
                full snapshot read-only; <Term>Roll back</Term> on an older
                version restores it. Rollback is{" "}
                <strong>non-destructive</strong> — it brings the chosen
                version&apos;s content back as a new current version while
                keeping every version in history, so you can always roll
                forward again. The agent can do this too (&ldquo;show me the
                ServiceNow version history&rdquo;, &ldquo;roll ServiceNow back
                to version 1&rdquo;).
              </p>
              <p className="text-sm">
                <strong>Export any version.</strong> Each row in
                the History panel has an <Term>Export</Term> button that
                downloads that version&apos;s YAML (filename{" "}
                <Code>{`<dataset>.v<n>.yaml`}</Code>). The card&apos;s main{" "}
                <Term>Export</Term> button still downloads the{" "}
                <em>current</em> version — which, after an edit, is now the
                edited content (matching the drawer) rather than the original
                shipped file.
              </p>
            </SubSection>

            <SubSection icon="palette" title="Vendor logos + visual conventions">
              <p>
                Every bundled vendor carries an inline logo embedded
                in its <Code>data_source.yaml</Code>. Logo provenance
                is recorded per-vendor in the YAML&apos;s{" "}
                <Code>logo:</Code> block under{" "}
                <Code>source:</Code> / <Code>license:</Code> /{" "}
                <Code>fidelity:</Code>:
              </p>
              <ul className="list-disc pl-5 space-y-1 text-sm">
                <li>
                  <Code>branded</Code> — vendor&apos;s actual artwork,
                  unmodified (e.g. Apache, Cisco, Microsoft via
                  simple-icons; Arista, Avaya, Brocade via Wikipedia)
                </li>
                <li>
                  <Code>branded-recolored</Code> — vendor&apos;s actual
                  SVG with fills swapped for visibility on the{" "}
                  <Code>#F7F8FA</Code> near-white card panel (e.g.
                  Tanium, Thinkst, SecureAuth)
                </li>
                <li>
                  <Code>monochrome-brand</Code> — simple-icons-style
                  single-color mark
                </li>
                <li>
                  <Code>approximation</Code> — hand-crafted by the
                  maintainer (Semperis is the only one today)
                </li>
              </ul>
              <p className="text-sm">
                The Installed page uses the vendor-level logo, not
                per-pack logos. F5ASM, F5LTM, F5APM, F5BigIPAWAF all
                render the F5 mark — consistency across the same
                vendor.
              </p>
              <p className="text-sm">
                A standalone library of all 137 vendor SVGs lives at{" "}
                <Code>docs/assets/vendor-logos/</Code> in the repo —
                maintainer asset library for docs / brand-mark reuse.
                Phantom&apos;s runtime never reads it (serves from
                the YAML inline blocks).
              </p>
            </SubSection>
            <SubSection icon="http" title="HTTP data sources">
              <p>
                Most data sources are sent to Cortex over syslog. A data source
                with an <strong>HTTP</strong> pill on its card is different:
                its events are sent as JSON to an HTTP Log Collector in your
                Cortex tenant. Okta, Proofpoint TAP and Google Drive each have
                an HTTP version beside the standard one. HTTP sources are meant
                for simulating HTTP delivery; they do not carry a validation mark.
              </p>
              <p>
                <strong>Which version to use.</strong> Cortex collects these
                three products with its own API collectors, and its Analytics
                detectors have only been seen to fire on data that arrives with
                the source&apos;s own identity, which the HTTP sender
                reproduces (the next section shows the strongest route).
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  To <strong>test Analytics alerts</strong>, use the HTTP version
                  with the http-sender connector. The standard (syslog) version of
                  the same event lands and maps the same way but is not expected
                  to raise Analytics alerts. This was measured for Okta; it has
                  not been checked separately for Proofpoint TAP or Google Drive.
                </li>
                <li>
                  To <strong>check parsing and modeling</strong>, use the standard
                  syslog version. Its guide opens with this same note.
                </li>
              </ul>
              <p>
                <strong>Before you ask the agent to simulate one:</strong>
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  Install the data source from Browse like any other, and make
                  sure the vendor&apos;s content pack is installed on your Cortex
                  tenant, otherwise events land but their fields are not filled in.
                </li>
                <li>
                  Create an HTTP Log Collector in Cortex for the vendor, then add
                  an <strong>http-sender</strong> instance in Connectors with that
                  collector&apos;s URL and key. The collector&apos;s vendor and
                  product decide which dataset the events go to, so set them to
                  match the data source. The key is entered in the instance form
                  only; the agent never sees it.
                </li>
              </ul>
              <p>
                Then ask in chat the way you would for any vendor, for example
                &ldquo;Send 20 Okta sign-in events over HTTP&rdquo; or
                &ldquo;Simulate Proofpoint TAP phishing events over HTTP&rdquo;.
                The agent uses the HTTP sender instead of a syslog destination,
                and tells you which collector it used. Events can take 5 to 7
                minutes to appear in Cortex after they are sent.
              </p>
              <p className="text-sm">
                If the collector&apos;s vendor and product do not match a dataset
                that Cortex parses, the events still arrive but only as raw data.
                For Google Drive the collector should use vendor{" "}
                <Code>google_workspace</Code> and product <Code>drive</Code>; that
                combination has not been confirmed to map yet.
              </p>
            </SubSection>

            <SubSection icon="http" title="Native feeds through Cribl (http-sender)">
              <p>
                The tenant&apos;s Cribl integration lets the HTTP sender
                deliver events the way Cortex treats a real vendor feed. Each
                event is tagged with the source&apos;s own identifier, so the
                rows get the vendor&apos;s native collector type and stories,
                and the built-in Analytics detectors can fire. This is how
                Phantom reproduces detections that never fire over syslog or
                the plain HTTP collector: the Okta Tor sign-in, AWS
                detections (public exposure, logging switched off, backup
                policy changes, new administrative identities), GCP detections
                (public sharing, a sensitive role granted to a group, anonymous
                Kubernetes access) and 5 Azure AD audit detections.
              </p>
              <p>
                <strong>Before you ask the agent:</strong>
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  In Cortex, create the Cribl collector (Settings, Data Sources)
                  and copy its URL and token. There is one per tenant.
                </li>
                <li>
                  In Connectors, open the <strong>http-sender</strong>{" "}
                  instance, put the URL in <Code>criblUrl</Code> and the token
                  in the <Code>criblToken</Code> secret field, and save. The
                  token is entered there only; the agent never sees it. The
                  destinations <Code>cribl_okta_sso</Code>,{" "}
                  <Code>cribl_aws_audit</Code>,{" "}
                  <Code>cribl_gcp_cloud_logging</Code> and{" "}
                  <Code>cribl_azure_ad_audit</Code> appear on their own.
                </li>
                <li>
                  Install the vendor&apos;s content pack on your Cortex tenant,
                  otherwise the events land but their fields stay empty (AWS
                  CloudTrail, Google Cloud Logging, Microsoft Entra ID).
                </li>
              </ul>
              <p>
                Then ask in chat, for example &ldquo;Trigger the Okta sign-in
                from Tor alert&rdquo; or &ldquo;Make AWS CloudTrail show a
                GuardDuty detector being deleted&rdquo;. The agent follows the
                matching trigger skill. Alerts appeared a few seconds to about 7
                minutes after sending (most under 20 seconds). Every run uses brand-new identities, so
                each looks like a first-time actor.
              </p>
              <p>
                <strong>Windows without a Broker.</strong> The same Cribl
                destination also carries Windows events: the agent sends the
                same events it would send to the Windows Event Collector, and
                the nine Windows identity detections (machine account added to
                Domain Admins, DCSync, Guest account enabled and the others)
                fire the same way, with no Broker VM, certificate or
                subscription. Each Windows skill describes both routes.
              </p>
            </SubSection>

            <SubSection icon="http" title="Windows events over WEC (wec-sender)">
              <p>
                Windows telemetry can also be sent the way a real Windows
                server forwards its event log: to the Windows Event Collector
                on your Cortex Broker VM. Events sent this way arrive with
                collector type <Code>WEC</Code>, fill the Windows columns from
                the event&apos;s own text, and create the host and sign-in
                records that a syslog or CEF source cannot. It is a deliberate,
                narrow exception to Phantom&apos;s syslog and CEF delivery. It
                is for Windows simulation only and never validates or promotes
                a data source&apos;s mapping.
              </p>
              <p>
                <strong>What must exist first:</strong>
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  The Windows Event Collector is activated on the Broker VM, and
                  the Broker has a host name (FQDN) that the engine can resolve.
                </li>
                <li>
                  A firewall rule allows TCP 5986 from the engine to the
                  Broker VM.
                </li>
                <li>
                  The client certificate bundle (a PFX file) that the Cortex
                  console issues for the collector, and its password. Add a{" "}
                  <strong>wec-sender</strong> instance in Connectors and enter
                  the PFX (as base64 text) and its password as the
                  instance&apos;s secrets. The agent never sees them.
                </li>
                <li>
                  The Subscription Manager value from the Cortex console, pasted
                  as issued into the instance&apos;s{" "}
                  <Code>subscriptionManagerUrl</Code> field.
                </li>
              </ul>
              <p>
                <strong>The four tools.</strong> Ask the agent in plain words:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Code>list_subscriptions</Code> asks the collector which
                  subscriptions it offers. It doubles as the connection test:
                  if it works, the certificate, the address and the port are
                  right.
                </li>
                <li>
                  <Code>send_test_event</Code> sends one clearly synthetic
                  Windows sign-in and returns a query you can run to find it.
                </li>
                <li>
                  <Code>generate_events</Code> sends a built-in scenario. Today
                  that is a baseline of ordinary logons for a small made-up
                  domain: the same users always sign in from the same
                  workstations, so running it daily builds a history.
                  It can be back-dated and has a preview mode.
                </li>
                <li>
                  <Code>send_events</Code> sends Windows events you describe
                  yourself, such as a failed logon or an AD FS event.
                </li>
              </ul>
              <p>
                <strong>How to check that it worked.</strong> The{" "}
                <Code>sent</Code> number in a result only counts events the
                collector accepted. It does not prove they arrived. To prove it,
                run the query the tool returns (it looks for{" "}
                <Code>_collector_type = &quot;WEC&quot;</Code> and the host name
                in <Code>microsoft_windows_raw</Code>) and expect the row
                within about ten seconds.
              </p>
            </SubSection>

            <SubSection icon="terminal" title="Vendors sent as their own log line (RAW)">
              <p>
                Most data sources are delivered to Cortex as CEF, where each
                field arrives as its own labelled column. Some vendors are
                different: Cortex reads their logs by parsing the original log
                line as text. For those, sending labelled columns delivers
                nothing useful — the text Cortex wants to read is empty.
              </p>
              <p>
                Phantom sends those vendors their own way, shipping the log line
                exactly as the vendor writes it. You don&apos;t have to work out
                which vendors these are: open a data source and its{" "}
                <strong>How to use</strong> section says which format to ask for.
                When you tell the chat agent to generate logs for one, it picks
                the right format from that guidance.
              </p>
              <p>
                <strong>One setup step on the Cortex side.</strong> A log line
                sent this way carries no vendor label, so the Broker cannot tell
                who sent it and files everything under an{" "}
                <Code>unknown</Code> dataset. To route it, add a syslog
                collector entry on the Broker for the port Phantom sends to, and
                set its vendor and product to the two values the data
                source&apos;s <strong>How to use</strong> section names. Use
                those values exactly as written — they are often shorter and
                lower-case than the vendor and product names shown at the top of
                the page, and only the ones in <strong>How to use</strong> route
                correctly.
              </p>
              <p>
                Until that entry exists these sources still generate and deliver
                logs, but the events collect under the <Code>unknown</Code>{" "}
                dataset instead of the vendor&apos;s own, and none of the
                vendor&apos;s fields will be filled in.
              </p>
            </SubSection>
          </Section>

          {/* Log destinations page operator workflow. */}
          <Section id="log-destinations-ux" icon="cloud_upload" title="Log Destinations">
            <p>
              <strong>The <Code>/log-destinations</Code> page is where you configure
              where Phantom forwards synthesized security records.</strong> Each
              destination has a name, a type (syslog / HTTP webhook / XSIAM HTTP
              Collector / Splunk HEC), and a type-specific config. Workers reference
              destinations by a stable handle; the agent can list them — and create
              secretless syslog ones — but cannot edit credentialed destinations or
              read their secrets (credential boundary).
            </p>

            <SubSection icon="add_circle" title="Adding a destination">
              <ol className="list-decimal pl-6 space-y-2 text-sm">
                <li>Open the sidebar → Integration → <Code>Log Destinations</Code>.</li>
                <li>Click <Code>[+ New Destination]</Code>.</li>
                <li>Pick a type. The form re-renders with the type&apos;s fields.</li>
                <li>Fill in identity (name + optional description) + config.
                  Secret fields show a masked input with an eye toggle.</li>
                <li>For Webhook destinations: pick <Code>auth_type</Code> first.
                  The cred fields appear conditionally (bearer → token; basic
                  → username+password; api_key_header → header_name + value).</li>
                <li>For Syslog with TLS: set <Code>protocol=tls</Code> → the
                  PEM cert fields appear. Drop your CA + client cert + client key
                  in their respective textareas. The key is treated as a secret
                  (masked + stored encrypted).</li>
                <li>Save. The row appears in the list.</li>
              </ol>
            </SubSection>

            <SubSection icon="play_circle" title="Testing a destination">
              <p>
                Click the <Code>Test</Code> button on any row. Phantom sends a
                real test message to the destination (probe handler) and shows
                the result inline as a green/red badge for ~6s. The row&apos;s
                status dot updates: green = last probe OK, red = last probe
                failed (hover for the error), grey = never probed.
              </p>
              <p className="text-sm text-on-surface-variant">
                Test fires from the MCP server — the message reaches the
                destination from inside the phantom-agent container, not from
                the operator&apos;s browser.
              </p>
            </SubSection>

            <SubSection icon="push_pin" title="Setting a default for a type">
              <p>
                Each row has a pin (📌) icon. Clicking it marks that destination
                as the default for its type and clears the &quot;default&quot;
                flag on any sibling of the same type. The agent uses the default
                when the operator references a type without naming a specific
                destination.
              </p>
            </SubSection>

            <SubSection icon="terminal" title="Asking the agent to send logs to a destination">
              <p>
                The agent reads destinations (<Code>log_destinations_list</Code>{" "}
                + <Code>log_destinations_get</Code>) and can create{" "}
                <strong>secretless syslog</strong> ones, but never edits,
                deletes, or reads the secrets of credentialed destinations —
                credential boundary. When you ask it to generate logs, it
                resolves <em>where</em> they go from your configured
                destinations — it never invents a hardcoded address:
              </p>
              <ol className="list-decimal pl-6 space-y-1 text-sm">
                <li>Works out the transport from your request (&quot;over
                  syslog&quot;, &quot;to my XSIAM webhook&quot;) — or infers it
                  from the data source&apos;s &ldquo;How to simulate&rdquo; notes.</li>
                <li>Lists your destinations and picks by match:{" "}
                  <strong>exactly one</strong> of that transport → uses it
                  without asking; <strong>several</strong> → asks which (unless
                  you named one by name or IP); <strong>none</strong> → offers to
                  create a syslog destination for you, or — for a credentialed
                  type — points you to this page to add it.</li>
                <li>Starts the worker with an opaque{" "}
                  <Code>logdest:&lt;id&gt;</Code> handle. Phantom fills in the
                  real address — and, for an XSIAM HTTP destination, the endpoint
                  + auth key — behind the scenes, so the agent never handles your
                  credentials.</li>
              </ol>
              <p className="text-sm text-on-surface-variant">
                So &quot;send 50 FortiGate logs to syslog&quot; just works when
                you have one syslog destination; with two, the agent asks which
                one. Webhook + Splunk HEC destinations are configurable +
                testable here, but a worker does not send to them — use
                syslog or XSIAM HTTP for the worker flow.
              </p>
            </SubSection>

            <SubSection icon="dns" title="Sending assets, not just logs (XSIAM Asset Inventory)">
              <p>
                Everything else on this page sends <em>logs</em>. Cortex keeps
                its <strong>asset inventory</strong> — the list of machines,
                identities and cloud resources it knows about — in a completely
                separate place, and logs never add anything to it. You can send
                a million events about a server and Cortex still will not list
                that server as an asset.
              </p>
              <p>
                The <strong>XSIAM Asset Inventory</strong> destination is the
                first piece of closing that gap. It knows how to create asset
                records in your tenant, each optionally carrying
                vulnerabilities. Set it up here and use Test to confirm it
                reaches your tenant and your key has the right permission.
              </p>
              <p>
                Once the destination is saved, ask the agent for assets in
                plain language — <em>&quot;create 40 hosts on 10.20.30.0/24 with
                vulnerabilities&quot;</em>. It builds a realistic fleet
                (Windows servers, Linux web and database hosts, each with a
                hostname, address and a few genuine CVEs) and creates them in
                your tenant in one call.
              </p>
              <p>
                <strong>Then tie the two together.</strong> The agent gets back
                the list of hostnames and addresses it just created, so ask it
                to generate logs for those same hosts. That is what makes the
                data hang together: an address in a firewall event resolves to a
                machine that really is in the inventory, carrying real findings.
                Assets nobody refers to leave you with an inventory nothing
                cites and alerts about machines that do not exist.
              </p>
              <p className="text-sm text-on-surface-variant">
                Ask for a dry run first if you want to see the fleet before
                anything is created — the agent can list the hosts it would
                make without writing to your tenant.
              </p>
              <p>
                Two things to know before you set it up:
              </p>
              <ul className="list-disc pl-6 space-y-1 text-sm">
                <li>
                  <strong>Use an API key with vulnerability-management
                  permission.</strong> Without it every send fails with
                  &quot;URL Forbidden&quot;. Use a <em>Standard</em> key, and
                  test the destination after saving it — the test tells you
                  whether the key works <em>without</em> creating any assets.
                </li>
                <li>
                  <strong>Send in batches.</strong> Cortex allows only ten of
                  these calls per hour, so Phantom sends one request per batch
                  rather than one per asset.
                </li>
              </ul>
              <p className="text-sm text-on-surface-variant">
                One honest limitation: Cortex decides how these assets are
                labelled, and it files every one of them as a generic device.
                Even if you describe an asset as an AWS EC2 instance, it will
                appear as a generic device from an unspecified provider. Assets
                that show up properly labelled as AWS, Azure or GCP resources
                can only come from connecting a real cloud account to Cortex.
              </p>
            </SubSection>

            <SubSection icon="autorenew" title="Seeding a default destination from WEBHOOK_ENDPOINT">
              <p>
                If <Code>WEBHOOK_ENDPOINT</Code> + <Code>WEBHOOK_KEY</Code> env
                vars are set in <Code>/opt/phantom/.env</Code>, an automatic{" "}
                <Code>XSIAM Default</Code> destination is created on first boot,
                marked as the default for the <Code>xsiam_http</Code> type.
                The env vars stay in place as a fallback for any code path
                that still reads them.
              </p>
            </SubSection>

            <SubSection icon="vpn_key" title="Credential boundary">
              <p>
                Log destinations sit on the credential side of the boundary —
                they carry secrets (bearer tokens, basic-auth passwords, API
                keys, Splunk HEC tokens, TLS private keys). The agent has no
                write tools; only the operator (you) can create or edit them
                through this page. Secrets are AES-GCM-encrypted at rest under{" "}
                <Code>PHANTOM_SECRET_KEK</Code>; GET responses always redact
                them as <Code>&quot;***&quot;</Code> sentinels.
              </p>
            </SubSection>

            <SubSection icon="dataset" title="Where do my records land in XSIAM?">
              <p>
                When you send records through a destination targeting XSIAM,
                the dataset they land in depends on the destination type:
              </p>

              <h4 className="text-sm font-bold text-on-surface mt-4 mb-2">
                XSIAM HTTP Collector destinations
              </h4>
              <p>
                Records ALWAYS land in <Code>phantom_logs_raw</Code>. This is
                XSIAM-side hardcoded for the &quot;phantom&quot; brand on the
                collector. Each batch arrives as one outer row with an{" "}
                <Code>events</Code> JSON-array column holding the original
                record list. A downstream modeling rule unflattens per-event
                if your XSIAM tenant has one configured.
              </p>
              <p className="text-sm">
                Verify with:{" "}
                <Code>
                  dataset = phantom_logs_raw | sort desc _time | limit 10
                </Code>
              </p>

              <h4 className="text-sm font-bold text-on-surface mt-4 mb-2">
                Syslog → XSIAM broker (CEF format)
              </h4>
              <p>
                When you use{" "}
                <Code>
                  phantom_create_data_worker(type=&quot;CEF&quot;,
                  vendor=&quot;phantom&quot;,
                  product=&quot;smoke_test&quot;, destination=&quot;udp:
                  &lt;broker&gt;:514&quot;)
                </Code>
                , the broker parses the CEF header and routes records into a
                dataset named{" "}
                <Code>&lt;vendor&gt;_&lt;product&gt;_raw</Code> (both
                lowercased, non-alphanumeric chars → <Code>_</Code>). So{" "}
                <Code>vendor=phantom + product=smoke_test</Code> →{" "}
                <Code>phantom_smoke_test_raw</Code>. Each CEF extension
                (<Code>act</Code>, <Code>src</Code>, <Code>dst</Code>,{" "}
                <Code>spt</Code>, <Code>dpt</Code>, ...) becomes a typed
                column automatically — no modeling rule needed.
              </p>
              <p className="text-sm">
                Verify with:{" "}
                <Code>
                  dataset = phantom_smoke_test_raw | sort desc _time | limit
                  20
                </Code>
              </p>

              <h4 className="text-sm font-bold text-on-surface mt-4 mb-2">
                Vendor-faithful simulation
              </h4>
              <p>
                When you ask the agent to simulate logs for a specific vendor
                (e.g. &quot;stream 50 FortiGate traffic logs to my broker&quot;),
                the agent sets <Code>vendor=Fortinet + product=FortiGate</Code>{" "}
                so the records land in a vendor-tagged dataset (e.g.{" "}
                <Code>fortinet_fortigate_raw</Code>) the receiving platform
                can route to its FortiGate-specific parser. Combined with a{" "}
                <Link href="#data-sources-ux" className="link">data source schema override</Link>{" "}
                the simulated records carry real FortiGate field names
                (<Code>srcip</Code>, <Code>dstport</Code>, etc.) — any
                downstream FortiGate parser on the destination platform
                (vendor-specific modeling rule, Splunk technology
                add-on, Sentinel parser, Elastic ingest pipeline)
                ingests them cleanly.
              </p>

              <h4 className="text-sm font-bold text-on-surface mt-4 mb-2">
                Non-XSIAM syslog targets
              </h4>
              <p>
                For rsyslog / syslog-ng / on-prem SIEMs (anything that isn&apos;t
                an XSIAM broker), records land wherever your collector routes
                them. There&apos;s no convention to predict — check your
                collector&apos;s input rule mapping.
              </p>
            </SubSection>
          </Section>

          {/* Plugins page operator workflow. */}
          <Section id="plugins-ux" icon="extension" title="Plugins">
            <p>
              Plugins are vendor-shipped or operator-authored bundles
              that contribute extra tools, skills, hooks, or agent
              definitions to the runtime without touching the core
              Phantom image. View installed plugins at{" "}
              <Link href="/plugins" className="link">/plugins</Link>.
            </p>

            <SubSection icon="inventory_2" title="What a plugin can contribute">
              <p>
                Each plugin&apos;s manifest declares any of:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>tools</Term> — additional MCP tools surfaced
                  through a plugin-namespaced prefix
                  (<Code>plugin:&lt;name&gt;:&lt;tool&gt;</Code>).
                </li>
                <li>
                  <Term>skills</Term> — markdown skills loaded into the
                  catalog and toggleable from{" "}
                  <Link href="/skills" className="link">/skills</Link>{" "}
                  like any other.
                </li>
                <li>
                  <Term>hooks</Term> — pre-installed hook definitions
                  (see <a href="#hooks-ux" className="link">Hooks</a>).
                  Operator can disable individually.
                </li>
                <li>
                  <Term>agents</Term> — agent definitions that show up
                  on <a href="#agents-ux" className="link">/agents</a>{" "}
                  with the <Term>plugin</Term> origin badge.
                </li>
              </ul>
            </SubSection>

            <SubSection icon="install_desktop" title="Install + reload">
              <p>
                The <Term>Install</Term> button takes a plugin URL or
                manifest YAML upload. The plugin is staged into{" "}
                <Code>/app/runtime/plugins/&lt;name&gt;/</Code> and the
                runtime reloads contributions automatically. Reload also
                fires manually via the <Term>Reload</Term> button at the
                top of the page — useful when you&apos;ve edited a plugin
                in place during development.
              </p>
              <p>
                Reloads write a <Code>plugins_reloaded</Code> audit row
                with the contribution counts (tools / skills / hooks /
                agents added or removed). Find them at{" "}
                <Link
                  href="/observability/events?action=plugins_reloaded"
                  className="link"
                >
                  /observability/events?action=plugins_reloaded
                </Link>
                .
              </p>
            </SubSection>

            <SubSection icon="conflict" title="Overwrite policy">
              <p>
                If two sources declare the same agent definition name
                (e.g., a plugin and an operator-authored agent), the{" "}
                <Term>operator</Term> source wins — operator-owned
                customizations are never silently overwritten by a
                plugin reload. Plugin-vs-plugin conflicts surface as a
                warning toast on the plugins page; you pick which source
                to keep.
              </p>
            </SubSection>

            <Callout tone="warn">
              Plugins run inside the same MCP container as the rest of
              Phantom — they can call any internal API the MCP can
              reach. Treat plugin installation with the same care as
              installing a vendor library: review the manifest, scope
              the tools you allow, and check audit rows after the first
              run to confirm only expected calls happened.
            </Callout>

            <SubSection
              icon="inventory_2"
              title="Distributable plugins"
            >
              <p>
                The <Code>/plugins</Code> page above covers the older
                filesystem-discovered plugin system. A parallel surface
                lives at{" "}
                <Link
                  href="/observability/plugins"
                  className="link"
                >
                  /observability/plugins
                </Link>{" "}
                for <strong>pip-installable</strong> plugins that target
                one of five reserved entry-point groups
                (<Code>phantom.skills</Code>,{" "}
                <Code>phantom.connectors</Code>,{" "}
                <Code>phantom.hooks</Code>,{" "}
                <Code>phantom.scanners</Code>,{" "}
                <Code>phantom.providers</Code>).
              </p>
              <p>
                The page hosts:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  An <Term>install form</Term> at the top — paste a pypi
                  name, a <Code>git+https://...</Code> URL, or a local
                  path; click Install. The server runs{" "}
                  <Code>pip install --user --quiet &lt;spec&gt;</Code>{" "}
                  in the agent container and refreshes the catalog
                  below.
                </li>
                <li>
                  Per-row <Term>Uninstall buttons</Term> on each
                  discovered plugin. Click → confirm → server runs{" "}
                  <Code>pip uninstall -y &lt;dist&gt;</Code> and
                  refreshes.
                </li>
              </ul>
              <p>
                Both actions audit via the standard event log; filter at{" "}
                <Link
                  href="/observability/events?action=plugin_install"
                  className="link"
                >
                  /observability/events?action=plugin_install
                </Link>{" "}
                or{" "}
                <Link
                  href="/observability/events?action=plugin_uninstall"
                  className="link"
                >
                  ?action=plugin_uninstall
                </Link>
                .
              </p>
              <Callout tone="info">
                Plugin handlers in the <Code>phantom.hooks</Code> group
                are <strong>callable</strong> from{" "}
                <Link href="/settings/hooks" className="link">
                  /settings/hooks
                </Link>{" "}
                via the <Term>plugin</Term> transport (Add hook →
                pick the plugin handler from the dropdown → fill the
                JSON config). Install/uninstall clears the plugin-hook
                cache, so a newly installed handler is picked up on the
                next hook invocation; upgrading a handler package that
                is already loaded needs a phantom-agent restart, and so
                do the other contribution types (skills, connectors,
                providers, scanners) before they wire into their
                respective registries.
              </Callout>
            </SubSection>
          </Section>

          {/* Hooks management UX. */}
          <Section id="hooks-ux" icon="webhook" title="Hooks">
            <p>
              Hooks let you attach policy actions to runtime events — get
              a Slack notification when a Tier-3 tool runs, block a
              specific tool from firing in production, mirror tool
              outputs to an external SIEM. Manage them at{" "}
              <Link href="/settings/hooks" className="link">
                /settings/hooks
              </Link>
              .
            </p>

            <SubSection icon="bolt" title="The event taxonomy">
              <p>
                Every hook subscribes to one of these event names; the
                fire-site is fixed in the chat lifecycle so you know
                exactly when a handler runs:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Code>PreToolUse</Code> — before any tool call.
                  Handler can <em>deny</em> the call, transforming the
                  agent&apos;s next turn into an error message instead.
                </li>
                <li>
                  <Code>PostToolUse</Code> — after a tool call returns
                  (success or failure). Read-only side effects only.
                </li>
                <li>
                  <Code>UserPromptSubmit</Code> — when the operator
                  sends a chat message. Handler can rewrite or annotate
                  the prompt.
                </li>
                <li>
                  <Code>Notification</Code> — when the agent emits a
                  notification event (approval requested, scenario
                  complete). Common hook target for Slack mirrors.
                </li>
                <li>
                  <Code>Stop</Code> / <Code>SubagentStop</Code> — at the
                  end of a chat turn / subagent completion. Useful for
                  end-of-run summaries.
                </li>
              </ul>
            </SubSection>

            <SubSection icon="add_circle" title="Installing a hook">
              <p>
                Click <Term>New hook</Term> on{" "}
                <Link href="/settings/hooks" className="link">
                  /settings/hooks
                </Link>
                . The form asks for:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>Name</Term> — human label shown in audit rows
                  and the hooks list.
                </li>
                <li>
                  <Term>Event</Term> — which fire-site to attach to (one
                  of the seven above).
                </li>
                <li>
                  <Term>Matcher</Term> — optional filter to scope when
                  the handler runs. Tool patterns
                  (<Code>caldera.*</Code>), session tags
                  (<Code>session.tag:prod</Code>), or actor filters
                  (<Code>actor:user:*</Code>).
                </li>
                <li>
                  <Term>Transport</Term> — how the handler runs. Four
                  options:
                  <ul className="list-disc pl-5 mt-1 space-y-1">
                    <li>
                      <Term>Built-in</Term> — pick a named
                      handler that ships with the agent image (e.g.,
                      Slack approval). Form fields appear automatically
                      from the built-in&apos;s config schema. No
                      subprocess, no HTTP — runs in-process. Recommended
                      starter.
                    </li>
                    <li>
                      <Term>HTTP webhook</Term> — POST the event payload
                      to a URL you operate. Right when you have your own
                      policy service / SIEM mirror / Slack receiver.
                    </li>
                    <li>
                      <Term>Shell command</Term> — runtime spawns the
                      command with the event payload on stdin, parses
                      stdout as the handler outcome. Right when policy
                      lives in a local script.
                    </li>
                    <li>
                      <Term>Agent tool</Term> — reserved. Plugin
                      handlers (see below) cover the
                      vendor-distributed path; this discriminator is
                      kept on the form for forward compatibility.
                    </li>
                  </ul>
                </li>
              </ul>
              <p>
                On submit, the runtime writes the hook config and emits
                a <Code>hook_upsert</Code> audit row. The hook is
                immediately active — no restart needed.
              </p>
            </SubSection>

            <SubSection id="hooks-builtin" icon="extension" title="Built-in handlers">
              <p>
                Built-in handlers are policy primitives that ship with
                every Phantom deployment. Pick one from the dropdown,
                fill its config form, save. The agent calls the handler
                in-process on each matching event — no subprocess to
                manage, no HTTP service to operate.
              </p>
              <p>
                The current built-in catalogue:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>Slack approval</Term> — On{" "}
                  <Code>PreToolUse</Code>, POSTs the tool details to a
                  webhook receiver you operate. Your receiver pings
                  Slack with Approve/Deny buttons, waits for an analyst
                  click, returns the decision. Phantom blocks the tool
                  on <Code>deny</Code> and lets it through on{" "}
                  <Code>allow</Code>. Config: webhook URL + optional
                  auth header.
                </li>
              </ul>
              <p>
                The catalogue is enumerable at runtime via{" "}
                <Code>GET /api/agent/hooks/builtins</Code> — that
                endpoint reflects exactly what the current install
                offers. Additional built-ins (memory-injection, pre-
                compact warning, cost-warn-over-budget) ship in image
                updates and appear automatically in the form&apos;s
                dropdown.
              </p>
              <Callout tone="info">
                Built-ins run with the agent&apos;s privileges. They
                can read tool args and call the agent&apos;s services
                directly. Operators who need stricter isolation should
                continue using the <Code>http</Code> transport, which
                forces the handler into a separate process boundary.
              </Callout>
            </SubSection>

            <SubSection
              id="hooks-plugin"
              icon="inventory_2"
              title="Plugin handlers"
            >
              <p>
                A fifth transport — <Term>Plugin handler</Term> — wires
                in handlers contributed by pip-installable Python
                packages targeting the <Code>phantom.hooks</Code>{" "}
                entry-point group. Discovery + lifecycle for those
                packages happens at{" "}
                <Link
                  href="/observability/plugins"
                  className="link"
                >
                  /observability/plugins
                </Link>{" "}
                (see the Plugins section); the hook form picks them up
                automatically once the package is pip-installed and the
                agent restarts.
              </p>
              <p>
                In the Add-hook form, picking <Term>Plugin handler</Term>{" "}
                from the transport dropdown surfaces a fetched dropdown
                of currently-discovered handler names + a generic JSON
                config textarea + an optional per-hook timeout in
                seconds. Schema for the config is plugin-defined — TS
                can&apos;t introspect Python entry-points, so the form
                ships a JSON editor and the plugin author documents
                their own contract.
              </p>
              <p>
                Click <Term>Refresh</Term> in the section header to
                re-walk entry-points (useful when you just installed a
                plugin in a different tab and want it to appear without
                a full page reload). Each invocation audits as{" "}
                <Code>plugin_hook_invoked</Code> with handler name +
                outcome category at{" "}
                <Link
                  href="/observability/events?action=plugin_hook_invoked"
                  className="link"
                >
                  /observability/events?action=plugin_hook_invoked
                </Link>
                .
              </p>
              <Callout tone="warn">
                Plugin handlers run in the MCP process with full agent
                privileges — same trust boundary as installing a vendor
                library. Review the plugin source before{" "}
                <Code>pip install</Code>. Use the timeout field
                aggressively for handlers you don&apos;t fully trust:
                MCP caps invocation at 60s server-side, but a tighter
                bound prevents a misbehaving handler from sitting on a
                hook fire.
              </Callout>
            </SubSection>

            <SubSection icon="toggle_on" title="Lifecycle controls">
              <p>
                Each hook row has a toggle (enabled/disabled), an{" "}
                <Term>Edit</Term> button (re-opens the form with current
                values), and a <Term>Delete</Term> button. Disabled
                hooks stay in the list — useful to pause a noisy hook
                without losing its config. Edits write{" "}
                <Code>hook_enabled</Code> /{" "}
                <Code>hook_disabled</Code> /{" "}
                <Code>hook_deleted</Code> audit rows.
              </p>
            </SubSection>

            <SubSection icon="article" title="Audit + dispatch trail">
              <p>
                Every hook fire writes a <Code>hook_dispatched</Code>{" "}
                audit row with the hook name, event, matcher hit, and
                handler outcome (allowed / denied / errored). Filter on{" "}
                <Code>action:hook_dispatched</Code> in{" "}
                <Link href="/observability/events" className="link">
                  /observability/events
                </Link>{" "}
                to confirm a hook is firing and (for deny hooks) what
                got blocked.
              </p>
            </SubSection>

            <Callout tone="info">
              Hooks load <em>fresh</em> from disk on each fire, not from
              an in-memory cache — so editing a hook&apos;s handler
              command takes effect on the very next event, no reload
              needed. This is intentional for fast policy iteration; see{" "}
              <Link
                href="/help/architecture#design-decisions"
                className="link"
              >
                Architecture &rarr; Design Decisions
              </Link>{" "}
              for the trade-offs.
            </Callout>

            <SubSection icon="bug_report" title="Debugging hooks">
              <p>
                When a hook isn&apos;t doing what you expect, walk this
                short ladder:
              </p>
              <ol className="list-decimal pl-5 space-y-1.5 text-sm">
                <li>
                  Open{" "}
                  <Link href="/observability/events" className="link">
                    /observability/events
                  </Link>{" "}
                  and filter by <Code>action:hook_fire</Code>. Every
                  successful fire writes a row with the hook id, event
                  name, matched payload, and the returned decision. No
                  rows for your hook means the matcher didn&apos;t hit
                  (check toolGlob / triggerPrefix / tenantId) or the
                  event itself never fired.
                </li>
                <li>
                  Look for <Code>hook_denied</Code> (the hook actively
                  denied) and <Code>hook_error</Code> (the transport
                  raised). <Code>hook_error</Code> rows carry the
                  stderr / response body / exception trace in the{" "}
                  <Code>error</Code> metadata field — that&apos;s where
                  to start when a Slack webhook 404s, when a shell
                  script segfaults, or when a builtin throws.
                </li>
                <li>
                  Use the dry-run endpoint to fire a hook against a
                  synthetic payload:{" "}
                  <Code>POST /api/agent/hooks/&lt;id&gt;/test</Code>{" "}
                  with <Code>{`{ "payload": {...} }`}</Code> in the
                  body. The hook runs but no agent state changes; the
                  response carries the same <Code>HookResult</Code>{" "}
                  shape the real fire-site would see. Use this to
                  iterate on matchers + handlers without driving the
                  agent through a real tool call.
                </li>
                <li>
                  Toggle <Term>Enabled</Term> off on{" "}
                  <Link href="/settings/hooks" className="link">
                    /settings/hooks
                  </Link>{" "}
                  to remove a hook from the pipeline without deleting
                  its config. Useful when a hook is producing too many
                  denials and you want to confirm the agent path works
                  without it.
                </li>
                <li>
                  Check the <Term>Failure policy</Term> column. A hook
                  with <Code>block</Code> failure policy that hits an
                  error denies the tool — operators sometimes set this
                  too aggressively on observability hooks. Switch to{" "}
                  <Code>warn</Code> or <Code>allow</Code> for
                  best-effort notification handlers; reserve{" "}
                  <Code>block</Code> for true policy enforcers.
                </li>
              </ol>
            </SubSection>
          </Section>

          <Section id="approvals" icon="fact_check" title="Approvals">
            <p>
              A tool can be set to wait for your approval before it runs.
              Which tools wait is a list that ships with the product.{" "}
              <strong>In this release the list is empty, so no tool waits
              for approval</strong>: when the agent changes a job, a
              setting, its persona, a skill or a connector instance, the
              change takes effect as soon as it makes the call. The agent
              says what it changed, and every call is recorded in the{" "}
              <Link href="/observability/audit" className="link">audit log</Link>.
              The chat header shows <em>No approvals</em> and{" "}
              <Link href="/approvals" className="link">/approvals</Link>{" "}
              says nothing new will appear there.
            </p>
            <Callout tone="info">
              Want a pause before the agent changes something? In{" "}
              <Link href="#settings-personality" className="link">Settings → Personality</Link>{" "}
              set the confirmation for local actions to <Code>soft</Code>:
              the agent then says what it is about to do and waits for your
              yes in chat.
            </Callout>
            <p>
              Connector calls (caldera operations, xsiam log pushes, log
              generation) never use this list — those are explicit operator
              intent at chat level. When a call does wait, it lands in{" "}
              <Link href="/approvals" className="link">/approvals</Link> with
              the agent name, tool, args, and risk tier.
            </p>

            <SubSection icon="check_circle" title="Tools that wait when the list names them">
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>Self-modification</Term>: <Code>jobs_create</Code>,
                  <Code> jobs_update</Code>, <Code>jobs_run_now</Code>,
                  <Code> personality_update</Code>, <Code>personality_patch</Code>,
                  <Code> settings_update</Code>,
                  <Code> notifications_dismiss</Code>,{" "}
                  <Code>approvals_resolve</Code>.
                </li>
                <li>
                  <Term>Destructive</Term>: <Code>jobs_delete</Code>,
                  <Code> skills_delete</Code>, <Code>personality_reset</Code>,
                  <Code> settings_reset</Code>. Same gate; UI shows a red
                  banner.
                </li>
                <li>
                  <Term>Credentials</Term>: the agent has no tools for
                  provider credentials, connector secrets or API keys, so
                  they never reach an approval card, alone or inside a
                  batch. Manage them yourself on the Providers, Instances
                  and API keys pages.
                </li>
              </ul>
            </SubSection>

            <SubSection icon="block" title="What does NOT require approval">
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>Caldera</Term> — <Code>create_operation</Code>,{" "}
                  <Code>get_operation_event_logs</Code>, etc. Run inline.
                </li>
                <li>
                  <Term>XSIAM</Term> — <Code>send_webhook_log</Code>,
                  <Code> xql_*</Code>. Run inline.
                </li>
                <li>
                  <Term>XLog</Term> — log generation, scenario workers. Run
                  inline.
                </li>
                <li>
                  <Term>Reads</Term> — anything classified as a read query
                  (the agent&apos;s view of its own state, audit search, etc).
                </li>
              </ul>
              <p className="text-sm text-on-surface-variant mt-2">
                Per-instance opt-in to gating exists via the connector
                instance&apos;s <Code>trusted: false</Code> flag — see the{" "}
                <Link href="#connectors" className="link">Connectors</Link>{" "}
                section. By default new instances are untrusted-but-ungated
                (manifest-driven), letting operators tune per-deployment.
              </p>
            </SubSection>

            <SubSection icon="timer" title="Lifecycle">
              <p>
                Pending approvals time out server-side after 5 minutes —
                the chat unblocks with an error. Resolved approvals stay
                in the history tab indefinitely (subject to audit-log
                retention). The sidebar shows a count badge for pending
                approvals so you don&apos;t miss them while in another
                tab.
              </p>
              <Callout tone="info">
                Today, you click Approve on the <Code>/approvals</Code>{" "}
                page. If the timeout fires before you approve, re-issue
                the chat command — the agent will create a fresh request.
              </Callout>
            </SubSection>

            <SubSection icon="record_voice_over" title="Preamble + key args">
              <p>
                Before any approval card lands in the chat thread, you
                always see context for what&apos;s about to happen.
                Two layers cooperate to guarantee this:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>Model narration (preferred)</Term> — the system
                  prompt instructs the agent to write a short
                  &quot;here&apos;s what I&apos;m about to do and
                  why&quot; sentence before any gated tool call. When
                  the model complies, that text streams into the chat
                  thread first; the approval card lands below it.
                </li>
                <li>
                  <Term>Server-side preamble (fallback)</Term> — when
                  the model is silent (function call only, no
                  accompanying text), the chat-route synthesizes a
                  one-line{" "}
                  <Code>I&apos;ll call `tool_name` with key=value, …</Code>
                  {" "}preamble per pending tool call and streams it
                  before the approval card. Up to four args are surfaced
                  (preferring human-meaningful keys like name, cron, url,
                  query, instance_id); secret-looking keys (api_key,
                  password, token, …) are hidden.
                </li>
                <li>
                  <Term>Approval-card &quot;Will be called with&quot; panel</Term>
                  {" "}— the card itself shows the same key=value summary
                  above the Approve / Deny buttons. Defense-in-depth:
                  even if the preamble didn&apos;t render, the card is
                  never opaque. Click the small &quot;Raw arguments&quot;
                  expander to see the full args object including any
                  hidden-from-summary keys.
                </li>
              </ul>
              <p className="text-sm text-on-surface-variant">
                Net result: you should never see an approval card that
                says only &quot;Approve job creation?&quot; without
                context. If you do, file a bug.
              </p>
            </SubSection>
          </Section>

          <Section id="notifications" icon="notifications" title="Notifications">
            <p>
              <Link href="/notifications" className="link">/notifications</Link>{" "}
              is the platform alert feed. Job completions, failed
              scenarios, approval resolutions, configuration changes —
              anything that fires a system-level event lands here. The
              filter bar lets you scope by tab (all / unread / mentions
              / approvals) and search by free-text. Mark-read is
              optimistic and persists across sessions.
            </p>
            <p>
              Event sources currently wired:
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-sm">
              <li>
                <Term>Jobs</Term> — runs that complete, fail, or are
                disabled.
              </li>
              <li>
                <Term>Scenarios</Term> — long-running scenario workers
                that finish or error.
              </li>
              <li>
                <Term>Approvals</Term> — pending, granted, denied.
              </li>
              <li>
                <Term>System</Term> — settings changes, secret rotations,
                MCP_TOKEN refresh.
              </li>
            </ul>
          </Section>

          <Section id="profile" icon="person" title="Your Profile">
            <p>
              <Link href="/profile" className="link">/profile</Link> is the
              operator&apos;s account-settings page. Click the
              &quot;Operator&quot; tile at the bottom of the sidebar to
              get there. Two sections:
            </p>
            <SubSection icon="badge" title="Account">
              <p>
                Read-only display of your username and role. The
                username comes from <Code>UI_USER</Code> in the
                runtime config and isn&apos;t editable in the UI — to
                change it, update the env var in your{" "}
                <Code>.env</Code> and restart the phantom-agent
                container.
              </p>
            </SubSection>
            <SubSection icon="lock_reset" title="Change password">
              <p>
                Rotate your UI password from this page. The form
                requires your current password as a second factor:
                a stolen session cookie alone can&apos;t lock you
                out, because rotation also needs the password you
                already know.
              </p>
              <p>
                See{" "}
                <Link href="#authentication" className="link">
                  Authentication
                </Link>{" "}
                for the full flow — storage layout, hash algorithm,
                session-revocation behavior on success, security
                notification on the bell badge, and observability
                audit rows.
              </p>
            </SubSection>
          </Section>

          <Section id="api-keys" icon="vpn_key" title="API Keys">
            <p>
              <Link href="/api-keys" className="link">/api-keys</Link> mints
              and revokes operator-issued bearer tokens for programmatic
              access to the agent&apos;s <Code>/api/v1/*</Code> surface.
              Useful for SIEM pollers reading the audit log, CI scripts
              triggering scenario runs, cross-host integrations exposing
              automation hooks back at the agent. Keys take the shape{" "}
              <Code>phantom_ak_&lt;id&gt;_&lt;secret&gt;</Code>; the
              backend stores only <Code>sha256(&lt;secret&gt;)</Code> so
              the plaintext is shown <em>once</em> at create time and
              never recoverable after that.
            </p>
            <p>
              The page wires to the <Code>/api/v1/api_keys</Code>
              backend. The model uses <Term>advisory scopes</Term> —
              a flat list of capability strings the auth layer
              compares against the route&apos;s required scope:
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-sm">
              <li><Code>audit:read</Code> — GET <Code>/api/v1/audit*</Code></li>
              <li><Code>settings:read</Code> / <Code>settings:write</Code></li>
              <li><Code>approvals:resolve</Code></li>
              <li><Code>tools:call</Code> — JSON-RPC tool dispatch</li>
              <li><Code>*</Code> — superset / admin-equivalent</li>
            </ul>
            <p>
              Fresh installs read &quot;0 active, 0 revoked&quot;.
              Listing, minting, and revocation all require the
              bundle-internal <Code>MCP_TOKEN</Code> (proxied for you
              by the agent), so a key with one narrow scope can never
              mint a wider one.
            </p>
            <Callout tone="warn">
              Keys are shown <em>once</em>. Lose the value, rotate — the
              platform never stores plaintext. Treat keys with the same
              care as MCP_TOKEN; with the <Code>*</Code> scope they grant
              agent-equivalent access to the platform.
            </Callout>
          </Section>

          {/* ============================================================
                              OBSERVABILITY
              ============================================================ */}

          <Section
            id="obs-pipeline"
            icon="account_tree"
            title="Pipeline Health"
          >
            <p>
              <Link href="/observability/pipeline" className="link">
                /observability/pipeline
              </Link>{" "}
              is a live React Flow graph of every Phantom subsystem: the
              browser, the agent, the MCP, the six storage subsystems
              (audit, memory, secrets, settings, sessions, jobs), and the
              three connectors. Box borders flip green/amber/red based on
              live health probes; edges pulse cyan when traffic flowed in
              the last 60 seconds.
            </p>
            <p>Status sources:</p>
            <ul className="list-disc pl-5 space-y-1.5 text-sm">
              <li>
                <Term>Probes</Term> — the agent&apos;s{" "}
                <Code>/api/agent/health</Code> endpoint hits each
                service&apos;s health URL server-side (xlog
                <Code>/health</Code>, MCP <Code>/ping/</Code>, agent
                self-check, caldera root) and returns HTTP code +
                latency. Refresh interval: 5s.
              </li>
              <li>
                <Term>Storage rollup</Term> — the six SQLite stores live
                inside the MCP process, so they inherit MCP&apos;s
                status. If MCP is up, the stores are reachable; if
                MCP&apos;s probe fails, the stores can&apos;t be probed
                independently.
              </li>
              <li>
                <Term>Edge pulses</Term> — the audit log feed gives
                action-by-action history. Edges pulse if matching events
                appeared in the last 60s (e.g., a tool_call to{" "}
                <Code>tool:caldera.*</Code> pulses the mcp→caldera edge).
              </li>
            </ul>
            <p>
              Below the graph: a <Term>Component Status</Term> table with
              HTTP code + latency per probe (so you can see exact response
              times), and a <Term>Recent Traffic</Term> feed of the last
              audit events.
            </p>
          </Section>

          <Section
            id="obs-metrics"
            icon="monitoring"
            title="Metrics & Traces"
          >
            <p>
              <Link href="/observability/metrics" className="link">
                /observability/metrics
              </Link>{" "}
              renders the Prometheus text feed from the MCP — counter,
              gauge, and histogram series for tool calls, request
              latency, and store operations. No external Prometheus or
              Grafana required; the page parses and graphs the text
              directly. Common series:
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-sm">
              <li>
                <Code>tool_call_total{"{tool=\"...\"}"}</Code> — counter
                per tool, per status.
              </li>
              <li>
                <Code>tool_call_duration_seconds_bucket</Code> — histogram
                of tool latency.
              </li>
              <li>
                <Code>agent_chat_turn_duration_seconds</Code> — end-to-end
                chat-turn timing.
              </li>
              <li>
                <Code>store_op_total{"{store=\"...\",op=\"...\"}"}</Code> —
                read/write counts per store.
              </li>
            </ul>
            <p>
              <Link href="/observability/traces" className="link">
                /observability/traces
              </Link>{" "}
              shows OpenTelemetry spans for end-to-end requests. Each
              chat-turn spans the agent → MCP → tool → connector → LLM
              path; clicking a span tree lets you find latency spikes
              precisely. Spans are stored alongside the audit log and
              survive container restarts.
            </p>
          </Section>

          <Section id="obs-logs" icon="terminal" title="Logs & Events">
            <p>
              <Link href="/observability/logs" className="link">
                /observability/logs
              </Link>{" "}
              is the structured-event firehose with a Lucene-light query
              syntax. <Link href="/observability/events" className="link">
                /observability/events
              </Link>{" "}
              is the same data rendered for compliance / who-did-what use
              cases (one row per event with actor, action, target,
              timestamp, source IP).
            </p>

            <SubSection icon="search" title="Lucene-light cheat sheet">
              <p>
                The query bar accepts <Code>key:value</Code> pairs,{" "}
                <Code>key:prefix*</Code> wildcards, and free-text. Six
                supported keys:
              </p>
              <Pre>{`actor:user:operator         // who triggered the event
action:tool_call            // what the event was
target:tool:xsiam.*         // wildcard prefix match
severity:error              // error / warn / info / debug
session:s_4k21m             // chat session id
job:weekly-coverage         // job name`}</Pre>
              <p>Common composed queries:</p>
              <Pre>{`actor:user:operator action:tool_call target:tool:caldera.*
   // operator-triggered caldera tool calls

severity:error action:tool_call
   // failed tool calls (good first stop when chat broke)

job:weekly-* action:job_run_complete
   // run completions for any "weekly-*" job

session:s_4k21m
   // every event from one chat session — replay an interaction`}</Pre>
            </SubSection>

            <SubSection icon="speed" title="Live tail vs paginated">
              <p>
                The <Term>Logs</Term> page tails the same stream over SSE
                (server-sent events) — new events stream in at the top
                without a page refresh. The <Term>Events</Term> page is
                paginated (20 rows per page, jump-to-time) so it&apos;s
                better for incident review and audit reads.
              </p>
            </SubSection>
          </Section>

          {/* Cost rollup operator UX. */}
          <Section id="cost-ux" icon="payments" title="Cost Rollup">
            <p>
              Every chat turn writes a <Code>chat_turn_cost</Code> audit
              row with input tokens, output tokens, cached tokens, and a
              dollar estimate (model&apos;s public per-token rate × token
              counts).{" "}
              <Link href="/observability/cost" className="link">
                /observability/cost
              </Link>{" "}
              rolls those rows up into a dashboard, and{" "}
              <Code>/cost</Code> in any chat shows the just-finished
              turn&apos;s breakdown inline.
            </p>

            <SubSection icon="terminal" title="The /cost slash command">
              <p>
                Type <Code>/cost</Code> right after a turn to render an
                inline cost card: input / output / cached token counts,
                the model&apos;s rate, the resulting dollar estimate, and
                the cumulative session total. <Code>/cost session</Code>{" "}
                shows just the session total; <Code>/cost turn</Code>{" "}
                forces just the last turn.
              </p>
            </SubSection>

            <SubSection icon="dashboard" title="The cost page">
              <p>
                Three primary views, each pickable from the page header:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>Window picker</Term> — 1d / 7d / 30d / custom
                  date range. The chart updates immediately; subtotals
                  appear as cards above the chart.
                </li>
                <li>
                  <Term>By model</Term> — stacked bar showing per-model
                  spend in the chosen window. Useful for catching when a
                  switch to a more expensive model is ballooning costs.
                </li>
                <li>
                  <Term>By session</Term> — table of the top-N priciest
                  sessions, click-through to the session transcript so
                  you can see what was being asked.
                </li>
              </ul>
            </SubSection>

            <SubSection icon="discount" title="Cache savings">
              <p>
                When Vertex prompt caching is on, cached input tokens
                bill at ~25% of the standard rate.
                The page shows two figures side by side:{" "}
                <Term>actual spend</Term> (what you paid) and{" "}
                <Term>without-cache spend</Term> (what you would have
                paid if every cached token had billed at full rate). The
                delta is your cumulative cache ROI — typically 30-60%
                savings on long sessions with stable system prompts.
              </p>
            </SubSection>

            <Callout tone="warn">
              Dollar estimates use public per-token list pricing baked
              into <Code>lib/model-pricing.ts</Code>. They&apos;re a{" "}
              <em>useful approximation</em>, not a billing source of
              truth — your actual GCP invoice may differ due to
              negotiated discounts, free-tier credits, or rate-card
              updates that haven&apos;t propagated to the table.
            </Callout>
          </Section>

          <Section
            id="obs-activity"
            icon="history_toggle_off"
            title="Live Activity"
          >
            <p>
              <Link href="/activity" className="link">/activity</Link> is a
              streaming feed of recent platform events — same data backing
              the pipeline graph&apos;s edge pulses, but rendered as a
              chronological list with action / target / actor columns.
              Useful when you&apos;re debugging &quot;why is this not
              happening&quot; in real time and don&apos;t want to write
              the query yet.
            </p>
            <p>
              Filter capabilities mirror the Logs page (Lucene-light
              syntax) but the page auto-refreshes every 2 seconds and
              caps at the latest 200 events to keep memory bounded.
            </p>
          </Section>

          {/* ============================================================
                                 SETTINGS
              ============================================================ */}

          <Section id="settings-services" icon="tune" title="Services">
            <p>
              <Link href="/settings" className="link">/settings</Link> shows
              every internal service with config and runtime status —
              ports, health endpoints, language/runtime, mounted volumes,
              and environment-variable overrides. It&apos;s the canonical
              service inventory; the{" "}
              <Link href="/observability/pipeline" className="link">
                pipeline
              </Link>{" "}
              page is the visual rendition of the same underlying data.
            </p>
            <p>
              The page derives status from the same{" "}
              <Code>/api/agent/health</Code> probes as the pipeline graph
              — so if an entry shows degraded here, the matching node
              flips amber on the graph too. They&apos;re two views of one
              source.
            </p>
          </Section>

          <Section
            id="settings-personality"
            icon="psychology_alt"
            title="Personality"
          >
            <p>
              <Link href="/settings/personality" className="link">
                /settings/personality
              </Link>{" "}
              is where the agent&apos;s voice and behavior live.
              Click <Term>Operator</Term> at the bottom of the
              sidebar, then <Term>Personality</Term> in the settings
              tab strip. The page is split into two panels:{" "}
              <Term>Persona</Term> (free-form system-prompt content)
              and <Term>Tuning</Term> (typed behavior knobs).
            </p>

            <SubSection icon="shield" title="Action policy — when the agent asks first">
              <p>
                The <Term>Action Policy</Term> decides whether the agent
                asks before it acts. Tools are sorted into{" "}
                <Term>local</Term> categories (the agent&apos;s own jobs,
                settings, memory, skills) and <Term>external</Term>{" "}
                categories (the SOC environment: log workers, Caldera,
                XSIAM, and the <Code>http-sender</Code> and{" "}
                <Code>wec-sender</Code> connectors). Each side has a
                cadence:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>Approval card</Term> — an inline card; the tool
                  waits until you click Approve.
                </li>
                <li>
                  <Term>Soft confirm</Term> — a clear, explicit instruction to simulate,
                  send or trigger something small (one scenario, up to a
                  few hundred events, a few minutes) is its own
                  confirmation: the agent does it and tells you exactly
                  what it sent. It asks &ldquo;About to call … — fire
                  it?&rdquo; and waits for a yes only when the request is
                  ambiguous, large or long-running, runs on real
                  endpoints (Caldera), or cannot be undone.
                </li>
                <li>
                  <Term>Off</Term> (the default for external actions on a
                  new install) — the agent never asks
                  (tool-level approval gates still apply). That includes
                  Caldera operations, which run on real endpoints: choose{" "}
                  <Term>Soft confirm</Term> for them if you want a pause.
                </li>
              </ul>
              <p className="text-sm">
                An install that is already running keeps the setting it has;
                an upgrade does not change it. Set it in{" "}
                <Link href="#settings-personality" className="link">Settings → Personality</Link>.
                <Code>Reset Defaults</Code> there returns local actions to
                the approval card and external actions to off.
              </p>
            </SubSection>

            <SubSection icon="record_voice_over" title="Persona panel — who the agent is">
              <p>
                Three free-form fields shape every system prompt the
                agent ever sends:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>Name</Term> — what the agent calls itself
                  when it introduces. Examples:{" "}
                  <em>&ldquo;SOC analyst assistant&rdquo;</em>,{" "}
                  <em>&ldquo;Red-team operator&rdquo;</em>,{" "}
                  <em>&ldquo;Detection engineer&rdquo;</em>. Appears
                  in the chat header chip.
                </li>
                <li>
                  <Term>Tone</Term> — voice instructions:{" "}
                  <em>concise, factual</em> vs{" "}
                  <em>verbose, narrative</em> vs{" "}
                  <em>tactical, command-only</em>. Threaded into
                  the system-prompt persona block.
                </li>
                <li>
                  <Term>Instructions</Term> — system-prompt-style
                  guidance the operator wants the agent to follow
                  every turn. Things like{" "}
                  <em>&ldquo;Always cite the XQL dataset name when
                  reporting query results&rdquo;</em> or{" "}
                  <em>&ldquo;Before destructive operations, name the
                  target system in plain English&rdquo;</em>.
                </li>
              </ul>
              <p className="text-sm">
                Persona content prepends a <Code>## PERSONA</Code>{" "}
                block to the system prompt for every chat turn. The
                TAIL of the system prompt (skills inventory + tool
                catalog) stays cacheable for Vertex prompt caching;
                only the small persona block varies. So you can iterate
                on the persona without exploding cache costs.
              </p>
            </SubSection>

            <SubSection icon="tune" title="Tuning panel — behavior knobs">
              <p>
                Four sliders / toggles that modulate chat-route and
                memory-store behavior without redeploying:
              </p>
              <ul className="list-disc pl-5 space-y-2 text-sm">
                <li>
                  <Term>Vertex prompt caching</Term> — when ON,
                  Phantom uses Vertex&apos;s{" "}
                  <Code>cachedContents</Code> API to cache the
                  system-prompt TAIL across turns. Saves 30-60% on
                  input tokens after the first turn. Default ON if
                  the <Code>PHANTOM_VERTEX_CACHE=1</Code> env var is
                  set at boot; OFF otherwise. Toggle here to turn it
                  off per-workspace without redeploying.
                </li>
                <li>
                  <Term>Auto-compaction threshold</Term> — when
                  loading session history at the start of a turn,
                  Phantom token-budget-walks oldest-to-newest until
                  the cap fits. If the walk drops ≥ N prior messages,
                  auto-compaction kicks in and summarizes the dropped
                  portion via Gemini. Default 5; chatty workflows
                  can dial down to 2-3 to compact early; one-shot
                  workflows can dial up to suppress.
                </li>
                <li>
                  <Term>Memory MMR λ</Term> — Maximal Marginal
                  Relevance weight in the memory-store ranking
                  pipeline. Higher λ favors relevance over diversity
                  (returns tighter matches); lower λ favors diversity
                  (returns a spread of related-but-different memories).
                  Default 0.7. Lower it if memory results feel
                  repetitive.
                </li>
                <li>
                  <Term>Memory temporal decay λ</Term> — exponential
                  decay applied to memory-row recency in ranking.
                  Higher λ favors fresh memories aggressively; lower
                  λ treats old + new equally. Default 0.05 (half-life
                  ~14 days). Raise it for fast-moving incident
                  response contexts; lower it for long-running
                  knowledge bases.
                </li>
              </ul>
              <p className="text-sm">
                Slider drags auto-save after a short debounce — no
                explicit Save button. The auto-save fires a tier-2
                approval card the first time per session; subsequent
                drags in the same session reuse the approval already
                granted.
              </p>
            </SubSection>

            <SubSection icon="history" title="History + reset">
              <p>
                Every save snapshots the prior blob into{" "}
                <Code>personality_history</Code>. The page&apos;s{" "}
                <Term>History</Term> drawer shows the last N
                snapshots with diff highlights — click a row to
                preview the prior state, or click{" "}
                <Term>Restore</Term> to write it back (itself a
                tier-2 approval-gated write).
              </p>
              <p>
                <Term>Reset to default</Term> at the bottom of the
                page is a tier-3 destructive action — it requires
                an approval card AND types the literal word{" "}
                <Code>RESET</Code> into a confirmation field. The
                snapshot happens BEFORE the reset, so you can always
                restore from history afterwards.
              </p>
            </SubSection>

            <SubSection icon="smart_toy" title="Asking the agent to update the persona">
              <p>
                The chat agent has tools to read and update the
                personality blob directly. Examples:
              </p>
              <ul className="list-disc pl-5 space-y-1 text-sm">
                <li>
                  &ldquo;Set the agent name to &lsquo;Detection
                  engineer&rsquo; and the tone to &lsquo;tactical,
                  command-only&rsquo;.&rdquo; → calls{" "}
                  <Code>personality_patch</Code>, surfaces an approval
                  card with the diff.
                </li>
                <li>
                  &ldquo;What instructions are configured?&rdquo; →
                  calls <Code>personality_get</Code> (tier-1, no
                  approval).
                </li>
                <li>
                  &ldquo;Reset the personality to default.&rdquo; →
                  calls <Code>personality_reset</Code> (tier-3
                  destructive), surfaces a stronger approval card.
                </li>
              </ul>
              <p className="text-sm">
                Each call writes an audit row (<Code>personality_set</Code>,{" "}
                <Code>personality_reset</Code>, etc.) — browse them
                in <Link href="/observability/events" className="link">
                /observability/events
                </Link>{" "}
                with the <em>Personality</em> filter chip.
              </p>
            </SubSection>
          </Section>

          <Section id="backup-restore" icon="save" title="Backup & Restore">
            <p>
              Phantom packages every operator-owned piece of state
              into a single portable zip:{" "}
              <Link href="/settings/backup-restore" className="link">
                /settings/backup-restore
              </Link>{" "}
              is the one-stop surface. The same zip downloads from one
              deployment and restores onto another, even when the
              destination uses a different{" "}
              <Code>PHANTOM_SECRET_KEK</Code>. Use it to migrate
              between hosts, snapshot before risky changes, or
              capture known-good state for compliance.
            </p>

            <SubSection icon="download" title="Backup — what travels">
              <p>
                Click <Term>Download</Term> on{" "}
                <Link href="/settings/backup-restore" className="link">
                  /settings/backup-restore
                </Link>{" "}
                and your browser saves{" "}
                <Code>phantom-backup-&lt;ISO-stamp&gt;.zip</Code>.
                The zip carries one JSON or directory per platform
                surface:
              </p>
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>Personality</Term> — single-row blob (persona
                  fields + tuning knobs)
                </li>
                <li>
                  <Term>Instances + secrets</Term> — every connector
                  instance with config + cleartext secrets (so the
                  destination can re-encrypt under its own KEK)
                </li>
                <li>
                  <Term>Jobs</Term> — runtime-source jobs only;
                  manifest jobs reseed from{" "}
                  <Code>manifest.yaml</Code> at boot
                </li>
                <li>
                  <Term>Memory</Term> — all memory entries, without
                  embedding BLOBs (those re-embed at first search
                  on the destination)
                </li>
                <li>
                  <Term>Skills</Term> — every operator skill MD file,
                  preserving the category subdirectory structure
                </li>
                <li>
                  <Term>Knowledge</Term> — bundle doc references (the
                  KB itself reseeds from the destination&apos;s image)
                </li>
                <li>
                  <Term>Data sources</Term> — operator-uploaded YAML
                  files + the install set (which bundled packs were
                  picked)
                </li>
                <li>
                  <Term>Log destinations</Term> — every destination
                  config with secrets
                </li>
              </ul>
              <p className="text-warning text-sm">
                <span className="material-symbols-outlined text-[14px] align-text-bottom mr-1">
                  warning
                </span>
                <strong>The zip contains plaintext secrets.</strong>{" "}
                That&apos;s how the destination re-encrypts under its
                own KEK on restore — but it means the zip is
                operator-sensitive. Don&apos;t commit to version
                control; don&apos;t share over unencrypted channels;
                store at-rest encrypted if you keep snapshots.
              </p>
            </SubSection>

            <SubSection icon="preview" title="Dry-run preview">
              <p>
                Before committing a restore, click the file picker on{" "}
                <Link href="/settings/backup-restore" className="link">
                  /settings/backup-restore
                </Link>{" "}
                → <Term>Preview restore plan</Term>. The server
                parses the zip&apos;s <Code>manifest.json</Code>,
                counts entries per section, and renders a per-section
                summary card:
              </p>
              <Pre>{`Restore preview — phantom-backup-2026-05-25T14-22-09Z.zip

  Personality           1 row (will overwrite existing)
  Instances             4 instances + 11 secrets
  Skills               23 files (3 collisions; default = skip)
  Memory              152 entries (no collisions; embeddings re-built)
  Knowledge             — (no-op; image-baked)
  Data sources          7 user uploads + 12 install picks
  Log destinations      2 destinations (1 collision; default = skip)
  Jobs                  6 runtime jobs (last in restore order)

  ☐ Overwrite existing entries (force)`}</Pre>
              <p className="text-sm">
                The dry-run is purely read-only — nothing is written
                on the destination until you click{" "}
                <Term>Apply restore</Term>.
              </p>
            </SubSection>

            <SubSection icon="play_arrow" title="Restore — dependency-ordered apply">
              <p>
                Apply commits each section in dependency order so
                cross-section references never fail-closed:
              </p>
              <ol className="list-decimal pl-5 space-y-1 text-sm">
                <li>
                  <Term>Personality</Term> first (no dependencies;
                  always overwritten)
                </li>
                <li>
                  <Term>Instances + secrets</Term> next (connectors
                  must exist before jobs reference them)
                </li>
                <li>
                  <Term>Skills</Term> + <Term>Memory</Term> +{" "}
                  <Term>Knowledge</Term>
                </li>
                <li>
                  <Term>Data sources</Term> (user uploads via two-
                  phase preview/commit; install set re-runs the
                  install endpoint)
                </li>
                <li>
                  <Term>Jobs</Term> last — runtime jobs that
                  reference connectors don&apos;t fire on a missing
                  instance because instances landed in step 2.
                </li>
              </ol>
            </SubSection>

            <SubSection icon="merge_type" title="Collisions + force-overwrite">
              <p>
                Default semantics on every section are{" "}
                <Term>upsert-or-skip</Term>: an incoming row whose
                name/id collides with an existing one preserves the
                existing entry and reports the incoming one in the{" "}
                <Code>skipped</Code> summary count. Tick{" "}
                <Term>Overwrite existing entries (force)</Term> on the
                Restore plan to overwrite. <Term>Personality is
                always overwritten</Term> regardless — it&apos;s a
                single-row blob, there&apos;s no merge semantics.
              </p>
            </SubSection>

            <SubSection icon="warning" title="Caveats">
              <ul className="list-disc pl-5 space-y-1.5 text-sm">
                <li>
                  <Term>Memory embeddings</Term> aren&apos;t exported
                  (they&apos;re dim-bound to the embedding model). The
                  destination re-embeds entries on next semantic
                  search; the first search may be slightly slower
                  while the queue warms up.
                </li>
                <li>
                  <Term>Knowledge bundles</Term> are image-baked. The
                  zip carries doc content for reference but restore is
                  a no-op — the destination&apos;s KB is determined by
                  its container image.
                </li>
                <li>
                  <Term>Manifest jobs</Term> reseed from{" "}
                  <Code>manifest.yaml</Code> at boot regardless of
                  restore. Only runtime-source jobs round-trip.
                </li>
                <li>
                  <Term>API keys + audit log</Term> are NOT exported
                  on purpose. API keys are scoped to a specific
                  deploy; audit logs are tamper-evident per-host
                  records.
                </li>
              </ul>
            </SubSection>

            <SubSection icon="api" title="API surface">
              <Pre>{`GET    /api/agent/backup                  -- download zip (cookie-gated)
POST   /api/agent/restore?dry_run=true    -- parse + preview only
POST   /api/agent/restore                 -- apply (with ?force=1 to overwrite)`}</Pre>
              <p className="text-sm text-on-surface-variant">
                The agent has no MCP tool surface for backup/restore
                — the cleartext-secrets envelope keeps these
                operator-only per the credential boundary.
                Scripted backup workflows use the REST endpoints
                with an{" "}
                <Link href="#api-keys" className="link">
                  API key
                </Link>{" "}
                in the bearer header.
              </p>
            </SubSection>
          </Section>

          <Section id="log-generation" icon="speed" title="Log Generation: Rates, Restarts and Stalls">
            <p>
              Synthetic log generation runs as <strong>workers</strong>. Each one
              emits a set number of events on a repeating tick, so its real output
              is a <em>rate that continues until you stop it</em> — not a one-off
              batch. Reading a worker&rsquo;s count as a total is the single easiest
              mistake to make here, and the difference can be four orders of
              magnitude.
            </p>

            <SubSection icon="visibility" title="Seeing what is running">
              <p>
                The <Code>Log Destinations</Code> page shows a{" "}
                <strong>Live generation rate</strong> panel: every running worker,
                its rate, and the combined total measured against the ceiling. Use
                it to answer &ldquo;what is currently producing data, and how
                much?&rdquo; without reading container logs.
              </p>
              <p>
                The rates shown are what each worker <em>declared</em> when it was
                created &mdash; which is what the ceilings are enforced against.
                They are not a measurement of events that arrived at the far end.
              </p>
            </SubSection>

            <SubSection icon="restart_alt" title="Restarts do not stop generation">
              <p>
                Workers are recorded and rebuilt automatically when the log service
                restarts, so a restart &mdash; an upgrade, a crash, a
                container recreate &mdash; does not end any worker <strong>silently</strong>
                or leave the list empty and the platform looking idle.
              </p>
              <p>
                This matters most when you are building up baseline telemetry.
                Behavioural detections only advance their learning while data is
                arriving, so a silent stop sets back the one thing that cannot be
                caught up later.
              </p>
              <p>
                A worker part-way through a bounded run resumes with its{" "}
                <strong>remaining</strong> budget, never a fresh one, so a restart
                cannot replay the same burst repeatedly. Stopping a worker yourself
                is permanent &mdash; a restart will not bring it back.
              </p>
            </SubSection>

            <SubSection icon="cleaning_services" title="Stalled workers are reclaimed">
              <p>
                A worker can stop making progress without stopping &mdash; blocked
                writing to a destination that has gone away, for instance. It would
                otherwise keep holding its slot and its share of the rate budget,
                so new workers get refused on behalf of one doing nothing.
              </p>
              <p>
                A background check reclaims those. Detecting a worker whose thread
                has died is exact and always on. Detecting one that is merely{" "}
                <em>slow to emit</em> is a judgement call, so it is off unless you
                enable it &mdash; a low-rate worker emits rarely by design, and
                stopping a healthy one is worse than the capacity it frees.
              </p>
            </SubSection>
          </Section>

          <Section id="settings-precedence" icon="layers" title="Where Settings Live">
            <p>
              Phantom has multiple surfaces where you can set or change
              operator credentials and connector config. This section
              is the cheat sheet for which surface to use when, what
              survives an upgrade, and where the data actually lives.
              The full architectural picture is in{" "}
              <Link href="/help/architecture#secret-store" className="link">
                Architecture → Secret Store
              </Link>
              {" "}where the SecretStore Flow diagram traces every read
              and write path.
            </p>

            <Callout tone="info">
              <Term>One-line summary.</Term> The first-run setup form
              runs ONCE at install. Every change after that goes
              through the dedicated UI for what you&apos;re editing —
              {" "}<Link href="/profile" className="link">/profile</Link>{" "}for
              your UI password,{" "}
              <Link href="/providers" className="link">/providers</Link>{" "}
              for Vertex / Gemini service-account JSON,{" "}
              <Link href="/connectors" className="link">/connectors</Link>{" "}
              for per-connector instance creds. No setup re-runs,
              no merge logic, no surprise replacements.
            </Callout>

            <SubSection icon="rocket_launch" title="Scenario 1 — First-time install">
              <p>
                AuthGate detects no setup-completed flag at{" "}
                <Code>/app/runtime/.setup_complete</Code> → renders the
                setup form. You fill everything (UI password, Vertex
                SA JSON, connector configs — Caldera, XSIAM, XLOG) and
                submit.
              </p>
              <p>
                The agent then delegates each piece of data to its
                canonical store:
              </p>
              <ul className="list-disc pl-6 space-y-1">
                <li>UI password → <Code>POST /api/v1/ui/auth/password</Code> → SecretStore <Code>/ui/auth/&lt;user&gt;/password_hash</Code> (PBKDF2)</li>
                <li>Vertex creds → <Code>POST /api/v1/setup</Code> → ProviderStore <Code>primary-vertex</Code> instance (config + secrets)</li>
                <li>Connector configs → same setup endpoint → InstanceStore one row per connector</li>
                <li>TLS material → <Code>/tls/cert.pem</Code> + <Code>/tls/key.pem</Code> on the shared volume</li>
                <li>Setup-completed flag → <Code>/app/runtime/.setup_complete</Code> (presence-only marker)</li>
              </ul>
              <p>
                <Code>setup.json</Code> and <Code>.env.generated</Code>{" "}
                are NOT written. Operator-typed values live exclusively
                in the stores listed above. See{" "}
                <Link href="/help/architecture#setup-wiring" className="link">/help/architecture#setup-wiring</Link>{" "}
                for the canonical specification.
              </p>
            </SubSection>

            <SubSection icon="upload" title="Scenario 2 — Upgrade preserves everything">
              <p>
                Upgrading the stack via{" "}
                <Code>docker compose pull + up</Code> swaps in new
                images without touching persistent volumes. The
                bind-mounted <Code>./.phantom-agent</Code> path holds
                the setup-completed flag; the named volume{" "}
                <Code>phantom_mcp_data</Code> holds the SecretStore +
                InstanceStore + ProviderStore + audit log. Both
                survive container recreation.
              </p>
              <p>
                After upgrade, AuthGate calls{" "}
                <Code>isSetupRequired()</Code> and renders the
                LoginScreen. The setup form is unreachable
                post-install: typing <Code>/setup</Code> directly
                redirects to <Code>/</Code>, and{" "}
                <Code>POST /api/setup</Code> returns 409. Your
                existing credentials, connector instances, provider
                config, password hash, audit history — all preserved.
              </p>
            </SubSection>

            <SubSection icon="cable" title="Scenario 3a — Change connector creds via /connectors">
              <p>
                Want to rotate the Caldera password, change the XSIAM
                PAPI URL, or update the XLOG webhook key? Use{" "}
                <Link href="/connectors" className="link">/connectors</Link>.
                Each connector has an instance (created at first-run
                from the bundle&apos;s <Code>bindsInstances</Code>{" "}
                template) and you can edit its config + secrets in
                place. Writes go through the MCP&apos;s instance API
                directly to the InstanceStore + SecretStore — no setup
                re-run, no agent restart. Tool calls (
                <Code>caldera.*</Code>, <Code>xsiam.*</Code>,{" "}
                <Code>xlog.*</Code>) read from InstanceStore on every
                invocation, so changes take effect at the next call.
              </p>
              <p className="text-sm text-on-surface-variant/85">
                Every caldera + xsiam tool routes through a single
                chokepoint helper that calls{" "}
                <Code>store.list_for(...)</Code> and{" "}
                <Code>instance.merged_config(secret_store)</Code> on every
                invocation, ensuring the InstanceStore is the single
                source of truth. See{" "}
                <Link
                  href="/help/architecture#connector-state"
                  className="link"
                >
                  Connector State Machine
                </Link>{" "}
                for the architectural detail.
              </p>
            </SubSection>

            <SubSection icon="psychology" title="Scenario 3b — Change Vertex creds via /providers">
              <p>
                Replace the Vertex service-account JSON, update the
                project ID, switch regions — all from{" "}
                <Link href="/providers" className="link">/providers</Link>.
                The page populates from the ProviderStore on load:
                Project ID and Region show in cleartext, the JSON shows
                as masked bullets. Change any subset — Test Connection
                and Save Changes activate when at least one field
                differs from the loaded value.
              </p>
              <p>
                Save calls <Code>PUT /api/v1/providers/{"{id}"}</Code>{" "}
                directly on the MCP. Untouched secret slots round-trip
                as the redaction sentinel and are preserved server-side.
                <Code>setup.json</Code> and <Code>.env.generated</Code>{" "}
                are NEVER written by this path. The cache for
                chat-handler vertex-cred resolution is invalidated
                in the same response, so the next chat dispatch sees
                your update with no propagation delay.
              </p>
              <p>
                If the operator hasn&apos;t configured Vertex yet
                (clean install, no <Code>primary-vertex</Code> instance
                in the ProviderStore), saving for the first time
                creates the instance via{" "}
                <Code>POST /api/v1/providers</Code>. All three fields
                (project, region, JSON) are required for the create
                path; partial creates aren&apos;t allowed because the
                MCP&apos;s manifest binding wouldn&apos;t materialise.
              </p>
            </SubSection>

            <SubSection icon="lock_reset" title="Scenario 3c — Change UI password via /profile">
              <p>
                Password changes go through the dedicated{" "}
                <Link href="/profile" className="link">/profile</Link>{" "}
                page. The hash lives in the SecretStore under{" "}
                <Code>/ui/auth/&lt;username&gt;/password_hash</Code>{" "}
                — see{" "}
                <Link href="#authentication" className="link">
                  Authentication
                </Link>{" "}
                for the full storage spec, session-revocation
                semantics, and audit-row references.
              </p>
            </SubSection>

            <SubSection icon="save" title="Scenario 3e — Backup &amp; restore the whole deployment">
              <p>
                Phantom packages every operator-owned piece of state
                into a single portable zip. See{" "}
                <Link href="#backup-restore" className="link">
                  Backup &amp; Restore
                </Link>{" "}
                for the full walkthrough — what travels in the zip,
                dry-run preview, dependency-ordered apply, collision
                semantics, and the REST API surface.
              </p>
            </SubSection>

            <SubSection icon="terminal" title="Env overlay (advanced — read-only shadow)">
              <p>
                <Code>EnvSecretStore</Code> is a read-time shadow: when
                a SecretStore consumer calls <Code>read(path)</Code>,
                the overlay first checks env vars matching the path
                pattern. If matched, the env value wins for THAT read;
                the file-backed store is never touched. Useful for IaC
                / CI flows that want to pin a credential per deployment
                without mutating the encrypted store. Set the env var
                via your <Code>.env</Code> or a compose override.
              </p>
            </SubSection>
          </Section>

          {/* ============================================================
                              TROUBLESHOOTING
              ============================================================ */}

          <Section id="troubleshoot" icon="support" title="Where to Look When…">
            <p>
              Common symptoms and the first place to look. The full
              troubleshooting tree lives across{" "}
              <Link href="/observability" className="link">
                /observability
              </Link>{" "}
              — these are the highest-yield starting points.
            </p>

            <Decision title="A job didn't fire">
              <p>
                Open <Link href="/jobs" className="link">/jobs</Link>, find
                the row. Filter by &quot;Failed&quot; or &quot;Never
                run.&quot; Click the card → the &quot;Last error&quot;
                banner tells you why; the run history table shows trigger
                source and duration. For chat actions that return empty,
                expand the row — the model&apos;s reply is rendered
                inline; an empty reply means Gemini hit MAX_TOKENS or
                returned only function calls.
              </p>
            </Decision>

            <Decision title="A chat session looks empty after reload">
              <p>
                Right-side telemetry panel rehydrates from the messages
                table on session reload. If it&apos;s empty there, the
                session probably had no tool calls — the panel only
                restores tool round-trips, not the model&apos;s text
                deltas (those aren&apos;t persisted to keep storage
                tractable).
              </p>
            </Decision>

            <Decision title="An approval is stuck">
              <p>
                Open <Link href="/approvals" className="link">/approvals</Link>.
                Pending tab shows live requests; click Approve or Deny.
                Resolved tab shows history. Stuck requests time out after
                5 minutes server-side (the chat just unblocks with an
                error); if a card is older than that, it was already
                resolved — refresh.
              </p>
            </Decision>

            <Decision title="A connector call returns 'invalid bearer token'">
              <p>
                The <Code>MCP_TOKEN</Code> rotated. A copy saved elsewhere
                may be stale; the container always
                reads the live one from{" "}
                <Code>/app/runtime/setup.json</Code> (or its env). When
                in doubt, exec into the container and check{" "}
                <Code>env | grep MCP_TOKEN</Code>. Setup-form values for
                MCP_TOKEN are persisted but ignored on the wire.
              </p>
            </Decision>

            <Decision title="A connector shows 'Not Installed' in the marketplace">
              <p>
                Visit{" "}
                <Link href="/connectors" className="link">
                  /connectors
                </Link>{" "}
                → Instances tab. If the connector has no instance there,
                the credentials weren&apos;t bound at first-run setup.
                Create an instance directly from /connectors → Create
                Instance — the form uses the same configSchema +
                secretSlots the bundle exposes, so it asks for the
                same fields setup would have. The marketplace status
                derives from instance presence — once an instance
                exists, the badge flips to{" "}
                <Term>Installed</Term> on the next refresh.
              </p>
            </Decision>

            <Decision title="A node on the pipeline graph shows red but the service is up">
              <p>
                Container-internal hostnames (e.g.,{" "}
                <Code>https://xlog:8000</Code>) can&apos;t be reached from
                the browser, so the pipeline page routes all probes through{" "}
                <Code>/api/agent/health</Code> (server-side). If a node is
                still red, hit the Component Status
                table on that page — the HTTP code + latency tell you
                whether the probe completed and what came back.
              </p>
            </Decision>

            <Decision title="The agent says 'I can't run that'">
              <p>
                Either the matching skill is disabled (check{" "}
                <Link href="/skills" className="link">/skills</Link>, look
                for the toggle in the off state), or the agent doesn&apos;t
                think it has a relevant tool — check the skill&apos;s{" "}
                detail panel for the listed tools and confirm those exist
                in the right connector via the{" "}
                <Link href="/connectors" className="link">
                  Connectors
                </Link>{" "}
                tool inventory.
              </p>
            </Decision>
          </Section>

          {/* ============================================================
                              REFERENCES
              ============================================================ */}

          <Section
            id="ref-architecture"
            icon="schema"
            title="Architecture Guide"
          >
            <p>
              Companion to this user guide, focused on{" "}
              <em>how Phantom is built</em> rather than how to use it.
              Covers the 5-service stack, boot lifecycle, the
              chat-route pipeline, every subsystem (memory, knowledge,
              skills, hooks, tasks, plan mode, subagents, plugins,
              jobs, notifications, approvals, models, providers,
              secret store), the three external connectors (xlog /
              CALDERA / XSIAM), audit-row schemas, REST endpoint wire
              formats, and the design decisions that shaped each
              substrate.
            </p>
            <p>
              Read this when you&apos;re extending the platform — adding
              a hook event, wiring a new audit action, building a
              plugin, or just trying to understand <em>why</em> something
              was built the way it was.
            </p>
            <Link
              href="/help/architecture"
              className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline mt-2"
            >
              <span className="material-symbols-outlined text-base">
                arrow_forward
              </span>
              Open the Architecture Guide
            </Link>
          </Section>

          <Section id="ref-journeys" icon="tour" title="User Journeys">
            <p>
              Hands-on, step-by-step walkthroughs for common operator
              tasks — onboarding a new connector, running a full attack
              simulation, validating detections after a content release,
              installing a Slack policy hook, monitoring tasks,
              spawning red/blue subagents. Each journey lists the
              prompts to paste, the tools that fire, and the expected
              output. Filter by category (memory, simulation, redteam,
              validation, ops, chat) or difficulty (starter,
              intermediate, advanced).
            </p>
            <Link
              href="/help/journeys"
              className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline mt-2"
            >
              <span className="material-symbols-outlined text-base">
                arrow_forward
              </span>
              Browse user journeys
            </Link>
          </Section>

          <Section id="ref-api" icon="api" title="REST API">
            <p>
              Wire-format reference for every <Code>/api/v1/*</Code>{" "}
              endpoint — request schema, response shape, auth requirements,
              cURL examples. Click an endpoint card for the detail view
              with a try-it-out form; the icon buttons in the header view
              or download the OpenAPI 3.0 JSON spec. Endpoint internals
              (which audit rows fire, which tier gates them) are
              cross-referenced from{" "}
              <Link
                href="/help/architecture#rest-api"
                className="link"
              >
                Architecture &rarr; REST API
              </Link>
              .
            </p>
            <Link
              href="/help/api"
              className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline mt-2"
            >
              <span className="material-symbols-outlined text-base">
                arrow_forward
              </span>
              Browse REST API
            </Link>
          </Section>
        </div>
      </div>

      <style jsx>{`
        .link {
          color: var(--m3-primary, hsl(var(--primary)));
          text-decoration: none;
          font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
            "Liberation Mono", "Courier New", monospace;
          font-size: 0.95em;
        }
        .link:hover {
          text-decoration: underline;
        }
      `}</style>
    </div>
  );
}

// ── Section primitives ─────────────────────────────────────────────

function Section({
  id,
  icon,
  title,
  children,
}: {
  id: string;
  icon: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-8 space-y-4">
      <div className="flex items-center gap-3 pb-2 border-b border-outline-variant/30">
        <span className="material-symbols-outlined text-2xl text-primary">
          {icon}
        </span>
        <h2 className="font-headline text-2xl font-bold tracking-tight text-on-surface">
          {title}
        </h2>
      </div>
      <div className="space-y-3 text-sm leading-relaxed text-on-surface-variant">
        {children}
      </div>
    </section>
  );
}

function SubSection({
  id,
  icon,
  title,
  children,
}: {
  id?: string;
  icon: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div id={id} className="space-y-2 pt-2">
      <div className="flex items-center gap-2">
        <span className="material-symbols-outlined text-base text-primary/80">
          {icon}
        </span>
        <h3 className="font-headline text-sm font-bold tracking-tight text-on-surface uppercase">
          {title}
        </h3>
      </div>
      <div className="space-y-2 pl-7 text-sm leading-relaxed text-on-surface-variant">
        {children}
      </div>
    </div>
  );
}

function Decision({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="rounded-xl p-4 space-y-2"
      style={glassStyle}
    >
      <div className="flex items-center gap-2">
        <span className="material-symbols-outlined text-base text-tertiary">
          troubleshoot
        </span>
        <h3 className="font-bold text-sm text-on-surface">{title}</h3>
      </div>
      <div className="text-sm text-on-surface-variant leading-relaxed">
        {children}
      </div>
    </div>
  );
}

function Term({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-semibold text-on-surface">
      {children}
    </span>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="font-mono text-[0.85em] px-1.5 py-0.5 rounded bg-surface-container-low text-on-surface border border-outline-variant/30">
      {children}
    </code>
  );
}

function Pre({ children }: { children: string }) {
  return (
    <pre
      className="text-[12px] leading-relaxed font-mono p-4 rounded-xl overflow-x-auto text-on-surface-variant"
      style={glassStyle}
    >
      {children}
    </pre>
  );
}

function Callout({
  tone,
  children,
}: {
  tone: "info" | "warn";
  children: React.ReactNode;
}) {
  const toneClass =
    tone === "warn"
      ? "border-l-4 border-l-tertiary bg-tertiary/5"
      : "border-l-4 border-l-primary bg-primary/5";
  const icon = tone === "warn" ? "warning" : "info";
  return (
    <div
      className={`rounded-r-xl pl-4 pr-5 py-3 flex gap-3 text-sm ${toneClass}`}
    >
      <span
        className={`material-symbols-outlined text-base shrink-0 ${
          tone === "warn" ? "text-tertiary" : "text-primary"
        }`}
      >
        {icon}
      </span>
      <div className="text-on-surface leading-relaxed">{children}</div>
    </div>
  );
}

