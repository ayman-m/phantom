/**
 * Knowledge Bases — operator browser for the bundle's loaded KBs.
 *
 * Spec context: per spec.md §6.10, KBs are *read-only* at the agent
 * surface. Entries are added/removed by editing the bundle (under
 * `bundles/spark/kbs/<name>/entries/*.md`) and redeploying — the boot
 * loader reconciles. So this page is intentionally a *browser*, not
 * an editor: list KBs, drill into one, search semantically. That
 * authoring workflow is developer context and lives in the architecture
 * page (#knowledge-bases), not on this operator page. Import and
 * Settings tabs are added only when runtime CRUD ships.
 *
 * Phantom is single-tenant, so there is no workspace prefix.
 */

"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

interface KbSummary {
  name: string;
  doc_count: number;
  latest_loaded_at: string | null;
}

interface ListResponse {
  kbs: KbSummary[];
  count: number;
}

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

const glassStyleSubtle = {
  background: "rgba(20, 20, 45, 0.25)",
  backdropFilter: "blur(8px)",
  border: "0.5px solid rgba(140, 145, 157, 0.1)",
} as const;

function relativeAge(iso: string | null): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const seconds = Math.floor((Date.now() - t) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export default function KnowledgePage() {
  const [kbs, setKbs] = useState<KbSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch("/api/agent/knowledge", { cache: "no-store" });
      if (!r.ok) throw new Error(`fetch ${r.status}`);
      const data = (await r.json()) as ListResponse;
      setKbs(data.kbs ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-8 space-y-6">
        {/* Header — jobs-style (icon directly on bg, no bg box). */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <span className="material-symbols-outlined text-2xl text-primary">
                menu_book
              </span>
              <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
                Knowledge Bases
              </h1>
            </div>
            <p className="text-sm text-on-surface-variant ml-9">
              Curated reference content the agent uses to ground responses — semantically searchable.
            </p>
          </div>
          <button
            onClick={() => void refresh()}
            disabled={loading}
            className="glass-panel px-4 py-2 rounded-xl text-xs font-medium text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-base align-middle mr-1">
              refresh
            </span>
            Refresh
          </button>
        </div>

        {error ? (
          <div className="rounded-xl border border-error/30 bg-error/10 p-3 text-xs text-error">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="text-center py-16 text-sm text-on-surface-variant/60">
            Loading…
          </div>
        ) : kbs.length === 0 ? (
          <div
            className="rounded-2xl px-8 py-16 text-center text-sm text-on-surface-variant/70 space-y-2"
            style={glassStyle}
          >
            <div className="text-base font-headline text-on-surface">
              No knowledge bases loaded
            </div>
            <div>
              This install has no knowledge bases yet, or they are still
              loading. Refresh in a moment.
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {kbs.map((kb) => (
              <Link
                key={kb.name}
                href={`/knowledge/${encodeURIComponent(kb.name)}`}
                className="group rounded-2xl p-5 flex flex-col gap-3 transition-all hover:scale-[1.01]"
                style={glassStyle}
              >
                <div className="flex items-start gap-3">
                  <div
                    className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
                    style={{
                      background:
                        "linear-gradient(135deg, rgba(167, 200, 255, 0.18), rgba(25, 99, 179, 0.1))",
                      border: "0.5px solid rgba(167, 200, 255, 0.18)",
                    }}
                  >
                    <span
                      className="material-symbols-outlined text-lg text-primary"
                      style={{ fontVariationSettings: "'FILL' 1" }}
                    >
                      library_books
                    </span>
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="font-mono text-sm font-semibold text-on-surface truncate group-hover:text-primary transition-colors">
                      {kb.name}
                    </div>
                    <div className="text-[11px] text-on-surface-variant/60 font-mono mt-0.5">
                      {kb.doc_count} {kb.doc_count === 1 ? "entry" : "entries"}{" "}
                      · loaded {relativeAge(kb.latest_loaded_at)}
                    </div>
                  </div>
                  <span
                    className="material-symbols-outlined text-base text-on-surface-variant/40 group-hover:text-primary transition-colors"
                    aria-hidden
                  >
                    chevron_right
                  </span>
                </div>
                <div className="flex flex-wrap gap-1.5 pt-1">
                  <span
                    className="rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-on-surface-variant/80"
                    style={glassStyleSubtle}
                  >
                    read-only
                  </span>
                </div>
              </Link>
            ))}
          </div>
        )}

      </div>
    </div>
  );
}
