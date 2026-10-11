"use client";

/**
 * /about/history — full release-history timeline. Opened in a new
 * browser tab from the sidebar's About menu.
 *
 * Lists every entry in lib/release-notes.ts (newest first). The
 * running version's entry gets the "Running" badge so operators can
 * locate themselves on the timeline at a glance.
 */

import { useEffect, useState } from "react";
import { RELEASE_NOTES } from "@/lib/release-notes";
import { ReleaseEntry } from "@/components/about/release-entry";

export default function ReleaseHistoryPage() {
  const [version, setVersion] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/agent/version", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data?.version) setVersion(String(data.version));
      })
      .catch(() => {
        // Highlight nothing if version lookup fails — list still
        // renders, operators just lose the "you are here" anchor.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="p-8 max-w-3xl mx-auto space-y-6">
      <header>
        <p className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant mb-1">
          Phantom
        </p>
        <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
          Release history
        </h1>
        <p className="text-[12px] text-on-surface-variant mt-1">
          {RELEASE_NOTES.length} releases · newest first
          {version && (
            <>
              {" · running "}
              <span className="font-mono text-primary">v{version}</span>
            </>
          )}
        </p>
      </header>

      <div className="space-y-4">
        {RELEASE_NOTES.map((note) => (
          <ReleaseEntry
            key={note.version}
            note={note}
            highlight={note.version === version}
          />
        ))}
      </div>
    </div>
  );
}
