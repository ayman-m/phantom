"use client";

import { useCallback, useEffect, useState } from "react";

// ── Types ───────────────────────────────────────────────────────────────────
//
// Mirrors the wire shape produced by bundles/spark/mcp/src/usecase/api_keys.py
// (`SqliteApiKeyStore.ApiKey.to_dict()`). Anything the backend doesn't
// store (workspaces, expiration windows, permission tiers, request-rate
// telemetry) is intentionally absent here — earlier revisions of this page
// invented all four and the resulting UI misled operators into thinking the
// platform tracked them.

interface ApiKey {
  id: string;
  label: string;
  scopes: string[];
  created_at: string;
  created_by: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
}

type PanelView = "create" | "detail" | null;

// ── Scope Catalog ───────────────────────────────────────────────────────────
//
// Sourced directly from the docstring at the top of usecase/api_keys.py.
// Scopes are advisory at the storage layer — the auth middleware compares
// the verifying key's scope list against the route's required scope and
// 401s on miss. "*" is the superset (no narrowing).

const SCOPE_CATALOG: {
  key: string;
  label: string;
  description: string;
}[] = [
  {
    key: "audit:read",
    label: "Audit (read)",
    description: "GET /api/v1/audit* — read the running event log.",
  },
  {
    key: "settings:read",
    label: "Settings (read)",
    description: "GET /api/v1/settings — read operator preferences.",
  },
  {
    key: "settings:write",
    label: "Settings (write)",
    description: "PUT /api/v1/settings — mutate operator preferences.",
  },
  {
    key: "approvals:resolve",
    label: "Approvals (resolve)",
    description: "Resolve pending approval requests on behalf of the operator.",
  },
  {
    key: "tools:call",
    label: "Tool dispatch",
    description: "JSON-RPC tool dispatch (read-only tools by default).",
  },
  {
    key: "agent:read",
    label: "Agent API (read)",
    description:
      "GET /api/chat + /api/agent/* reads — programmatic read access to the agent surface.",
  },
  {
    key: "agent:write",
    label: "Agent API (read + write)",
    description:
      "/api/chat (run a turn) + /api/agent/* reads & mutations. Credential routes stay session-only.",
  },
  {
    key: "agent:*",
    label: "Agent API (full)",
    description:
      "Full non-credential agent API. providers / instances / api-keys remain session-only.",
  },
  {
    key: "*",
    label: "Full access (admin)",
    description: "Superset — no scope narrowing. Equivalent to MCP_TOKEN.",
  },
];

// ── Style Constants ─────────────────────────────────────────────────────────

const glassPanel: React.CSSProperties = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(20px)",
  border: "1px solid var(--color-outline-variant)",
};

// Solid, theme-aware surface (the var routes through [data-theme="light"]) for
// the create/detail slide-overs — was a hardcoded dark navy that ignored the
// theme toggle.
const panelStyle: React.CSSProperties = {
  background: "var(--m3-surface-container-low)",
  backdropFilter: "blur(40px)",
  borderLeft: "1px solid var(--color-outline-variant)",
};

// ── Helpers ─────────────────────────────────────────────────────────────────

function statusOf(key: ApiKey): "active" | "revoked" {
  return key.revoked_at ? "revoked" : "active";
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

function formatRelative(iso: string | null): string {
  if (!iso) return "Never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const diffSec = Math.floor((Date.now() - then) / 1000);
  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}

function redactedPrefix(key: ApiKey): string {
  // Backend stores only sha256(<secret>); after creation we have no
  // way to reconstitute the secret portion of the bearer token, so
  // the listing shows the structurally-identifiable prefix only.
  return `phantom_ak_${key.id}_${"•".repeat(8)}`;
}

function mostRecentLastUsed(keys: ApiKey[]): string {
  // Aggregate "most recently used across any key" — surfaces the
  // fact that someone is actively hitting the API surface, or
  // "Never" on a fresh install.
  const stamps = keys
    .map((k) => k.last_used_at)
    .filter((s): s is string => Boolean(s))
    .map((s) => new Date(s).getTime())
    .filter((t) => !Number.isNaN(t));
  if (stamps.length === 0) return "Never";
  return formatRelative(new Date(Math.max(...stamps)).toISOString());
}

// ── Component ───────────────────────────────────────────────────────────────

export default function ApiKeysPage() {
  // ── State ────────────────────────────────────────────────────────────
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [panelView, setPanelView] = useState<PanelView>(null);
  const [selectedKey, setSelectedKey] = useState<ApiKey | null>(null);

  // create-key form state
  const [newLabel, setNewLabel] = useState("");
  const [newScopes, setNewScopes] = useState<string[]>(["tools:call"]);
  const [creating, setCreating] = useState(false);
  const [createdKeyValue, setCreatedKeyValue] = useState<string | null>(null);
  const [createdRecord, setCreatedRecord] = useState<ApiKey | null>(null);
  const [createWarning, setCreateWarning] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const [revokingId, setRevokingId] = useState<string | null>(null);

  // ── Data load ────────────────────────────────────────────────────────
  const loadKeys = useCallback(async () => {
    setError(null);
    try {
      const r = await fetch("/api/agent/api-keys", { cache: "no-store" });
      if (!r.ok) throw new Error(`api-keys fetch ${r.status}`);
      const data = (await r.json()) as { keys?: ApiKey[]; error?: string };
      if (data.error) throw new Error(data.error);
      setKeys(data.keys ?? []);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadKeys();
  }, [loadKeys]);

  // ── Handlers ─────────────────────────────────────────────────────────
  function openCreate() {
    setNewLabel("");
    setNewScopes(["tools:call"]);
    setCreatedKeyValue(null);
    setCreatedRecord(null);
    setCreateWarning(null);
    setCopied(false);
    setSelectedKey(null);
    setPanelView("create");
  }

  function openDetail(key: ApiKey) {
    setSelectedKey(key);
    setPanelView("detail");
  }

  function closePanel() {
    setPanelView(null);
    setSelectedKey(null);
    setCreatedKeyValue(null);
    setCreatedRecord(null);
    setCreateWarning(null);
  }

  function toggleScope(scope: string) {
    setNewScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope],
    );
  }

  async function handleCreate() {
    if (!newLabel.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const r = await fetch("/api/agent/api-keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          label: newLabel.trim(),
          scopes: newScopes,
        }),
      });
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(`create failed (${r.status}): ${txt}`);
      }
      const data = (await r.json()) as {
        key?: string;
        record?: ApiKey;
        warning?: string;
      };
      if (data.key && data.record) {
        setCreatedKeyValue(data.key);
        setCreatedRecord(data.record);
        setCreateWarning(data.warning ?? null);
        setKeys((prev) => [data.record!, ...prev]);
      } else {
        throw new Error("create response missing key + record");
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setCreating(false);
    }
  }

  function handleCopy() {
    if (!createdKeyValue) return;
    navigator.clipboard.writeText(createdKeyValue);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  async function handleRevoke(id: string) {
    setRevokingId(id);
    setError(null);
    try {
      const r = await fetch(`/api/agent/api-keys/${encodeURIComponent(id)}`, {
        method: "DELETE",
      });
      if (!r.ok && r.status !== 404) {
        throw new Error(`revoke failed (${r.status})`);
      }
      await loadKeys();
      if (selectedKey?.id === id) closePanel();
    } catch (e) {
      setError(String(e));
    } finally {
      setRevokingId(null);
    }
  }

  // ── Derived ──────────────────────────────────────────────────────────
  const activeCount = keys.filter((k) => !k.revoked_at).length;
  const revokedCount = keys.filter((k) => k.revoked_at).length;
  const lastUsedAggregate = mostRecentLastUsed(keys);

  // ── Render ───────────────────────────────────────────────────────────
  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-8 space-y-8">
        {/* Header — matches /skills layout pattern */}
        <header>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <span className="material-symbols-outlined text-2xl text-primary">
                vpn_key
              </span>
              <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
                API Keys
              </h1>
            </div>
            <p className="text-sm text-on-surface-variant ml-9">
              Mint scoped, revocable bearer tokens for external integrations.
            </p>
          </div>
          <button
            type="button"
            onClick={openCreate}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-white text-sm font-bold shadow-lg active:scale-95 transition-transform hover:brightness-110"
            style={{
              background: "linear-gradient(135deg, #1963B3 0%, #2D8DF0 100%)",
            }}
          >
            <span className="material-symbols-outlined text-lg">add</span>
            Create Key
          </button>
        </div>
      </header>

      {error ? (
        <div className="rounded-xl px-4 py-3 bg-error-container/10 border border-error/30 text-error text-sm">
          {error}
        </div>
      ) : null}

      {/* ── Info Banner ── */}
      <div
        className="rounded-2xl p-5 flex items-start gap-4 border border-primary-container/20"
        style={{
          background:
            "rgba(var(--md-sys-color-primary-rgb, 167,200,255), 0.05)",
          backdropFilter: "blur(16px)",
        }}
      >
        <div className="w-10 h-10 rounded-xl bg-primary-container/20 flex items-center justify-center shrink-0">
          <span className="material-symbols-outlined text-primary text-[20px]">
            key
          </span>
        </div>
        <p className="text-sm text-on-surface-variant leading-relaxed">
          Keys are presented to the MCP as{" "}
          <code className="font-mono text-on-surface">Authorization: Bearer phantom_ak_…</code>.
          The plaintext secret is shown <strong>once</strong> at creation —
          treat it like a password and store it in your secret manager
          immediately. Listing, minting, and revocation here all require
          the bundle-internal <code className="font-mono text-on-surface">MCP_TOKEN</code>{" "}
          (proxied for you by the agent); a key with one narrow scope can
          never mint a wider one.
        </p>
      </div>

      {/* ── Stats Row ── */}
      <div className="grid grid-cols-3 gap-4">
        {[
          {
            label: "Active Keys",
            value: String(activeCount),
            icon: "vpn_key",
            color: "text-[#7bdc7b]",
            iconBg: "bg-[#7bdc7b]/10",
          },
          {
            label: "Revoked",
            value: String(revokedCount),
            icon: "block",
            color: "text-error",
            iconBg: "bg-error-container/10",
          },
          {
            label: "Last Used",
            value: lastUsedAggregate,
            icon: "schedule",
            color: "text-[#fbbc30]",
            iconBg: "bg-[#fbbc30]/10",
          },
        ].map((stat) => (
          <div
            key={stat.label}
            className="rounded-2xl p-5 border border-on-surface/[0.04]"
            style={glassPanel}
          >
            <div className="flex items-center gap-3 mb-3">
              <div
                className={`w-9 h-9 rounded-lg ${stat.iconBg} flex items-center justify-center`}
              >
                <span
                  className={`material-symbols-outlined ${stat.color} text-[18px]`}
                >
                  {stat.icon}
                </span>
              </div>
              <span className="text-[11px] font-mono text-on-surface-variant/60 tracking-wider uppercase">
                {stat.label}
              </span>
            </div>
            <p
              className={`text-3xl font-headline font-bold ${stat.color} tracking-tight`}
            >
              {stat.value}
            </p>
          </div>
        ))}
      </div>

      {/* ── Keys Table ── */}
      <div
        className="rounded-2xl overflow-hidden border border-on-surface/[0.04]"
        style={glassPanel}
      >
        <div className="px-6 py-4 border-b border-on-surface/5 flex items-center gap-3">
          <span className="material-symbols-outlined text-primary text-[20px]">
            table_rows
          </span>
          <h2 className="font-headline font-bold text-on-surface text-lg tracking-tight">
            Keys
          </h2>
          <span className="ml-auto text-[11px] font-mono text-on-surface-variant/40">
            {keys.length} total
          </span>
        </div>

        {/* Empty / loading / data states */}
        {loading ? (
          <div className="px-6 py-12 text-center text-sm text-on-surface-variant/60">
            Loading…
          </div>
        ) : keys.length === 0 ? (
          <div className="px-6 py-16 text-center space-y-3">
            <span className="material-symbols-outlined text-4xl text-on-surface-variant/30">
              vpn_key_off
            </span>
            <p className="text-sm font-bold text-on-surface-variant">
              No API keys yet
            </p>
            <p className="text-xs text-on-surface-variant/60 max-w-md mx-auto">
              Click <strong>Create Key</strong> above to mint a scoped bearer
              token for an external integration. Keys are persistent until
              you revoke them — only revoke breaks the bond, restart does
              not.
            </p>
          </div>
        ) : (
          <>
            {/* Table header */}
            <div className="grid grid-cols-[1.3fr_1fr_1.4fr_0.7fr_0.7fr_0.6fr_0.9fr] px-6 py-3 border-b border-on-surface/5 text-[10px] font-mono text-on-surface-variant/40 tracking-[0.15em] uppercase">
              <span>Label</span>
              <span>Key Prefix</span>
              <span>Scopes</span>
              <span>Created</span>
              <span>Last Used</span>
              <span>Status</span>
              <span className="text-right">Actions</span>
            </div>

            {/* Table rows */}
            {keys.map((key) => {
              const status = statusOf(key);
              const isRevoked = status === "revoked";
              const isAdminScope = key.scopes.includes("*");
              return (
                <div
                  key={key.id}
                  className="group grid grid-cols-[1.3fr_1fr_1.4fr_0.7fr_0.7fr_0.6fr_0.9fr] px-6 py-4 border-b border-on-surface/[0.03] hover:bg-on-surface/[0.02] transition-colors cursor-pointer items-center"
                  onClick={() => openDetail(key)}
                >
                  {/* Label */}
                  <div className="flex items-center gap-3">
                    <div
                      className={`w-8 h-8 rounded-lg ${
                        isAdminScope
                          ? "bg-[#c084fc]/10"
                          : "bg-primary/10"
                      } flex items-center justify-center`}
                    >
                      <span
                        className={`material-symbols-outlined ${
                          isAdminScope
                            ? "text-[#c084fc]"
                            : "text-primary-fixed-dim"
                        } text-[16px]`}
                      >
                        {isAdminScope ? "admin_panel_settings" : "vpn_key"}
                      </span>
                    </div>
                    <span className="text-sm font-bold text-on-surface truncate">
                      {key.label}
                    </span>
                  </div>

                  {/* Prefix */}
                  <span className="font-mono text-xs text-on-surface/50">
                    {redactedPrefix(key)}
                  </span>

                  {/* Scopes */}
                  <div className="flex flex-wrap gap-1.5">
                    {key.scopes.length === 0 ? (
                      <span className="text-[10px] font-mono text-on-surface-variant/40">
                        none
                      </span>
                    ) : (
                      key.scopes.map((s) => (
                        <span
                          key={s}
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-mono font-bold tracking-wider ${
                            s === "*"
                              ? "bg-[#c084fc]/10 text-[#c084fc]"
                              : "bg-primary/10 text-primary-fixed-dim"
                          }`}
                        >
                          {s}
                        </span>
                      ))
                    )}
                  </div>

                  {/* Created */}
                  <span className="text-xs text-on-surface-variant/60">
                    {formatDate(key.created_at)}
                  </span>

                  {/* Last Used */}
                  <span className="text-xs text-on-surface-variant/60">
                    {formatRelative(key.last_used_at)}
                  </span>

                  {/* Status */}
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${
                        isRevoked ? "bg-error" : "bg-[#7bdc7b]"
                      }`}
                    />
                    <span
                      className={`text-[10px] font-bold uppercase tracking-wider ${
                        isRevoked ? "text-error" : "text-[#7bdc7b]"
                      }`}
                    >
                      {isRevoked ? "Revoked" : "Active"}
                    </span>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    {!isRevoked && (
                      <button
                        type="button"
                        disabled={revokingId === key.id}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleRevoke(key.id);
                        }}
                        className="px-3 py-1.5 rounded-lg text-[11px] font-bold text-error bg-error-container/10 hover:bg-error-container/20 border border-error/20 transition-all disabled:opacity-30"
                      >
                        {revokingId === key.id ? "Revoking…" : "Revoke"}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </>
        )}
      </div>

      {/* ── Slide-Over Overlay ── */}
      {panelView && (
        <div
          className="fixed inset-0 bg-black/60 z-40 backdrop-blur-[2px]"
          onClick={closePanel}
          aria-hidden="true"
        />
      )}

      {/* ── Create Key Panel ── */}
      {panelView === "create" && (
        <aside
          className="fixed right-0 top-0 h-full w-[50vw] min-w-[600px] max-w-[960px] z-50 shadow-[0_0_80px_rgba(0,0,0,0.5)] flex flex-col overflow-y-auto custom-scrollbar"
          style={panelStyle}
        >
          {/* Header */}
          <header className="p-8 pb-6 border-b border-on-surface/5 shrink-0">
            <div className="flex items-start justify-between mb-4">
              <button
                type="button"
                onClick={closePanel}
                className="w-10 h-10 rounded-full flex items-center justify-center bg-on-surface/5 hover:bg-on-surface/10 transition-all"
                aria-label="Close panel"
              >
                <span className="material-symbols-outlined text-on-surface-variant">
                  close
                </span>
              </button>
            </div>
            <h2 className="text-2xl font-headline font-bold text-on-surface tracking-tight">
              Create API Key
            </h2>
            <p className="text-sm text-on-surface-variant/60 mt-1">
              Mint a new bearer token. Pick a descriptive label and the
              minimum scope set needed.
            </p>
          </header>

          {!createdKeyValue ? (
            <div className="flex-1 p-8 space-y-8">
              {/* Label */}
              <div>
                <label className="block font-mono text-[10px] text-on-surface-variant/60 tracking-[0.2em] mb-2 uppercase">
                  Label <span className="text-error">*</span>
                </label>
                <input
                  type="text"
                  value={newLabel}
                  onChange={(e) => setNewLabel(e.target.value)}
                  placeholder="e.g. siem-poller, ci-deploy-bot"
                  className="w-full bg-surface-container-lowest border border-on-surface/10 rounded-xl px-4 py-3 text-sm text-on-surface placeholder:text-on-surface-variant/30 focus:outline-none focus:border-primary-container/40 focus:ring-1 focus:ring-primary-container/20 transition-all"
                />
                <p className="text-[11px] text-on-surface-variant/40 mt-2">
                  Human-readable identifier shown in the table and the
                  audit log. Cannot be changed after creation.
                </p>
              </div>

              {/* Scopes */}
              <div>
                <label className="block font-mono text-[10px] text-on-surface-variant/60 tracking-[0.2em] mb-3 uppercase">
                  Scopes
                </label>
                <div className="grid grid-cols-2 gap-2.5">
                  {SCOPE_CATALOG.map((s) => {
                    const isSelected = newScopes.includes(s.key);
                    const isAdmin = s.key === "*";
                    return (
                      <button
                        key={s.key}
                        type="button"
                        onClick={() => toggleScope(s.key)}
                        className={`w-full flex items-start gap-3 p-3.5 rounded-xl text-left transition-all border ${
                          isSelected
                            ? isAdmin
                              ? "bg-[#c084fc]/10 border-[#c084fc]/30"
                              : "bg-primary-container/10 border-primary-container/30"
                            : "bg-on-surface/[0.02] border-on-surface/5 hover:border-on-surface/10 hover:bg-on-surface/[0.04]"
                        }`}
                      >
                        <span
                          className={`material-symbols-outlined text-[20px] mt-0.5 ${
                            isSelected
                              ? isAdmin
                                ? "text-[#c084fc]"
                                : "text-primary"
                              : "text-on-surface-variant/30"
                          }`}
                          style={
                            isSelected
                              ? { fontVariationSettings: "'FILL' 1" }
                              : undefined
                          }
                        >
                          {isSelected ? "check_circle" : "radio_button_unchecked"}
                        </span>
                        <div className="flex-1 min-w-0">
                          <code
                            className={`text-sm font-mono font-bold ${
                              isAdmin
                                ? "text-[#c084fc]"
                                : "text-on-surface"
                            }`}
                          >
                            {s.key}
                          </code>
                          <p className="text-xs text-on-surface-variant/60 mt-0.5">
                            {s.description}
                          </p>
                        </div>
                      </button>
                    );
                  })}
                </div>
                <p className="text-[11px] text-on-surface-variant/40 mt-3">
                  At least one scope is required. Use{" "}
                  <code className="font-mono text-on-surface-variant">*</code>{" "}
                  only when the integration genuinely needs admin-equivalent
                  access — narrow scopes are much easier to rotate.
                </p>
              </div>

              {/* Submit */}
              <button
                type="button"
                onClick={handleCreate}
                disabled={
                  !newLabel.trim() || newScopes.length === 0 || creating
                }
                className="w-full bg-primary-container/20 hover:bg-primary-container/30 disabled:opacity-30 disabled:cursor-not-allowed text-primary font-headline font-bold py-3.5 rounded-xl transition-all border border-primary-container/30 active:scale-[0.98]"
              >
                {creating ? "Generating…" : "Generate Key"}
              </button>
            </div>
          ) : (
            /* ── Key Created View ── */
            <div className="flex-1 p-8 space-y-6">
              <div className="rounded-xl p-5 border border-tertiary/30 bg-tertiary-container/10">
                <div className="flex items-center gap-2 mb-3">
                  <span className="material-symbols-outlined text-tertiary text-[18px]">
                    warning
                  </span>
                  <span className="text-sm font-bold text-tertiary">
                    Copy your key now
                  </span>
                </div>
                <p className="text-xs text-on-surface/50 leading-relaxed">
                  {createWarning ??
                    "This key will only be shown once. Copy it now and store it securely. The server stores only a sha256 hash and cannot recover the plaintext after this response closes."}
                </p>
              </div>

              <div>
                <label className="block font-mono text-[10px] text-on-surface-variant/60 tracking-[0.2em] mb-2 uppercase">
                  Your API Key
                </label>
                <div className="relative">
                  <pre className="w-full bg-surface-container-lowest border border-on-surface/10 rounded-xl px-4 py-3.5 text-sm font-mono text-[#7bdc7b] overflow-x-auto whitespace-nowrap custom-scrollbar">
                    {createdKeyValue}
                  </pre>
                  <button
                    type="button"
                    onClick={handleCopy}
                    className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1.5 rounded-lg text-[11px] font-bold bg-on-surface/5 hover:bg-on-surface/10 border border-on-surface/10 transition-all flex items-center gap-1.5"
                  >
                    <span className="material-symbols-outlined text-[14px]">
                      {copied ? "check" : "content_copy"}
                    </span>
                    <span
                      className={
                        copied ? "text-[#7bdc7b]" : "text-on-surface-variant"
                      }
                    >
                      {copied ? "Copied" : "Copy"}
                    </span>
                  </button>
                </div>
              </div>

              {createdRecord ? (
                <div className="rounded-xl p-4 bg-on-surface/[0.02] border border-on-surface/5 space-y-3">
                  <div className="flex justify-between text-xs">
                    <span className="text-on-surface-variant/60">Label</span>
                    <span className="text-on-surface font-bold">
                      {createdRecord.label}
                    </span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-on-surface-variant/60">Scopes</span>
                    <span className="font-mono text-on-surface">
                      {createdRecord.scopes.join(", ") || "—"}
                    </span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-on-surface-variant/60">
                      Created
                    </span>
                    <span className="text-on-surface font-bold">
                      {formatDate(createdRecord.created_at)}
                    </span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-on-surface-variant/60">ID</span>
                    <span className="font-mono text-on-surface">
                      {createdRecord.id}
                    </span>
                  </div>
                </div>
              ) : null}

              <button
                type="button"
                onClick={closePanel}
                className="w-full bg-on-surface/5 hover:bg-on-surface/10 text-on-surface-variant font-headline font-bold py-3.5 rounded-xl transition-all border border-on-surface/10 active:scale-[0.98]"
              >
                Done
              </button>
            </div>
          )}
        </aside>
      )}

      {/* ── Key Detail Panel ── */}
      {panelView === "detail" && selectedKey && (
        <aside
          className="fixed right-0 top-0 h-full w-[480px] max-w-[92vw] z-50 shadow-[0_0_80px_rgba(0,0,0,0.5)] flex flex-col overflow-y-auto custom-scrollbar"
          style={panelStyle}
        >
          {/* Header */}
          <header className="p-8 pb-6 border-b border-on-surface/5 shrink-0">
            <div className="flex items-start justify-between mb-4">
              <button
                type="button"
                onClick={closePanel}
                className="w-10 h-10 rounded-full flex items-center justify-center bg-on-surface/5 hover:bg-on-surface/10 transition-all"
                aria-label="Close panel"
              >
                <span className="material-symbols-outlined text-on-surface-variant">
                  close
                </span>
              </button>
              <div
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full ${
                  statusOf(selectedKey) === "revoked"
                    ? "bg-error-container/20"
                    : "bg-[#7bdc7b]/10"
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    statusOf(selectedKey) === "revoked"
                      ? "bg-error"
                      : "bg-[#7bdc7b]"
                  }`}
                />
                <span
                  className={`text-[10px] font-bold uppercase tracking-wider ${
                    statusOf(selectedKey) === "revoked"
                      ? "text-error"
                      : "text-[#7bdc7b]"
                  }`}
                >
                  {statusOf(selectedKey) === "revoked" ? "Revoked" : "Active"}
                </span>
              </div>
            </div>
            <h2 className="text-2xl font-headline font-bold text-on-surface tracking-tight mb-1">
              {selectedKey.label}
            </h2>
            <p className="font-mono text-sm text-on-surface-variant/60">
              {redactedPrefix(selectedKey)}
            </p>
          </header>

          <div className="flex-1 p-8 space-y-8">
            {/* Metadata */}
            <div className="rounded-xl border border-on-surface/5 overflow-hidden bg-on-surface/[0.03]">
              {[
                {
                  label: "ID",
                  value: selectedKey.id,
                  color: "text-on-surface-variant",
                  mono: true,
                },
                {
                  label: "Scopes",
                  value: selectedKey.scopes.join(", ") || "none",
                  color: "text-on-surface",
                  mono: true,
                },
                {
                  label: "Created",
                  value: formatDate(selectedKey.created_at),
                  color: "text-on-surface",
                },
                {
                  label: "Created By",
                  value: selectedKey.created_by ?? "—",
                  color: "text-on-surface",
                },
                {
                  label: "Last Used",
                  value: formatRelative(selectedKey.last_used_at),
                  color: "text-on-surface",
                },
                ...(selectedKey.revoked_at
                  ? [
                      {
                        label: "Revoked",
                        value: formatDate(selectedKey.revoked_at),
                        color: "text-error",
                      },
                    ]
                  : []),
              ].map((item, i, arr) => (
                <div
                  key={item.label}
                  className={`flex justify-between items-center px-5 py-3.5 ${
                    i < arr.length - 1 ? "border-b border-on-surface/[0.03]" : ""
                  }`}
                >
                  <span className="text-xs text-on-surface-variant/60">
                    {item.label}
                  </span>
                  <span
                    className={`text-sm font-bold ${item.color} ${
                      "mono" in item && item.mono ? "font-mono" : ""
                    }`}
                  >
                    {item.value}
                  </span>
                </div>
              ))}
            </div>

            {/* Actions */}
            {statusOf(selectedKey) === "active" ? (
              <button
                type="button"
                disabled={revokingId === selectedKey.id}
                onClick={() => handleRevoke(selectedKey.id)}
                className="w-full flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-bold text-error bg-error-container/10 hover:bg-error-container/20 border border-error/20 transition-all active:scale-[0.98] disabled:opacity-30"
              >
                <span className="material-symbols-outlined text-[18px]">
                  block
                </span>
                {revokingId === selectedKey.id ? "Revoking…" : "Revoke Key"}
              </button>
            ) : (
              <p className="text-center text-xs text-on-surface-variant/60">
                This key has been revoked and can no longer be used.
              </p>
            )}
          </div>
        </aside>
      )}
      </div>
    </div>
  );
}
