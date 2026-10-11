"use client";

/**
 * /help/api — REST API documentation index.
 *
 * Sister page to /help (the journey catalog). Lists every endpoint in
 * lib/api-catalog.ts grouped by category, with method+path badges and
 * a one-line summary. Click into a card to land on /help/api/[id]
 * for the detail page (full schema + try-it-out form).
 *
 * Top-bar actions:
 *   - "Download OpenAPI" → /api/agent/openapi (JSON)
 *   - "Download YAML"    → /api/agent/openapi?format=yaml
 *   - "View raw spec"    → modal showing pretty-printed JSON
 *
 * Search filters by method, path, summary, or category.
 */

import Link from "next/link";
import { useMemo, useState } from "react";

import {
  API_ENDPOINTS,
  CATEGORY_META,
  searchEndpoints,
  type ApiCategory,
  type ApiEndpoint,
  type HttpMethod,
} from "@/lib/api-catalog";

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

const METHOD_COLOR: Record<HttpMethod, string> = {
  GET: "bg-secondary/15 text-secondary",
  POST: "bg-primary/15 text-primary",
  PUT: "bg-tertiary/15 text-tertiary",
  PATCH: "bg-tertiary/15 text-tertiary",
  DELETE: "bg-error/15 text-error",
};

const TIER_BADGE: Record<string, string> = {
  soft: "bg-tertiary/10 text-tertiary border-tertiary/30",
  destructive: "bg-error/10 text-error border-error/30",
  credential: "bg-error/15 text-error border-error/40",
};

export default function ApiCatalogPage() {
  const [query, setQuery] = useState("");
  const [activeCat, setActiveCat] = useState<ApiCategory | "all">("all");
  const [showSpecModal, setShowSpecModal] = useState(false);

  const filtered = useMemo(() => {
    let out = query ? searchEndpoints(query) : API_ENDPOINTS;
    if (activeCat !== "all") out = out.filter((e) => e.category === activeCat);
    return out;
  }, [query, activeCat]);

  const grouped = useMemo(() => {
    const map = new Map<ApiCategory, ApiEndpoint[]>();
    for (const e of filtered) {
      const list = map.get(e.category) ?? [];
      list.push(e);
      map.set(e.category, list);
    }
    return map;
  }, [filtered]);

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-8 space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-4">
            <div
              className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
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
                api
              </span>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <Link
                  href="/help"
                  className="text-xs text-on-surface-variant/60 hover:text-on-surface transition-colors"
                >
                  Help
                </Link>
                <span className="text-xs text-on-surface-variant/40">/</span>
                <span className="text-xs text-on-surface-variant">API</span>
              </div>
              <h1 className="text-xl font-headline font-bold text-on-surface mt-0.5">
                REST API Reference
              </h1>
              <p className="text-xs text-on-surface-variant/60 font-label mt-1 max-w-2xl">
                {API_ENDPOINTS.length} endpoints across {Object.keys(CATEGORY_META).length}{" "}
                categories. The browser proxies through{" "}
                <code className="font-mono">/api/agent/*</code> with auth attached
                server-side. Click any card for schema + a try-it-out form.
              </p>
            </div>
          </div>

          {/* OpenAPI actions — icon-only. Operator wanted YAML killed
              (JSON is the canonical format) and labels removed; the
              hover tooltips and aria-labels carry the full intent.
              The View action opens a modal with pretty-printed JSON;
              the Download action grabs the spec file. */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowSpecModal(true)}
              className="w-10 h-10 rounded-lg flex items-center justify-center text-on-surface-variant hover:text-on-surface transition-colors"
              style={glassStyle}
              title="View OpenAPI spec"
              aria-label="View OpenAPI spec"
            >
              <span className="material-symbols-outlined text-lg">
                visibility
              </span>
            </button>
            <a
              href="/api/agent/openapi"
              download="phantom-agent-openapi.json"
              className="w-10 h-10 rounded-lg flex items-center justify-center text-on-primary bg-primary hover:opacity-90 transition-opacity"
              title="Download OpenAPI JSON"
              aria-label="Download OpenAPI JSON"
            >
              <span className="material-symbols-outlined text-lg">
                file_download
              </span>
            </a>
          </div>
        </div>

        {/* Filter row */}
        <div className="rounded-2xl p-3 flex flex-wrap items-center gap-3" style={glassStyle}>
          <div className="flex-1 min-w-[260px] flex items-center gap-2 px-2">
            <span className="material-symbols-outlined text-base text-on-surface-variant/60">
              search
            </span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter by method, path, summary…"
              className="flex-1 bg-transparent border-0 outline-0 text-sm text-on-surface placeholder:text-on-surface-variant/40"
            />
          </div>
          <div className="flex items-center gap-1 bg-surface-container-lowest/50 rounded-lg p-1 flex-wrap">
            <button
              onClick={() => setActiveCat("all")}
              className={
                "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors " +
                (activeCat === "all"
                  ? "bg-primary-container text-on-primary-container"
                  : "text-on-surface-variant hover:text-on-surface")
              }
            >
              All ({API_ENDPOINTS.length})
            </button>
            {(Object.keys(CATEGORY_META) as ApiCategory[]).map((c) => {
              const count = API_ENDPOINTS.filter((e) => e.category === c).length;
              return (
                <button
                  key={c}
                  onClick={() => setActiveCat(c)}
                  className={
                    "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors capitalize flex items-center gap-1 " +
                    (activeCat === c
                      ? "bg-primary-container text-on-primary-container"
                      : "text-on-surface-variant hover:text-on-surface")
                  }
                >
                  <span className="material-symbols-outlined text-sm">
                    {CATEGORY_META[c].icon}
                  </span>
                  {CATEGORY_META[c].label} ({count})
                </button>
              );
            })}
          </div>
        </div>

        {/* Grouped endpoint cards */}
        {filtered.length === 0 ? (
          <div className="text-center py-16 text-sm text-on-surface-variant/60">
            No endpoints match your filter.
          </div>
        ) : (
          <div className="space-y-6">
            {(Array.from(grouped.entries()) as [ApiCategory, ApiEndpoint[]][]).map(
              ([cat, endpoints]) => (
                <div key={cat} className="space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-base text-on-surface-variant/70">
                      {CATEGORY_META[cat].icon}
                    </span>
                    <h2 className="text-sm font-headline font-bold text-on-surface uppercase tracking-wider">
                      {CATEGORY_META[cat].label}
                    </h2>
                    <span className="text-[11px] text-on-surface-variant/50 font-mono">
                      ({endpoints.length})
                    </span>
                  </div>
                  <p className="text-xs text-on-surface-variant/60 -mt-1">
                    {CATEGORY_META[cat].description}
                  </p>
                  <div className="grid gap-2">
                    {endpoints.map((e) => (
                      <Link
                        key={e.id}
                        href={`/help/api/${e.id}`}
                        className="rounded-xl p-4 flex items-start gap-3 transition-all hover:scale-[1.005]"
                        style={glassStyle}
                      >
                        <span
                          className={
                            "rounded-md px-2 py-0.5 text-[10px] font-mono font-bold uppercase tracking-wider shrink-0 mt-0.5 " +
                            METHOD_COLOR[e.method]
                          }
                        >
                          {e.method}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <code className="text-sm font-mono text-on-surface break-all">
                              {e.path}
                            </code>
                            {e.riskTier ? (
                              <span
                                className={
                                  "rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider border " +
                                  TIER_BADGE[e.riskTier]
                                }
                              >
                                {e.riskTier}
                              </span>
                            ) : null}
                          </div>
                          <p className="text-xs text-on-surface-variant/80 mt-1 line-clamp-2">
                            {e.summary}
                          </p>
                        </div>
                        <span
                          className="material-symbols-outlined text-base text-on-surface-variant/40 self-center shrink-0"
                          aria-hidden
                        >
                          chevron_right
                        </span>
                      </Link>
                    ))}
                  </div>
                </div>
              ),
            )}
          </div>
        )}
      </div>

      {/* OpenAPI viewer modal */}
      {showSpecModal ? <OpenApiModal onClose={() => setShowSpecModal(false)} /> : null}
    </div>
  );
}

function OpenApiModal({ onClose }: { onClose: () => void }) {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [format, setFormat] = useState<"json" | "yaml">("json");

  useMemo(() => {
    setLoading(true);
    setContent(null);
    fetch(`/api/agent/openapi?format=${format}`)
      .then((r) => r.text())
      .then((t) => {
        setContent(t);
        setLoading(false);
      })
      .catch((err) => {
        setContent(`/* failed to fetch spec: ${String(err)} */`);
        setLoading(false);
      });
  }, [format]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={onClose}
      role="dialog"
      aria-modal
    >
      <div
        className="rounded-2xl w-full max-w-5xl max-h-[85vh] overflow-hidden flex flex-col"
        style={glassStyle}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-on-surface/10">
          <div className="flex items-center gap-3">
            <span className="material-symbols-outlined text-xl text-primary">api</span>
            <h2 className="text-base font-headline font-bold text-on-surface">
              OpenAPI 3.0 Specification
            </h2>
            <div className="flex items-center gap-1 bg-surface-container-lowest/50 rounded-lg p-1">
              {(["json", "yaml"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setFormat(f)}
                  className={
                    "px-2.5 py-1 rounded-md text-[10px] font-medium uppercase tracking-wider transition-colors " +
                    (format === f
                      ? "bg-primary-container text-on-primary-container"
                      : "text-on-surface-variant hover:text-on-surface")
                  }
                >
                  {f}
                </button>
              ))}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-on-surface-variant hover:text-on-surface transition-colors"
            aria-label="Close"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>
        <div className="flex-1 overflow-auto px-6 py-4">
          {loading ? (
            <div className="text-sm text-on-surface-variant/60">Loading spec…</div>
          ) : (
            <pre
              className="rounded-lg p-4 text-xs font-mono whitespace-pre-wrap text-on-surface-variant"
              style={glassStyleSubtle}
            >
              {content}
            </pre>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-3 border-t border-on-surface/10">
          <button
            onClick={() => {
              if (content) navigator.clipboard.writeText(content);
            }}
            className="px-3 py-2 rounded-lg text-xs font-medium text-on-surface-variant hover:text-on-surface transition-colors"
            style={glassStyleSubtle}
          >
            <span className="material-symbols-outlined text-base align-middle mr-1">
              content_copy
            </span>
            Copy
          </button>
          <a
            href={`/api/agent/openapi?format=${format}`}
            download={`phantom-agent-openapi.${format}`}
            className="px-3 py-2 rounded-lg text-xs font-medium text-on-primary bg-primary hover:opacity-90 transition-opacity"
          >
            <span className="material-symbols-outlined text-base align-middle mr-1">
              download
            </span>
            Download
          </a>
        </div>
      </div>
    </div>
  );
}
