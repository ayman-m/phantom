/**
 * PageHeader — canonical page-title block.
 *
 * Standardizes the layout operators preferred (jobs-style):
 *   • Icon-on-the-left in primary color, NO background box
 *   • Title (font-headline, 3xl, on-surface)
 *   • Subtitle below, indented to align with title (ml-9)
 *   • Optional actions area on the right (Create button, etc.)
 *
 * Replaces a few different shapes that were sprinkled across pages
 * (some had a colored icon-box, some had a breadcrumb instead of an
 * icon, some had no subtitle). Server-component-safe — all rendering,
 * no hooks, no event handlers.
 *
 * Usage:
 *   <PageHeader
 *     icon="auto_awesome"
 *     title="Skills"
 *     subtitle="Manage skill definitions and context injection"
 *     actions={<Link href="/skills/new">Create</Link>}
 *   />
 */

import type { ReactNode } from "react";

export interface PageHeaderProps {
  icon: string;
  title: string;
  subtitle?: string;
  /** Right-aligned actions (button, dropdown, etc.). */
  actions?: ReactNode;
  /** Extra classes on the outer header element. */
  className?: string;
}

export function PageHeader({
  icon,
  title,
  subtitle,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <header className={`mb-8 ${className ?? ""}`}>
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-3 mb-1">
            <span className="material-symbols-outlined text-2xl text-primary">
              {icon}
            </span>
            <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
              {title}
            </h1>
          </div>
          {subtitle && (
            <p className="text-sm text-on-surface-variant ml-9">{subtitle}</p>
          )}
        </div>
        {actions && <div className="flex-shrink-0">{actions}</div>}
      </div>
    </header>
  );
}
