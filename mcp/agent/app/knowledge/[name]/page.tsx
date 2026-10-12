/**
 * KB detail page — two read-only tabs:
 *
 *   Entries     → browse of every doc in this KB
 *                 (no `content` field; opens a drawer for full body)
 *   Try search  → semantic-search playground with score + snippet
 *
 * The entry count shown is the KB's `total_count` from the API, the same
 * number the /knowledge index card shows. The list is fetched in pages until
 * everything is loaded (up to MAX_PAGES), so the in-page filter covers every
 * entry; if a KB ever exceeds that, the page says how many of the total are
 * loaded instead of presenting the loaded count as the total.
 *
 * Routing: phantom is single-tenant, so we don't have spark_ui's
 * `/w/{workspace}/...` prefix — KBs are global to this deployment.
 */

"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useMemo, useState } from "react";
import { MarkdownContent } from "@/components/markdown-content";

interface KbDoc {
  id: string;
  kb_name: string;
  doc_id: string;
  title: string | null;
  category: string | null;
  metadata: Record<string, unknown>;
  source_path: string | null;
  loaded_at: string;
  content?: string;
  score?: number;
}

interface DocsResponse {
  documents: KbDoc[];
  count: number;
  total_count?: number;
  has_more?: boolean;
}

const PAGE_SIZE = 500;
const MAX_PAGES = 20;

interface SearchResponse {
  results: KbDoc[];
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

type TabId = "entries" | "search";

export default function KbDetailPage({
  params,
}: {
  // Next.js 15 — params is a Promise
  params: Promise<{ name: string }>;
}) {
  const { name } = use(params);

  // Shared state
  const [tab, setTab] = useState<TabId>("entries");
  const [error, setError] = useState<string | null>(null);

  // Entries tab state
  const [docs, setDocs] = useState<KbDoc[]>([]);
  // Entries in the whole KB (unfiltered) and the category chips, both taken
  // from the unfiltered load so picking a category does not shrink them.
  const [kbTotal, setKbTotal] = useState<number | null>(null);
  const [allCategories, setAllCategories] = useState<string[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [filterText, setFilterText] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("");
  const [activeDoc, setActiveDoc] = useState<KbDoc | null>(null);
  const [activeDocLoading, setActiveDocLoading] = useState(false);

  // Search tab state
  const [searchQuery, setSearchQuery] = useState("");
  const [searchLimit, setSearchLimit] = useState(5);
  const [searchResults, setSearchResults] = useState<KbDoc[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchElapsedMs, setSearchElapsedMs] = useState<number | null>(null);

  const refreshDocs = useCallback(async () => {
    setLoadingDocs(true);
    setError(null);
    try {
      const loaded: KbDoc[] = [];
      let total = 0;
      for (let page = 0; page < MAX_PAGES; page++) {
        const params = new URLSearchParams({
          limit: String(PAGE_SIZE),
          offset: String(loaded.length),
        });
        if (categoryFilter) params.set("category", categoryFilter);
        const r = await fetch(
          `/api/agent/knowledge/${encodeURIComponent(name)}/docs?${params}`,
          { cache: "no-store" },
        );
        if (!r.ok) throw new Error(`fetch ${r.status}`);
        const data = (await r.json()) as DocsResponse;
        const batch = data.documents ?? [];
        loaded.push(...batch);
        total = data.total_count ?? loaded.length;
        if (!data.has_more || batch.length === 0) break;
      }
      setDocs(loaded);
      if (!categoryFilter) {
        setKbTotal(total);
        setAllCategories(
          [...new Set(loaded.map((d) => d.category).filter((c): c is string => !!c))].sort(),
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingDocs(false);
    }
  }, [name, categoryFilter]);

  useEffect(() => {
    void refreshDocs();
  }, [refreshDocs]);

  const openDoc = useCallback(
    async (doc: KbDoc) => {
      setActiveDoc(doc);
      // Browse-list responses don't include content; fetch full doc.
      if (doc.content !== undefined) return;
      setActiveDocLoading(true);
      try {
        const r = await fetch(
          `/api/agent/knowledge/${encodeURIComponent(name)}/docs/${encodeURIComponent(doc.doc_id)}`,
          { cache: "no-store" },
        );
        if (!r.ok) throw new Error(`fetch ${r.status}`);
        const data = (await r.json()) as { document: KbDoc };
        setActiveDoc(data.document);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setActiveDocLoading(false);
      }
    },
    [name],
  );

  const runSearch = useCallback(async () => {
    const q = searchQuery.trim();
    if (!q) return;
    setSearching(true);
    setError(null);
    setSearchElapsedMs(null);
    const t0 = performance.now();
    try {
      const r = await fetch(
        `/api/agent/knowledge/${encodeURIComponent(name)}/search`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: q, limit: searchLimit }),
        },
      );
      if (!r.ok) throw new Error(`search ${r.status}`);
      const data = (await r.json()) as SearchResponse;
      setSearchResults(data.results ?? []);
      setSearchElapsedMs(Math.round(performance.now() - t0));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSearching(false);
    }
  }, [name, searchQuery, searchLimit]);

  // Categories surface as filter chips, derived from the unfiltered load so
  // we don't need a separate /categories endpoint.
  const categories = allCategories;
  const entryTotal = kbTotal ?? docs.length;

  const filteredDocs = useMemo(() => {
    const f = filterText.trim().toLowerCase();
    if (!f) return docs;
    return docs.filter((d) =>
      [d.title ?? "", d.doc_id, d.category ?? "", JSON.stringify(d.metadata)]
        .some((s) => s.toLowerCase().includes(f)),
    );
  }, [docs, filterText]);

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-8 space-y-6">
        {/* Breadcrumb + header */}
        <div className="space-y-3">
          <Link
            href="/knowledge"
            className="inline-flex items-center gap-1 text-xs text-on-surface-variant/60 hover:text-on-surface transition-colors"
          >
            <span className="material-symbols-outlined text-base">
              arrow_back
            </span>
            Knowledge Bases
          </Link>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div
                className="w-11 h-11 rounded-xl flex items-center justify-center"
                style={{
                  background:
                    "linear-gradient(135deg, rgba(167, 200, 255, 0.2), rgba(25, 99, 179, 0.12))",
                  border: "0.5px solid rgba(167, 200, 255, 0.2)",
                }}
              >
                <span
                  className="material-symbols-outlined text-2xl text-primary"
                  style={{ fontVariationSettings: "'FILL' 1" }}
                >
                  library_books
                </span>
              </div>
              <div>
                <h1 className="font-mono text-xl font-bold text-on-surface">
                  {name}
                </h1>
                <p className="text-xs text-on-surface-variant/60 font-mono">
                  {entryTotal} {entryTotal === 1 ? "entry" : "entries"}
                  {" · "}embedded with text-embedding-004
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div
          className="rounded-2xl flex flex-wrap"
          style={{ ...glassStyle, padding: "4px" }}
        >
          <Tab
            id="entries"
            active={tab === "entries"}
            label="Entries"
            icon="list"
            onClick={() => setTab("entries")}
          />
          <Tab
            id="search"
            active={tab === "search"}
            label="Try search"
            icon="search"
            onClick={() => setTab("search")}
          />
        </div>

        {error ? (
          <div className="rounded-xl border border-error/30 bg-error/10 p-3 text-xs text-error">
            {error}
          </div>
        ) : null}

        {tab === "entries" ? (
          <div className="space-y-4">
            {/* Filter row */}
            <div
              className="rounded-2xl p-4 flex flex-wrap items-center gap-3"
              style={glassStyle}
            >
              <div className="flex-1 min-w-[240px] flex items-center gap-2">
                <span className="material-symbols-outlined text-base text-on-surface-variant/60">
                  filter_list
                </span>
                <input
                  value={filterText}
                  onChange={(e) => setFilterText(e.target.value)}
                  placeholder="Filter by title, id, category, metadata…"
                  className="flex-1 bg-transparent border-0 outline-0 text-sm text-on-surface placeholder:text-on-surface-variant/40"
                />
              </div>
              {categories.length > 0 ? (
                <div className="flex items-center gap-1 bg-surface-container-lowest/50 rounded-lg p-1 flex-wrap">
                  <button
                    onClick={() => setCategoryFilter("")}
                    className={
                      "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors capitalize " +
                      (categoryFilter === ""
                        ? "bg-primary-container text-on-primary-container"
                        : "text-on-surface-variant hover:text-on-surface")
                    }
                  >
                    All
                  </button>
                  {categories.map((c) => (
                    <button
                      key={c}
                      onClick={() => setCategoryFilter(c)}
                      className={
                        "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors " +
                        (categoryFilter === c
                          ? "bg-primary-container text-on-primary-container"
                          : "text-on-surface-variant hover:text-on-surface")
                      }
                    >
                      {c}
                    </button>
                  ))}
                </div>
              ) : null}
              <div className="text-xs text-on-surface-variant/60 font-mono">
                showing {filteredDocs.length} / {docs.length}
                {docs.length < (categoryFilter ? docs.length : entryTotal)
                  ? ` loaded (${entryTotal} in this KB)`
                  : ""}
              </div>
            </div>

            {/* Entry list */}
            {loadingDocs ? (
              <div className="text-center py-16 text-sm text-on-surface-variant/60">
                Loading…
              </div>
            ) : filteredDocs.length === 0 ? (
              <div className="text-center py-16 text-sm text-on-surface-variant/60">
                {docs.length === 0 ? "No entries in this KB." : "No entries match this filter."}
              </div>
            ) : (
              <div className="grid gap-2">
                {filteredDocs.map((doc) => (
                  <button
                    key={doc.id}
                    onClick={() => void openDoc(doc)}
                    className="rounded-xl p-4 flex items-start gap-4 text-left transition-all hover:scale-[1.005]"
                    style={glassStyle}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 mb-1 flex-wrap">
                        <span className="text-sm font-headline font-semibold text-on-surface">
                          {doc.title ?? doc.doc_id}
                        </span>
                        {doc.category ? (
                          <span
                            className="rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-on-surface-variant/80"
                            style={glassStyleSubtle}
                          >
                            {doc.category}
                          </span>
                        ) : null}
                      </div>
                      <div className="text-[11px] font-mono text-on-surface-variant/60">
                        {doc.doc_id}
                        {doc.source_path ? ` · ${doc.source_path}` : ""}
                      </div>
                    </div>
                    <span
                      className="material-symbols-outlined text-base text-on-surface-variant/40 shrink-0 self-center"
                      aria-hidden
                    >
                      chevron_right
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : null}

        {tab === "search" ? (
          <div className="space-y-4">
            <div className="rounded-2xl p-4 space-y-3" style={glassStyle}>
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-base text-on-surface-variant/60">
                  search
                </span>
                <input
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void runSearch();
                  }}
                  placeholder="Natural language: 'find C2 beaconing examples'"
                  className="flex-1 bg-transparent border-0 outline-0 text-sm text-on-surface placeholder:text-on-surface-variant/40"
                />
                <select
                  value={searchLimit}
                  onChange={(e) => setSearchLimit(Number(e.target.value))}
                  className="rounded-lg px-2 py-1 text-xs text-on-surface-variant"
                  style={glassStyleSubtle}
                >
                  {[3, 5, 10, 20].map((n) => (
                    <option key={n} value={n} className="bg-surface text-on-surface">
                      top {n}
                    </option>
                  ))}
                </select>
                <button
                  onClick={() => void runSearch()}
                  disabled={searching || !searchQuery.trim()}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-50"
                  style={glassStyleSubtle}
                >
                  {searching ? "Searching…" : "Search"}
                </button>
              </div>
              {searchElapsedMs !== null ? (
                <div className="text-[11px] font-mono text-on-surface-variant/60">
                  {searchResults.length} result(s) in {searchElapsedMs}ms ·
                  query embedded via text-embedding-004 · cosine similarity
                  ranked across all entries
                </div>
              ) : null}
            </div>

            {searchResults.length === 0 ? (
              <div className="text-center py-16 text-sm text-on-surface-variant/60">
                {searchQuery.trim()
                  ? searching
                    ? "Searching…"
                    : "No matches yet — run the query."
                  : "Type a natural-language query and press Enter."}
              </div>
            ) : (
              <div className="grid gap-2">
                {searchResults.map((doc) => (
                  <button
                    key={doc.id}
                    onClick={() => void openDoc(doc)}
                    className="rounded-xl p-4 flex items-start gap-4 text-left transition-all hover:scale-[1.005]"
                    style={glassStyle}
                  >
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-headline font-semibold text-on-surface">
                          {doc.title ?? doc.doc_id}
                        </span>
                        {doc.category ? (
                          <span
                            className="rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-on-surface-variant/80"
                            style={glassStyleSubtle}
                          >
                            {doc.category}
                          </span>
                        ) : null}
                        {typeof doc.score === "number" ? (
                          <span className="text-[10px] font-mono text-primary">
                            score {doc.score.toFixed(3)}
                          </span>
                        ) : null}
                      </div>
                      <div className="text-[11px] font-mono text-on-surface-variant/60">
                        {doc.doc_id}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : null}

        {/* Doc drawer */}
        {activeDoc ? (
          <div
            className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 backdrop-blur-sm p-4"
            onClick={() => setActiveDoc(null)}
            role="dialog"
            aria-modal
          >
            <div
              className="rounded-2xl w-full max-w-3xl max-h-[85vh] overflow-y-auto p-6 space-y-4"
              style={glassStyle}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-xs font-mono text-on-surface-variant/60 mb-1">
                    {activeDoc.doc_id}
                  </div>
                  <h2 className="text-lg font-headline font-bold text-on-surface">
                    {activeDoc.title ?? activeDoc.doc_id}
                  </h2>
                  <div className="flex items-center gap-2 flex-wrap mt-2">
                    {activeDoc.category ? (
                      <span
                        className="rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-on-surface-variant/80"
                        style={glassStyleSubtle}
                      >
                        {activeDoc.category}
                      </span>
                    ) : null}
                    {typeof activeDoc.score === "number" ? (
                      <span className="text-[10px] font-mono text-primary">
                        score {activeDoc.score.toFixed(3)}
                      </span>
                    ) : null}
                    <span className="text-[10px] font-mono text-on-surface-variant/50">
                      loaded {activeDoc.loaded_at}
                    </span>
                  </div>
                </div>
                <button
                  onClick={() => setActiveDoc(null)}
                  className="text-on-surface-variant hover:text-on-surface transition-colors"
                  aria-label="Close"
                >
                  <span className="material-symbols-outlined">close</span>
                </button>
              </div>

              {activeDocLoading ? (
                <div className="text-sm text-on-surface-variant/60">
                  Loading content…
                </div>
              ) : (
                // Shared MarkdownContent component, so chat
                // assistant messages render the same way, with
                // SQL/XQL syntax highlighting via Prism. See
                // components/markdown-content.tsx.
                <div
                  className="rounded-lg p-5 max-h-[50vh] overflow-y-auto"
                  style={glassStyleSubtle}
                >
                  <MarkdownContent>
                    {activeDoc.content ?? "(no content)"}
                  </MarkdownContent>
                </div>
              )}

              {activeDoc.metadata && Object.keys(activeDoc.metadata).length > 0 ? (
                <details className="text-xs">
                  <summary className="cursor-pointer text-on-surface-variant/60 hover:text-on-surface transition-colors">
                    metadata
                  </summary>
                  <pre
                    className="mt-2 overflow-auto rounded-lg p-3 text-[11px] font-mono text-on-surface-variant"
                    style={glassStyleSubtle}
                  >
                    {JSON.stringify(activeDoc.metadata, null, 2)}
                  </pre>
                </details>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Tab({
  active,
  label,
  icon,
  onClick,
}: {
  id: string;
  active: boolean;
  label: string;
  icon: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={
        "flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-medium transition-colors " +
        (active
          ? "bg-primary-container text-on-primary-container"
          : "text-on-surface-variant hover:text-on-surface")
      }
    >
      <span className="material-symbols-outlined text-base">{icon}</span>
      {label}
    </button>
  );
}
