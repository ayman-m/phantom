"use client";

/**
 * /about/whats-new — full-page release-notes view for the running
 * version. Opened in a new browser tab from the sidebar's About menu.
 *
 * The matching entry in lib/release-notes.ts is rendered as the
 * primary card (highlighted) at the top, and any preceding releases
 * follow as context — operators upgrading from older
 * versions see the cumulative changelog without having to navigate
 * elsewhere.
 *
 * Falls back to "version unknown" if /api/agent/version isn't
 * reachable; in that case we render the latest known release as a
 * best-effort.
 */

import { useEffect, useState } from "react";
import {
  RELEASE_NOTES,
  findRelease,
  latestRelease,
} from "@/lib/release-notes";
import { ReleaseEntry } from "@/components/about/release-entry";

export default function WhatsNewPage() {
  const [version, setVersion] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/agent/version", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data?.version) setVersion(String(data.version));
      })
      .catch(() => {
        // Fall through to "unknown" — the page still renders the
        // latest release as a sensible default.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const current = version ? findRelease(version) : undefined;
  const fallback = latestRelease();
  const primary = current ?? fallback;

  // Earlier releases (in reverse chronological order, newest first) so
  // operators upgrading from a much older version see the full delta.
  const earlier = RELEASE_NOTES.filter((n) => n.version !== primary.version);

  return (
    <div className="p-8 max-w-3xl mx-auto space-y-6">
      <header>
        <p className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant mb-1">
          What&apos;s new in
        </p>
        <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
          Phantom v{version ?? "—"}
        </h1>
        {!current && version && (
          <p className="text-[12px] text-on-surface-variant mt-1">
            Dev build — release notes for v{version} are not yet committed.
            Showing the most recent published release as a fallback.
          </p>
        )}
      </header>

      <ReleaseEntry note={primary} highlight />

      {earlier.length > 0 && (
        <section className="space-y-4">
          <h2 className="font-headline text-sm font-bold uppercase tracking-wider text-on-surface-variant pt-4 border-t border-white/5">
            Earlier releases
          </h2>
          <div className="space-y-4">
            {earlier.map((note) => (
              <ReleaseEntry key={note.version} note={note} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
