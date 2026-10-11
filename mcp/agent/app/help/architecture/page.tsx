"use client";

/**
 * Phantom Architecture Guide.
 *
 * Architect-focused deep documentation for Phantom's internals.
 * Distinct from /help/user (operator-task-oriented). The split is
 * deliberate: operators don't need to know how the chat-route's
 * tool-dispatch loop wires hooks; architects extending Phantom DO
 * need that level of detail. Splitting keeps each guide useful to
 * its audience without bloating either.
 *
 * Coverage:
 * - 5-service stack topology + service contracts
 * - Manifest & bundle layout
 * - Chat-route turn lifecycle (entry → fire-sites → tool dispatch
 * → done event → audit + cost rows)
 * - Context & sessions: token budgeting, compaction, Vertex caching
 * - Slash & plan: slash framework, plan-mode proposal flow
 * - Tasks & agents: task registry, subagent dispatch
 * - Connectors & extensions: hooks, connector state, tool metadata,
 * skill activation, plugin contributions
 * - Operability: audit persistence, settings tuning, cost tracking
 * - Substrate composition (how hooks + tasks + plugins + subagents
 * reuse one another rather than duplicating machinery)
 * - Audit log schema & event-name aliases
 * - REST API reference table
 * - Design decisions
 *
 * Sections describe the system as it currently is. No project-history
 * framing: sections name concepts, not internal milestones.
 *
 * No diagrams (per operator request — those land later).
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { AgentKnowledgeSurfaces } from "@/components/diagrams/agent-knowledge-surfaces";
import {
  AuthLoginFlow,
  AuthChangePasswordFlow,
  AuthCliResetFlow,
} from "@/components/diagrams/auth-flows";
import { AuthTopology } from "@/components/diagrams/auth-topology";
import { AuthTrustBoundaries } from "@/components/diagrams/auth-trust-boundaries";
import { ChatTurnLifecycle } from "@/components/diagrams/chat-turn-lifecycle";
import { ContextMemoryPipeline } from "@/components/diagrams/context-memory-pipeline";
import { DataSourcesFlow } from "@/components/diagrams/data-sources-flow";
import { LogDestinationsFlow } from "@/components/diagrams/log-destinations-flow";
import { ExternalConnectorsAnatomy } from "@/components/diagrams/external-connectors-anatomy";
import { FullPlatformTopology } from "@/components/diagrams/full-platform-topology";
import { JobsLifecycle } from "@/components/diagrams/jobs-lifecycle";
import { SkillsActivation } from "@/components/diagrams/skills-activation";
import { PersistentStores } from "@/components/diagrams/persistent-stores";
import { SecretStoreFlow } from "@/components/diagrams/secret-store-flow";
import { StateMachinesAtlas } from "@/components/diagrams/state-machines-atlas";
import { SubstrateComposition as SubstrateCompositionDiagram } from "@/components/diagrams/substrate-composition";
import { cn } from "@/lib/utils";

// ─── Layout primitives ────────────────────────────────────────────

const glassStyle = {
 background: "var(--glass-bg-strong)",
 backdropFilter: "blur(12px)",
 border: "0.5px solid var(--glass-border)",
} as const;

interface SectionDef {
 id: string;
 label: string;
 group: string;
 icon: string;
}

const SECTIONS: SectionDef[] = [
 // ── Foundation ─────────────────────────────────────────────────
 { id: "intro", label: "Introduction", group: "Foundation", icon: "info" },
 { id: "stack", label: "Service Stack", group: "Foundation", icon: "view_module" },
 { id: "image-pinning", label: "Image Digest Pinning", group: "Foundation", icon: "verified" },
 { id: "tls-proxy", label: "TLS Proxy & Entrypoint", group: "Foundation", icon: "lock" },
 { id: "phantom-updater", label: "phantom-updater Service", group: "Foundation", icon: "system_update" },
 { id: "manifest", label: "Manifest & Bundle", group: "Foundation", icon: "package_2" },
 { id: "data-roots", label: "Data Roots", group: "Foundation", icon: "database" },
 { id: "boot-lifecycle", label: "Boot Lifecycle", group: "Foundation", icon: "rocket_launch" },
 { id: "authentication", label: "Authentication", group: "Foundation", icon: "lock_person" },
 { id: "setup-wiring", label: "Setup & First-Run Wiring", group: "Foundation", icon: "rocket_launch" },

 // ── Chat Pipeline ──────────────────────────────────────────────
 { id: "chat-lifecycle", label: "Chat Turn Lifecycle", group: "Chat Pipeline", icon: "loop" },
 { id: "fire-sites", label: "Hook Fire-Sites", group: "Chat Pipeline", icon: "flag" },
 { id: "tool-dispatch", label: "Tool Dispatch Loop", group: "Chat Pipeline", icon: "build" },
 { id: "sse-events", label: "SSE Event Stream", group: "Chat Pipeline", icon: "stream" },

 // ── Context & Sessions ─────────────────────────────────────────
 { id: "session-store", label: "Session Store", group: "Context & Sessions", icon: "chat_bubble" },
 { id: "context-budget", label: "Context Budgeting", group: "Context & Sessions", icon: "token" },
 { id: "compaction", label: "Compaction Pipeline", group: "Context & Sessions", icon: "compress" },
 { id: "vertex-cache", label: "Vertex Caching", group: "Context & Sessions", icon: "bolt" },
 { id: "memory-store", label: "Memory Store Internals", group: "Context & Sessions", icon: "database" },

 // ── Knowledge & Skills ─────────────────────────────────────────
 { id: "knowledge-pipeline", label: "Knowledge Pipeline", group: "Knowledge & Skills", icon: "menu_book" },
 { id: "skill-catalogue", label: "Skill Catalogue", group: "Knowledge & Skills", icon: "auto_awesome" },
 { id: "skill-activation", label: "Skill Activation", group: "Knowledge & Skills", icon: "school" },

 // ── Slash & Plan ───────────────────────────────────────────────
 { id: "slash-commands", label: "Slash Framework", group: "Slash & Plan", icon: "terminal" },
 { id: "plan-mode", label: "Plan Mode", group: "Slash & Plan", icon: "map" },

 // ── Tasks & Agents ─────────────────────────────────────────────
 { id: "tasks", label: "Task Registry", group: "Tasks & Agents", icon: "pending_actions" },
 { id: "subagents", label: "Subagents & Agent Definitions", group: "Tasks & Agents", icon: "groups" },

 // ── Connectors & Extensions ────────────────────────────────────
 { id: "hooks", label: "Hooks Framework", group: "Connectors & Extensions", icon: "webhook" },
 { id: "connectors-design", label: "Connectors & Instances — Design", group: "Connectors & Extensions", icon: "schema" },
 { id: "connector-containers", label: "Per-instance Containers", group: "Connectors & Extensions", icon: "apps" },
 { id: "connector-state", label: "Connector State Machine", group: "Connectors & Extensions", icon: "cable" },
 { id: "tool-metadata", label: "Tool Metadata", group: "Connectors & Extensions", icon: "fact_check" },
 { id: "plugins", label: "Plugin System", group: "Connectors & Extensions", icon: "extension" },
 { id: "marketplace-logic", label: "Marketplace Logic", group: "Connectors & Extensions", icon: "storefront" },
 { id: "data-sources", label: "Data Sources", group: "Connectors & Extensions", icon: "dataset" },
 { id: "log-destinations", label: "Log Destinations", group: "Connectors & Extensions", icon: "cloud_upload" },
 { id: "operator-state", label: "Operator Workflow State", group: "Connectors & Extensions", icon: "savings" },

 // ── External Connectors ────────────────────────────────────────
 { id: "xlog-connector", label: "xlog Connector", group: "External Connectors", icon: "data_object" },
 { id: "caldera-connector", label: "CALDERA Connector", group: "External Connectors", icon: "swords" },
 { id: "xsiam-connector", label: "XSIAM Connector", group: "External Connectors", icon: "security" },
 { id: "cortex-xdr-connector", label: "Cortex XDR Connector", group: "External Connectors", icon: "shield_lock" },
 { id: "cortex-docs-connector", label: "Cortex Docs Connector", group: "External Connectors", icon: "menu_book" },
 { id: "cortex-content-connector", label: "Cortex Content Connector", group: "External Connectors", icon: "library_books" },
 { id: "web-connector", label: "Web Browser Connector", group: "External Connectors", icon: "language" },

 // ── Auth & Security ────────────────────────────────────────────
 { id: "auth-identity", label: "Auth & Identity", group: "Auth & Security", icon: "shield_person" },
 { id: "secret-store", label: "Secret Store", group: "Auth & Security", icon: "lock" },
 { id: "approvals", label: "Approvals & Tiers", group: "Auth & Security", icon: "fact_check" },
 { id: "api-keys", label: "API Keys", group: "Auth & Security", icon: "vpn_key" },

 // ── Models & Providers ─────────────────────────────────────────
 { id: "model-resolution", label: "Model Resolution", group: "Models & Providers", icon: "psychology" },
 { id: "provider-store", label: "Provider Store", group: "Models & Providers", icon: "outlet" },

 // ── Background & Async ─────────────────────────────────────────
 { id: "jobs-subsystem", label: "Jobs Subsystem", group: "Background & Async", icon: "schedule" },
 { id: "notifications-feed", label: "Notifications Feed", group: "Background & Async", icon: "notifications" },

 // ── Operability ────────────────────────────────────────────────
 { id: "observability-overview", label: "Observability Overview", group: "Operability", icon: "insights" },
 { id: "audit-persistence", label: "Audit Persistence", group: "Operability", icon: "policy" },
 { id: "backup-restore", label: "Backup & Restore", group: "Operability", icon: "save" },
 { id: "settings-tuning", label: "Settings Tuning", group: "Operability", icon: "tune" },
 { id: "personality", label: "Personality Store", group: "Operability", icon: "psychology_alt" },
 { id: "cost-tracking", label: "Cost Tracking", group: "Operability", icon: "payments" },
 { id: "pipeline-health", label: "Pipeline Health Probes", group: "Operability", icon: "monitor_heart" },
 { id: "logs-events-traces", label: "Logs / Events / Traces", group: "Operability", icon: "stacked_line_chart" },
 { id: "polish", label: "Resilience & Polish", group: "Operability", icon: "auto_awesome" },

 // ── Composition ────────────────────────────────────────────────
 { id: "substrate-composition", label: "Substrate Composition", group: "Composition", icon: "diversity_3" },

 // ── Reference ──────────────────────────────────────────────────
 { id: "audit-schema", label: "Audit Log Schema", group: "Reference", icon: "history" },
 { id: "audit-events", label: "Audit Event Names", group: "Reference", icon: "list" },
 { id: "rest-api", label: "REST API Reference", group: "Reference", icon: "api" },
 { id: "design-decisions", label: "Design Decisions", group: "Reference", icon: "psychology" },
];

const GROUP_ORDER = [
 "Foundation",
 "Chat Pipeline",
 "Context & Sessions",
 "Knowledge & Skills",
 "Slash & Plan",
 "Tasks & Agents",
 "Connectors & Extensions",
 "External Connectors",
 "Auth & Security",
 "Models & Providers",
 "Background & Async",
 "Operability",
 "Composition",
 "Reference",
] as const;

export default function ArchitectureGuide() {
 const [active, setActive] = useState<string>(SECTIONS[0]?.id ?? "");
 const containerRef = useRef<HTMLDivElement>(null);
 // Section nav collapses INDEPENDENTLY of route navigation.
 // An explicit chevron toggle: collapse shows a thin rail with the
 // same chevron pointing the other way to expand. Persists in
 // localStorage so a re-open keeps the operator's preferred density.
 const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
 useEffect(() => {
 try {
 const stored = window.localStorage.getItem(
 "phantom.help.architecture.sidebar-collapsed",
);
 if (stored === "true") setSidebarCollapsed(true);
 } catch {
 // localStorage unavailable (private window, SSR) — accept the
 // expanded default; preference just doesn't persist.
 }
 }, []);
 useEffect(() => {
 try {
 window.localStorage.setItem(
 "phantom.help.architecture.sidebar-collapsed",
 sidebarCollapsed ? "true" : "false",
);
 } catch {
 // ditto — silent skip
 }
 }, [sidebarCollapsed]);

 useEffect(() => {
 const visible = new Map<string, number>();
 const obs = new IntersectionObserver(
 (entries) => {
 for (const e of entries) {
 if (e.isIntersecting) {
 visible.set(e.target.id, e.intersectionRatio);
 } else {
 visible.delete(e.target.id);
 }
 }
 if (visible.size > 0) {
 let bestId = "";
 let bestRatio = -1;
 for (const [id, r] of visible) {
 if (r > bestRatio) {
 bestRatio = r;
 bestId = id;
 }
 }
 if (bestId) setActive(bestId);
 }
 },
 { rootMargin: "-20% 0px -60% 0px", threshold: [0, 0.25, 0.5] },
);
 for (const s of SECTIONS) {
 const el = document.getElementById(s.id);
 if (el) obs.observe(el);
 }
 return () => obs.disconnect();
 }, []);

 return (
 <div className="h-screen overflow-hidden flex">
 {/* Sidebar — expanded view (collapses to a thin rail when
     sidebarCollapsed is true; the rail keeps the expand affordance
     visible without consuming the section-list's worth of width). */}
 {!sidebarCollapsed && (
 <aside
 className="w-80 shrink-0 overflow-y-auto custom-scrollbar p-5 border-r border-outline-variant/20"
 style={glassStyle}
 aria-label="Architecture guide section navigation"
 >
 {/* Top row: Help-index back link + collapse-sidebar toggle.
        The toggle is explicit; the backlink is purely a route
        navigation. */}
 <div className="mb-4 flex items-center justify-between gap-2">
 <Link
 href="/help"
 className="text-sm text-on-surface-variant/80 hover:text-on-surface flex items-center gap-1.5 transition-colors"
 >
 <span className="material-symbols-outlined text-base">arrow_back</span>
 Help index
 </Link>
 <button
 type="button"
 onClick={() => setSidebarCollapsed(true)}
 className="w-7 h-7 flex items-center justify-center rounded-md text-on-surface-variant/70 hover:text-on-surface hover:bg-white/5 transition-colors"
 aria-label="Collapse section navigation"
 title="Collapse navigation (stays on this page)"
 >
 <span className="material-symbols-outlined text-lg">chevron_left</span>
 </button>
 </div>
 <h1 className="font-headline text-xl font-bold text-on-surface mb-1.5">
 Architecture Guide
 </h1>
 <p className="text-sm text-on-surface-variant/80 mb-5 leading-relaxed">
 Deep technical documentation. For operator-facing tasks, see{" "}
 <Link href="/help/user" className="link">
 the user guide
 </Link>
.
 </p>
 {GROUP_ORDER.map((group) => (
 <div key={group} className="mb-5">
 <h2 className="text-xs font-label uppercase tracking-widest text-on-surface-variant/70 mb-2">
 {group}
 </h2>
 <ul className="space-y-0.5">
 {SECTIONS.filter((s) => s.group === group).map((s) => (
 <li key={s.id}>
 <a
 href={`#${s.id}`}
 className={cn(
 "flex items-center gap-2 px-2.5 py-1.5 rounded text-sm transition-colors",
 active === s.id
 ? "bg-primary/15 text-primary"
 : "text-on-surface-variant hover:text-on-surface hover:bg-white/5",
)}
 >
 <span className="material-symbols-outlined text-base">
 {s.icon}
 </span>
 {s.label}
 </a>
 </li>
))}
 </ul>
 </div>
))}
 </aside>
 )}

 {/* Sidebar — collapsed rail. Thin vertical strip with just an
     expand chevron, so the operator can recover the section nav
     in one click without leaving the page. */}
 {sidebarCollapsed && (
 <aside
 className="w-10 shrink-0 flex flex-col items-center pt-5 border-r border-outline-variant/20"
 style={glassStyle}
 aria-label="Architecture guide section navigation (collapsed)"
 >
 <button
 type="button"
 onClick={() => setSidebarCollapsed(false)}
 className="w-7 h-7 flex items-center justify-center rounded-md text-on-surface-variant/70 hover:text-on-surface hover:bg-white/5 transition-colors"
 aria-label="Expand section navigation"
 title="Expand navigation"
 >
 <span className="material-symbols-outlined text-lg">chevron_right</span>
 </button>
 </aside>
 )}

 {/* Content
     The page uses the full viewport width. Content stays readable
     on ultra-wide monitors thanks to the inner reading-flow elements
     (paragraphs wrap naturally; pre-formatted code blocks scroll
     inside their own boxes). */}
 <div
 ref={containerRef}
 className="flex-1 overflow-y-auto custom-scrollbar text-base"
 >
 <div className="px-10 py-8 space-y-12 max-w-[1400px]">
 {/* Foundation */}
 <Intro />
 <Stack />
 <ImagePinning />
 <TlsProxy />
 <PhantomUpdater />
 <ConnectorContainers />
 <Manifest />
 <DataRoots />
 <BootLifecycle />
 <Authentication />
 <SetupWiring />
 {/* Chat Pipeline */}
 <ChatLifecycle />
 <FireSites />
 <ToolDispatch />
 <SseEvents />
 {/* Context & Sessions */}
 <SessionStore />
 <ContextBudget />
 <Compaction />
 <VertexCache />
 <MemoryStore />
 {/* Knowledge & Skills */}
 <KnowledgePipeline />
 <SkillCatalogue />
 <SkillActivation />
 {/* Slash & Plan */}
 <SlashCommands />
 <PlanMode />
 {/* Tasks & Agents */}
 <Tasks />
 <Subagents />
 {/* Connectors & Extensions */}
 <Hooks />
 <ConnectorsDesign />
 <ConnectorState />
 <ToolMetadata />
 <Plugins />
 <MarketplaceLogic />
 <DataSourcesMarketplace />
 <OperatorState />
 {/* External Connectors */}
 <XlogConnector />
 <CalderaConnector />
 <XsiamConnector />
 <CortexXdrConnector />
 <CortexDocsConnector />
 <CortexContentConnector />
 <WebConnector />
 {/* Auth & Security */}
 <AuthIdentity />
 <SecretStore />
 <Approvals />
 <ApiKeys />
 {/* Models & Providers */}
 <ModelResolution />
 <ProviderStore />
 {/* Background & Async */}
 <JobsSubsystem />
 <NotificationsFeed />
 {/* Operability */}
 <ObservabilityOverview />
 <AuditPersistence />
 <BackupRestore />
 <SettingsTuning />
 <Personality />
 <CostTracking />
 <PipelineHealth />
 <LogsEventsTraces />
 <Polish />
 {/* Composition */}
 <SubstrateComposition />
 {/* Reference */}
 <AuditSchema />
 <AuditEvents />
 <RestApi />
 <DesignDecisions />
 </div>
 </div>
 </div>
);
}

// ─── Sections ────────────────────────────────────────────────────

function Intro() {
 return (
 <Section id="intro" icon="info" title="Introduction">
 <p>
 Phantom is a continuous SOC simulation platform: it generates synthetic
 security telemetry, drives MITRE ATT&CK scenario emulation, validates
 detections against XSIAM, and orchestrates red/blue workflows over
 an MCP (Model Context Protocol) tool surface. This guide documents
 Phantom&apos;s architecture for engineers extending it.
 </p>
 <p>
 Phantom is built on{" "}
 <Term>Spark Agents&apos;</Term> bundle-spec foundation: a manifest-driven
 agent definition that ships as a self-contained directory and loads
 through a 5-service Compose stack. Layered on top of that
 foundation: token-aware budgeting, lifecycle compaction, Vertex
 prompt caching, a slash-command framework, per-action audit
 logging, plan mode, lifecycle hooks, a durable task registry,
 the MCP connector state machine, cost tracking, rich tool
 metadata, the plugin system, conditional skill activation, and
 scoped subagents.
 </p>
 <SubSection icon="layers" title="Reading order">
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <Term>Foundation</Term> — service stack, manifest, data roots.
 Read first to understand the deploy shape.
 </li>
 <li>
 <Term>Chat-route Internals</Term> — the chat handler is the
 central nervous system; understand the turn lifecycle before
 reading any phase deep-dive.
 </li>
 <li>
 <Term>Subsystem sections</Term> — context &amp; sessions,
 slash &amp; plan, tasks &amp; agents, connectors &amp;
 extensions, operability. They&apos;re largely independent; read
 the ones touching the surface you&apos;re working on. Hooks
 reuse audit; subagents reuse hooks + tasks + plugins.
 </li>
 <li>
 <Term>Substrate Composition</Term> — how the building blocks
 compose. The &ldquo;why&rdquo; of the architecture.
 </li>
 <li>
 <Term>Reference</Term> — schemas, audit names, REST API,
 design decisions. Lookup material.
 </li>
 </ul>
 </SubSection>
 </Section>
);
}

function Stack() {
 return (
 <Section id="stack" icon="view_module" title="Service Stack">
 <p>
 The customer compose ships <Term>five fixed services</Term> and
 <Term> N per-instance connector containers</Term> (one per
 configured instance of any container-style connector). The
 topology below maps each service and every authenticated edge —
 colour encodes the auth class.
 </p>
 <p>
 A sixth container, <Code>phantom_tls_init</Code>, is a one-shot
 that exits within a second of <Code>compose up</Code>: it creates
 the shared TLS certificate before <Code>xlog</Code> and{" "}
 <Code>phantom-agent</Code> start (see{" "}
 <a href="#tls-proxy" className="link">TLS Proxy</a>). It is not a
 running service and appears as <Code>Exited (0)</Code> in{" "}
 <Code>docker compose ps -a</Code>.
 </p>
 <p>
 Every <Code>image:</Code> reference is{" "}
 <Term>pinned by content digest</Term> (sha256), not by version
 tag. See <a href="#image-pinning" className="link">Image Digest Pinning</a>{" "}
 for the full contract; in summary, container recreation tracks
 image content, so unchanged-byte services keep their in-memory
 state across upgrades.
 </p>

 <FullPlatformTopology />

 <SubSection icon="dns" title="Fixed services">
 <ul className="list-disc pl-5 space-y-2 text-sm">
 <li>
 <Term>xlog</Term> (container <Code>xlog</Code>) — Python 3.12,
 FastAPI + Strawberry GraphQL on :8000. Synthetic-log generator.
 Module-level <Code>workers = {}</Code> dict tracks active
 workers; restart drops every worker (no persistence by design
 — workers are simulation state, not customer data).
 </li>
 <li>
 <Term>caldera</Term> (container <Code>caldera</Code>) —
 prebuilt image, MITRE Caldera 5.3.0 red-team backend. Phantom
 drives it via the <Code>caldera.*</Code> MCP tool family. Has
 its own SQLite for adversaries / abilities / operations under
 <Code> /usr/src/app/data</Code>.
 </li>
 <li>
 <Term>phantom-browser</Term> (container <Code>phantom_browser</Code>) —
 <Code> chromedp/headless-shell</Code> sidecar exposing CDP on
 :9222 (internal-only — never published to the host network).
 The web connector connects via Playwright&apos;s{" "}
 <Code>connect_over_cdp()</Code>, never spawns its own Chromium.
 Profile-gated in compose so it doesn&apos;t auto-start unless
 a web-connector instance exists.
 </li>
 <li>
 <Term>phantom-updater</Term> (container <Code>phantom_updater</Code>) —
 Python 3.12 sidecar; drives the host&apos;s
 <Code> /var/run/docker.sock</Code> to manage per-instance
 connector containers and to perform stack-level updates. See
 the dedicated <a href="#phantom-updater" className="link">phantom-updater</a> section below.
 </li>
 <li>
 <Term>phantom-agent</Term> (container <Code>phantom_agent</Code>) —
 Next.js 15 + React 19 UI on :3000 AND embedded MCP server on
 :8080. The MCP runs as a Python subprocess of the agent&apos;s
 entrypoint, NOT a separate container — same trust boundary,
 one image to ship. Source: <Code>mcp/agent/</Code> (Next.js)
 and <Code>bundles/spark/mcp/</Code> (MCP). When TLS is enabled
 the entrypoint flips both ports to HTTPS via a TLS proxy
 (see <a href="#tls-proxy" className="link">TLS Proxy</a> below).
 </li>
 </ul>
 </SubSection>

 <SubSection icon="build" title="The source-build compose">
 <p>
 <Code>docker-compose.yml</Code> at the repo root is the development
 compose file. It builds <Code>xlog</Code>, <Code>caldera</Code>,{" "}
 <Code>phantom-updater</Code>, <Code>phantom-agent</Code> and (profile{" "}
 <Code>browser</Code>) <Code>phantom-browser</Code> from this tree
 and tags them <Code>&lt;name&gt;:local</Code>. The updater service
 follows the same contract as in the customer compose: no host
 port, <Code>MCP_TOKEN</Code> bearer on every endpoint except{" "}
 <Code>/healthz</Code>, the Docker socket and the checkout mounted
 (at <Code>/host</Code>), and the agent reaches it at{" "}
 <Code>http://phantom-updater:8090</Code>. One difference: with no
 release manifest the updater pins connector images by tag, not by
 digest. It pulls <Code>phantom-connector-&lt;id&gt;-oss</Code> from
 the registry for <Code>PHANTOM_VERSION</Code> (or{" "}
 <Code>latest</Code>), so connector containers in a source build run
 the published connector images rather than the code in the tree.
 See <Code>BUILDING.md</Code> for the <Code>.env</Code> values the
 source stack needs.
 </p>
 </SubSection>

 <SubSection icon="apps" title="Per-instance connector containers">
 <p>
 Container-style connectors get one Docker container{" "}
 <Term>per instance</Term>. See the dedicated{" "}
 <a href="#connector-containers" className="link">
 Per-instance Connector Containers
 </a>{" "}
 section for the full design.
 </p>
 </SubSection>

 <SubSection icon="lan" title="Container-to-container URLs">
 <p>
 Use container DNS names internally; <Code>localhost</Code> in
 a service refers to that service&apos;s own loopback. Operator
 <Code> .env</Code> only overrides the operator-facing fields:
 </p>
 <Pre>{`# Internal (compose DNS, not configurable):
XLOG_URL              = https://xlog:8000   # TLS-only; xlog mounts
                                            # /tls/cert.pem from shared volume
CALDERA_URL           = http://caldera:8888 # caldera TLS pending
MCP_URL               = http://localhost:8080/api/v1/stream/mcp
                        # ← localhost because MCP is a SUBPROCESS of
                        #   phantom-agent, not a separate service.

# Cross-service (operator may override in .env):
PHANTOM_AGENT_INTERNAL_URL = https://phantom-agent:8080
                             # ← phantom-updater calls back to the
                             #   agent over this URL after starting
                             #   a connector container.

# Per-instance connector containers:
container_url         = http://phantom-connector-<connector>-<instance>:9000
                        # ← stored in instance_store.db; the agent's
                        #   tool-dispatch loader uses it to route
                        #   tool calls to the right container.`}</Pre>
 </SubSection>

 <SubSection icon="key" title="Auth surface">
 <ul className="list-disc pl-5 space-y-1.5 text-sm">
 <li>
 <Term>UI auth</Term>: operator UI password is
 PBKDF2-HMAC-SHA256 hashed (600k iterations, 32-byte salt)
 and stored in the SecretStore at{" "}
 <Code>/ui/auth/&lt;username&gt;/password_hash</Code>. See{" "}
 <a href="#secret-store" className="link">Secret Store</a> for
 the at-rest encryption.
 </li>
 <li>
 <Term>MCP auth</Term>:{" "}
 <Code>Authorization: Bearer $MCP_TOKEN</Code> on every MCP
 request. <Code>MCP_TOKEN</Code> is generated at first boot and
 lives in <Code>/app/runtime/.env.generated</Code>; the agent&apos;s
 entrypoint passes it to the embedded MCP subprocess via env.
 The chat-route uses <Code>callMcpServer()</Code>{" "}
 (<Code>lib/mcp-proxy.ts</Code>) which auto-injects the bearer.
 </li>
 <li>
 <Term>External connectors</Term>: per-instance credentials in
 the SecretStore (XSIAM PAPI auth header, CALDERA red user,
 web connector cdp_url, etc). The connector state machine{" "}
 (<a href="#connector-state" className="link">below</a>)
 tracks per-instance lifecycle (connected / failed /
 needs-auth / pending / disabled).
 </li>
 <li>
 <Term>API keys</Term>:{" "}
 <Code>Authorization: Bearer phantom_ak_&lt;id&gt;_&lt;secret&gt;</Code>{" "}
 — operator-minted long-lived tokens for programmatic access.
 Hashed at rest in <Code>api_keys.db</Code> with a per-key
 random salt. See <a href="#api-keys" className="link">API Keys</a> in the user guide for the operator-facing flow.
 </li>
 </ul>
 </SubSection>
 </Section>
);
}

function ImagePinning() {
 return (
 <Section id="image-pinning" icon="verified" title="Image Digest Pinning">
 <p>
 Image references in the customer compose, the phantom-updater
 service, and per-instance connector container startup use{" "}
 <Term>content-digest pinning</Term>. Containers are recreated
 by docker compose <i>iff their image content actually changed</i>,
 not when a version label is bumped.
 </p>

 <p>
 Why this matters: caldera holds in-memory red-team operation
 state, xlog holds active streaming workers in a module-level
 dict, phantom-agent holds in-flight chat sessions and job
 history. Without digest pinning, every release would recreate
 all five containers (because the compose file&apos;s{" "}
 <Code>{`image: foo:${"${PHANTOM_VERSION}"}`}</Code>{" "}
 string changed), even when the release pipeline&apos;s conditional-rebuild
 logic had retagged caldera/xlog/browser from the previous version&apos;s
 same-byte image. The compose file&apos;s image string only
 changes when the digest changes — so unchanged-content services
 retain their state across upgrades.
 </p>

 <SubSection icon="package_2" title="The release manifest">
 <p>
 Each release publishes a{" "}
 <Code>release-manifest-vX.Y.Z.env</Code> file as a GitHub
 Release asset. The manifest enumerates every image in the
 release with its sha256 content digest:
 </p>
 <Pre>{`# Phantom image digest manifest
# Generated by the release pipeline from a release commit.

PHANTOM_VERSION=1.0.0
DIGEST_PHANTOM_AGENT=sha256:abc...
DIGEST_PHANTOM_XLOG=sha256:def...
DIGEST_PHANTOM_CALDERA=sha256:ghi...
DIGEST_PHANTOM_UPDATER=sha256:jkl...
DIGEST_PHANTOM_BROWSER=sha256:mno...
DIGEST_PHANTOM_CONNECTOR_RUNTIME=sha256:pqr...
DIGEST_PHANTOM_CONNECTOR_XLOG=sha256:stu...
DIGEST_PHANTOM_CONNECTOR_XSIAM=sha256:vwx...
DIGEST_PHANTOM_CONNECTOR_CALDERA=sha256:yz0...
DIGEST_PHANTOM_CONNECTOR_WEB=sha256:123...
DIGEST_PHANTOM_CONNECTOR_CORTEX_DOCS=sha256:456...`}</Pre>
 <p>
 Same manifest content is{" "}
 <Term>embedded into the phantom-installer binary</Term> at build
 time so the installer is fully self-contained — no runtime fetch
 from GitHub Releases needed during fresh installs. The manifest
 is also reachable as a Release asset for the{" "}
 <a href="#phantom-updater" className="link">phantom-updater</a>{" "}
 to fetch during in-app upgrades.
 </p>
 </SubSection>

 <SubSection icon="settings_ethernet" title="How the customer compose consumes it">
 <p>
 Each <Code>image:</Code> line in{" "}
 <Code>installer/docker-compose.yml</Code> uses digest-pinning
 with an explicit-invalid fallback:
 </p>
 <Pre>{`xlog:
  image: ghcr.io/\${PHANTOM_OWNER:-ayman-m}/phantom-xlog-oss@\${DIGEST_PHANTOM_XLOG:-sha256:invalid_digest_run_installer_first}`}</Pre>
 <p>
 The fallback is intentionally invalid — when an operator&apos;s
 .env is missing a <Code>DIGEST_*</Code> value, docker compose
 fails loudly with a clear hint pointing at the installer. Silent
 fallback to a wrong image is the failure mode this design
 explicitly prevents.
 </p>
 </SubSection>

 <SubSection icon="rocket_launch" title="Install / upgrade flow">
 <ul className="list-disc pl-5 space-y-2 text-sm">
 <li>
 <Term>Fresh install.</Term> Customer downloads{" "}
 <Code>phantom-installer</Code> for vX.Y.Z, runs{" "}
 <Code>sudo ./phantom-installer</Code>. Installer reads its
 embedded manifest and writes{" "}
 <Code>PHANTOM_VERSION=X.Y.Z</Code>{" "}
 plus 10 <Code>DIGEST_PHANTOM_*</Code> lines into{" "}
 <Code>/opt/phantom/.env</Code>. <Code>docker compose pull</Code>{" "}
 +{" "}
 <Code>up -d</Code> launches with digest-pinned images.
 </li>
 <li>
 <Term>Upgrade (in-app).</Term> Operator clicks &quot;Update
 now&quot; in the UI sidebar. The agent proxies to{" "}
 phantom-updater&apos;s <Code>POST /api/v1/update</Code>;
 updater fetches the latest GitHub Release&apos;s manifest,
 compares each service&apos;s current digest vs the manifest&apos;s
 target, pulls only changed images, applies the manifest to{" "}
 <Code>/host/.env</Code>, and runs{" "}
 <Code>docker compose up -d --no-deps &lt;changed services&gt;</Code>.
 Compose sees changed digests as spec changes for the affected
 services only — selective recreation falls out for free.
 </li>
 <li>
 <Term>Upgrade (re-run installer).</Term> Same flow as fresh
 install, but the installer detects the existing{" "}
 <Code>/opt/phantom/.env</Code>, preserves secrets / KEK,
 strips stale{" "}
 <Code>PHANTOM_VERSION + DIGEST_PHANTOM_*</Code> lines, appends
 the new manifest. Each phantom-installer binary is{" "}
 <Term>sealed to one version</Term> (its embedded manifest is
 only valid for that version) — to install vN, download the
 vN binary.
 </li>
 <li>
 <Term>Upgrades retain in-memory state.</Term> Subsequent
 minor-version upgrades retain in-memory state for unchanged
 services — docker compose only recreates services whose
 image digest actually changed.
 </li>
 </ul>
 </SubSection>

 <SubSection icon="lan" title="Per-instance connector containers">
 <p>
 Per-instance connector containers (see{" "}
 <a href="#connector-containers" className="link">Connector Containers</a>)
 also use digest pinning. <Code>_connector_image_ref()</Code> in{" "}
 <Code>updater/src/main.py</Code> reads{" "}
 <Code>DIGEST_PHANTOM_CONNECTOR_&lt;ID&gt;</Code>{" "}
 (forwarded from{" "}
 <Code>/host/.env</Code> through the updater&apos;s{" "}
 <Code>environment:</Code> block) and constructs the image ref as{" "}
 <Code>ghcr.io/.../phantom-connector-&lt;id&gt;@sha256:...</Code>.
 Without the env var, the updater falls back to tag pinning with
 a loud warning — observable in{" "}
 <Code>/observability/connectors</Code> as a yellow{" "}
 &quot;tag (legacy)&quot; badge per affected instance.
 </p>
 </SubSection>

 <SubSection icon="visibility" title="Operator visibility">
 <p>
 <Term>About modal:</Term> the agent&apos;s <Code>/api/agent/version</Code>{" "}
 endpoint returns <Code>{`{ version, digests: {...} }`}</Code>; the About
 modal&apos;s release-history section shows the running version
 plus an &quot;Image versions&quot; expandable with the 5
 stack-tier digests.
 </p>
 <p>
 <Term>Observability panel:</Term>{" "}
 <a href="#observability-connectors" className="link">/observability/connectors</a>{" "}
 has an Image-Digests section above the connector state-machine
 list. Two sub-tables — stack tier (5 rows) and per-instance
 connectors (variable). Pinning-mode badge on every row.
 </p>
 <p>
 <Term>Comprehensive endpoint:</Term>{" "}
 <Code>GET /api/agent/digests</Code> returns the full picture:
 stack-tier digest list + per-instance connector digest list (proxied
 to phantom-updater&apos;s <Code>/api/v1/connectors/digests</Code>).
 Used by the observability panel; also the canonical
 incident-response endpoint for &quot;exactly which image bytes is
 each running container?&quot;.
 </p>
 </SubSection>
 </Section>
 );
}

function TlsProxy() {
 return (
 <Section id="tls-proxy" icon="lock" title="TLS Proxy & Entrypoint">
 <p>
 The phantom-agent container ships with a tiny Node TLS proxy that
 fronts both the Next.js UI (:3000) and the embedded MCP (:8080)
 with HTTPS when <Code>PHANTOM_TLS_ENABLED=1</Code> is set. The
 entrypoint script (<Code>mcp/agent/entrypoint.sh</Code>) decides
 at boot whether to hand sockets to Next.js / Uvicorn directly
 (TLS off) or to start the proxy and route through it (TLS on).
 Operators flip the switch in <Code>.env</Code>; no rebuild needed.
 </p>

 <SubSection icon="settings_input_component" title="Boot decision tree">
 <Pre>{`PHANTOM_TLS_ENABLED unset / "0"
  → Next.js binds :3000 directly (HTTP)
  → Uvicorn (MCP) binds :8080 directly (HTTP)
  → No tls-proxy.js process

PHANTOM_TLS_ENABLED = "1"
  ├─ Cert + key present at /tls/cert.pem + /tls/key.pem
  │   → use as-is (in the compose stacks this is always the case:
  │     phantom-tls-init created them before anything else started)
  └─ Else (the image runs without the init service)
      → entrypoint runs /app/tls-init.sh: self-signed via openssl into /tls/,
        PHANTOM_AUTO_TLS=1, log "no TLS cert ... generating self-signed cert"
      → if openssl fails the script exits non-zero with openssl's message and
        the container stops (fail-fast)

  → Uvicorn binds 127.0.0.1:8080 (loopback, HTTPS using same cert)
  → Next.js binds 127.0.0.1:3001 (loopback, plain HTTP)
  → tls-proxy.js binds 0.0.0.0:3000 (HTTPS) → 127.0.0.1:3001
  → tls-proxy.js binds 0.0.0.0:8080 (HTTPS) → 127.0.0.1:8080
                                              (intra-process)`}</Pre>
 </SubSection>

 <SubSection icon="route" title="Why a proxy and not Next.js HTTPS directly">
 <p>
 Next.js production server has no native HTTPS option;{" "}
 <Code>next start</Code> is HTTP-only by design (its docs assume
 you put a real load balancer in front). Adding a Node-level
 TLS wrapper inside the container is cheaper than dragging in
 nginx, has no separate process to monitor, and stays under the
 same restart policy as everything else.
 </p>
 <p>
 The proxy is ~80 lines of Node — it does TLS termination, then
 a streaming pipe to the inner port. No buffering, no header
 rewrites except <Code>X-Forwarded-Proto</Code>, <Code>X-Forwarded-Port</Code> and <Code>X-Forwarded-For</Code> (the proxy appends the real socket address to whatever the client sent, so the LAST entry is the one to trust; the auth rate limits key on it). SSE flows from
 the chat handler still stream end-to-end because the proxy
 uses Node&apos;s streams, not <Code>fetch()</Code>.
 </p>
 </SubSection>

 <SubSection icon="schedule" title="Who creates the certificate, and boot order">
 <p>
 The shared <Code>phantom_tls</Code> volume holds one cert + key
 pair, and <Code>/app/tls-init.sh</Code> (in the agent image) is the
 only code that creates it. It writes nothing when a pair is already
 there, so an operator-supplied certificate is never replaced, and it
 renames the files into place so a reader never sees half a pair.
 </p>
 <p>
 In both compose files the one-shot <Code>phantom-tls-init</Code>{" "}
 service runs that script and exits, and <Code>xlog</Code> and{" "}
 <Code>phantom-agent</Code> each declare{" "}
 <Code>depends_on: phantom-tls-init: service_completed_successfully</Code>.
 xlog reads <Code>/tls</Code> once, at process start, and serves
 HTTPS only if the pair is there, so it has to exist before it starts. The agent&apos;s own entrypoint calls the same script as
 a no-op safety net for deployments that run the image without the
 init service. Nothing that writes the certificate may wait on a
 service that reads it: the agent waits for xlog to be healthy, so
 letting the agent create the certificate left xlog on plain HTTP on
 every fresh install.
 </p>
 </SubSection>

 <SubSection icon="warning" title="Self-signed cert and PHANTOM_TLS_VERIFY">
 <p>
 The auto-generated certificate is self-signed (written by{" "}
 <Code>tls-init.sh</Code>; <Code>PHANTOM_AUTO_TLS=1</Code> marks an
 agent boot that had to create it itself). Internal callers (phantom-updater calling
 back to the agent, the agent&apos;s own loopback healthchecks)
 then need to skip chain verification. The convention:{" "}
 <Code>PHANTOM_TLS_VERIFY</Code> with a value of <Code>0</Code>{" "}
 means &quot;skip verify&quot;; anything else means enforce.
 The agent&apos;s entrypoint sets it on every internal client
 (Python httpx, Node fetch wrappers) when the self-signed mode
 is active.
 </p>
 <p>
 Production-grade: replace <Code>/tls/cert.pem</Code> +{" "}
 <Code>/tls/key.pem</Code> with a CA-signed pair and unset{" "}
 <Code>PHANTOM_TLS_VERIFY</Code>. The proxy serves the new cert
 on next container restart; no code change.
 </p>
 </SubSection>

 <SubSection icon="bug_report" title="Operator pitfall: healthcheck mismatch">
 <p>
 The dev compose at <Code>$VM_REMOTE_REPO/docker-compose.yml</Code>{" "}
 originally had a <Code>curl http://localhost:3000</Code>{" "}
 healthcheck. When the entrypoint flips to TLS, that probe
 returns curl exit 52 (&quot;empty reply from server&quot;)
 because the port is now HTTPS. The container is healthy but
 reports unhealthy. Fix: use{" "}
 <Code>curl -ksf https://localhost:3000/...</Code> in the
 healthcheck (the <Code>-k</Code> skips chain validation
 since we&apos;re inside the container talking to ourselves).
 </p>
 </SubSection>
 </Section>
);
}

function PhantomUpdater() {
 return (
 <Section id="phantom-updater" icon="autorenew" title="phantom-updater Service">
 <p>
 phantom-updater is a sidecar container with one job: drive the
 host&apos;s docker daemon for lifecycle operations the agent
 itself can&apos;t safely perform on its own image. Two surfaces:
 stack-level updates (pull new image versions, recreate services)
 and per-instance connector containers (start/stop/restart one
 container per configured instance of any container-style
 connector).
 </p>

 <SubSection icon="approval" title="Why a separate container">
 <p>
 During a stack-level update, phantom-agent&apos;s container is
 destroyed and replaced. If the update logic lived inside that
 image, the operator&apos;s progress stream would die mid-update.
 Living in its own container — its own image, its own version —
 means the updater keeps streaming progress even when the agent
 restarts. The updater never updates itself; if its own image
 needs rotating, that&apos;s a manual SSH job (a future{" "}
 <Code>update-updater.sh</Code> ships with the install kit for
 those rare cases).
 </p>
 <p>
 Same trust boundary as the agent — the updater binds the same{" "}
 <Code>MCP_TOKEN</Code> bearer on every authenticated route.
 What it has that the agent doesn&apos;t: a mount of{" "}
 <Code>/var/run/docker.sock</Code> (root-equivalent on the host)
 and a read-only mount of the operator install dir at{" "}
 <Code>/host</Code> so it can shell out to{" "}
 <Code>docker compose</Code> with the operator&apos;s pinned env.
 </p>
 </SubSection>

 <SubSection icon="api" title="Endpoints">
 <Pre>{`# All except /healthz require Authorization: Bearer $MCP_TOKEN

GET    /healthz                                       # docker healthcheck
GET    /api/v1/version/current                        # running image versions
GET    /api/v1/version/check                          # diff vs GHCR latest
GET    /api/v1/update/status                          # {in_progress: bool}
POST   /api/v1/update                                 # SSE stream of progress

# Per-instance connector containers
POST   /api/v1/connectors/{id}/instances/{name}/start
POST   /api/v1/connectors/{id}/instances/{name}/stop
POST   /api/v1/connectors/{id}/instances/{name}/restart
GET    /api/v1/connectors/{id}/instances/{name}/status

# Reconciliation — sync running containers to instance store
POST   /api/v1/connectors/reconcile`}</Pre>
 <p>
 <Code>stop</Code>, <Code>status</Code> and <Code>restart</Code> work for uploaded (user) connectors as well as bundled ones. They act on the container <Code>phantom-connector-&lt;id&gt;-&lt;name&gt;</Code> only when its own labels say it is a connector container for that id (<Code>phantom.role=connector-runtime</Code>, <Code>phantom.connector_id</Code>); anything else with that name is refused with a 409. <Code>restart</Code> recreates a bundled connector from its pinned digest and an uploaded one from the image it was running. <Code>start</Code> of an uploaded connector takes its image from <Code>image_ref</Code>, and the periodic reconcile leaves uploaded connectors alone because they have no pin.
 </p>
 <p>
 <Code>DELETE /api/v1/instances/&#123;id&#125;</Code> on the agent stops the container first and reports it in the response as <Code>container_stop</Code> (<Code>stopped</Code>, <Code>not_running</Code> or <Code>failed</Code>; <Code>null</Code> when the connector has no container). The instance is deleted either way, and a <Code>failed</Code> stop is logged as a warning because the container may still be running.
 </p>
 </SubSection>

 <SubSection icon="sync" title="Digest-drift reconciliation (startup + periodic)">
 <p>
 Per-instance connector containers are managed dynamically by phantom-updater — they are NOT in <Code>docker-compose.yml</Code>, so a <Code>docker compose up -d</Code> never touches them. When an install or upgrade updates a connector&apos;s pinned digest in <Code>/host/connector-digests.env</Code>, the already-running container keeps its old image until phantom-updater recreates it.
 </p>
 <p>
 phantom-updater reconciles that drift automatically: once ~30s after startup, and <strong>on a periodic loop</strong> (default every 5 minutes, override via <Code>PHANTOM_UPDATER_RECONCILE_INTERVAL_S</Code>). Each pass compares every <Code>phantom-connector-*</Code> container&apos;s running digest to its pin and recreates only the divergent ones (sequential, per-container error isolation). The periodic loop matters because phantom-updater rarely restarts, so a startup-only reconcile would leave a pin that changes between restarts unapplied. Operators can force a synchronous pass with <Code>POST /api/v1/connectors/reconcile/digests</Code>.
 </p>
 <p>
 A container is identified from its <Code>phantom.connector_id</Code> / <Code>phantom.instance_name</Code> / <Code>phantom.instance_id</Code> labels (containers started by an older updater fall back to matching the name against the known ids, longest first, so <Code>cortex-xdr</Code> is never read as <Code>cortex</Code>). Its running digest is the content digest of the image it runs, compared with the pin <strong>whatever registry owner the image was pulled under</strong>; when the image object has been pruned the digest in the container&apos;s own image reference is used. A container whose digest cannot be determined is reported as <Code>failed</Code> with the reason, never as unchanged, and an uploaded connector has no pin so it is left alone. The sweep examines every container independently, so one unreadable container does not stop it.
 </p>
 <p>
 <Code>GET /api/v1/connectors/digests</Code> (behind <Code>/api/agent/digests</Code>) returns, per container, the running <Code>digest</Code>, the <Code>pinned_digest</Code>, a <Code>drift</Code> flag and the <Code>image_pull</Code> outcome. <Code>/observability/connectors</Code> shows a <em>drifted</em> chip when a container runs something other than its pin and a <em>cached image</em> chip when its registry pull failed.
 </p>
 </SubSection>

 <SubSection icon="cached" title="Image-pull retry policy">
 <p>
 The pull-with-retry helper does up to 5 attempts with
 exponential backoff (1s → 2s → 4s → 8s → 16s, capped at 30s
 total). Each <Code>docker pull</Code> failure logs at WARNING.
 After 5 attempts the helper falls back to a local-cache check —
 if a previous pull seeded the image, the container starts from
 cache and the response includes{" "}
 <Code>image_pull: &quot;cached&quot;</Code> so audit can
 distinguish &quot;customer is offline today&quot; from{" "}
 &quot;customer has the latest&quot;.
 </p>
 <p>
 A registry <em>authentication</em> failure (401/403, &quot;denied&quot;, &quot;unauthorized&quot;) is not retried: the package is not public or the image name is wrong, and waiting does not change that. The helper logs one ERROR saying so, then takes the same cache fallback. The response carries <Code>image_pull_error</Code> with the reason, and the container is labelled <Code>phantom.image_pull=cached</Code> so <Code>/observability/connectors</Code> can show it. With neither a registry nor a cached copy the start fails with a 502 that says the registry denied access.
 </p>
 </SubSection>

 <SubSection icon="callback" title="Update flow → operator visibility">
 <p>
 An update is an SSE stream from{" "}
 <Code>POST /api/v1/update</Code>. The chat UI&apos;s About
 modal renders a progress bar while the stream is active; the
 sidebar version chip flips green only after every service is
 healthy. Failures are surfaced verbatim (image-pull error
 string, healthcheck timeout, etc.) — no silent retries on
 long-tail failures. Recovery is a manual SSH job; v1 has no
 rollback.
 </p>
 </SubSection>
 </Section>
);
}

function ConnectorContainers() {
 return (
 <Section id="connector-containers" icon="apps" title="Per-instance Connector Containers">
 <p>
 <strong>Universal container-mode.</strong> Every connector — all
 6 in the bundle (caldera, cortex-content, cortex-docs, web,
 xlog, xsiam) plus any user-uploaded connectors — runs as a
 per-instance container. The agent&apos;s connector_loader is a
 routing proxy that forwards tool calls over MCP-over-HTTP. The
 schema enum is tightened to <Code>[&quot;container&quot;]</Code>{" "}
 only so a future connector.yaml drift can&apos;t reintroduce
 in-process dispatch paths.
 </p>
 <p>
 Per-instance container images are <Term>digest-pinned</Term> at
 startup (matching the stack-tier services). The phantom-updater
 reads <Code>DIGEST_PHANTOM_CONNECTOR_&lt;ID&gt;</Code> from its{" "}
 environment when starting a new instance container, so the
 instance is reproducibly bound to a specific image-byte hash.
 See{" "}
 <a href="#image-pinning" className="link">Image Digest Pinning</a>{" "}
 for the full contract; the &quot;tag fallback&quot; behaviour
 surfaces as a yellow{" "}
 &quot;tag (legacy)&quot; badge in{" "}
 <Code>/observability/connectors</Code>.
 </p>

 <SubSection icon="why" title="Motivation">
 <ul className="list-disc pl-5 space-y-1.5 text-sm">
 <li>
 <Term>Crash isolation</Term>: a Playwright leak in the web
 connector takes down one connector container, which docker
 restarts, instead of the whole agent process.
 </li>
 <li>
 <Term>Resource isolation</Term>: a runaway xlog scenario can&apos;t
 starve the agent&apos;s chat handler of CPU because they run
 in different cgroups.
 </li>
 <li>
 <Term>Independent versioning</Term>: a connector image can
 ship without rebuilding the agent. Useful when a third-party
 publishes a connector and the operator wants to update it
 without touching the rest.
 </li>
 <li>
 <Term>Foreign runtimes</Term>: a future Node-based connector
 can ship as its own image without forcing the agent to embed
 Node. The runtime contract is HTTP, not Python imports.
 </li>
 </ul>
 </SubSection>

 <SubSection icon="schema" title="Naming + addressing">
 <Pre>{`# Container name (deterministic):
phantom-connector-<connector_id>-<instance_name>
   # e.g. phantom-connector-web-acme

# Image tag:
ghcr.io/ayman-m/phantom-connector-<id>:<VERSION>
   # VERSION = $PHANTOM_VERSION (the customer's pinned release)

# Compose-network DNS:
http://phantom-connector-<id>-<name>:9000
   # Stored in instance_store.db.container_url after the
   # updater calls back POST /api/v1/instances/{id}/container_url
   # The agent's tool-dispatch loader reads container_url at tool
   # call time and proxies via the streamable-HTTP MCP transport.`}</Pre>
 </SubSection>

 <SubSection icon="sequence" title="Lifecycle on instance create">
 <Pre>{`Operator clicks "Create Instance" on /connectors
                ↓
Next.js POST /api/v1/instances → MCP creates instance row
                ↓
MCP read connector.yaml.runtimeMapping.style
   ├─ "module"    → register tools in-process (legacy path)
   └─ "container" → POST /api/v1/connectors/<id>/instances/<name>/start
                    on phantom-updater
                                       ↓
                    updater.docker_run(image, env, network=phantom_default,
                                       volume=phantom_mcp_data:/app/data:ro)
                                       ↓
                    container boots; entrypoint loads instance config from
                    the read-only data volume + decrypts secrets via the
                    SecretStoreReader (PHANTOM_SECRET_KEK from env)
                                       ↓
                    FastMCP server up on :9000; updater POSTs back to
                    /api/v1/instances/{id}/container_url with the URL
                                       ↓
                    agent's set_container_url handler updates the row +
                    triggers reload_tools_now() to rebuild proxy closures
                                       ↓
                    next tool call routes through the proxy, hits the
                    container's MCP, returns the result`}</Pre>
 </SubSection>

 <SubSection icon="signature_pen" title="Synthesized proxy signatures">
 <p>
 FastMCP rejects callables with <Code>**kwargs</Code> — it
 introspects the function signature to build the JSON schema
 for the tool. The container-mode loader can&apos;t use a
 generic <Code>def proxy(**args)</Code> shim; instead it
 synthesizes a Python function whose signature mirrors the
 connector.yaml <Code>args</Code> declaration, then forwards
 the call to the container&apos;s MCP. See{" "}
 <Code>bundles/spark/mcp/src/usecase/connector_loader.py:_build_container_proxy</Code>{" "}
 — uses <Code>compile() + exec</Code> with bundle-immutable
 source (paths from <Code>connector.yaml</Code>, no operator
 input) to produce the function with the right signature.
 </p>
 </SubSection>

 <SubSection icon="security" title="Trust model">
 <ul className="list-disc pl-5 space-y-1.5 text-sm">
 <li>
 <Term>Container only sees its own instance</Term>. The data
 volume is mounted <Code>:ro</Code> (read-only) and the
 container only reads the row matching its{" "}
 <Code>INSTANCE_ID</Code> env var. Cross-instance reads
 require the agent itself.
 </li>
 <li>
 <Term>Same KEK</Term>. The container needs{" "}
 <Code>PHANTOM_SECRET_KEK</Code> in env to decrypt the
 instance&apos;s secrets. phantom-updater inherits it from
 the host&apos;s <Code>.env</Code> and passes it through.
 </li>
 <li>
 <Term>No outbound to operator network</Term> by default. The
 container is on the compose network only; if a connector
 needs internet (e.g. xsiam → tenant API), that&apos;s
 explicit operator config in the instance.
 </li>
 </ul>
 </SubSection>

 </Section>
);
}

function Manifest() {
 return (
 <Section id="manifest" icon="package_2" title="Manifest & Bundle">
 <p>
 Phantom is a Spark v1.2 bundle. The bundle root contains a{" "}
 <Code>manifest.yaml</Code> declaring identity, model requirements,
 connectors, settings, audit events, and capabilities. The manifest
 is the contract between the bundle and its runtime.
 </p>
 <SubSection icon="folder" title="Bundle layout">
 <Pre>{`bundles/spark/
├── manifest.yaml # Bundle contract — identity, models,
│ # connectors, audit events, etc.
├── mcp/ # phantom-mcp service source
│ ├── src/
│ │ ├── main.py # MCP boot + service wiring
│ │ ├── api/ # REST routes (audit, hooks, tasks, etc.)
│ │ └── usecase/ # Stores + loaders + business logic
│ ├── skills/ # Bundle-default skills (markdown)
│ ├── scenarios/ready/ # Bundle-default scenarios (JSON)
│ └── tests/
├── plugins/ # Filesystem-discovered plugin tree
│ └── example-vendor/
│ ├── manifest.yaml # Plugin contract — agents, skills, seeds
│ ├── skills/
│ └── agents/ # Plugin-contributed AgentDefinitions
└── connectors/ # Tool-providing connector source`}</Pre>
 </SubSection>

 <SubSection icon="article" title="Key manifest blocks">
 <ul className="list-disc pl-5 space-y-1.5 text-sm">
 <li>
 <Code>audit.events</Code> — Closed list of audit action names
 this bundle emits. The current set covers chat lifecycle
 (<Code>chat_compaction_*</Code>,{" "}
 <Code>chat_context_warning</Code>,{" "}
 <Code>chat_cache_hit</Code>,{" "}
 <Code>chat_turn_cost</Code>,{" "}
 <Code>chat_plan_*</Code>,{" "}
 <Code>chat_subagent_*</Code>), plus subsystem events
 (<Code>hook_*</Code>, <Code>task_*</Code>,{" "}
 <Code>connector_*</Code>, <Code>plugins_reloaded</Code>,{" "}
 <Code>agent_definition_*</Code>).
 </li>
 <li>
 <Code>approvals.humanRequired[]</Code> — Tier-2+ tools the
 chat-route gates with inline approval cards.{" "}
 <Code>lib/approvals-config.ts:isToolGated</Code> reads this
 list at every tool dispatch.
 </li>
 <li>
 <Code>toolConnectors[]</Code> — Connector ids + paths the
 connector_loader registers tools from. tracks
 per-connector runtime state alongside.
 </li>
 <li>
 <Code>settings.overridable[]</Code> — Closed list of operator-
 tunable settings. Each goes through SqliteSettingsStore +{" "}
 <Code>/api/v1/settings</Code>. (Personality lives in a
 separate store)
 </li>
 </ul>
 </SubSection>
 </Section>
);
}

function DataRoots() {
 return (
 <Section id="data-roots" icon="database" title="Data Roots">
 <p>
 Spark&apos;s invariant: <Term>bundle_root is read-only; data_root
 is mutable</Term>. Phantom honors this strictly. Every store writes
 to <Code>/app/data/</Code>; bundle files (manifest, skills,
 scenarios, plugin manifests) are read-only at runtime. The diagram
 below shows every store, the audit log they all write into, and
 the observability surfaces derived from it.
 </p>

 <PersistentStores />

 <SubSection icon="folder_open" title="Stores under /app/data/">
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <Code>sessions.db</Code> — Chat sessions + persisted messages.
 Sessions can be ended (audit-friendly soft delete) or hard-
 deleted. Also stores <Code>compaction-checkpoint</Code> and{" "}
 <Code>plan-proposed</Code> system messages alongside user/
 assistant turns.
 </li>
 <li>
 <Code>audit.db</Code> — Append-only audit log. Index on{" "}
 <Code>(action, ts, target, actor, trigger)</Code>.{" "}
 <Code>SqliteAuditLog.record()</Code> never raises — failures
 log a warning and continue.
 </li>
 <li>
 <Code>memory.db</Code> — Vector-indexed memory store with MMR
 reranking, temporal decay, and an FTS5 hybrid path for literal
 keyword promotion.
 </li>
 <li>
 <Code>tasks.db</Code> — Task registry. State machine:
 pending → running → succeeded | failed | aborted.{" "}
 <Code>is_aborted(id)</Code> is the cheap polling primitive
 workers consult to honour cancel.
 </li>
 <li>
 <Code>hooks.db</Code> — Hook definitions. Multi-row, indexed
 on event + enabled. Hooks are JSON blobs in{" "}
 <Code>payload_json</Code> for forward-compat.
 </li>
 <li>
 <Code>connector_state.db</Code> — Per-connector state-machine
 row (enabled, disabled, failed, auth_required, probed). Tiny
 table; one row per configured connector.
 </li>
 <li>
 <Code>agent_definitions.db</Code> — Agent registry. Multi-row,
 unique on name. <Code>origin</Code> column tracks provenance
 (operator | plugin:name | builtin).
 </li>
 <li>
 <Code>personality.db</Code> — Single-row personality store
 with a last-N-versions history table. Holds the system-prompt
 customizations plus tuning fields (compaction threshold,
 cache toggle, memory-rank lambdas).
 </li>
 <li>
 <Code>setup.json</Code> — Free-form key/value (UI auth,
 provider keys, etc). Migrated into typed stores incrementally.
 </li>
 </ul>
 </SubSection>
 </Section>
);
}

// ─── Chat-route internals ─────────────────────────────────────────

function ChatLifecycle() {
 return (
 <Section id="chat-lifecycle" icon="loop" title="Chat Turn Lifecycle">
 <p>
 Every chat turn flows through{" "}
 <Code>app/api/chat/route.ts:POST()</Code>. The handler is a
 ReadableStream with SSE event emission. The diagram below shows
 the 12 numbered steps mapped across the four actors (browser,
 agent, MCP, model), with hook fire-sites flagged on the left
 margin and representative SSE events on the right.
 </p>

 <ChatTurnLifecycle />

 <SubSection icon="play_arrow" title="1. Entry">
 <p>
 Parse body (<Code>message</Code>, <Code>session_id?</Code>,{" "}
 <Code>model?</Code>, <Code>provider?</Code>). Resolve sessionId
 (lazy-create if not provided). Emit <Code>meta</Code> SSE event.
 </p>
 <p className="text-sm leading-relaxed mt-2">
 <strong>Alternative entry path — direct tool invocation:</strong>{" "}
 chat input starting with <Code>^toolname args</Code> bypasses
 this route entirely. The chat hook (
 <Code>components/chat/use-chat.ts</Code>) detects the prefix,
 parses the command, and POSTs to{" "}
 <Code>/api/agent/tool/call</Code> instead &mdash; which talks to
 the MCP&apos;s JSON-RPC <Code>tools/call</Code> directly with no
 model, no system prompt, no planner. Critical property: works
 even when no provider is configured. The result renders as a
 JSON code block in the transcript with a distinct visual style
 from chat bubbles. See{" "}
 <Code>app/api/agent/tool/call/route.ts</Code> for the JSON-RPC
 session-management details.
 </p>
 </SubSection>
 <SubSection icon="event_available" title="2. Lifecycle hooks">
 <p>
 Fire <Code>RunStart</Code> hook (may deny). Fire{" "}
 <Code>UserPromptSubmit</Code> hook (may deny, redact, or inject
 context). The injected context becomes a synthetic{" "}
 <Code>user</Code> message prepended to <Code>contents</Code>.
 </p>
 </SubSection>
 <SubSection icon="save" title="3. Persist user message">
 <p>
 <Code>safePersist(sessionId, role:&quot;user&quot;, content)</Code>{" "}
 writes
 the inbound message before the model loop. Doing it here means a
 partial / crashed turn still leaves a record of what was asked.
 </p>
 </SubSection>
 <SubSection icon="alt_route" title="4. Slash command dispatch">
 <p>
 <Code>parseSlashCommand(message)</Code> returns{" "}
 <Code>{`{ name, args }`}</Code> or null. If non-null, route to{" "}
 <Code>dispatchSlashCommand</Code> which finds the SlashCommand
 handler in <Code>SLASH_COMMANDS</Code> and runs it. Slash
 handlers own their controller close — the framework wraps in
 try-catch but doesn&apos;t auto-close.
 </p>
 </SubSection>
 <SubSection icon="settings_input_component" title="5. Tool catalog assembly">
 <p>
 <Code>getGeminiTools(mcpClient)</Code> lists MCP tools, sanitizes
 their schemas for Gemini, appends the synthetic{" "}
 <Code>subagent_create</Code> tool spec. Cached for
 5 minutes via in-process map.
 </p>
 </SubSection>
 <SubSection id="permission-policies" icon="shield_lock" title="5b. Permission policies">
 <p>
 Each job can carry a declarative permission policy that the
 chat-route&apos;s tool-dispatch loop evaluates before each tool
 fires. The policy is a JSON blob stored in{" "}
 <Code>jobs.permission_policy_json</Code>; the scheduler threads
 it into <Code>body.permission_policy</Code> on the chat dispatch.
 Shape:
 </p>
 <Pre>{`{
 "allowed_tools":     ["pattern", ...],   // whitelist when non-empty
 "denied_tools":      ["pattern", ...],   // blacklist
 "require_approval":  ["pattern", ...]    // force approval card
}`}</Pre>
 <p>
 Patterns are globs (same as <Code>HookMatcher.toolGlob</Code>):{" "}
 <Code>*</Code> matches any sequence, <Code>?</Code> matches one
 character, comma-separated lists are OR. Evaluation precedence
 (narrowest wins):
 </p>
 <ol className="list-decimal pl-5 space-y-1 text-sm">
 <li>
 <Code>denied_tools</Code> match → decision is <Code>deny</Code>;
 the chat-route synthesizes a tool-error response, emits a{" "}
 <Code>tool_call</Code> SSE event with{" "}
 <Code>status: &quot;denied_by_policy&quot;</Code>, fires a{" "}
 <Code>tool_denied_by_policy</Code> audit event.
 </li>
 <li>
 <Code>require_approval</Code> match → decision is{" "}
 <Code>ask</Code>; falls through to the standard inline approval
 card path. The scheduler&apos;s <Code>bypass_approvals=true</Code>{" "}
 does NOT override <Code>ask</Code> — policy intent wins.
 </li>
 <li>
 <Code>allowed_tools</Code> non-empty AND no match → decision is{" "}
 <Code>deny</Code> (whitelist mode).
 </li>
 <li>
 Otherwise → decision is <Code>allow</Code>.
 </li>
 </ol>
 <p style={{ marginTop: 8 }}>
 Empty policy (all three lists empty, or no policy at all) is
 fully permissive — backwards-compatible default. The operator
 opts INTO restrictions on a per-job basis.
 </p>
 <p style={{ marginTop: 8 }}>
 <strong>Not a security boundary by itself.</strong> The MCP-side
 approval gate (<Code>humanRequired</Code> in the bundle
 manifest) remains the authoritative defense for destructive
 tools. Permission policies are an operator-facing scope check
 that runs BEFORE the approval gate — defense in depth. A
 motivated attacker who compromises the chat-route bypasses
 both; that&apos;s a security model problem, not a policy
 problem.
 </p>
 </SubSection>
 <SubSection id="model-routing" icon="psychology" title="6. Model resolution chain">
 <p>
 <Code>effectiveRequestedModel = requestedModel ?? loadSessionPreferredModel(sessionId) ?? null</Code>
. Header dropdown wins (operator override); session pref next
 (set via <Code>/model</Code> slash); runtime default is the
 fallback inside <Code>resolveModelName</Code>.
 </p>
 <p style={{ marginTop: 8 }}>
 <strong>Per-job model override.</strong> When the scheduler
 dispatches a chat-action job, the request body includes{" "}
 <Code>body.model = job.model_id</Code> if the job has an
 override set. The chat route reads that field exactly the
 same way it reads the header-dropdown override — it shows up
 as <Code>requestedModel</Code> and flows into{" "}
 <Code>resolveModelName(modelOverride, runtimeConfig)</Code>{" "}
 with no new code path. Resolution chain in priority order:
 per-request <Code>body.model</Code> (operator header pick OR
 scheduler-driven job override) → session pref → runtime
 default → hardcoded fallback. Jobs persist their override in{" "}
 <Code>jobs.model_id TEXT</Code>; <Code>NULL</Code> means
 &ldquo;use the runtime default at dispatch time.&rdquo;
 </p>
 <p style={{ marginTop: 8 }}>
 The companion <Code>thinking_enabled</Code> column +{" "}
 <Code>body.thinking</Code> field is plumbed end-to-end: the
 scheduler adds <Code>thinking: true</Code> to the dispatch
 body when the job has it set, and the chat route maps it to
 the Gemini call&apos;s <Code>thinkingConfig</Code>{" "}
 (<Code>thinkingBudget: -1</Code>,{" "}
 <Code>includeThoughts: true</Code>). Thinking is on by
 default: only an explicit <Code>thinking: false</Code> in the
 request body disables it, so a job with the toggle off still
 runs with the default. Models without thinking support ignore
 the setting.
 </p>
 </SubSection>
 <SubSection icon="history_edu" title="7. History load (+ auto-compact)">
 <p>
 <Code>loadSessionHistory(sessionId, model, autoCompactionHooks)</Code>
 {" "}fetches the message history (300-message cap from MCP),
 token-budget-walks newest-to-oldest, and either truncates or
 (if auto-compaction hooks are wired) summarizes the dropped
 portion via Gemini and persists a checkpoint. Output is a list
 of <Code>GeminiContent</Code> messages.
 </p>
 </SubSection>
 <SubSection icon="security" title="8. Context-window guard">
 <p>
 Estimate input + reserved-output tokens vs the model&apos;s
 context cap. If &gt;= 99%: block with structured error. If &gt;=
 90%: emit <Code>context_warning</Code> SSE event AND write a{" "}
 <Code>chat_context_warning</Code> audit row.
 </p>
 </SubSection>
 <SubSection icon="rocket_launch" title="9. Initial Gemini call">
 <p>
 <Code>callGemini(contents, tools, runtimeConfig, actionPolicy, model)</Code>
 {" "}runs through the API-key path or falls through to Vertex.
 Prompt caching sits inside the Vertex path: if{" "}
 <Code>PHANTOM_VERTEX_CACHE=1</Code>, the system prompt is
 cached and referenced via <Code>cachedContent</Code>.
 </p>
 </SubSection>
 <SubSection icon="sell" title="10. Cost recording">
 <p>
 <Code>extractAndRecordCost(response,...)</Code> reads{" "}
 <Code>usageMetadata</Code>, applies the per-model rate from{" "}
 <Code>lib/model-pricing.ts</Code>, writes a{" "}
 <Code>chat_turn_cost</Code> audit row with input/cached/output
 token counts and USD cost components. Returns the cost so
 turn-totals can be summed across follow-up calls.
 </p>
 </SubSection>
 <SubSection icon="loop" title="11. Tool-call loop">
 <p>
 See <a href="#tool-dispatch" className="link">Tool Dispatch Loop</a>{" "}
 for the per-call internals. Loop continues up to 20 steps or
 until the model emits text-only response.
 </p>
 </SubSection>
 <SubSection icon="check_circle" title="12. Done event">
 <p>
 Synthesize <Code>finalResponse</Code> from accumulated text,
 persist as the assistant message, classify{" "}
 <Code>RunStatusReason</Code>, emit{" "}
 <Code>turn_cost</Code> SSE event with totals, fire{" "}
 <Code>RunEnd</Code> hook, emit <Code>done</Code> with{" "}
 <Code>{`{ response, toolCalls, status_reason, duration_ms }`}</Code>.
 </p>
 </SubSection>
 </Section>
);
}

function FireSites() {
 return (
 <Section id="fire-sites" icon="flag" title="Hook Fire-Sites">
 <p>
 The chat-route fires hooks at 10 lifecycle points. Each is a{" "}
 <Code>fireHookEvent(event, payload, trigger)</Code> call that
 loads matching hooks from MCP, dispatches them in priority order,
 applies their decisions, and writes a{" "}
 <Code>hook_dispatched</Code> audit row.
 </p>
 <SubSection icon="format_list_numbered" title="The 10 fire-sites">
 <ul className="list-disc pl-5 space-y-1.5 text-sm">
 <li>
 <Code>RunStart</Code> — After meta event, before user message
 persist. A deny cleanly aborts the turn.
 </li>
 <li>
 <Code>UserPromptSubmit</Code> — Before persist. Hook may deny,
 replace the message (redaction), or inject context.
 </li>
 <li>
 <Code>PreCompact</Code> — Inside /compress before
 history fetch + summarize. Hook may veto compaction (audit
 policy: don&apos;t roll up this session).
 </li>
 <li>
 <Code>PostCompact</Code> — After compaction success. Non-
 decisional; for forwarding to external archives.
 </li>
 <li>
 <Code>PreToolUse</Code> — Per tool call, before approval-poll
 dispatch. Most-used hook event. Decisions:
 allow/deny/ask + replace args.
 </li>
 <li>
 <Code>PostToolUse</Code> — Per tool call, after success. May
 replace the result (scrub sensitive output before the model
 sees it).
 </li>
 <li>
 <Code>PostToolUseFailure</Code> — Per tool call, on error.
 Non-decisional; for incident-channel forwarding.
 </li>
 <li>
 <Code>SubagentStart</Code> — Before subagent
 dispatch. May deny.
 </li>
 <li>
 <Code>SubagentEnd</Code> — After subagent
 completes. Non-decisional.
 </li>
 <li>
 <Code>RunEnd</Code> — After final response composed, before
 stream close. Non-decisional; for turn-summary
 notifications.
 </li>
 </ul>
 </SubSection>
 <SubSection icon="info" title="Decision precedence">
 <p>
 Multiple hooks per event run serially in priority asc order
 (low priority runs first). Aggregate decision is{" "}
 <Code>deny &gt; ask &gt; allow &gt; undefined</Code>. A deny
 short-circuits the chain (no later hook can override). An ask
 short-circuits decision but lets later hooks contribute{" "}
 <Code>injectContext</Code>.
 </p>
 </SubSection>
 </Section>
);
}

function ToolDispatch() {
 return (
 <Section id="tool-dispatch" icon="build" title="Tool Dispatch Loop">
 <p>
 The tool-call loop is the most complex part of the chat-route.
 Per Gemini response with function calls, the loop:
 </p>
 <SubSection icon="format_list_numbered" title="Per-tool steps">
 <ol className="list-decimal pl-5 space-y-1.5 text-sm">
 <li>
 <Term>Subagent intercept</Term>: if{" "}
 <Code>toolName === &apos;subagent_create&apos;</Code>, route to{" "}
 <Code>runSubagent()</Code> and skip the rest. Returns the
 subagent result as a synthetic tool result.
 </li>
 <li>
 <Term>PreToolUse hook</Term>: fire with
 sessionId/toolName/args. Deny → synthesize an error result
 and continue to next call. Replace → swap in new args.
 </li>
 <li>
 <Term>Tool metadata resolution</Term>:{" "}
 <Code>resolveToolMetadata(toolName)</Code> returns
 readOnly/destructive/concurrencySafe/openWorld flags.
 Denormalized onto the <Code>tool_call</Code> SSE event.
 </li>
 <li>
 <Term>Approval poll</Term>: if{" "}
 <Code>isToolGated(toolName)</Code>, snapshot pending approval
 ids and arm a poll loop. The MCP creates a pending row when
 the tool fires; the chat-route detects the new id and emits{" "}
 <Code>approval_pending</Code> SSE for the inline UI card.
 </li>
 <li>
 <Term>MCP dispatch</Term>:{" "}
 <Code>mcpClient.callTool(toolName, toolArgs)</Code>. The MCP
 tool wrapper writes a <Code>tool_call</Code> audit row, runs
 the tool, returns the result.
 </li>
 <li>
 <Term>Connector state recording</Term>: success
 → <Code>recordConnectorSuccess(connectorId)</Code>; failure
 → <Code>recordConnectorFailure(connectorId, isAuthError)</Code>.
 The connector id is the first segment of the tool name
 (<Code>caldera.start_op</Code> → caldera).
 </li>
 <li>
 <Term>PostToolUse / PostToolUseFailure hook</Term>:
 fire with the result or error. PostToolUse may{" "}
 <Code>replace</Code> the result text.
 </li>
 <li>
 <Term>Result emission</Term>: <Code>tool_result</Code> SSE
 event + persistence + push to the parent&apos;s{" "}
 <Code>responseParts</Code> for the next Gemini call.
 </li>
 </ol>
 </SubSection>
 <SubSection icon="cached" title="Turn-scoped read cache">
 <p>
 Models sometimes re-request the same idempotent read several
 times within one turn (observed: <Code>data_sources_list</Code>{" "}
 called 3-4× while answering a single question). A soft
 system-prompt nudge did not reliably stop this, so
 step 5 (<Term>MCP dispatch</Term>) is fronted by a{" "}
 <Term>per-message memo</Term>: an identical{" "}
 <Code>(tool, args)</Code> call for an allowlisted read returns
 the already-fetched result instead of re-dispatching to the MCP.
 </p>
 <ul className="list-disc pl-6 space-y-1 text-sm">
 <li>
 <Term>Allowlist</Term> (<Code>TURN_CACHEABLE_TOOLS</Code>):
 static platform metadata only — <Code>data_sources_list</Code>,{" "}
 <Code>data_sources_get_schema</Code>,{" "}
 <Code>data_sources_installed_as_vendors</Code>,{" "}
 <Code>marketplace_list</Code>,{" "}
 <Code>log_destinations_list</Code>, <Code>settings_get</Code>,{" "}
 <Code>skills_read</Code>, <Code>knowledge_search</Code>,{" "}
 <Code>phantom_get_field_info</Code>.
 </li>
 <li>
 <Term>REPEATABLE-READ semantics</Term>: a catalog/config
 mutation (<Code>invalidatesTurnCache()</Code>) clears the
 snapshot, so a same-turn install→re-list still sees fresh
 state. Different args ⇒ different key ⇒ both calls dispatch
 (schema for source A then B is never collapsed).
 </li>
 <li>
 <Term>Scope</Term>: the cache is declared inside the POST
 handler (per user message), never module-level — no snapshot
 leaks across turns or operators.
 </li>
 <li>
 <Term>Display</Term>: only the MCP round-trip is skipped. The
 model still emits the <Code>tool_call</Code>, so live telemetry
 still shows the request, now badged <Code>cached</Code> in the Live
 Telemetry panel to distinguish a cache-served hit
 from a real MCP dispatch.
 </li>
 </ul>
 </SubSection>
 <SubSection icon="block" title="Failed-call loop breaker">
 <p>
 The read cache memoizes only successes. Some tools signal failure
 with an <Code>{"{ok:false}"}</Code> result payload rather than
 throwing (e.g. <Code>data_sources_install</Code> on a not-found
 pack), so a model can re-fire the identical failing call many times
 (observed: <Code>data_sources_install</Code> seven times while
 answering a read-only field question). A per-message failure ledger
 keyed on <Code>(tool, args)</Code> counts failures; after{" "}
 <Code>MAX_IDENTICAL_FAILS</Code> (2) failures of the SAME call this
 turn, further identical dispatches are short-circuited with a
 synthetic <Code>{'{ok:false, note:"do not retry; change approach"}'}</Code>{" "}
 payload instead of hitting the MCP again.
 </p>
 <ul className="list-disc pl-6 space-y-1 text-sm">
 <li>
 Poll/wait tools (<Code>isPollTool</Code>) are exempt — they
 legitimately re-issue identical calls (e.g.{" "}
 <Code>caldera_wait_for_operation_progress</Code>).
 </li>
 <li>
 Distinct arguments are independent keys, so a genuine retry with
 changed inputs still dispatches; only verbatim repeats are capped.
 </li>
 <li>
 Detection is via exception OR the explicit{" "}
 <Code>{'"ok": false'}</Code> envelope only — never tool output
 that merely contains the word &quot;error&quot;.
 </li>
 </ul>
 </SubSection>
 <SubSection icon="error_outline" title="Auth-error classification">
 <p>
 The chat-route uses message-string heuristics to detect 401/403
 / &quot;auth&quot; / &quot;expired&quot; / &quot;invalid token&quot;
 patterns. When an auth error is detected, the connector state
 flips to <Code>needs-auth</Code> AND a{" "}
 <Code>connector_auth_required</Code> SSE event fires for the
 chat UI. This is heuristic until the MCP exposes typed errors;
 the false-positive risk is low (the regex is anchored to
 common auth phrases).
 </p>
 </SubSection>
 <SubSection icon="record_voice_over" title="Pre-dispatch preamble">
 <p>
 Before the per-tool dispatch loop kicks off, the chat-route
 inspects the parts the model emitted in this turn. If the
 model produced <Term>any</Term> text, that text was already
 streamed via <Code>text_delta</Code> SSE events at the moment
 each part was processed (lines ~3819–3828 in{" "}
 <Code>app/api/chat/route.ts</Code>). If the model emitted
 ONLY function calls and zero text, the chat-route synthesizes
 a one-line preamble per pending tool call and streams it as{" "}
 <Code>text_delta</Code> BEFORE the dispatch loop begins —
 which means it lands before any{" "}
 <Code>approval_pending</Code> event the gate could fire.
 </p>
 <p>
 Goal: the operator never sees an approval card pop out of
 nowhere. Either the model narrates first (preferred — the
 system prompt instructs it to), or the server fills the gap.
 </p>
 <Pre>{`if (finalText.length === 0) {
  for (const call of functionCalls) {
    const preamble = formatToolPreamble(call.name, call.args || {});
    if (preamble) {
      sendEvent('text_delta', { text: preamble + '\\n\\n' });
    }
  }
}`}</Pre>
 <p>
 <Code>formatToolPreamble()</Code> picks up to 4 keys from the
 args, prefers human-meaningful ones (<Code>name</Code>,{" "}
 <Code>cron</Code>, <Code>url</Code>, <Code>query</Code>,{" "}
 <Code>instance_id</Code>, …), hides secret-looking keys
 (regex on <Code>api_key</Code>, <Code>password</Code>,{" "}
 <Code>token</Code>, …), truncates string values to 80
 characters, and reduces arrays / objects to summaries
 (<Code>[12 items]</Code>, <Code>{`{cdp_url, …}`}</Code>).
 </p>
 <p>
 The same logic is mirrored UI-side in{" "}
 <Code>components/chat/approval-card.tsx</Code> as a defense-
 in-depth &quot;Will be called with&quot; panel — even if the
 preamble didn&apos;t render for some reason, the card itself
 shows the same key=value summary above the Approve / Deny
 buttons.
 </p>
 </SubSection>
 <SubSection icon="hub" title="Process-wide tool_dispatcher singleton">
 <p>
 The unified dispatch helper is lifted to a process-wide
 singleton so multiple consumers (the job scheduler AND{" "}
 <a href="#approvals" className="link">agent_batch_propose</a>)
 can reach it without duplicating fastmcp.Client wiring.
 </p>
 <p>
 <Code>usecase/tool_dispatcher.py</Code> exposes the same
 set/get pair as the other module-level singletons in the
 bundle (<Code>set_scheduler</Code>/<Code>get_scheduler</Code>,
 etc.). <Code>main.py async_main()</Code> builds the dispatcher
 unconditionally after{" "}
 <Code>register_all_tools()</Code> populates the registry, then
 installs it via <Code>set_tool_dispatcher(d)</Code>. The same
 instance is consumed by the job scheduler (when{" "}
 <Code>manifest.jobs[]</Code> has entries) AND by
 agent_batch_propose. The boot log line{" "}
 <Code>tool_dispatcher installed</Code> confirms wiring; a
 missing line means partial boot — agent_batch_propose then
 falls back to its clean &quot;dispatcher not configured&quot;
 error envelope rather than crashing.
 </p>
 </SubSection>
 </Section>
);
}

// ─── Context & Sessions sections ──────────────────────────────────

function ContextBudget() {
 return (
 <Section id="context-budget" icon="token" title="Token-aware Context Budgeting">
 <p>
 The chat handler walks history token-aware rather than by a
 fixed N-message slice: it walks newest-to-oldest, accumulating
 estimated tokens, until the model&apos;s input budget is reached.
 Older messages either drop entirely or are summarized into a
 compaction checkpoint. The diagram shows the full 5-stage
 pipeline including the compaction + cache decision branches and
 the parallel memory ranking sub-pipeline.
 </p>

 <ContextMemoryPipeline />

 <SubSection icon="calculate" title="Estimation heuristic">
 <p>
 <Code>lib/tokens.ts:estimateTokens(text)</Code> uses{" "}
 <Code>length / 4 + 5 envelope</Code>. Conservative — real
 Gemini tokenization is closer to 1 token per 3.5 chars on
 English text. The 30% safety margin in the budget walk
 absorbs tokenizer drift.
 </p>
 </SubSection>
 <SubSection icon="settings" title="Per-model context cap">
 <p>
 <Code>lib/model-context-caps.ts:resolveContextCap(model)</Code>{" "}
 returns the model&apos;s context-window cap (gemini-3.1-pro
 = 1M, gemini-2.5-flash-lite = 32K, etc).{" "}
 <Code>computeInputBudget(model, reservedForOutput)</Code> applies
 a 30% safety margin to give the budget walk headroom.
 </p>
 </SubSection>
 <SubSection icon="warning" title="Context-utilization guard">
 <p>
 Computed at chat-route step 8 (see lifecycle). At &gt;= 99%
 the chat-route blocks with a structured{" "}
 <Code>CONTEXT_NEAR_FULL</Code> error. At &gt;= 90% emits a
 warning + writes a <Code>chat_context_warning</Code> audit row. The 80% threshold drives the chat-input
 banner with the one-click /compress chip.
 </p>
 </SubSection>
 </Section>
);
}

function Compaction() {
 return (
 <Section id="compaction" icon="compress" title="Compaction Pipeline">
 <p>
 Two compaction paths — manual (operator types{" "}
 <Code>/compress</Code>) and automatic (history-load notices the
 token budget is about to drop too many messages) — both
 collapse prior session history into a single summary
 checkpoint. The checkpoint is a system-role message with{" "}
 <Code>meta.kind=&apos;compaction-checkpoint&apos;</Code>;{" "}
 <Code>loadSessionHistory</Code> recognizes it and slices replay
 from the checkpoint forward.
 </p>
 <SubSection icon="bolt" title="Manual /compress">
 <p>
 Operator-triggered via <Code>SLASH_COMMANDS</Code> entry. Fetches
 full session history (limit=1000), filters out the just-persisted
 /compress message + earlier checkpoints, calls{" "}
 <Code>compactMessages(summarizable, summarizer)</Code>, persists
 the result. Empty-summarizable case fast-returns with text_delta
 + done (no Gemini call).
 </p>
 </SubSection>
 <SubSection icon="auto_mode" title="Auto budget-edge compaction">
 <p>
 When token-budget walking would drop more than{" "}
 <Code>autoCompactMinDropped</Code> messages (default 5; the
 Personality &rarr; Tuning slider adjusts), the dropped portion is summarized via Gemini and
 persisted as a checkpoint INSIDE the history-load function.
 Subsequent turns benefit from the checkpoint without
 re-summarizing.
 </p>
 </SubSection>
 <SubSection icon="article" title="Summarization contract">
 <p>
 <Code>lib/compaction.ts:SUMMARIZE_INSTRUCTIONS</Code> is the
 system prompt for the summarizer. Instructions: preserve open
 tasks + decisions + tool round-trips + opaque IDs verbatim
 (UUIDs, IPs, hostnames, audit ids). 300-500 word target. No
 headers, no bullets, dense prose.
 </p>
 </SubSection>
 <SubSection icon="badge" title="Checkpoint shape">
 <Pre>{`{
 role: 'system',
 content: '<summary text>',
 meta: {
 kind: 'compaction-checkpoint',
 covers_until: '<iso ts of latest summarized msg>',
 messages_summarized: <count>,
 trigger: 'auto' | 'manual' // auto-compaction tags 'auto'
 }
}`}</Pre>
 </SubSection>
 </Section>
);
}

function VertexCache() {
 return (
 <Section id="vertex-cache" icon="bolt" title="Vertex Prompt Caching">
 <p>
 adds Vertex <Code>cachedContents</Code> for the
 stable system prompt. Cached input tokens bill at ~25% of the
 standard rate. The bundle&apos;s ~13K-token system prompt
 amortizes to a real cost win when an operator runs many turns
 in one session.
 </p>
 <SubSection icon="cached" title="Cache lifecycle">
 <p>
 <Code>lib/vertex-cache.ts:getOrCreateSystemPromptCache()</Code>{" "}
 maintains a per-process cache keyed by{" "}
 <Code>{`{model}:{sha256(systemPromptText)[0:16]}`}</Code>. On
 miss: POST <Code>/v1/.../cachedContents</Code> with TTL=3600s.
 On success: stash name + local-clock expiry. Local expiry
 subtracts 60s buffer to avoid landing on a freshly-expired
 Vertex resource.
 </p>
 </SubSection>
 <SubSection icon="warning" title="Failure handling">
 <p>
 Some models reject <Code>cachedContents.create</Code> for
 prompts under 32K tokens (gemini-2.5-pro&apos;s minimum
 varies by region). Failures are sticky-cached for 5 minutes
 (FAILURE_BACKOFF_MS) so we don&apos;t hammer Vertex with
 create requests for prompts that don&apos;t qualify. Fail-
 fallback: send the inline system prompt instead.
 </p>
 </SubSection>
 <SubSection icon="lock" title="Gating">
 <p>
 Vertex prompt caching is gated behind <Code>PHANTOM_VERTEX_CACHE=1</Code> env
 var (operator opt-in). exposed this as a
 personality toggle. Future: per-model gate as the chat-route
 learns which models reliably support cached references.
 </p>
 </SubSection>
 </Section>
);
}

// ─── Slash + Audit + Settings sections ──────────────────────────

function SlashCommands() {
 return (
 <Section id="slash-commands" icon="terminal" title="Slash-Command Framework">
 <p>
 Slash commands are dispatched by a parse-and-register framework
 rather than ad-hoc string matching:{" "}
 <Code>SLASH_COMMANDS: readonly SlashCommand[]</Code> at module
 scope in <Code>route.ts</Code>; <Code>parseSlashCommand(text)</Code>{" "}
 returns <Code>{`{ name, args }`}</Code> or null;{" "}
 <Code>dispatchSlashCommand(parsed, commands, ctx)</Code> finds the
 handler. Adding a command means appending one entry to the
 array.
 </p>
 <SubSection icon="contract" title="SlashCommand contract">
 <Pre>{`interface SlashCommand {
 name: string; // 'compress', 'clear', etc.
 argHint?: string; // shown in /help
 description: string; // shown in /help
 handler: (ctx: SlashCommandContext) => Promise<void>;
}`}</Pre>
 <p>
 Handlers receive a context with sessionId / args / runtimeConfig
 / sendEvent / controller. Handlers MUST close the controller
 before returning — the framework wraps with try-catch but
 doesn&apos;t auto-close (so a handler can leave the stream
 open across awaits).
 </p>
 </SubSection>
 <SubSection icon="list" title="Registered commands">
 <p>
 Seven commands ship today: <Code>/help</Code>,{" "}
 <Code>/clear</Code>, <Code>/model</Code>,{" "}
 <Code>/compress</Code>, <Code>/plan</Code>,{" "}
 <Code>/tasks</Code>, and <Code>/cost</Code>. Adding a new
 command is one entry in the array; no other code changes
 needed.
 </p>
 </SubSection>
 <SubSection icon="bug_report" title="Defensive close pattern">
 <p>
 The chat-route&apos;s outer{" "}
 <Code>{`try {... } finally { controller.close(); }`}</Code> can
 throw &ldquo;Invalid state: Controller is already closed&rdquo;
 when a slash handler already closed. commit{" "}
 The defensive close pattern wraps both the catch&apos;s sendEvent and
 the finally&apos;s close in try-catch. Without this, queued
 events from inside a slash handler (text_delta, done) would
 silently vanish before flushing.
 </p>
 </SubSection>
 </Section>
);
}

function ObservabilityOverview() {
 return (
 <Section id="observability-overview" icon="insights" title="Observability Overview">
 <p>
 Phantom emits enough telemetry that customers can answer{" "}
 <em>&ldquo;what is the platform doing right now?&rdquo;</em>{" "}
 and{" "}
 <em>&ldquo;what did it do last week?&rdquo;</em>{" "}
 without instrumenting external tooling. Every operator-visible
 surface lives under <Code>/observability/*</Code>; this section
 orients you across them and points at the deeper specs.
 </p>

 <SubSection icon="hub" title="The ten surfaces">
 <p>
 Each surface answers a different question. Pick by what you
 want to know:
 </p>
 <ul className="list-disc pl-5 space-y-1.5 text-sm">
 <li>
 <Term><Link href="/observability/events" className="link">/observability/events</Link></Term>
 {" "}— forensic audit log. Every tool call, every settings change, every hook fire,
 every approval decision. Lucene-light query bar; 7-day retention.{" "}
 <Link href="#audit-persistence" className="link">Audit Persistence</Link> covers the schema.
 </li>
 <li>
 <Term><Link href="/observability/runtime-events" className="link">/observability/runtime-events</Link></Term>
 {" "}— operational event log (e.g. <Code>rt.simulation.started</Code>, <Code>rt.worker.completed</Code>).
 Higher-level than audit; structured for &ldquo;what jobs ran today?&rdquo; rollups.
 </li>
 <li>
 <Term><Link href="/observability/metrics" className="link">/observability/metrics</Link></Term>
 {" "}— Prometheus-format gauges + counters + histograms.
 <Code>GET /metrics</Code> is the unauthenticated scrape endpoint for external Prometheus servers.{" "}
 <Link href="#logs-events-traces" className="link">Logs / Events / Traces</Link>
 {" "}covers the registry contract.
 </li>
 <li>
 <Term><Link href="/observability/traces" className="link">/observability/traces</Link></Term>
 {" "}— OpenTelemetry distributed traces (opt-in via <Code>PHANTOM_OTEL=1</Code>).
 Chat turns are parent spans; tool calls are child spans; connector calls are grandchildren.
 Drill in to find which sub-call dominated turn latency.
 </li>
 <li>
 <Term><Link href="/observability/pipeline" className="link">/observability/pipeline</Link></Term>
 {" "}— live React Flow graph of every component (agent, MCP, connectors, xlog, log destinations) with
 per-edge health pulses and per-node status badges.{" "}
 <Link href="#pipeline-health" className="link">Pipeline Health</Link> covers the probe machinery.
 </li>
 <li>
 <Term><Link href="/observability/connectors" className="link">/observability/connectors</Link></Term>
 {" "}— per-connector state (<Code>enabled / disabled / failed / needs-auth / probed</Code>) +
 last-50-probes table per connector. Where to start when an integration goes red.{" "}
 <Link href="#connector-state" className="link">Connector State Machine</Link> covers the state graph.
 </li>
 <li>
 <Term><Link href="/observability/logs" className="link">/observability/logs</Link></Term>
 {" "}— live tail of raw container stdout/stderr (SSE-streamed, last 200 lines per container).
 The fallback when audit and runtime-events don&apos;t carry enough detail.
 </li>
 <li>
 <Term><Link href="/observability/cost" className="link">/observability/cost</Link></Term>
 {" "}— per-model token cost rollup with by-session and by-day breakdowns. Vertex caching savings tile
 quantifies cache ROI.{" "}
 <Link href="#cost-tracking" className="link">Cost Tracking</Link> covers the pricing table + computation.
 </li>
 <li>
 <Term><Link href="/observability/bench" className="link">/observability/bench</Link></Term>
 {" "}— benchmark run history with per-run scored output + side-by-side compare view across runs.
 Tracks agent quality regression as the bundle or prompt changes.
 </li>
 <li>
 <Term><Link href="/observability/detections" className="link">/observability/detections</Link></Term>
 {" "}— XSIAM detection inventory: rules indexed locally, per-rule fire counts, MITRE ATT&amp;CK
 technique coverage gaps. Sync from XSIAM via{" "}
 <Code>detections_sync</Code>.
 </li>
 <li>
 <Term><Link href="/observability/plugins" className="link">/observability/plugins</Link></Term>
 {" "}— entry-point plugin inventory (pip-installed Python packages exposing{" "}
 <Code>phantom.hooks</Code> / <Code>phantom.skills</Code> / etc.) with install + uninstall buttons.
 </li>
 </ul>
 </SubSection>

 <SubSection icon="account_tree" title="Telemetry shape — three layers stacked">
 <p>
 The surfaces above sit on a small set of underlying telemetry
 layers. Understanding the layering helps when you&apos;re
 looking for a specific signal and unsure which surface to
 open:
 </p>
 <Pre>{`UI surfaces (10)
  ┌──────────────────────────────────────────────────────────────┐
  │  /observability/{events,runtime-events,metrics,traces,...}   │
  └──────────────────────────────────────────────────────────────┘
                              │
                              v
Aggregation layer (3 stores + 1 sidecar)
  ┌─────────────────┐  ┌──────────────────┐  ┌───────────────┐
  │  audit.db       │  │ metrics_registry │  │ event_log.db  │
  │  append-only    │  │ in-memory        │  │ runtime-events│
  │  SOC trail      │  │ Prometheus       │  │ operational   │
  └─────────────────┘  └──────────────────┘  └───────────────┘
                              │
                              v (opt-in)
  ┌──────────────────────────────────────────────────────────────┐
  │  OTel exporter → external observability backend              │
  └──────────────────────────────────────────────────────────────┘

Emission layer (every component)
  ┌──────────────────────────────────────────────────────────────┐
  │  chat-route, MCP tool dispatch, connectors, xlog,            │
  │  job scheduler, hook runner, approval bus                    │
  │  All write via safeAudit() / metrics.record() / events.emit()│
  └──────────────────────────────────────────────────────────────┘`}</Pre>
 <p className="text-sm text-on-surface-variant">
 The three aggregation stores are intentionally separated by{" "}
 <em>cardinality</em>:
 audit.db is per-event (high cardinality, long retention);
 metrics_registry is per-counter (low cardinality, queryable
 only as time-series); event_log is mid-cardinality
 (operational summary, 7-day retention). Trying to use one
 for another&apos;s job ends in tears.
 </p>
 </SubSection>

 <SubSection icon="psychology" title="When to use which surface">
 <p>
 Operator decision tree:
 </p>
 <Pre>{`Q: "Why did this chat turn fail?"
   → /observability/events (filter by session_id) — every tool
     call's outcome, plus chat_turn_cost row at the end.

Q: "Which jobs failed today?"
   → /observability/runtime-events (filter by 'rt.job.failed')
     OR /jobs (filter by status=failed).

Q: "Is XSIAM healthy?"
   → /observability/connectors → xsiam row. State + last-50
     probes table. If degraded, /observability/pipeline shows
     the upstream/downstream impact.

Q: "Where is my Vertex spend coming from?"
   → /observability/cost. By-model bar chart + by-session
     drill-down. Cache-savings tile if PHANTOM_VERTEX_CACHE=1.

Q: "How long are turns taking?"
   → /observability/traces (requires PHANTOM_OTEL=1). Per-turn
     span tree shows the dominant cost.

Q: "Did anyone change settings while I was out?"
   → /observability/events (filter by action ∈ {settings_set,
     personality_set, jobs_create, hooks_create, …}).

Q: "Why did this detection rule fire?"
   → /observability/detections → click the rule → fire history
     with per-fire context.`}</Pre>
 </SubSection>

 <SubSection icon="rule_folder" title="Retention + privacy">
 <p>
 Default retention windows + privacy contract for each store:
 </p>
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <Term>audit.db</Term> — 7 days by default, tunable via the{" "}
 <Code>auditRetentionDays</Code> setting. Tamper-evident (no
 UPDATE or DELETE endpoint; SQLite WAL append-only).
 </li>
 <li>
 <Term>event_log.db</Term> — 7 days fixed retention; older
 rows swept by a periodic vacuum.
 </li>
 <li>
 <Term>metrics_registry</Term> — in-memory, lost on restart.
 External Prometheus servers are expected to scrape and
 retain. <Code>GET /metrics</Code> is intentionally
 unauthenticated so existing Prometheus deployments work.
 </li>
 <li>
 <Term>traces</Term> — exported live to an OTLP endpoint;
 Phantom doesn&apos;t retain them locally.
 </li>
 <li>
 <Term>logs (container stdout)</Term> — Docker&apos;s log
 driver decides (default: json-file, 10 MB rotated). Not
 forensic — use audit.db for that.
 </li>
 </ul>
 <p className="text-sm text-on-surface-variant">
 No PII or secret values flow into any observability store
 by design — emitters call{" "}
 <Code>_sanitize(meta)</Code> before write, which scrubs
 anything matching the SecretStore path pattern. Operator
 names + connector instance names + tool arguments DO appear
 in audit rows; they&apos;re considered operator-visible
 metadata.
 </p>
 </SubSection>

 <SubSection icon="construction" title="Implementation references">
 <ul className="list-disc pl-6 space-y-1 text-sm">
 <li><Code>bundles/spark/mcp/src/usecase/audit_log.py</Code> — audit.db CRUD + safeAudit() helper</li>
 <li><Code>bundles/spark/mcp/src/usecase/event_log.py</Code> — operational event_log.db</li>
 <li><Code>bundles/spark/mcp/src/usecase/metrics_registry.py</Code> — Prometheus counters/gauges/histograms</li>
 <li><Code>bundles/spark/mcp/src/api/tracing.py</Code> — OTel autoinstrumentation toggle</li>
 <li><Code>bundles/spark/mcp/src/api/observability.py</Code> — REST endpoints for runtime-events</li>
 <li><Code>bundles/spark/mcp/src/api/audit.py</Code> — REST endpoints for audit query + SSE stream</li>
 <li><Code>mcp/agent/app/observability/*/page.tsx</Code> — each UI surface</li>
 </ul>
 </SubSection>
 </Section>
);
}

function AuditPersistence() {
 return (
 <Section id="audit-persistence" icon="policy" title="Audit Persistence Layer">
 <p>
 Audit persistence makes the chat-route&apos;s SSE events
 queryable history rather than transient stream output. Three
 pieces work together:
 </p>
 <SubSection icon="api" title="POST /api/v1/audit endpoint">
 <p>
 <Code>bundles/spark/mcp/src/api/audit.py</Code> exposes a
 generic POST endpoint that the chat-route hits for events
 that aren&apos;t tool calls. Body:{" "}
 <Code>{`{ action, target?, status?, duration_ms?, metadata? }`}</Code>
. Actor is fixed to <Code>user:operator</Code> (bearer auth).
 Trigger inherits from the X-Phantom-Trigger contextvar.
 </p>
 </SubSection>
 <SubSection icon="cloud_upload" title="safeAudit() helper">
 <p>
 <Code>route.ts:safeAudit(action, args)</Code> never throws;
 failures log a warning. Wired at compaction lifecycle
 (start/end/failed), context warnings, cache hits, hook
 dispatches, task transitions, connector state changes, turn
 cost, plan proposed, and subagent lifecycle.
 </p>
 </SubSection>
 <SubSection icon="filter_list" title="Filter chips on /observability/events">
 <p>
 Pre-fab queries: Compactions / Context warnings / Cache hits /
 Failed compactions / Tool calls. Each click pre-populates the
 query bar AND commits the filter. One-click drill-in.
 </p>
 </SubSection>
 <SubSection icon="palette" title="/activity feed icons">
 <p>
 <Code>actionMeta(action)</Code> maps every audit family to
 a Material Symbol + tone class. Per-row icon column means
 eye sweeps pick up event KIND visually rather than reading
 the action name.
 </p>
 </SubSection>
 </Section>
);
}

function BackupRestore() {
 return (
 <Section id="backup-restore" icon="save" title="Backup & Restore">
 <p>
 Operators can take a complete-state snapshot of the deployment
 via <Link href="/settings/backup-restore" className="link">
 /settings/backup-restore
 </Link>. One zip captures every operator-owned data surface;
 the same zip restores onto another deployment with a different{" "}
 <Code>PHANTOM_SECRET_KEK</Code>.
 </p>
 <SubSection icon="folder_zip" title="Zip layout (schema_version: 1)">
 <Pre>{`phantom-backup-<ISO-stamp>.zip
├── manifest.json          schema_version, phantom_version,
│                          created_at, section_counts,
│                          restore_order, plaintext-secrets warning
├── personality.json       SqlitePersonalityStore blob
├── instances.json         InstanceStore rows + cleartext secrets
├── memory.json            Memory entries (no embedding BLOBs)
├── jobs.json              runtime jobs only (manifest jobs reseed)
├── skills/<category>/...  every skill MD, preserves dir structure
└── knowledge/<kb>/...     KB doc content (read-only at runtime)`}</Pre>
 </SubSection>
 <SubSection icon="data_object" title="API surface">
 <ul className="list-disc pl-6 space-y-1.5">
 <li>
 <Code>GET /api/agent/backup</Code> — session-gated via the{" "}
 <Code>phantom_session</Code> cookie at{" "}
 <Code>middleware.ts</Code>. Server-side calls{" "}
 <Code>/api/v1/instances?include_secrets=true</Code> (a
 bearer-auth gated MCP flag mirroring the ProviderStore
 detail-endpoint pattern), plus{" "}
 <Code>/api/v1/personality</Code>,{" "}
 <Code>/api/v1/memories</Code>, <Code>/api/v1/jobs</Code>,{" "}
 <Code>/api/v1/kbs</Code>, and the <Code>skills_list_all</Code>{" "}
 + <Code>skills_read</Code> MCP tools. Per-section try/catch —
 a failing endpoint emits a <Code>backup_warnings[]</Code>{" "}
 entry rather than killing the whole backup.
 </li>
 <li>
 <Code>POST /api/agent/restore</Code> — multipart upload,
 optional <Code>?dry_run=true</Code> to preview without writing,
 optional <Code>?force=true</Code> to overwrite name collisions
 (default = skip). Returns{" "}
 <Code>{`{applied, skipped, errors, warnings}`}</Code>.
 100 MB upload cap, schema_version pin in the manifest, JSZip-
 backed parse.
 </li>
 </ul>
 </SubSection>
 <SubSection icon="sort" title="Restore order (dependency-aware)">
 <ol className="list-decimal pl-6 space-y-1">
 <li>
 <strong>Personality</strong> — no deps; setting it first is
 harmless even if a later section fails.
 </li>
 <li>
 <strong>Instances + secrets</strong> — atomic write so secret
 paths resolve from first read. Cleartext secrets in the zip
 re-encrypt under the destination&rsquo;s KEK on POST.
 </li>
 <li>
 <strong>Skills</strong> — must exist before any restored job
 that binds to a skill name can fire.
 </li>
 <li>
 <strong>Memory</strong> — independent. Embedding BLOBs are
 stripped from the zip (they&rsquo;re dim-bound); the
 destination re-embeds on next semantic search.
 </li>
 <li>
 <strong>Knowledge</strong> — read-only at runtime; the
 <Code>kb.db</Code> is rebuilt from <Code>/app/bundle/kbs/</Code>
 (image-baked) on every boot. Restore counts the docs in the
 zip, emits a warning if non-empty, but does not write.
 </li>
 <li>
 <strong>Jobs</strong> — last because runtime jobs may
 reference connector tools (e.g.{" "}
 <Code>phantom_create_data_worker</Code>) that need their
 instance enabled before the first cron tick.
 </li>
 </ol>
 </SubSection>
 <SubSection icon="key" title="Secrets handling">
 <p>
 The zip carries <strong>cleartext</strong> connector secrets so
 the operator&rsquo;s <Code>PHANTOM_SECRET_KEK</Code> doesn&rsquo;t
 need to match across deployments. The destination&rsquo;s
 SecretStore re-encrypts on write. Tradeoff: the zip itself is
 sensitive — the manifest carries an explicit warning, the UI
 surfaces it next to the Download button. Operators are
 responsible for handling the zip like any other plaintext
 credential file (no version control, no unencrypted
 channels).
 </p>
 <p>
 The MCP-side bearer auth on{" "}
 <Code>/api/v1/instances?include_secrets=true</Code> is the
 internal gate; the agent&rsquo;s{" "}
 <Code>/api/agent/backup</Code> route runs behind{" "}
 <Code>middleware.ts</Code> which validates the operator&rsquo;s{" "}
 <Code>phantom_session</Code> cookie before any handler fires —
 secrets never reach an unauthenticated caller.
 </p>
 </SubSection>
 <SubSection icon="bug_report" title="Idempotence + collision policy">
 <p>
 Default semantics are <strong>upsert-or-skip</strong>: a name
 collision (job/skill/instance) on restore preserves the
 existing entry and reports the incoming one in the{" "}
 <Code>skipped</Code> summary. <Code>?force=true</Code>{" "}
 overwrites — but personality is <em>always</em> overwritten
 regardless of the flag because the personality table is a
 single-row blob; partial-merge of a persona doesn&rsquo;t
 have meaningful semantics.
 </p>
 </SubSection>
 </Section>
);
}

function SettingsTuning() {
 return (
 <Section id="settings-tuning" icon="tune" title="Settings & Tuning">
 <p>
 Phantom exposes a handful of operator-tunable knobs that
 modulate chat-route and memory-store behavior:{" "}
 <Code>vertexCacheEnabled</Code>,{" "}
 <Code>autoCompactMinDropped</Code>,{" "}
 <Code>memoryMmrLambda</Code>,{" "}
 <Code>memoryTemporalDecayLambda</Code>. They live alongside
 the persona fields in the{" "}
 <Link href="#personality" className="link">Personality store</Link>{" "}
 (single-row blob with per-edit history) and round-trip via{" "}
 <Code>/api/agent/personality</Code>.
 </p>
 <SubSection icon="info" title="Default-load behavior">
 <p>
 Defaults are synthesized client-side via{" "}
 <Code>DEFAULT_CONFIG</Code> at first GET — they don&apos;t
 appear in the persisted blob until the operator clicks Save.
 The auto-save fires after any slider drag so the writeback
 happens organically.
 </p>
 </SubSection>
 <SubSection icon="link" title="Server-side wiring">
 <p>
 <Term>vertexCacheEnabled</Term> is consulted by the chat-route
 alongside the <Code>PHANTOM_VERTEX_CACHE</Code> env var.{" "}
 <Term>autoCompactMinDropped</Term> threads into the
 compaction pipeline as the trigger threshold (drop ≥ N
 prior messages → summarize via Gemini). The MMR + temporal-
 decay lambdas thread into the memory store&apos;s ranking
 pipeline.
 </p>
 </SubSection>
 </Section>
);
}

// ─── Personality store ──────────────────────────────────────────

function Personality() {
 return (
 <Section id="personality" icon="psychology_alt" title="Personality Store">
 <p>
 Phantom&apos;s agent personality lives in a single-row store
 separate from manifest-driven settings. It captures both
 free-form persona content (name, tone, system-prompt
 instructions) AND a small set of behavior knobs the operator
 can dial without redeploying. The store is the single source
 of truth for what the chat agent feels like — every chat turn
 reads from it at system-prompt-assembly time.
 </p>
 <SubSection icon="storage" title="Storage — personality.db">
 <p>
 A single-row SQLite table at{" "}
 <Code>/app/data/personality.db</Code>. The single-row design
 is intentional: Phantom is single-user, the persona is global
 across all sessions, and concurrent edits are operator-
 visible (last-writer-wins with audit-row history).
 </p>
 <Pre>{`personality (single row)
  ┌─────────────────────────────────────────────────────────────┐
  │ Persona content (free-form)                                 │
  │   name           TEXT     -- e.g. "SOC analyst assistant"  │
  │   tone           TEXT     -- e.g. "concise, factual"        │
  │   instructions   TEXT     -- system-prompt-style guidance   │
  │                                                             │
  │ Behavior knobs (typed)                                      │
  │   vertexCacheEnabled         BOOLEAN                        │
  │   autoCompactMinDropped      INTEGER                        │
  │   memoryMmrLambda            REAL                           │
  │   memoryTemporalDecayLambda  REAL                           │
  │                                                             │
  │ Audit shadow                                                │
  │   updated_at     TEXT NOT NULL                              │
  │   updated_by     TEXT     -- operator | agent              │
  │   version        INTEGER  -- monotonic per save             │
  └─────────────────────────────────────────────────────────────┘

personality_history (per-edit snapshots)
  ┌─────────────────────────────────────────────────────────────┐
  │ id, snapshotted_at, snapshot_json, reason                   │
  └─────────────────────────────────────────────────────────────┘`}</Pre>
 <p className="text-sm text-on-surface-variant">
 Every save writes a row to{" "}
 <Code>personality_history</Code> with the prior blob. Reset
 also snapshots the pre-reset state so an operator can
 retrieve their tuned blob even after a Reset-to-default
 click.
 </p>
 </SubSection>

 <SubSection icon="api" title="REST surface">
 <Pre>{`GET    /api/v1/personality              -- current single-row blob
PUT    /api/v1/personality              -- full replace
POST   /api/v1/personality/reset        -- snapshot + reset to bundle default
GET    /api/v1/personality/history      -- prior snapshots (newest first)

GET    /api/agent/personality           -- Next.js proxy, gated by session cookie
PUT    /api/agent/personality           -- same`}</Pre>
 <p>
 PUT validates against{" "}
 <Code>personality.schema.json</Code> before write (string-
 length caps on persona fields, range caps on numeric knobs).
 Rejected blobs return HTTP 400 with field-level errors;
 nothing is persisted.
 </p>
 </SubSection>

 <SubSection icon="smart_toy" title="MCP tool surface — agent-callable">
 <p>
 Three tiers, matching the agent self-modification model:
 </p>
 <ul className="list-disc pl-6 space-y-1 text-sm">
 <li><Code>personality_get()</Code> — Tier 1 (read-only). No approval card.</li>
 <li><Code>personality_update(spec)</Code> — Tier 2. Tool-dispatch loop renders an approval card; the operator sees the diff before commit.</li>
 <li><Code>personality_patch(fields)</Code> — Tier 2. Partial update; same approval surface as <Code>personality_update</Code>.</li>
 <li><Code>personality_reset()</Code> — Tier 3 destructive. Snapshots the current blob to history, then writes the bundle default back to the single row.</li>
 </ul>
 <p className="text-sm text-on-surface-variant">
 Tier-3 destructive tools live behind the{" "}
 <Link href="#approvals" className="link">
 approvals + tier system
 </Link>
 . The agent narrates the reset in the approval card so the
 operator sees what&apos;s about to disappear before signing
 off.
 </p>
 </SubSection>

 <SubSection icon="construction" title="Chat consumption — system prompt assembly">
 <p>
 At each chat turn the chat-route calls{" "}
 <Code>buildSystemPromptText(personality, approvalMode, …)</Code>{" "}
 in <Code>lib/system-prompt.ts</Code>. The persona fields
 (<Code>name</Code>, <Code>tone</Code>,{" "}
 <Code>instructions</Code>) prepend a dedicated{" "}
 <Code>## PERSONA</Code> block to the system prompt; the
 behavior knobs are read by their respective subsystems (chat-
 route for cache + compaction; memory store for ranking
 lambdas). The TAIL of the system prompt stays cacheable for
 Vertex prompt caching — only the persona block + the
 approval-mode block vary per session.
 </p>
 </SubSection>

 <SubSection icon="history" title="Audit + history">
 <p>
 Every mutation writes an audit row + a history snapshot:
 </p>
 <ul className="list-disc pl-6 space-y-1 text-sm">
 <li><Code>personality_set</Code> — write succeeded. Metadata: <Code>actor</Code>, <Code>version</Code>, <Code>changed_fields[]</Code>.</li>
 <li><Code>personality_set_rejected</Code> — schema validation failed. Metadata: <Code>errors[]</Code>.</li>
 <li><Code>personality_reset</Code> — reset succeeded. Metadata: prior <Code>version</Code>, history row id.</li>
 </ul>
 <p className="text-sm text-on-surface-variant">
 The history table is browsable via{" "}
 <Code>GET /api/v1/personality/history</Code>; the UI&apos;s
 audit feed at{" "}
 <Link href="/observability/events" className="link">
 /observability/events
 </Link>{" "}
 surfaces the same events.
 </p>
 </SubSection>

 <SubSection icon="construction" title="Implementation references">
 <ul className="list-disc pl-6 space-y-1 text-sm">
 <li><Code>bundles/spark/mcp/src/usecase/personality_store.py</Code> — single-row CRUD, history shadow</li>
 <li><Code>bundles/spark/mcp/src/api/personality.py</Code> — REST routes</li>
 <li><Code>bundles/spark/mcp/src/usecase/builtin_components/self_mod_tools.py</Code> — MCP tool registrations</li>
 <li><Code>mcp/agent/app/api/agent/personality/route.ts</Code> — Next.js proxy</li>
 <li><Code>mcp/agent/app/settings/personality/page.tsx</Code> — UI page (Persona + Tuning panels)</li>
 <li><Code>mcp/agent/lib/system-prompt.ts</Code> — system-prompt assembly</li>
 <li><Code>bundles/spark/mcp/schemas/personality.schema.json</Code> — JSON Schema</li>
 </ul>
 </SubSection>
 </Section>
);
}

// ─── Tasks + Agents + Hooks + Plugins sections ──────────────────

function Hooks() {
 return (
 <Section id="hooks" icon="webhook" title="Hooks Framework">
 <p>
 The hooks framework is Phantom&apos;s policy fabric. Operators
 register hooks that fire at chat-route lifecycle events
 (PreToolUse, PostToolUse, etc.). Four transports: <Code>command</Code>{" "}
 (subprocess), <Code>http</Code> (webhook),{" "}
 <Code>builtin</Code> — an in-process TS handler
 shipped with the agent image, selected from a registry by name),
 and <Code>agent</Code> (a registered tool that runs as a hook —
 reserved for plugin-contributed handlers). A hook may
 deny/ask/allow the gated action, replace I/O, or inject context.
 </p>
 <SubSection icon="data_object" title="Hook contract">
 <Pre>{`interface Hook {
 id: string;
 name: string;
 description?: string;
 event: HookEvent; // 10 lifecycle events
 priority?: number; // lower runs first; default 100
 matcher?: HookMatcher; // toolGlob, triggerPrefix, tenantId
 transport: HookTransport;// command | http | builtin | agent
 timeoutMs?: number; // default 5000
 failurePolicy?: 'block' | 'allow' | 'warn';
 enabled?: boolean;
 createdAt: string;
 updatedAt: string;
}`}</Pre>
 </SubSection>
 <SubSection id="hooks-transport-types" icon="alt_route" title="Transport types — when to use each">
 <p>
 Four transport types cover three different operator economics.
 Pick by latency + extensibility tradeoff:
 </p>
 <ul className="list-disc pl-5 space-y-2 text-sm">
 <li>
 <strong>
 <Code>builtin</Code>
 </strong>{" "}
 — in-process TypeScript handler in{" "}
 <Code>mcp/agent/lib/hook-builtins/</Code>. Operator picks the
 builtin by name + fills a dynamic config form (no code edits,
 no subprocess, no HTTP round-trip). Latency: microseconds.
 Right for <em>framework-side primitives</em>{" "}
 (slack approval, rate-limit, memory injection,
 pre-compact warnings, cost-warn-over-budget) — features that
 ship with every deployment and benefit from in-process speed.
 Catalog: <Code>GET /api/agent/hooks/builtins</Code> enumerates
 what&apos;s in the current image.
 </li>
 <li>
 <strong>
 <Code>http</Code>
 </strong>{" "}
 — POST the JSON payload to an operator-supplied URL. Latency:
 50-200ms per HTTP round-trip. Right for{" "}
 <em>bring-your-own integrations</em>: a customer-managed
 webhook receiver (Lambda / Cloud Run / on-prem service) that
 implements policy specific to their environment. Slack
 approval is also available as an HTTP hook pattern; new
 installs should prefer the <Code>builtin</Code> form.
 </li>
 <li>
 <strong>
 <Code>command</Code>
 </strong>{" "}
 — spawn a subprocess with the payload on stdin, parse stdout
 as the result. Latency: 20-50ms subprocess spawn + handler
 run-time. Right for <em>policy scripts</em> the operator
 maintains in their own SCM (a Python policy engine, a shell
 script that calls out to LDAP, etc.). The script can have
 any deps it likes — Phantom doesn&apos;t care.
 </li>
 <li>
 <strong>
 <Code>agent</Code>
 </strong>{" "}
 — invoke a registered MCP tool as a hook handler. Reserved
 for a future feature; not implemented today. Entry-point
 plugins use the new <Code>plugin</Code> transport instead
 (see below).
 </li>
 <li>
 <strong>
 <Code>plugin</Code>
 </strong>{" "}
 — invoke a plugin-contributed handler from the{" "}
 <Code>phantom.hooks</Code> entry-point group. Plugin
 handlers live in Python, the hook-runner lives in TS, the
 agent bridges via{" "}
 <Code>POST /api/v1/plugin-hooks/{"{name}"}/invoke</Code>{" "}
 (MCP runs the handler on a thread pool with a hard timeout,
 returns the result, hook-runner translates to{" "}
 <Code>HookResult</Code>). Config is plugin-defined; the{" "}
 <Code>/settings/hooks</Code> form ships a generic JSON
 editor since TS can&apos;t introspect Python entry-point
 schemas.
 </li>
 </ul>
 <p style={{ marginTop: 12 }}>
 The <Code>builtin</Code> transport doesn&apos;t replace{" "}
 <Code>command</Code> /<Code>http</Code> — it complements them.
 Operators who need bespoke per-deployment behavior keep those
 transports; framework-side primitives get the fast path.
 </p>
 </SubSection>
 <SubSection icon="alt_route" title="Dispatcher">
 <p>
 <Code>lib/hook-runner.ts:dispatchHooks(event, payload)</Code>:
 </p>
 <ol className="list-decimal pl-5 space-y-1 text-sm">
 <li>
 Load matching hooks from MCP{" "}
 <Code>/api/v1/hooks?event={`{event}`}</Code> (no in-process
 cache; loaded fresh per fire-site, file is small).
 </li>
 <li>
 Filter by <Code>HookMatcher</Code>:{" "}
 <Code>toolGlob</Code> for PreToolUse/PostToolUse,{" "}
 <Code>triggerPrefix</Code> for job-driven runs.
 </li>
 <li>
 Sort by priority asc.
 </li>
 <li>
 Run each through its transport. Apply failurePolicy on
 error.
 </li>
 <li>
 Aggregate decision (deny &gt; ask &gt; allow). Concat all{" "}
 <Code>injectContext</Code> values.
 </li>
 </ol>
 </SubSection>
 <SubSection icon="speed" title="Why fresh load (not cached)?">
 <p>
 Hooks are policy. Operators expect &ldquo;disable this hook&rdquo;
 to take effect immediately, not after a TTL. The hooks file
 per chat-route process is small (under 10 hooks in typical
 deploys); the MCP round-trip is &lt;100ms. Fresh-load
 simplifies semantics; we add caching only if it becomes a
 measurable problem.
 </p>
 </SubSection>
 <SubSection icon="security" title="Failure policy semantics">
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <Code>block</Code> — Treat hook error as deny (most paranoid).
 Right for production policy hooks where availability matters
 less than enforcement.
 </li>
 <li>
 <Code>allow</Code> — Treat hook error as no-op. Right for
 best-effort notification hooks.
 </li>
 <li>
 <Code>warn</Code> (default) — Same as allow but logs a
 warning. Visible without blocking.
 </li>
 </ul>
 </SubSection>

 <SubSection icon="account_tree" title="Per-transport walkthroughs">
 <p>
 Each transport implements the same <Code>HookResult</Code>{" "}
 contract but the wire format + failure modes differ. End-to-
 end walkthroughs for a single <Code>PreToolUse</Code> fire-site
 below; the pattern generalises to the other nine events:
 </p>

 <div style={{ marginTop: 10, marginBottom: 4 }}>
 <strong>builtin</strong>
 </div>
 <Pre>{`chat-route → dispatchHooks('PreToolUse', { tool, args })
  → load matching hooks                           (fresh from MCP)
  → for hook where transport.type === 'builtin':
      handler = BUILTIN_REGISTRY[transport.name]   (lookup by name)
      result  = await handler(payload, config)     (in-process call)
  → aggregate HookResult { decision, reason?, injectContext? }

Latency: microseconds. Failure mode: thrown exception → failurePolicy
(block | allow | warn). Right for slack-approval, rate-limit,
memory-injection — primitives that ship with every Phantom deploy.`}</Pre>

 <div style={{ marginTop: 14, marginBottom: 4 }}>
 <strong>http</strong>
 </div>
 <Pre>{`chat-route → dispatchHooks('PreToolUse', { tool, args })
  → for hook where transport.type === 'http':
      POST transport.url
        Content-Type: application/json
        Authorization: <transport.authHeader>?  (operator-supplied)
        Body: { event, payload, hook: { id, name } }
      Response: 200 + JSON { decision, reason?, injectContext? }
                OR non-2xx → failurePolicy
  → aggregate

Latency: 50-200ms per HTTP round-trip. Right for bring-your-own
integrations: Lambda/CloudRun/on-prem service implementing
environment-specific policy. Receiver MUST respond within
timeoutMs (default 5s) or failurePolicy fires.`}</Pre>

 <div style={{ marginTop: 14, marginBottom: 4 }}>
 <strong>command</strong>
 </div>
 <Pre>{`chat-route → dispatchHooks('PreToolUse', { tool, args })
  → for hook where transport.type === 'command':
      child = spawn(transport.argv, { stdio: ['pipe', 'pipe', 'pipe'] })
      child.stdin.write(JSON.stringify({ event, payload, hook }))
      child.stdin.end()
      Wait up to timeoutMs for exit (kill -SIGTERM on overrun)
      Parse stdout as JSON HookResult
      stderr drained into audit row regardless of outcome
  → aggregate

Latency: 20-50ms subprocess spawn + handler runtime. Right for
operator-maintained policy scripts (a Python policy engine, a
shell script that calls LDAP, etc.). Subprocess can use any
deps — Phantom doesn't care.`}</Pre>

 <div style={{ marginTop: 14, marginBottom: 4 }}>
 <strong>plugin</strong>
 </div>
 <Pre>{`chat-route → dispatchHooks('PreToolUse', { tool, args })
  → for hook where transport.type === 'plugin':
      POST /api/v1/plugin-hooks/{transport.handlerName}/invoke
        Body: { event, payload, config: transport.config }
      MCP runs handler on a thread pool
        with timeoutMs hard limit (CPU-thread cap → no runaway)
      Handler returns Python dict → MCP serialises to HookResult JSON
  → hook-runner translates to TS HookResult
  → aggregate

Latency: 5-30ms (in-process Python call inside the agent container,
no subprocess spawn). Right for vendor-distributed policy
packages — pip-install + restart, plugin contributes itself to
the entry-point group.`}</Pre>

 <div style={{ marginTop: 14, marginBottom: 4 }}>
 <strong>agent</strong>
 </div>
 <Pre>{`Reserved transport. Hook contract carries the discriminator + form
support today, but no fire-site is yet wired to invoke a registered
MCP tool as a hook handler. Documented here so operators don't
mistake the form option for an active path. New deploys should use
the plugin transport instead.`}</Pre>
 </SubSection>

 <SubSection icon="event_note" title="Fire-site catalog — what payload arrives where">
 <p>
 The 10 fire-sites and their payload shapes. Hook authors read
 this to know which fields to expect on each event:
 </p>
 <Pre>{`PreToolUse          { tool, args, sessionId, actor }
                    decision: deny | ask | allow
                    injectContext: prepended to next model turn

PostToolUse         { tool, args, result, durationMs, sessionId }
                    decision: ignored (post-hoc)
                    injectContext: appended as observation

UserPromptSubmit    { prompt, sessionId, actor }
                    decision: deny → reject the turn
                    injectContext: prepended to user message

RunStart            { sessionId, actor, runId }
                    decision: deny → reject the run
                    injectContext: ignored (no model call yet)

RunEnd              { sessionId, runId, statusReason, durationMs }
                    decision: ignored
                    injectContext: ignored — terminal event

Notification        { kind, title, body, link?, severity }
                    decision: ignored
                    injectContext: ignored — emit-only

SubagentStart       { subagentName, sessionId, parentRunId }
                    decision: deny → reject the subagent dispatch
                    injectContext: prepended to subagent system prompt

SubagentStop        { subagentName, sessionId, runId, statusReason }
                    decision: ignored
                    injectContext: ignored — terminal event

PreCompact          { sessionId, droppedCount, droppedTokens }
                    decision: deny → skip compaction this turn
                    injectContext: ignored — model not invoked

PostCompact         { sessionId, checkpointId, durationMs }
                    decision: ignored
                    injectContext: ignored — bookkeeping event`}</Pre>
 <p className="text-sm text-on-surface-variant">
 Payloads are sanitised before write — secret-store paths and
 token values never appear in <Code>args</Code> /{" "}
 <Code>result</Code> blobs. The same{" "}
 <Code>_sanitize(meta)</Code> helper that protects audit rows
 runs on every hook payload.
 </p>
 </SubSection>

 <SubSection icon="api" title="REST + UI surface">
 <Pre>{`GET    /api/v1/hooks                  -- list (cookie OR bearer)
GET    /api/v1/hooks/{id}             -- single
POST   /api/v1/hooks                  -- create
PUT    /api/v1/hooks/{id}             -- replace
DELETE /api/v1/hooks/{id}             -- remove
GET    /api/v1/hooks/builtins         -- enumerate the in-image builtin catalog
POST   /api/v1/hooks/{id}/test        -- fire with synthetic payload (dry-run)

UI surface: /settings/hooks            -- create/edit/disable + last-fired column
            /observability/events     -- filter by action ∈ {hook_fire, hook_denied, hook_error}`}</Pre>
 </SubSection>
 </Section>
);
}

function Tasks() {
 return (
 <Section id="tasks" icon="pending_actions" title="Task Registry">
 <p>
 The task registry is the persisted home for every long-running
 unit of work the chat-route spawns or observes: scenario
 workers, compaction summarizers, CALDERA operations, hook
 subprocess invocations, subagent runs. The diagram below shows
 the task state machine alongside connector and session — three
 subsystems sharing the same persistence + transition pattern.
 </p>

 <StateMachinesAtlas />

 <p style={{ marginTop: 12 }}>
 More detail on the task subsystem follows; the connector state
 machine has its own deep-dive in{" "}
 <Link href="#connector-state" className="link">
 Connector State Machine
 </Link>
 .
 </p>
 <SubSection icon="schema" title="Task model">
 <Pre>{`Task {
 id uuid
 kind 'scenario_worker' | 'caldera_operation' |
 'xsiam_xql' | 'compaction' | 'hook_command' |
 'subagent' | etc. (free-form)
 status 'pending' | 'running' | 'succeeded' |
 'failed' | 'aborted'
 title operator-friendly label
 parent_session_id chat session that spawned this (NULL
 for cron / system-spawned)
 progress 0.0.. 1.0
 progress_label 'step 3 of 10: generating IOCs'
 output final result on success / error msg on failure
 cancel_token opaque; reserved for future operator-attribution
 meta_json kind-specific metadata
 created_at, updated_at, completed_at
}`}</Pre>
 </SubSection>
 <SubSection icon="auto_mode" title="State transitions">
 <Pre>{`pending → running, aborted, failed
running → succeeded, failed, aborted
terminal → no transitions (sticky)`}</Pre>
 <p>
 Transitions validated in{" "}
 <Code>SqliteTaskStore.transition()</Code>. Final progress on
 succeeded snaps to 1.0; failed/aborted preserve the last
 reported value (helps the UI show &ldquo;we got 60% through
 before the abort&rdquo;).
 </p>
 </SubSection>
 <SubSection icon="speed" title="is_aborted() polling primitive">
 <p>
 Workers periodically call <Code>is_aborted(task_id)</Code> —
 a single indexed lookup on{" "}
 <Code>(id, status)</Code> — to know whether to bail. Cheap
 enough to call between every progress step.
 </p>
 </SubSection>
 <SubSection icon="audit" title="Audit row pattern">
 <p>
 Lifecycle transitions audit cleanly:{" "}
 <Code>task_created</Code> on POST,{" "}
 <Code>task_started</Code> / <Code>task_completed</Code> /{" "}
 <Code>task_failed</Code> / <Code>task_aborted</Code> on
 transition. Progress patches DON&apos;T audit (high-volume).
 </p>
 </SubSection>
 </Section>
);
}

function PlanMode() {
 return (
 <Section id="plan-mode" icon="map" title="Plan Mode">
 <p>
 collapses multi-tool approval into a single
 approve-once-execute-many flow. <Code>/plan &lt;prompt&gt;</Code>{" "}
 runs the prompt with{" "}
 <Code>PLAN_MODE_INSTRUCTIONS</Code> as the system text and NO
 tools wired. The model emits a structured plan (numbered steps,
 each with tool name + args + risk callout). Operator reviews;
 sends original prompt without /plan to execute.
 </p>
 <SubSection icon="block" title="Why no tools wired during planning">
 <p>
 <Code>callGemini()</Code> with empty tool catalog means the
 model can&apos;t accidentally execute mid-plan. The plan is
 PURE TEXT — even if the model produces a function call, the
 chat-route&apos;s tool dispatch loop never runs (planning
 uses <Code>summarizeViaGemini</Code> which doesn&apos;t loop).
 </p>
 </SubSection>
 <SubSection icon="badge" title="Plan persistence">
 <p>
 The plan text is persisted as a system message with{" "}
 <Code>meta.kind=&apos;plan-proposed&apos;</Code> +{" "}
 <Code>source_prompt</Code> +{" "}
 <Code>proposed_at</Code>. The chat thread renders it as a
 distinct PlanCard (tertiary tint, map icon). On reload, the
 card re-renders from the persisted system row.
 </p>
 </SubSection>
 <SubSection icon="psychology" title="Per-turn, not persistent">
 <p>
 Phantom&apos;s plan mode is per-turn (slash command on a
 specific message), not a workspace-wide setting. Rationale: a
 permanent setting trains operators to dismiss every plan card;
 a per-turn opt-in keeps friction proportional to operator
 intent.
 </p>
 </SubSection>
 </Section>
);
}

// ConnectorsLifecycleSvg
// Inline SVG showing the full connector/instance lifecycle: two origin
// paths (bundle vs user upload), the 5 storage layers, schema validation,
// marketplace catalog → install → instance → container spawn → runtime
// tool routing.
//
// Colors use Material You-ish tokens that read on both light + dark.
// Strokes + fills are explicit (not CSS vars) so the SVG renders
// consistently in the help page regardless of theme — accessibility
// concern outweighs perfect theme alignment for a single diagram.
function ConnectorsLifecycleSvg() {
 return (
 <svg
 xmlns="http://www.w3.org/2000/svg"
 viewBox="0 0 1100 820"
 width="100%"
 style={{ maxWidth: 1100, display: "block", margin: "0 auto", height: "auto" }}
 role="img"
 aria-label="Connectors + instances lifecycle: origins, storage, install, instance creation, container spawn, runtime"
 >
 <defs>
 <marker
 id="arrow-blue"
 viewBox="0 0 10 10"
 refX="9"
 refY="5"
 markerWidth="6"
 markerHeight="6"
 orient="auto-start-reverse"
 >
 <path d="M 0 0 L 10 5 L 0 10 z" fill="#60a5fa" />
 </marker>
 <marker
 id="arrow-purple"
 viewBox="0 0 10 10"
 refX="9"
 refY="5"
 markerWidth="6"
 markerHeight="6"
 orient="auto-start-reverse"
 >
 <path d="M 0 0 L 10 5 L 0 10 z" fill="#c084fc" />
 </marker>
 <marker
 id="arrow-green"
 viewBox="0 0 10 10"
 refX="9"
 refY="5"
 markerWidth="6"
 markerHeight="6"
 orient="auto-start-reverse"
 >
 <path d="M 0 0 L 10 5 L 0 10 z" fill="#34d399" />
 </marker>
 <marker
 id="arrow-orange"
 viewBox="0 0 10 10"
 refX="9"
 refY="5"
 markerWidth="6"
 markerHeight="6"
 orient="auto-start-reverse"
 >
 <path d="M 0 0 L 10 5 L 0 10 z" fill="#fb923c" />
 </marker>
 </defs>

 {/* Background */}
 <rect width="1100" height="820" fill="#0a0e1a" rx="14" />

 {/* Title */}
 <text
 x="550"
 y="32"
 fill="#e5e7eb"
 fontSize="16"
 fontWeight="600"
 textAnchor="middle"
 fontFamily="ui-sans-serif, system-ui, sans-serif"
 >
 Connector & Instance Lifecycle
 </text>
 <text
 x="550"
 y="52"
 fill="#94a3b8"
 fontSize="11"
 textAnchor="middle"
 fontFamily="ui-sans-serif, system-ui, sans-serif"
 >
 Two origin paths → one schema validator → catalog → install → instance config → container spawn → runtime routing
 </text>

 {/* ROW 1 — Origins */}
 <text x="40" y="92" fill="#94a3b8" fontSize="11" fontWeight="600" fontFamily="ui-sans-serif, system-ui, sans-serif">
 1. ORIGIN
 </text>

 {/* Bundle author box */}
 <rect x="120" y="78" width="180" height="64" rx="10" fill="#0f1e3a" stroke="#60a5fa" strokeWidth="1.5" />
 <text x="210" y="100" fill="#e5e7eb" fontSize="12" fontWeight="600" textAnchor="middle" fontFamily="ui-sans-serif, system-ui, sans-serif">
 Bundle author
 </text>
 <text x="210" y="118" fill="#94a3b8" fontSize="10" textAnchor="middle" fontFamily="ui-monospace, monospace">
 git PR · CI builds image
 </text>
 <text x="210" y="132" fill="#94a3b8" fontSize="10" textAnchor="middle" fontFamily="ui-monospace, monospace">
 + digest manifest entry
 </text>

 {/* User upload box */}
 <rect x="800" y="78" width="180" height="64" rx="10" fill="#2a1238" stroke="#c084fc" strokeWidth="1.5" />
 <text x="890" y="100" fill="#e5e7eb" fontSize="12" fontWeight="600" textAnchor="middle" fontFamily="ui-sans-serif, system-ui, sans-serif">
 Operator (UI upload)
 </text>
 <text x="890" y="118" fill="#94a3b8" fontSize="10" textAnchor="middle" fontFamily="ui-monospace, monospace">
 POST /api/agent/
 </text>
 <text x="890" y="132" fill="#94a3b8" fontSize="10" textAnchor="middle" fontFamily="ui-monospace, monospace">
 marketplace/upload
 </text>

 {/* ROW 2 — YAML storage */}
 <text x="40" y="190" fill="#94a3b8" fontSize="11" fontWeight="600" fontFamily="ui-sans-serif, system-ui, sans-serif">
 2. STORAGE
 </text>

 {/* Bundle YAML path */}
 <rect x="120" y="176" width="320" height="72" rx="10" fill="#0a1530" stroke="#60a5fa" strokeWidth="1" />
 <text x="280" y="198" fill="#e5e7eb" fontSize="12" fontWeight="600" textAnchor="middle" fontFamily="ui-sans-serif, system-ui, sans-serif">
 Bundle YAML
 </text>
 <text x="280" y="216" fill="#94a3b8" fontSize="10" textAnchor="middle" fontFamily="ui-monospace, monospace">
 /app/bundle/connectors/&lt;id&gt;/connector.yaml
 </text>
 <text x="280" y="232" fill="#64748b" fontSize="9" textAnchor="middle" fontFamily="ui-monospace, monospace">
 baked into phantom-agent image · COPY at build time
 </text>

 {/* Arrow: bundle author → bundle YAML */}
 <line x1="210" y1="142" x2="280" y2="176" stroke="#60a5fa" strokeWidth="1.5" markerEnd="url(#arrow-blue)" />

 {/* User YAML path */}
 <rect x="660" y="176" width="320" height="72" rx="10" fill="#1a0a2e" stroke="#c084fc" strokeWidth="1" />
 <text x="820" y="198" fill="#e5e7eb" fontSize="12" fontWeight="600" textAnchor="middle" fontFamily="ui-sans-serif, system-ui, sans-serif">
 User YAML
 </text>
 <text x="820" y="216" fill="#94a3b8" fontSize="10" textAnchor="middle" fontFamily="ui-monospace, monospace">
 /app/data/user_connectors/&lt;id&gt;/connector.yaml
 </text>
 <text x="820" y="232" fill="#64748b" fontSize="9" textAnchor="middle" fontFamily="ui-monospace, monospace">
 phantom_mcp_data volume · persistent across upgrades
 </text>

 {/* Arrow: user upload → user YAML */}
 <line x1="890" y1="142" x2="820" y2="176" stroke="#c084fc" strokeWidth="1.5" markerEnd="url(#arrow-purple)" />

 {/* ROW 3 — Schema validation */}
 <text x="40" y="298" fill="#94a3b8" fontSize="11" fontWeight="600" fontFamily="ui-sans-serif, system-ui, sans-serif">
 3. VALIDATE
 </text>

 <rect x="380" y="282" width="340" height="62" rx="10" fill="#3a2a05" stroke="#fb923c" strokeWidth="1.5" />
 <text x="550" y="304" fill="#e5e7eb" fontSize="12" fontWeight="600" textAnchor="middle" fontFamily="ui-sans-serif, system-ui, sans-serif">
 validate_connector_spec()
 </text>
 <text x="550" y="322" fill="#94a3b8" fontSize="10" textAnchor="middle" fontFamily="ui-monospace, monospace">
 jsonschema Draft 2020-12 ↦ connector.schema.json
 </text>
 <text x="550" y="336" fill="#64748b" fontSize="9" textAnchor="middle" fontFamily="ui-monospace, monospace">
 boot-time for bundles · upload-time + boot-time for user
 </text>

 {/* Arrows: YAMLs → validator */}
 <line x1="280" y1="248" x2="450" y2="282" stroke="#fb923c" strokeWidth="1.5" markerEnd="url(#arrow-orange)" />
 <line x1="820" y1="248" x2="650" y2="282" stroke="#fb923c" strokeWidth="1.5" markerEnd="url(#arrow-orange)" />

 {/* ROW 4 — Catalog + install */}
 <text x="40" y="392" fill="#94a3b8" fontSize="11" fontWeight="600" fontFamily="ui-sans-serif, system-ui, sans-serif">
 4. CATALOG
 </text>

 {/* In-memory catalog */}
 <rect x="120" y="378" width="280" height="68" rx="10" fill="#0a2a1f" stroke="#34d399" strokeWidth="1" />
 <text x="260" y="400" fill="#e5e7eb" fontSize="12" fontWeight="600" textAnchor="middle" fontFamily="ui-sans-serif, system-ui, sans-serif">
 _scan_catalogue() (in-memory)
 </text>
 <text x="260" y="418" fill="#94a3b8" fontSize="10" textAnchor="middle" fontFamily="ui-monospace, monospace">
 GET /api/v1/marketplace
 </text>
 <text x="260" y="432" fill="#64748b" fontSize="9" textAnchor="middle" fontFamily="ui-monospace, monospace">
 powers Marketplace tab cards
 </text>

 {/* marketplace.db */}
 <rect x="540" y="378" width="280" height="68" rx="10" fill="#0a2a1f" stroke="#34d399" strokeWidth="1" />
 <text x="680" y="400" fill="#e5e7eb" fontSize="12" fontWeight="600" textAnchor="middle" fontFamily="ui-sans-serif, system-ui, sans-serif">
 marketplace.db
 </text>
 <text x="680" y="418" fill="#94a3b8" fontSize="10" textAnchor="middle" fontFamily="ui-monospace, monospace">
 sqlite · install state + origin
 </text>
 <text x="680" y="432" fill="#64748b" fontSize="9" textAnchor="middle" fontFamily="ui-monospace, monospace">
 row per installed connector_id · catalog flip only
 </text>

 {/* Arrow: validate → catalog */}
 <line x1="500" y1="344" x2="320" y2="378" stroke="#34d399" strokeWidth="1.5" markerEnd="url(#arrow-green)" />
 {/* Arrow: catalog → marketplace.db (install) */}
 <line x1="400" y1="412" x2="540" y2="412" stroke="#34d399" strokeWidth="1.5" markerEnd="url(#arrow-green)" />
 <text x="470" y="406" fill="#34d399" fontSize="9" textAnchor="middle" fontFamily="ui-monospace, monospace">
 POST install
 </text>

 {/* ROW 5 — Instance config + secrets */}
 <text x="40" y="496" fill="#94a3b8" fontSize="11" fontWeight="600" fontFamily="ui-sans-serif, system-ui, sans-serif">
 5. CONFIGURE
 </text>

 {/* instances.db */}
 <rect x="120" y="482" width="320" height="68" rx="10" fill="#0a2a1f" stroke="#34d399" strokeWidth="1" />
 <text x="280" y="504" fill="#e5e7eb" fontSize="12" fontWeight="600" textAnchor="middle" fontFamily="ui-sans-serif, system-ui, sans-serif">
 instances.db
 </text>
 <text x="280" y="522" fill="#94a3b8" fontSize="10" textAnchor="middle" fontFamily="ui-monospace, monospace">
 sqlite · non-secret config + state
 </text>
 <text x="280" y="536" fill="#64748b" fontSize="9" textAnchor="middle" fontFamily="ui-monospace, monospace">
 status: pending → connected → failed | needs-auth
 </text>

 {/* SecretStore */}
 <rect x="660" y="482" width="320" height="68" rx="10" fill="#2a0f1f" stroke="#ef4444" strokeWidth="1" />
 <text x="820" y="504" fill="#e5e7eb" fontSize="12" fontWeight="600" textAnchor="middle" fontFamily="ui-sans-serif, system-ui, sans-serif">
 SecretStore
 </text>
 <text x="820" y="522" fill="#94a3b8" fontSize="10" textAnchor="middle" fontFamily="ui-monospace, monospace">
 AES-GCM at rest · KEK from .env
 </text>
 <text x="820" y="536" fill="#64748b" fontSize="9" textAnchor="middle" fontFamily="ui-monospace, monospace">
 connectors/&lt;id&gt;/instances/&lt;n&gt;/&lt;slot&gt;
 </text>

 {/* Arrow: marketplace.db → instances.db + SecretStore */}
 <line x1="680" y1="446" x2="320" y2="482" stroke="#34d399" strokeWidth="1.5" markerEnd="url(#arrow-green)" />
 <line x1="680" y1="446" x2="820" y2="482" stroke="#ef4444" strokeWidth="1.5" markerEnd="url(#arrow-blue)" />
 <text x="540" y="468" fill="#94a3b8" fontSize="9" textAnchor="middle" fontFamily="ui-monospace, monospace">
 operator fills setup form
 </text>

 {/* ROW 6 — Spawn */}
 <text x="40" y="600" fill="#94a3b8" fontSize="11" fontWeight="600" fontFamily="ui-sans-serif, system-ui, sans-serif">
 6. SPAWN
 </text>

 {/* phantom-updater */}
 <rect x="120" y="586" width="280" height="76" rx="10" fill="#1a0a2e" stroke="#c084fc" strokeWidth="1.5" />
 <text x="260" y="608" fill="#e5e7eb" fontSize="12" fontWeight="600" textAnchor="middle" fontFamily="ui-sans-serif, system-ui, sans-serif">
 phantom-updater
 </text>
 <text x="260" y="626" fill="#94a3b8" fontSize="10" textAnchor="middle" fontFamily="ui-monospace, monospace">
 _connector_image_ref(id, version)
 </text>
 <text x="260" y="640" fill="#64748b" fontSize="9" textAnchor="middle" fontFamily="ui-monospace, monospace">
 reads /host/.env · derives ghcr.io/.../@sha256:…
 </text>
 <text x="260" y="654" fill="#64748b" fontSize="9" textAnchor="middle" fontFamily="ui-monospace, monospace">
 docker_run(image, network, volume)
 </text>

 {/* Per-instance container */}
 <rect x="540" y="586" width="440" height="76" rx="10" fill="#2a1238" stroke="#c084fc" strokeWidth="1.5" />
 <text x="760" y="608" fill="#e5e7eb" fontSize="12" fontWeight="600" textAnchor="middle" fontFamily="ui-sans-serif, system-ui, sans-serif">
 phantom-connector-&lt;id&gt;-&lt;name&gt;
 </text>
 <text x="760" y="626" fill="#94a3b8" fontSize="10" textAnchor="middle" fontFamily="ui-monospace, monospace">
 FastMCP server on :9000 · reads secrets via SecretStoreReader
 </text>
 <text x="760" y="640" fill="#64748b" fontSize="9" textAnchor="middle" fontFamily="ui-monospace, monospace">
 image digest-pinned · digest-pinning invariant preserves
 </text>
 <text x="760" y="654" fill="#64748b" fontSize="9" textAnchor="middle" fontFamily="ui-monospace, monospace">
 in-memory state across stack upgrades
 </text>

 {/* Arrow: instances → updater */}
 <line x1="280" y1="550" x2="260" y2="586" stroke="#c084fc" strokeWidth="1.5" markerEnd="url(#arrow-purple)" />
 <text x="260" y="572" fill="#94a3b8" fontSize="9" textAnchor="middle" fontFamily="ui-monospace, monospace">
 POST start
 </text>
 {/* Arrow: updater → container */}
 <line x1="400" y1="624" x2="540" y2="624" stroke="#c084fc" strokeWidth="1.5" markerEnd="url(#arrow-purple)" />
 <text x="470" y="618" fill="#94a3b8" fontSize="9" textAnchor="middle" fontFamily="ui-monospace, monospace">
 docker spawn
 </text>
 {/* Arrow: SecretStore → container (read decrypt) */}
 <path d="M 820 550 Q 850 570 770 586" stroke="#ef4444" strokeWidth="1.2" fill="none" strokeDasharray="3 3" markerEnd="url(#arrow-blue)" />
 <text x="860" y="572" fill="#ef4444" fontSize="9" textAnchor="middle" fontFamily="ui-monospace, monospace">
 decrypt via KEK
 </text>
 {/* Arrow: container → instances.db (callback container_url) */}
 <path d="M 540 624 Q 460 670 280 550" stroke="#34d399" strokeWidth="1.2" fill="none" strokeDasharray="3 3" markerEnd="url(#arrow-green)" />
 <text x="370" y="690" fill="#34d399" fontSize="9" textAnchor="middle" fontFamily="ui-monospace, monospace">
 callback: container_url
 </text>

 {/* ROW 7 — Runtime tool dispatch */}
 <text x="40" y="730" fill="#94a3b8" fontSize="11" fontWeight="600" fontFamily="ui-sans-serif, system-ui, sans-serif">
 7. RUNTIME
 </text>

 <rect x="120" y="716" width="860" height="80" rx="10" fill="#0f1e3a" stroke="#60a5fa" strokeWidth="1.5" />
 <text x="550" y="738" fill="#e5e7eb" fontSize="12" fontWeight="600" textAnchor="middle" fontFamily="ui-sans-serif, system-ui, sans-serif">
 Agent MCP connector_loader (routing proxy)
 </text>
 <text x="550" y="756" fill="#94a3b8" fontSize="10" textAnchor="middle" fontFamily="ui-monospace, monospace">
 tool call: cortex-docs/cortex_search → look up container_url in instances.db
 </text>
 <text x="550" y="770" fill="#94a3b8" fontSize="10" textAnchor="middle" fontFamily="ui-monospace, monospace">
 → open MCP-over-HTTP session to http://phantom-connector-&lt;id&gt;-&lt;name&gt;:9000
 </text>
 <text x="550" y="784" fill="#64748b" fontSize="9" textAnchor="middle" fontFamily="ui-monospace, monospace">
 errors classified → state machine: connected | failed | needs-auth
 </text>

 {/* Arrow: container → runtime row */}
 <line x1="760" y1="662" x2="600" y2="716" stroke="#60a5fa" strokeWidth="1.5" markerEnd="url(#arrow-blue)" />
 </svg>
);
}

function ConnectorsDesign() {
 return (
 <Section
 id="connectors-design"
 icon="schema"
 title="Connectors & Instances — End-to-end Design"
 >
 <p>
 A <Term>connector</Term> is a versioned spec (
 <Code>connector.yaml</Code>) describing how Phantom integrates with
 one external system — its tools, its config schema, its secrets,
 its OCI image. An <Term>instance</Term> is a configured deployment
 of a connector — a specific tenant/account with its own credentials
 and its own running container. The two concepts deliberately stay
 separate so one connector spec can drive many isolated tenants.
 </p>

 <p>
 The system has <strong>two origin paths</strong> for connectors
 (bundle-shipped vs operator-uploaded), <strong>five storage layers</strong>{" "}
 (YAML on disk, marketplace.db, instances.db, SecretStore,
 phantom-updater&apos;s docker daemon state), and{" "}
 <strong>three runtime actors</strong> (the agent&apos;s MCP, phantom-
 updater, and per-instance containers). The diagram below shows how
 they fit together; the subsections after it walk each step.
 </p>

 <SubSection icon="account_tree" title="End-to-end lifecycle">
 <div
 className="rounded-2xl overflow-hidden p-4"
 style={{
 background: "var(--m3-surface-container-low, rgba(255,255,255,0.02))",
 border: "0.5px solid var(--glass-border, rgba(255,255,255,0.08))",
 }}
 >
 <ConnectorsLifecycleSvg />
 </div>
 <p className="text-xs text-on-surface-variant/70 mt-3 italic">
 Two origin paths feed one schema validator → one catalog → one
 install table. Instance creation forks the path: config goes to
 instances.db, secrets go to SecretStore, and phantom-updater
 derives the image ref + spawns a per-instance container. The
 agent&apos;s connector-loader proxies tool calls over MCP-over-
 HTTP to the right instance container at runtime.
 </p>
 </SubSection>

 <SubSection icon="inventory_2" title="The two origin paths">
 <p>
 Every connector enters the system through one of two paths. The
 difference is <em>where the YAML file lives</em> + <em>who owns
 the image</em> — everything downstream is identical.
 </p>
 <Pre>{`BUNDLE                                  USER (uploaded)
──────                                  ───────────────
Path:   bundles/spark/connectors/<id>/  Path:   /app/data/user_connectors/<id>/
        connector.yaml                          connector.yaml
Origin: ships in the phantom-agent      Origin: POST /api/v1/marketplace/upload
        image (Dockerfile COPY)                 (multipart from /connectors UI)
Image:  derived at runtime from         Image:  REQUIRED — operator declares
        digest manifest:                        an OCI ref in the YAML:
        ghcr.io/<owner>/                          image: ghcr.io/your-org/
          phantom-connector-<id>                          your-connector:v1.2
          @\${DIGEST_PHANTOM_CONNECTOR_<ID>}
        (read from /host/.env by                 phantom-updater pulls this URL
         phantom-updater at startup)             directly.
Schema: bundle-validates at MCP boot    Schema: validates at upload time
        via validate_connector_spec             (POST endpoint), again at next
        (jsonschema)                            MCP boot.
Edit:   git PR + new release            Edit:   POST upload of a new YAML
        (the image gets rebuilt +               with the same id (DELETE the
         redigested by CI)                       existing user-connector row
                                                 first → 409 otherwise).`}</Pre>
 <p>
 Bundle vs user is informational on the catalogue side but{" "}
 <strong>authoritative on the install side</strong> — the
 marketplace.db row pins origin at first install. The UI shows a
 small badge per card so an operator can audit provenance at a
 glance. See{" "}
 <a href="#marketplace-logic" className="link">Marketplace Logic</a>{" "}
 for the catalog-side details.
 </p>
 </SubSection>

 <SubSection icon="database" title="The five storage layers">
 <p>
 The connector + instance lifecycle touches five distinct stores.
 Each has a different shape, a different write path, and a
 different reset semantics. Operators occasionally need this map
 when triaging &ldquo;I deleted X and Y is now in a weird state.&rdquo;
 </p>
 <table className="w-full text-xs my-3 border-collapse">
 <thead>
 <tr style={{ borderBottom: "1px solid var(--glass-border)" }}>
 <th className="text-left py-2 px-2 font-label uppercase tracking-wider text-on-surface-variant">
 Store
 </th>
 <th className="text-left py-2 px-2 font-label uppercase tracking-wider text-on-surface-variant">
 Content
 </th>
 <th className="text-left py-2 px-2 font-label uppercase tracking-wider text-on-surface-variant">
 Backed by
 </th>
 <th className="text-left py-2 px-2 font-label uppercase tracking-wider text-on-surface-variant">
 Lifecycle
 </th>
 </tr>
 </thead>
 <tbody>
 <tr style={{ borderBottom: "0.5px solid var(--glass-border)" }}>
 <td className="py-2 px-2 align-top">
 <Code>connector.yaml</Code>
 <span className="block text-on-surface-variant/60 text-[10px]">
 bundle path
 </span>
 </td>
 <td className="py-2 px-2 align-top">
 The spec itself — tools, configSchema, secretSlots, image,
 displayName, tags, logo (inline data URI).
 </td>
 <td className="py-2 px-2 align-top font-mono text-on-surface-variant">
 image file
 </td>
 <td className="py-2 px-2 align-top">
 Baked at <Code>docker build</Code>. Replaced on every
 phantom-agent image upgrade.
 </td>
 </tr>
 <tr style={{ borderBottom: "0.5px solid var(--glass-border)" }}>
 <td className="py-2 px-2 align-top">
 <Code>connector.yaml</Code>
 <span className="block text-on-surface-variant/60 text-[10px]">
 user path
 </span>
 </td>
 <td className="py-2 px-2 align-top">
 Same shape as the bundle path. Operator-owned (uploaded
 via the marketplace upload form).
 </td>
 <td className="py-2 px-2 align-top font-mono text-on-surface-variant">
 phantom_mcp_data volume
 </td>
 <td className="py-2 px-2 align-top">
 Persistent across upgrades. Cleared by{" "}
 <Code>phantom-factory-reset</Code> only.
 </td>
 </tr>
 <tr style={{ borderBottom: "0.5px solid var(--glass-border)" }}>
 <td className="py-2 px-2 align-top">
 <Code>marketplace.db</Code>
 </td>
 <td className="py-2 px-2 align-top">
 Install state per connector_id: <Code>installed_at</Code>,{" "}
 <Code>origin</Code> (bundle|user), <Code>version</Code>.
 No config or secrets here.
 </td>
 <td className="py-2 px-2 align-top font-mono text-on-surface-variant">
 sqlite in phantom_mcp_data
 </td>
 <td className="py-2 px-2 align-top">
 Persistent. Cleared by factory-reset. Survives both
 connector.yaml edits and image upgrades.
 </td>
 </tr>
 <tr style={{ borderBottom: "0.5px solid var(--glass-border)" }}>
 <td className="py-2 px-2 align-top">
 <Code>instances.db</Code>
 </td>
 <td className="py-2 px-2 align-top">
 Per-instance non-secret config (parsed from the operator&apos;s
 setup form), state (connected/failed/etc), and{" "}
 <Code>container_url</Code> (compose-DNS name set by
 phantom-updater after start).
 </td>
 <td className="py-2 px-2 align-top font-mono text-on-surface-variant">
 sqlite in phantom_mcp_data
 </td>
 <td className="py-2 px-2 align-top">
 Persistent. Surveys container lifecycle independently:
 a deleted container leaves an instance row in{" "}
 <Code>failed</Code> until manually reconciled.
 </td>
 </tr>
 <tr>
 <td className="py-2 px-2 align-top">
 <Code>SecretStore</Code>
 </td>
 <td className="py-2 px-2 align-top">
 Per-instance secrets keyed by{" "}
 <Code>connectors/&lt;id&gt;/instances/&lt;name&gt;/&lt;slot&gt;</Code>.
 AES-GCM at rest with KEK derived via PBKDF2 from{" "}
 <Code>PHANTOM_SECRET_KEK</Code> (lives in <Code>.env</Code>).
 </td>
 <td className="py-2 px-2 align-top font-mono text-on-surface-variant">
 dir tree in phantom_mcp_data
 </td>
 <td className="py-2 px-2 align-top">
 Persistent. <strong>Lose the KEK and ALL secrets are
 unrecoverable</strong> — back up{" "}
 <Code>PHANTOM_SECRET_KEK</Code> with your other deployment
 credentials.
 </td>
 </tr>
 </tbody>
 </table>
 <div
 className="rounded-xl p-3 my-3 text-xs"
 style={{
 background: "rgba(96, 165, 250, 0.08)",
 border: "0.5px solid rgba(96, 165, 250, 0.25)",
 color: "#94a3b8",
 }}
 >
 <strong>Note:</strong> the phantom-updater&apos;s docker daemon
 is technically a sixth store (per-instance container state).
 It&apos;s ephemeral — containers can be killed + recreated and
 the agent reconciles from <Code>instances.db</Code> +{" "}
 <Code>SecretStore</Code> on next instance startup. See{" "}
 <a href="#connector-containers" className="link">
 Per-instance Connector Containers
 </a>{" "}
 for the reconciliation contract.
 </div>
 </SubSection>

 <SubSection icon="route" title="Lifecycle walkthrough — author to runtime">
 <p>
 Following one connector — say <Code>cortex-docs</Code> — through
 its lifetime:
 </p>
 <ol className="list-decimal pl-5 space-y-2 text-sm">
 <li>
 <strong>Author</strong> — Phantom maintainer writes{" "}
 <Code>bundles/spark/connectors/cortex-docs/connector.yaml</Code>{" "}
 + the implementation in <Code>src/connector.py</Code>. PR lands;
 the release pipeline builds <Code>phantom-connector-cortex-docs</Code>{" "}
 image at this version&apos;s digest + writes{" "}
 <Code>DIGEST_PHANTOM_CONNECTOR_CORTEX_DOCS</Code> into the
 release manifest.
 </li>
 <li>
 <strong>Customer install</strong> — operator runs
 <Code> phantom-installer</Code>. installer pulls phantom-agent
 (which bakes <Code>bundles/spark/connectors/</Code> at{" "}
 <Code>/app/bundle/</Code>) + writes the digest manifest into{" "}
 <Code>/opt/phantom/.env</Code>. MCP boots,{" "}
 <Code>_scan_catalogue</Code> validates the YAML against
 <Code> connector.schema.json</Code>, registers the connector in
 the in-memory catalog.
 </li>
 <li>
 <strong>Marketplace browse</strong> — operator opens{" "}
 <Code>/connectors</Code> → Marketplace tab. UI fetches{" "}
 <Code>GET /api/agent/marketplace/installed</Code> (which proxies{" "}
 <Code>GET /api/v1/marketplace</Code>) → catalog summary +
 install state for each connector. Each card shows{" "}
 <Code>display_name</Code> + <Code>logo</Code> + tags +
 tools_count + an{" "}
 Install button (or Download icon for inspection).
 </li>
 <li>
 <strong>Install</strong> — operator clicks Install →{" "}
 <Code>POST /api/v1/marketplace/cortex-docs/install</Code> →
 row added to <Code>marketplace.db</Code> with origin pinned at{" "}
 <Code>bundle</Code>. <strong>No container is spawned yet</strong>{" "}
 — install is a catalog state flip, not a deployment.
 </li>
 <li>
 <strong>Configure instance</strong> — operator clicks Create
 Instance, fills the setup form (configSchema-driven). The
 form&apos;s setup fields go to{" "}
 <Code>POST /api/v1/instances</Code> body; secret slots get
 stashed in <Code>SecretStore</Code> via a separate request shape
 (see <a href="#secret-store" className="link">Secret Store</a>).
 The new instance row lands in <Code>instances.db</Code> with
 status <Code>pending</Code>.
 </li>
 <li>
 <strong>Container spawn</strong> — MCP reads the connector&apos;s
 runtimeMapping.style (must be <Code>container</Code>){" "}
 → POSTs to phantom-updater&apos;s
 <Code> /api/v1/connectors/cortex-docs/instances/&lt;name&gt;/start</Code>.{" "}
 phantom-updater derives image ref via{" "}
 <Code>_connector_image_ref</Code> (reads{" "}
 <Code>DIGEST_PHANTOM_CONNECTOR_CORTEX_DOCS</Code> from{" "}
 <Code>/host/.env</Code> — moved here from{" "}
 <Code>os.environ</Code> to a 30s-cached file read), then{" "}
 <Code>docker_run(image, name, network, volume)</Code>.
 </li>
 <li>
 <strong>Container init</strong> — the spawned{" "}
 <Code>phantom-connector-cortex-docs-&lt;name&gt;</Code> container
 reads its instance config + secrets from{" "}
 <Code>/app/data</Code> (mounted read-only) via the{" "}
 <Code>SecretStoreReader</Code> (decrypts using{" "}
 <Code>PHANTOM_SECRET_KEK</Code> from env). Starts a FastMCP
 server on :9000.
 </li>
 <li>
 <strong>Container URL callback</strong> — phantom-updater POSTs
 the resolved DNS{" "}
 (<Code>http://phantom-connector-cortex-docs-&lt;name&gt;:9000</Code>) back to{" "}
 <Code>/api/v1/instances/&lt;id&gt;/container_url</Code>; the agent
 stores it in <Code>instances.db</Code> + transitions status to{" "}
 <Code>connected</Code> on first successful probe.
 </li>
 <li>
 <strong>Tool call</strong> — operator runs a chat message that
 triggers a <Code>cortex-docs/cortex_search</Code> tool. MCP&apos;s{" "}
 <Code>connector_loader</Code> looks up the container_url for
 that instance, opens an MCP-over-HTTP session, forwards the
 tool call, returns the result. Per-tool latency adds the
 loopback HTTP cost (&lt;5ms) on top of the actual external API
 call.
 </li>
 <li>
 <strong>State transitions</strong> — failures (transport, 401/
 403, timeouts) get classified by{" "}
 <Code>route.ts:isAuthError</Code> and transition the instance
 to <Code>failed</Code> or <Code>needs-auth</Code>. See{" "}
 <a href="#connector-state" className="link">
 Connector State Machine
 </a>{" "}
 for the full state graph + classification.
 </li>
 </ol>
 </SubSection>

 <SubSection icon="bookmark" title="Where the operator sees what">
 <table className="w-full text-xs my-3 border-collapse">
 <thead>
 <tr style={{ borderBottom: "1px solid var(--glass-border)" }}>
 <th className="text-left py-2 px-2 font-label uppercase tracking-wider text-on-surface-variant">
 Question
 </th>
 <th className="text-left py-2 px-2 font-label uppercase tracking-wider text-on-surface-variant">
 Surface
 </th>
 </tr>
 </thead>
 <tbody>
 <tr style={{ borderBottom: "0.5px solid var(--glass-border)" }}>
 <td className="py-2 px-2 align-top">Which connectors exist?</td>
 <td className="py-2 px-2 align-top">
 <Code>/connectors</Code> → Marketplace tab (catalog +
 install state)
 </td>
 </tr>
 <tr style={{ borderBottom: "0.5px solid var(--glass-border)" }}>
 <td className="py-2 px-2 align-top">
 What does the YAML look like?
 </td>
 <td className="py-2 px-2 align-top">
 Download icon on each card →{" "}
 <Code>GET /api/agent/marketplace/&lt;id&gt;/download</Code>{" "}
 (logo inline data URI)
 </td>
 </tr>
 <tr style={{ borderBottom: "0.5px solid var(--glass-border)" }}>
 <td className="py-2 px-2 align-top">
 What image is actually running per instance?
 </td>
 <td className="py-2 px-2 align-top">
 <Code>/observability/connectors</Code> — shows the resolved
 image digest + tag/digest pinning badge per instance
 </td>
 </tr>
 <tr style={{ borderBottom: "0.5px solid var(--glass-border)" }}>
 <td className="py-2 px-2 align-top">
 What instances are configured?
 </td>
 <td className="py-2 px-2 align-top">
 <Code>/connectors</Code> → Instances tab. Per-instance
 state badge + edit/delete actions.
 </td>
 </tr>
 <tr style={{ borderBottom: "0.5px solid var(--glass-border)" }}>
 <td className="py-2 px-2 align-top">
 What secrets are stashed?
 </td>
 <td className="py-2 px-2 align-top">
 Slots are listed under the configSchema preview; values
 are never displayed (write-only). <Code>/observability/events</Code>{" "}
 has the audit trail of secret writes.
 </td>
 </tr>
 <tr>
 <td className="py-2 px-2 align-top">Fork or inspect a connector?</td>
 <td className="py-2 px-2 align-top">
 Download YAML → edit locally → upload as a user connector
 (with a different <Code>id</Code> + your own{" "}
 <Code>image:</Code>).
 </td>
 </tr>
 </tbody>
 </table>
 </SubSection>

 <SubSection icon="dynamic_form" title="Setup form widgets">
 <p className="text-sm leading-relaxed">
 The instance-creation form ({" "}
 <Code>/connectors → Create Instance</Code>) renders one input
 widget per <Code>configSchema</Code> property + one masked
 input per <Code>secretSlots[]</Code> entry. The widget is
 selected by the property&apos;s <Code>type</Code> field on the
 synthetic-card config block in{" "}
 <Code>mcp/agent/app/api/marketplace/connectors/route.ts</Code>{" "}
 (and, forward-looking, by an optional <Code>widget</Code>{" "}
 keyword on <Code>configSchema.properties.&lt;name&gt;</Code> in
 each <Code>connector.yaml</Code> — see{" "}
 <Code>connector.schema.json</Code>).
 </p>
 <p className="text-sm leading-relaxed mt-3">
 The full widget vocabulary, with what each renders + when to
 pick it:
 </p>
 <table className="w-full text-xs my-3 border-collapse">
 <thead>
 <tr style={{ borderBottom: "1px solid var(--glass-border)" }}>
 <th className="text-left py-2 px-2 font-label uppercase tracking-wider text-on-surface-variant">
 Widget
 </th>
 <th className="text-left py-2 px-2 font-label uppercase tracking-wider text-on-surface-variant">
 Renders
 </th>
 <th className="text-left py-2 px-2 font-label uppercase tracking-wider text-on-surface-variant">
 Use when
 </th>
 </tr>
 </thead>
 <tbody>
 <tr style={{ borderBottom: "0.5px solid var(--glass-border)" }}>
 <td className="py-2 px-2 align-top"><Code>text</Code></td>
 <td className="py-2 px-2 align-top">Plain text input</td>
 <td className="py-2 px-2 align-top">
 Short free-form strings (default for unknown types)
 </td>
 </tr>
 <tr style={{ borderBottom: "0.5px solid var(--glass-border)" }}>
 <td className="py-2 px-2 align-top"><Code>url</Code></td>
 <td className="py-2 px-2 align-top">
 Text input with <Code>inputMode=&quot;url&quot;</Code>
 </td>
 <td className="py-2 px-2 align-top">
 API endpoints, callback URLs — same as text + better mobile-keyboard hint
 </td>
 </tr>
 <tr style={{ borderBottom: "0.5px solid var(--glass-border)" }}>
 <td className="py-2 px-2 align-top"><Code>string</Code></td>
 <td className="py-2 px-2 align-top">Plain text input</td>
 <td className="py-2 px-2 align-top">
 Alias for text — used by JSON-Schema-style connector configs (api_id, IDs)
 </td>
 </tr>
 <tr style={{ borderBottom: "0.5px solid var(--glass-border)" }}>
 <td className="py-2 px-2 align-top"><Code>number</Code></td>
 <td className="py-2 px-2 align-top">
 Text input with <Code>inputMode=&quot;numeric&quot;</Code>
 </td>
 <td className="py-2 px-2 align-top">
 Integer / numeric tuning knobs (ports, timeouts, limits)
 </td>
 </tr>
 <tr style={{ borderBottom: "0.5px solid var(--glass-border)" }}>
 <td className="py-2 px-2 align-top">
 <Code>secret</Code> / <Code>password</Code>
 </td>
 <td className="py-2 px-2 align-top">
 Masked input with eye-toggle reveal
 </td>
 <td className="py-2 px-2 align-top">
 API keys, tokens, passwords — anything that lives in <Code>SecretStore</Code>
 </td>
 </tr>
 <tr style={{ borderBottom: "0.5px solid var(--glass-border)" }}>
 <td className="py-2 px-2 align-top"><Code>textarea</Code></td>
 <td className="py-2 px-2 align-top">Multiline <Code>&lt;textarea&gt;</Code></td>
 <td className="py-2 px-2 align-top">
 JSON service-account blobs, PEM certs, multi-line tokens
 </td>
 </tr>
 <tr style={{ borderBottom: "0.5px solid var(--glass-border)" }}>
 <td className="py-2 px-2 align-top"><Code>select</Code></td>
 <td className="py-2 px-2 align-top">Single-select dropdown</td>
 <td className="py-2 px-2 align-top">
 Discrete enum with 4+ options, requires <Code>options[]</Code>
 </td>
 </tr>
 <tr style={{ borderBottom: "0.5px solid var(--glass-border)" }}>
 <td className="py-2 px-2 align-top"><Code>radio</Code></td>
 <td className="py-2 px-2 align-top">Radio button group</td>
 <td className="py-2 px-2 align-top">
 2-3 options where visibility-at-a-glance beats compactness, requires <Code>options[]</Code>
 </td>
 </tr>
 <tr style={{ borderBottom: "0.5px solid var(--glass-border)" }}>
 <td className="py-2 px-2 align-top"><Code>multi_select</Code></td>
 <td className="py-2 px-2 align-top">Checkbox chip list</td>
 <td className="py-2 px-2 align-top">
 Pick multiple from a known enum, value serializes as JSON array string, requires <Code>options[]</Code>
 </td>
 </tr>
 <tr style={{ borderBottom: "0.5px solid var(--glass-border)" }}>
 <td className="py-2 px-2 align-top"><Code>boolean</Code></td>
 <td className="py-2 px-2 align-top">Toggle switch</td>
 <td className="py-2 px-2 align-top">
 On/off flags
 </td>
 </tr>
 <tr>
 <td className="py-2 px-2 align-top"><Code>array</Code></td>
 <td className="py-2 px-2 align-top">Free-form chip-list editor</td>
 <td className="py-2 px-2 align-top">
 List-of-string fields with no enum (e.g. web&apos;s <Code>allowed_domains</Code>)
 </td>
 </tr>
 </tbody>
 </table>
 <p className="text-sm leading-relaxed mt-2">
 The widget vocabulary above covers every field type a connector
 schema can declare (including <Code>url</Code> and <Code>string</Code>).
 Every field renders in one unified Configuration section in declaration
 order; advanced-grouping, if added, needs a schema-level flag (e.g. <Code>widget: &quot;advanced&quot;</Code> or{" "}
 <Code>x-advanced: true</Code> on the property), not positional heuristics.
 </p>
 </SubSection>

 <SubSection icon="explore" title="Cross-references">
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <a href="#connector-containers" className="link">
 Per-instance Connector Containers
 </a>{" "}
 — naming convention, lifecycle on instance create, the
 universal-container migration.
 </li>
 <li>
 <a href="#connector-state" className="link">
 Connector State Machine
 </a>{" "}
 — state graph + auth-error classification + the
 connector_auth_required SSE event.
 </li>
 <li>
 <a href="#marketplace-logic" className="link">
 Marketplace Logic
 </a>{" "}
 — catalog scan, install state machine, origin pinning, the
 single-source-of-truth model.
 </li>
 <li>
 <a href="#image-pinning" className="link">
 Image Digest Pinning
 </a>{" "}
 — how DIGEST_PHANTOM_CONNECTOR_* values get baked into{" "}
 <Code>/host/.env</Code> at runtime-read time.
 </li>
 <li>
 <a href="#secret-store" className="link">Secret Store</a> — KEK
 derivation, encryption format, the audit-trail integration.
 </li>
 </ul>
 </SubSection>
 </Section>
);
}

function ConnectorState() {
 return (
 <Section id="connector-state" icon="cable" title="Connector State Machine">
 <p>
 tracks per-connector lifecycle:{" "}
 <Code>connected</Code> | <Code>failed</Code> |{" "}
 <Code>needs-auth</Code> | <Code>pending</Code> |{" "}
 <Code>disabled</Code>. The chat-route classifies tool errors
 (auth vs other) and transitions the connector accordingly. The
 UI surfaces this via a Reauth chip when needs-auth.
 </p>
 <SubSection icon="auto_mode" title="State machine">
 <Pre>{`pending → connected (first successful call)
 → failed (transport error)
 → needs-auth (401/403)
 → disabled (operator)

connected → failed (transport error)
 → needs-auth (401/403)
 → disabled

failed → connected, needs-auth, disabled
needs-auth → connected (after reauth + success)
 → disabled
disabled → pending (operator re-enables)`}</Pre>
 </SubSection>
 <SubSection icon="track_changes" title="Auth classification">
 <p>
 <Code>route.ts:isAuthError</Code> regex:{" "}
 <Code>/(401|403|unauth|forbidden|invalid (token|api key| credentials|auth)|expired|reauth|needs.?auth)/i</Code>
. Heuristic until the MCP exposes typed errors. Connector id
 extracted by splitting tool name on first <Code>.</Code> or{" "}
 <Code>_</Code>.
 </p>
 </SubSection>
 <SubSection icon="visibility" title="Surface area">
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <Code>GET /api/v1/connectors</Code> — list with state +{" "}
 <Code>configured</Code> + <Code>in_manifest</Code> flags.
 </li>
 <li>
 <Code>POST /api/v1/connectors/{`{id}`}/disable | enable | probe</Code>{" "}
 — operator actions.
 </li>
 <li>
 <Code>POST /api/v1/connectors/{`{id}`}/_record_success | _record_failure</Code>{" "}
 — internal endpoints the chat-route hits per tool dispatch.
 Underscore prefix flags them as intra-Phantom.
 </li>
 <li>
 <Code>connector_auth_required</Code> SSE event — emitted to
 the chat UI when the chat-route classifies a tool error as
 auth-related. Lets the chat surface a needs-auth chip
 without the operator opening /observability/connectors.
 </li>
 </ul>
 </SubSection>
 </Section>
);
}

function CostTracking() {
 return (
 <Section id="cost-tracking" icon="payments" title="Cost Tracking">
 <p>
 adds per-Gemini-call cost computation. Every
 callGemini() (initial + each follow-up) writes a{" "}
 <Code>chat_turn_cost</Code> audit row with input/cached/output
 token counts and USD breakdown by component. Per-turn totals
 accumulate and emit a single <Code>turn_cost</Code> SSE event
 at done time.
 </p>
 <SubSection icon="price_check" title="Pricing table">
 <p>
 <Code>lib/model-pricing.ts:MODEL_PRICING_TABLE</Code> —
 hard-coded per-model rates from Vertex public pricing (2026-05).
 Cached input bills at ~25% of standard. Longest-prefix match
 so &ldquo;gemini-2.5-pro-preview-0514&rdquo; resolves to
 gemini-2.5-pro pricing. Unknown models fall through to a
 conservative gemini-2.5-pro-class fallback.
 </p>
 </SubSection>
 <SubSection icon="calculate" title="Cost computation">
 <Pre>{`computeTurnCostUsd({inputTokens, cachedInputTokens, outputTokens, model}):
 pricing = resolveModelPricing(model)
 cached = max(0, cachedInputTokens)
 uncached = max(0, inputTokens - cached)
 inputUsd = (uncached / 1M) * pricing.inputPerM
 cachedInputUsd = (cached / 1M) * pricing.cachedInputPerM
 outputUsd = (outputTokens / 1M) * pricing.outputPerM
 uncachedHypotheticalInputUsd = ((uncached + cached) / 1M)
 * pricing.inputPerM
 return {
 usd: inputUsd + cachedInputUsd + outputUsd,
 components: { inputUsd, cachedInputUsd, outputUsd,
 uncachedHypotheticalInputUsd, pricing }
 }`}</Pre>
 </SubSection>
 <SubSection icon="trending_up" title="Savings attribution">
 <p>
 <Code>cost_components.cached_savings_usd</Code> ={" "}
 <Code>uncachedHypotheticalInputUsd - (inputUsd + cachedInputUsd)</Code>
. Sum across rows in a window for cumulative Vertex caching
 ROI. This is what /observability/cost shows as &ldquo;Cached
 savings&rdquo;.
 </p>
 </SubSection>
 </Section>
);
}

function ToolMetadata() {
 return (
 <Section id="tool-metadata" icon="fact_check" title="Tool Metadata Catalogue">
 <p>
 The diagram below shows how the three knowledge surfaces — tools,
 skills, and knowledge bases — flow from bundle source through their
 loaders into runtime catalogs, all feeding the same chat-route
 consumer.
 </p>

 <AgentKnowledgeSurfaces />

 <p style={{ marginTop: 12 }}>
 The tool-metadata catalogue specifically adds per-tool flags:{" "}
 <Code>readOnly</Code>, <Code>destructive</Code>,{" "}
 <Code>concurrencySafe</Code>, <Code>openWorld</Code>. Stored in
 a curated TS table (<Code>lib/tool-metadata.ts</Code>) keyed by
 tool name. Denormalized onto every <Code>tool_call</Code> SSE
 event so the UI doesn&apos;t need a parallel table lookup.
 </p>
 <SubSection icon="schema" title="Why a table (not connector.yaml flags)">
 <p>
 Adding fields to bundle connector.yaml forces every connector
 author to know agent-runtime vocabulary. Many tools are
 already deployed; backfilling 80 specs is churn-heavy. The
 metadata is fundamentally agent-runtime concern (what the
 chat-route does with it), not a contract concern.
 </p>
 </SubSection>
 <SubSection icon="auto_awesome" title="Use cases today">
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <Term>destructive</Term> — UI red border on the approval card
 (existing tier classification still drives gating; this is
 the visual).
 </li>
 <li>
 <Term>openWorld</Term> — UI amber border for tools with
 external side effects (Slack post, webhook fire).
 </li>
 <li>
 <Term>readOnly</Term> — Informational; future audit-volume
 optimization (skip <Code>tool_call</Code> audit for read-only
 calls when they&apos;re already in catalog metadata).
 </li>
 <li>
 <Term>concurrencySafe</Term> — Reserved for parallel-batch
 execution. The <Code>allConcurrencySafe(toolNames)</Code>{" "}
 helper exists; the chat-route&apos;s for-loop body still
 runs serially. Wiring is deferred because the per-call body
 includes approval polling + multiple hook fires that need
 careful Promise.all preservation.
 </li>
 </ul>
 </SubSection>
 </Section>
);
}

function Plugins() {
 return (
 <Section id="plugins" icon="extension" title="Plugin System">
 <p>
 The plugin system makes Phantom a platform: drop a directory
 under <Code>bundles/spark/plugins/&lt;name&gt;/</Code> with a{" "}
 <Code>manifest.yaml</Code> declaring contributions; restart or
 click Reload; the plugin&apos;s skills, scenarios, memory
 seeds, and agent definitions land.
 </p>
 <SubSection icon="article" title="Plugin manifest">
 <Pre>{`name: vendor-x
version: 1.0.0
description:...
enabled: true

skills:
 - skills/foo.md # copied to /app/skills/plugins/<name>/

scenarios:
 - scenarios/bar.json # copied to /app/scenarios/ready/<name>__bar.json

memory_seeds:
 - key: vendor-x.facts
 scope: agent
 value: |
...
 meta:
 source: plugin:vendor-x

agents: # agent definitions contributed to /agents
 - agents/red-team-x.yaml`}</Pre>
 </SubSection>
 <SubSection icon="settings" title="Loader behavior">
 <p>
 <Code>PluginLoader.apply_all(memory_store, agent_definition_store)</Code>{" "}
 discovers plugin dirs, parses manifests, applies contributions:
 </p>
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <Term>Skills</Term> — <Code>shutil.copy2</Code> to
 <Code>/app/skills/plugins/&lt;plugin&gt;/</Code>. Idempotent.
 </li>
 <li>
 <Term>Scenarios</Term> — <Code>shutil.copy2</Code> to
 <Code>/app/scenarios/ready/</Code> with{" "}
 <Code>&lt;plugin&gt;__</Code> prefix to avoid collisions.
 </li>
 <li>
 <Term>Memory seeds</Term> — Write to memory store IF the
 (scope, key) doesn&apos;t already exist. Operator edits
 survive plugin reloads.
 </li>
 <li>
 <Term>Agents</Term> — Upsert into agent definition
 store with origin <Code>plugin:&lt;name&gt;</Code>. Operator
 edits to plugin-origin agents ARE overwritten on reload.
 </li>
 </ul>
 </SubSection>
 <SubSection icon="inventory_2" title="Entry-point distributable plugins">
 <p>
 The filesystem plugin system covers operator-owned drop-in
 directories. The <strong>entry-point distributable plugin
 system</strong> covers pip-installable Python packages that
 register contributions via{" "}
 <Code>[project.entry-points.&quot;phantom.*&quot;]</Code>{" "}
 stanzas in their <Code>pyproject.toml</Code>. Five reserved
 groups: <Code>phantom.skills</Code>,{" "}
 <Code>phantom.connectors</Code>, <Code>phantom.hooks</Code>,{" "}
 <Code>phantom.scanners</Code>, <Code>phantom.providers</Code>.
 </p>
 <p style={{ marginTop: 12 }}>
 Discovery is implemented in{" "}
 <Code>bundles/spark/mcp/src/usecase/plugin_entry_points.py</Code>:
 walks <Code>importlib.metadata.entry_points(group=&quot;phantom.*&quot;)</Code>{" "}
 at MCP startup, logs the catalog. Contributed
 handlers in the <Code>phantom.hooks</Code> group are{" "}
 <strong>callable</strong> via the <Code>plugin</Code>{" "}
 hook transport — see <a href="#hooks-transport-types" className="link">the Hook System section</a> for the cross-language
 invocation bridge. Other group contributions (skills,
 connectors, scanners, providers) still need a phantom-agent
 restart to wire into their respective registries.
 </p>
 <p style={{ marginTop: 12 }}>
 Lifecycle endpoints (all bearer-auth via <Code>MCP_TOKEN</Code>):
 </p>
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <Code>GET /api/v1/plugin-entries</Code> — list groups + total.
 Proxied at <Code>/api/agent/plugin-entries</Code>; consumed by
 <Code>/observability/plugins</Code>.
 </li>
 <li>
 <Code>POST /api/v1/plugin-entries/install</Code> — body{" "}
 <Code>{"{spec: \"<pypi-name>\" | \"git+https://...\" | \"<local-path>\"}"}</Code>.
 Runs <Code>python -m pip install --user --quiet &lt;spec&gt;</Code>{" "}
 via <Code>asyncio.create_subprocess_exec</Code> (no shell;
 spec validated against shell metacharacters). Audits via{" "}
 <Code>record_event(&quot;plugin_install&quot;, ...)</Code>.
 </li>
 <li>
 <Code>DELETE /api/v1/plugin-entries/{"{dist_name}"}</Code> —
 runs <Code>pip uninstall -y</Code>. Same audit pattern.
 </li>
 </ul>
 <p style={{ marginTop: 12 }}>
 Operator UX: <Code>/observability/plugins</Code> hosts an
 install form + per-row Uninstall buttons. Newly-installed
 packages&apos; entry-points appear in the right group after
 the auto-refresh. Install and uninstall clear the in-process
 plugin-hook handler cache, so a newly installed{" "}
 <Code>phantom.hooks</Code> handler is resolved on the next hook
 invocation without a restart (an unknown handler name also
 triggers one re-walk of the entry-points). A handler module that
 is already loaded stays loaded, so upgrading such a package
 needs a phantom-agent restart.
 </p>
 </SubSection>
 <SubSection icon="lightbulb" title="Why two systems coexist">
 <p>
 Filesystem-discovered plugins are right for operator-owned
 customizations: drop a folder under{" "}
 <Code>bundles/spark/plugins/</Code>, restart, done. No
 versioning ceremony, no pypi round-trip, fits the
 internal-SOC-tooling deployment model.
 </p>
 <p style={{ marginTop: 12 }}>
 Entry-point distributable plugins are right for
 framework-extensions a vendor wants to SHIP — a hook library,
 a connector, a model provider. <Code>pip install</Code> + an
 entry-point declaration is the standard Python distribution
 path; this surface meets package authors where they already
 are. The two systems target different audiences and don&apos;t
 overlap.
 </p>
 </SubSection>
 </Section>
);
}

function SkillActivation() {
 return (
 <Section id="skill-activation" icon="school" title="Skill Activation">
 <p>
 The activation layer narrows which skills load into the chat
 system prompt at a given turn.{" "}
 <Code>load_simulation_skills(keywords=[...])</Code> takes a
 keyword filter; skills declare their activation triggers
 inline (in <Code>get_skill_metadata()</Code>) OR via YAML
 frontmatter (<Code>when: {"{ keywords: [...] }"}</Code>).
 </p>
 <SubSection icon="link" title="Filter logic">
 <p>
 <Code>filter_skills(keywords=[...])</Code>: a skill is included
 only if its keywords intersect the supplied list (case-
 insensitive substring match). Skills without declared keywords
 are NOT filtered out (no keywords = no opinion).
 </p>
 </SubSection>
 <SubSection icon="psychology" title="Why substring (not exact match)">
 <p>
 Operator phrasing varies. &ldquo;fortigate&rdquo; should match
 a skill keyword &ldquo;fortigate-auth-spray&rdquo; — exact
 match would force operators to type exact skill keywords.
 The substring is bounded enough that &ldquo;auth&rdquo;
 doesn&apos;t accidentally match every authentication-themed
 skill.
 </p>
 </SubSection>
 </Section>
);
}

function Polish() {
 return (
 <Section id="polish" icon="auto_awesome" title="Resilience & Polish">
 <p>Three independent polish wins.</p>
 <SubSection icon="info" title="RunStatusReason on done events">
 <p>
 <Code>lib/run-status.ts</Code> defines a closed-list union of
 12 reasons: <Code>completed</Code>, <Code>aborted_by_operator</Code>,
 <Code>hook_denied</Code>, <Code>model_error</Code>,{" "}
 <Code>max_output_truncation</Code>, <Code>max_turns_exceeded</Code>,{" "}
 <Code>context_overflow</Code>, <Code>tool_unrecoverable_error</Code>,{" "}
 <Code>stream_disconnected</Code>, <Code>slash_command_completed</Code>,{" "}
 <Code>compaction_completed</Code>, <Code>plan_proposed</Code>.
 Done event payload now carries <Code>status_reason</Code>;{" "}
 <Code>statusReasonLabel(r)</Code> + <Code>statusReasonTone(r)</Code>
 {" "}helpers for UI rendering.
 </p>
 </SubSection>
 <SubSection icon="translate" title="Audit event-name aliases">
 <p>
 <Code>lib/audit-event-names.ts</Code> bidirectional table
 mapping phantom-internal action names to OTel-conventional
 dot-namespaced form (<Code>chat_compaction_end</Code> →{" "}
 <Code>agent.context.compaction.completed</Code>). Phantom
 continues writing the phantom names as canonical; the
 alias table is consultative for downstream observability
 forwarders (Datadog, OTel collector).
 </p>
 </SubSection>
 <SubSection icon="message" title="Slack approval transport (helper)">
 <p>
 <Code>lib/slack-approval-hook.ts</Code> ships a builder that
 generates the Hook JSON for a Slack approval. The actual
 Slack-side webhook receiver is operator-owned (every
 customer&apos;s Slack workspace is different). The helper
 documents the pattern and exposes{" "}
 <Code>SLACK_APPROVAL_INSTRUCTIONS</Code> as operator-facing
 markdown.
 </p>
 </SubSection>
 </Section>
);
}

function Subagents() {
 return (
 <Section id="subagents" icon="groups" title="Subagents & Agent Definitions">
 <p>
 Subagents are Phantom&apos;s foreground delegation primitive:
 the parent agent dispatches a scoped child with its own
 system prompt, tool catalogue, and transcript. The model
 invokes the synthetic <Code>subagent_create</Code> tool with{" "}
 <Code>{`{ agent_name, prompt }`}</Code>; the chat-route&apos;s
 tool-dispatch loop intercepts and routes to{" "}
 <Code>runSubagent()</Code>. The parent blocks until the
 subagent returns, which keeps the control flow synchronous
 and the audit trail linear.
 </p>
 <SubSection icon="data_object" title="AgentDefinition">
 <Pre>{`AgentDefinition {
 id uuid
 name unique identifier
 description one-line operator summary
 system_prompt the subagent's system instruction
 (NOT inherited from parent)
 tools_allowed glob list (empty = all tools, NOT recommended)
 tools_denied glob list (deny wins on overlap)
 model optional override (null = inherit)
 max_turns 1..50, default 10
 isolation 'fresh_session' (default) | 'parent_session'
 origin 'operator' | 'plugin:<name>' | 'builtin'
 enabled bool
 created_at, updated_at
}`}</Pre>
 </SubSection>
 <SubSection icon="filter_alt" title="Tool catalog filter">
 <p>
 <Code>filterToolsForAgent(parentTools, allowed, denied)</Code>{" "}
 filters the Gemini tool catalog through the agent&apos;s
 glob lists. Uses <Code>globMatch()</Code> from the hook
 framework (DRY). Empty allow list = all tools. Deny wins.
 Returns a tool catalog the model SEES — no defense-in-depth
 required at the model layer because denied tools are not in
 the catalog.
 </p>
 <p>
 Defense-in-depth re-check in the subagent&apos;s tool loop
 catches any tool name the model produces that&apos;s outside
 scope (rare but possible if a hook injected a tool call).
 Blocked calls emit <Code>subagent_tool_blocked</Code> SSE.
 </p>
 </SubSection>
 <SubSection icon="alt_route" title="runSubagent flow">
 <ol className="list-decimal pl-5 space-y-1 text-sm">
 <li>
 Fire <Code>SubagentStart</Code> hook — may deny.
 </li>
 <li>
 Resolve agent definition by name. 404 / disabled →
 failed result.
 </li>
 <li>
 Create a fresh MCP session for the subagent.
 <Code>parent_session_id</Code> linkage in metadata.
 </li>
 <li>
 Open a task-registry entry (<Code>kind=&apos;subagent&apos;</Code>).
 </li>
 <li>
 Persist subagent&apos;s user-message; audit{" "}
 <Code>chat_subagent_started</Code>.
 </li>
 <li>
 Filter tools to scope; emit{" "}
 <Code>subagent_started</Code> SSE.
 </li>
 <li>
 Run model loop with agent&apos;s system_prompt + scoped
 tools + max_turns. Each Gemini call records a{" "}
 <Code>chat_turn_cost</Code> audit row tagged with the
 subagent&apos;s session id so cost rollups in{" "}
 <Link href="/observability/cost" className="link">
 /observability/cost
 </Link>{" "}
 attribute it correctly.
 </li>
 <li>
 Per tool call: emit <Code>subagent_tool_call</Code>; check
 scope; dispatch; emit <Code>subagent_tool_result</Code>.
 </li>
 <li>
 On done: persist final assistant message; close task;
 audit <Code>chat_subagent_completed</Code> /{" "}
 <Code>chat_subagent_failed</Code>; fire{" "}
 <Code>SubagentEnd</Code> hook; emit{" "}
 <Code>subagent_completed</Code> SSE.
 </li>
 <li>
 Return synthetic tool result (JSON-stringified) to parent&apos;s
 tool-call loop.
 </li>
 </ol>
 </SubSection>
 <SubSection icon="link" title="Sidechain transcripts">
 <p>
 Each subagent run gets its own session id. Persistent
 transcript is queryable separately; the parent session has
 NO direct messages from the subagent — only the
 subagent_create tool call + its result. This is by design:
 the parent&apos;s context budget shouldn&apos;t balloon with
 subagent transcripts; operators who want detail click the
 sidechain link.
 </p>
 </SubSection>
 <SubSection icon="rule" title="Constraints + dispatch model">
 <ul className="list-disc pl-5 space-y-1.5 text-sm">
 <li>
 <Term>Foreground only.</Term> Dispatching a subagent blocks
 the parent&apos;s tool call until the subagent returns.
 Synchronous control flow keeps the audit trail linear:
 every subagent run pairs to a single{" "}
 <Code>subagent_create</Code> entry in the parent
 transcript.
 </li>
 <li>
 <Term>Bounded depth via max_turns.</Term>{" "}
 <Code>subagent_create</Code> appears in every tool catalog
 (including subagents&apos;), so a subagent can dispatch a
 subagent of its own. <Code>max_turns</Code> on each level
 bounds the work; the synchronous dispatch model means a
 runaway recursion surfaces immediately as a stalled parent
 rather than a silent fan-out.
 </li>
 <li>
 <Term>Tool scope is the security model.</Term> The
 catalogue filter is what the model SEES — denied tools
 don&apos;t appear in the schema at all. The defense-in-
 depth re-check inside the subagent&apos;s tool loop
 catches hook-injected calls only.
 </li>
 </ul>
 </SubSection>

 <SubSection icon="api" title="REST + UI surface">
 <Pre>{`GET    /api/v1/agent-definitions?origin=<name>&enabled_only=1
GET    /api/v1/agent-definitions/{id}
GET    /api/v1/agent-definitions/by-name/{name}
POST   /api/v1/agent-definitions             -- upsert
PATCH  /api/v1/agent-definitions/{id}        -- partial update (enable, system_prompt, ...)
DELETE /api/v1/agent-definitions/{id}        -- soft-delete (origin=operator only)

POST   /api/v1/subagents/{name}/dispatch     -- programmatic dispatch (mirrors subagent_create)

UI: /agents              -- CRUD over operator + browse over builtin/plugin
    /observability/events filter action:chat_subagent_* or action:agent_definition_*`}</Pre>
 <p className="text-sm text-on-surface-variant">
 The agent-definition store is shared across origins: operator
 rows live alongside plugin-contributed and builtin rows; the{" "}
 <Code>origin</Code> column determines whether DELETE is
 honored (operator-only) and whether reloads re-seed the entry
 (plugin/builtin re-seed at boot; operator entries persist
 untouched).
 </p>
 </SubSection>

 <SubSection icon="construction" title="Implementation references">
 <ul className="list-disc pl-6 space-y-1 text-sm">
 <li><Code>mcp/agent/app/api/chat/route.ts</Code> — <Code>runSubagent()</Code>, tool-dispatch interception, sidechain session opening</li>
 <li><Code>mcp/agent/lib/subagent-runner.ts</Code> — scoped model loop + audit + SSE emit</li>
 <li><Code>mcp/agent/lib/tool-catalog-filter.ts</Code> — <Code>filterToolsForAgent()</Code> via globMatch from hook framework</li>
 <li><Code>bundles/spark/mcp/src/usecase/agent_definitions_store.py</Code> — SQLite-backed CRUD + origin reconcile</li>
 <li><Code>bundles/spark/mcp/src/api/agent_definitions.py</Code> — REST routes</li>
 <li><Code>mcp/agent/app/agents/page.tsx</Code> — UI (browse + edit drawer + /spawn typeahead source)</li>
 </ul>
 </SubSection>
 </Section>
);
}

// ─── Composition ────────────────────────────────────────────────

function SubstrateComposition() {
 return (
 <Section id="substrate-composition" icon="diversity_3" title="Substrate Composition">
 <p>
 Phantom&apos;s subsystems compose rather than duplicate. Each
 substrate contributes one capability; higher-level features sit
 on top by reusing the substrate&apos;s primitives. New features
 land mostly as glue rather than new infrastructure.
 </p>

 <SubstrateCompositionDiagram />

 <SubSection icon="layers" title="The composition graph">
 <ul className="list-disc pl-5 space-y-2 text-sm">
 <li>
 <Term>Hooks framework</Term> contributes lifecycle
 event-firing infrastructure. Plan mode reuses it via{" "}
 <Code>PreCompact</Code> hooks. Subagents reuse it via{" "}
 <Code>SubagentStart</Code> + <Code>SubagentEnd</Code>{" "}
 events. The Slack-approval transport is an HTTP-transport
 hook on <Code>PreToolUse</Code> — zero new chat-route code.
 </li>
 <li>
 <Term>Task registry</Term> contributes the durable work-
 tracking model. Subagents reuse it: every subagent run is a
 Task with <Code>kind=&apos;subagent&apos;</Code>. The /tasks
 page shows subagent runs alongside scenario workers without
 any subagent-specific UI.
 </li>
 <li>
 <Term>Audit log + cost tracking</Term> — Audit log is the
 universal queryable surface; cost rows are just one audit
 family. Subagent runs each write their own cost rows tagged
 with the subagent session id; the parent session&apos;s
 aggregate cost includes the subagents&apos; Gemini calls
 without special-casing.
 </li>
 <li>
 <Term>Plugin system</Term> contributes a manifest-driven
 extension pipeline. Agent definitions ride it: a plugin&apos;s{" "}
 <Code>agents:</Code> block contributes AgentDefinitions the
 same way <Code>memory_seeds:</Code> contributes memories and{" "}
 <Code>skills:</Code> contributes skill markdown.
 </li>
 <li>
 <Term>Tool metadata catalogue</Term> contributes the
 denormalized-on-tool_call pattern. UI consumers read
 metadata from the SSE event without a parallel lookup.
 Parallel-batch tool execution just consults the same{" "}
 <Code>concurrencySafe</Code> flag.
 </li>
 </ul>
 </SubSection>
 <SubSection icon="favorite" title="Why this matters">
 <p>
 The subagents subsystem shipped in roughly 3,200 LOC with
 zero architectural duplication. The agent definition store
 reuses the persistence pattern from the hook store. The
 subagent runner reuses the cost recorder, the hook
 dispatcher, the task store, and the audit log helpers
 already in place for other features. The plugin
 contribution mechanism is identical to the
 memory-seed path. Adding a new feature is a feature
 decision, not an architectural one.
 </p>
 </SubSection>
 </Section>
);
}

// ─── Reference ──────────────────────────────────────────────────

function AuditSchema() {
 return (
 <Section id="audit-schema" icon="history" title="Audit Log Schema">
 <p>
 <Code>SqliteAuditLog</Code> writes append-only rows. No update
 or delete API — SOC audit trails must be tamper-evident.
 </p>
 <Pre>{`audit_events (
 id TEXT PRIMARY KEY, -- uuid4
 ts TEXT NOT NULL, -- ISO8601 UTC, microsecond precision
 actor TEXT, -- 'system' | 'user:<name>' | 'agent'
 action TEXT NOT NULL, -- one of manifest.audit.events
 target TEXT, -- 'connector:caldera' | 'tool:xsiam.execute_xql_query'
 -- 'session:<uuid>' | 'task:<uuid>' | etc.
 status TEXT, -- 'success' | 'failure' | 'skipped'
 duration_ms INTEGER, -- nullable
 metadata_json TEXT NOT NULL, -- action-specific JSON (NEVER secret VALUES)
 trigger TEXT -- X-Phantom-Trigger header
);
CREATE INDEX idx_audit_ts ON audit_events(ts);
CREATE INDEX idx_audit_actor ON audit_events(actor);
CREATE INDEX idx_audit_action ON audit_events(action);
CREATE INDEX idx_audit_target ON audit_events(target);`}</Pre>
 <SubSection icon="security" title="Sanitization">
 <p>
 <Code>SqliteAuditLog._sanitize(meta)</Code> scrubs values that
 look like raw secrets before they hit the metadata_json column.
 Secret PATHS are fine (operator can audit which secret was
 read); secret VALUES are not (and the audit log is the wrong
 place to store them anyway).
 </p>
 </SubSection>
 </Section>
);
}

function AuditEvents() {
 return (
 <Section id="audit-events" icon="list" title="Audit Event Names">
 <p>
 Every /14/15 phase that wanted observability registered
 audit action names. Manifest declares them; the chat-route
 emits them; <Code>/observability/events</Code> queries them.
 </p>
 <SubSection icon="bookmark" title="By round">
 <ul className="list-disc pl-5 space-y-1.5 text-sm">
 <li>
 <Term>Pre-</Term>: <Code>tool_call</Code>,{" "}
 <Code>simulation_created</Code>,{" "}
 <Code>scenario_started</Code>,{" "}
 <Code>caldera_operation_created</Code>,{" "}
 <Code>detection_validation_recorded</Code>,{" "}
 <Code>coverage_report_generated</Code>,{" "}
 <Code>setup_completed</Code>, <Code>settings_changed</Code>,{" "}
 <Code>approval_requested</Code>, <Code>approval_resolved</Code>,
 etc.
 </li>
 <li>
 <Term>D</Term>: <Code>chat_compaction_start</Code>,{" "}
 <Code>chat_compaction_end</Code>,{" "}
 <Code>chat_compaction_failed</Code>,{" "}
 <Code>chat_context_warning</Code>, <Code>chat_cache_hit</Code>.
 </li>
 <li>
 <Term>H</Term>: <Code>hook_upsert</Code>,{" "}
 <Code>hook_enabled</Code>, <Code>hook_disabled</Code>,{" "}
 <Code>hook_deleted</Code>, <Code>hook_dispatched</Code>.
 </li>
 <li>
 <Term>T</Term>: <Code>task_created</Code>,{" "}
 <Code>task_started</Code>, <Code>task_completed</Code>,{" "}
 <Code>task_failed</Code>, <Code>task_aborted</Code>,{" "}
 <Code>task_pending</Code>, <Code>task_transitioned</Code>.
 </li>
 <li>
 <Term>P</Term>: <Code>chat_plan_proposed</Code>,{" "}
 <Code>chat_plan_failed</Code>.
 </li>
 <li>
 <Term>M</Term>: <Code>connector_failed</Code>,{" "}
 <Code>connector_auth_required</Code>,{" "}
 <Code>connector_disabled</Code>,{" "}
 <Code>connector_enabled</Code>, <Code>connector_probed</Code>.
 </li>
 <li>
 <Term>$</Term>: <Code>chat_turn_cost</Code>.
 </li>
 <li>
 <Term>X</Term>: <Code>plugins_reloaded</Code>.
 </li>
 <li>
 <Term>S</Term>: <Code>chat_subagent_started</Code>,{" "}
 <Code>chat_subagent_completed</Code>,{" "}
 <Code>chat_subagent_failed</Code>,{" "}
 <Code>agent_definition_upsert</Code>,{" "}
 <Code>agent_definition_enabled</Code>,{" "}
 <Code>agent_definition_disabled</Code>,{" "}
 <Code>agent_definition_deleted</Code>.
 </li>
 </ul>
 </SubSection>
 <SubSection icon="translate" title="OTel-conventional aliases">
 <p>
 <Code>lib/audit-event-names.ts:AUDIT_EVENT_NAME_ALIASES</Code>{" "}
 maps phantom names to dot-namespaced form for downstream
 observability forwarders. Examples:{" "}
 <Code>chat_compaction_end</Code> →{" "}
 <Code>agent.context.compaction.completed</Code>;{" "}
 <Code>chat_turn_cost</Code> → <Code>agent.model.cost</Code>;{" "}
 <Code>chat_subagent_started</Code> →{" "}
 <Code>agent.subagent.started</Code>.
 </p>
 </SubSection>
 </Section>
);
}

function RestApi() {
 return (
 <Section id="rest-api" icon="api" title="REST API Reference">
 <p>
 The MCP side requires <Code>Authorization: Bearer $MCP_TOKEN</Code>{" "}
 on every <Code>/api/v1/*</Code> call. The agent-side proxies
 at <Code>/api/agent/*</Code> are gated by the operator&apos;s
 <Code>phantom_session</Code> cookie (server-side validated at
 the edge middleware — see{" "}
 <Link href="#authentication" className="link">Authentication</Link>).
 The endpoints below are the surfaces unique to Phantom&apos;s
 control plane (the broader xlog GraphQL surface is documented
 in the Foundation section).
 </p>
 <SubSection icon="api" title="Audit">
 <ul className="list-disc pl-5 space-y-0.5 font-mono text-[12px]">
 <li>POST /api/v1/audit — write a generic audit row</li>
 </ul>
 </SubSection>
 <SubSection icon="api" title="Hooks">
 <ul className="list-disc pl-5 space-y-0.5 font-mono text-[12px]">
 <li>GET /api/v1/hooks?event=&lt;name&gt;&amp;enabled_only=1</li>
 <li>GET /api/v1/hooks/{`{id}`}</li>
 <li>POST /api/v1/hooks (upsert)</li>
 <li>PATCH /api/v1/hooks/{`{id}`}</li>
 <li>DELETE /api/v1/hooks/{`{id}`}</li>
 </ul>
 </SubSection>
 <SubSection icon="api" title="Tasks">
 <ul className="list-disc pl-5 space-y-0.5 font-mono text-[12px]">
 <li>GET /api/v1/tasks?status=running&amp;active_only=1&amp;session=&lt;id&gt;</li>
 <li>GET /api/v1/tasks/{`{id}`}</li>
 <li>POST /api/v1/tasks (create)</li>
 <li>PATCH /api/v1/tasks/{`{id}`}/progress</li>
 <li>POST /api/v1/tasks/{`{id}`}/transition</li>
 <li>POST /api/v1/tasks/{`{id}`}/abort</li>
 </ul>
 </SubSection>
 <SubSection icon="api" title="Connectors">
 <ul className="list-disc pl-5 space-y-0.5 font-mono text-[12px]">
 <li>GET /api/v1/connectors</li>
 <li>GET /api/v1/connectors/{`{id}`}</li>
 <li>POST /api/v1/connectors/{`{id}`}/disable | enable | probe</li>
 <li>POST /api/v1/connectors/{`{id}`}/_record_success | _record_failure</li>
 </ul>
 </SubSection>
 <SubSection icon="api" title="Plugins">
 <ul className="list-disc pl-5 space-y-0.5 font-mono text-[12px]">
 <li>GET /api/v1/plugins</li>
 <li>POST /api/v1/plugins/reload</li>
 </ul>
 </SubSection>
 <SubSection icon="api" title="Agent Definitions">
 <ul className="list-disc pl-5 space-y-0.5 font-mono text-[12px]">
 <li>GET /api/v1/agent-definitions?origin=&lt;name&gt;&amp;enabled_only=1</li>
 <li>GET /api/v1/agent-definitions/{`{id}`}</li>
 <li>GET /api/v1/agent-definitions/by-name/{`{name}`}</li>
 <li>POST /api/v1/agent-definitions (upsert)</li>
 <li>PATCH /api/v1/agent-definitions/{`{id}`}</li>
 <li>DELETE /api/v1/agent-definitions/{`{id}`}</li>
 </ul>
 </SubSection>
 <SubSection icon="forward" title="Agent passthroughs">
 <p>
 Every <Code>/api/v1/...</Code> endpoint above has a sibling{" "}
 <Code>/api/agent/...</Code> proxy in the Next.js agent. The
 proxy is gated by the <Code>phantom_session</Code> cookie at
 the edge middleware and forwards via the bearer-authed{" "}
 <Code>callMcpServer()</Code>. UI pages hit the agent paths.
 </p>
 </SubSection>
 </Section>
);
}

function DesignDecisions() {
 return (
 <Section id="design-decisions" icon="psychology" title="Design Decisions">
 <p>
 Significant decisions worth recording. Each is a where-why, not
 prescription.
 </p>
 <Decision title="Foreground subagents, not background">
 <p>
 Foreground (subagent blocks parent&apos;s tool call until done)
 maps cleanly onto the existing tool-call flow — model calls
 subagent_create, gets result back, continues reasoning.
 Background would need its own SSE stream or polling, with
 orchestration complexity to match. Foreground keeps the
 agent-definition + sidechain-transcript + scoped-tools mechanics
 simple. A future variant can wrap the runner in a task-registry
 entry with deferred result delivery for genuinely long-running
 work.
 </p>
 </Decision>
 <Decision title="Audit-row-driven cost rollups instead of a separate cost table">
 <p>
 Cost data is fundamentally event-shaped (one row per
 callGemini). A separate aggregations table would be
 redundant precomputation. Audit log is fast at SUM aggregation
 on indexed columns; for now /observability/cost does
 sum-in-the-browser for windows up to 5K rows. If audit grows
 past ~10K rows in the active window, add an MCP-side
 /api/v1/observability/cost-rollup endpoint.
 </p>
 </Decision>
 <Decision title="Tool metadata in TS table, not in connector.yaml">
 <p>
 Pushing flags into bundle connector.yaml forces every
 connector author to know agent-runtime vocabulary. Many tools
 are already deployed; backfilling 80 specs is churn-heavy.
 The metadata is fundamentally agent-runtime concern (what the
 chat-route does with it), not contract concern. Curated TS
 table keeps it close to the consumer.
 </p>
 </Decision>
 <Decision title="Hook framework loads fresh per fire-site, not cached">
 <p>
 Hooks are policy. Operators expect &ldquo;disable this
 hook&rdquo; to take effect immediately, not after a TTL.
 The hooks table is small (under 10 rows in typical deploys);
 the MCP round-trip is &lt;100ms. Fresh-load simplifies
 semantics; caching adds complexity for marginal performance
 benefit.
 </p>
 </Decision>
 <Decision title="Scoped tool catalogs in subagents, not just permission checks">
 <p>
 Permission checks are runtime gates; scoped catalogs are
 compile-time gates (the model literally doesn&apos;t see
 out-of-scope tools). Scoped catalogs give correctness AND
 better LLM behavior: the model can&apos;t even attempt
 out-of-scope tools, so it doesn&apos;t hallucinate calls
 that would just get denied. Defense-in-depth re-check inside
 the runner catches edge cases (hook injection).
 </p>
 </Decision>
 <Decision title="Plugin agent edits get overwritten on reload (operator clones)">
 <p>
 Plugin-origin agents (origin=plugin:&lt;name&gt;) are
 authoritatively owned by the plugin manifest. Operator edits
 to them should NOT survive a plugin reload — that would
 create silent diffs between what&apos;s in the plugin file
 and what&apos;s actually running. Operators wanting persistent
 edits clone the agent via &ldquo;New agent&rdquo; with
 origin=operator. The /agents UI shows a warning banner when
 editing a plugin-origin agent.
 </p>
 </Decision>
 </Section>
);
}

// ─── Foundation: boot + setup ──────────────────────────────────────

function BootLifecycle() {
 return (
 <Section id="boot-lifecycle" icon="rocket_launch" title="Boot Lifecycle">
 <p>
 Each container has a deterministic boot sequence. Understanding
 it explains why first-run feels different from subsequent runs
 (skills volume merged per release via marker-driven auto-merge,
 KBs reconciled by source-hash) and what gates the agent UI from
 rendering before the runtime is ready.
 </p>
 <SubSection icon="schedule" title="phantom-mcp boot sequence">
 <Pre>{`1. entrypoint.sh runs:
   - skills bootstrap (marker-driven auto-merge):
       FORCE_SKILLS_SYNC=1   → merge defaults; stamp marker
       volume empty          → seed defaults; stamp marker
       marker missing/stale  → MERGE defaults; stamp marker
                               (the per-release auto-rollout path)
       marker matches        → no-op (operator deletions stick)
     marker file: phantom_mcp_skills/.seeded_version
2. python -m src.main starts:
   - load config (pydantic-settings; env via validation_alias)
   - build FastMCP instance
   - reconcile knowledge bases (per-KB source-hash → embed only changed)
   - load bundle manifest, register connector instances
   - register ~80 tools (one mcp.tool() call per tool)
   - register runtime built-ins (memory, sessions, knowledge, skills)
   - start transport (stdio | streamable-http)
3. /ping/ becomes 200; /health/full becomes 200`}</Pre>
 <p>
 The skills bootstrap uses a per-release marker
 (PHANTOM_VERSION stamped into <Code>.seeded_version</Code> on
 every successful merge) so the entrypoint detects &ldquo;this
 volume hasn&apos;t seen the current release&apos;s defaults
 yet&rdquo; and auto-merges. The merge is strictly additive:{" "}
 <Code>cp -r</Code> overwrites image-default collisions but
 never removes files only in the volume — so customer-created
 skills are preserved. The next-release upgrade is the only
 point where image defaults get re-introduced over an
 operator&apos;s in-volume deletion (which is the right
 semantic — upgrading is opting into the new release&apos;s
 default set).
 </p>
 </SubSection>
 <SubSection icon="schedule" title="phantom-agent boot sequence">
 <Pre>{`1. Next.js boots; AuthGate wraps every page
2. /api/agent/setup-status checks runtime config:
   - reads /app/runtime/setup.json
   - returns { configured: bool, ready: bool }
3. If !configured: redirect every route to /setup
4. If configured: hydrate operator session from cookie, render UI`}</Pre>
 </SubSection>
 <SubSection icon="schedule" title="xlog boot sequence">
 <p>
 Uvicorn comes up with 4 workers (configurable via{" "}
 <Code>WORKERS_NUMBER</Code>). The Strawberry GraphQL schema
 mounts at <Code>/</Code>. Module-level <Code>workers = {}</Code>{" "}
 dict is empty — there is no persistent worker state across
 restarts. Scenario files under <Code>scenarios/ready/*.json</Code>{" "}
 are read on demand.
 </p>
 </SubSection>
 <SubSection icon="warning" title="Boot ordering subtleties">
 <ul className="list-disc pl-5 space-y-1.5 text-sm">
 <li>
 <Term>MCP before agent</Term> — the agent&apos;s health probes
 hit MCP server-side; if MCP is still loading, the agent shows
 a degraded pipeline. Compose <Code>depends_on</Code> with
 <Code>condition: service_healthy</Code> serialises this.
 </li>
 <li>
 <Term>Skills volume on first run</Term> — entrypoint copies
 defaults only when the volume is empty. Editing a skill in the
 repo and rebuilding does NOT propagate to a running container
 unless the volume is dropped (<Code>down -v</Code>) or{" "}
 <Code>FORCE_SKILLS_SYNC=1</Code> is set.
 </li>
 <li>
 <Term>KB reconcile is incremental</Term> — entries with
 unchanged source hash skip re-embedding. A typical reboot is
 a no-op for KB indices.
 </li>
 </ul>
 </SubSection>
 </Section>
);
}

function Authentication() {
 return (
 <Section id="authentication" icon="lock_person" title="Authentication">
 <p>
 <strong>This section is the source of truth for authentication.</strong>{" "}
 Any change to <Code>/api/auth/*</Code>, <Code>/profile</Code>, the
 reset CLI, or the MCP-side auth_store MUST conform to the contract
 below. CLAUDE.md mandates reading this section before touching
 any auth-related code.
 </p>

 <SubSection icon="hub" title="Topology — components, tiers, trust boundaries">
 <p>
 Before any individual flow, the static picture: four trust tiers
 stacked from the browser at the top to the canonical stores at the
 bottom, with the audit log observing every action and the CLI
 reset shown as the only out-of-band bypass. Every flow diagram
 further down traces a path through this same graph.
 </p>
 <AuthTopology />
 <ul className="list-disc pl-6 space-y-1">
 <li><strong>USER tier</strong> — operator&apos;s browser. Untrusted from the server&apos;s POV; the only credential it carries is the <Code>phantom_session</Code> cookie (32-byte random, HttpOnly, Secure, SameSite=Strict, 2-hour Max-Age).</li>
 <li><strong>EDGE tier (in-container)</strong> — TLS terminates at <Code>tls-proxy.js</Code> on :3000 and forwards to Next.js on :3001 (plain HTTP, loopback). The four <Code>/api/auth/*</Code> route handlers (<Code>login</Code>, <Code>logout</Code>, <Code>status</Code>, <Code>change-password</Code>) live inside the Next.js process and call MCP for everything storage-related.</li>
 <li><strong>AUTH SERVICE tier (in-container, separate process)</strong> — embedded MCP, reached at <Code>https://127.0.0.1:8080</Code> with bearer <Code>MCP_TOKEN</Code>. Three layers internally: <Code>api/ui_auth.py</Code> (HTTP routes) → <Code>usecase/auth_store.py</Code> (orchestration: seeding, sessions, the credentials_changed flag) → <Code>usecase/ui_auth.py</Code> (crypto envelope: PBKDF2-HMAC-SHA256 at 600k iters).</li>
 <li><strong>STORAGE tier (single source of truth)</strong> — exactly two persisted-state stores. <Code>SecretStore</Code> holds the password hash + the credentials_changed flag (AES-256-GCM at rest, KEK-derived). <Code>auth_sessions.db</Code> (SQLite) holds session token HASHES (never raw tokens) + their expiry / revoked state.</li>
 <li><strong>AUDIT log (observer)</strong> — every auth action emits an <Code>audit_events</Code> row. Write-only from the service&apos;s POV; queryable separately via the observability surfaces.</li>
 <li><strong>CLI reset (out-of-band bypass)</strong> — <Code>docker exec phantom_agent node /app/cli/reset-admin.mjs</Code> skips the browser + Next.js tiers entirely. Trust boundary: host shell access (anyone with <Code>docker exec</Code> already has root inside the container, so the bypass is no privilege escalation). Reads <Code>MCP_TOKEN</Code> from <Code>/proc/1/environ</Code> and POSTs directly to the service tier&apos;s <Code>/admin_reset</Code> route.</li>
 </ul>
 </SubSection>

 <SubSection icon="storage" title="Storage contract — one canonical home">
 <p>
 Every persisted auth value lives in EXACTLY ONE place. No fallback
 chains, no env overrides, no setup.json reads.
 </p>
 <Pre>{`SecretStore  (DATA_ROOT/secrets/ — AES-GCM at rest, PBKDF2-derived KEK)
 └── /ui/auth/admin/
       ├── password_hash             pbkdf2_sha256$600000$<salt>$<hash>
       └── credentials_changed       "true" | "false"   (gates first-login banner)

auth_sessions.db  (DATA_ROOT/ — SQLite, per-row indexed)
 └── sessions(token_hash PK, username, created_at_ms, expires_at_ms,
              user_agent_hash, revoked_at_ms)

Cookie: phantom_session=<32B random>; HttpOnly; Secure; SameSite=Strict;
        Max-Age=7200
`}</Pre>
 <ul className="list-disc pl-6 space-y-1">
 <li><Code>password_hash</Code> — PBKDF2-HMAC-SHA256 at 600,000 iterations (OWASP 2023 password-storage recommendation). Owned by <Code>bundles/spark/mcp/src/usecase/ui_auth.py</Code>.</li>
 <li><Code>credentials_changed</Code> — boolean flag flipped to <Code>true</Code> the first time the operator successfully rotates the password. Gates the non-dismissible &ldquo;change your default password&rdquo; banner. Set to <Code>false</Code> by the entrypoint seed and never reset by code.</li>
 <li><Code>sessions</Code> — stores SHA-256 hashes of session tokens (never the raw token). The raw token only exists in the operator&apos;s cookie; server-side validation hashes on every check. A leaked DB doesn&apos;t immediately surface live sessions.</li>
 <li>Cookie <Code>HttpOnly + Secure + SameSite=Strict</Code> gives us CSRF protection without a separate token system. <Code>Max-Age=7200</Code> means 2-hour absolute expiry, no remember-me.</li>
 </ul>
 </SubSection>

 <SubSection icon="key" title="API-key bearer auth — programmatic access">
 <p>
 Besides the session cookie, the agent surface (<Code>/api/chat</Code>,{" "}
 <Code>/api/agent/*</Code>, <Code>/api/skills/*</Code>) accepts an{" "}
 <strong>API-key bearer</strong> for scripts, schedulers, CI, and any
 programmatic integration. Operators mint scoped, revocable keys in{" "}
 <Code>/api-keys</Code> (shape <Code>phantom_ak_&lt;id&gt;_&lt;secret&gt;</Code>;
 the DB stores only <Code>sha256(secret)</Code>, never the raw key).
 Send <Code>Authorization: Bearer phantom_ak_…</Code>.
 </p>
 <ul className="list-disc pl-6 space-y-1">
 <li><strong>Coarse scopes</strong>: <Code>agent:read</Code> (GET routes + chat read), <Code>agent:write</Code> (mutations + <Code>/api/chat</Code>), <Code>agent:*</Code> (both). <Code>*</Code> remains full admin. Chosen per key at mint time.</li>
 <li><strong>Credential exclusion (security invariant)</strong>: <Code>/api/agent/providers/*</Code>, <Code>/api/agent/instances/*</Code>, and <Code>/api/agent/api-keys/*</Code> reject API keys <em>even with</em> <Code>agent:*</Code> — those stay session-cookie-only. A leaked key can never mint more keys or read provider secrets. Enforced in <Code>middleware.ts</Code> via <Code>lib/agent-scopes.ts</Code>, on top of the MCP api-keys surface which already refuses API-key auth on itself.</li>
 <li><strong>Validation wire</strong>: <Code>middleware.ts</Code> → <Code>lib/auth-store.ts validateApiKey()</Code> → MCP <Code>POST /api/v1/ui/auth/verify_key</Code> (loopback, <Code>MCP_TOKEN</Code> bearer, 30s positive cache; revocation busts the cache). Same shape as the session-validate path.</li>
 </ul>
 </SubSection>

 <SubSection icon="shield" title="Server-side session enforcement — middleware.ts">
 <p>
 Server-side gating runs in a Next.js middleware at{" "}
 <Code>mcp/agent/middleware.ts</Code> on the Edge runtime
 (Next.js 15.1.6). It enforces session validation at a higher
 trust boundary than any individual route handler — every
 operator-control surface is checked at the edge before reaching
 the route. A caller arriving at port 3000 without a valid
 session cookie gets <Code>401</Code> regardless of which API
 they target; route-level checks become defense-in-depth, not
 the single line of defence.
 </p>
 <p>
 The matcher catches every operator-control surface:
 </p>
 <Pre>{`config.matcher = [
  "/api/agent/:path*",
  "/api/chat",
  "/api/skills",
  "/api/skills/:path*",
];`}</Pre>
 <p>
 Each request: read{" "}
 <Code>phantom_session</Code> from cookies; call{" "}
 <Code>validateSession(token)</Code> (the same path{" "}
 <Code>/api/auth/status</Code> uses, with the 30s positive cache
 from <Code>lib/auth-store.ts</Code>); absence OR invalid value
 → <Code>{`401 { error, code }`}</Code>. Validation hits the
 MCP-side <Code>/api/v1/ui/auth/session</Code> endpoint — same
 session store the login flow writes to.
 </p>
 <p>
 Two exemptions live in the middleware code (not the matcher),
 so the matcher stays maximally inclusive:
 </p>
 <ul className="list-disc pl-6 space-y-1.5">
 <li>
 <Code>GET /api/agent/health</Code> — Docker compose
 healthcheck calls this from inside the container with no
 cookies. Gating it would make the container unhealthy.
 </li>
 <li>
 <Code>POST /api/agent/internal/fire-hook</Code> — called by
 the embedded MCP subprocess using{" "}
 <Code>MCP_TOKEN</Code> bearer auth (not the session cookie).
 Has its own auth layer at the route handler.
 </li>
 </ul>
 <p>
 <Code>/api/auth/*</Code> is INTENTIONALLY excluded from the
 matcher entirely — login can&apos;t require login, and{" "}
 <Code>AuthGate</Code> polls <Code>/api/auth/status</Code>{" "}
 BEFORE any cookie exists.
 </p>
 <p className="text-sm text-on-surface-variant">
 Canonical-state discipline applies: the middleware is the
 single auth gate. Routes hold no ad-hoc cookie checks of
 their own; they defer entirely to the edge layer — one gate,
 one home.
 </p>
 </SubSection>

 <SubSection icon="login" title="Login flow">
 <p>
 First boot: container starts, entrypoint calls{" "}
 <Code>auth_store.seed_admin_defaults_if_empty()</Code>. If the
 SecretStore has no <Code>auth.v1</Code> for <Code>admin</Code>, it
 writes the PBKDF2 hash of{" "}
 <Code>$PHANTOM_DEFAULT_ADMIN_PASSWORD</Code> (sourced from{" "}
 <Code>/opt/phantom/.env</Code>) and sets{" "}
 <Code>credentials_changed=false</Code>. Idempotent on subsequent
 boots.
 </p>
 <p>
 The default password does not live in the phantom-agent image.
 The installer auto-generates a random per-install value into{" "}
 <Code>.env</Code> on first install (or back-fills it on upgrade
 if missing) per the &ldquo;no credentials in any image&rdquo;
 rule. The seed path fails-loud if the env var is unset on a
 fresh install (refuses to seed an empty hash); operators recover
 by re-running the installer or via{" "}
 <Code>sudo /opt/phantom/phantom-reset-admin-password</Code>.
 </p>
 <AuthLoginFlow />
 <ul className="list-disc pl-6 space-y-1">
 <li><Code>POST /api/auth/login</Code> validates username against the baked <Code>ADMIN_USERNAME</Code> constant. Phantom is single-user; only the admin account exists.</li>
 <li>In-memory per-source-IP rate limit: 5 failures / 60s → 60s lockout. Resets on container restart. Audited via <Code>login_failed</Code> events.</li>
 <li><Code>POST /api/auth/change-password</Code> checks the current password, so it carries the same limit with its own counter (<Code>lib/auth-rate-limit.ts</Code>, shared with login), keyed on the source address (last <Code>X-Forwarded-For</Code> hop) AND on a hash of the session token: five wrong current passwords against either key within 60s return 429 with <Code>Retry-After</Code> for 60s, so rotating addresses with a stolen cookie does not help. Limitation: behind an additional reverse proxy that you add in front of Phantom, the last hop is that proxy for every client, so one source can then lock sign-in for everyone for a minute; keep Phantom&apos;s own TLS proxy as the first hop. The attempt is counted before the password is checked, so parallel guesses cannot all pass. Without it a stolen session cookie could guess the password through this endpoint and skip the login lockout. Validation errors and an unreachable MCP do not count; a success clears the counter.</li>
 <li>Successful verify mints a random 32-byte URL-safe token, hashes it, stores the hash in <Code>auth_sessions.db</Code>, returns the raw token in the JSON body, and the Next.js login route wraps it in the <Code>phantom_session</Code> cookie with the security attributes listed above.</li>
 <li>Audit row: <Code>login_success</Code> with the resolved <Code>credentials_changed</Code> in metadata so the UI knows whether to redirect to <Code>/profile</Code>.</li>
 </ul>
 </SubSection>

 <SubSection icon="lock_reset" title="Change password (UI)">
 <p>
 Operator-driven from <Code>/profile</Code>. Requires the current
 password as second factor — a stolen cookie alone can&apos;t lock
 the operator out.
 </p>
 <AuthChangePasswordFlow />
 <ul className="list-disc pl-6 space-y-1">
 <li><Code>POST /api/auth/change-password</Code> reads the session cookie, validates it via <Code>auth-store.changePassword()</Code> which calls MCP <Code>POST /api/v1/ui/auth/change_password</Code>.</li>
 <li>MCP verifies <Code>current_password</Code> against the stored hash, writes the new hash, sets <Code>credentials_changed=true</Code>, and revokes ALL active sessions for the user.</li>
 <li>Server response carries cleared <Code>phantom_session</Code> cookie. The operator is force-logged-out on this device. Other tabs / devices get a 401 on their next API call (the 30s positive-validation cache on the Next.js side means up to 30s of stale-valid before the revocation takes effect everywhere).</li>
 <li>A security notification is posted to <Code>/notifications</Code>: <em>&ldquo;Your password was changed at &lt;ts&gt;&rdquo;</em>. Canary if someone else changes the password.</li>
 <li>Audit row: <Code>password_changed_ui</Code> with the sessions-revoked count.</li>
 </ul>
 </SubSection>

 <SubSection icon="terminal" title="Reset password (host utility — forgot path)">
 <p>
 Host-side utility for the forgot-password case. No current password
 needed; the trust boundary is shell access to the host (anyone with{" "}
 <Code>docker exec</Code> already has root inside the container). A
 named host script ships in the installer kit so operators have one
 consistent invocation shape:
 </p>
 <AuthCliResetFlow />
 <Pre>{`# Canonical path (script lives at /opt/phantom/ on every install):
sudo /opt/phantom/phantom-reset-admin-password

# Legacy invocation still works (the wrapper above just execs into this):
docker exec -it phantom_agent node /app/cli/reset-admin.mjs
`}</Pre>
 <ul className="list-disc pl-6 space-y-1">
 <li><strong>Host script is a thin wrapper</strong>: validates the agent container is running, then exec-replaces itself with <Code>docker exec -it phantom_agent node /app/cli/reset-admin.mjs</Code>. Credential-write logic stays inside the container (single code path with /profile&apos;s change-password flow); the host script just gives operators a memorable command.</li>
 <li>CLI presents a <Code>Type RESET to continue</Code> ceremony to prevent fat-finger triggers, then prompts for new password (terminal echo masked) + confirmation.</li>
 <li>Reads <Code>MCP_TOKEN</Code> from <Code>/proc/1/environ</Code> inside the container (the same in-container loopback trust the other operator tooling uses). Calls MCP <Code>POST /api/v1/ui/auth/admin_reset</Code>.</li>
 <li>MCP overwrites the password hash, sets <Code>credentials_changed=true</Code>, revokes all sessions, and audits the action with <Code>actor=cli:&lt;hostname&gt;</Code> + action=<Code>password_changed_cli</Code>.</li>
 <li>CLI prints <Code>Restart the agent: docker compose restart phantom-agent</Code> on success. The operator does the restart — flushes any in-memory caches and forces clean state.</li>
 <li><strong>Companion utility</strong> — <Code>sudo /opt/phantom/phantom-factory-reset</Code> wipes ALL operator-state volumes + re-runs the installer. Use that when you want the customer-fresh blank-canvas state (not just a password reset). Preserves <Code>.env</Code> so KEK + registry creds survive across the reset.</li>
 </ul>
 </SubSection>

 <SubSection icon="shield" title="Agent credential guardrail">
 <p>
 The chat agent has NO MCP tools that read, write, mint, or rotate
 credentials. The relevant tools (
 <Code>providers_create</Code>, <Code>providers_update</Code>,{" "}
 <Code>providers_delete</Code>, <Code>instances_create</Code>,{" "}
 <Code>instances_update</Code>, <Code>instances_delete</Code>,{" "}
 <Code>api_keys_create</Code>, <Code>api_keys_rotate</Code>,{" "}
 <Code>api_keys_revoke</Code>) are deliberately NOT registered as{" "}
 <Code>mcp.tool()</Code> entries in{" "}
 <Code>connector_loader.py</Code>&apos;s{" "}
 <Code>_BUILTIN_LEGACY_TOOLS</Code> list. The system prompt block in{" "}
 <Code>lib/system-prompt.ts</Code> (
 <Code>renderAgentCredentialGuardrailBlock</Code>) tells the agent
 the boundary so refusals are polite and consistent.
 </p>
 <p>
 These same tools REMAIN available at the REST surface (
 <Code>/api/v1/providers</Code>, <Code>/api/v1/instances</Code>,{" "}
 <Code>/api/v1/api_keys</Code>) so the operator UI keeps working.
 The agent simply has no handle to them: one canonical list of the
 names (<Code>usecase/credential_guardrail.py</Code>) backs the
 tool catalogue, the <Code>agent_batch_propose</Code> table and
 the job-scheduler dispatcher, so none of them can reach a
 credential tool by name, bare or namespaced. See the CLAUDE.md
 &ldquo;Agent credential guardrail (MANDATORY)&rdquo; rule for the
 full rationale.
 </p>
 </SubSection>

 <SubSection icon="visibility" title="Observability — every auth action is auditable">
 <p>
 Every auth path emits structured events to the
 <Code>audit_events</Code> table (the storage backend behind the
 observability surfaces). The intent: an operator reviewing
 <Code>/observability/events</Code> should be able to reconstruct
 exactly what happened to the auth surface — login attempts,
 password rotations, session lifecycles, secret-store reads/writes
 — without needing to read container logs or run docker exec.
 </p>
 <Pre>{`event                          actor                  target                  emitted by
─────────────────────────────  ─────────────────────  ──────────────────────  ──────────────────────────
login_success                  user:<username>        user:<username>         /api/v1/ui/auth/login
login_failed                   ip:<source>            user:<username>         /api/v1/ui/auth/login
logout                         user:<username>        session:<id>            /api/v1/ui/auth/logout
password_changed_ui            user:<username>        user:<username>         /api/v1/ui/auth/change_password
password_changed_cli           cli:<hostname>         user:<username>         /api/v1/ui/auth/admin_reset
ui_password_set                user|cli|system        user:<username>         every successful set/reset
ui_password_verify_failed      ip:<source>            user:<username>         current-password check fail
ui_password_change_rejected    user:<username>        user:<username>         validation failure (<8 chars)
session_created                user:<username>        session:<id>            login + reset paths
session_revoked                system                 session:<id>            change-password + admin_reset
session_deleted                system                 session:<id>            logout + expiry sweep
secret_read                    system                 secret:/ui/auth/...     verify-path reads
secret_write                   system                 secret:/ui/auth/...     hash + flag writes`}</Pre>
 <ul className="list-disc pl-6 space-y-1">
 <li><strong>Symmetric counts as a reliability signal</strong>: <Code>session_created</Code> should equal <Code>session_deleted + session_revoked</Code> over any time window. Drift = leaked sessions and warrants investigation. Same logic for <Code>secret_write</Code> on the credentials_changed flag (should flip exactly once per password rotation).</li>
 <li><strong>Source attribution</strong>: the <Code>actor</Code> column distinguishes UI changes (<Code>user:&lt;username&gt;</Code>) from CLI resets (<Code>cli:&lt;hostname&gt;</Code>) from system internals (<Code>system</Code>). A <Code>password_changed_cli</Code> event with an unfamiliar hostname is the classic &ldquo;someone else SSH&apos;d into the box&rdquo; canary.</li>
 <li><strong>What feeds where</strong>: <Code>/observability/events</Code> shows the audit table directly. <Code>/observability/metrics</Code> exposes <Code>phantom_mcp_http_requests_total</Code> counters that include the auth route paths. <Code>/notifications</Code> surfaces the security canary &ldquo;Your password was changed at &lt;ts&gt;&rdquo; that ALSO fires on every password change (UI or CLI) so the operator gets a UI-level signal even when not actively watching observability.</li>
 <li><strong>What&apos;s deliberately NOT logged</strong>: raw passwords (never), raw session tokens (never — only the SHA-256 hash exists server-side), <Code>MCP_TOKEN</Code> (never), KEK material (never). Audit metadata is operator-readable; secrets are not.</li>
 </ul>
 </SubSection>

 <SubSection icon="rule" title="Out of scope">
 <ul className="list-disc pl-6 space-y-1">
 <li><strong>Multi-user / RBAC / per-user audit attribution.</strong> Single-user with the baked <Code>admin</Code> name; multi-user is not supported.</li>
 <li><strong>SSO / OAuth / OIDC / SAML / LDAP.</strong> Out of scope.</li>
 <li><strong>Periodic password rotation enforcement.</strong> Modern guidance is against forced rotation.</li>
 <li><strong>Password complexity rules beyond min-length-8.</strong> Operators pick their own; the only constraint is &ge; 8 chars.</li>
 <li><strong>2FA / TOTP / hardware-key support.</strong> Out of scope.</li>
 <li><strong>Forgot-password via email recovery.</strong> CLI on the host is the recovery path.</li>
 <li><strong>KEK rotation.</strong> Current &ldquo;no rotation, key is permanent for the volume lifetime&rdquo; stays.</li>
 </ul>
 </SubSection>

 <SubSection icon="construction" title="Implementation references">
 <ul className="list-disc pl-6 space-y-1">
 <li><strong>Constants</strong>: <Code>mcp/agent/lib/auth-defaults.ts</Code> — admin username, default password, cookie name, session TTL. Baked into the image; never env-overridable.</li>
 <li><strong>Next.js auth client</strong>: <Code>mcp/agent/lib/auth-store.ts</Code> — discriminated-union return types, 30s positive-validation cache, cache-busting on change-password.</li>
 <li><strong>Routes</strong>: <Code>app/api/auth/login</Code>, <Code>logout</Code>, <Code>status</Code>, <Code>change-password</Code>. All under 200 lines each.</li>
 <li><strong>UI</strong>: <Code>components/auth/auth-gate.tsx</Code> (server-side validation via /api/auth/status, redirects to /profile when credentials_changed=false), <Code>components/auth/login-screen.tsx</Code> (spark-style animated UI), <Code>app/profile/page.tsx</Code> (read-only username, banner + change form).</li>
 <li><strong>MCP side</strong>: <Code>bundles/spark/mcp/src/usecase/auth_store.py</Code> (sessions + flag + seeding) wraps <Code>usecase/ui_auth.py</Code> (PBKDF2 envelope). HTTP routes at <Code>api/ui_auth.py</Code>: <Code>/login</Code>, <Code>/logout</Code>, <Code>/session</Code>, <Code>/change_password</Code>, <Code>/admin_reset</Code>.</li>
 <li><strong>CLI</strong>: <Code>mcp/agent/cli/reset-admin.mjs</Code> (interactive prompts + ceremony, runs inside the agent container).</li>
 <li><strong>Host utilities</strong>: <Code>installer/phantom-reset-admin-password.sh</Code> (host wrapper around the CLI above), <Code>installer/phantom-factory-reset.sh</Code> (wipes phantom_* volumes + re-runs installer). Both embedded into the single-file <Code>phantom-installer</Code> binary via heredoc; both also copied verbatim into the multi-file install kit. After install, they live at <Code>/opt/phantom/phantom-reset-admin-password</Code> and <Code>/opt/phantom/phantom-factory-reset</Code>.</li>
 </ul>
 </SubSection>
 </Section>
);
}

// ─── Setup & first-run wiring ──────────────────────────────────────

function SetupWiring() {
 return (
 <Section id="setup-wiring" icon="rocket_launch" title="Setup & First-Run Wiring">
 <p>
 Phantom comes up on first install with no operator clicks
 needed — the installer generates per-install credentials and
 the entrypoint seeds the stores at boot. Subsequent provider
 + connector configuration happens through dedicated UI surfaces,
 not a one-shot setup wizard. There is no <Code>/setup</Code>{" "}
 page or <Code>setup.json</Code> blob; every piece of operator-
 owned config lives in a typed store with its own REST + UI.
 </p>

 <SubSection icon="terminal" title="Installer-side: generate the .env">
 <p>
 The customer-facing installer binary (<Code>phantom-installer</Code>)
 writes <Code>/opt/phantom/.env</Code> on first run. The file
 carries:
 </p>
 <Pre>{`# Service credentials + the 5 core compose-substitution digests
PHANTOM_DEFAULT_ADMIN_PASSWORD=<random-32-byte-base64>  # auto-generated, per-install
PHANTOM_SECRET_KEK=<random-32-byte-base64>              # AES-256-GCM key encryption key
MCP_TOKEN=<random-32-byte-hex>                          # bearer for /api/v1/*
PHANTOM_VERSION=<current-tag>                           # runtime version marker
DIGEST_PHANTOM_AGENT=sha256:...                         # image-digest pinning per service
DIGEST_PHANTOM_UPDATER=sha256:...
DIGEST_PHANTOM_XLOG=sha256:...
DIGEST_PHANTOM_CALDERA=sha256:...
DIGEST_PHANTOM_BROWSER=sha256:...`}</Pre>
 <p>
 The <Code>.env</Code> file is owned by the customer. The
 installer never ships secrets in the image; everything sensitive
 lands here on the target host. A companion file{" "}
 <Code>/opt/phantom/connector-digests.env</Code> carries the
 per-connector image digests (read only by phantom-updater).
 See{" "}
 <Link href="#image-pinning" className="link">
 Image Digest Pinning
 </Link>{" "}
 for the full digest contract.
 </p>
 </SubSection>

 <SubSection icon="play_arrow" title="First boot: entrypoint seeds the stores">
 <p>
 When the phantom-agent container starts for the first time, its{" "}
 <Code>entrypoint.sh</Code> walks an idempotent seed sequence
 BEFORE the Next.js + MCP processes accept traffic:
 </p>
 <ol className="list-decimal pl-5 space-y-1.5 text-sm">
 <li>
 <strong>TLS proxy boot</strong> — generates a self-signed
 cert at <Code>/tls/cert.pem</Code>; tls-proxy.js starts
 first because Next.js + MCP rely on it to serve HTTPS.
 </li>
 <li>
 <strong>Skills volume merge</strong> — checks{" "}
 <Code>phantom_mcp_skills</Code> against the image-baked
 default-skills tree. Per-release marker (
 <Code>.seeded_version</Code>) drives the auto-merge: image
 files copy in if new, operator edits stay. See{" "}
 <Link href="#skill-catalogue" className="link">
 Skill Catalogue
 </Link>
 .
 </li>
 <li>
 <strong>SecretStore seed</strong> — calls{" "}
 <Code>auth_store.seed_admin_defaults_if_empty()</Code>. If
 the SecretStore has no <Code>auth.v1</Code> entry for{" "}
 <Code>admin</Code>, writes the PBKDF2-HMAC-SHA256 hash of{" "}
 <Code>$PHANTOM_DEFAULT_ADMIN_PASSWORD</Code> and sets{" "}
 <Code>credentials_changed=false</Code>. Idempotent — if the
 hash already exists, this is a no-op.
 </li>
 <li>
 <strong>Knowledge-base reconcile</strong> — incremental
 source-hash walk to import bundle KBs into ChromaDB. Only
 changed docs re-embed.
 </li>
 <li>
 <strong>MCP subprocess</strong> — Python FastMCP starts on
 loopback HTTPS:8080 with the bearer{" "}
 <Code>$MCP_TOKEN</Code>.
 </li>
 <li>
 <strong>Next.js</strong> — accepts the first request only
 after the MCP healthcheck returns 200.
 </li>
 </ol>
 <p className="text-sm text-on-surface-variant">
 Boot is fail-loud: if any seed step errors, the container
 stops and reports the failed step in its logs. Half-seeded
 state is preferable to a silently-broken stack.
 </p>
 </SubSection>

 <SubSection icon="login" title="First operator login">
 <p>
 The operator opens the agent UI (port 3000, HTTPS through
 tls-proxy) and is presented with the login screen. Their
 credentials are:
 </p>
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 Username: <Code>admin</Code> (the only account — Phantom is
 single-user)
 </li>
 <li>
 Password: the auto-generated value from{" "}
 <Code>PHANTOM_DEFAULT_ADMIN_PASSWORD</Code> in the install
 host&apos;s <Code>/opt/phantom/.env</Code>
 </li>
 </ul>
 <p>
 The login response carries{" "}
 <Code>credentials_changed: false</Code>. The UI&apos;s{" "}
 <Code>AuthGate</Code> sees that flag and force-redirects to{" "}
 <Code>/profile</Code> before any other page renders. The
 operator must rotate the password (current → new) before
 going further; the rotation sets{" "}
 <Code>credentials_changed=true</Code> and the redirect lifts.
 See{" "}
 <Link href="#authentication" className="link">
 Authentication
 </Link>{" "}
 for the full flow + storage layout.
 </p>
 </SubSection>

 <SubSection icon="settings" title="Provider configuration">
 <p>
 Phantom needs at least one configured LLM provider to drive
 the chat agent. <Code>/providers</Code> is the configuration
 surface for Vertex AI (GCP service account) and Gemini API
 keys. The page wires to:
 </p>
 <Pre>{`POST   /api/agent/providers           -- create
GET    /api/agent/providers           -- list (secrets redacted)
PATCH  /api/agent/providers/{id}      -- update
DELETE /api/agent/providers/{id}      -- delete
PUT    /api/agent/providers/config    -- legacy single-default Vertex path
POST   /api/agent/providers/vertex/test -- probe credentials`}</Pre>
 <p>
 Credentials write through to the SecretStore at{" "}
 <Code>/providers/&lt;id&gt;/auth</Code>. The UI never sees
 the cleartext after save — GET responses return{" "}
 <Code>***</Code> in the secret slots. The agent has read-only
 MCP tools (<Code>providers_list</Code>,{" "}
 <Code>providers_get</Code>) but NO write tools — credential
 mutations are operator-only. See{" "}
 <Link href="#secret-store" className="link">
 Secret Store
 </Link>{" "}
 for the at-rest envelope.
 </p>
 </SubSection>

 <SubSection icon="cable" title="Connector + instance configuration">
 <p>
 With at least one provider configured, the operator picks
 connectors from the marketplace at{" "}
 <Code>/connectors</Code> and creates per-connector instances.
 Instance config (CALDERA URL + red/blue user credentials,
 XSIAM PAPI auth headers + playground id, xlog webhook
 endpoint + key, etc.) flows through the same dynamic-form
 widget vocabulary the manifest declares. See{" "}
 <Link href="#connectors-design" className="link">
 Connectors & Instances — Design
 </Link>
 .
 </p>
 <p className="text-sm text-on-surface-variant">
 Instance credentials write through to the SecretStore at{" "}
 <Code>/connectors/&lt;name&gt;/&lt;field&gt;</Code> with the
 same redaction-on-read contract as providers. The bundle&apos;s{" "}
 <Code>manifest.yaml</Code> declares the field schema for each
 connector type; the UI renders it as the create + edit
 forms.
 </p>
 </SubSection>

 <SubSection icon="restart_alt" title="Factory reset path">
 <p>
 The host-side <Code>phantom-factory-reset</Code> utility
 returns a Phantom install to shipped defaults: wipes the
 SecretStore, the data root, the skills volume, and every
 connector instance + provider entry. Re-runs the entrypoint
 seed flow on next boot as if it were a fresh install.{" "}
 <Code>--dry-run</Code> prints what would be wiped without
 touching anything; <Code>--yes</Code> skips the interactive
 confirmation. The operator&apos;s <Code>.env</Code>{" "}
 (PHANTOM_DEFAULT_ADMIN_PASSWORD, KEK, digests) is preserved
 so the post-reset stack comes up under the same identity. See{" "}
 <Link href="#authentication" className="link">
 Authentication → Factory reset
 </Link>{" "}
 for the CLI ceremony.
 </p>
 </SubSection>

 <SubSection icon="construction" title="Implementation references">
 <ul className="list-disc pl-6 space-y-1 text-sm">
 <li><Code>installer/</Code> — installer binary template that generates the per-install <Code>.env</Code></li>
 <li><Code>mcp/agent/entrypoint.sh</Code> — first-boot seed sequence (TLS / skills / SecretStore / MCP / Next.js)</li>
 <li><Code>bundles/spark/mcp/src/usecase/ui_auth.py</Code> — <Code>seed_admin_defaults_if_empty()</Code></li>
 <li><Code>mcp/agent/components/auth/auth-gate.tsx</Code> — first-login redirect to <Code>/profile</Code> on <Code>credentials_changed=false</Code></li>
 <li><Code>mcp/agent/app/providers/page.tsx</Code> — provider config UI</li>
 <li><Code>mcp/agent/app/connectors/page.tsx</Code> — connector marketplace + instance config UI</li>
 <li><Code>mcp/agent/app/profile/page.tsx</Code> — password rotation UI</li>
 <li><Code>installer/templates/phantom-factory-reset</Code> — host-side reset utility</li>
 </ul>
 </SubSection>
 </Section>
);
}

// ─── Chat pipeline: SSE event stream ───────────────────────────────

function SseEvents() {
 return (
 <Section id="sse-events" icon="stream" title="SSE Event Stream">
 <p>
 Every chat turn streams server-sent events back to the browser.
 The event stream is the single contract between chat-route and
 client; the UI renders entirely from these events. Knowing the
 event taxonomy is the first stop when chat behaves wrong.
 </p>
 <SubSection icon="data_object" title="Event types">
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <Code>session</Code> — emitted once at turn start with the
 session id (so a brand-new session shows in the URL).
 </li>
 <li>
 <Code>model</Code> — chosen model + override source
 (<Code>session</Code> | <Code>header</Code> | <Code>default</Code>).
 </li>
 <li>
 <Code>text_delta</Code> — incremental model text. Many of
 these per turn.
 </li>
 <li>
 <Code>tool_call</Code> — a tool dispatch with name, args,
 metadata. Renders the tool card.
 </li>
 <li>
 <Code>tool_result</Code> — the matching result payload.
 </li>
 <li>
 <Code>approval_required</Code> — emitted when a tier-2/3
 tool gates. Operator clicks Approve to release the awaited
 promise.
 </li>
 <li>
 <Code>context_warning</Code> — context utilisation crossed
 the threshold; UI shows a yellow banner.
 </li>
 <li>
 <Code>compaction_start</Code> /{" "}
 <Code>compaction_end</Code> /{" "}
 <Code>compaction_failed</Code> — manual or auto compaction.
 </li>
 <li>
 <Code>cache_hit</Code> — Vertex prompt-cache hit; UI flips
 the model chip dot.
 </li>
 <li>
 <Code>plan_proposed</Code> — plan-mode card payload.
 </li>
 <li>
 <Code>subagent_started</Code> /{" "}
 <Code>subagent_token</Code> /{" "}
 <Code>subagent_completed</Code> — subagent panel events.
 </li>
 <li>
 <Code>cost</Code> — per-turn cost summary (input / output /
 cached tokens, dollar estimate).
 </li>
 <li>
 <Code>done</Code> — turn complete. Always emitted exactly
 once, even on failure.
 </li>
 </ul>
 </SubSection>
 <SubSection icon="lightbulb" title="Why one stream, not many">
 <p>
 Multiple event types over one stream simplifies the client:
 a single <Code>EventSource</Code> with a switch on{" "}
 <Code>event.type</Code>. Alternative designs (separate
 streams per kind, websockets) bring no benefit and complicate
 reconnect semantics.
 </p>
 </SubSection>
 </Section>
);
}

// ─── Context & Sessions: session + memory stores ───────────────────

function SessionStore() {
 return (
 <Section id="session-store" icon="chat_bubble" title="Session Store">
 <p>
 Sessions are first-class — every chat opens a session row,
 every message appends a row, and the right-side telemetry panel
 rehydrates from messages on reload. The store is two SQLite
 tables wrapped in <Code>SqliteSessionStore</Code>.
 </p>
 <SubSection icon="database" title="Schema">
 <Pre>{`sessions (
  id              TEXT PRIMARY KEY,        -- s_<6-char-base32>
  workspace       TEXT NOT NULL,
  created_at      TEXT NOT NULL,            -- ISO8601 UTC
  updated_at      TEXT NOT NULL,
  title           TEXT,                     -- auto-derived from 1st prompt
  preferred_model TEXT,                     -- /model session override
  metadata_json   TEXT NOT NULL DEFAULT '{}'
);

messages (
  id              TEXT PRIMARY KEY,
  session_id      TEXT NOT NULL,
  ts              TEXT NOT NULL,
  role            TEXT NOT NULL,            -- user | assistant | system | tool
  kind            TEXT,                     -- compaction-checkpoint | tool-call | etc
  content         TEXT NOT NULL,            -- model text or tool JSON
  metadata_json   TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE INDEX idx_messages_session ON messages(session_id, ts);`}</Pre>
 </SubSection>
 <SubSection icon="lightbulb" title="What is and isn't persisted">
 <p>
 Every user / assistant / tool message lands. Raw model deltas
 (the per-token <Code>text_delta</Code> events) are NOT
 persisted — only the assembled assistant message at end-of-turn.
 Approval requests, context warnings, and cache hits write audit
 rows but not message rows. The right-side telemetry panel
 reconstructs from the audit log + message kinds, which is why
 telemetry rehydrates after reload.
 </p>
 </SubSection>
 <SubSection icon="schedule" title="Retention">
 <p>
 Sessions persist for 30 days by default
 (<Code>SESSIONS_RETENTION_DAYS</Code>). A periodic sweeper
 deletes rows older than the cutoff, cascading to messages.
 Operators can pin a session to opt out of expiry — pinned
 sessions show a 📌 indicator in the sidebar and survive sweeps.
 </p>
 </SubSection>
 </Section>
);
}

function MemoryStore() {
 return (
 <Section id="memory-store" icon="database" title="Memory Store Internals">
 <p>
 Memory is a vector-indexed key/value store with three ranking
 augmentations layered over base similarity. The store is one
 SQLite database with a vector extension (sqlite-vec) plus an
 FTS5 virtual table for keyword promotion.
 </p>
 <SubSection icon="database" title="Schema">
 <Pre>{`memory_entries (
  id            TEXT PRIMARY KEY,
  scope         TEXT NOT NULL,        -- agent | session | user | system
  scope_id      TEXT,                  -- session_id when scope='session'
  key           TEXT NOT NULL,
  value         TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  ttl_seconds   INTEGER,                -- nullable → no expiry
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  embedding     BLOB                   -- 768-dim float32 (text-embedding-004)
);

CREATE INDEX idx_memory_scope ON memory_entries(scope, scope_id);
CREATE VIRTUAL TABLE memory_fts USING fts5(
  key, value, content='memory_entries', tokenize='porter unicode61'
);`}</Pre>
 </SubSection>
 <SubSection icon="diversity_3" title="Ranking pipeline">
 <ul className="list-disc pl-5 space-y-1.5 text-sm">
 <li>
 <Term>1. Vector retrieval</Term> — top-K (default 25) by
 cosine similarity using sqlite-vec. Embeddings are cached at
 write-time so reads never call Vertex.
 </li>
 <li>
 <Term>2. MMR rerank</Term> — re-score each candidate as{" "}
 <Code>λ × similarity − (1 − λ) × max_pairwise_sim</Code>{" "}
 against already-selected candidates. Default λ = 0.7. Removes
 near-duplicates from the top-N output.
 </li>
 <li>
 <Term>3. Temporal decay</Term> — multiply by{" "}
 <Code>exp(−age_days × λ)</Code>. Default λ = 0.01. The result
 row UI tags candidates as fresh / recent / old based on the
 decay bucket.
 </li>
 <li>
 <Term>4. FTS5 promotion</Term> — for queries with literal
 tokens (UUIDs, IPs, hostnames), the FTS5 query promotes
 keyword hits ahead of pure-similarity matches and tags them
 with an <Term>FTS hit</Term> badge.
 </li>
 </ul>
 </SubSection>
 <SubSection icon="schedule" title="TTL sweeper">
 <p>
 A 5-minute tick deletes rows where{" "}
 <Code>ttl_seconds IS NOT NULL AND created_at + ttl &lt; now</Code>.
 Effective TTL is therefore the configured value plus up to
 5 minutes. For sub-minute lifetimes, prefer scope=session
 (cleared on session end) over a tiny TTL.
 </p>
 </SubSection>
 </Section>
);
}

// ─── Knowledge & Skills ────────────────────────────────────────────

function KnowledgePipeline() {
 return (
 <Section id="knowledge-pipeline" icon="menu_book" title="Knowledge Pipeline">
 <p>
 Knowledge bases are bundle-shipped, schema-validated, semantically
 searchable reference content. They differ from memory in three
 ways: read-only at the agent surface, sourced from the bundle
 (not chat), and indexed at boot rather than on-write.
 </p>
 <SubSection icon="folder_open" title="Bundle layout">
 <Pre>{`bundles/spark/kbs/<name>/
├── schema.json            # JSON-Schema for entry validation
└── entries/
    ├── 001-arch-overview.md
    ├── 002-scenario-runbook.md
    └── ...

# Two KBs ship today:
#   phantom-soc    — main reference content
#   xql-examples   — curated Cortex XQL / XSIAM queries for
#                    RAG retrieval, spanning many datasets,
#                    MITRE techniques and XQL stages`}</Pre>
 </SubSection>
 <SubSection icon="loop" title="Boot reconcile">
 <p>
 <Code>SqliteKnowledgeBase.reconcile_from_bundle()</Code> runs at
 every MCP boot. For each entry: parse markdown frontmatter,
 validate against <Code>schema.json</Code>, hash the source. If
 the hash matches the stored row, skip; otherwise embed via
 Vertex <Code>text-embedding-004</Code> and upsert. Source-hash
 detection means an unchanged repo = zero Vertex calls at boot.
 </p>
 </SubSection>
 <SubSection icon="search" title="Retrieval">
 <p>
 <Code>knowledge_search(kb, query, top_k)</Code> embeds the query
 and runs cosine similarity against the KB&apos;s vector index.
 The xsiam connector wraps this in{" "}
 <Code>find_xql_examples_rag</Code> for natural-language XQL
 example retrieval; phantom-soc is queried whenever the agent
 needs conceptual context.
 </p>
 </SubSection>
 <SubSection icon="science" title="Why bundle-shipped (not runtime CRUD)">
 <p>
 KBs encode <em>curated</em> reference content reviewed before
 release. Runtime CRUD would let drift accumulate (operators add
 entries that contradict the schema; embedding drift between
 entries created at different times). Bundle-shipping enforces
 a review gate. A future tier-3 may add operator-authored KBs
 with a separate origin tag, but the bundle KBs will stay
 immutable from the UI.
 </p>
 </SubSection>
 </Section>
);
}

function SkillCatalogue() {
 return (
 <Section id="skill-catalogue" icon="auto_awesome" title="Skill Catalogue">
 <p>
 Skills are markdown procedural recipes the agent reads at the
 start of relevant sessions to bias its tool selection. Unlike
 tools (which are runnable code), skills are{" "}
 <em>guidance</em> — they tell the agent &ldquo;when X, do
 Y&rdquo; in natural language. Three categories live under{" "}
 <Code>bundles/spark/mcp/skills/</Code>: foundation (5 skills),
 scenarios (12), workflows (3) — 20 skills total. Each MD file
 carries optional YAML frontmatter declaring its category,
 activation triggers, locked state, and loading mode.
 </p>

 <SkillsActivation />
 <p className="text-xs text-on-surface-variant/70 italic mt-1">
 Source MD files in the bundle → docker COPY into the image at
 bake time → entrypoint.sh merges into the named volume on every
 boot (marker-driven; preserves operator customizations
 while letting new-release skills auto-appear) → MCP scans on
 startup + registers each as a callable tool → three activation
 paths get the skill body into the chat context for the agent to
 follow.
 </p>
 <SubSection icon="article" title="Skill anatomy">
 <Pre>{`---
name: generate_shared_iocs
displayName: Generate Shared IOCs
category: foundation
locked: true               # platform-enforced; can't be disabled
loadingMode: always        # vs "on_demand" (only when activation matches)
when:
  keywords: [ioc, indicator, observable]
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
 <SubSection icon="dns" title="Volume-mounted runtime">
 <p>
 The MCP image builds skills into{" "}
 <Code>/app/skills-default/</Code>. Compose mounts a named
 volume <Code>phantom_mcp_skills</Code> at{" "}
 <Code>/app/skills</Code>. The entrypoint copies defaults into
 the volume only when the volume is empty; on subsequent boots
 it leaves the volume alone. <em>Operator edits to{" "}
 <Code>/app/skills/</Code> survive image rebuilds.</em> The
 trade-off: editing a skill in the repo and rebuilding does
 NOT propagate without <Code>down -v</Code> or{" "}
 <Code>FORCE_SKILLS_SYNC=1</Code>.
 </p>
 </SubSection>
 <SubSection icon="lock" title="Lock state and overrides">
 <p>
 Skills with <Code>locked: true</Code> in frontmatter cannot be
 disabled by the operator — useful for foundational skills that
 break the agent if absent (e.g.{" "}
 <Code>generate_shared_iocs</Code>). Per-workspace overrides
 disable a skill in one workspace without affecting the global
 default; stored in <Code>skill_overrides</Code> table keyed by
 (workspace, skill_name).
 </p>
 </SubSection>
 <SubSection icon="terminal" title="Skills CRUD tools">
 <p>
 Two MCP tool families operate on the catalogue:{" "}
 <Code>skills_crud_*</Code> (list / get / upsert / delete; used
 by the /skills page) and <Code>simulation_skills_*</Code>{" "}
 (load / activate; used during chat to inject skills into the
 system prompt). Both read from the mounted volume so they see
 the live catalogue.
 </p>
 </SubSection>
 <SubSection icon="auto_awesome" title="Frontmatter as the source of truth">
 <p>
 Frontmatter is the canonical metadata surface.{" "}
 <Code>skills_crud.py::parse_frontmatter</Code> (PyYAML-backed,
 falls back gracefully on malformed YAML) extracts{" "}
 <Code>name</Code>, <Code>displayName</Code>,{" "}
 <Code>category</Code>, <Code>description</Code>,{" "}
 <Code>icon</Code>, <Code>source</Code>,{" "}
 <Code>loadingMode</Code>, <Code>locked</Code>, and{" "}
 <Code>attack[]</Code> on every <Code>skills_list_all</Code>{" "}
 call. The <Code>/api/skills</Code> route forwards the rich
 shape; <Code>app/skills/page.tsx</Code> fetches it on mount and
 renders live data. New MD files appear automatically; deletion
 is reflected on next page load.
 </p>
 <p>
 A small hardcoded array exists as a first-paint / SSR fallback
 so the page renders something during the live fetch round-trip.
 It&apos;s a cushion, not the source of truth.
 </p>
 </SubSection>
 <SubSection icon="edit" title="Full CRUD from the UI">
 <p>
 The detail panel on each skill card grew three header buttons:{" "}
 <Term>Download</Term> (fetches the live MD body via{" "}
 <Code>GET /api/skills?file_path=…</Code> and triggers a Blob
 → <Code>&lt;a download&gt;</Code>),{" "}
 <Term>Save</Term> (commits textarea edits via{" "}
 <Code>PUT /api/skills</Code> — backend creates a{" "}
 <Code>.md.bak</Code> first), and <Term>Delete</Term>{" "}
 (soft-deletes via <Code>DELETE /api/skills?file_path=…</Code>{" "}
 → moves the MD to <Code>/app/skills/.deleted/</Code>{" "}
 with a backup-on-rename collision handler).
 </p>
 <p>
 The body textarea is controlled state with lazy-load — clicking
 into the editor pulls the live body via <Code>skills_read</Code>;
 not loaded eagerly because that&apos;d burn bytes for the 23+
 skills the operator only wants to scan. An unsaved-change guard
 fires <Code>window.confirm</Code> on close.
 </p>
 <p>
 The Create flow takes display name (auto-derives the filename
 via <Code>slugifyForFilename</Code>), category dropdown
 (foundation/scenarios/validation/workflows — the only valid
 ones), description, and body. Submit composes minimal
 frontmatter and POSTs. Locked skills (<Code>locked: true</Code>
 in frontmatter) render Delete as disabled with a
 &ldquo;platform-locked&rdquo; tooltip so foundation skills
 can&apos;t be accidentally nuked.
 </p>
 <p>
 An <Term>Import</Term> button sits next to Create. Hidden
 file input accepts a <Code>.md</Code> file; client-side parses
 the YAML frontmatter (without pulling a YAML library — line-
 by-line key:value scan is sufficient for the fields we care
 about: <Code>name</Code> + <Code>category</Code>) and POSTs to{" "}
 <Code>/api/skills</Code> with the same{" "}
 <Code>{`{category, filename, content}`}</Code> shape Create
 uses. Frontmatter-less files default to category{" "}
 <Code>scenarios</Code> with the filename as canonical name;
 the backend re-validates so a garbage category from a hand-
 edited frontmatter surfaces a clean error. Import + Download
 give operators a portable round-trip for skills between
 deployments without needing repo access.
 </p>
 <p>
 Summary widgets at the top of the page (Total / Active /
 Categories / Invocations) derive from the LIVE skills array.
 Invocations is currently a placeholder; populating it requires
 the chat-route to emit a per-skill invocation event, which
 ships when the audit-event surface absorbs that family.
 </p>
 <p>
 The header carries just the operator-actionable affordances:
 Import + Create. Phantom is single-tenant; no workspace
 selector.
 </p>
 </SubSection>
 <SubSection icon="psychology" title="Chat agent skill awareness">
 <p>
 The chat system prompt now includes an{" "}
 <Code>## AVAILABLE SKILLS</Code> block listing every installed
 skill&apos;s minimal metadata: name, displayName, category,
 description, ATT&amp;CK tactics. Total ~2-3KB for our 23 skills.
 The bodies stay out of the prompt (50-150KB if we shipped
 them); the agent calls <Code>skills_read</Code> when it decides
 to apply a specific skill.
 </p>
 <p>
 Implementation: <Code>lib/skills-registry.ts</Code> runs a
 server-side <Code>fetchSkillsForPrompt</Code> that calls the
 embedded MCP&apos;s <Code>skills_list_all</Code> tool and maps
 to a <Code>SkillSummary</Code> shape. The chat handler runs
 it in parallel with the personality fetch (one extra MCP
 round-trip for the whole turn) and threads the registry to
 every <Code>callGemini</Code> site. <Code>renderSkillsBlock</Code>{" "}
 in <Code>lib/system-prompt.ts</Code> formats the block with
 explicit instructions on when to apply / how to compose
 foundation+scenario+validation skills.
 </p>
 <p>
 Failure mode is &ldquo;graceful skip&rdquo;: if{" "}
 <Code>fetchSkillsForPrompt</Code> errors, the chat turn proceeds
 without the block rather than failing. Audit log surfaces the
 drift via docker logs.
 </p>
 </SubSection>
 <SubSection icon="schedule" title="Job skill binding">
 <p>
 Prompt-action jobs grew an optional <Code>action.skill</Code>{" "}
 field. UI: a Skill (optional) dropdown grouped by category in{" "}
 <Code>/jobs/new</Code>; default is{" "}
 <em>Let agent decide</em> — the model picks based on the
 system-prompt skills block. Picking a specific
 skill writes the canonical name to the job row.
 </p>
 <p>
 At fire time, <Code>job_scheduler.py::_load_skill_body</Code>{" "}
 resolves the name to its MD body and prepends it to the user
 message inside <Code>&lt;skill name=&quot;…&quot;&gt;</Code>{" "}
 tags. Makes scheduled exercises deterministic regardless of
 model drift. Skill not found → warning logged, falls back to
 plain prompt rather than failing the run. Validation
 (<Code>_validate_action</Code>) checks shape only — existence
 is checked at fire time, since skills can come/go after a job
 is added.
 </p>
 </SubSection>
 <SubSection icon="notifications" title="Job-run notifications">
 <p>
 The manifest declares four new notification topics:{" "}
 <Code>job-run-completed</Code> (info),{" "}
 <Code>job-run-failed</Code> (warning),{" "}
 <Code>approval-requested</Code> (warning), and{" "}
 <Code>marketplace-install</Code> (info). The scheduler&apos;s
 post-run hook publishes to the appropriate topic with
 <Code> {`{job_name, run_id, trigger, action_name, duration_ms, summary, error?}`}</Code>{" "}
 payload. Skipped runs don&apos;t emit (cron-cap squelching
 noise). Best-effort: a publish failure logs a warning but
 doesn&apos;t fail the run — the audit row above is still the
 canonical record.
 </p>
 </SubSection>

 <SubSection icon="api" title="REST + MCP tool surface">
 <Pre>{`REST  (Next.js proxy + cookie auth)
GET    /api/agent/skills                       -- list all skills with metadata
GET    /api/agent/skills?file_path=<path>      -- read one skill body (lazy)
POST   /api/agent/skills                       -- create + frontmatter compose
PUT    /api/agent/skills                       -- save body / metadata
DELETE /api/agent/skills?file_path=<path>      -- soft-delete to .deleted/

MCP   (agent-callable, bearer MCP_TOKEN)
skills_list_all()           -- enumerate registry with metadata
skills_read(file_path)      -- pull one skill's body
skills_crud_upsert(...)     -- agent-side create + write
skills_crud_delete(...)     -- agent-side soft-delete
simulation_skills_load(keywords?)  -- system-prompt injection
simulation_skills_activate(name)   -- explicit activation`}</Pre>
 <p className="text-sm text-on-surface-variant">
 Read-side tools (<Code>skills_list_all</Code>,{" "}
 <Code>skills_read</Code>) are Tier 1 — no approval card. Write-
 side tools (<Code>skills_crud_upsert</Code>,{" "}
 <Code>skills_crud_delete</Code>) are Tier 2 — every change
 surfaces an approval card and writes an audit row. The chat
 system prompt reads via <Code>simulation_skills_load</Code> at
 turn start; this is server-side, no approval.
 </p>
 </SubSection>

 <SubSection icon="construction" title="Implementation references">
 <ul className="list-disc pl-6 space-y-1 text-sm">
 <li><Code>bundles/spark/mcp/skills/&lt;category&gt;/*.md</Code> — bundle-shipped skills source</li>
 <li><Code>bundles/spark/mcp/src/usecase/skills_crud.py</Code> — frontmatter parse + CRUD primitives</li>
 <li><Code>bundles/spark/mcp/src/usecase/simulation_skills.py</Code> — activation + chat-side load</li>
 <li><Code>bundles/spark/mcp/src/api/skills.py</Code> — REST routes</li>
 <li><Code>mcp/agent/app/api/skills/route.ts</Code> — Next.js proxy</li>
 <li><Code>mcp/agent/lib/skills-registry.ts</Code> — <Code>fetchSkillsForPrompt()</Code> + <Code>SkillSummary</Code> shape</li>
 <li><Code>mcp/agent/lib/system-prompt.ts</Code> — <Code>renderSkillsBlock()</Code></li>
 <li><Code>mcp/agent/app/skills/page.tsx</Code> — UI (browse + edit + create + import)</li>
 <li><Code>mcp/agent/entrypoint.sh</Code> — boot-time volume seed + marker-driven merge</li>
 </ul>
 </SubSection>
 </Section>
);
}

// ─── Connectors & Extensions: marketplace ──────────────────────────

function MarketplaceLogic() {
 return (
 <Section id="marketplace-logic" icon="storefront" title="Marketplace Logic">
 <p>
 <strong>This section is the source of truth for the connector
 marketplace.</strong> Any change to <Code>/api/v1/marketplace/*</Code>,
 the install state model, the catalogue source, the schema, or the
 system-vs-user distinction MUST conform to the contract below.
 </p>

 <SubSection icon="storage" title="Canonical state — one storage home">
 <p>
 Install state lives in a single sqlite store, owned by the MCP.
 </p>
 <Pre>{`marketplace.db  (DATA_ROOT/ — SQLite, sole source of truth)
 └── marketplace_installs(
       connector_id  TEXT PRIMARY KEY,
       installed_at  TEXT NOT NULL,        -- ISO 8601 UTC
       origin        TEXT NOT NULL,        -- 'bundle' | 'user'
       version       TEXT NOT NULL
     )

Catalogue (read at every list call from disk — cheap, YAML on disk):
  bundle:        bundles/spark/connectors/<id>/connector.yaml
  user-uploaded: /app/data/user_connectors/<id>/connector.yaml
`}</Pre>
 <ul className="list-disc pl-6 space-y-1">
 <li><Code>origin</Code> gates DELETE — bundle connectors are 403-rejected (image-baked, undeletable at runtime); user connectors deletable via DELETE /api/v1/marketplace/&lt;id&gt;.</li>
 <li><Code>MarketplaceStore.upgrade_install_existing_instances</Code> auto-installs every connector that has at least one row in <Code>instances.db</Code> on upgrade boot.</li>
 </ul>
 </SubSection>

 <SubSection icon="schema" title="Schema is single — connector.schema.json">
 <p>
 Every <Code>connector.yaml</Code> validates against{" "}
 <Code>bundles/spark/connectors/connector.schema.json</Code>{" "}
 at boot via <Code>usecase/connector_schema.py</Code>. Bundle
 and user-uploaded connectors validate against the same file —
 no separate schemas for system vs user. Drift produces an
 immediate boot failure with the path-into-the-field error.
 </p>
 </SubSection>

 <SubSection icon="inventory_2" title="Bundle connectors that ship in a release">
 <p>
 Nine connectors are bundle connectors: <Code>caldera</Code>,{" "}
 <Code>cortex-content</Code>, <Code>cortex-docs</Code>,{" "}
 <Code>cortex-xdr</Code>, <Code>http-sender</Code>, <Code>web</Code>,{" "}
 <Code>wec-sender</Code>, <Code>xlog</Code> and <Code>xsiam</Code>.
 Each is declared in <Code>manifest.yaml</Code>{" "}
 <Code>toolConnectors[]</Code>, built into its own image by CI, and
 pinned by digest in the release manifest as{" "}
 <Code>DIGEST_PHANTOM_CONNECTOR_&lt;ID&gt;</Code>. The installer copies
 those lines into <Code>connector-digests.env</Code>, which
 phantom-updater reads (bind mount, no auth, re-read every 30 seconds)
 to start and reconcile the per-instance containers. The two senders,{" "}
 <Code>http-sender</Code> and <Code>wec-sender</Code>, are bundle
 connectors so that the Cortex Analytics trigger skills, which call
 them, work on a fresh install with no upload and no hand-built image.
 </p>
 <ul className="list-disc pl-6 space-y-1">
 <li>
 A bundle connector&apos;s <Code>connector.yaml</Code> declares no{" "}
 <Code>image:</Code>. The agent passes an <Code>image_ref</Code> to
 the updater only when the yaml declares one, and an explicit tag
 would bypass the digest pin. A user connector must declare{" "}
 <Code>image:</Code>; the upload route enforces it.
 </li>
 <li>
 When an id is both an uploaded connector and a bundle connector, the
 bundle copy wins the catalogue and the upload route refuses the id.
 An install that had uploaded the connector keeps its instances,
 their configuration and their secrets, and the updater recreates
 the container at the pinned digest on its next reconcile.
 </li>
 <li>
 Adding a bundle connector means registering it in every site that
 lists the built-in connectors (the manifest, the build and release
 workflows, the updater&apos;s known-connector list, the probes, the
 marketplace catalogue); see{" "}
 <Code>bundles/spark/connectors/CLAUDE.md</Code>.
 </li>
 </ul>
 </SubSection>

 <SubSection icon="storefront" title="Install state is the functional gate">
 <p>
 Install state is a real gate, not a UI sentinel. The sequence:
 </p>
 <Pre>{`Operator opens /connectors → Marketplace tab
            ↓
GET /api/v1/marketplace returns 9 bundle connectors + N user-uploaded
   (each carries installed: bool, install: {origin, version, ts})
            ↓
Operator clicks Install on a card
            ↓
POST /api/v1/marketplace/<id>/install → marketplace.db row
                                      → audit: marketplace_install
            ↓
Connector now "installed" in the catalogue. STILL NO INSTANCE YET.
            ↓
Operator clicks Create Instance → /connectors → <id> → form
            ↓
POST /api/v1/instances → instances.py checks marketplace_store.is_installed
                       → 409 connector_not_installed if not (deny)
                       → otherwise InstanceStore.create writes row
                       → phantom-updater starts per-instance container
                       → MCP's iter_registrations re-runs
                       → tools now advertise
            ↓
Agent's tool catalogue: <id>/<tool_name> entries appear`}</Pre>
 <p>
 The install gate runs at <Code>POST /api/v1/instances</Code>{" "}
 (see <Code>bundles/spark/mcp/src/api/instances.py</Code>).
 Tool registration runs at the loader (see{" "}
 <Code>iter_registrations</Code> — only connectors with
 instances get their tools registered). The combination produces
 strict semantics: install + instance → tools. Either missing →
 no tools.
 </p>
 </SubSection>

 <SubSection icon="upload_file" title="User-uploaded connectors — system vs user">
 <p>
 The operator can upload custom <Code>connector.yaml</Code> files
 via <Code>POST /api/v1/marketplace/upload</Code> (multipart) or
 via the agent tool <Code>connector_upload(yaml_content)</Code>.
 Validation:
 </p>
 <ul className="list-disc pl-6 space-y-1">
 <li>Schema validation against <Code>connector.schema.json</Code> (same as bundle connectors).</li>
 <li>The declared <Code>id</Code> must not collide with a bundle id (409 <Code>id_collides_with_bundle</Code>) or an existing user id (409 <Code>id_already_exists</Code> — operator must DELETE first to replace).</li>
 <li>The YAML MUST declare an <Code>image</Code> field — the OCI reference to the operator&apos;s pre-published connector container (e.g. <Code>ghcr.io/your-org/your-connector:v1.0</Code>). phantom-updater pulls this image when instances are created.</li>
 </ul>
 <p>
 On success the YAML is written to{" "}
 <Code>/app/data/user_connectors/&lt;id&gt;/connector.yaml</Code>{" "}
 (volume-persistent across upgrades). The marketplace card shows{" "}
 <Code>origin: user</Code>. <Code>DELETE /api/v1/marketplace/&lt;id&gt;</Code>{" "}
 removes user connectors entirely (refused if instances exist).
 Bundle connectors get 403 — they&apos;re image-baked and can&apos;t
 be removed at runtime. Use uninstall (which keeps the catalogue
 entry, just flips the install flag) to hide a bundle connector
 from instance creation.
 </p>
 <p>
 An uploaded connector is first-class once it has an instance.
 Everything that asks &ldquo;which connectors exist?&rdquo; reads{" "}
 <Code>usecase/connector_catalog.py</Code>: the bundle manifest
 entries first, then the uploaded connectors (a bundle id always
 wins a collision). Four consumers use it:
 </p>
 <ul className="list-disc pl-6 space-y-1">
 <li><strong>Tool registration</strong> — <Code>iter_registrations</Code> advertises an uploaded connector&apos;s tools as <Code>&lt;id&gt;.&lt;tool&gt;</Code> while it has an instance, honouring the per-instance <Code>disabled_tools</Code> list and the human-approval list. Uploaded connectors get <strong>no</strong> legacy flat aliases, so an upload can never shadow a built-in tool name. A broken upload is logged and skipped; it never stops other connectors&apos; tools from registering.</li>
 <li><strong>Tool counts</strong> — <Code>tool_summary</Code> counts them the same way.</li>
 <li><strong>State list</strong> — <Code>GET /api/v1/connectors</Code> and <Code>/{"{id}"}</Code> include them, and every row carries <Code>origin</Code> (<Code>bundle</Code> | <Code>user</Code> | <Code>orphaned</Code>). <Code>in_manifest</Code> stays true only for bundle connectors.</li>
 <li><strong>Tools panel</strong> — <Code>GET /api/v1/connectors/&lt;id&gt;/tools</Code> resolves uploaded connectors too; it answers 404 only when the id is in neither place.</li>
 </ul>
 <p>
 The container proxy for each tool is synthesized from the
 connector&apos;s <Code>spec.tools</Code>, so no connector source is
 needed inside the agent image. Creating the instance starts the
 container and the updater&apos;s container-URL callback reloads the
 tool registry, so the tools appear without a restart.
 </p>
 </SubSection>

 <SubSection icon="shield" title="Catalog boundary vs credential boundary">
 <p>
 The agent has 4 marketplace tools — deliberately on the
 CATALOG side of the boundary, not the credential side:
 </p>
 <ul className="list-disc pl-6 space-y-1">
 <li><Code>marketplace_list</Code> — read-only catalogue + install state. Mirror of <Code>GET /api/v1/marketplace</Code>.</li>
 <li><Code>marketplace_install(connector_id)</Code> — idempotent install row write.</li>
 <li><Code>marketplace_uninstall(connector_id)</Code> — refuses with instances_count if any instances exist (operator must clean up secrets via the UI first).</li>
 <li><Code>connector_upload(yaml_content)</Code> — validates + writes the user_connectors directory.</li>
 </ul>
 <p>
 None of these tools touch a SecretStore value. Instance
 creation (which carries secrets) stays operator-only — the
 agent can hand the operator a fully-installed connector but
 still can&apos;t fill in the operator&apos;s API key for them.
 See CLAUDE.md&apos;s &ldquo;Catalog boundary ≠ credential
 boundary&rdquo; section for the 2-question test that gates any
 future MCP tool addition.
 </p>
 </SubSection>

 <SubSection icon="rule" title="Out of scope">
 <ul className="list-disc pl-6 space-y-1">
 <li><strong>Module-style or class-style dispatch.</strong> Schema enum is <Code>[&quot;container&quot;]</Code> only. Every connector runs as a per-instance container.</li>
 <li><strong>Env-var-driven instance creation.</strong> Instances are never materialized from env vars (CALDERA_URL, PAPI_AUTH_HEADER, etc.); create them through the instance store.</li>
 <li><strong>Bundle connector deletion at runtime.</strong> DELETE on a bundle id returns 403. Use uninstall to hide it.</li>
 <li><strong>Bundle/user id sharing.</strong> User uploads cannot reuse a bundle id; upload rejected at validation time.</li>
 <li><strong>Image building inside Phantom.</strong> Users publish their connector container to any OCI registry first; Phantom only references the image. No <Code>docker build</Code> inside our containers.</li>
 </ul>
 </SubSection>

 <SubSection icon="construction" title="Implementation references">
 <ul className="list-disc pl-6 space-y-1">
 <li><strong>Schema</strong>: <Code>bundles/spark/connectors/connector.schema.json</Code> (JSON Schema Draft 2020-12).</li>
 <li><strong>Validator</strong>: <Code>bundles/spark/mcp/src/usecase/connector_schema.py</Code> — boot-time + upload-time.</li>
 <li><strong>Store</strong>: <Code>bundles/spark/mcp/src/usecase/marketplace_store.py</Code> — SQLite, JSON migration, upgrade migration, singleton accessor.</li>
 <li><strong>REST routes</strong>: <Code>bundles/spark/mcp/src/api/marketplace.py</Code> — list / get / install / uninstall / upload / delete.</li>
 <li><strong>Install gate</strong>: <Code>bundles/spark/mcp/src/api/instances.py</Code> — install-state check before <Code>InstanceStore.create</Code>.</li>
 <li><strong>Loader</strong>: <Code>bundles/spark/mcp/src/usecase/connector_loader.py</Code> — container-only <Code>_resolve_callable</Code>, deleted <Code>_AUTO_MIGRATION</Code>, gated <Code>iter_registrations</Code>.</li>
 <li><strong>Catalog</strong>: <Code>bundles/spark/mcp/src/usecase/connector_catalog.py</Code> — the single list of bundle + uploaded connectors that the loader and <Code>api/connectors.py</Code> both read.</li>
 <li><strong>Agent tools</strong>: <Code>bundles/spark/mcp/src/usecase/builtin_components/self_mod_tools.py</Code> — <Code>marketplace_list</Code>, <Code>marketplace_install</Code>, <Code>marketplace_uninstall</Code>, <Code>connector_upload</Code>.</li>
 <li><strong>Updater</strong>: <Code>updater/src/main.py</Code> — <Code>image_ref</Code> body field for user-uploaded connectors.</li>
 <li><strong>Next.js proxies</strong>: <Code>mcp/agent/app/api/agent/marketplace/*</Code> — thin forwards to MCP.</li>
 </ul>
 </SubSection>
 </Section>
);
}

// ─── Data Sources marketplace (vendor schemas) ─────────────────────

function DataSourcesMarketplace() {
 return (
 <>
 <Section id="data-sources" icon="dataset" title="Data Sources">
 <p>
 <strong>This section is the source of truth for the Data Sources
 marketplace.</strong> Data sources are vendor field schemas —
 a structured description of what a vendor&apos;s product
 actually emits on the wire. Install one and the agent generates
 simulated logs whose top-level keys match the vendor&apos;s
 native shape (FortiGate&apos;s{" "}
 <Code>srcip</Code> / <Code>dstport</Code> / <Code>sentbyte</Code>,
 Okta&apos;s <Code>eventType</Code> / <Code>actor.alternateId</Code>,
 CrowdStrike&apos;s <Code>event_simpleName</Code> /{" "}
 <Code>ComputerName</Code>, AWS CloudTrail&apos;s{" "}
 <Code>eventName</Code> / <Code>userIdentity</Code>, etc.).
 </p>
 <p>
 Because the records carry the vendor&apos;s real field names,
 any downstream system that already understands that vendor
 parses them cleanly — the vendor&apos;s own SIEM connector, a
 Splunk technology add-on, a Sentinel parser, an Elastic
 ingest pipeline, a custom Logstash filter, or any other
 platform&apos;s vendor-specific modeling rule. Phantom is
 destination-neutral; the data sources marketplace produces
 wire-faithful events, and the receiving system decides how
 to parse them.
 </p>
 <p>
 The bundled schemas are sourced from publicly-available
 vendor and platform catalogues — at build time the extractor
 reads any source that exposes canonical per-vendor field
 shapes. Today the build pipeline reads Cortex content packs;
 future iterations can layer Splunk mapping catalogues and
 other vendor-doc sources to widen coverage. The discovery
 source is a <em>build-time</em> concern, not a runtime
 dependency: once extracted, the bundled catalogue ships as
 plain YAML and the receiving platform at parse time is
 whatever the operator chose. Operators can also upload their
 own YAML to cover internal apps or vendors not in the bundle.
 </p>
 <p>
 The contract below covers the catalog source, storage, REST
 surface, MCP tool surface, and the skill chain that ties
 everything together.
 </p>

 <SubSection icon="storefront" title="Two marketplaces, two storage homes">
 <p>
 Phantom ships two distinct marketplaces. Both live under the
 catalog side of the{" "}
 <Link href="#authentication" className="link">
 catalog/credential boundary
 </Link>
 ; the agent can read + install + uninstall in both via
 narrow tools but never touches secrets.
 </p>
 <Pre>{`/connectors → Marketplace tab
  └── Connector marketplace (see §Marketplace Logic)
       state: marketplace.db (which connectors are installed)
       atom:  connector + its instance containers + its tools

/data-sources
  └── Data Sources marketplace (this section)
       state: data_sources.db (which vendor schemas are installed)
       atom:  vendor + product + field inventory (with examples
              for composite fields)`}</Pre>
 <p className="text-sm text-on-surface-variant">
 The two are decoupled by design. Installing a connector
 doesn&apos;t install its data sources, and installing a data
 source doesn&apos;t spin up a connector. Both can be exercised
 independently.
 </p>
 </SubSection>

 <SubSection icon="storage" title="Storage — data_sources.db (2 tables, FK cascade)">
 <p>
 Install state lives in a single SQLite store, owned by the MCP.
 Decoupled from <Code>marketplace.db</Code>. The table holds only
 data source–specific information (vendor truth + field
 inventory). Integration-specific metadata (e.g. Cortex pack /
 rule / dataset names, XDM mappings) lives as build-time
 provenance in the bundled YAMLs, NOT in the install store.
 </p>
 <Pre>{`data_sources.db  (DATA_ROOT/ — SQLite, sole source of truth)
├── data_sources (
│     id              TEXT PRIMARY KEY,    -- <vendor>_<product>
│     vendor          TEXT NOT NULL,
│     product         TEXT NOT NULL,
│     description     TEXT,
│     field_count     INTEGER NOT NULL,
│     non_meta_field_count INTEGER NOT NULL,
│     is_rawlog_only  INTEGER NOT NULL,
│     is_pinned       INTEGER NOT NULL DEFAULT 0,
│     pinned_version  TEXT,
│     source_revision TEXT,
│     installed_at    TEXT NOT NULL,
│     installed_by    TEXT NOT NULL,
│     logo_url        TEXT,
│     logo_type       TEXT
│   )
└── data_source_fields (
      data_source_id  TEXT NOT NULL REFERENCES data_sources(id)
                      ON DELETE CASCADE,
      name            TEXT NOT NULL,
      type_hint       TEXT,
      is_meta         INTEGER NOT NULL,
      description     TEXT,
      example         TEXT,                -- composite field shape
      observable_overrides JSON,
      PRIMARY KEY (data_source_id, name)
    )`}</Pre>
 <p className="text-sm">
 <strong>Two tables, ON DELETE CASCADE</strong>. A single{" "}
 <Code>DELETE FROM data_sources WHERE id=…</Code> drops the
 vendor row and all its field rows in one transaction. No
 orphans.
 </p>
 <p className="text-sm">
 <strong>The <Code>example</Code> column</strong> on{" "}
 <Code>data_source_fields</Code> carries a small concrete
 sample for fields whose wire shape is composite — JSON
 dicts, arrays, nested objects. Without an example, the
 generator can&apos;t produce records that match what
 downstream parsers expect for that field. Simple scalar
 fields leave it NULL.
 </p>
 <p className="text-sm">
 <strong>The <Code>id</Code> composition</strong> is{" "}
 <Code>{`<vendor>_<product>`}</Code> (lowercased, non-
 alphanumeric chars → <Code>_</Code>). Matches the dataset-
 naming convention downstream parsers use — see{" "}
 <Code>vendor_product_raw</Code> in the{" "}
 <Link href="#xsiam-dataset-routing" className="link">
 XSIAM dataset routing
 </Link>{" "}
 subsection below. An operator who asks the agent
 &quot;what dataset for vendor X product Y?&quot; gets the
 answer derived directly from the data source <Code>id</Code>.
 </p>
 <div className="rounded-lg border border-tertiary/30 bg-tertiary/5 p-3 mt-3 text-sm">
 <strong className="text-tertiary">Implementation gap</strong>{" "}
 — the running code still carries the legacy columns{" "}
 <Code>pack_name</Code> / <Code>rule_name</Code> /{" "}
 <Code>dataset_name</Code> / <Code>pack_version</Code> /{" "}
 <Code>supported_modules</Code> on{" "}
 <Code>data_sources</Code>, the{" "}
 <Code>pack_description</Code> name (not yet renamed to{" "}
 <Code>description</Code>), an <Code>id</Code> composition
 of <Code>{`<pack>_<rule>_<dataset>`}</Code>, and an
 entire <Code>data_source_xdm_mappings</Code> table.
 The new <Code>example</Code> column on{" "}
 <Code>data_source_fields</Code> is also pending. These
 cleanups land in a follow-on sub-release once the YAML
 re-extraction + migration script are wired through.
 </div>
 </SubSection>

 <SubSection icon="sync" title="Install is a snapshot — refreshed from the bundle at boot">
 <p>
 Installing a source copies its schema into{" "}
 <Code>data_sources.db</Code>, and{" "}
 <Code>data_sources_get_schema</Code> serves installed sources
 from those rows, not from the YAML. The volume survives image
 upgrades, so without the boot refresh a corrected bundled{" "}
 <Code>data_source.yaml</Code> would never reach an install that
 already had the source.
 </p>
 <p>
 <strong>The invariant.</strong> An installed
 source&apos;s stored schema equals its <em>effective</em> catalog
 YAML — the bundled <Code>data_source.yaml</Code> overlaid with any
 operator edit (the version store&apos;s current version) — unless
 the source is pinned. Two paths enforce it: an edit or rollback
 syncs the installed rows at the moment it happens, and a boot pass
 reconciles anything that drifted (for example a bundle change from
 an upgrade).
 </p>
 <p>
 <strong>Boot pass.</strong> After the store, the field backfill
 and the version store are wired,{" "}
 <Code>refresh_installed_from_bundle()</Code>{" "}
 (<Code>api/data_sources.py</Code>) walks every installed source
 that has a bundled YAML. The YAML loader&apos;s{" "}
 <Code>list_all()</Code> is overlay-aware, so an edited source
 already presents its edited effective YAML. It composes the rows{" "}
 <Code>data_sources_install</Code> would write, through the same{" "}
 <Code>_compose_from_user_yaml</Code>, and compares them with the
 stored rows field by field (type, is_array, is_meta, is_gate,
 enum_values, description, example). When they differ:
 </p>
 <Pre>{`pinned (is_pinned = 1)  → skipped, reported (a pin is an explicit "stay put";
                          automatic sync leaves it alone — an explicit edit
                          still outranks the pin)
otherwise              → store.replace_schema(ds, fields)
                          field rows swapped in one transaction; installed_at,
                          installed_by, is_pinned, pinned_version, source_revision
                          kept — a sync is not a reinstall`}</Pre>
 <p className="text-sm">
 <strong>Edit-time sync.</strong>{" "}
 <Code>_resync_installed_schema(ds_id)</Code> runs at the end of{" "}
 <Code>_apply_edit</Code> and <Code>_apply_rollback</Code>: if the
 source is installed it re-composes from the now-current effective
 YAML and replaces the rows, so{" "}
 <Code>data_sources_get_schema</Code> (and the agent&apos;s
 simulation) reflects the edit immediately. It returns{" "}
 <Code>installed_schema_synced</Code> in the edit/rollback result.
 </p>
 <p className="text-sm">
 Cortex-extracted and operator-uploaded sources have no bundled
 YAML and are not touched. The pass is idempotent: once rows match,
 later boots count the source as unchanged. A failure on one source
 is logged and reported, and the rest still sync.
 </p>
 <p className="text-sm">
 <strong>Observability.</strong> One log line per synced source
 (<Code>+added / -removed fields, N changed</Code>), a warning per
 pinned skip, and one audit event,{" "}
 <Code>data_sources_refreshed</Code> (actor <Code>system</Code>,
 trigger <Code>boot</Code>, metadata{" "}
 <Code>{`{refreshed, skipped_pinned, failed, unchanged}`}</Code>),
 recorded only when something was synced, skipped or failed. It
 appears in <Code>/observability/events</Code> under the{" "}
 <em>Data source refreshes</em> chip.
 </p>
 <div className="rounded-lg border border-tertiary/30 bg-tertiary/5 p-3 mt-3 text-sm">
 <strong className="text-tertiary">Known limitation</strong>{" "}
 — an edit&apos;s v1 &quot;bundle-baseline&quot; snapshot is frozen
 at first edit (see Versioning overlay below), so an edited source
 does not track later bundle changes: its effective YAML stays
 edit-over-old-bundle. To pick up a newer bundle for an edited
 source, roll back to the baseline first, then re-apply the edit.
 </div>
 </SubSection>

 <SubSection icon="folder_zip" title="Catalog source — per-source YAML, bundle + user">
 <p>
 The marketplace catalog is driven by per-source YAML files
 split across two storage roots:
 </p>
 <Pre>{`/app/bundle/data-sources/                  (image-baked, read-only)
  data_source.schema.json                  -- JSON Schema draft 2020-12, v1
  <vendor>__<product>/
    data_source.yaml

/app/data/user_data_sources/               (operator-uploaded, writable,
                                             persists via phantom_mcp_data volume)
  <operator-chosen-id>/
    data_source.yaml`}</Pre>
 <p>
 The bundled root ships in the agent image — one YAML per
 vendor-product pair, refreshed when Phantom releases. The
 user root is a writable mount; operators populate it via the
 upload flow.
 </p>
 <p>
 Each YAML carries identity (vendor + product), display
 fields (description, categories), inline base64 logo,
 formats[], and field declarations (name + type + description +
 optional example for composite fields). The 26-type field
 vocabulary covers <Code>string_short</Code> /{" "}
 <Code>string_long</Code> / <Code>ipv4</Code> /{" "}
 <Code>ipv6</Code> / <Code>enum</Code>{" "}
 (requires <Code>enum_values</Code>) /{" "}
 <Code>regex</Code> (requires <Code>regex_pattern</Code>) /{" "}
 <Code>json</Code> / etc. Unknown types fall back to xlog&apos;s
 name-pattern matching.
 </p>
 <p>
 The bundled YAMLs also carry a <Code>source_provenance:</Code>{" "}
 block documenting where each pack came from at build time
 (e.g. a Cortex content pack name + rule + dataset tuple, or
 a Splunk add-on identifier in future iterations). The
 provenance block is build-time forensic info — useful for
 tracing back to the upstream source when fields need
 refreshing — and is intentionally NOT persisted into{" "}
 <Code>data_sources.db</Code>. The install store sees only
 vendor + product + field inventory.
 </p>
 <p>
 An optional <Code>how_to_use:</Code> field carries{" "}
 <em>operator-facing simulation guidance</em> as multi-line
 markdown. Multi-dataset packs (Okta&apos;s{" "}
 <Code>okta_okta_raw</Code> + <Code>okta_sso_raw</Code>,
 Office365&apos;s five workload variants, PANW NGFW&apos;s six
 log_type splits) carry sibling-dataset notes; nested-JSON
 vendors call out the CEF-wrap pattern (pack composites as
 JSON-string CEF extensions; the MR&apos;s{" "}
 <Code>json_extract_scalar</Code> parses at query time); every
 entry names the single-event XDM ceiling so the operator can
 plan single-event vs split-event saturation. The drawer
 surfaces this as a collapsible &quot;How to simulate&quot;
 section per pack — empty for packs not yet validated; rich
 for the vendors smoked end-to-end.
 </p>
 <p className="text-sm">
 <strong>Loader contract</strong>:{" "}
 <Code>DataSourcesYamlLoader</Code> in{" "}
 <Code>bundles/spark/mcp/src/usecase/data_sources_yaml_loader.py</Code>{" "}
 reads from both roots on every catalog request (re-read, not
 cached) so operator uploads land without container restart.
 Bundle always wins on id collision — operators cannot
 override bundled packs; their custom sources must use new ids.
 </p>
 <p className="text-sm">
 <strong>vendor_map.yaml</strong> at the bundle root remains
 the per-vendor metadata source (display_name, primary_color)
 for the marketplace gradient — vendor-level metadata is
 intentionally separated from per-source YAML metadata.
 </p>
 <div className="rounded-lg border border-tertiary/30 bg-tertiary/5 p-3 mt-3 text-sm">
 <strong className="text-tertiary">Implementation gap</strong>{" "}
 — bundled YAMLs today are still organized under{" "}
 <Code>{`<pack>__<rule>__<dataset>/`}</Code> directories and
 carry their pack/rule/dataset tuple as top-level identity.
 Re-extraction into the new <Code>{`<vendor>__<product>/`}</Code>{" "}
 layout with the <Code>source_provenance:</Code> block is
 wired in the follow-on schema-migration sub-release.
 </div>
 </SubSection>

 <SubSection icon="http" title="HTTP delivery variants">
 <p>
 A bundled data source can declare <Code>delivery: http</Code>{" "}
 (optional key in <Code>data_source.schema.json</Code>, enum{" "}
 <Code>syslog | http</Code>, default <Code>syslog</Code>). Such a
 source is sent as JSON through the <Code>http-sender</Code>
 connector to an XSIAM HTTP Log Collector, not as CEF through{" "}
 <Code>phantom_create_data_worker</Code>. Three exist, each beside
 its unchanged syslog sibling:{" "}
 <Code>Okta__OktaHttpCollector__okta_sso_raw</Code>,{" "}
 <Code>ProofpointTAP__ProofpointTAPHttpCollector__proofpoint_tap_raw</Code>{" "}
 and{" "}
 <Code>GoogleDrive__GoogleDriveHttpCollector__google_workspace_drive_raw</Code>.
 The catalog row, the schema payload and{" "}
 <Code>data_sources_installed_as_vendors</Code> expose{" "}
 <Code>delivery</Code>; the Data Sources page renders an
 &ldquo;HTTP&rdquo; pill from it.
 </p>
 <p className="text-sm mt-2">
 <strong>The wires.</strong>
 </p>
 <ul className="list-disc pl-6 space-y-1 text-sm">
 <li>
 <strong>Routing.</strong> The agent reads <Code>delivery</Code>{" "}
 from the schema and, for <Code>http</Code>, uses{" "}
 <Code>http-sender.list_destinations</Code>,{" "}
 <Code>send_test_event</Code>, <Code>generate_events</Code>{" "}
 (profiles <Code>okta</Code>, <Code>proofpoint_tap</Code>,{" "}
 <Code>google_workspace</Code>) or <Code>send_events</Code>{" "}
 (custom JSON). The rule is in the agent system prompt; the
 syslog/CEF worker is not used for these sources.
 </li>
 <li>
 <strong>Agent to connector.</strong> The agent invokes the{" "}
 <Code>http-sender.&lt;tool&gt;</Code> tools through the embedded
 MCP, which proxies them to the per-instance <Code>http-sender</Code>{" "}
 connector container exactly as for any uploaded connector (see{" "}
 <Code>#connector-containers</Code>).
 </li>
 <li>
 <strong>Connector to tenant.</strong> The connector POSTs the
 JSON events over HTTPS to the tenant&apos;s{" "}
 <Code>/logs/v1/event</Code> with the collector key. One collector
 is one destination, and Phantom allows a single active instance
 per connector, so an instance holds its primary destination plus
 any more as additional destinations.
 </li>
 <li>
 <strong>Dataset.</strong> The collector, configured in XSIAM and
 not in the sender, fixes vendor and product and so the dataset.
 The parsing and modeling rules bound to that dataset then apply
 to the JSON as they would to any other arrival path.
 </li>
 <li>
 <strong>Auth.</strong> The collector key is entered by the
 operator when creating the instance and lives in that
 instance&apos;s SecretStore. It is never returned by a tool,
 never logged, never accepted as a tool argument, and never
 visible to the agent (credential guardrail).
 </li>
 </ul>
 <p className="text-sm mt-2">
 <strong>Failure modes.</strong>
 </p>
 <ul className="list-disc pl-6 space-y-1 text-sm">
 <li>
 <strong>HTTP 429</strong> — the collector rate-limits; send
 fewer events per call or space the calls out.
 </li>
 <li>
 <strong>Ingestion lag</strong> — measured at 5 to 7 minutes
 between a successful send and the rows being queryable, so an
 empty dataset immediately after a send is not a failure.
 </li>
 <li>
 <strong>Unmodeled dataset</strong> — events land raw but{" "}
 <Code>xdm.*</Code> stays empty when no rule binds to the
 collector&apos;s dataset. Measured: a collector with vendor
 Google and product Workspace writes{" "}
 <Code>google_workspace_raw</Code>, which no Cortex rule binds
 to (datamodel 0 rows). The Google HTTP source targets{" "}
 <Code>google_workspace_drive_raw</Code> and is expected to
 model only through a collector with vendor{" "}
 <Code>google_workspace</Code> and product <Code>drive</Code>;
 that path is not yet verified.
 </li>
 <li>
 <strong>No Analytics alert from the syslog sibling</strong> —
 expected, not a failure: the same event alerts over HTTP and
 not over syslog/CEF. Check the mapping with{" "}
 <Code>datamodel</Code> and use the HTTP sibling for alerts.
 </li>
 </ul>
 <p className="text-sm mt-2">
 <strong>Identity.</strong> An HTTP variant reuses its
 sibling&apos;s <Code>pack_name</Code>, <Code>vendor</Code> and{" "}
 <Code>dataset_name</Code>, and differs in{" "}
 <Code>rule_name</Code> (<Code>*HttpCollector</Code>) and the
 product label (<Code>&lt;X&gt; HTTP</Code>). The runtime
 identity is the pack / rule / dataset tuple, so the two siblings
 install and are edited independently. The product label is a
 display label only; it is not a wire value.
 </p>
 <p className="text-sm mt-2">
 This is the sanctioned exception to the syslog/CEF-only delivery
 doctrine (root <Code>CLAUDE.md</Code>, rule 1): HTTP sources are
 for HTTP simulation, are never API pollers, and never replace
 syslog/CEF for validating or promoting a mapping. The admission
 rule still applies: each has a real parsing and modeling path.
 </p>
 <p className="text-sm mt-2">
 <strong>Which sibling for which goal.</strong> The two
 siblings land in the same dataset and model identically, but
 Cortex Analytics has only been seen to fire on the
 HTTP-collected copy. Measured for Okta: one FastPass
 event with identical columns and <Code>xdm.*</Code> fields
 alerted over the HTTP collector in about 20 seconds and raised
 nothing in 11-15 minutes over CEF. The cause is not established
 (the collector-type stamp and a registered data-source stream
 both fit). So the syslog sibling is for checking parsing and
 modeling, and its <Code>how_to_use</Code> opens with that note;
 the agent system prompt tells the agent to choose the HTTP
 sibling when the operator wants Analytics alerts. Proofpoint TAP
 and Google Drive carry the same note and have not been tested
 separately. Cortex collects all three with its own API
 collectors, not an HTTP collector; for Okta and Proofpoint TAP the
 strongest route is the Cribl path below.
 </p>
 </SubSection>

 <SubSection icon="http" title="Cribl path (dedicated-UUID native feeds)">
 <p>
 The <Code>http-sender</Code> connector has a third way to deliver
 JSON: the tenant&apos;s Cribl
 integration endpoint. A request that carries a source&apos;s
 dedicated <Code>Source-Identifier</Code> UUID is treated by
 Cortex as that vendor&apos;s own feed: the rows get the
 vendor&apos;s native collector type, parsing, per-event stories
 and the normalized <Code>saas_audit_logs</Code> /{" "}
 <Code>cloud_audit_logs</Code> rows, and the out-of-the-box
 Analytics detectors can fire. Neither the generic HTTP collector
 nor syslog/CEF gives that identity. On a test tenant this route
 raised Analytics alerts from 25 distinct detectors
 (Okta, AWS, GCP and Azure AD audit), none of which fire over
 syslog/CEF. Cortex itself collects Okta, Proofpoint TAP and
 Google Workspace with its own API collectors, not an HTTP
 collector; the Cribl UUID is the documented way to reproduce
 their native feed.
 </p>
 <p className="text-sm mt-2">
 <strong>The wires.</strong>
 </p>
 <ul className="list-disc pl-6 space-y-1 text-sm">
 <li>
 <strong>Agent to connector.</strong> Unchanged: the agent calls{" "}
 <Code>http-sender.&lt;tool&gt;</Code> through the embedded MCP,
 which proxies to the per-instance container. A destination named{" "}
 <Code>cribl_&lt;source&gt;</Code> selects the Cribl path
 (sources: <Code>okta_sso</Code>, <Code>aws_audit</Code>,{" "}
 <Code>gcp_cloud_logging</Code>, <Code>azure_ad_audit</Code>,{" "}
 <Code>azure_ad_signins</Code>, <Code>azure_event_hub</Code>,{" "}
 <Code>windows_events</Code>, <Code>proofpoint_tap</Code>). They
 exist automatically when the instance has both{" "}
 <Code>criblUrl</Code> and the <Code>criblToken</Code> secret;{" "}
 <Code>list_destinations</Code> reports a problem when only one
 is set.
 </li>
 <li>
 <strong>Connector to tenant.</strong> One HTTPS POST per 300
 events to the <Code>criblUrl</Code> (the tenant&apos;s{" "}
 <Code>/logs/v1/integrated/cribl/data</Code>), body NDJSON with{" "}
 <Code>every line wrapped as {`{"data": <event>}`}</Code> (an
 unwrapped line lands as <Code>_raw_log</Code> only), headers{" "}
 <Code>Authorization</Code> (the raw token, no Bearer),{" "}
 <Code>Source-Identifier</Code>, <Code>Format: json</Code>,{" "}
 <Code>Integration-Identifier</Code> (config{" "}
 <Code>criblIntegration</Code>, default{" "}
 <Code>phantom-http-sender</Code>, shows as{" "}
 <Code>_collector_name</Code>) and <Code>Content-Type</Code>. The
 reply is <Code>{`{"num_records": N, "success": "true"}`}</Code>; a
 count mismatch counts as a failure. Synchronous, 15 s default
 timeout, no retry.
 </li>
 <li>
 <strong>Auth.</strong> The tenant has one Cribl collector; its
 token is entered by the operator in the instance form and lives
 in the <Code>criblToken</Code> secret slot. It is never
 returned, logged or accepted as a tool argument, and is scrubbed
 from every error string (credential guardrail).
 </li>
 <li>
 <strong>Profiles.</strong> <Code>aws_cloudtrail</Code>,{" "}
 <Code>gcp_audit</Code> and <Code>azure_ad_audit</Code>, and{" "}
 <Code>tor_signin</Code> and <Code>fastpass_phishing</Code> on{" "}
 <Code>okta</Code>, build the events that fired the detectors,
 with fresh identities on every call so each run looks like a
 first-time actor.
 </li>
 <li>
 <strong>Windows.</strong> <Code>send_events</Code> to{" "}
 <Code>cribl_windows_events</Code> takes the same structured
 events as <Code>wec-sender.send_events</Code>, renders each to
 Windows Event XML with a copy of the wec-sender renderer and
 posts it as a plain string (an object wrapper returns 200 and
 lands nothing). The rows reach{" "}
 <Code>microsoft_windows_raw</Code> with the same columns and{" "}
 <Code>xdm.*</Code> fields as WEC rows
 (<Code>_transport = cribl</Code>, no <Code>_collector_type</Code>)
 and fire the same Windows identity detectors, with no Broker,
 certificate or WEC subscription. AD FS keeps{" "}
 <Code>wec-sender</Code>: its parsing rule requires the WEC
 collector type.
 </li>
 </ul>
 <p className="text-sm mt-2">
 <strong>Failure modes.</strong> HTTP 400 names the missing header.
 Rows stay without <Code>xdm.*</Code> until the vendor&apos;s
 content pack is installed on the tenant. Stale Tor exits fail
 silently (the detector does not fire; pass a current exit as{" "}
 <Code>source_ip</Code>). Ingestion and alert latency was 3
 seconds to about 7 minutes (most under 20 seconds).
 </p>
 <p className="text-sm mt-2">
 This is the third sanctioned use of non-syslog delivery (after
 the HTTP collector and WEC), with the same limits: it never
 replaces syslog/CEF when validating or promoting a data
 source&apos;s mapping, it carries no validation tier, and it is
 never an API poller.
 </p>
 </SubSection>

 <SubSection icon="http" title="WEC delivery (wec-sender)">
 <p>
 The <Code>wec-sender</Code> connector forwards synthetic
 Windows events to the Windows Event Collector applet on the
 Cortex Broker VM over WS-Management (source-initiated
 forwarding), so they ingest with{" "}
 <Code>_collector_type = &quot;WEC&quot;</Code> into{" "}
 <Code>microsoft_windows_raw</Code> (or{" "}
 <Code>microsoft_adfs_raw</Code> for AD FS). This is the second
 sanctioned exception to the syslog/CEF-only delivery doctrine
 (root <Code>CLAUDE.md</Code>): it exists
 for feeds a CEF source cannot produce (host and sign-in
 entities, AD FS through its own parsing rule) and never
 replaces syslog/CEF for validating or promoting a mapping.
 </p>
 <p className="text-sm mt-2">
 <strong>The wires.</strong>
 </p>
 <ul className="list-disc pl-6 space-y-1 text-sm">
 <li>
 <strong>Agent to connector.</strong> The agent invokes the{" "}
 <Code>wec-sender.&lt;tool&gt;</Code> tools (
 <Code>list_subscriptions</Code>, <Code>send_test_event</Code>,{" "}
 <Code>generate_events</Code>, <Code>send_events</Code>) through
 the embedded MCP, which proxies them to the per-instance
 connector container exactly as for any uploaded connector (see{" "}
 <Code>#connector-containers</Code>).
 </li>
 <li>
 <strong>Source and destination.</strong> Source: the{" "}
 <Code>wec-sender</Code> connector container on the engine.
 Destination: the Broker VM, TCP 5986, at the FQDN named in the
 instance&apos;s <Code>subscriptionManagerUrl</Code>. The engine
 must resolve that FQDN and a firewall rule must allow TCP 5986
 from the engine.
 </li>
 <li>
 <strong>Auth.</strong> Mutual TLS (TLS 1.2 or later) with the
 client certificate the Cortex console issues, supplied as a PFX.
 The server is verified against only the CA that issued the client
 certificate (trust is pinned to it; the system store is not
 used), and because the applet&apos;s certificate has a CN and no
 subjectAltName, the name is matched by hand right after the
 handshake and before any request is sent. Verification cannot be
 turned off.
 </li>
 <li>
 <strong>Protocol.</strong> Synchronous request and response over
 one HTTPS connection per request, SOAP 1.2 encoded as UTF-16: a
 WS-Enumeration request lists the subscriptions (done at the
 start of every tool call; each reply carries a fresh identifier),
 then an Events envelope per computer is POSTed to the chosen
 subscription. HTTP 200 with an empty body means the applet
 accepted the envelope.
 </li>
 <li>
 <strong>Secrets.</strong> The PFX and its password are the
 instance&apos;s secret slots in its SecretStore, created by the
 operator over REST. No tool returns, logs or accepts them, and
 the private key only ever touches tmpfs as an encrypted file for
 the instant it is loaded (credential guardrail).
 </li>
 </ul>
 <p className="text-sm mt-2">
 <strong>Failure modes.</strong>
 </p>
 <ul className="list-disc pl-6 space-y-1 text-sm">
 <li>
 <strong>Non-200 delivery</strong> — the subscriptions are
 enumerated again and that one envelope is retried once; a second
 failure ends the call with <Code>ok: false</Code> and a partial
 report of what was already accepted. Accepted envelopes are
 never resent.
 </li>
 <li>
 <strong>Nothing sent on a bad event</strong> — every batch is
 planned (sizes measured in real UTF-16 bytes against the
 subscription&apos;s <Code>MaxEnvelopeSize</Code>) before the
 first delivery, so an oversized or unsendable event fails the
 call with nothing delivered.
 </li>
 <li>
 <strong>TLS and certificate errors</strong> — a name mismatch, a
 foreign CA or a wrong IssuerCA stops the call before a request
 is sent and returns a clear <Code>ok: false</Code>.
 </li>
 <li>
 <strong>Accepted is not landed</strong> — <Code>sent</Code>{" "}
 counts events the applet accepted; landing is proven only by the
 XQL query each tool returns (about 10 seconds in measurement).
 </li>
 </ul>
 </SubSection>

 <SubSection icon="verified" title="Validation tiers — Mapping Validated vs Raw Validated">
 <p>
 Each bundled syslog/CEF data source can carry one of two
 mutually-exclusive validation marks, surfaced as a pill on the
 Browse card. HTTP-delivery variants (see{" "}
 <em>HTTP delivery variants</em> above) carry neither mark: both
 tiers describe the syslog/CEF path, and an HTTP variant is never
 promoted by them. The
 distinction reflects <em>how far we could prove the source on the
 live tenant</em> — both are real validations, but one is stronger
 than the other.
 </p>
 <ul className="list-disc pl-6 space-y-1 text-sm">
 <li>
 <strong className="text-secondary">Mapping Validated</strong>{" "}
 (green, YAML <Code>validated: true</Code>) — the source was
 verified end-to-end against the live XSIAM tenant and its{" "}
 <strong>modeling rule populates <Code>xdm.*</Code></strong>{" "}
 (or, when the vendor has no modeling rule, its parsing rule
 extracts the columns). The pack is installed, the rule is
 bound, and the synthetic event maps. This is the strong tier —
 the 40 sources confirmed via the simulate → XSIAM → XQL loop.
 </li>
 <li>
 <strong className="text-tertiary">Raw Validated</strong>{" "}
 (amber, YAML <Code>raw_validated: true</Code>) — the
 vendor&apos;s content pack is <strong>not installed</strong> on
 the tenant, so parsing/modeling cannot be exercised
 (<Code>datamodel</Code> returns 0). But a raw-dataset query —{" "}
 <Code>{`dataset = X | fields <rule columns> | limit 10`}</Code>{" "}
 — confirmed our synthetic data lands the <em>exact field names
 the rule would read</em>. Proven-correct shape, ready-to-map the
 moment the operator installs the pack. This validates content
 correctness independent of what&apos;s installed on the tenant.
 </li>
 </ul>
 <p className="text-sm mt-2">
 Raw validation only applies to <strong>named-column /
 JSON-composite</strong> rules, where the rule reads the columns
 our data lands. <Code>_raw_log</Code>-regex rules are excluded:
 their named columns can land yet the rule reads{" "}
 <Code>_raw_log</Code> content, so columns-present is not proof
 the rule would map. This follows the syslog/CEF-only doctrine —
 the broker, parsing rules, and modeling rules are
 protocol-agnostic and map on the data <em>shape</em>, so
 confirming the wire columns confirms the source regardless of
 how the real vendor is collected in production.
 </p>
 <p className="text-sm mt-2">
 <strong>Enforcement.</strong> Two canonical manifests under{" "}
 <Code>tooling/validate/</Code> —{" "}
 <Code>validated_data_sources.txt</Code> and{" "}
 <Code>raw_validated_data_sources.txt</Code> — MUST equal the set
 of YAMLs flagged with each mark.{" "}
 <Code>check_raw_validated_data_sources_manifest</Code> fails the
 build on drift OR on any source claiming both tiers, so neither
 pill ever ships unverified.
 </p>
 </SubSection>

 <SubSection icon="terminal" title="RAW wire format — sources whose rules read _raw_log">
 <p>
 88 bundled sources declare a <Code>_raw_log</Code> field because their
 Cortex rules extract from the vendor&apos;s own native log line rather
 than from parsed-out columns. A CEF event&apos;s extensions become
 dataset <em>columns</em> and the broker leaves <Code>_raw_log</Code>{" "}
 EMPTY — verified on a live tenant — so over CEF those rules map nothing
 no matter how the schema is shaped.
 </p>
 <p>
 For 75 of the 88 the dependency runs deeper than the modeling rule.
 Their <strong>parsing</strong> rule also reads <Code>_raw_log</Code> —
 Cisco ASA&apos;s opens with{" "}
 <Code>alter _json = parse_cisco(_raw_log)</Code> and builds every column
 from it. Over CEF the parsing rule receives nothing, extracts no
 columns, and the modeling rule&apos;s column-derived fields end up empty
 too. CEF does not cost these sources a few fields; it breaks the whole
 ingestion chain.
 </p>
 <p>
 xlog therefore carries a <Code>RAW</Code> wire format alongside{" "}
 <Code>SYSLOG</Code> / <Code>CEF</Code> / <Code>LEEF</Code> /{" "}
 <Code>JSON</Code>. It emits the record&apos;s <Code>_raw_log</Code>{" "}
 value as the syslog body, verbatim, and prepends the frame{" "}
 <Code>&lt;134&gt;Mon DD HH:MM:SS host &lt;body&gt;</Code>. Two contracts
 follow, both load-bearing:
 </p>
 <ul className="list-disc pl-6 space-y-1 text-sm">
 <li>
 <strong>The example is the body only.</strong> An example carrying its
 own <Code>&lt;14&gt;…</Code> priority gets double-framed. Rules
 anchored with <Code>^</Code> still see the frame, and some depend on
 it — Arista&apos;s regexes match <Code>&lt;\d+&gt;</Code> directly.
 </li>
 <li>
 <strong>Timestamps self-date.</strong> A frozen date stamps{" "}
 <Code>_time</Code> in the past, which presents exactly like
 &quot;nothing landed&quot;. Examples carry a{" "}
 <Code>{"{{now:<strftime>}}"}</Code> placeholder rendered at send time.
 </li>
 </ul>
 <p>
 <strong>Routing.</strong> A raw line has no CEF header, so the broker
 cannot derive vendor/product from the wire and the event lands in{" "}
 <Code>unknown_unknown_raw</Code>. Routing must come from a{" "}
 <strong>Broker syslog collector row</strong> mapping the listener port
 to a vendor/product pair — and that pair is the literal in the
 pack&apos;s parsing-rule <Code>[INGEST: …]</Code> block,{" "}
 <em>not</em> the schema&apos;s display <Code>vendor</Code>/
 <Code>product</Code> fields. All 75 sources with an INGEST block
 disagree with their display values:{" "}
 <Code>beyondtrust_pra_raw</Code> displays <Code>BeyondTrust</Code>/
 <Code>BeyondTrustPrivilegedRemoteAccess</Code> but routes as{" "}
 <Code>beyondtrust</Code>/<Code>pra</Code>. Each source&apos;s{" "}
 <Code>how_to_use</Code> therefore names its own pair explicitly.
 </p>
 <p className="text-sm mt-2">
 <strong>Implementation gap.</strong> The collector row is operator-side
 Broker configuration and does not yet exist on the reference install, so
 raw-format events currently land in <Code>unknown_unknown_raw</Code> and
 no <Code>_raw_log</Code> source is validated end-to-end yet. The wire
 format, framing, self-dating timestamps and per-source routing literals
 are all in place and verified independently of it.
 </p>
 <p className="text-sm mt-2">
 <strong>Implementation gap.</strong> 71 of the 88 still carry an
 auto-generated placeholder in their <Code>_raw_log</Code> example rather
 than a real vendor line. Those land but do not map until each is
 reverse-engineered from its own rule.
 </p>
 </SubSection>

 <SubSection icon="upload_file" title="Operator-uploaded sources — preview/commit flow">
 <p>
 Five REST endpoints let operators upload custom
 data_source.yaml files. The flow is two-phase to surface
 vendor-name conflicts BEFORE write:
 </p>
 <Pre>{`POST /api/v1/data-sources/user/preview
  body: { yaml: "<text>" }  OR  { doc: {...parsed...} }
  -> validates against data_source.schema.json
  -> runs Levenshtein-2 + substring similarity vs known vendors
  -> { ok, uploaded_vendor, similarity_matches[], bundle_collision, accept_token }

POST /api/v1/data-sources/user
  body: { yaml|doc, accept_token, vendor_choice }
  -> re-hashes the doc; verifies accept_token matches
  -> writes to /app/data/user_data_sources/<id>/data_source.yaml
  -> 201 { ok, id, data_source }

GET    /api/v1/data-sources/user           -- list operator-uploaded
GET    /api/v1/data-sources/user/{id}      -- single + full YAML doc
DELETE /api/v1/data-sources/user/{id}      -- cascade-uninstall from store
GET    /api/v1/data-sources/user/{id}/logo -- stream inline base64 logo`}</Pre>
 <p>
 <strong>Accept-token semantics</strong>: SHA-256 of the
 canonical JSON form of the YAML doc, bound preview→commit by
 byte-exact match. Not a security boundary (operator is
 already bearer-authenticated); a sanity check that the
 operator commits exactly what they previewed.
 </p>
 <p>
 <strong>Vendor-grouping flow</strong>: if similarity matches
 surface (e.g. uploaded vendor &quot;Forinet&quot; → suggested
 &quot;Fortinet&quot;), the UI prompts{" "}
 <Code>create_new</Code> (keep as-typed) or{" "}
 <Code>group_under</Code> (rewrite the YAML&apos;s{" "}
 <Code>vendor</Code> field). Rewrite happens CLIENT-side, then
 the dialog re-previews to obtain a fresh accept_token bound
 to the rewritten bytes. Server-side rewriting would
 invalidate the token check.
 </p>
 <p className="text-sm">
 <strong>Install path branching</strong>:{" "}
 <Code>data_sources_install</Code> (REST + MCP tool) resolves
 by vendor + product against the YAML loader, then lifts the
 field declarations directly from the YAML. Both bundle and
 user-upload paths share the same lift today — the YAML is
 the canonical schema source at install time.
 </p>
 <p className="text-sm">
 Per CLAUDE.md § Credential vs catalog boundary: user uploads
 are CATALOG operations. The upload endpoints are REST-only
 (no agent MCP tool registered) because uploading is an
 explicit operator action with a similarity-check prompt the
 agent shouldn&apos;t auto-confirm.
 </p>
 </SubSection>

 <SubSection icon="api" title="REST surface — /api/v1/data-sources/*">
 <p>
 The MCP exposes a vendor-keyed REST surface, all bearer-
 protected. Order matters: literal <Code>/install</Code> +
 literal <Code>/catalog</Code> + literal{" "}
 <Code>{`/logo/{vendor}`}</Code> are registered before the
 catch-all <Code>{`/{vendor}/{product}`}</Code> pair so they
 don&apos;t collide.
 </p>
 <Pre>{`-- Installed-state (data_sources.db, sqlite)
GET    /api/v1/data-sources                           -- list installed (?filter=)
POST   /api/v1/data-sources/install                   -- {vendor, product}
GET    /api/v1/data-sources/{vendor}/{product}        -- metadata only
GET    /api/v1/data-sources/{vendor}/{product}/schema -- full field inventory
DELETE /api/v1/data-sources/{vendor}/{product}        -- uninstall (CASCADE)

-- Marketplace browse (YAML loader)
GET    /api/v1/data-sources/catalog                   -- bundle + user joined
                                                       (?origin=bundle|user, ?include_rawlog=)

-- User uploads
POST   /api/v1/data-sources/user/preview              -- {yaml|doc}; validates + similarity
POST   /api/v1/data-sources/user                      -- commit with accept_token
PUT    /api/v1/data-sources/user/{id}                 -- edit in place (accept_token-gated)
GET    /api/v1/data-sources/user                      -- list operator-uploaded
GET    /api/v1/data-sources/user/{id}                 -- single + full YAML doc
DELETE /api/v1/data-sources/user/{id}                 -- cascade-uninstall from store
GET    /api/v1/data-sources/user/{id}/logo            -- stream inline base64 logo

-- Logo serving (bundled)
GET    /api/v1/data-sources/logo/{vendor}             -- SVG/PNG bytes, Cache-Control 1d`}</Pre>
 <div className="rounded-lg border border-tertiary/30 bg-tertiary/5 p-3 mt-3 text-sm">
 <strong className="text-tertiary">Implementation gap</strong>{" "}
 — the running routes still accept the legacy 3-tuple{" "}
 <Code>{`/{pack}/{rule}/{dataset}`}</Code> path shape and the{" "}
 <Code>install</Code> body still uses{" "}
 <Code>{`{pack_name, rule_name, dataset_name?}`}</Code>. The
 vendor + product surface lands when the schema migration
 sub-release ships; legacy routes get redirected to the new
 paths via a one-shot rewrite on first boot of the migrated
 image.
 </div>
 <p>
 The catalog endpoint loads from the{" "}
 <Code>DataSourcesYamlLoader</Code> (per-source YAMLs from
 bundle + user roots), overlays per-row{" "}
 <Code>installed: bool</Code> from <Code>data_sources.db</Code>,
 and enriches with <Code>vendor_primary_color</Code> from{" "}
 <Code>vendor_map.yaml</Code> for bundled rows.
 </p>
 <p className="text-sm">
 The Next.js side at <Code>mcp/agent/app/api/agent/data-sources/*</Code>{" "}
 forwards via <Link href="#rest-api" className="link"><Code>mcp-proxy</Code></Link>.
 Every route above has a thin proxy on the agent side; the
 agent always reaches the MCP through it.
 </p>
 </SubSection>

 <SubSection icon="smart_toy" title="MCP tool surface — agent-callable">
 <p>
 The agent has 3 data-sources tools — all on the CATALOG side
 of the boundary:
 </p>
 <ul className="list-disc pl-6 space-y-1 text-sm">
 <li><Code>data_sources_list(filter?)</Code> — read-only listing of installed schemas, optionally filtered by substring against vendor / product.</li>
 <li><Code>data_sources_get_schema(data_source_id)</Code> — full field inventory (name + type + description + example) for one installed data source. Returns the same shape as <Code>GET /api/v1/data-sources/{`{vendor}/{product}`}/schema</Code>.</li>
 <li><Code>data_sources_install(vendor, product)</Code> — idempotent install. Resolves the YAML by vendor + product key.</li>
 </ul>
 <p>
 The cortex-content connector also exposes 4 lower-level
 extraction tools (<Code>cortex_list_packs</Code>,{" "}
 <Code>cortex_extract_vendor_schema</Code>,{" "}
 <Code>cortex_extract_vendor_logo</Code>,{" "}
 <Code>cortex_extract_vendor_catalog</Code>) — these are
 build-time helpers used during YAML extraction and read
 directly from the baked tree without touching the install
 store. They are NOT part of the runtime install path; the
 install tool resolves by vendor + product against the
 already-extracted YAML.
 </p>
 <div className="rounded-lg border border-tertiary/30 bg-tertiary/5 p-3 mt-3 text-sm">
 <strong className="text-tertiary">Implementation gap</strong>{" "}
 — running tool signatures still accept the legacy 3-tuple
 (<Code>data_sources_install(pack_name, rule_name,
 dataset_name?)</Code>) and the response shape still includes
 XDM mappings. The vendor + product signatures + the new
 example field land in the follow-on MCP-tools sub-release.
 </div>
 <p className="text-sm">
 None of these tools touch a SecretStore value. There is no
 uninstall MCP tool today — uninstall happens via the UI&apos;s
 confirmation modal, deliberately operator-gated since dropping
 a schema can break in-flight simulation skills that reference it.
 </p>
 </SubSection>

 <SubSection icon="account_tree" title="Skill chain — simulate_vendor_logs">
 <p>
 The capability arc closes via a workflow skill:
 </p>
 <Pre>{`Operator: "simulate 50 FortiGate traffic logs"
            ↓
Agent:    matches simulate_vendor_logs skill (vendor-named request)
            ↓
Step 1:   data_sources_list(filter="fortigate")
          → finds FortiGate/FortiGate_1_3/fortinet_fortigate_raw
            ↓
Step 2:   data_sources_get_schema(data_source_id)
          → 176 fields (172 non-meta) with observable_overrides + XDM mappings
            ↓
Step 3:   phantom_generate_fake_data_v2(
            request_input={records=50, type="json", ...},
            schema_override={field_names_and_types from step 2}
          )
            ↓
xlog:     generate_fake_data_v2 GraphQL resolver
            ↓
xlog:     dynamic_schema.py value generator
          - observable_overrides → vendor-faithful IP/port/hash/etc.
          - type_hint → typed faker (int/bool/timestamp/etc.)
          - field-name pattern → heuristic (e.g. srcip→IPv4, sentbyte→int)
          - fallback to Rosetta synthesis if all else fails
            ↓
Records:  3 sample records with srcip/dstip/srcport/dstport/proto/action/...
          schemaApplied: true, vendorFieldCount: 11, fallbackReason: null`}</Pre>
 <p className="text-sm">
 If no installed data source matches the operator&apos;s vendor,
 the skill instructs the agent to STOP + tell the operator to
 install via <Code>/data-sources</Code> first — it does NOT
 auto-install. Install is operator-gated by skill discipline,
 not by tool guardrail (the agent CAN call{" "}
 <Code>data_sources_install</Code> if the operator says
 &ldquo;yes, install it&rdquo;).
 </p>
 </SubSection>

 <SubSection icon="bolt" title="xlog dynamic schema engine">
 <p>
 xlog ships two GraphQL fields for fake-data synthesis:
 </p>
 <ul className="list-disc pl-6 space-y-1 text-sm">
 <li><Code>generateFakeData(requestInput)</Code> — legacy path. Uses Rosetta&apos;s built-in field universe (generic Phantom-branded shape).</li>
 <li><Code>generateFakeDataV2(requestInput, schemaOverride?)</Code> — vendor-aware path. When <Code>schemaOverride</Code> is supplied, top-level keys + value generation come from the override. When omitted, falls back to identical Rosetta behavior — strict backward-compat.</li>
 </ul>
 <p>
 The override engine lives at <Code>xlog/app/dynamic_schema.py</Code>.
 Each field&apos;s value is resolved in priority order:{" "}
 <strong>(1)</strong> <Code>observable_overrides</Code> if present
 (vendor-faithful: real IP ranges, real action enums),{" "}
 <strong>(2)</strong> <Code>type_hint</Code> via typed faker,{" "}
 <strong>(3)</strong> field-name pattern (e.g. <Code>srcip</Code>{" "}
 → IPv4, <Code>sentbyte</Code> → byte-count integer),{" "}
 <strong>(4)</strong> Rosetta fallback. The resolver returns{" "}
 <Code>schemaApplied</Code> + <Code>vendorFieldCount</Code> + an
 optional <Code>fallbackReason</Code> in the response envelope
 so the agent can detect partial overrides.
 </p>
 </SubSection>

 <SubSection icon="construction" title="Implementation references">
 <ul className="list-disc pl-6 space-y-1 text-sm">
 <li><strong>Store</strong>: <Code>bundles/spark/mcp/src/usecase/data_sources_store.py</Code> — SQLite, install/uninstall/get/list/get_with_schema, FK cascade.</li>
 <li><strong>REST routes</strong>: <Code>bundles/spark/mcp/src/api/data_sources.py</Code> — 7 custom routes + 3 agent-callable functions + the extract/compose helper.</li>
 <li><strong>Catalog client</strong>: <Code>bundles/spark/connectors/cortex-content/src/_baked_client.py</Code> — local-filesystem reader, path-traversal guarded.</li>
 <li><strong>Cortex-content connector</strong>: <Code>bundles/spark/connectors/cortex-content/src/connector.py</Code> — 4 extract tools that operate on the baked tree.</li>
 <li><strong>Baked catalog</strong>: <Code>bundles/spark/connectors/cortex-content/baked/</Code> — 576 files / 2.9 MB / <Code>_manifest.json</Code> sentinel.</li>
 <li><strong>Refresh script</strong>: <Code>scripts/refresh_cortex_baked_catalog.py</Code> — maintainer-only, not invoked at runtime.</li>
 <li><strong>xlog dynamic schema</strong>: <Code>xlog/app/dynamic_schema.py</Code> + <Code>xlog/app/schema.py</Code> (<Code>generateFakeDataV2</Code> resolver).</li>
 <li><strong>xlog MCP tool</strong>: <Code>bundles/spark/connectors/xlog/src/data_faker.py</Code> — <Code>phantom_generate_fake_data_v2</Code>.</li>
 <li><strong>Skill</strong>: <Code>bundles/spark/mcp/skills/workflows/simulate_vendor_logs.md</Code>.</li>
 <li><strong>UI page</strong>: <Code>mcp/agent/app/data-sources/page.tsx</Code> — Browse + Installed tabs, drill-down drawer, ruby-red uninstall modal.</li>
 <li><strong>Next.js proxies</strong>: <Code>mcp/agent/app/api/agent/data-sources/*</Code> — thin forwards to MCP.</li>
 </ul>
 </SubSection>

 <SubSection icon="local_offer" title="Use-case taxonomy — vendor cards + filter dropdown">
 <p>
 Each <Code>data_source.yaml</Code> carries a curated{" "}
 <Code>use_cases</Code> field — short product-type labels
 meaningful to a SOC operator (F5 → <em>WAF</em>,{" "}
 <em>LoadBalancer</em>; Okta → <em>Identity</em>,{" "}
 <em>MFA</em>; CyberArk → <em>PAM</em>). The canonical taxonomy
 enumerates 44 labels across 8 domains:
 </p>
 <Pre>{`Network   : Network · Firewall · WAF · LoadBalancer · SDWAN · VPN
            · Proxy · DNS · IDS · DDoS
Endpoint  : EDR · AV · Endpoint · Forensics
Identity  : Identity · MFA · PAM · AD · CIAM
Data      : Email · DLP · CASB
Cloud     : Cloud · SaaS · Container · Virtualization · CSPM
Apps      : Database · Storage · Collab · DevOps · WebServer · AppServer
SecOps    : SIEM · SOAR · XDR · ThreatIntel · Vuln · ASM · CTEM
Specialty : OS · Honeypot · ICS · PhysSec · Voice · Analytics · Other`}</Pre>
 <p>
 One data source can belong to multiple use cases (Cisco is
 both <em>Firewall</em> and <em>EDR</em>). <Code>use_cases</Code>{" "}
 drives both the vendor-card badges and the filter dropdown
 above the Browse grid. A separate <Code>categories</Code> field
 on each YAML records the Cortex XSIAM platform module the pack
 ships under and is preserved for backend metadata — operators
 don&apos;t see it.
 </p>
 </SubSection>

 <SubSection icon="filter_list" title="Filter dropdown — multi-select use cases">
 <p>
 Above the Browse grid is a single pill-shaped{" "}
 <Term>Use case</Term> trigger that opens a Material 3 multi-
 select dropdown panel. The dropdown lets the operator narrow
 the 137-vendor catalog to one or more product types at a time:
 </p>
 <Pre>{`Trigger button:
    ┌────────────────────────────────────────┐
    │ ⚲ Use case  [3]  ▾                     │
    └────────────────────────────────────────┘

  Inline removable pills next to the trigger (capped at 6 + overflow):
    [Firewall ×]  [EDR ×]  [WAF ×]   +5 more

  Click trigger → floating panel (rounded, soft shadow):
    ┌──────────────────────────────────────┐
    │ Filter by use case · 3 of 44 selected│  All  Clear
    │ ─────────────────────────────────────│
    │ ⚲ Filter use cases…                  │
    │ ─────────────────────────────────────│
    │ ☑ Firewall          (24)             │
    │ ☑ EDR               (18)             │
    │ ☑ WAF               (12)             │
    │ ☐ Identity          (15)             │
    │ ...                                   │
    │ ─────────────────────────────────────│
    │ Multiple selections = OR (any match) │
    └──────────────────────────────────────┘`}</Pre>
 <p className="text-sm text-on-surface-variant">
 Filter semantics: a vendor matches if ANY of its{" "}
 <Code>use_cases</Code> intersect with the selected set. Cisco
 tagged both Firewall and EDR shows under either selection.
 Selected items float to the top of the panel list so the
 active set stays easy to read and uncheck. Inline pills mirror
 the active selection so the operator can see + remove filters
 without re-opening the panel. Click-outside or Escape closes
 the panel.
 </p>
 </SubSection>

 <SubSection icon="image" title="Logo pipeline — one vendor logo per vendor">
 <p>
 Phantom serves vendor logos inline from each YAML&apos;s
 base64 <Code>logo:</Code> block. The catalog endpoint
 resolves a single <em>vendor</em> logo per vendor_key so every
 pack of the same vendor renders the same mark — every F5 pack
 carries the F5 logo, every FortiGate pack carries the
 Fortinet logo, regardless of which specific pack-rule-dataset
 row the UI is rendering.
 </p>
 <Pre>{`Logo resolution priority (per YAMLDataSource._compute_logo_url):

  1. YAML has inline 'logo:' → /api/agent/data-sources/inline-logo/<id>
                              served from the base64 blob in the YAML.
  2. Else (user origin)     → /api/agent/data-sources/user/<id>/logo
                              (legacy path; user uploads typically
                              carry inline logos via path 1.)
  3. Else                   → null. UI renders the inventory_2
                              placeholder icon via LogoOrFallback.

Catalog enrichment (api/data_sources.py):
  After all rows are built, scan once and pick the first sibling-per-
  vendor_key with a non-null logo_url. Set vendor_logo_url on every
  row. Frontend prefers vendor_logo_url ?? logo_url so every F5 pack
  renders the F5 mark, every FortiGate pack renders the Fortinet
  mark, etc.

Logo provenance is recorded in each YAML's 'logo:' block:
  source:   "wikipedia:File:Avaya_Logo.svg" / "simpleicons:fortinet"
            / "phantom-bundle" / "hand-crafted"
  license:  Wikimedia Commons / vendor trademark / CC0-1.0 / CC BY-SA
  fidelity: branded (vendor's actual artwork)
            | branded-recolored (white→navy for visibility)
            | monochrome-brand (simple-icons single-color mark)
            | approximation (maintainer-authored wordmark)`}</Pre>
 </SubSection>

 <SubSection icon="speed" title="Loader cache — mtime-keyed">
 <p>
 <Code>DataSourcesYamlLoader.list_all()</Code> caches its scan
 of both YAML roots keyed by directory <Code>st_mtime_ns</Code>{" "}
 + an O(1) <Code>id</Code>-index dict. Modifying an existing
 YAML&apos;s contents doesn&apos;t bump the parent
 directory&apos;s mtime (always cache-hit); adding or removing
 a YAML does bump mtime (automatic invalidation). The upload
 and delete endpoints also call <Code>invalidate()</Code>{" "}
 explicitly as a safety net against the 1-second mtime
 quantization on ext4 + APFS.
 </p>
 <p className="text-sm text-on-surface-variant">
 Invariants: the bundle root never changes at runtime (baked
 into the image) so it&apos;s an effectively-eternal cache hit.
 The user root changes only via upload/delete endpoints which
 call <Code>invalidate()</Code> after writing. Container
 restart re-scans by design — YAMLs are the source of truth;
 the cache is purely an in-memory accelerator.
 </p>
 <p className="text-sm text-on-surface-variant">
 <strong>Schema-drawer resolution order.</strong>{" "}
 A source&apos;s schema (drawer + the agent&apos;s{" "}
 <Code>data_sources_get_schema</Code> tool) resolves in order:
 (1) the installed store, for installed sources; (2) the{" "}
 <strong>bundled/user YAML</strong> via{" "}
 <Code>get_by_3tuple</Code> — the same source of truth the
 catalog lists from, so any catalog dataset opens even when
 uninstalled; (3) the cortex-content baked tree, only for packs
 with no YAML. The YAML step is what lets a second dataset under
 one pack+rule that cortex doesn&apos;t enumerate (e.g.{" "}
 <Code>okta_sso_raw</Code>) open in the drawer.
 </p>
 </SubSection>

 <SubSection icon="diagram_2" title="Picture — internal data flow">
 <p>
 The diagram below shows a single <Code>/data-sources</Code>{" "}
 request flowing through Phantom&apos;s four layers — browser →
 Next.js proxy → embedded MCP → YAML loader — and the two
 storage roots the loader scans (bundle: read-only, ships with
 the image; user: writable through the CRUD endpoints). The
 Response enrichment box on the right surfaces the four fields
 the API adds beyond the YAML&apos;s own attributes:{" "}
 <Code>vendor_logo_url</Code>, <Code>use_cases</Code>,{" "}
 <Code>origin</Code>, and <Code>vendor_key</Code>.
 </p>
 <DataSourcesFlow />
 <p className="text-sm text-on-surface-variant">
 The <Code>accept_token</Code> at the write gate is the SHA-256
 of the canonical-serialized YAML doc returned by the preview
 endpoint. Server re-hashes the incoming body and compares; a
 mismatch ⇒ HTTP 409 force re-preview. Same discipline applies
 to POST (create) and PUT (edit) — the operator must have
 previewed the exact bytes they&apos;re about to commit.
 </p>
 </SubSection>

 <SubSection icon="edit_note" title="Edit flow — PUT /user/{id}">
 <p>
 Operators edit a previously uploaded YAML in place via the{" "}
 <Code>PUT</Code> endpoint. The request body shape mirrors the
 upload POST — a YAML doc (or pre-parsed dict), an{" "}
 <Code>accept_token</Code> obtained from{" "}
 <Code>/user/preview</Code>, and a <Code>vendor_choice</Code>{" "}
 discriminator.
 </p>
 <Pre>{`PUT /api/v1/data-sources/user/{id}

Body (same shape as POST /user):
  {
    "yaml":         "<full YAML text>" | "doc": { ...parsed... },
    "accept_token": "<sha256(canonical_yaml) — from /user/preview>",
    "vendor_choice": "create_new" | "group_under"
  }

Semantics — differs from POST /user in three places:
  • Target MUST already exist                  →  HTTP 404
  • Body's id MUST equal path id (no rename)   →  HTTP 409
  • created_at preserved from on-disk YAML;    →  updated_at refreshed
    operator's body value ignored                   server-side

Success: 200  →  { ok: true, id, data_source: {...row...} }

Audit row: data_source_user_edit (logs field-count delta + vendor delta)`}</Pre>
 <p className="text-sm text-on-surface-variant">
 Loader contract: <Code>DataSourcesYamlLoader.update_user(ds_id, doc)</Code>{" "}
 verifies the target exists, validates the body id matches the
 path id, preserves <Code>created_at</Code> from the on-disk
 YAML, refreshes <Code>updated_at</Code>, and busts the
 scan-cache + id-index after the successful write.
 </p>
 <p className="text-sm text-on-surface-variant">
 UI affordances surface the edit button in three places on the{" "}
 <Code>/data-sources</Code> page: the row inside an expanded
 vendor tray on the Browse tab (inline Edit button), the
 Installed card footer (pencil-icon button), and the Detail
 Drawer footer (pill alongside Install / Uninstall). All three
 are gated by <Code>row.origin === &quot;user&quot;</Code>. This
 flow edits the operator&apos;s <em>own</em> uploaded YAML in
 place. System (bundle) sources use the distinct{" "}
 <em>versioned overlay</em> edit described next — they are
 editable too.
 </p>
 </SubSection>

 <SubSection icon="history" title="Versioning overlay — edit any source">
 <p>
 <strong>Any data source — system (bundle) or user — can have
 its <Code>how_to_use</Code> guidance and field schema edited,
 with full version history.</strong> Edits never mutate the
 file on disk. Instead each save is a full-YAML snapshot in a
 new store, and the loader serves the newest snapshot as an{" "}
 <em>overlay</em>. The shipped/uploaded file stays pristine, so
 an operator can always roll back to the original.
 </p>
 <Pre>{`data_source_versions.db  (DATA_ROOT/ — SQLite, owned by MCP)
└── data_source_versions (
      data_source_id  TEXT NOT NULL,   -- "<pack>/<rule>/<dataset>"
      version         INTEGER NOT NULL,
      yaml_snapshot   TEXT NOT NULL,   -- full YAML doc at this version
      created_at      TEXT NOT NULL,
      author          TEXT NOT NULL,   -- "bundle-baseline" | "operator" | "agent"
      note            TEXT,            -- optional change note
      is_current      INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (data_source_id, version)
    )

Invariant: exactly one row per data_source_id has is_current=1.`}</Pre>
 <p className="text-sm">
 <strong>Resolution order (the overlay).</strong> The YAML
 loader resolves each source as: <em>store-current → user
 YAML → bundle YAML</em>. If the version store has a current
 snapshot for a source, that snapshot wins; otherwise the file
 (user root, then bundle root) is served as before. The overlay
 is applied in <Code>list_all()</Code> and{" "}
 <Code>get_by_3tuple()</Code> and degrades gracefully — any
 parse/store error falls back to the file.
 </p>
 <p className="text-sm">
 <strong>v1 = the original (baseline-on-first-edit).</strong>{" "}
 The first time a source is edited, the loader snapshots the
 <em>pristine</em> doc as version 1 (author{" "}
 <Code>bundle-baseline</Code>) before writing the edit as
 version 2. Unedited sources cost zero storage; edited sources
 always carry their original as v1.{" "}
 <strong>Rollback is non-destructive</strong> —
 rolling back to vK copies vK&apos;s snapshot forward as a new
 current version; the intervening versions stay in history, so
 roll-forward always works. Nothing is ever deleted.
 </p>
 <Pre>{`Edit path (shared by REST + agent):
  _apply_edit(pack, rule, dataset, *, how_to_use?, fields?, note?, author)
   1. resolve current doc via loader.get_by_3tuple(...).to_doc()
   2. patch how_to_use / fields
   3. validate against data_source.schema.json + field-name uniqueness
      └─ on failure → {ok: false, error} (NO snapshot written)
   4. first edit? snapshot original as v1 (author "bundle-baseline")
   5. snapshot the edit as the new current version
   6. loader.invalidate()  → next read serves the overlay

Rollback path (shared):
  _apply_rollback(pack, rule, dataset, *, version, author)
   → store.rollback(id, k): copy vK's yaml_snapshot forward as a new
     current version (note "rolled back to vK"); history preserved.

REST (catalog-side; + Next.js /api/agent/... proxies):
  PUT  /api/v1/data-sources/{pack}/{rule}/{dataset}/edit            edit (author "operator")
  GET  /api/v1/data-sources/{pack}/{rule}/{dataset}/versions        history metadata list
  GET  /api/v1/data-sources/{pack}/{rule}/{dataset}/versions/{n}    one version (full snapshot)
  POST /api/v1/data-sources/{pack}/{rule}/{dataset}/rollback        body {version} (author "operator")
  GET  /api/v1/data-sources/{pack}/{rule}/{dataset}/export[?version=n]  YAML; default = current overlay

Agent MCP tools (catalog-side):
  data_sources_edit · data_sources_list_versions · data_sources_rollback`}</Pre>
 <p className="text-sm text-on-surface-variant">
 <strong>Inter-service wiring.</strong>{" "}
 <Code>/data-sources</Code> page (Next.js, port 3000) → Next.js
 proxy <Code>PUT /api/agent/data-sources/{`{pack}/{rule}/{dataset}`}/edit</Code>{" "}
 → embedded MCP (Python FastMCP, loopback 8080, bearer{" "}
 <Code>MCP_TOKEN</Code>) → <Code>_apply_edit</Code> →{" "}
 <Code>data_source_versions.db</Code>. The agent reaches the same{" "}
 <Code>_apply_edit</Code> via the <Code>data_sources_edit</Code>{" "}
 MCP tool. Catalog-side (no secrets) per the{" "}
 <Link href="#authentication" className="link">
 catalog/credential boundary
 </Link>.
 </p>
 <p className="text-sm text-on-surface-variant">
 <strong>UI.</strong> The Detail Drawer footer shows an{" "}
 <Code>Edit guidance</Code> pill for system sources
 (<Code>origin !== &quot;user&quot;</Code>) in both preview and
 installed states. It opens a modal with a{" "}
 <Code>how_to_use</Code> editor + change note and a banner
 explaining the override semantics. Beside it a{" "}
 <Code>History</Code> pill opens the version-history panel —
 list every version (author / note / timestamp, current
 tagged), view any version&apos;s snapshot read-only, and roll
 back a non-current version. Schema-field editing from the UI
 is not available (the agent/API path accepts a full{" "}
 <Code>fields</Code> list).
 </p>
 </SubSection>

 <SubSection icon="restore" title="Backup + restore — data sources travel">
 <p>
 The backup zip captures personality, instances, memory, jobs,
 skills, knowledge, and data sources. The data-sources section
 is split into two manifests:
 </p>
 <Pre>{`backup.zip
├── data_sources/
│   ├── user/<id>.json     ← full parsed YAML doc per operator upload
│   │                        (origin=user only — bundle YAMLs travel
│   │                        with the image, not the backup)
│   └── installed.json     ← [{pack_name, rule_name, dataset_name}, …]
│                            install picks (both bundle + user)
├── personality.json
├── instances/...
├── memory/...
├── jobs/...
├── skills/...
└── knowledge/...

Restore order (manifest.json restore_order):
  personality → instances → skills → memory → knowledge → data_sources → jobs

  Rationale: data_sources before jobs because runtime jobs may reference
  installed data sources via the simulate-vendor-logs skill (which
  reads data_sources_list at execution time, not at job-creation
  time). Manifest-driven jobs reseed at boot, so the order only
  matters for ad-hoc runtime jobs.`}</Pre>
 <p className="text-sm text-on-surface-variant">
 Restore is idempotent: each user upload goes through the
 normal preview → commit two-phase flow on the destination, so
 the same accept_token discipline applies; install-set entries
 hit <Code>POST /api/v1/data-sources/install</Code>; already-
 installed packs return 200 with no-op. Bundle YAMLs themselves
 are not exported — they re-arrive in the destination&apos;s
 image. What needs to travel is <em>which ones the operator
 picked</em> (install set) plus <em>what custom ones they
 added</em> (user uploads).
 </p>
 </SubSection>
 </Section>

      <Section id="log-destinations" icon="cloud_upload" title="Log Destinations">
        <p>
          <strong>Log destinations are first-class, operator-managed
          forwarding targets</strong> for synthesized security records.
          Each destination has a stable name + uuid + a type-discriminated
          config schema rendered live in the UI. The platform models
          destinations as a typed domain object with a dedicated page
          + dynamic form.
        </p>

        <SubSection icon="schema" title="Schema-driven type manifests">
          <p>
            Each destination type ships under{" "}
            <Code>bundles/spark/destinations/&lt;id&gt;/</Code> with a
            <Code> spec.yaml</Code> declaring the type&apos;s ConfigParam-style
            field schema and a <Code>handler.py</Code> implementing two
            async functions:
          </p>
          <Pre>{`bundles/spark/destinations/
├── destination.schema.json    ← JSON Schema for the per-type spec.yaml
├── syslog/
│   ├── spec.yaml              ← fields[] + display + icon + handler ref
│   └── handler.py             ← probe() + send() implementations
├── webhook/                   ← 4 auth modes via visible_when discriminator
├── xsiam_http/                ← x-xdr-auth-id + Authorization header pair
├── splunk_hec/                ← Splunk HEC token + {event:...} batches
└── xsiam_assets/              ← BYOS asset ingest — the only external
                                  path that creates asset_inventory rows`}</Pre>
          <p className="text-sm text-on-surface-variant">
            Adding a new destination type = ship one yaml + one Python
            module. Loader auto-picks it up at boot. No code changes in
            the REST surface or the UI form renderer. Matches the
            connector-marketplace mental model.
          </p>
        </SubSection>

        <SubSection icon="dns" title="Assets are a separate subsystem — and logs cannot reach it">
          <p>
            Cortex XSIAM models ASSETS separately from events, in the{" "}
            <Code>asset_inventory</Code> dataset under an{" "}
            <Code>xdm.asset.*</Code> object model. None of Phantom&apos;s log
            paths can create one, and this is measured rather than assumed: a
            CEF event carrying the same flat <Code>xdm_asset_provider</Code> /{" "}
            <Code>xdm_asset_type_id</Code> / <Code>xdm_asset_strong_id</Code>{" "}
            columns that the first-party <Code>panw_ad_hygiene_*_raw</Code>{" "}
            datasets use lands as a dataset row and creates no asset.{" "}
            <Code>xdm.asset</Code> is not part of the event XDM schema at all,
            so no parsing or modeling rule can emit one.
          </p>
          <p>
            Three other doors are closed to an external system. The Asset
            Inventory REST API is read-only. The{" "}
            <Code>POST /logs/v1/xsiam</Code> path that shipping XSOAR asset
            collectors use authenticates with a license custom field
            (<Code>Http_Connector.token</Code>) readable only from code running
            inside the tenant. And the cloud connectors cannot be pointed at a
            mock, because Cortex&apos;s Discovery Engine calls AWS/Azure/GCP
            from Palo Alto&apos;s own SaaS — the customer is never in the
            request path.
          </p>
          <p>
            The <Code>xsiam_assets</Code> destination therefore uses the one
            remaining door: the Vulnerability Ingest / &quot;Bring Your Own
            Scanner&quot; API,{" "}
            <Code>
              POST /public_api/vulnerability-management/v1/external-scans/assets
            </Code>
            . Auth is a STANDARD key (plain <Code>Authorization</Code> +{" "}
            <Code>x-xdr-auth-id</Code>), not the advanced nonce+SHA256 scheme.
            Only <Code>last_seen</Code> is required per asset; a vulnerability
            is optional. The call is asynchronous and returns a{" "}
            <Code>job_id</Code> with no status endpoint, so landing is confirmed
            by reading the inventory back.
          </p>
          <p className="text-sm text-on-surface-variant">
            <Code>probe()</Code> for this type posts an EMPTY asset list and
            treats the resulting <Code>422</Code> as success — that proves
            reachability and entitlement while creating nothing, which is why
            the manifest sets <Code>probe.send_test_message: false</Code>.{" "}
            <Code>send()</Code> issues exactly one request per batch because the
            endpoint allows only 10 requests per hour.
          </p>
          <p className="text-sm mt-2">
            <strong>Implementation gap.</strong> BYOS assets are typed by the
            platform, not by the caller: a record submitted as{" "}
            <Code>provider: AWS</Code> / <Code>asset_type: EC2_INSTANCE</Code>{" "}
            materialises as <Code>xdm.asset.provider = OTHER</Code> and{" "}
            <Code>xdm.asset.type.id = GENERIC_DEVICE_IP</Code>. Phantom cannot
            currently produce cloud-typed assets by any route; properly-typed
            AWS/AZURE/GCP assets come only from first-party cloud discovery.
          </p>
          <p>
            The send path runs through the MCP built-in{" "}
            <Code>phantom_generate_assets</Code>, which is the first caller of
            the destination registry&apos;s <Code>dispatch_send()</Code>. It
            synthesizes a host fleet, resolves a <Code>logdest:&lt;id&gt;</Code>{" "}
            reference MCP-side — the only place that can read both{" "}
            <Code>log_destinations.db</Code> and the SecretStore, so the API key
            never crosses the agent&apos;s tool surface — and dispatches one
            request carrying the whole batch. Note this is a DEDICATED tool
            rather than the xlog worker flow: xlog&apos;s senders are wire-format
            encoders (CEF/RAW/syslog) and BYOS is a JSON API, so assets are
            generated and shipped MCP-side instead.
          </p>
          <p>
            <strong>Correlation is the point.</strong> The tool returns every
            hostname and IP it created so the caller can pin those same values
            into <Code>phantom_create_data_worker</Code>&apos;s{" "}
            <Code>observables_dict</Code>. An IP in a Cisco ASA event then
            resolves to a real asset carrying real findings. A fleet nobody
            references produces two disconnected views — an inventory nothing
            cites, and alerts about hosts that do not exist — which is the
            failure mode this design exists to prevent.
          </p>
        </SubSection>

        <SubSection icon="database" title="Storage + secret boundary">
          <p>
            SQLite store at <Code>/app/data/log_destinations.db</Code>{" "}
            holds the row + non-secret config. Secret slots (declared by
            <Code> type:&quot;secret&quot;</Code> fields in the spec.yaml)
            land in SecretStore at{" "}
            <Code>/agents/phantom/log_destinations/&lt;id&gt;/&lt;slot&gt;</Code>{" "}
            and cascade-delete on row delete.
          </p>
          <Pre>{`CREATE TABLE log_destinations (
    id                   TEXT PRIMARY KEY,
    name                 TEXT NOT NULL UNIQUE,
    type_id              TEXT NOT NULL,
    config_json          TEXT NOT NULL,
    secret_refs_json     TEXT NOT NULL,
    enabled              INTEGER NOT NULL DEFAULT 1,
    is_default           INTEGER NOT NULL DEFAULT 0,
    description          TEXT,
    created_at, updated_at  TEXT NOT NULL,
    last_probe_at        TEXT,
    last_probe_ok        INTEGER,
    last_probe_error     TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0
);`}</Pre>
        </SubSection>

        <SubSection icon="vpn_key" title="Credential boundary">
          <p>
            Log destinations sit on the{" "}
            <Link href="#authentication" className="link">credential side</Link>{" "}
            of the boundary. The agent gets two read-only MCP tools:{" "}
            <Code>log_destinations_list(type_id?)</Code> +{" "}
            <Code>log_destinations_get(id_or_name)</Code> — both return
            <Code> &quot;***&quot;</Code> sentinels for every secret slot.
            All write + probe paths (POST / PATCH / DELETE /probe /set-default)
            are REST-only; the operator UI is the only caller.
          </p>
        </SubSection>

        <SubSection icon="alt_route" title="Store-driven log generation (the resolution chokepoint)">
          <p>
            When the agent generates logs it does NOT format a raw address
            or touch any destination secret. It passes a{" "}
            <strong>reference</strong> —{" "}
            <Code>destination=&quot;logdest:&lt;id&gt;&quot;</Code> — to{" "}
            <Code>phantom_create_data_worker</Code>. The reference is
            resolved <strong>server-side, inside the MCP</strong>, at the
            connector-proxy chokepoint, immediately before the call is
            forwarded to the xlog connector container:
          </p>
          <Pre>{`agent (chat)
  │  destination = "logdest:<id>"
  ▼
MCP  pkg/connector_proxy.proxy_call_tool          ← resolution chokepoint
  │   └ usecase/log_destination_resolver.resolve_worker_args
  │       • syslog      → destination = "<proto>:<host>:<port>"
  │       • xsiam_http  → destination = "XSIAM_WEBHOOK"
  │                       + webhook_url / webhook_key (plaintext auth_key,
  │                         read from merged_config = store + SecretStore)
  ▼  MCP-over-HTTP (bearer) — resolved address + injected key
xlog connector  phantom-connector-xlog-<name>:9000
  │   forwards webhookUrl / webhookKey on BOTH createDataWorker
  │   and createScenarioWorkerFromQuery
  ▼  GraphQL over HTTP
xlog service  xlog:8000 → rosetta Sender / WebhookSender → destination`}</Pre>
          <p>
            <strong>Why resolve in the MCP</strong> — not the agent, not the
            connector? The MCP is the only layer that can read BOTH{" "}
            <Code>log_destinations.db</Code> AND the SecretStore. Resolving
            here means the xsiam_http auth key travels only{" "}
            MCP&nbsp;→&nbsp;connector&nbsp;→&nbsp;xlog over the internal
            network — it never crosses the agent&apos;s tool surface, so the{" "}
            <Link href="#authentication" className="link">credential
            boundary</Link> holds even though the agent triggered the send.
            The agent only ever sees the opaque{" "}
            <Code>logdest:&lt;id&gt;</Code> handle.
          </p>
          <ul className="list-disc pl-6 mt-2 text-sm space-y-1">
            <li><strong>Selection is the agent&apos;s job</strong> (system
              prompt + the <Code>generate-logs</Code> skill): list configured
              destinations, use the single transport match without asking,
              ask on ambiguity, create a secretless syslog or guide the
              operator on none.</li>
            <li><strong>Resolution is the platform&apos;s job</strong>: the
              agent never formats an address or reads a secret.</li>
            <li>The agent CAN create secretless syslog destinations
              (<Code>log_destinations_create</Code>) but never credentialed
              ones — those stay on the operator-only REST + UI path.</li>
          </ul>
          <p className="text-sm text-on-surface-variant">
            Scope: covers <Code>phantom_create_data_worker</Code> (both its{" "}
            <Code>createDataWorker</Code> and{" "}
            <Code>createScenarioWorkerFromQuery</Code> routes — xlog honors{" "}
            <Code>webhookUrl</Code>/<Code>webhookKey</Code> on each, falling
            back to the <Code>WEBHOOK_ENDPOINT</Code> env default when
            absent). The file-scenario tool{" "}
            (<Code>phantom_create_scenario_worker</Code>) takes a destination
            object and is not yet on the <Code>logdest:</Code> path;{" "}
            <Code>webhook</Code> / <Code>splunk_hec</Code> destination types
            are not yet wired into generation.
          </p>
        </SubSection>

        <SubSection icon="settings_ethernet" title="Per-type probe + send">
          <p>
            Each handler exposes two async callables:{" "}
            <Code>probe(merged_config)</Code> sends a real test message and
            returns <Code>{`{ok, error, latency_ms}`}</Code>;{" "}
            <Code>send(merged_config, records)</Code> forwards a batch and
            returns <Code>{`{sent, failed, errors}`}</Code>. The MCP boots
            the handlers eagerly via file-path import — a missing handler.py
            fails MCP boot loudly (no silent fallback).
          </p>
          <ul className="list-disc pl-6 mt-2 text-sm">
            <li><strong>syslog</strong> — UDP/TCP/TLS. RFC3164 + RFC5424 framing.
              TLS via in-memory PEM → temp files; full facility codes.</li>
            <li><strong>webhook</strong> — 4 auth modes (none / bearer / basic /
              api_key_header) via <Code>visible_when</Code> discriminator on
              <Code> auth_type</Code>.</li>
            <li><strong>xsiam_http</strong> — XSIAM-specific{" "}
              <Code>x-xdr-auth-id</Code> + <Code>Authorization</Code> header pair;
              <Code> {`{events: [...]}`}</Code> envelope.</li>
            <li><strong>splunk_hec</strong> — Splunk HEC{" "}
              <Code>Splunk &lt;token&gt;</Code> auth; newline-separated
              <Code> {`{event:...}`}</Code> batches; optional verify-ssl toggle.</li>
          </ul>
          <p className="text-sm text-on-surface-variant mt-2">
            <Code>probe()</Code> is live — it backs the <em>Test</em> button on{" "}
            <Code>/log-destinations</Code> (REST{" "}
            <Code>POST /&#123;id&#125;/probe</Code>). <Code>send()</Code> is the
            per-handler forwarding primitive for direct destination delivery;
            today the agent&apos;s log-<em>generation</em> path egresses through
            xlog (see <strong>Store-driven log generation</strong> above), not{" "}
            <Code>handler.send()</Code>.
          </p>
        </SubSection>

        <SubSection icon="autorenew" title="Legacy WEBHOOK_ENDPOINT compatibility">
          <p>
            Older installs configured their XSIAM forwarding via the{" "}
            <Code>WEBHOOK_ENDPOINT</Code> / <Code>WEBHOOK_KEY</Code> env
            vars. On boot, if those env vars are set AND no{" "}
            <Code>xsiam_http</Code> destination exists yet, the store
            auto-creates an &quot;XSIAM Default&quot; destination marked{" "}
            <Code>is_default=true</Code>. Idempotent on subsequent
            boots; safe to leave in <Code>.env</Code> permanently.
          </p>
        </SubSection>

        <SubSection icon="dataset" title="XSIAM dataset routing">
          <p>
            Knowing the dataset destinations write to is the difference
            between &quot;agent verifies the records arrived&quot; and
            &quot;agent reports zero rows because it queried the wrong
            dataset.&quot; The conventions are stable per destination type:
          </p>
          <Pre>{`Destination type → XSIAM dataset

xsiam_http   →  phantom_logs_raw   (ALWAYS; XSIAM-side hardcoded for
                                    the 'phantom' brand on the collector)
                Shape: 1 row per batch with an 'events' JSON-array
                column holding the original record list. A downstream
                modeling rule unflattens per-event if needed.

syslog (CEF) →  <vendor>_<product>_raw   (lowercased, non-alphanumeric
                                          chars → '_')
                ONLY when records are CEF-formatted AND the destination
                is an XSIAM broker VM. Example: vendor='Fortinet' +
                product='FortiGate' → 'fortinet_fortigate_raw'.
                Each CEF extension key (act, src, dst, spt, dpt, ...)
                arrives as a typed column — no modeling rule needed
                for the basic fields.

syslog (JSON)→  depends on the broker's input config (no convention).
                If you send raw JSON in the syslog MSG body, the
                broker may drop it OR route to a catchall — ask the
                operator which dataset their broker is mapped to.`}</Pre>
          <p>
            The <Code>phantom_create_data_worker</Code> docstring
            teaches the agent these mappings so when an operator says
            &quot;simulate 50 FortiGate logs and verify they arrived in
            XSIAM,&quot; the agent fires the worker with the right{" "}
            <Code>type/vendor/product</Code> AND queries{" "}
            <Code>fortinet_fortigate_raw</Code> after the ingestion
            wait window.
          </p>
        </SubSection>

        <SubSection icon="diagram_2" title="Picture — internal data flow">
          <p>
            The diagram below shows a single{" "}
            <Code>/log-destinations</Code> request flowing through
            Phantom&apos;s four layers — browser → Next.js proxy →
            embedded MCP → SQLite + SecretStore. The MCP lane splits
            into three concerns: the <strong>types loader</strong>{" "}
            (boot-time scan of <Code>bundles/spark/destinations/</Code>),
            the <strong>store</strong> (CRUD + the one-shot{" "}
            <Code>WEBHOOK_ENDPOINT</Code> migration), and the{" "}
            <strong>handler registry</strong> (per-type{" "}
            <Code>probe()</Code> + <Code>send()</Code> dispatch). The
            credential boundary is explicit: secrets land in
            SecretStore at{" "}
            <Code>/agents/phantom/log_destinations/&lt;id&gt;/&lt;slot&gt;</Code>,
            never in the SQLite row (which only carries{" "}
            <Code>secret_refs_json</Code> pointers), and the
            agent-callable MCP tools return <Code>&quot;***&quot;</Code>{" "}
            sentinels for every secret slot.
          </p>
          <LogDestinationsFlow />
          <p className="text-sm text-on-surface-variant">
            The orange edge at the bottom-right is the{" "}
            <strong>probe path</strong> (the <em>Test</em> button) — the
            only edge in THIS diagram that leaves the trust boundary.
            (Generated logs leave by a different route — the resolution
            chokepoint → xlog — described under &quot;Store-driven log
            generation&quot; above.) Every other write stays inside the
            container. Adding a new destination type follows the
            same shape: ship a <Code>spec.yaml</Code> + a{" "}
            <Code>handler.py</Code> under{" "}
            <Code>bundles/spark/destinations/&lt;id&gt;/</Code>; the
            loader picks it up at next boot, the form-engine renders
            the UI from the schema, and the handler registry imports
            the dispatch callables. No REST surface or UI form code
            changes.
          </p>
        </SubSection>

        <SubSection icon="folder_open" title="Files of record">
          <ul className="list-disc pl-6 text-sm">
            <li><Code>bundles/spark/destinations/*</Code> — type manifests + handlers (this is the contract; add new types here)</li>
            <li><Code>bundles/spark/mcp/src/usecase/destination_types_loader.py</Code> — YAML loader + JSON-schema validator</li>
            <li><Code>bundles/spark/mcp/src/usecase/destination_handler_registry.py</Code> — file-path-based handler import + dispatch</li>
            <li><Code>bundles/spark/mcp/src/usecase/log_destinations_store.py</Code> — SQLite CRUD + WEBHOOK_ENDPOINT migration</li>
            <li><Code>bundles/spark/mcp/src/usecase/log_destination_resolver.py</Code> — resolves <Code>logdest:&lt;id&gt;</Code> → concrete address (syslog) or <Code>XSIAM_WEBHOOK</Code> + injected url/key (xsiam_http)</li>
            <li><Code>bundles/spark/mcp/src/pkg/connector_proxy.py</Code> — the resolution chokepoint: <Code>proxy_call_tool</Code> resolves the reference MCP-side before forwarding to the xlog connector</li>
            <li><Code>bundles/spark/mcp/src/api/log_destinations.py</Code> — REST routes (CRUD + probe + set-default)</li>
            <li><Code>mcp/agent/app/log-destinations/page.tsx</Code> — operator UI</li>
            <li><Code>mcp/agent/components/form-engine.tsx</Code> — reusable dynamic-form renderer with <Code>visible_when</Code> support</li>
            <li><Code>mcp/agent/components/diagrams/log-destinations-flow.tsx</Code> — the diagram above</li>
          </ul>
        </SubSection>
      </Section>
 </>
);
}

// ─── Operator workflow state ───────────────────────────────────────

function OperatorState() {
 return (
 <Section id="operator-state" icon="checklist" title="Operator Workflow State">
 <p>
 <strong>This section is the source of truth for operator workflow
 state.</strong> Any UI surface that persists operator-facing
 progress / preferences / saved-queries / bookmarks MUST conform
 to the contract below — single canonical home in MCP.
 </p>

 <SubSection icon="category" title="The three state categories — distinct boundaries">
 <p>
 CLAUDE.md codifies a three-category model. Operator workflow
 state is the third leg.
 </p>
 <Pre>{`╔═══════════════════════╦═══════════════════════════╦═══════════════════════╗
║ Category              ║ Examples                  ║ Where it lives        ║
╠═══════════════════════╬═══════════════════════════╬═══════════════════════╣
║ Credential            ║ Admin password, Vertex    ║ SecretStore           ║
║                       ║ SA JSON, API keys,        ║   /app/data/secrets/  ║
║                       ║ per-connector secrets     ║ (AES-256-GCM at rest) ║
║                       ║                           ║ Agent: FORBIDDEN      ║
╠═══════════════════════╬═══════════════════════════╬═══════════════════════╣
║ Catalog               ║ Marketplace install state,║ marketplace.db        ║
║                       ║ user-uploaded connectors  ║   /app/data/          ║
║                       ║ + their YAMLs             ║ user_connectors/      ║
║                       ║                           ║ Agent: PERMITTED      ║
║                       ║                           ║ (catalog tools, no    ║
║                       ║                           ║  secret access)       ║
╠═══════════════════════╬═══════════════════════════╬═══════════════════════╣
║ Operator workflow     ║ Journey-tested marks,     ║ operator_state.db     ║
║                       ║ metrics bookmarks,        ║   /app/data/          ║
║                       ║ future: saved filters,    ║ Agent: NOT EXPOSED    ║
║                       ║ favorite skills, etc.     ║ (operator-only UI)    ║
╚═══════════════════════╩═══════════════════════════╩═══════════════════════╝`}</Pre>
 <ul className="list-disc pl-6 space-y-1">
 <li>None of the three categories permit the agent to touch credentials. Catalog tools (marketplace_install etc.) are agent-accessible; operator workflow state is NOT agent-accessible today (no use case yet — if one emerges, a narrow read-only tool gets added then, per CLAUDE.md &quot;catalog boundary ≠ credential boundary&quot; rules).</li>
 <li>UI preferences (theme, sidebar collapsed, debug panel open/closed) are a FOURTH category — legitimately device-local, NOT in operator_state.db. They stay in localStorage. The rule of thumb: if the operator&apos;s answer to &quot;should this follow me to my other laptop?&quot; is yes, it&apos;s operator workflow state; if it&apos;s no (because the laptop has a different screen size, different desk setup, etc.), it&apos;s a UI preference.</li>
 </ul>
 </SubSection>

 <SubSection icon="storage" title="Storage contract">
 <Pre>{`operator_state.db  (DATA_ROOT/ — SQLite, sole source of truth)
 └── operator_state(
       key         TEXT PRIMARY KEY,
       value_json  TEXT NOT NULL,    -- arbitrary JSON; hook owns shape
       updated_at  TEXT NOT NULL     -- ISO 8601 UTC
     )

Current keys:
  tested_journeys      : string[] of journey ids
  metrics_bookmarks    : array of {label, query, savedAt} objects

Future keys (no schema change required — just pick a new key):
  saved_filters        : per-operator search filter presets
  favorite_skills      : skills the operator pins to the top
  chat_compose_drafts  : in-flight drafts not yet sent
`}</Pre>
 <p>
 The store is intentionally untyped at the SQL layer — value_json
 holds whatever the hook serializes. Per-key shape is documented
 in the hook&apos;s top-of-file comment block. This trades a small
 amount of schema rigor for zero migration overhead when adding
 new operator workflow concerns.
 </p>
 </SubSection>

 <SubSection icon="api" title="REST surface">
 <Pre>{`GET    /api/v1/operator-state           → list all keys + values
GET    /api/v1/operator-state/{key}     → one key (404 if unset)
PUT    /api/v1/operator-state/{key}     → upsert {value: <json>}
DELETE /api/v1/operator-state/{key}     → idempotent 204

Auth: bearer MCP_TOKEN (same as the rest of /api/v1/).
Next.js proxy: /api/agent/operator-state/{key} (session-gated).
`}</Pre>
 <p>
 Hooks (browser-side React) drive these from the operator&apos;s
 UI. Each does <Term>optimistic-update + fire-and-forget PUT</Term>:
 local state updates immediately on toggle; PUT to server runs
 in the background; if the server returns 5xx the operator&apos;s
 intent is retained client-side + a console.warn fires. This
 trades server-side strict consistency for snappy UI — the
 server gets the latest state on every mutation, just not
 synchronously.
 </p>
 </SubSection>

 <SubSection icon="rule" title="Out of scope">
 <ul className="list-disc pl-6 space-y-1">
 <li><strong>Expose operator state to the agent.</strong> Operator workflow state stays operator-only. No <Code>operator_state_get</Code> or similar in the agent&apos;s catalog. If a use case emerges (e.g. agent summarizing &quot;tests you&apos;ve passed&quot;), it&apos;ll come in as a separate narrow read-only tool, scoped per-key.</li>
 <li><strong>Per-user scoping.</strong> Phantom ships single-user (admin only). The schema has no user_id column today; multi-user lands by adding it + moving PRIMARY KEY to (user_id, key). All existing rows migrate cleanly with the DEFAULT clause.</li>
 <li><strong>Migrate UI preferences.</strong> Theme, sidebar-collapsed, debug-panel-open stay in localStorage by intent — device-local is correct for those (per the third-leg discussion above).</li>
 </ul>
 </SubSection>

 <SubSection icon="construction" title="Implementation references">
 <ul className="list-disc pl-6 space-y-1">
 <li><strong>Store</strong>: <Code>bundles/spark/mcp/src/usecase/operator_state_store.py</Code> — SQLite, singleton accessor, list_all for backup.</li>
 <li><strong>REST routes</strong>: <Code>bundles/spark/mcp/src/api/operator_state.py</Code> — GET / PUT / DELETE + audit events.</li>
 <li><strong>Next.js proxy</strong>: <Code>mcp/agent/app/api/agent/operator-state/[key]/route.ts</Code>.</li>
 <li><strong>Hook: tested journeys</strong>: <Code>mcp/agent/lib/use-tested-journeys.ts</Code> — server-backed.</li>
 <li><strong>Hook: metrics bookmarks</strong>: <Code>mcp/agent/components/observability/metrics-bookmarks.tsx</Code> — same shape.</li>
 </ul>
 </SubSection>
 </Section>
);
}

// ─── External Connectors ───────────────────────────────────────────

function XlogConnector() {
 return (
 <Section id="xlog-connector" icon="data_object" title="xlog Connector">
 <p>
 xlog is the synthetic-log generator. It runs as its own service
 (the <Code>phantom</Code> container) and exposes a Strawberry
 GraphQL API. The xlog MCP connector wraps that API as ~25 MCP
 tools so the agent can request log generation through chat. The
 diagram below shows xlog alongside CALDERA and XSIAM PAPI — the
 three external connector backends, each with its protocol, port,
 auth, and tool family.
 </p>

 <ExternalConnectorsAnatomy />

 <SubSection icon="api" title="GraphQL surface">
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <Code>query.listWorkers</Code> — currently active workers
 (in-memory module-level dict; non-persistent).
 </li>
 <li>
 <Code>mutation.createWorker</Code> — start a worker for one
 log type with given format / sender / rate.
 </li>
 <li>
 <Code>mutation.createScenarioWorker</Code> — start a worker
 from a scenario file; references{" "}
 <Code>scenarios/ready/&lt;name&gt;.json</Code>.
 </li>
 <li>
 <Code>mutation.createScenarioWorkerFromQuery</Code> — same
 but inline JSON instead of a file reference.
 </li>
 <li>
 <Code>mutation.stopWorker</Code> — terminate a running worker
 by id.
 </li>
 <li>
 <Code>query.listScenarios</Code> — discover what
 ready-scenario JSONs exist on disk.
 </li>
 </ul>
 </SubSection>
 <SubSection icon="settings" title="Workers, formats, and senders">
 <p>
 Worker types, formats, and senders are declared as Strawberry
 enums in <Code>app/types/datafaker.py</Code> and{" "}
 <Code>app/types/sender.py</Code>. Adding a new vendor format
 (FortiGate, CrowdStrike, etc.) requires touching both the
 enum and the dispatch in <Code>app/schema.py</Code>. Senders
 cover direct UDP, XSIAM HTTP collectors, and arbitrary
 webhook URLs.
 </p>
 </SubSection>
 <SubSection icon="link" title="rosetta-ce">
 <p>
 Vendor-specific event shapes come from the{" "}
 <Code>rosetta-ce</Code> library (external dependency). Phantom
 imports <Code>Events</Code>, <Code>Observables</Code>, and{" "}
 <Code>Sender</Code> classes; vendor catalogues live in
 rosetta-ce, not in this repo. Updating to support a new vendor
 means updating rosetta-ce and bumping the dep.
 </p>
 </SubSection>
 <SubSection icon="warning" title="Webhook auth quirk">
 <p>
 The webhook sender uses header{" "}
 <Code>Authorization: $WEBHOOK_KEY</Code> — raw, not{" "}
 <Code>Bearer</Code>. Any non-XSIAM webhook receiver must
 accept that form. See{" "}
 <Code>_get_webhook_headers</Code> in{" "}
 <Code>app/schema.py</Code>.
 </p>
 </SubSection>
 </Section>
);
}

function CalderaConnector() {
 return (
 <Section id="caldera-connector" icon="swords" title="CALDERA Connector">
 <p>
 CALDERA is a MITRE ATT&amp;CK adversary emulation backend.
 Phantom runs CALDERA 5.3.0 in the <Code>caldera</Code>{" "}
 container and wraps its REST API as MCP tools. The connector
 carries its own state DB independent of phantom-mcp.
 </p>
 <SubSection icon="dns" title="Tool family">
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <Code>caldera_list_abilities</Code> — abilities indexed by
 MITRE technique id.
 </li>
 <li>
 <Code>caldera_list_adversaries</Code> — saved adversary
 profiles.
 </li>
 <li>
 <Code>caldera_list_agents</Code> — connected sandcat agents.
 </li>
 <li>
 <Code>caldera_start_operation</Code> — kick off an
 adversary against an agent group.
 </li>
 <li>
 <Code>caldera_get_results</Code> — operation output, per
 link.
 </li>
 <li>
 <Code>caldera_kill_operation</Code> — terminate.
 </li>
 </ul>
 </SubSection>
 <SubSection icon="settings_input_component" title="Authentication">
 <p>
 CALDERA exposes <Code>red</Code> and <Code>blue</Code> users
 plus a per-user API key. The connector authenticates as the
 red user (<Code>CALDERA_RED_USER</Code> +{" "}
 <Code>CALDERA_RED_PASSWORD</Code>) for operation control and
 uses the API key for query calls. Compose hard-fails the
 stack if those env vars are missing.
 </p>
 </SubSection>
 <SubSection icon="lan" title="Network shape">
 <p>
 CALDERA listens on <Code>:8888</Code> (HTTP) and{" "}
 <Code>:8443</Code> (HTTPS). On the compose network, MCP
 reaches it as <Code>http://caldera:8888</Code>. Sandcat
 agents in your simulated environment dial back to the
 same endpoint over whatever bridge your lab uses; that is
 outside the Phantom stack&apos;s scope.
 </p>
 </SubSection>
 </Section>
);
}

function XsiamConnector() {
 return (
 <Section id="xsiam-connector" icon="security" title="XSIAM Connector">
 <p>
 The XSIAM connector wraps Cortex XSIAM&apos;s public API
 (PAPI). It is the bridge between Phantom&apos;s synthetic
 telemetry and a real detection-engineering surface — operators
 push log streams to XSIAM via webhook senders, then verify
 their detection content fired via XQL queries through this
 connector.
 </p>
 <SubSection icon="api" title="Tool family">
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <Code>xsiam_run_xql</Code> — execute XQL with a
 timestamp window; returns rows.
 </li>
 <li>
 <Code>xsiam_find_xql_examples_rag</Code> — natural-language
 retrieval against the bundled <Code>xql-examples</Code> KB
 (curated queries).
 </li>
 <li>
 Detection-content CRUD —{" "}
 <Code>xsiam_list_detection_rules</Code>,{" "}
 <Code>xsiam_get_rule</Code>,{" "}
 <Code>xsiam_upsert_rule</Code>.
 </li>
 <li>
 Issue stream — read war-room issues and append comments via
 the playground id.
 </li>
 </ul>
 </SubSection>
 <SubSection icon="lock" title="Authentication">
 <p>
 PAPI uses a bearer-style auth pair:{" "}
 <Code>x-xdr-auth-id</Code> (a numeric id) plus an{" "}
 <Code>Authorization</Code> header (a long secret). Both come
 from XSIAM&apos;s API Keys page. Phantom stores them via the
 secret store envelope; the connector attaches both on every
 call.
 </p>
 </SubSection>
 <SubSection icon="science" title="Playground id">
 <p>
 PAPI executes XQL against an &ldquo;issue war room&rdquo;
 context. Phantom uses one fixed playground id
 (<Code>PLAYGROUND_ID</Code>) for all execution. Configurable
 per-instance, but the typical install uses a single
 dedicated playground that the operator created for Phantom.
 </p>
 </SubSection>
 </Section>
);
}

function CortexXdrConnector() {
 return (
 <Section id="cortex-xdr-connector" icon="shield_lock" title="Cortex XDR Connector">
 <p>
 The Cortex XDR connector wraps the Cortex XDR Public API — the same{" "}
 <Code>/public_api/v1/…</Code> endpoint family as XSIAM, with
 identical <Code>Authorization</Code> + <Code>x-xdr-auth-id</Code>{" "}
 header auth. The unified field names (<Code>api_url</Code>,{" "}
 <Code>api_id</Code>, <Code>api_key</Code>) match XSIAM exactly,
 so operators don&apos;t translate between products.
 </p>
 <SubSection icon="api" title="Tool family (5 tools)">
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <Code>xdr_get_cases_and_issues</Code> — list incidents (cases)
 and the alerts (issues) within them, filtered by time range,
 hostname, severity, or status.
 </li>
 <li>
 <Code>xdr_get_incident_extra_data</Code> — drill into one
 incident: all alerts, forensic artifacts, network/file
 artifacts, related users/hosts.
 </li>
 <li>
 <Code>xdr_run_xql_query</Code> — execute an XQL query against
 the XDR data lake. Returns results inline when the query
 completes in the synchronous poll window (default 2 min);
 otherwise returns an <Code>execution_id</Code> for async
 retrieval.
 </li>
 <li>
 <Code>xdr_get_xql_results</Code> — fetch results for an
 in-flight XQL query by its <Code>execution_id</Code>. Use
 when a long query exceeded the synchronous window.
 </li>
 <li>
 <Code>xdr_list_datasets</Code> — empirically
 enumerate XQL datasets available in this tenant. Tries{" "}
 <Code>dataset = X | limit 1</Code> against ~20 well-known
 dataset names and reports which exist. Works on every XDR
 tier (the XSIAM-license-gated <Code>datamodel</Code> stage
 is bypassed).
 </li>
 </ul>
 </SubSection>
 <SubSection icon="dataset" title="Datasets discoverable in a typical tenant">
 <p>
 <Code>xdr_list_datasets</Code> probes ~20 names and reports
 which exist. A representative XDR-only tenant returns ~11–12
 datasets:
 </p>
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <Code>xdr_data</Code> — process, file, network, registry,
 login events (the firehose telemetry)
 </li>
 <li>
 <Code>agent_auditing</Code> — XDR agent self-audit events
 (start/stop, policy changes)
 </li>
 <li>
 <Code>endpoints</Code> — XDR-managed endpoints with agent
 installed (inventory)
 </li>
 <li>
 <Code>host_inventory</Code> / <Code>asset_inventory</Code> —
 discovered hosts and broader assets (XSIAM asset management)
 </li>
 <li>
 <Code>alerts</Code> — flat legacy schema (
 <Code>alert_id</Code>, <Code>severity</Code>,{" "}
 <Code>mitre_attack_tactic</Code>)
 </li>
 <li>
 <Code>issues</Code> — XDM-normalized parallel of alerts (
 <Code>xdm.issue.severity</Code>,{" "}
 <Code>xdm.issue.mitre_tactics</Code>). Operators often pick
 one schema or the other based on whether they want flat-XQL
 ergonomics or XDM normalization. Both contain the same
 source data.
 </li>
 <li>
 <Code>incidents</Code> — incident records aggregating
 related alerts
 </li>
 <li>
 <Code>va_endpoints</Code> / <Code>va_cves</Code> —
 vulnerability assessment (endpoints + CVE catalog)
 </li>
 <li>
 <Code>cloud_audit_logs</Code> — cloud provider audit logs
 (AWS CloudTrail, GCP Audit, Azure)
 </li>
 <li>
 <Code>metrics_source</Code> — broker / collector performance
 metrics
 </li>
 </ul>
 </SubSection>
 <SubSection icon="psychology" title="The XQL skill capability arc">
 <p>
 The connector is paired with the{" "}
 <Code>build_xql_query</Code> skill plus the{" "}
 <Code>xql-examples</Code> KB (curated examples that ship with
 the connector). The chain: operator asks &ldquo;show me X&rdquo; →
 agent runs <Code>knowledge_search</Code> over the KB to find
 a matching template → adapts the query → runs it via{" "}
 <Code>xdr_run_xql_query</Code>. The KB covers many datasets,
 MITRE techniques, and XQL stages including{" "}
 <Code>iploc</Code>, <Code>search</Code>,{" "}
 <Code>replacenull</Code>, <Code>transaction</Code>,{" "}
 <Code>view</Code>, plus window functions (<Code>rank</Code>,{" "}
 <Code>lag</Code>, <Code>first_value</Code>,{" "}
 <Code>last_value</Code>) and aggregation variants (
 <Code>median</Code>, <Code>list</Code>,{" "}
 <Code>earliest</Code>, <Code>latest</Code>).
 </p>
 </SubSection>
 </Section>
);
}

function CortexDocsConnector() {
 return (
 <Section id="cortex-docs-connector" icon="menu_book" title="Cortex Docs Connector">
 <p>
 The Cortex Docs connector (<Code>cortex-docs</Code>) exposes
 the public Cortex XSIAM / XDR documentation as a searchable
 reference. Used by the <Code>build_xql_query</Code> skill to
 look up XQL function/stage syntax when the local{" "}
 <Code>xql-examples</Code> KB doesn&apos;t have a matching
 template — semantic-search complement to the in-product KB.
 </p>
 <SubSection icon="api" title="Tool family">
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <Code>cortex_xql_lookup</Code> — semantic search across all
 indexed Cortex doc pages for an XQL term (e.g. &ldquo;arraymap
 example&rdquo;, &ldquo;windowcomp frame&rdquo;,{" "}
 &ldquo;coverage of MITRE Attack tactics&rdquo;). Returns
 page-level summaries with publication metadata and a deep
 link to the canonical doc URL.
 </li>
 </ul>
 </SubSection>
 <SubSection icon="lock" title="Authentication">
 <p>
 No external auth required — the docs are public. The connector
 runs an embedded vector index built at image-bake time from a
 snapshot of the official docs site. Updating to a newer
 documentation snapshot requires rebuilding the connector image.
 </p>
 </SubSection>
 </Section>
);
}

function CortexContentConnector() {
 return (
 <Section id="cortex-content-connector" icon="library_books" title="Cortex Content Connector">
 <p>
 The Cortex Content connector (<Code>cortex-content</Code>)
 exposes the official Palo Alto Networks{" "}
 <Code>palo-cortex/content</Code> GitHub repository — detection
 rules, parsers, dashboards, playbooks — as a searchable
 reference. Operators use it to (a) look up the Cortex-published
 rule for a behavior they care about, (b) ground their own rule
 authoring on the official content shape, (c) confirm a
 detection name they saw in alerts originates from official
 content versus a custom rule.
 </p>
 <SubSection icon="api" title="Tool family">
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <Code>cortex_content_search</Code> — semantic search across
 the indexed content repo (rules, BIOCs, parsers, dashboards)
 for a natural-language query.
 </li>
 <li>
 <Code>cortex_content_get</Code> — fetch a specific content
 artifact by path or ID.
 </li>
 </ul>
 </SubSection>
 <SubSection icon="lock" title="Authentication">
 <p>
 No external auth required — the content repo is public. Like{" "}
 <Code>cortex-docs</Code>, an embedded vector index ships in
 the connector image at bake time. Updating to a newer content
 snapshot requires rebuilding the connector image.
 </p>
 </SubSection>
 </Section>
);
}

function WebConnector() {
 return (
 <Section id="web-connector" icon="language" title="Web Browser Connector">
 <p>
 The Web Browser connector (<Code>web</Code>) drives a headless
 Chromium for tasks the agent can&apos;t do with REST tools —
 navigating JavaScript-heavy pages, executing in-page JS,
 capturing screenshots, exporting cookies for downstream auth
 flows, scraping pages that gate content behind interactive
 controls. Backed by the <Code>phantom-browser</Code> service
 (profile-gated; only spawns when a web-connector instance
 exists per CLAUDE.md §Stack topology).
 </p>
 <SubSection icon="api" title="Tool family">
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <Code>web_navigate</Code> — open a URL, return rendered DOM.
 </li>
 <li>
 <Code>web_evaluate</Code> — execute JavaScript in the page
 context, return the result.
 </li>
 <li>
 <Code>web_screenshot</Code> — capture page screenshot (full
 page or viewport).
 </li>
 <li>
 <Code>web_get_cookies</Code> / <Code>web_set_cookies</Code> —
 read/write the browser&apos;s cookie jar (for downstream
 auth flows the agent needs to maintain).
 </li>
 <li>
 <Code>web_click</Code> / <Code>web_fill</Code> — interact
 with DOM elements via selector.
 </li>
 </ul>
 </SubSection>
 <SubSection icon="settings_input_component" title="Architecture (Playwright + CDP)">
 <p>
 The web connector container spawns a Playwright client and
 attaches it to <Code>phantom-browser</Code> via the Chrome
 DevTools Protocol (
 <Code>connect_over_cdp(&quot;http://phantom-browser:9222&quot;)</Code>
 ). Playwright never spawns its own Chromium — that would
 balloon the connector image size. Sharing one host browser
 across all web-connector instances keeps per-instance
 overhead small.
 </p>
 </SubSection>
 <SubSection icon="lock" title="Authentication + safety">
 <p>
 No connector-level auth (no upstream API key required), but
 web fetches are subject to per-task safety constraints — the
 agent treats fetched content as untrusted data per the
 platform&apos;s prompt-injection defense (see{" "}
 <Code>#auth-identity</Code>).
 </p>
 </SubSection>
 </Section>
);
}

// ─── Auth & Security ───────────────────────────────────────────────

function AuthIdentity() {
 return (
 <Section id="auth-identity" icon="shield_person" title="Auth & Identity Flows">
 <p>
 Four identity boundaries meet inside Phantom: operator (HTTP),
 agent (browser), MCP (compose-internal), and external
 connectors. Each has its own auth surface; understanding all
 four is necessary before wiring up an integration or debugging
 a 401. The diagram shows the concentric trust zones with their
 auth headers, plus the three-tier approval ladder for tool
 gating.
 </p>

 <AuthTrustBoundaries />

 <SubSection icon="person" title="Operator → UI (session cookie)">
 <p>
 The Next.js <Code>middleware.ts</Code> validates a{" "}
 <Code>phantom_session</Code> cookie on every request to{" "}
 <Code>/api/agent/**</Code>, <Code>/api/chat</Code>, and{" "}
 <Code>/api/skills/**</Code>. The cookie is minted by{" "}
 <Code>POST /api/auth/login</Code> after PBKDF2-HMAC-SHA256
 password verification and carries a server-side validated
 32-byte random token (HttpOnly · Secure · SameSite=Strict ·
 2-hour Max-Age). See{" "}
 <Link href="#authentication" className="link">
 Authentication
 </Link>{" "}
 for the full flow, password-change semantics, and CLI reset
 utilities.
 </p>
 </SubSection>
 <SubSection icon="vpn_key" title="Agent → MCP (Bearer MCP_TOKEN)">
 <p>
 Every <Code>fetch</Code> from an agent route handler to MCP
 attaches{" "}
 <Code>Authorization: Bearer $MCP_TOKEN</Code>. The token is
 process-env on both sides; Compose injects the same value into
 both containers. The browser never sees this token.
 </p>
 </SubSection>
 <SubSection icon="key" title="External clients → REST (API keys)">
 <p>
 Operator-issued API keys (32-byte random, hashed at rest with
 a per-deploy pepper) gate{" "}
 <Code>/api/v1/*</Code> for non-browser callers. Routes accept
 either UI Basic auth (operator path) or an API key bearer
 (script path). Keys carry a name, created-at, last-used-at,
 and disabled flag.
 </p>
 </SubSection>
 <SubSection icon="cable" title="Phantom → external (per-connector)">
 <p>
 Each connector instance carries its own credentials in the
 secret store: CALDERA red-user + API key, XSIAM PAPI
 auth-id + auth-header, xlog webhook key, Vertex SA JSON. The
 connector reads from the secret store at call time, never
 from process env.
 </p>
 </SubSection>
 </Section>
);
}

function SecretStore() {
 return (
 <Section id="secret-store" icon="lock" title="Secret Store">
 <p>
 Every connector secret, provider credential, and operator UI
 password lives behind a single abstraction:{" "}
 <Code>SecretStore.read(path)</Code> /{" "}
 <Code>write(path, value)</Code> /{" "}
 <Code>delete(path)</Code> /{" "}
 <Code>list_under(prefix)</Code>. The interface is identical
 across all backends, so consumers (instance store, provider
 store, ui_auth) never know which backend is serving them.
 Plaintext is materialised only at call time, in-process,
 never logged or returned over the API.
 </p>

 <SubSection icon="account_tree" title="Write surfaces and override precedence">
 <p>
 The diagram below maps every operator-facing surface that can
 write to the SecretStore (top half) and every consumer that
 reads from it (bottom half). The visual argument: there is
 exactly one encrypted-at-rest store, and it&apos;s the
 single source of truth no matter which UI the operator used
 to set the value.
 </p>
 <SecretStoreFlow />
 <p className="text-sm text-on-surface-variant/80 mt-4">
 Notes on the colour-coded edges:
 </p>
 <ul className="list-disc pl-5 space-y-1.5 text-sm">
 <li>
 The <Term>/setup</Term> form is the{" "}
 <strong>first-run-only</strong> bootstrap path. It runs
 ONCE at install time, writes setup.json (with{" "}
 <Code>setupComplete: true</Code>) + .env.generated +
 invokes the MCP&apos;s <Code>POST /api/v1/setup</Code>{" "}
 binding-expansion which materialises every connector +
 provider instance and writes its <Code>secretRefs</Code>{" "}
 slots into the SecretStore. After that first save, the
 form locks: the route page redirects to <Code>/</Code>{" "}
 when <Code>setupRequired=false</Code>, and the
 <Code> POST /api/setup</Code> handler returns 409 with a
 message pointing operators at the dedicated post-install
 surfaces.
 </li>
 <li>
 The <Term>/providers/config</Term> page is the canonical
 post-install path for Vertex JSON updates. It writes to
 setup.json AND pushes the same payload through the MCP
 setup endpoint (via the shared{" "}
 <Code>pushSetupToMcp</Code> helper) so the
 SecretStore-backed provider instance stays current. The
 bundleValuesChanged guard in this route skips the MCP push
 when no provider field actually changed (no-op saves
 don&apos;t re-materialise).
 </li>
 <li>
 The <Term>/connectors/[id]</Term> page edits per-instance
 config + secrets directly via the MCP&apos;s instance API.
 Writes go straight to the InstanceStore + SecretStore and
 take effect at the next tool call. Operator wants to
 change a connector URL or rotate an API key →{" "}
 /connectors is the right surface, no agent restart, no
 setup re-run, no merge logic.
 </li>
 <li>
 The <Term>/profile</Term> password change path is its own
 dedicated route (<Code>/api/auth/change-password</Code>)
 that writes a PBKDF2-HMAC-SHA256 hash to the SecretStore
 at <Code>/ui/auth/&lt;user&gt;/password_hash</Code>.
 </li>
 <li>
 The <Term>EnvSecretStore overlay</Term> is a read-time
 shadow — env values mask stored secrets without rewriting
 them. Useful for IaC / CI flows that want to pin a
 specific credential per deployment without mutating the
 encrypted store.
 </li>
 </ul>
 <p className="text-sm text-on-surface-variant/80 mt-4">
 Bottom-half edges:
 </p>
 <ul className="list-disc pl-5 space-y-1.5 text-sm">
 <li>
 <Term>MCP tool calls</Term> + <Term>UI login verify</Term>{" "}
 are live read paths today.
 </li>
 <li>
 <Term>Chat → Vertex (today)</Term> is dashed-muted because
 it&apos;s the legacy env-var path: the chat handler reads{" "}
 <Code>GOOGLE_APPLICATION_CREDENTIALS</Code> from the setup-
 mirrored env, not directly from the SecretStore via the
 provider instance. Functionally identical to the future
 path; the difference matters when v1.2 cuts the setup-mirror
 over.
 </li>
 <li>
 <Term>Chat → Vertex (planned)</Term> is the planned
 future read path — straight from the provider instance
 via <Code>SecretStore.read(provider_instance.secret_refs.serviceAccountJson)</Code>.
 The /providers/config sync makes this transition transparent:
 SecretStore is already current, so the day the chat handler
 flips, no migration is needed.
 </li>
 </ul>
 </SubSection>

 <SubSection icon="layers" title="Two backends today, one tomorrow">
 <p>
 Phantom ships two backends. They layer: the env-var
 overlay is consulted first, the file-backed store is the
 default and the only place writes go. InfisicalSecretStore
 lands when Phantom onboards onto Spark.
 </p>
 <Pre>{`╔═══════════════════════════════╤══════════════════════╤══════════════╗
║ Backend                       │ When                 │ Status       ║
╠═══════════════════════════════╪══════════════════════╪══════════════╣
║ File-backed AES-256-GCM       │ Standalone install   │ Shipping     ║
║ EnvSecretStore overlay        │ CI / K8s / IaC       │ Shipping     ║
║ InfisicalSecretStore          │ Spark platform       │ Roadmap      ║
╚═══════════════════════════════╧══════════════════════╧══════════════╝`}</Pre>
 <p>
 Why not Infisical for standalone: forcing a customer to run
 a separate secrets server (and the credentials to reach
 it) just to hold a handful of API keys for one agent is
 overkill. The file-backed store gives the same
 encryption-at-rest property with a single env var and zero
 extra services. When/if Phantom onboards onto Spark, the
 platform&apos;s Infisical takes over &mdash; same{" "}
 <Code>read(path)</Code> calls, different backend.
 </p>
 </SubSection>

 <SubSection icon="folder" title="File-backed AES-256-GCM (today)">
 <p>
 Source: <Code>bundles/spark/mcp/src/usecase/secret_store.py</Code>.
 One file per secret under <Code>/app/data/secrets/</Code>
 (mode 0700 dir, 0600 file). The path you write to maps 1:1
 to the file path on disk:
 </p>
 <Pre>{`/app/data/secrets/
└── agents/
    └── phantom/
        ├── connectors/
        │   └── <instance_id>/
        │       ├── apiToken
        │       └── webhookKey
        ├── providers/
        │   └── <instance_id>/
        │       └── serviceAccountJson
        └── ...
└── ui/
    └── auth/
        └── <username>/
            └── password_hash`}</Pre>
 <p>
 Each file holds a versioned envelope:{" "}
 <Code>v1\\x00</Code> magic header, 12-byte random nonce,
 ciphertext, 16-byte GCM auth tag &mdash; all base64-wrapped
 to keep the file UTF-8-readable for ops tooling. The state
 is the named volume{" "}
 <Code>phantom_mcp_data</Code>, so secrets survive container
 recreation; <Code>docker compose down -v</Code> wipes
 everything.
 </p>
 </SubSection>

 <SubSection icon="bolt" title="EnvSecretStore overlay">
 <p>
 When a secret&apos;s env-var-mapped name is set in the
 process environment, <Code>read()</Code> returns its
 value instead of going to disk. Operators can pre-bake
 secrets via Kubernetes <Code>Secret</Code> mounts,
 Terraform / Helm provisioning, CI runner config, or a
 <Code>.env</Code> file — without ever touching the
 setup form.
 </p>
 <p>
 The mapping is deterministic. The path
 segments uppercase and join with double-underscore,
 prefixed with <Code>PHANTOM_SECRET__</Code>. Examples:
 </p>
 <Pre>{`/agents/phantom/connectors/foo/api_key
  → PHANTOM_SECRET__AGENTS__PHANTOM__CONNECTORS__FOO__API_KEY

/ui/auth/admin/password_hash
  → PHANTOM_SECRET__UI__AUTH__ADMIN__PASSWORD_HASH`}</Pre>
 <p>
 Double-underscore separator avoids ambiguity with the
 single underscores common in slot names (e.g.{" "}
 <Code>password_hash</Code>, <Code>api_token</Code>).
 </p>
 <p>
 <Term>Reads only.</Term> Writes still hit the file
 backend — env vars are owned by whatever provisioned
 the container, and we can&apos;t push back to those
 sources. This is by design: rotation = redeploy.
 </p>
 <p>
 <Term>Audit grain.</Term> Every read records its source
 in audit metadata —{" "}
 <Code>{`{"source": "env"}`}</Code> for overlay reads,
 <Code>{`{"source": "file"}`}</Code> for file-backed.
 SOC operators can tell at-a-glance which secrets came
 from runtime environment vs. operator setup.
 </p>
 <p>
 <Term>Boot inventory.</Term> The agent logs every bound
 overlay env var → secret-path mapping at startup so
 the inventory is visible without consulting{" "}
 <Code>printenv</Code>. Values never appear in the log,
 only names and target paths.
 </p>
 <p>
 <Term>Disable knob.</Term> Set{" "}
 <Code>PHANTOM_ENV_SECRETS_DISABLED=1</Code> to turn
 off the overlay entirely. Useful for testing, or for
 deployments that intentionally don&apos;t want env-var
 precedence.
 </p>
 </SubSection>

 <SubSection icon="key" title="The KEK">
 <p>
 <Code>PHANTOM_SECRET_KEK</Code> is a 32-byte AES key,
 base64-encoded, lives in operator <Code>.env</Code>{" "}
 alongside <Code>MCP_TOKEN</Code>. Generate with{" "}
 <Code>openssl rand -base64 32</Code>. The KEK never leaves
 the MCP process.
 </p>
 <p>
 <Term>Critical:</Term> lose the KEK and every operator-supplied
 secret becomes unrecoverable &mdash; the SQLite-backed path
 references survive but resolve to nothing. KEK + the data
 volume must be backed up together; either alone is useless.
 </p>
 <p>
 KEK-unset = legacy plaintext mode with a loud startup
 warning. Setting the env var on a running deploy migrates
 secrets transparently on the next read of each secret.
 KEK rotation requires re-encrypting every envelope and is
 not a routine operation.
 </p>
 </SubSection>

 <SubSection icon="route" title="Path conventions">
 <p>
 Paths follow the spec&apos;s <Code>/&lt;scope&gt;/&lt;id&gt;/&lt;sub-id&gt;/&lt;slot&gt;</Code>{" "}
 form:
 </p>
 <ul className="list-disc pl-5 space-y-1.5 text-sm">
 <li>
 <Code>/agents/phantom/connectors/&lt;instance_id&gt;/&lt;slot&gt;</Code>{" "}
 &mdash; per-connector-instance secrets (xsiam{" "}
 <Code>apiToken</Code>, caldera{" "}
 <Code>redPassword</Code>, etc.)
 </li>
 <li>
 <Code>/agents/phantom/providers/&lt;instance_id&gt;/&lt;slot&gt;</Code>{" "}
 &mdash; model provider creds (vertex{" "}
 <Code>serviceAccountJson</Code>, gemini{" "}
 <Code>apiKey</Code>)
 </li>
 <li>
 <Code>/ui/auth/&lt;username&gt;/password_hash</Code>{" "}
 &mdash; operator UI password (PBKDF2-HMAC-SHA256
 envelope, set via <Code>/profile</Code>)
 </li>
 </ul>
 <p>
 The companion SQLite stores ({" "}
 <Code>instances.db</Code>,{" "}
 <Code>provider_instances.db</Code>) hold only{" "}
 <Term>references</Term> to these paths in their{" "}
 <Code>secrets_json</Code> columns &mdash; never values.
 Leaking those databases leaks no credential material.
 </p>
 </SubSection>

 <SubSection icon="security" title="API redaction">
 <p>
 <Code>GET /api/v1/instances/&lt;id&gt;</Code> returns the
 instance config but redacts secret fields as{" "}
 <Code>***</Code>. The redacted shape preserves field names
 so the UI knows which fields are populated without
 exposing values. Same redaction on{" "}
 <Code>GET /api/v1/providers/*</Code>.
 </p>
 </SubSection>

 <SubSection icon="loop" title="Rotation + audit">
 <p>
 Rotating a secret writes a new file at the same path,
 atomically (write to tmp + rename). There is no envelope
 history &mdash; the previous ciphertext is overwritten.
 Audit captures the fact of rotation as a{" "}
 <Code>secret:write target=&lt;path&gt;</Code> row;
 paths are logged, never values.
 </p>
 <p>
 Reads also audit (<Code>secret:read</Code>) so an operator
 can answer &quot;when did the agent last touch the xsiam
 webhook key?&quot; from{" "}
 <Code>/observability/events</Code>.
 </p>
 </SubSection>
 </Section>
);
}

function Approvals() {
 return (
 <Section id="approvals" icon="fact_check" title="Approvals & Tier System">
 <p>
 Which tools wait for a human is decided by one list: the bundle
 manifest&apos;s <Code>approvals.humanRequired</Code>. The embedded
 MCP reads it at boot and blocks a listed tool on the approvals
 bus; the chat route reads the same file through{" "}
 <Code>lib/approvals-config.ts</Code> (<Code>isToolGated</Code>,{" "}
 <Code>getApprovalGating</Code>) to render the inline card and to
 tell the model what to promise. A tool on the list blocks until
 an operator approves; a tool off the list runs at once.{" "}
 <strong>In this release the list is empty, so no tool is
 gated.</strong> The tiers below only classify the tools that are
 listed (the card&apos;s colour and the type-CONFIRM step); they
 do not gate anything by themselves.
 </p>
 <SubSection icon="layers" title="Tier definitions">
 <ul className="list-disc pl-5 space-y-1.5 text-sm">
 <li>
 <Term>Tier 1 — runs at once</Term>: read-only queries, log
 generation, non-destructive runs, and every tool the list does
 not name.
 </li>
 <li>
 <Term>Tier 2 — soft writes</Term>: config writes
 (jobs_create, personality_update, settings_update). Green card
 when the list names them.
 </li>
 <li>
 <Term>Tier 3 — destructive and credential</Term>: jobs_delete,
 skills_delete, personality_reset, settings_reset. Red banner
 when the list names them. Credential operations are not agent
 tools at all (see the credential guardrail).
 </li>
 </ul>
 </SubSection>
 <SubSection icon="rule" title="What the install reports about its own gate">
 <p>
 One reading of the list feeds every surface, so none of them
 can promise a card the gate will not show:
 </p>
 <ul className="list-disc pl-5 space-y-1.5 text-sm">
 <li>
 <Code>buildSystemPromptText(…, gatedTools)</Code> in{" "}
 <Code>lib/system-prompt.ts</Code>: an empty list renders an
 approval block saying that nothing is gated, no card appears and
 calls run at once (manual and bypass alike); a non-empty list
 renders the manual and bypass blocks naming exactly the listed
 tools. The action-policy <Code>approve-card</Code> cadence line
 says that no card appears when nothing is gated; the
 operator&apos;s cadence setting itself is not changed. An
 unreadable manifest passes <Code>undefined</Code> and keeps the
 generic wording.
 </li>
 <li>
 <Code>GET /api/agent/approvals/gating</Code> returns{" "}
 <Code>{`{gated, count, known}`}</Code> (Next.js route, session
 cookie, read-only). The chat-header chip reads{" "}
 <em>No approvals</em> with no Manual/Bypass menu when{" "}
 <Code>count</Code> is 0, and <Code>/approvals</Code> shows a
 notice.
 </li>
 <li>
 The tool docstrings the model reads say{" "}
 <em>Waits for approval when the install gates it</em>.
 </li>
 </ul>
 <p>
 Restoring the gate is a change to the bundle manifest, which
 ships inside the agent image: rename{" "}
 <Code>humanRequired__DISABLED</Code> back to{" "}
 <Code>humanRequired</Code> (the original 20 entries are kept
 under that name) and deploy the image. The MCP reads the list at
 boot and the chat route when its process starts; every surface
 above then follows with no further change. The approvals bus,
 the REST routes, the audit rows and the bypass plumbing stay
 wired whether or not any tool is listed.
 </p>
 </SubSection>
 <SubSection icon="alt_route" title="Gating logic">
 <Pre>{`// app/api/chat/route.ts (sketch)
const tier = approvalsConfig.tierFor(toolName);
if (tier === 1) {
  return executeTool(toolName, args);
}
const approvalId = await approvalQueue.enqueue({
  session, tool: toolName, args, tier,
});
sendEvent({ type: 'approval_required', approvalId });
const decision = await approvalQueue.awaitDecision(approvalId, 5*60_000);
if (decision === 'approved') return executeTool(toolName, args);
throw new ApprovalDeniedError(toolName, decision);`}</Pre>
 </SubSection>
 <SubSection icon="schedule" title="Timeout + history">
 <p>
 Pending approvals time out after 5 minutes server-side; the
 chat unblocks with an error. Resolved approvals stay in the{" "}
 <Code>approvals</Code> table indefinitely for audit. The
 sidebar count badge sums un-resolved entries.
 </p>
 </SubSection>
 <SubSection icon="layers_clear" title="Batch propose — one card for N actions">
 <p>
 When the agent has multiple gated actions to perform in one
 turn (&ldquo;schedule a daily sim for each of my 5 skills&rdquo;,
 &ldquo;delete these 3 jobs&rdquo;),{" "}
 <Code>agent_batch_propose(actions=[{`{tool, args}`}, ...])</Code>{" "}
 bundles N actions into ONE approval row. The card&apos;s UI
 shows the action list inline; on approve the executor flips
 the bypass contextvar and dispatches each action sequentially
 (audit-only, no further UI ceremony per action).
 </p>
 <p>
 Dispatch flows through the <Code>tool_dispatcher()</Code>{" "}
 singleton so connector tools (xsiam, caldera, web,
 cortex-content, …) reach the same fastmcp.Client path the
 job scheduler uses — preserving per-instance contextvar
 setup. Two loop-hazard exclusions:{" "}
 <Code>agent_batch_propose</Code> itself (no nesting) and{" "}
 <Code>approvals_resolve</Code> (logical loop). A third rule is
 the credential guardrail: an action naming any tool in{" "}
 <Code>CREDENTIAL_SIDE_TOOLS</Code> (<Code>providers_*</Code>,{" "}
 <Code>instances_*</Code>, <Code>api_keys_*</Code> writes) is
 refused before any card is shown, on both dispatch routes.
 Prometheus
 metrics:{" "}
 <Code>phantom_batch_proposals_total</Code>,{" "}
 <Code>phantom_batch_actions_total</Code>, and the{" "}
 <Code>phantom_batch_size</Code> histogram (buckets 1/2/3/5/10/25
 matching the eager 25-action cap).
 </p>
 </SubSection>
 </Section>
);
}

function ApiKeys() {
 return (
 <Section id="api-keys" icon="vpn_key" title="API Keys">
 <p>
 Operator-issued API keys gate programmatic access to the
 agent&apos;s <Code>/api/v1/*</Code> surface. They&apos;re the
 mechanism for automating job creation, exporting audit logs,
 or integrating Phantom with external dashboards.
 </p>
 <SubSection icon="database" title="Schema">
 <Pre>{`api_keys (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,            -- operator-chosen label
  hash          TEXT NOT NULL,            -- sha256(plaintext + per-deploy pepper)
  created_at    TEXT NOT NULL,
  last_used_at  TEXT,
  disabled      INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX idx_api_keys_hash ON api_keys(hash);`}</Pre>
 </SubSection>
 <SubSection icon="lock" title="Issuance + storage">
 <p>
 <Code>POST /api/v1/api-keys</Code> generates a 32-byte
 random value, computes <Code>sha256(value || pepper)</Code>,
 stores the hash, and returns the plaintext{" "}
 <em>once</em> in the response. The plaintext is never
 stored. Hash equality at lookup time is the entire auth
 check.
 </p>
 </SubSection>
 <SubSection icon="loop" title="Rotation + revocation">
 <p>
 Rotation = mint new + delete old (atomic). Revocation =
 set <Code>disabled = 1</Code>. Disabled keys are kept for
 audit; lookup matches both active and disabled rows but
 returns 401 on disabled.
 </p>
 </SubSection>
 <SubSection icon="warning" title="Why no encryption-at-rest">
 <p>
 The hash IS the at-rest representation; there is no plaintext
 to encrypt. Compromise of the SQLite file plus the per-deploy
 pepper would let an attacker brute-force trivially-named
 keys, but 32-byte random values resist offline brute force
 even with full pepper disclosure.
 </p>
 </SubSection>
 </Section>
);
}

// ─── Models & Providers ────────────────────────────────────────────

function ModelResolution() {
 return (
 <Section id="model-resolution" icon="psychology" title="Model Resolution">
 <p>
 Every chat turn picks one model. The pick respects four inputs
 in priority order; understanding the chain explains why the
 chosen model in the chat header sometimes differs from the
 default.
 </p>
 <SubSection icon="alt_route" title="Resolution chain">
 <ol className="list-decimal pl-5 space-y-1 text-sm">
 <li>
 <Term>Header dropdown</Term> — operator picked a model in
 the chat header. Wins everything.
 </li>
 <li>
 <Term>Session preference</Term> — set via{" "}
 <Code>/model &lt;name&gt;</Code> slash command. Persists
 in <Code>sessions.preferred_model</Code>.
 </li>
 <li>
 <Term>Workspace default</Term> — personality store key{" "}
 <Code>preferred_model</Code> for the active workspace.
 </li>
 <li>
 <Term>Bundle modelRequirements</Term> — declared in{" "}
 <Code>manifest.yaml</Code> (capability gates +{" "}
 <Code>preferFamily</Code>). The runtime picks the first
 available provider model satisfying the gates.
 </li>
 </ol>
 </SubSection>
 <SubSection icon="settings" title="Capability gates">
 <Pre>{`# manifest.yaml (excerpt)
modelRequirements:
  primary:
    kind: chat
    mustSupport: [streaming, tool_use]
    contextWindowMin: 100000
    preferFamily: [gemini-3, gemini-2.5, gpt-4o]
  fallback:
    kind: chat
    mustSupport: [streaming, tool_use]
    contextWindowMin: 32000`}</Pre>
 </SubSection>
 <SubSection icon="warning" title="Resolution failure modes">
 <p>
 If the resolved model isn&apos;t reachable (provider down,
 quota exhausted), the chat-route falls through to{" "}
 <Code>fallback</Code>. If both fail, the turn errors with a
 structured <Code>provider_unavailable</Code> response and the
 SSE stream emits a <Code>done</Code> event with{" "}
 <Code>error: true</Code>.
 </p>
 </SubSection>
 </Section>
);
}

function ProviderStore() {
 return (
 <Section id="provider-store" icon="outlet" title="Provider Store">
 <p>
 Providers are LLM-vendor configurations: Vertex AI (default),
 OpenAI (fallback), Anthropic (optional). Each provider has
 zero or more instances — a configured copy with credentials
 bound. The shape mirrors the connector model exactly.
 </p>
 <SubSection icon="dns" title="Default catalogue">
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <Term>vertex</Term> — Vertex AI on GCP. Reads service-account
 JSON from the secret store. Project + location are config
 fields. Default for chat.
 </li>
 <li>
 <Term>openai</Term> — fallback. Reads API key from secret
 store. Declared but disabled by default; operator enables
 by adding an instance.
 </li>
 <li>
 <Term>anthropic</Term> — optional. Same shape as openai.
 </li>
 </ul>
 </SubSection>
 <SubSection icon="link" title="Provider → Model link">
 <p>
 The <Code>/models</Code> page renders models grouped by
 provider. Each model card lists capability flags (streaming,
 tool_use), context window, and default-or-not. Clicking a
 model sets it as the workspace default. Provider availability
 is derived from instance presence — an instance-less provider
 shows greyed-out.
 </p>
 </SubSection>
 </Section>
);
}

// ─── Background & Async ────────────────────────────────────────────

function JobsSubsystem() {
 return (
 <Section id="jobs-subsystem" icon="schedule" title="Jobs Subsystem">
 <p>
 Jobs are recurring scheduled work — natural-language prompts that
 run through the same chat pipeline as interactive operator
 sessions, OR direct MCP tool invocations with explicit args. The
 subsystem owns a cron parser (<Code>croniter</Code>), a
 dispatcher, a SQLite-backed run-history table, and a scheduler
 thread that picks up due jobs.
 </p>

 <JobsLifecycle />
 <p className="text-xs text-on-surface-variant/70 italic mt-1">
 Two creation paths converge into the runtime store → cron loop
 ticks every minute → action discriminator dispatches to one of
 three executors → uniform outputs (audit row + hook fires +
 optional notification). The discriminator is the load-bearing
 abstraction: any new action type plugs in at that point without
 changing the surrounding lifecycle.
 </p>

 <SubSection icon="layers" title="Action types — exactly two">
 <p>
 The operator-facing model is two types and only two:{" "}
 <Code>prompt</Code> and <Code>tool_call</Code>.
 </p>
 <ul className="list-disc pl-5 space-y-1.5 text-sm">
 <li>
 <Term><Code>prompt</Code></Term> — body{" "}
 <Code>{`{type: "prompt", message}`}</Code>. The dispatcher
 POSTs to the agent&apos;s <Code>/api/chat</Code> endpoint
 with the message and an{" "}
 <Code>X-Phantom-Trigger: job:&lt;name&gt;</Code> header for
 audit attribution. Personality, memory tools, audit, and
 session persistence all apply — same pipeline as
 interactive chat. The chat handler creates a fresh{" "}
 <Code>session_id</Code> per fire.
 </li>
 <li>
 <Term><Code>tool_call</Code></Term> — body{" "}
 <Code>{`{type: "tool_call", name, args}`}</Code>.
 Dispatcher calls{" "}
 <Code>self._dispatcher(name, args)</Code> directly — no
 LLM, no chat handler. Best for log generation, recurring
 queries, anything where the args are known up-front and
 deterministic execution beats narrative.
 </li>
 </ul>
 </SubSection>

 <SubSection icon="database" title="Schema">
 <Pre>{`jobs (
  name              TEXT PRIMARY KEY,        -- 'daily-soc-coverage'
  id                TEXT,                    -- opaque UUID for stable URLs
  cron              TEXT NOT NULL,           -- '0 8 * * *'
  timezone          TEXT NOT NULL,           -- 'UTC' | 'Europe/Berlin'
  action_json       TEXT NOT NULL,           -- {type: "prompt"|"tool_call", ...}
  enabled           INTEGER NOT NULL DEFAULT 1,
  removed           INTEGER NOT NULL DEFAULT 0,
  source            TEXT NOT NULL DEFAULT 'manifest', -- manifest | runtime
  run_once          INTEGER NOT NULL DEFAULT 0,       -- auto-disable after first fire
  bypass_approvals  INTEGER NOT NULL DEFAULT 0,
  last_fired_at     TEXT,
  last_status       TEXT,                             -- success | failure | skipped
  last_error        TEXT,
  next_due_at       TEXT,
  registered_at     TEXT NOT NULL
);

job_runs (
  id           TEXT PRIMARY KEY,            -- run UUID
  job_name     TEXT NOT NULL,
  fired_at     TEXT NOT NULL,
  finished_at  TEXT,
  status       TEXT NOT NULL,               -- success | failure | skipped
  duration_ms  INTEGER,
  trigger      TEXT NOT NULL,               -- cron | manual | onboot
  result       TEXT,                         -- JSON-serialized model reply / tool result
  error        TEXT
);`}</Pre>
 </SubSection>

 <SubSection icon="alt_route" title="Provenance — manifest vs runtime">
 <ul className="list-disc pl-5 space-y-1.5 text-sm">
 <li>
 <Term>Manifest-declared</Term> (<Code>source=manifest</Code>) —
 listed in <Code>manifest.yaml:jobs[]</Code>. Reconciled at
 boot: any drift between the manifest and the runtime row is
 resolved IN FAVOR OF the manifest, so editing a manifest job
 and redeploying overwrites the runtime row. <Code>DELETE</Code>{" "}
 of a manifest job soft-marks <Code>removed=1</Code>; the next
 boot resurrects it.
 </li>
 <li>
 <Term>Runtime</Term> (<Code>source=runtime</Code>) — created
 via <Code>POST /api/v1/jobs</Code> (operator UI or API).
 Persists in the runtime DB and survives boot. The reconciler
 does not touch runtime-origin jobs even if names collide
 with manifest entries. <Code>DELETE</Code> hard-removes
 (row + run history).
 </li>
 </ul>
 </SubSection>

 <SubSection icon="schedule" title="Scheduler loop">
 <p>
 The <Code>CroniterJobScheduler</Code> spawns one background
 task at startup that ticks every <Code>max_sleep=30s</Code>.
 On each tick it loads enabled, non-removed jobs whose{" "}
 <Code>next_due_at</Code> is &lt;= now and fires them. After
 each fire it computes the next due time via{" "}
 <Code>croniter</Code> + the job&apos;s timezone.
 Concurrent runs of the same job are serialised (one in-flight
 at a time per job name) to avoid surprising duplicate side
 effects.
 </p>
 </SubSection>

 <SubSection icon="bolt" title="Run-now + run-once">
 <p>
 <Code>POST /api/v1/jobs/&lt;name&gt;/run</Code> bypasses the
 cron and enqueues immediately with{" "}
 <Code>trigger=manual</Code>. The audit row distinguishes
 manual from cron triggers; useful for replaying a failed
 nightly without waiting for the next cron tick.
 </p>
 <p>
 <Code>run_once=1</Code> on a job means &quot;auto-disable
 after first fire&quot; (success or failure). Set by the
 &quot;Run now&quot; and &quot;Run at &lt;datetime&gt;&quot;
 modes in the create form. The cron expression for those
 modes targets a specific minute; the flag prevents the
 same minute from re-firing the job in subsequent years.
 </p>
 </SubSection>

 <SubSection icon="security" title="Approval bypass per job">
 <p>
 The <Code>bypass_approvals</Code> column lets an operator
 mark a specific job as &quot;auto-approve any{" "}
 <Code>humanRequired</Code> tools the agent calls during this
 fire&quot;. Useful for trusted recurring jobs where every
 tool call would otherwise block on the operator. The
 dispatcher sends{" "}
 <Code>X-Phantom-Approval-Bypass: 1</Code> on the chat call;
 the MCP-side gate auto-approves with{" "}
 <Code>auto_approved=true</Code> in the audit row so post-hoc
 review surfaces what ran. Toggle from the kebab menu (Edit →
 &quot;Enable approval bypass&quot;) or via PATCH.
 </p>
 </SubSection>

 <SubSection icon="record_voice_over" title="Session approval mode + agent narration">
 <p>
 Per-job bypass (above) and per-session bypass share the same
 wire: <Code>X-Phantom-Approval-Bypass: 1</Code> on the chat
 call to the MCP. The per-session form is operator-driven from
 the chat header dropdown:{" "}
 <Code>session.metadata.approval_mode ∈ {`{`}manual,
 bypass{`}`}</Code>. The chat handler reads it at the start of
 each turn (30s server-side cache) and forwards the header
 when{" "}
 <Code>bypass</Code> is selected.
 </p>
 <p>
 The chat agent&apos;s system prompt must narrate the right
 expectation per mode: in <Code>manual</Code> mode the agent
 promises an approval card; in <Code>bypass</Code> mode the
 MCP gate auto-approves and never renders a card, so the
 agent warns the call will execute immediately.
 </p>
 <p>
 Fix shape:{" "}
 <Code>renderApprovalModeBlock(mode)</Code> in{" "}
 <Code>lib/system-prompt.ts</Code> emits a dedicated{" "}
 <Code>## CRITICAL - Approval mode for this session</Code>{" "}
 block with mode-specific narration guidance. Manual: promise
 the card. Bypass: warn the call will execute immediately.{" "}
 <Code>buildSystemPromptText</Code> accepts an{" "}
 <Code>approvalMode</Code> parameter and inserts the block
 between the persona/skills blocks and the cached TAIL — the
 TAIL stays cacheable, only the ~50-token approval-mode block
 varies turn to turn. <Code>callGemini</Code> threads the same
 value through every call site in a turn (initial, follow-up,
 budget-exhausted summary) so the narration is consistent
 across multi-tool conversations. The{" "}
 <Code>ApprovalMode = &apos;manual&apos; | &apos;bypass&apos;</Code>{" "}
 type union lives in <Code>lib/system-prompt.ts</Code> and is
 imported by the chat route — single source of truth.
 </p>
 <p>
 What the operator sees: in a bypass-mode session, the agent
 now says{" "}
 <em>
   &quot;I&apos;ll delete the job. Bypass mode is on, so this
   will execute immediately.&quot;
 </em>{" "}
 instead of the misleading approval-card promise. In manual
 mode the existing card-promising language is preserved
 unchanged. The MCP-side gate behavior didn&apos;t change in
 either mode — only what the agent SAYS about it.
 </p>
 </SubSection>

 <SubSection icon="import_export" title="Export + Import">
 <p>
 Two export shapes; both JSON. The envelope is{" "}
 <Code>{`{exported_at, schema_version: 1, job: {…}}`}</Code>;
 runs export adds <Code>runs: [...]</Code>. The{" "}
 <Code>job</Code> block is exactly the shape{" "}
 <Code>POST /api/v1/jobs</Code> accepts — runtime-only fields
 (<Code>id</Code>, <Code>last_fired_at</Code>,{" "}
 <Code>next_due_at</Code>, <Code>registered_at</Code>,{" "}
 <Code>source</Code>, <Code>run_count</Code>) are stripped so
 import is a clean round-trip. Run history is NOT carried
 across imports — the runs export is for forensic snapshots,
 not portable history.
 </p>
 </SubSection>
 <SubSection icon="rule" title="YAML load-issue surfacing">
 <p>
 The scheduler reconciles{" "}
 <Code>/app/data/jobs/*.yaml</Code> into SQLite at boot via{" "}
 <Code>load_yaml_jobs()</Code>. Per-file failures append to{" "}
 <Code>scheduler.yaml_load_issues: list[dict]</Code> with
 fields <Code>path</Code>, <Code>basename</Code>,{" "}
 <Code>error</Code>, <Code>mtime</Code>. ONE INFO summary at
 the end of boot:{" "}
 <Code>YAML mirror: N file(s) skipped due to load issues (GET
 /api/v1/jobs/yaml-issues for details)</Code>. Load issues
 belong in /observability + UI, not in docker compose logs.
 </p>
 <p>
 The bearer-auth endpoint{" "}
 <Code>GET /api/v1/jobs/yaml-issues</Code> returns the list
 read-only. The agent-side proxy at{" "}
 <Code>/api/agent/jobs/yaml-issues</Code> forwards
 browser-cookie sessions. The <Code>/jobs</Code> page polls
 it on render; when <Code>count &gt; 0</Code> a yellow
 banner appears above the summary cards with a collapsible
 details panel. No auto-quarantine, no auto-delete — the
 data files in <Code>/app/data/jobs/</Code> belong to the
 operator.
 </p>
 </SubSection>
 </Section>
);
}

function NotificationsFeed() {
 return (
 <Section id="notifications-feed" icon="notifications" title="Notifications Feed">
 <p>
 The notifications page is the platform&apos;s alert feed: job
 completions, failed scenarios, approval resolutions,
 configuration changes. It&apos;s an audit-log derivative,
 filtered to events with operator-visible severity.
 </p>
 <SubSection icon="filter_alt" title="What lands here">
 <ul className="list-disc pl-5 space-y-1 text-sm">
 <li>
 <Term>Jobs</Term> — runs that complete, fail, or are
 disabled. From <Code>job_run_complete</Code>,{" "}
 <Code>job_run_failed</Code>.
 </li>
 <li>
 <Term>Scenarios</Term> — long-running scenario workers
 that finish or error.
 </li>
 <li>
 <Term>Approvals</Term> — pending, granted, denied. From
 <Code>approval_*</Code> audit families.
 </li>
 <li>
 <Term>System</Term> — settings changes, secret rotations,
 MCP_TOKEN refresh.
 </li>
 </ul>
 </SubSection>
 <SubSection icon="check" title="Read state">
 <p>
 <Code>notification_reads</Code> table stores per-operator
 read state (id + read_at). Mark-read is optimistic in the UI
 and posts to{" "}
 <Code>POST /api/v1/notifications/&lt;id&gt;/read</Code>{" "}
 in the background. The sidebar badge sums un-read across
 all categories.
 </p>
 </SubSection>
 <SubSection icon="science" title="Why a derivative, not a separate table">
 <p>
 Treating the audit log as the universal queryable surface
 keeps notifications honest: anything an operator should see
 is already an audit row, so the notifications view is just a
 different filter on the same data. Adding a new notification
 source = adding an audit action and listing it in the
 derivative&apos;s allow-list.
 </p>
 </SubSection>
 </Section>
);
}

// ─── Operability: pipeline + logs/events/traces ────────────────────

function PipelineHealth() {
 return (
 <Section id="pipeline-health" icon="monitor_heart" title="Pipeline Health Probes">
 <p>
 The pipeline page is a live React Flow graph of every Phantom
 subsystem. Box borders flip green / amber / red based on health
 probes; edges pulse cyan when traffic flowed in the last 60
 seconds. The page is two data sources stitched in real time.
 </p>
 <SubSection icon="check_circle" title="Health probe machinery">
 <ul className="list-disc pl-5 space-y-1.5 text-sm">
 <li>
 <Term>Server-side fan-out</Term> —{" "}
 <Code>GET /api/agent/health</Code> probes each
 service-internal hostname (xlog{" "}
 <Code>/health</Code>, MCP <Code>/ping/</Code>, agent
 self-check, caldera root) from the agent backend. Returns
 a normalised <Code>{`{ name, http, latency_ms, ok }`}</Code>{" "}
 array.
 </li>
 <li>
 <Term>Client refresh</Term> — the page polls the endpoint
 every 5 seconds. SWR-style cache so transient probe blips
 don&apos;t flicker the graph.
 </li>
 <li>
 <Term>Why server-side</Term> — browsers can&apos;t resolve
 compose-internal hostnames like{" "}
 <Code>https://xlog:8000</Code>. Routing all probes through
 the agent backend solves that and gives one normalised
 contract.
 </li>
 </ul>
 </SubSection>
 <SubSection icon="bolt" title="Edge pulses from audit">
 <p>
 Each edge on the graph (e.g. mcp → caldera) maps to a
 substring of <Code>target</Code> in the audit log
 (<Code>tool:caldera.*</Code>). The page subscribes to recent
 audit rows; an edge pulses if matching events appeared in the
 last 60 seconds. Source of truth is the same audit log that
 backs <Code>/observability/events</Code>.
 </p>
 </SubSection>
 <SubSection icon="grid_view" title="Storage rollup">
 <p>
 The six SQLite stores (audit, memory, secrets, settings,
 sessions, jobs) are rendered as a sub-grid under the MCP
 node. They share MCP&apos;s probe status — if MCP is up the
 stores are reachable, if MCP is unreachable they can&apos;t
 be probed independently. This avoids a cascade of redundant
 red boxes when the cause is one upstream failure.
 </p>
 </SubSection>
 </Section>
);
}

function LogsEventsTraces() {
 return (
 <Section id="logs-events-traces" icon="stacked_line_chart" title="Logs / Events / Traces">
 <p>
 Three views over one underlying stream: the audit log.{" "}
 <Code>/observability/logs</Code> is a live SSE tail;{" "}
 <Code>/observability/events</Code> is a paginated audit
 surface;{" "}
 <Code>/observability/traces</Code> is the same data shaped
 as OpenTelemetry-style spans.
 </p>
 <SubSection icon="search" title="Lucene-light query bar">
 <p>
 Every observability page shares a query bar. It accepts{" "}
 <Code>key:value</Code> pairs,{" "}
 <Code>key:prefix*</Code> wildcards, and free-text. Six
 supported keys:
 </p>
 <Pre>{`actor:user:operator         // who triggered the event
action:tool_call            // what the event was
target:tool:xsiam.*         // wildcard prefix match
severity:error              // error / warn / info / debug
session:s_4k21m             // chat session id
job:weekly-coverage         // job name`}</Pre>
 <p>
 Implemented in{" "}
 <Code>lib/audit-query.ts:parseQuery</Code> →{" "}
 SQL <Code>WHERE</Code> fragment. Free-text terms run against
 a whole-row LIKE on the audit&apos;s{" "}
 <Code>metadata_json</Code> column.
 </p>
 </SubSection>
 <SubSection icon="speed" title="Live tail vs paginated">
 <p>
 <Term>Logs</Term> SSE-streams new audit rows as they land,
 capped at the latest 200 in memory. Useful when debugging
 &ldquo;why didn&apos;t this fire&rdquo; in real time.{" "}
 <Term>Events</Term> paginates 20 rows per page with
 jump-to-time; better for incident review and audit reads.
 </p>
 </SubSection>
 <SubSection icon="account_tree" title="Trace shape">
 <p>
 Spans are constructed from chat-turn audit rows: each turn
 is a parent span; its tool calls are child spans;
 connector calls are grandchildren. Stored alongside the
 audit log; survive container restarts. The traces page
 lets operators drill from a turn down to a hot tool call
 without leaving the UI.
 </p>
 </SubSection>
 <SubSection icon="speed" title="Prometheus metrics — registry + emission">
 <p>
 In-process Prometheus-format collector at{" "}
 <Code>usecase/metrics_registry.py</Code>. Three metric types:
 Counter (monotonic, labels supported), Gauge (settable scalar,
 labels supported), Histogram (bucketed observe(), exports
 <Code>_bucket</Code>/<Code>_sum</Code>/<Code>_count</Code>).
 The registry is a plain dict of name → typed metric; rendered
 as Prometheus 0.0.4 text exposition via{" "}
 <Code>format_prometheus()</Code> at{" "}
 <Code>GET /api/v1/metrics</Code>.
 </p>
 <p>
 Counters declared in{" "}
 <Code>manifest.observability.metrics[]</Code> (dotted names
 like <Code>phantom.simulations_total</Code>) are
 pre-registered at boot — Prometheus underscored form
 (<Code>phantom_simulations_total</Code>) appears in{" "}
 <Code>/api/v1/metrics</Code> as 0-valued counters so
 dashboards never see &ldquo;metric not found&rdquo; gaps in
 the warm-up window. Histograms and lazily-created metrics
 register on first emission with their own
 <Code> # HELP </Code>line distinguishing them from
 manifest-declared counters.
 </p>
 <p>
 Three batch-approval metrics:{" "}
 <Code>phantom_batch_proposals_total{`{approved=...}`}</Code>{" "}
 (counter; +1 per agent_batch_propose call),{" "}
 <Code>phantom_batch_actions_total{`{tool=...,result=...}`}</Code>{" "}
 (counter; +1 per action inside a batch, labels split per-tool
 reliability from per-tool volume), and the lazy-registered{" "}
 <Code>phantom_batch_size</Code> histogram with custom
 count-buckets (1, 2, 3, 5, 10, 25) matching the 25-action
 eager-validation cap. The emission helpers wrap every metric
 call in <Code>try/except</Code> — metrics failures NEVER
 affect the tool&apos;s primary path; an operator missing a
 datapoint is preferable to an operator missing a tool result.
 </p>
 </SubSection>
 </Section>
);
}

// ─── Layout primitives ────────────────────────────────────────────

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
 /** Optional anchor id — when set, the wrapper gets an id attribute so
  *  cross-references like `#hooks-transport-types` deep-link to this
  *  subsection. Sections without an id behave
  *  exactly as before. */
 id?: string;
 icon: string;
 title: string;
 children: React.ReactNode;
}) {
 return (
 <div id={id} className="space-y-2 pt-2 scroll-mt-20">
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
 <div className="rounded-xl p-4 space-y-2" style={glassStyle}>
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
 return <span className="font-semibold text-on-surface">{children}</span>;
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
