"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Phantom providers page — ported from spark/services/ui's
 * settings/providers, with two phantom-specific shifts:
 *
 *   1. **Endpoints**: Spark's apiRequest helper hits the api-gateway
 *      at /api/v1/config{,/providers}. Phantom doesn't ship those
 *      routes; this page calls /api/agent/providers/config directly,
 *      which reads/writes the MCP-side ProviderStore.
 *   2. **Scope**: Vertex AI (Gemini), Anthropic and OpenAI. A provider the
 *      chat path cannot use has no card here.
 *
 * The Anthropic card holds anthropicApiKey and an optional anthropicBaseUrl;
 * the OpenAI card holds openaiApiKey and the optional openaiBaseUrl,
 * openaiOrganization and openaiProject. They are stored by the config route
 * and read back by lib/providers/credentials.ts. The model registry lists the
 * models from them and the chat route calls the models with them. Test
 * Connection asks the vendor's model list; the key field keeps the "***"
 * sentinel so a saved key is tested without leaving the server. A saved key is
 * only sent to the base URL it was saved with, so editing the base URL empties
 * the key field and the key has to be typed again before saving.
 */

// ── Types ────────────────────────────────────────────────────────────────────

interface ProviderConfig {
  anthropicApiKey: string;
  /** Anthropic — optional base URL for a gateway; empty means api.anthropic.com. Not a secret. */
  anthropicBaseUrl: string;
  openaiApiKey: string;
  /** OpenAI — optional base URL, version segment included; empty means api.openai.com/v1. Not a secret. */
  openaiBaseUrl: string;
  /** OpenAI — optional organization id (org-...). Not a secret. */
  openaiOrganization: string;
  /** OpenAI — optional project id (proj_...). Not a secret. */
  openaiProject: string;
  /** Google Vertex AI — service-account JSON blob (multi-line). Encrypted in Infisical. */
  vertexServiceAccountJson: string;
  /** Google Vertex AI — GCP project that owns the quotas. Not a secret. */
  vertexProjectId: string;
  /** Google Vertex AI — region, defaults to us-central1. Gemini 3 auto-routes to global. */
  vertexLocation: string;
}

/** Which providers have a saved credential, as the server reports it. */
interface ConfiguredProviders {
  vertex: boolean;
  anthropic: boolean;
  openai: boolean;
}

/** The last Test Connection outcome in this browser session. */
interface LastCheck {
  provider: string;
  ok: boolean;
  at: number;
}

/** The providers whose card is an API key plus an optional base URL. */
type KeyedProviderId = "anthropic" | "openai";
type ProviderCardId = KeyedProviderId | "vertex";

/** What the server returns in place of a saved key. */
const SAVED_KEY_SENTINEL = "***";

interface ConnectionStatus {
  provider: string;
  status: "idle" | "testing" | "success" | "error";
  message?: string;
}

// ── Constants ────────────────────────────────────────────────────────────────

const PROVIDER_LABEL: Record<string, string> = {
  vertex: "Vertex AI",
  anthropic: "Anthropic",
  openai: "OpenAI",
};

const NONE_CONFIGURED: ConfiguredProviders = { vertex: false, anthropic: false, openai: false };

const glassCard: React.CSSProperties = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "1px solid var(--glass-border)",
};

const DEFAULT_PROVIDER_CONFIG: ProviderConfig = {
  anthropicApiKey: "",
  anthropicBaseUrl: "",
  openaiApiKey: "",
  openaiBaseUrl: "",
  openaiOrganization: "",
  openaiProject: "",
  vertexServiceAccountJson: "",
  vertexProjectId: "",
  vertexLocation: "us-central1",
};

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Which providers have a saved credential. Read from the server's own
 * `configured` map (never from the form, which may hold unsaved typing).
 */
function extractConfigured(config: Record<string, unknown> | null): ConfiguredProviders {
  const flags = (config?.configured ?? {}) as Record<string, unknown>;
  return {
    vertex: flags.vertexServiceAccountJson === true && flags.vertexProjectId === true,
    anthropic: flags.anthropicApiKey === true,
    openai: flags.openaiApiKey === true,
  };
}

function extractProviderConfig(
  config: Record<string, unknown> | null,
): ProviderConfig {
  const providers = (config?.providers ?? {}) as Record<string, unknown>;
  return {
    anthropicApiKey:
      typeof providers.anthropicApiKey === "string"
        ? providers.anthropicApiKey
        : "",
    anthropicBaseUrl:
      typeof providers.anthropicBaseUrl === "string"
        ? providers.anthropicBaseUrl
        : "",
    openaiApiKey: typeof providers.openaiApiKey === "string" ? providers.openaiApiKey : "",
    openaiBaseUrl: typeof providers.openaiBaseUrl === "string" ? providers.openaiBaseUrl : "",
    openaiOrganization:
      typeof providers.openaiOrganization === "string" ? providers.openaiOrganization : "",
    openaiProject: typeof providers.openaiProject === "string" ? providers.openaiProject : "",
    vertexServiceAccountJson:
      typeof providers.vertexServiceAccountJson === "string"
        ? providers.vertexServiceAccountJson
        : "",
    vertexProjectId:
      typeof providers.vertexProjectId === "string"
        ? providers.vertexProjectId
        : "",
    vertexLocation:
      typeof providers.vertexLocation === "string"
        ? providers.vertexLocation
        : "us-central1",
  };
}

// ── Masked Input ─────────────────────────────────────────────────────────────

function MaskedKeyInput({
  id,
  label,
  value,
  onChange,
  placeholder,
  helpText,
  disabled,
  maxWidth,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  helpText?: string;
  disabled?: boolean;
  maxWidth?: boolean;
}) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="space-y-2">
      <label
        htmlFor={id}
        className="block text-[11px] font-bold text-on-surface-variant uppercase tracking-widest font-label"
      >
        {label}
      </label>
      <div className={`relative group${maxWidth ? " max-w-xl" : ""}`}>
        <input
          id={id}
          type={visible ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder ?? "sk-..."}
          disabled={disabled}
          className="w-full bg-surface-container-lowest border-none rounded-lg px-4 py-3 text-sm font-mono text-on-surface focus:ring-1 focus:ring-primary/40 transition-all outline-none disabled:opacity-40 disabled:cursor-not-allowed"
        />
        {!disabled && (
          <button
            type="button"
            onClick={() => setVisible((v) => !v)}
            aria-label={visible ? `Hide ${label}` : `Show ${label}`}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-on-surface-variant hover:text-white transition-colors"
          >
            <span className="material-symbols-outlined text-sm">
              {visible ? "visibility_off" : "visibility"}
            </span>
          </button>
        )}
      </div>
      {helpText && (
        <p className="text-[10px] text-on-surface-variant/50 font-label italic">
          {helpText}
        </p>
      )}
    </div>
  );
}

// ── Status Badge Helpers ─────────────────────────────────────────────────────

function ConnectionBadge({ status }: { status: ConnectionStatus | undefined }) {
  if (!status || status.status === "idle") return null;

  if (status.status === "testing") {
    return (
      <span className="bg-tertiary/10 text-tertiary text-[10px] font-bold px-2 py-0.5 rounded border border-tertiary/20 uppercase tracking-tighter">
        Testing...
      </span>
    );
  }
  if (status.status === "success") {
    return (
      <span className="bg-secondary/10 text-secondary text-[10px] font-bold px-2 py-0.5 rounded border border-secondary/20 uppercase tracking-tighter">
        Connected
      </span>
    );
  }
  return (
    <span className="bg-error/10 text-error text-[10px] font-bold px-2 py-0.5 rounded border border-error/20 uppercase tracking-tighter">
      {status.message ?? "Error"}
    </span>
  );
}

function EncryptedBadge({ value }: { value: string }) {
  if (!value || !value.includes("...")) return null;
  return (
    <span className="bg-primary/5 text-primary/70 text-[10px] font-bold px-2 py-0.5 rounded border border-primary/20 uppercase tracking-tighter">
      Encrypted
    </span>
  );
}

// ── Page Component ───────────────────────────────────────────────────────────

/**
 * Service-account JSON mask. The textarea is multi-line and `<input
 * type=password>` doesn't apply, so we render the value with every
 * non-newline char replaced by `•` when the operator hasn't clicked
 * Reveal. The textarea is NOT readOnly while masked (readOnly
 * would block all input, so the operator could never replace a
 * stored value and Save would stay disabled forever). Any keystroke or paste fires `onChange`, which strips leftover
 * bullets and auto-reveals so subsequent edits show real content.
 */
function maskJson(value: string): string {
  return value.replace(/[^\n]/g, "•");
}

export default function ProvidersSettingsPage() {
  const [form, setForm] = useState<ProviderConfig>(DEFAULT_PROVIDER_CONFIG);
  const initialForm = useRef<ProviderConfig>(DEFAULT_PROVIDER_CONFIG);
  const [loading, setLoading] = useState(true);
  const [savingProvider, setSavingProvider] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connectionStatuses, setConnectionStatuses] = useState<
    Record<string, ConnectionStatus>
  >({});
  const [configured, setConfigured] = useState<ConfiguredProviders>(NONE_CONFIGURED);
  const [lastCheck, setLastCheck] = useState<LastCheck | null>(null);
  // Vertex SA JSON masking — defaults to hidden when there's saved
  // content. New entries (operator typing into an empty field) start
  // visible until the next save round.
  const [vertexJsonVisible, setVertexJsonVisible] = useState(false);

  // ── Data fetching ────────────────────────────────────────────────────────

  const loadConfig = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch("/api/agent/providers/config", { cache: "no-store" });
      if (r.ok) {
        const data = (await r.json()) as Record<string, unknown>;
        const cfg = extractProviderConfig(data);
        setForm(cfg);
        initialForm.current = cfg;
        setConfigured(extractConfigured(data));
      }
    } catch {
      // empty state — operator hasn't supplied creds yet
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  // ── Form helpers ─────────────────────────────────────────────────────────

  function updateField<K extends keyof ProviderConfig>(
    key: K,
    value: ProviderConfig[K],
  ) {
    setForm((prev) => ({ ...prev, [key]: value }));
    setError(null);
  }

  /**
   * Edit a base URL. A saved key (shown as the "***" sentinel) is only sent to
   * the base URL it was saved with, so a changed base URL empties the key
   * field: the operator types the key again, and Save stays off until then.
   */
  function updateBaseUrl(provider: KeyedProviderId, value: string) {
    const urlField = provider === "anthropic" ? "anthropicBaseUrl" : "openaiBaseUrl";
    const keyField = provider === "anthropic" ? "anthropicApiKey" : "openaiApiKey";
    setForm((prev) => {
      const keyIsSaved = initialForm.current[keyField] === SAVED_KEY_SENTINEL && prev[keyField] === SAVED_KEY_SENTINEL;
      const moved = value.trim() !== initialForm.current[urlField].trim();
      // Back at the saved URL with the key field emptied by an earlier edit:
      // the saved key applies again.
      const restore = initialForm.current[keyField] === SAVED_KEY_SENTINEL && prev[keyField] === "" && !moved;
      return {
        ...prev,
        [urlField]: value,
        ...(keyIsSaved && moved ? { [keyField]: "" } : {}),
        ...(restore ? { [keyField]: SAVED_KEY_SENTINEL } : {}),
      };
    });
    setError(null);
  }

  function isProviderDirty(provider: ProviderCardId): boolean {
    if (provider === "anthropic") {
      return (
        form.anthropicApiKey !== initialForm.current.anthropicApiKey ||
        form.anthropicBaseUrl !== initialForm.current.anthropicBaseUrl
      );
    }
    if (provider === "openai") {
      return (
        form.openaiApiKey !== initialForm.current.openaiApiKey ||
        form.openaiBaseUrl !== initialForm.current.openaiBaseUrl ||
        form.openaiOrganization !== initialForm.current.openaiOrganization ||
        form.openaiProject !== initialForm.current.openaiProject
      );
    }
    return (
      form.vertexServiceAccountJson !==
        initialForm.current.vertexServiceAccountJson ||
      form.vertexProjectId !== initialForm.current.vertexProjectId ||
      form.vertexLocation !== initialForm.current.vertexLocation
    );
  }

  // ── Save (per-card) ─────────────────────────────────────────────────────

  async function handleSaveProvider(provider: ProviderCardId) {
    setSavingProvider(provider);
    setError(null);

    // Only this card's fields are sent, so saving one provider never
    // touches the other.
    const payload =
      provider === "anthropic"
        ? {
            anthropicApiKey: form.anthropicApiKey,
            anthropicBaseUrl: form.anthropicBaseUrl,
          }
        : provider === "openai"
          ? {
              openaiApiKey: form.openaiApiKey,
              openaiBaseUrl: form.openaiBaseUrl,
              openaiOrganization: form.openaiOrganization,
              openaiProject: form.openaiProject,
            }
          : {
              vertexServiceAccountJson: form.vertexServiceAccountJson,
              vertexProjectId: form.vertexProjectId,
              vertexLocation: form.vertexLocation,
            };

    try {
      const r = await fetch("/api/agent/providers/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: payload }),
      });
      if (r.ok) {
        await refreshSaved(provider);
      } else {
        const data = (await r.json().catch(() => ({}))) as {
          error?: string;
          mcp_sync?: Record<string, { error?: string } | undefined>;
        };
        setError(
          data.error ||
            data.mcp_sync?.[provider]?.error ||
            `Failed to save ${provider} configuration`,
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to save ${provider}`);
    }

    setSavingProvider(null);
  }

  /**
   * After a save, refresh what the page knows: the Active Backends tile follows
   * what is really stored, and a saved key field returns to the "***"
   * sentinel (the plaintext is not kept in the page). The other cards' unsaved
   * edits are left alone.
   */
  async function refreshSaved(provider: ProviderCardId) {
    try {
      const r = await fetch("/api/agent/providers/config", { cache: "no-store" });
      if (!r.ok) return;
      const data = (await r.json()) as Record<string, unknown>;
      const saved = extractProviderConfig(data);
      setConfigured(extractConfigured(data));
      const take = (keys: (keyof ProviderConfig)[]) => {
        const patch: Partial<ProviderConfig> = {};
        for (const k of keys) patch[k] = saved[k];
        setForm((prev) => ({ ...prev, ...patch }));
        initialForm.current = { ...initialForm.current, ...patch };
      };
      if (provider === "anthropic") {
        take(["anthropicApiKey", "anthropicBaseUrl"]);
      } else if (provider === "openai") {
        take(["openaiApiKey", "openaiBaseUrl", "openaiOrganization", "openaiProject"]);
      } else {
        // The Vertex card keeps what was typed, so Test Connection can still
        // use the pasted JSON; only its "saved" baseline moves.
        initialForm.current = {
          ...initialForm.current,
          vertexServiceAccountJson: form.vertexServiceAccountJson,
          vertexProjectId: form.vertexProjectId,
          vertexLocation: form.vertexLocation,
        };
      }
    } catch {
      // The save succeeded; the next page load shows the stored state.
    }
  }

  // ── Connection test ──────────────────────────────────────────────────────

  /**
   * Whether the provider's credential fields are filled enough to save
   * or test.
   */
  function hasTestableApiKey(provider: ProviderCardId): boolean {
    if (provider === "anthropic") {
      return !!form.anthropicApiKey.trim();
    }
    if (provider === "openai") {
      return !!form.openaiApiKey.trim();
    }
    // Vertex requires ALL three fields filled before either Test or
    // Save activates — incomplete state would either fail at the
    // JWT exchange (no project) or be saved as a half-config that
    // the runtime can't register the provider from. Forcing all 3
    // fields up front gives the user a single clear "fill the
    // section completely" signal instead of letting them save junk.
    return (
      !!form.vertexServiceAccountJson.trim() &&
      !!form.vertexProjectId.trim() &&
      !!form.vertexLocation.trim()
    );
  }

  /**
   * Can the operator legitimately Test Vertex now?
   *
   * `hasTestableApiKey("vertex")` alone ("all three fields non-empty")
   * is not enough. On a fresh page load with saved creds, the JSON
   * field carries the backend's masked-bullet sentinel (• repeated),
   * while Project + Region come down in cleartext from ProviderStore.
   * Testing then would send the masked sentinel as the JSON, and the
   * backend's /providers/vertex/test would respond "no Vertex
   * service-account JSON is configured yet" — which an operator could
   * misread as "my saved auth is broken" when nothing changed and chat
   * still works fine. A misleading banner on a working install
   * undermines trust during onboarding.
   *
   * Returns {ok, reason}. The reason becomes the disabled-button tooltip
   * so the operator knows exactly which precondition isn't met — they
   * can decide whether to paste a real JSON (to actually validate) or
   * skip the test (the saved creds are already in effect at runtime).
   *
   * The three checks, in order:
   *   1. Every field has a non-empty value.
   *   2. The JSON in the form differs from the JSON we loaded — i.e.,
   *      the operator has re-pasted (or this is a fresh install with
   *      no prior JSON). Just changing Project or Region without
   *      re-pasting the JSON is NOT enough, because the test endpoint
   *      receives the JSON from the form and can't probe with the
   *      masked sentinel.
   *
   * Save Changes already enforces the dirty + populated combo via
   * `isProviderDirty + hasTestableApiKey`; this brings Test onto the
   * same model with the additional JSON-specifically-touched check.
   */
  function canTestVertex(): { ok: boolean; reason: string } {
    if (!form.vertexProjectId.trim()) {
      return { ok: false, reason: "Fill in Project ID before testing." };
    }
    if (!form.vertexLocation.trim()) {
      return { ok: false, reason: "Fill in Region before testing." };
    }
    if (!form.vertexServiceAccountJson.trim()) {
      return { ok: false, reason: "Paste a Service Account JSON before testing." };
    }
    // Loaded JSON arrives as the backend's redaction sentinel (• chars).
    // If the operator hasn't pasted anything, the form value equals the
    // initial value AND the initial value is the sentinel pattern. Re-
    // pasting the same JSON over the masked field produces a new form
    // value that differs from initial — that's "dirty," and test fires.
    if (
      initialForm.current.vertexServiceAccountJson.length > 0 &&
      form.vertexServiceAccountJson === initialForm.current.vertexServiceAccountJson
    ) {
      return {
        ok: false,
        reason:
          "Re-paste the Service Account JSON to test. The masked sentinel can't be probed; your saved creds are already in effect at runtime.",
      };
    }
    return { ok: true, reason: "" };
  }

  async function testConnection(provider: string) {
    setConnectionStatuses((prev) => ({
      ...prev,
      [provider]: { provider, status: "testing" },
    }));

    // Build the body per provider. Anthropic and OpenAI send their api_key (the
    // "***" sentinel means the saved key, resolved on the server) and the base
    // URL; OpenAI adds its organization and project.
    // Vertex uses service-account JSON + project ID +
    // optional location, validated via a JWT→OAuth2 exchange followed
    // by a ping of Vertex's publisher-models endpoint.
    let body: Record<string, string>;
    if (provider === "vertex") {
      if (!form.vertexServiceAccountJson || !form.vertexProjectId) {
        setConnectionStatuses((prev) => ({
          ...prev,
          [provider]: {
            provider,
            status: "error",
            message: "Service account JSON and project ID are both required.",
          },
        }));
        return;
      }
      body = {
        service_account_json: form.vertexServiceAccountJson,
        project_id: form.vertexProjectId,
        location: form.vertexLocation || "us-central1",
      };
    } else {
      const isOpenAi = provider === "openai";
      const apiKey = (isOpenAi ? form.openaiApiKey : form.anthropicApiKey).trim();
      if (!apiKey) {
        setConnectionStatuses((prev) => ({
          ...prev,
          [provider]: {
            provider,
            status: "error",
            message: "Enter an API key to test connectivity.",
          },
        }));
        return;
      }
      body = isOpenAi
        ? {
            api_key: apiKey,
            base_url: form.openaiBaseUrl.trim(),
            organization: form.openaiOrganization.trim(),
            project: form.openaiProject.trim(),
          }
        : { api_key: apiKey, base_url: form.anthropicBaseUrl.trim() };
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);

    try {
      // Each provider has its own probe route under
      // /api/agent/providers/{id}/test. Vertex exchanges a JWT for an access
      // token; Anthropic and OpenAI list their models. A route that does not exist for a
      // provider (404) is reported as a soft success after save.
      const r = await fetch(
        `/api/agent/providers/${encodeURIComponent(provider)}/test`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: controller.signal,
        },
      );
      clearTimeout(timeoutId);

      if (r.ok) {
        const data = (await r.json().catch(() => ({}))) as { status?: string; message?: string };
        setLastCheck({ provider, ok: data.status === "success", at: Date.now() });
        if (data.status === "success") {
          setConnectionStatuses((prev) => ({
            ...prev,
            [provider]: { provider, status: "success", message: data.message || "Connected" },
          }));
        } else {
          setConnectionStatuses((prev) => ({
            ...prev,
            [provider]: { provider, status: "error", message: data.message || "Probe returned no status" },
          }));
        }
      } else if (r.status === 404) {
        // No probe endpoint — soft-success after save.
        setConnectionStatuses((prev) => ({
          ...prev,
          [provider]: {
            provider,
            status: "success",
            message: "Saved — validated at chat runtime",
          },
        }));
      } else {
        setConnectionStatuses((prev) => ({
          ...prev,
          [provider]: { provider, status: "error", message: `HTTP ${r.status}` },
        }));
      }
    } catch {
      clearTimeout(timeoutId);
      setConnectionStatuses((prev) => ({
        ...prev,
        [provider]: {
          provider,
          status: "error",
          message: "Connection timed out",
        },
      }));
    }
  }

  // ── Render ───────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <main className="h-screen overflow-y-auto custom-scrollbar">
        <div className="max-w-[1400px] mx-auto px-8 py-10">
          <p className="text-sm text-on-surface-variant">Loading provider settings...</p>
        </div>
      </main>
    );
  }

  return (
    <main className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-10 space-y-8">
        {/* Error Banner */}
        {error && (
          <div className="p-4 bg-error/10 border-l-4 border-error rounded-lg flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="material-symbols-outlined text-error">error</span>
              <p className="text-error font-medium text-sm font-label">{error}</p>
            </div>
            <button
              onClick={() => setError(null)}
              className="text-error/60 hover:text-error transition-colors"
              aria-label="Dismiss error"
            >
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>
        )}

        {/* Page Header — jobs-style (icon + title + subtitle). */}
        <header className="mb-2">
          <div className="flex items-center gap-3 mb-1">
            <span className="material-symbols-outlined text-2xl text-primary">
              key
            </span>
            <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
              Providers
            </h1>
          </div>
          <p className="text-sm text-on-surface-variant ml-9">
            Configure credentials for LLM providers and execution backends.
          </p>
        </header>

        <div className="space-y-6">
          {/* ── Google Vertex AI (Gemini) ─────────────────────────────── */}
          <section className="rounded-xl overflow-hidden relative" style={glassCard}>
            {/* Accent Bar — Google blue→teal gradient */}
            <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-[#4285F4] to-[#34A853]" />

            <div className="p-6">
              {/* Card Header */}
              <div className="flex items-center justify-between mb-8">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-lg bg-[#4285F4]/15 flex items-center justify-center text-[#4285F4]">
                    <span
                      className="material-symbols-outlined text-2xl"
                      style={{ fontVariationSettings: "'FILL' 1" }}
                    >
                      diamond
                    </span>
                  </div>
                  <div>
                    <h3 className="font-headline text-lg font-bold text-on-surface">
                      Google Vertex AI (Gemini)
                    </h3>
                    <div className="flex gap-2 mt-1">
                      <ConnectionBadge status={connectionStatuses["vertex"]} />
                      <EncryptedBadge value={form.vertexServiceAccountJson} />
                    </div>
                  </div>
                </div>
                <div className="flex gap-3">
                  {/* Test Connection mirrors
                      the dirty-tracking discipline Save Changes already
                      uses, with one extra check — the JSON field
                      specifically must differ from its loaded value,
                      because the test endpoint receives the JSON from
                      the form and can't probe with the masked sentinel.
                      canTestVertex returns {ok, reason}; the reason
                      becomes the disabled-button tooltip so the
                      operator sees exactly which precondition isn't
                      met (a saved key that simply hasn't been re-pasted is
                      not an error). */}
                  <button
                    type="button"
                    disabled={!canTestVertex().ok}
                    onClick={() => testConnection("vertex")}
                    title={
                      canTestVertex().ok
                        ? "Exchanges the service account JWT for an OAuth access token and pings the Vertex publisher-models endpoint."
                        : canTestVertex().reason
                    }
                    className="px-4 py-2 text-xs font-bold font-headline rounded bg-transparent border border-outline-variant/30 text-on-surface hover:bg-surface-bright transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    Test Connection
                  </button>
                  <button
                    type="button"
                    disabled={
                      !hasTestableApiKey("vertex") ||
                      !isProviderDirty("vertex") ||
                      savingProvider === "vertex"
                    }
                    title={
                      !hasTestableApiKey("vertex")
                        ? "Fill in Project ID, Region, and Service Account JSON before saving."
                        : ""
                    }
                    onClick={() => handleSaveProvider("vertex")}
                    className="px-6 py-2 text-xs font-bold font-headline rounded bg-primary-container text-on-primary-container hover:shadow-[0_0_15px_rgba(25,99,179,0.3)] transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {savingProvider === "vertex" ? "Saving..." : "Save Changes"}
                  </button>
                </div>
              </div>

              {/* Fields — 2-column top row (project / region), full-width JSON blob below */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-2">
                  <label
                    htmlFor="vertex-project-id"
                    className="block text-[11px] font-bold text-on-surface-variant uppercase tracking-widest font-label"
                  >
                    GCP Project ID
                  </label>
                  <div className="max-w-xl">
                    <input
                      id="vertex-project-id"
                      type="text"
                      value={form.vertexProjectId}
                      onChange={(e) => updateField("vertexProjectId", e.target.value)}
                      placeholder="my-gcp-project"
                      className="w-full bg-surface-container-lowest border-none rounded-lg px-4 py-3 text-sm font-mono text-on-surface focus:ring-1 focus:ring-primary/40 transition-all outline-none"
                    />
                  </div>
                  <p className="text-[10px] text-on-surface-variant/60 font-label">
                    GCP project that owns the Vertex AI quotas.
                  </p>
                </div>
                <div className="space-y-2">
                  <label
                    htmlFor="vertex-location"
                    className="block text-[11px] font-bold text-on-surface-variant uppercase tracking-widest font-label"
                  >
                    Region
                  </label>
                  <div className="max-w-xl">
                    <input
                      id="vertex-location"
                      type="text"
                      value={form.vertexLocation}
                      onChange={(e) => updateField("vertexLocation", e.target.value)}
                      placeholder="us-central1"
                      className="w-full bg-surface-container-lowest border-none rounded-lg px-4 py-3 text-sm font-mono text-on-surface focus:ring-1 focus:ring-primary/40 transition-all outline-none"
                    />
                  </div>
                  <p className="text-[10px] text-on-surface-variant/60 font-label">
                    Default <code className="font-mono">us-central1</code>. Gemini 3 preview auto-routes to <code className="font-mono">global</code>.
                  </p>
                </div>
              </div>

              <div className="mt-6 space-y-2">
                <div className="flex items-center justify-between">
                  <label
                    htmlFor="vertex-sa-json"
                    className="block text-[11px] font-bold text-on-surface-variant uppercase tracking-widest font-label"
                  >
                    Service Account JSON
                  </label>
                  {form.vertexServiceAccountJson && (
                    <button
                      type="button"
                      onClick={() => setVertexJsonVisible((v) => !v)}
                      className="flex items-center gap-1.5 text-[10px] font-bold text-on-surface-variant hover:text-on-surface uppercase tracking-widest transition-colors"
                      aria-label={vertexJsonVisible ? "Hide Service Account JSON" : "Show Service Account JSON"}
                    >
                      <span className="material-symbols-outlined text-sm">
                        {vertexJsonVisible ? "visibility_off" : "visibility"}
                      </span>
                      {vertexJsonVisible ? "Hide" : "Reveal"}
                    </button>
                  )}
                </div>
                <textarea
                  id="vertex-sa-json"
                  value={
                    vertexJsonVisible || !form.vertexServiceAccountJson
                      ? form.vertexServiceAccountJson
                      : maskJson(form.vertexServiceAccountJson)
                  }
                  onChange={(e) => {
                    // The textarea is not readOnly when the JSON is
                    // masked: a readOnly field would stop the operator
                    // pasting/typing a replacement and Save would stay
                    // disabled forever (form value never differing from
                    // the loaded "***" sentinel).
                    //
                    // When the user types into a masked field, the
                    // textarea's new value contains BOTH the bullet-
                    // mask of the prior stored JSON AND the new char(s)
                    // they typed. Stripping the bullets leaves only
                    // what they actually entered, which is what we
                    // want to capture as the replacement value.
                    // Switching to visible mode at the same time so
                    // subsequent edits show real content, not bullets.
                    if (!vertexJsonVisible && form.vertexServiceAccountJson) {
                      const stripped = e.target.value.replace(/•/g, "");
                      setVertexJsonVisible(true);
                      updateField("vertexServiceAccountJson", stripped);
                    } else {
                      updateField("vertexServiceAccountJson", e.target.value);
                    }
                  }}
                  placeholder='{"type":"service_account","project_id":"...","private_key":"...","client_email":"..."}'
                  rows={6}
                  spellCheck={false}
                  autoComplete="off"
                  className="w-full bg-surface-container-lowest border-none rounded-lg px-4 py-3 text-xs font-mono text-on-surface focus:ring-1 focus:ring-primary/40 transition-all outline-none resize-y"
                />
                <p className="text-[10px] text-on-surface-variant/60 font-label">
                  Paste the full JSON key from GCP Console → IAM → Service Accounts. Stored encrypted at rest with the
                  {" "}<code className="font-mono">PHANTOM_SECRET_KEK</code>{" "}from <code className="font-mono">/opt/phantom/.env</code>.
                  To replace a stored value, just type or paste — the masked bullets clear automatically. <em>Reveal</em> shows the redaction sentinel returned by the API (your real key is never sent back to the browser).
                </p>
              </div>
            </div>
          </section>

          {/* ── Anthropic Card ──────────────────────────────────────────── */}
          <section
            className="rounded-xl overflow-hidden relative"
            style={glassCard}
          >
            <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-primary to-primary-container" />
            <div className="p-6">
              <div className="flex items-center justify-between mb-8">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-lg bg-primary-container/20 flex items-center justify-center text-primary">
                    <span className="material-symbols-outlined text-2xl" style={{ fontVariationSettings: "'FILL' 1" }}>
                      auto_awesome
                    </span>
                  </div>
                  <div>
                    <h3 className="font-headline text-lg font-bold text-on-surface">Anthropic (Claude API)</h3>
                    <div className="flex gap-2 mt-1">
                      <ConnectionBadge status={connectionStatuses["anthropic"]} />
                    </div>
                  </div>
                </div>
                <div className="flex gap-3 items-center">
                  <button
                    type="button"
                    disabled={
                      !hasTestableApiKey("anthropic") ||
                      connectionStatuses["anthropic"]?.status === "testing"
                    }
                    onClick={() => testConnection("anthropic")}
                    title={
                      hasTestableApiKey("anthropic")
                        ? "Asks Anthropic for its model list, which costs no tokens. With a saved key, the key is read on the server."
                        : "Enter an API key before testing."
                    }
                    className="px-4 py-2 text-xs font-bold font-headline rounded bg-transparent border border-outline-variant/30 text-on-surface hover:bg-surface-bright transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    Test Connection
                  </button>
                  <button
                    type="button"
                    disabled={
                      savingProvider !== null ||
                      !hasTestableApiKey("anthropic") ||
                      !isProviderDirty("anthropic")
                    }
                    onClick={() => handleSaveProvider("anthropic")}
                    className="px-6 py-2 text-xs font-bold font-headline rounded bg-primary-container text-on-primary-container hover:shadow-[0_0_15px_rgba(25,99,179,0.3)] transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {savingProvider === "anthropic" ? "Saving..." : "Save Changes"}
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-6">
                <MaskedKeyInput
                  id="anthropic-api-key"
                  label="API Key"
                  value={form.anthropicApiKey}
                  onChange={(v) => updateField("anthropicApiKey", v)}
                  placeholder="sk-ant-api03-..."
                  helpText="An Anthropic API key (sk-ant-api03-). Stored encrypted; a saved key shows as dots and is never sent back to the browser."
                />
                <div className="space-y-2">
                  <label
                    htmlFor="anthropic-base-url"
                    className="block text-[11px] font-bold text-on-surface-variant uppercase tracking-widest font-label"
                  >
                    Base URL (optional)
                  </label>
                  <div className="max-w-xl">
                    <input
                      id="anthropic-base-url"
                      type="text"
                      value={form.anthropicBaseUrl}
                      onChange={(e) => updateBaseUrl("anthropic", e.target.value)}
                      placeholder="https://api.anthropic.com"
                      spellCheck={false}
                      autoComplete="off"
                      className="w-full bg-surface-container-lowest border-none rounded-lg px-4 py-3 text-sm font-mono text-on-surface focus:ring-1 focus:ring-primary/40 transition-all outline-none"
                    />
                  </div>
                  <p className="text-[10px] text-on-surface-variant/60 font-label">
                    Leave empty for <code className="font-mono">https://api.anthropic.com</code>. Use it to reach Claude
                    through your own gateway. HTTPS only; this install&apos;s own services and link-local addresses are refused.
                    Changing the base URL clears the saved key: type the key again, because a saved key is only sent
                    to the base URL it was saved with.
                  </p>
                </div>
              </div>
            </div>
          </section>


          {/* ── OpenAI Card ─────────────────────────────────────────────── */}
          <section
            className="rounded-xl overflow-hidden relative"
            style={glassCard}
          >
            <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-secondary to-tertiary" />
            <div className="p-6">
              <div className="flex items-center justify-between mb-8">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-lg bg-secondary/15 flex items-center justify-center text-secondary">
                    <span className="material-symbols-outlined text-2xl" style={{ fontVariationSettings: "'FILL' 1" }}>
                      smart_toy
                    </span>
                  </div>
                  <div>
                    <h3 className="font-headline text-lg font-bold text-on-surface">OpenAI (Responses API)</h3>
                    <div className="flex gap-2 mt-1">
                      <ConnectionBadge status={connectionStatuses["openai"]} />
                    </div>
                  </div>
                </div>
                <div className="flex gap-3 items-center">
                  <button
                    type="button"
                    disabled={
                      !hasTestableApiKey("openai") ||
                      connectionStatuses["openai"]?.status === "testing"
                    }
                    onClick={() => testConnection("openai")}
                    title={
                      hasTestableApiKey("openai")
                        ? "Asks OpenAI for its model list, which costs no tokens. With a saved key, the key is read on the server."
                        : "Enter an API key before testing."
                    }
                    className="px-4 py-2 text-xs font-bold font-headline rounded bg-transparent border border-outline-variant/30 text-on-surface hover:bg-surface-bright transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    Test Connection
                  </button>
                  <button
                    type="button"
                    disabled={
                      savingProvider !== null ||
                      !hasTestableApiKey("openai") ||
                      !isProviderDirty("openai")
                    }
                    onClick={() => handleSaveProvider("openai")}
                    className="px-6 py-2 text-xs font-bold font-headline rounded bg-primary-container text-on-primary-container hover:shadow-[0_0_15px_rgba(25,99,179,0.3)] transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {savingProvider === "openai" ? "Saving..." : "Save Changes"}
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-6">
                <MaskedKeyInput
                  id="openai-api-key"
                  label="API Key"
                  value={form.openaiApiKey}
                  onChange={(v) => updateField("openaiApiKey", v)}
                  placeholder="sk-proj-..."
                  helpText="An OpenAI API key (sk-). Stored encrypted; a saved key shows as dots and is never sent back to the browser. A restricted key must be allowed to list models and to make model requests."
                />
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="space-y-2">
                    <label
                      htmlFor="openai-organization"
                      className="block text-[11px] font-bold text-on-surface-variant uppercase tracking-widest font-label"
                    >
                      Organization (optional)
                    </label>
                    <div className="max-w-xl">
                      <input
                        id="openai-organization"
                        type="text"
                        value={form.openaiOrganization}
                        onChange={(e) => updateField("openaiOrganization", e.target.value)}
                        placeholder="org-..."
                        spellCheck={false}
                        autoComplete="off"
                        className="w-full bg-surface-container-lowest border-none rounded-lg px-4 py-3 text-sm font-mono text-on-surface focus:ring-1 focus:ring-primary/40 transition-all outline-none"
                      />
                    </div>
                    <p className="text-[10px] text-on-surface-variant/60 font-label">
                      Only needed when the key belongs to several organizations.
                    </p>
                  </div>
                  <div className="space-y-2">
                    <label
                      htmlFor="openai-project"
                      className="block text-[11px] font-bold text-on-surface-variant uppercase tracking-widest font-label"
                    >
                      Project (optional)
                    </label>
                    <div className="max-w-xl">
                      <input
                        id="openai-project"
                        type="text"
                        value={form.openaiProject}
                        onChange={(e) => updateField("openaiProject", e.target.value)}
                        placeholder="proj_..."
                        spellCheck={false}
                        autoComplete="off"
                        className="w-full bg-surface-container-lowest border-none rounded-lg px-4 py-3 text-sm font-mono text-on-surface focus:ring-1 focus:ring-primary/40 transition-all outline-none"
                      />
                    </div>
                    <p className="text-[10px] text-on-surface-variant/60 font-label">
                      Only needed when the key belongs to several projects.
                    </p>
                  </div>
                </div>
                <div className="space-y-2">
                  <label
                    htmlFor="openai-base-url"
                    className="block text-[11px] font-bold text-on-surface-variant uppercase tracking-widest font-label"
                  >
                    Base URL (optional)
                  </label>
                  <div className="max-w-xl">
                    <input
                      id="openai-base-url"
                      type="text"
                      value={form.openaiBaseUrl}
                      onChange={(e) => updateBaseUrl("openai", e.target.value)}
                      placeholder="https://api.openai.com/v1"
                      spellCheck={false}
                      autoComplete="off"
                      className="w-full bg-surface-container-lowest border-none rounded-lg px-4 py-3 text-sm font-mono text-on-surface focus:ring-1 focus:ring-primary/40 transition-all outline-none"
                    />
                  </div>
                  <p className="text-[10px] text-on-surface-variant/60 font-label">
                    Leave empty for <code className="font-mono">https://api.openai.com/v1</code>. Include the{" "}
                    <code className="font-mono">/v1</code> segment when you use your own gateway. HTTPS only; this
                    install&apos;s own services and link-local addresses are refused. Changing the base URL clears the saved
                    key: type the key again, because a saved key is only sent to the base URL it was saved with.
                  </p>
                </div>
              </div>
            </div>
          </section>
        </div>

        {/* ── Metadata Footer ─────────────────────────────────────────── */}
        <div className="mt-12 grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="rounded-xl p-4 flex items-center gap-4" style={glassCard}>
            <span className="material-symbols-outlined text-primary text-3xl">
              verified_user
            </span>
            <div>
              <p className="text-[10px] uppercase font-bold text-on-surface-variant tracking-widest">
                Security Protocol
              </p>
              <p className="text-sm font-bold text-on-surface">AES-256 Vault</p>
            </div>
          </div>
          <div className="rounded-xl p-4 flex items-center gap-4" style={glassCard}>
            <span className="material-symbols-outlined text-secondary text-3xl">
              hub
            </span>
            <div>
              <p className="text-[10px] uppercase font-bold text-on-surface-variant tracking-widest">
                Active Backends
              </p>
              <p className="text-sm font-bold text-on-surface">
                {Object.values(configured).filter(Boolean).length} of{" "}
                {Object.keys(configured).length} Configured
              </p>
            </div>
          </div>
          <div className="rounded-xl p-4 flex items-center gap-4" style={glassCard}>
            <span className="material-symbols-outlined text-tertiary text-3xl">
              history_toggle_off
            </span>
            <div>
              <p className="text-[10px] uppercase font-bold text-on-surface-variant tracking-widest">
                Last Connection Test
              </p>
              <p className="text-sm font-bold text-on-surface">
                {lastCheck
                  ? `${PROVIDER_LABEL[lastCheck.provider] ?? lastCheck.provider} ${lastCheck.ok ? "connected" : "failed"} at ${new Date(lastCheck.at).toLocaleTimeString()}`
                  : "Not run this session"}
              </p>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
