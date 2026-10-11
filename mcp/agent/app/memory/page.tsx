"use client";

import { useCallback, useEffect, useState } from "react";

interface MemoryRow {
  id: string;
  key: string;
  value: string;
  scope: string;
  created_at: string;
  updated_at: string;
  ttl_seconds: number | null;
  meta: Record<string, unknown>;
  score?: number;
  /**
   * True when the row was promoted into
   * the result set by the FTS5 keyword index,
   * vs by pure embedding similarity. The badge tells the operator
   * "this row matched on a literal token" — useful when checking
   * why a result surfaced.
   *
   * The MCP-side memory_store.search() will populate this when the
   * FTS hybrid path promotes a row. Older response shapes
   * leave it undefined; the UI hides the badge cleanly in that case.
   */
  fts_promoted?: boolean;
}

interface ListResponse {
  memories: MemoryRow[];
  count: number;
}

interface SearchResponse {
  results: MemoryRow[];
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

const SCOPES = ["agent", "session", "user", "system"] as const;
type Scope = (typeof SCOPES)[number];

/**
 * Render the row's age relative to "now",
 * with a colored bar that visually maps to the temporal-decay
 * impact on the row's ranking score. Three buckets:
 *   < 7 days    fresh    (green)
 *   < 30 days   recent   (amber)
 *   ≥ 30 days   old      (rose)
 *
 * Doesn't try to compute the exact decay factor (that depends on
 * the lambda the search call used, which isn't in the response
 * shape). The buckets are rough but match the operator's mental
 * model: "this row was written days ago / weeks ago / over a
 * month ago."
 */
function ageDescriptor(iso: string): {
  label: string;
  bucket: "fresh" | "recent" | "old";
  bar: string;
  fg: string;
} {
  const ts = Date.parse(iso);
  if (!Number.isFinite(ts)) {
    return {
      label: "—",
      bucket: "old",
      bar: "rgba(140, 145, 157, 0.2)",
      fg: "text-on-surface-variant/40",
    };
  }
  const days = Math.max(0, (Date.now() - ts) / 86400000);
  let label: string;
  if (days < 1) {
    label = "today";
  } else if (days < 2) {
    label = "1d ago";
  } else if (days < 30) {
    label = `${Math.round(days)}d ago`;
  } else if (days < 365) {
    label = `${Math.round(days / 30)}mo ago`;
  } else {
    label = `${(days / 365).toFixed(1)}y ago`;
  }
  if (days < 7) {
    return {
      label,
      bucket: "fresh",
      bar: "var(--m3-secondary, #4ade80)",
      fg: "text-secondary",
    };
  }
  if (days < 30) {
    return {
      label,
      bucket: "recent",
      bar: "var(--m3-tertiary, #fbbc30)",
      fg: "text-tertiary",
    };
  }
  return {
    label,
    bucket: "old",
    bar: "rgba(255, 180, 171, 0.6)",
    fg: "text-error/80",
  };
}

/** Per-query advanced controls. */
interface AdvancedSearchState {
  /** Visible / hidden via the Advanced disclosure. */
  open: boolean;
  /** Maximal-marginal-relevance lambda override for THIS query.
   *  null = use the server's configured default (operator-tuned knob). */
  mmrLambda: number | null;
  /** Temporal-decay lambda override for THIS query. null = use
   *  server default. */
  temporalDecayLambda: number | null;
}

const ADVANCED_DEFAULT: AdvancedSearchState = {
  open: false,
  mmrLambda: null,
  temporalDecayLambda: null,
};

export default function MemoryPage() {
  const [scope, setScope] = useState<Scope>("agent");
  const [query, setQuery] = useState("");
  const [memories, setMemories] = useState<MemoryRow[]>([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [advanced, setAdvanced] = useState<AdvancedSearchState>(ADVANCED_DEFAULT);

  // List all memories in the active scope.
  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(
        `/api/agent/memory?scope=${encodeURIComponent(scope)}&limit=100`,
        { cache: "no-store" },
      );
      if (!r.ok) throw new Error(`memory fetch ${r.status}`);
      const data = (await r.json()) as ListResponse;
      setMemories(data.memories ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [scope]);

  // Semantic search via embedding similarity.
  const search = useCallback(async () => {
    const q = query.trim();
    if (!q) {
      void refresh();
      return;
    }
    setSearching(true);
    setError(null);
    try {
      // Only include the lambda overrides when
      // the operator dialed them; sending undefined lets the
      // memory_store fall back to the operator's configured defaults
      // (or the source-level fallback if none are set).
      const body: Record<string, unknown> = { query: q, scope, limit: 50 };
      if (advanced.mmrLambda != null) body.mmr_lambda = advanced.mmrLambda;
      if (advanced.temporalDecayLambda != null) {
        body.temporal_decay_lambda = advanced.temporalDecayLambda;
      }
      const r = await fetch("/api/agent/memory/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(`search ${r.status}`);
      const data = (await r.json()) as SearchResponse;
      setMemories(data.results ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSearching(false);
    }
  }, [query, scope, refresh, advanced.mmrLambda, advanced.temporalDecayLambda]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleDelete = useCallback(
    async (key: string) => {
      if (!confirm(`Delete memory key "${key}" from scope "${scope}"?`)) return;
      try {
        const r = await fetch(
          `/api/agent/memory/${encodeURIComponent(key)}?scope=${encodeURIComponent(scope)}`,
          { method: "DELETE" },
        );
        if (!r.ok) throw new Error(`delete ${r.status}`);
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [scope, refresh],
  );

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-8 space-y-6">
        {/* Page Header — jobs-style (icon directly on bg, no bg box).
            Replaces the colored gradient-box wrapper that boxed the
            database icon. Same visual rhythm as /jobs and /skills. */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <span className="material-symbols-outlined text-2xl text-primary">
                database
              </span>
              <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
                Memory
              </h1>
            </div>
            <p className="text-sm text-on-surface-variant ml-9">
              Semantic memory store — vector-indexed key/value entries scoped per{" "}
              <code className="font-mono">agent | session | user | system</code>.
            </p>
          </div>
          <button
            onClick={() => void refresh()}
            disabled={loading}
            className="glass-panel px-4 py-2 rounded-xl text-xs font-medium text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-base align-middle mr-1">refresh</span>
            Refresh
          </button>
        </div>

        <div className="rounded-2xl p-4 flex flex-wrap items-center gap-3" style={glassStyle}>
          <div className="flex items-center gap-1 bg-surface-container-lowest/50 rounded-lg p-1">
            {SCOPES.map((s) => (
              <button
                key={s}
                onClick={() => setScope(s)}
                className={
                  "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors capitalize " +
                  (scope === s
                    ? "bg-primary-container text-on-primary-container"
                    : "text-on-surface-variant hover:text-on-surface")
                }
              >
                {s}
              </button>
            ))}
          </div>

          <div className="flex-1 min-w-[240px] flex items-center gap-2">
            <span className="material-symbols-outlined text-base text-on-surface-variant/60">search</span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void search();
              }}
              placeholder="Semantic search across this scope…"
              className="flex-1 bg-transparent border-0 outline-0 text-sm text-on-surface placeholder:text-on-surface-variant/40"
            />
            <button
              onClick={() => void search()}
              disabled={searching}
              className="px-3 py-1.5 rounded-lg text-xs font-medium text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-50"
              style={glassStyleSubtle}
            >
              {searching ? "Searching…" : "Search"}
            </button>
          </div>

          <div className="text-xs text-on-surface-variant/60 font-mono">
            {memories.length} entr{memories.length === 1 ? "y" : "ies"}
          </div>
        </div>

        {/* Advanced disclosure with per-query
            lambda overrides. Operator can dial down MMR (favor diversity)
            or boost temporal decay (push old entries out) for the next
            search. Resets to "use server defaults" each time the
            disclosure closes — overrides are intentionally
            single-query, not sticky, so the operator doesn't
            accidentally leave a tuning experiment running. */}
        <div className="rounded-2xl px-4 py-3" style={glassStyle}>
          <button
            type="button"
            onClick={() =>
              setAdvanced((prev) => ({
                ...prev,
                open: !prev.open,
                // Closing resets the overrides so the next search
                // uses server defaults again.
                ...(prev.open
                  ? { mmrLambda: null, temporalDecayLambda: null }
                  : {}),
              }))
            }
            className="flex items-center gap-2 text-xs text-on-surface-variant hover:text-on-surface transition-colors w-full"
            aria-expanded={advanced.open}
          >
            <span
              className="material-symbols-outlined text-base"
              aria-hidden="true"
            >
              {advanced.open ? "expand_less" : "tune"}
            </span>
            <span className="font-label uppercase tracking-wider">
              Advanced search controls
            </span>
            {!advanced.open &&
              (advanced.mmrLambda != null ||
                advanced.temporalDecayLambda != null) && (
                <span className="text-[10px] text-tertiary font-mono">
                  overrides set
                </span>
              )}
            <span className="ml-auto text-[10px] text-on-surface-variant/40 font-label">
              Single-query • Resets on close
            </span>
          </button>

          {advanced.open && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3 pt-3 border-t border-white/5">
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-label text-on-surface-variant/80">
                    MMR λ override
                  </label>
                  <span className="text-xs font-mono text-on-surface-variant/70">
                    {advanced.mmrLambda != null
                      ? advanced.mmrLambda.toFixed(2)
                      : "default"}
                  </span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={advanced.mmrLambda ?? 0.7}
                  onChange={(e) =>
                    setAdvanced((prev) => ({
                      ...prev,
                      mmrLambda: Number(e.target.value),
                    }))
                  }
                  className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
                  aria-label="MMR lambda override"
                  style={{
                    background: `linear-gradient(to right, #a7c8ff ${(advanced.mmrLambda ?? 0.7) * 100}%, rgba(140, 145, 157, 0.15) ${(advanced.mmrLambda ?? 0.7) * 100}%)`,
                    accentColor: "#a7c8ff",
                  }}
                />
                <p className="text-[10px] text-on-surface-variant/60 leading-tight">
                  1.0 = pure relevance, 0.0 = pure diversity. Server default
                  ≈ 0.7.
                </p>
              </div>

              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-label text-on-surface-variant/80">
                    Temporal decay λ override
                  </label>
                  <span className="text-xs font-mono text-on-surface-variant/70">
                    {advanced.temporalDecayLambda != null
                      ? advanced.temporalDecayLambda.toFixed(3)
                      : "default"}
                  </span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={0.05}
                  step={0.001}
                  value={advanced.temporalDecayLambda ?? 0.01}
                  onChange={(e) =>
                    setAdvanced((prev) => ({
                      ...prev,
                      temporalDecayLambda: Number(e.target.value),
                    }))
                  }
                  className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
                  aria-label="Temporal decay lambda override"
                  style={{
                    background: `linear-gradient(to right, #fbbc30 ${((advanced.temporalDecayLambda ?? 0.01) / 0.05) * 100}%, rgba(140, 145, 157, 0.15) ${((advanced.temporalDecayLambda ?? 0.01) / 0.05) * 100}%)`,
                    accentColor: "#fbbc30",
                  }}
                />
                <p className="text-[10px] text-on-surface-variant/60 leading-tight">
                  Higher = old rows lose more score. 0.0 disables decay.
                </p>
              </div>
            </div>
          )}
        </div>

        {error ? (
          <div className="rounded-xl border border-error/30 bg-error/10 p-3 text-xs text-error">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="text-center py-16 text-sm text-on-surface-variant/60">Loading…</div>
        ) : memories.length === 0 ? (
          <div className="text-center py-16 text-sm text-on-surface-variant/60">
            No memories in scope <code className="font-mono">{scope}</code>.
            {query.trim()
              ? " Try a different query or scope."
              : " The agent will write here as it captures notes."}
          </div>
        ) : (
          <div className="grid gap-3">
            {memories.map((m) => (
              <div key={m.id} className="rounded-2xl p-5 flex flex-col gap-3" style={glassStyle}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span className="font-mono text-sm font-semibold text-primary">{m.key}</span>
                      <span
                        className="rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider"
                        style={glassStyleSubtle}
                      >
                        {m.scope}
                      </span>
                      {typeof m.score === "number" ? (
                        <span className="text-[10px] font-mono text-on-surface-variant/60">
                          score {m.score.toFixed(3)}
                        </span>
                      ) : null}
                      {/* FTS-promoted indicator.
                          When the search promoted this row via the
                          FTS5 hybrid path (literal-token
                          match) instead of pure embedding similarity,
                          this badge tells the operator "this matched
                          on a keyword". Hidden when the field is
                          undefined (server didn't surface it). */}
                      {m.fts_promoted && (
                        <span
                          className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider bg-tertiary/15 text-tertiary"
                          title="Promoted by FTS5 keyword index, not pure embedding similarity"
                        >
                          <span
                            className="material-symbols-outlined text-[12px]"
                            aria-hidden="true"
                          >
                            search
                          </span>
                          FTS hit
                        </span>
                      )}
                      {/* Age + decay indicator.
                          Bucketed (fresh / recent / old) with a small
                          colored bar so the operator sees at a glance
                          how aged the row is and how much temporal
                          decay would have shaved off its score. */}
                      {(() => {
                        const age = ageDescriptor(m.created_at);
                        const widthPct =
                          age.bucket === "fresh"
                            ? 95
                            : age.bucket === "recent"
                              ? 55
                              : 20;
                        return (
                          <span
                            className={`inline-flex items-center gap-1.5 text-[10px] font-mono ${age.fg}`}
                            title={`${age.label} (created ${m.created_at})`}
                          >
                            <span
                              className="block w-8 h-1 rounded-full overflow-hidden"
                              style={{ background: "rgba(140, 145, 157, 0.15)" }}
                              aria-hidden="true"
                            >
                              <span
                                className="block h-full rounded-full"
                                style={{
                                  width: `${widthPct}%`,
                                  background: age.bar,
                                }}
                              />
                            </span>
                            {age.label}
                          </span>
                        );
                      })()}
                    </div>
                    <div className="text-xs text-on-surface-variant/60 font-mono">
                      {m.created_at}
                      {m.updated_at && m.updated_at !== m.created_at
                        ? ` · updated ${m.updated_at}`
                        : ""}
                      {m.ttl_seconds ? ` · ttl ${m.ttl_seconds}s` : ""}
                    </div>
                  </div>
                  <button
                    onClick={() => void handleDelete(m.key)}
                    className="opacity-60 hover:opacity-100 hover:text-error text-on-surface-variant transition-opacity"
                    aria-label={`Delete ${m.key}`}
                  >
                    <span className="material-symbols-outlined text-lg">delete</span>
                  </button>
                </div>

                <pre className="whitespace-pre-wrap text-sm text-on-surface font-body leading-relaxed">
                  {m.value}
                </pre>

                {m.meta && Object.keys(m.meta).length > 0 ? (
                  <details className="text-xs">
                    <summary className="cursor-pointer text-on-surface-variant/60 hover:text-on-surface transition-colors">
                      meta
                    </summary>
                    <pre
                      className="mt-1 overflow-auto rounded-lg p-2 text-[11px] font-mono text-on-surface-variant"
                      style={glassStyleSubtle}
                    >
                      {JSON.stringify(m.meta, null, 2)}
                    </pre>
                  </details>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
