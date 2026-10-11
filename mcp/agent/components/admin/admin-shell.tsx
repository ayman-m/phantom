/**
 * AdminShell — header + content scaffold reused by every admin
 * surface page (audit, jobs, memory, etc.). Operator-facing pages
 * have a consistent feel without each one re-inventing the layout.
 */

'use client';

import { ReactNode } from 'react';

interface AdminShellProps {
  title: string;
  subtitle?: string;
  toolbar?: ReactNode;
  children: ReactNode;
  error?: string | null;
}

export function AdminShell({
  title,
  subtitle,
  toolbar,
  children,
  error,
}: AdminShellProps) {
  return (
    <div className="mx-auto flex h-full min-h-0 w-full max-w-6xl flex-col gap-6 px-6 py-8">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-on-surface-variant/70">
            Phantom · Admin
          </p>
          <h1 className="text-3xl font-headline font-semibold text-on-surface md:text-4xl">
            {title}
          </h1>
          {subtitle ? (
            <p className="mt-1 text-sm text-on-surface-variant">{subtitle}</p>
          ) : null}
        </div>
        {toolbar ? (
          <div className="flex flex-wrap items-center gap-2">{toolbar}</div>
        ) : null}
      </header>

      {error ? (
        <div className="rounded-lg border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error}
        </div>
      ) : null}

      <div className="glass-panel flex-1 min-h-0 overflow-auto rounded-2xl p-5">
        {children}
      </div>
    </div>
  );
}
