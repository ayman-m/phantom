"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

/**
 * The 6 Observability tabs, rendered as a horizontal tab bar in the
 * shared observability layout. Each tab is technically a Next.js route
 * (so it's deep-linkable, shareable, and refresh-safe) but the layout
 * + shared header + tab bar make it feel like a single page to the
 * user. One sidebar entry (in the footer) → one visual page → six
 * tabs that switch the content area underneath.
 *
 * Keep the href + label + icon in sync with the routes under
 * `app/observability/` — adding a new tab means: add an entry here AND
 * create the matching `page.tsx`.
 */
const TABS: Array<{ href: string; label: string; icon: string }> = [
  { href: "/observability", label: "Overview", icon: "dashboard" },
  // Services lives under /settings (single source of truth).
  { href: "/observability/traces", label: "Traces", icon: "timeline" },
  { href: "/observability/logs", label: "Logs", icon: "terminal" },
  { href: "/observability/metrics", label: "Metrics", icon: "monitoring" },
  {
    href: "/observability/pipeline",
    label: "Pipeline Health",
    icon: "settings_input_component",
  },
];

/**
 * Determine whether a tab is the active one based on the current URL
 * pathname. The Overview tab is special-cased: it should only match
 * the exact `/observability` path, otherwise it would light up for
 * every sub-route too (because they all start with `/observability`).
 * Every other tab uses a prefix match so nested routes like a future
 * `/observability/traces/[traceId]` still highlight "Traces".
 */
function isTabActive(tabHref: string, pathname: string): boolean {
  if (tabHref === "/observability") {
    return pathname === "/observability";
  }
  return pathname === tabHref || pathname.startsWith(tabHref + "/");
}

export function ObservabilityTabBar() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Observability tabs"
      className="mb-8 border-b border-white/10"
    >
      <ul className="flex flex-wrap items-end gap-1 -mb-px">
        {TABS.map((tab) => {
          const active = isTabActive(tab.href, pathname ?? "/observability");
          return (
            <li key={tab.href}>
              <Link
                href={tab.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors",
                  "border-b-2 -mb-[2px]",
                  active
                    ? "text-secondary border-secondary bg-secondary-container/15"
                    : "text-on-surface-variant border-transparent hover:text-on-surface hover:border-white/20 hover:bg-white/5",
                )}
              >
                <span
                  aria-hidden="true"
                  className="material-symbols-outlined text-lg"
                >
                  {tab.icon}
                </span>
                <span className="font-headline">{tab.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
