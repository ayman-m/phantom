"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useNotificationsStore } from "@/lib/stores/notifications";
import { useTheme } from "@/lib/use-theme";
import { VersionMenu } from "@/components/about/version-menu";

const SIDEBAR_COLLAPSED_KEY = "spark-sidebar-collapsed";

// ── Types ─────────────────────────────────────────────────────────────────────

interface NavItem {
  href: string;
  label: string;
  icon: string;
  badgeKey?: "pendingApprovals";
}

interface NavGroup {
  id: string;
  label: string;
  icon: string;
  defaultHref: string;
  children: NavItem[];
}

type NavEntry = NavItem | NavGroup;

function isGroup(entry: NavEntry): entry is NavGroup {
  return "children" in entry;
}

// ── Navigation Structure (Architecture-Aligned) ──────────────────────────────

// ── Phantom-tailored nav. Mirrors Spark's grouped collapsible sidebar
//    structure but points at the routes phantom actually ships. The
//    Spark workspace concepts (Platform, /w/<workspace>) and gateway-
//    specific surfaces (Identities, Routing, Venus) are dropped because
//    phantom is a single-tenant standalone agent — no api-gateway,
//    no multi-workspace, no test-channel proxy.
const navEntries: NavEntry[] = [
  {
    id: "command",
    label: "Command",
    icon: "terminal",
    defaultHref: "/",
    children: [
      // The chat-page sidebar is the single source of truth for
      // browsing/loading/exporting sessions, so there is no standalone
      // /sessions page.
      { href: "/", label: "Chat", icon: "chat_bubble" },
      { href: "/skills", label: "Skills", icon: "auto_awesome" },
      { href: "/agents", label: "Agents", icon: "groups" },
      { href: "/memory", label: "Memory", icon: "database" },
      { href: "/knowledge", label: "Knowledge", icon: "menu_book" },
      // The one sample company (people, hosts, networks) every generator draws from.
      { href: "/organization", label: "Organization", icon: "apartment" },
      { href: "/jobs", label: "Jobs", icon: "schedule" },
      { href: "/tasks", label: "Tasks", icon: "task_alt" },
      // /models + /providers live under Settings — they're
      // operator-once-and-rarely-touch admin surfaces, not day-to-day
      // command actions. The Command group is scoped to the things
      // an operator interacts with multiple times per session.
    ],
  },
  {
    id: "integration",
    label: "Integration",
    icon: "hub",
    defaultHref: "/connectors",
    children: [
      { href: "/connectors", label: "Connectors", icon: "cable" },
      // Marketplace Data Sources. A separate operator-facing surface
      // from /connectors: vendor schemas are a different concept from
      // per-instance connector containers, so they get their own
      // top-level page rather than a tab inside /connectors.
      // Drill-down is vendor → product/rule → dataset.
      { href: "/data-sources", label: "Data Sources", icon: "schema" },
      { href: "/approvals", label: "Approvals", icon: "fact_check", badgeKey: "pendingApprovals" },
      // /notifications intentionally NOT listed here — it's promoted
      // to a footer-level standalone link below (cross-cutting bell
      // icon) so it surfaces from every page, not just the Integration
      // group. Listing it in both places gave operators the impression
      // of two separate destinations.
      { href: "/api-keys", label: "API Keys", icon: "vpn_key" },
      // Filesystem-discovered plugin tree. Distinct
      // from the entry-point distributable plugin catalog at
      // /observability/plugins — these are operator-owned drop-in
      // directories at bundles/spark/plugins/<vendor>/ that contribute
      // skills, scenarios, memory seeds, and agent definitions via a
      // manifest.yaml.
      { href: "/plugins", label: "Plugins", icon: "extension" },
      // Operator-managed log forwarding targets (syslog, webhook,
      // XSIAM HTTP Collector, Splunk HEC). CreateDataWorker references
      // destinations by id.
      { href: "/log-destinations", label: "Log Destinations", icon: "cloud_upload" },
    ],
  },
  {
    id: "observability",
    label: "Observability",
    icon: "monitoring",
    defaultHref: "/observability",
    children: [
      { href: "/observability", label: "Overview", icon: "space_dashboard" },
      // Services lives under /settings (single source of truth) —
      // /observability/services was a redundant lighter probe page.
      { href: "/observability/metrics", label: "Metrics", icon: "monitoring" },
      { href: "/observability/traces", label: "Traces", icon: "timeline" },
      { href: "/observability/logs", label: "Logs", icon: "terminal" },
      { href: "/observability/events", label: "Events", icon: "policy" },
      { href: "/observability/runtime-events", label: "Runtime events", icon: "bolt" },
      // Detections inventory + MITRE coverage: the non-chat path to
      // browse the rule inventory and coverage (the chat-driven
      // detections_list tool covers the same data).
      { href: "/observability/detections", label: "Detections", icon: "radar" },
      { href: "/observability/connectors", label: "Connectors", icon: "settings_input_component" },
      { href: "/observability/pipeline", label: "Pipeline", icon: "account_tree" },
      { href: "/observability/cost", label: "Cost", icon: "payments" },
      { href: "/observability/bench", label: "Bench", icon: "speed" },
      // Entry-point distributable plugin catalog with install/uninstall
      // lifecycle and plugin-hook handler discovery. Distinct from
      // /plugins (filesystem-discovered) in the Integration group above.
      { href: "/observability/plugins", label: "Plugins", icon: "deployed_code" },
      { href: "/activity", label: "Live activity", icon: "history_toggle_off" },
    ],
  },
  {
    id: "settings",
    label: "Settings",
    icon: "settings",
    defaultHref: "/settings",
    children: [
      { href: "/settings", label: "Services", icon: "tune" },
      { href: "/models", label: "Models", icon: "psychology" },
      { href: "/providers", label: "Providers", icon: "key" },
      // Hook management surface. Hosts builtin hook configs and
      // plugin-handler transport selection. This is the only nav entry
      // to /settings/hooks.
      { href: "/settings/hooks", label: "Hooks", icon: "webhook" },
      { href: "/settings/personality", label: "Personality", icon: "psychology_alt" },
      { href: "/settings/backup-restore", label: "Backup & Restore", icon: "save" },
    ],
  },
  // Learn — operator-facing reference. Drives the /help journey
  // catalog: every Phantom capability has a reproducible walkthrough
  // here. New journeys land in mcp/agent/lib/journeys.ts and surface
  // automatically without further wiring.
  {
    id: "learn",
    label: "Learn",
    icon: "school",
    defaultHref: "/help",
    children: [
      // /help is the comprehensive feature documentation hub with sticky
      // sidebar nav (the conceptual-guide content is inline).
      // /help/journeys is the catalog of task-oriented walkthroughs.
      { href: "/help", label: "Help & Capabilities", icon: "help_outline" },
      { href: "/help/journeys", label: "User Journeys", icon: "tour" },
      { href: "/help/api", label: "REST API", icon: "api" },
    ],
  },
];

// ── Component ─────────────────────────────────────────────────────────────────

export function Sidebar() {
  const pathname = usePathname();
  const pendingApprovals = useNotificationsStore((s) => s.pendingApprovals);
  const [collapsed, setCollapsed] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [activeGroupId, setActiveGroupId] = useState<string | null>(null);

  const isWorkspaceRoute = pathname.startsWith("/w/");

  // Determine which group contains the current route
  function findActiveGroupId(): string | null {
    for (const entry of navEntries) {
      if (isGroup(entry)) {
        if (entry.children.some((child) => isActiveHref(child.href))) {
          return entry.id;
        }
      }
    }
    return null;
  }

  function isActiveHref(href: string): boolean {
    if (href === "/") return pathname === "/";
    // Exact match for routes that have sibling sub-routes to prevent double-highlight.
    if (href === "/agents") {
      return pathname === "/agents" || (pathname.startsWith("/agents/") && !pathname.startsWith("/agents/teams"));
    }
    if (href === "/agents/teams") {
      return pathname === "/agents/teams" || pathname.startsWith("/agents/teams/");
    }
    // Command sub-routes: exact match to avoid /command/chat highlighting /command/chatbot etc.
    if (href.startsWith("/command/")) return pathname === href || pathname.startsWith(href + "/");
    if (href.startsWith("/settings/")) return pathname === href || pathname.startsWith(href + "/");
    if (href === "/settings") return pathname === "/settings";
    if (href === "/monitor") return pathname === "/monitor";
    if (href === "/platform") return pathname === "/platform";
    if (href.startsWith("/platform/")) return pathname === href || pathname.startsWith(href + "/");
    // Observability section needs the same exact-vs-prefix pair as
    // /command/ and /settings/ above. Without it, /observability
    // (Overview) falls through to the catchall `startsWith(href)`
    // below and matches /observability/traces, /observability/logs,
    // etc. — Overview ends up highlighted alongside whatever
    // sub-page you're actually on.
    if (href === "/observability") return pathname === "/observability";
    if (href.startsWith("/observability/")) {
      return pathname === href || pathname.startsWith(href + "/");
    }
    // /help has the same shape (index page + sub-pages like /help/api,
    // /help/[journeyId]). Same rule pair.
    if (href === "/help") return pathname === "/help";
    if (href.startsWith("/help/")) {
      return pathname === href || pathname.startsWith(href + "/");
    }
    return pathname.startsWith(href);
  }

  // Load persisted state on mount
  useEffect(() => {
    const storedCollapsed = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    if (storedCollapsed === "true") {
      setCollapsed(true);
    }
    setMounted(true);
  }, []);

  // Auto-collapse when entering workspace routes (transient — don't persist)
  useEffect(() => {
    if (isWorkspaceRoute && !collapsed) {
      setCollapsed(true);
      // Fire event so AppShell picks up the change, but do NOT write to localStorage
      window.dispatchEvent(new Event("sidebar-toggle"));
    }
    // Restore user preference when leaving workspace routes
    if (!isWorkspaceRoute) {
      const stored = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
      const shouldBeCollapsed = stored === "true";
      if (collapsed !== shouldBeCollapsed) {
        setCollapsed(shouldBeCollapsed);
        window.dispatchEvent(new Event("sidebar-toggle"));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isWorkspaceRoute]);

  // Auto-expand the correct group when route changes (accordion: only one open)
  useEffect(() => {
    const groupId = findActiveGroupId();
    if (groupId) {
      setActiveGroupId(groupId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next));
      window.dispatchEvent(new Event("sidebar-toggle"));
      return next;
    });
  }, []);

  const toggleGroup = useCallback((groupId: string) => {
    setActiveGroupId((prev) => (prev === groupId ? null : groupId));
  }, []);

  const badgeValues: Record<string, number> = {
    pendingApprovals,
  };

  return (
    <aside
      className={cn(
        // The .sidebar-shell utility resolves bg / border / shadow
        // through CSS vars defined in globals.css for both themes —
        // see :root + [data-theme="light"] for the values, so the
        // sidebar follows the active theme.
        "sidebar-shell h-screen fixed left-0 top-0 flex flex-col z-50 py-6 transition-all duration-300 flex-shrink-0 backdrop-blur-xl",
        collapsed ? "w-16 px-2" : "w-64 px-4",
        !mounted && "w-64 px-4",
      )}
    >
      {/* Brand Header */}
      <div className={cn("mb-6 flex items-center", collapsed ? "justify-center" : "px-2 gap-3")}>
        <div className="w-12 h-12 flex items-center justify-center flex-shrink-0">
          <PhantomLogo size={44} />
        </div>
        {!collapsed && (
          <h1 className="text-2xl font-bold tracking-tighter sidebar-text font-headline">
            Phantom
          </h1>
        )}
      </div>

      {/* Toggle Button */}
      <button
        type="button"
        onClick={toggleCollapsed}
        className="absolute top-6 -right-3 w-6 h-6 rounded-full bg-surface-container-high border border-white/10 flex items-center justify-center text-on-surface-variant hover:text-on-surface hover:bg-white/10 transition-colors z-50"
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
      >
        <span className="material-symbols-outlined text-sm">
          {collapsed ? "chevron_right" : "chevron_left"}
        </span>
      </button>

      {/* Primary Nav */}
      <nav aria-label="Primary" className="flex-1 space-y-1 overflow-y-auto custom-scrollbar">
        {navEntries.map((entry) => {
          if (isGroup(entry)) {
            const isExpanded = activeGroupId === entry.id;
            const groupHasActiveChild = entry.children.some((c) => isActiveHref(c.href));

            return (
              <NavGroupSection
                key={entry.id}
                group={entry}
                collapsed={collapsed}
                expanded={isExpanded}
                isActive={isActiveHref}
                isGroupActive={groupHasActiveChild}
                onToggle={() => toggleGroup(entry.id)}
                badgeValues={badgeValues}
              />
            );
          }

          return (
            <NavLink
              key={entry.href}
              item={entry}
              collapsed={collapsed}
              active={isActiveHref(entry.href)}
              badgeCount={entry.badgeKey ? badgeValues[entry.badgeKey] : 0}
            />
          );
        })}
      </nav>

      {/* Footer Nav */}
      <div className="mt-auto pt-4 space-y-1 border-t border-white/5">
        {/* Observability and Help are top-level groups in the main nav
            above (OBSERVABILITY group, LEARN group), so they are not
            repeated here. The footer is reserved for cross-cutting
            utilities (notifications + theme toggle) and the user
            profile. */}
        <FooterLink
          href="/notifications"
          icon="notifications"
          label="Notifications"
          collapsed={collapsed}
          active={isActiveHref("/notifications")}
          showDot
        />

        <ThemeToggle collapsed={collapsed} />

        {/* About menu — small icon button that opens a popover
            floating to the right of the sidebar with About / What's
            new / Release history items. Each item opens the About
            modal with the matching tab. Cortex XSIAM uses the same
            pattern (popover anchored next to the user profile). */}
        <VersionMenu collapsed={collapsed} />

        {/* User Profile */}
        <Link
          href="/profile"
          className={cn(
            "flex items-center gap-3 mt-2 rounded-xl border transition-all",
            collapsed ? "px-0 py-3 justify-center" : "px-3 py-3",
            isActiveHref("/profile")
              ? "bg-secondary-container/20 border-secondary/30"
              : "bg-white/5 border-white/10 hover:bg-white/10",
          )}
          title={collapsed ? "Operator" : undefined}
        >
          <div className="w-8 h-8 rounded-full overflow-hidden bg-primary-container flex items-center justify-center flex-shrink-0">
            <span className="material-symbols-outlined text-sm text-on-primary-container">
              person
            </span>
          </div>
          {!collapsed && (
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium sidebar-text truncate">Operator</p>
              <p className="text-[10px] sidebar-text-muted truncate uppercase tracking-tighter">
                Platform Admin
              </p>
            </div>
          )}
        </Link>
      </div>
    </aside>
  );
}

// ── Collapsible Nav Group (Accordion) ─────────────────────────────────────────

function NavGroupSection({
  group,
  collapsed,
  expanded,
  isActive,
  isGroupActive,
  onToggle,
  badgeValues,
}: {
  group: NavGroup;
  collapsed: boolean;
  expanded: boolean;
  isActive: (href: string) => boolean;
  isGroupActive: boolean;
  onToggle: () => void;
  badgeValues: Record<string, number>;
}) {
  if (collapsed) {
    return (
      <Link
        href={group.defaultHref}
        className={cn(
          "flex items-center justify-center rounded-lg transition-all duration-300 sidebar-text px-0 py-2.5",
          isGroupActive
            ? "bg-secondary-container/30 text-secondary"
            : "hover:bg-white/5 sidebar-text-muted",
        )}
        title={group.label}
      >
        <span className="material-symbols-outlined text-lg flex-shrink-0">{group.icon}</span>
      </Link>
    );
  }

  return (
    <div className="space-y-0.5">
      {/* Group Header */}
      <button
        type="button"
        onClick={onToggle}
        className={cn(
          "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200",
          isGroupActive
            ? "text-secondary"
            : "sidebar-text sidebar-hover",
        )}
      >
        <span className="material-symbols-outlined text-lg flex-shrink-0">{group.icon}</span>
        <span className="text-xs font-bold uppercase tracking-widest flex-1 text-left">
          {group.label}
        </span>
        <span
          className={cn(
            "material-symbols-outlined text-sm transition-transform duration-200",
            expanded && "rotate-180",
          )}
        >
          expand_more
        </span>
      </button>

      {/* Children (animated) */}
      <div
        className={cn(
          "overflow-hidden transition-all duration-200",
          expanded ? "max-h-96 opacity-100" : "max-h-0 opacity-0",
        )}
      >
        <div className="pl-3 space-y-0.5">
          {group.children.map((child) => {
            const active = isActive(child.href);
            const badgeCount = child.badgeKey ? badgeValues[child.badgeKey] : 0;

            return (
              <NavLink
                key={child.href}
                item={child}
                collapsed={false}
                active={active}
                badgeCount={badgeCount}
                isChild
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── Single Nav Link ───────────────────────────────────────────────────────────

function NavLink({
  item,
  collapsed,
  active,
  badgeCount,
  isChild = false,
}: {
  item: NavItem;
  collapsed: boolean;
  active: boolean;
  badgeCount: number;
  isChild?: boolean;
}) {
  return (
    <Link
      href={item.href}
      className={cn(
        "flex items-center gap-3 rounded-lg transition-all duration-200 group relative",
        collapsed ? "px-0 py-2.5 justify-center" : isChild ? "px-3 py-2" : "px-3 py-2.5",
        active
          ? isChild
            ? "bg-secondary-container/25 text-secondary border-l-2 border-secondary ml-1 font-bold"
            : "bg-gradient-to-r from-[#0077aa] to-[#00f5ff] text-[#050914] shadow-[0_0_15px_rgba(0,245,255,0.3)] active:scale-95 font-semibold"
          : isChild
            ? "sidebar-text sidebar-hover"
            : "sidebar-text sidebar-hover",
      )}
      aria-current={active ? "page" : undefined}
      title={collapsed ? item.label : undefined}
    >
      <span
        className={cn(
          "material-symbols-outlined flex-shrink-0",
          isChild ? "text-base" : "text-lg",
        )}
      >
        {item.icon}
      </span>
      {!collapsed && (
        <span className={cn("font-medium", isChild ? "text-xs" : "text-sm")}>
          {item.label}
        </span>
      )}
      {!collapsed && badgeCount > 0 && (
        <span className="ml-auto bg-tertiary-container text-on-tertiary-container text-[10px] px-1.5 py-0.5 rounded-full font-bold">
          {badgeCount}
        </span>
      )}
      {collapsed && badgeCount > 0 && (
        <span className="absolute top-0 right-0 w-2 h-2 bg-tertiary rounded-full" />
      )}
    </Link>
  );
}

// ── Footer Link ───────────────────────────────────────────────────────────────

/** Pill-shaped theme switcher — sun ↔ moon thumb slides between two
 *  ends. Persists to localStorage via useTheme. The actual color
 *  remapping for light theme is implemented separately; this wires
 *  the preference + writes `data-theme` on <html> so the CSS-var
 *  cascade can take over once the tokens are remapped. Until then,
 *  flipping the toggle persists the choice but the dark navy renders
 *  unchanged — no broken light state. */
function ThemeToggle({ collapsed }: { collapsed: boolean }) {
  const { theme, toggle, hydrated } = useTheme();
  const isDark = theme === "dark";

  if (collapsed) {
    // Collapsed sidebar: render as an icon-only button to match the
    // FooterLink density. Click toggles, hover shows current state.
    return (
      <button
        type="button"
        onClick={toggle}
        title={isDark ? "Switch to light theme" : "Switch to dark theme"}
        aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
        className="flex items-center justify-center w-full px-0 py-2.5 rounded-lg sidebar-text hover:bg-white/5 transition-all"
      >
        <span className="material-symbols-outlined text-lg">
          {!hydrated ? "dark_mode" : isDark ? "dark_mode" : "light_mode"}
        </span>
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={toggle}
      title={isDark ? "Switch to light theme" : "Switch to dark theme"}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      aria-pressed={!isDark}
      className="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg sidebar-text hover:bg-white/5 transition-all"
    >
      <span className="material-symbols-outlined text-lg flex-shrink-0">
        {!hydrated ? "dark_mode" : isDark ? "dark_mode" : "light_mode"}
      </span>
      <span className="text-sm font-medium flex-1 text-left">
        {isDark ? "Dark" : "Light"} theme
      </span>
      {/* Pill switch — sun on the left, moon on the right; thumb slides
          based on isDark. Static-but-correct render before hydration:
          stays in the dark position until localStorage is read. */}
      <span
        className={cn(
          "relative inline-flex w-9 h-5 items-center rounded-full border transition-colors",
          isDark
            ? "bg-primary-container/30 border-primary/30"
            : "bg-tertiary-container/30 border-tertiary/30",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform",
            isDark ? "translate-x-0.5" : "translate-x-[18px]",
          )}
        />
      </span>
    </button>
  );
}

function FooterLink({
  href,
  icon,
  label,
  collapsed,
  active,
  showDot = false,
}: {
  href: string;
  icon: string;
  label: string;
  collapsed: boolean;
  active: boolean;
  showDot?: boolean;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-3 rounded-lg transition-all duration-300 relative",
        collapsed ? "px-0 py-2.5 justify-center" : "px-3 py-2.5",
        active
          ? "bg-secondary-container/25 text-secondary font-bold"
          : "sidebar-text sidebar-hover",
      )}
      aria-current={active ? "page" : undefined}
      title={collapsed ? label : undefined}
    >
      <span className="material-symbols-outlined text-lg flex-shrink-0">{icon}</span>
      {!collapsed && <span className="text-sm font-medium">{label}</span>}
      {showDot && (
        <span className={cn(
          // The dot's ring matches the sidebar bg so it reads as
          // "punched out of the sidebar surface". `currentColor` would
          // pick up the parent text color (wrong tint); we use the
          // sidebar's bg gradient via a CSS-var-driven solid stand-in
          // (--m3-surface-container) which approximates the navy in
          // dark mode and the off-white in light mode.
          "absolute w-2 h-2 bg-error rounded-full border-2 border-surface-container",
          collapsed ? "top-1.5 right-1.5" : "top-2.5 left-6",
        )} />
      )}
    </Link>
  );
}

// ── Phantom Logo ────────────────────────────────────────────────────────────
//
// The official Phantom mark lives at logos/phantom.svg in the repo root,
// already shipped to mcp/agent/public/logo.svg. Render it as an <img>
// rather than re-inlining the SVG — single source of truth, edit the file
// in /public to update the look across every call site (sidebar header,
// chat empty-state hero, /memory, /settings/personality).
//
// CSS animations defined inside the SVG (the `pipelineFlow` keyframe and
// `.facet-1` … `.facet-4` selectors with staggered 1s delays) run when
// the file is loaded as `<img src=…>` — the browser parses the SVG's
// inner `<style>` element and fires the animations. The `animate` prop
// is preserved for callers that want a static logo (passes through to
// disable the SVG's animation via a `data-animate=false` attribute that
// the SVG could opt into; today the SVG always animates, so the flag is
// effectively ignored — kept for API stability with the previous inline
// implementation).
//
// Note: an `<img>` element doesn't accept className-driven SVG animation
// like an inlined element would; the animation lives inside the SVG file
// itself, which is the right place for it.

// eslint-disable-next-line @next/next/no-img-element
export function PhantomLogo({ size = 32, animate = true }: { size?: number; animate?: boolean }) {
  return (
    /* eslint-disable-next-line @next/next/no-img-element */
    <img
      src="/logo.svg"
      alt="Phantom logo"
      width={size}
      height={size}
      data-animate={animate}
      style={{ display: "block" }}
    />
  );
}

/**
 * Backwards-compatibility re-export. The verbatim Spark port left
 * `SparkLogo` imported from a few call sites; alias it to PhantomLogo
 * so we don't have to chase down every reference. New code should
 * import `PhantomLogo` directly.
 */
export const SparkLogo = PhantomLogo;

/** Returns the current sidebar width class for layout consumers. */
export function useSidebarCollapsed(): boolean {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    if (stored === "true") {
      setCollapsed(true);
    }

    function handleStorage(e: StorageEvent) {
      if (e.key === SIDEBAR_COLLAPSED_KEY) {
        setCollapsed(e.newValue === "true");
      }
    }

    window.addEventListener("storage", handleStorage);

    function handleCustom() {
      const current = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
      setCollapsed(current === "true");
    }

    window.addEventListener("sidebar-toggle", handleCustom);

    return () => {
      window.removeEventListener("storage", handleStorage);
      window.removeEventListener("sidebar-toggle", handleCustom);
    };
  }, []);

  return collapsed;
}
