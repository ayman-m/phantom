"use client";

/**
 * Hooks settings
 *
 * Operator surface for managing chat-lifecycle hooks. Each hook is
 * a small policy contributor that fires at one of the 8 lifecycle
 * events (PreToolUse, PostToolUse, PostToolUseFailure,
 * UserPromptSubmit, PreCompact, PostCompact, RunStart, RunEnd).
 *
 * The page is a CRUD form over `/api/agent/hooks` (which proxies
 * to the MCP's `/api/v1/hooks`). Hooks are stored MCP-side so
 * everyone hitting the same Phantom deploy sees the same policy.
 *
 * Common patterns the form helps with:
 *
 *   - "Block any caldera_create_operation against production hosts
 *      until the on-call approves" → PreToolUse, command transport,
 *      failurePolicy:'block'
 *   - "Inject the active incident's ticket id into every chat" →
 *      UserPromptSubmit, http transport, returns
 *      `{injectContext: 'Active incident: INC-1234'}`
 *   - "Notify #soc-ops when XSIAM detection_validation_recorded
 *      fires" → PostToolUse, http transport (Slack webhook)
 */

import { useCallback, useEffect, useState } from "react";
import { confirmAction } from "@/lib/stores/confirm";
import { cn } from "@/lib/utils";

const HOOK_EVENTS = [
  "PreToolUse",
  "PostToolUse",
  "PostToolUseFailure",
  "UserPromptSubmit",
  "PreCompact",
  "PostCompact",
  "RunStart",
  "RunEnd",
  // Subagent lifecycle plus MCP-originated events (Notification,
  // PermissionRequest), which the MCP delivers through the agent's
  // internal fire-hook endpoint.
  "SubagentStart",
  "SubagentEnd",
  "Notification",
  "PermissionRequest",
] as const;
type HookEvent = (typeof HOOK_EVENTS)[number];

type TransportKind = "command" | "http" | "agent" | "builtin" | "plugin";

/** Mirror of `BuiltinConfigField` in `lib/hook-builtins/types.ts`. We
 *  duplicate the shape here rather than import from the lib because the
 *  page is a client component and the `lib/hook-builtins/index.ts` module
 *  pulls in the builtin handlers (which use node:child_process etc.).
 *  Keeping the UI's view of the catalog metadata-only avoids dragging
 *  server-side modules into the bundle. */
interface BuiltinConfigFieldMeta {
  key: string;
  label: string;
  type: "string" | "url" | "number" | "boolean" | "select" | "secret-ref";
  options?: Array<{ value: string; label: string }>;
  helper?: string;
  placeholder?: string;
  min?: number;
  max?: number;
  defaultValue?: unknown;
  required?: boolean;
}

interface BuiltinSpecMeta {
  name: string;
  displayName: string;
  description: string;
  icon: string;
  compatibleEvents: readonly string[];
  configFields: readonly BuiltinConfigFieldMeta[];
}

interface HookRow {
  id: string;
  name: string;
  description?: string;
  event: HookEvent;
  priority?: number;
  matcher?: { toolGlob?: string; triggerPrefix?: string };
  transport:
    | { type: "command"; command: string; cwd?: string; env?: Record<string, string> }
    | { type: "http"; url: string; headers?: Record<string, string> }
    | { type: "agent"; toolName: string }
    | { type: "builtin"; name: string; config: Record<string, unknown> }
    | {
        type: "plugin";
        handlerName: string;
        config?: Record<string, unknown>;
        timeoutS?: number;
      };
  timeoutMs?: number;
  failurePolicy?: "block" | "allow" | "warn";
  enabled?: boolean;
  createdAt?: string;
  updatedAt?: string;
}

const glassCard = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

export default function HooksPage() {
  const [hooks, setHooks] = useState<HookRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<HookRow | null>(null);
  const [adding, setAdding] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch("/api/agent/hooks", { cache: "no-store" });
      if (!r.ok) throw new Error(`hooks fetch ${r.status}`);
      const data = (await r.json()) as { hooks?: HookRow[] };
      setHooks(data.hooks ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleToggle = useCallback(
    async (id: string, enabled: boolean) => {
      try {
        const r = await fetch(`/api/agent/hooks/${encodeURIComponent(id)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled }),
        });
        if (!r.ok) throw new Error(`toggle ${r.status}`);
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [refresh],
  );

  const handleDelete = useCallback(
    async (id: string, name: string) => {
      const accepted = await confirmAction({
        title: `Delete hook "${name}"?`,
        message: "This is irreversible.",
        confirmLabel: "Delete",
        tone: "danger",
      });
      if (!accepted) return;
      try {
        const r = await fetch(`/api/agent/hooks/${encodeURIComponent(id)}`, {
          method: "DELETE",
        });
        if (!r.ok) throw new Error(`delete ${r.status}`);
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [refresh],
  );

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-8 space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <span className="material-symbols-outlined text-2xl text-primary">
                webhook
              </span>
              <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
                Hooks
              </h1>
            </div>
            <p className="text-sm text-on-surface-variant ml-9 max-w-2xl">
              Policy contributors that fire at chat-lifecycle events
              (tool calls, prompts, compaction, run start/end). Each hook
              runs through a transport (command, HTTP webhook) and may
              deny/ask/inject context. Configured here, executed
              transparently by every chat turn.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setEditing({
                id: crypto.randomUUID(),
                name: "",
                event: "PreToolUse",
                transport: { type: "http", url: "" },
                priority: 100,
                timeoutMs: 5000,
                failurePolicy: "warn",
                enabled: true,
              });
              setAdding(true);
            }}
            className="px-4 py-2 rounded-xl text-xs font-medium text-on-primary-container bg-primary-container/30 hover:bg-primary-container/50 transition-colors"
          >
            <span className="material-symbols-outlined text-base align-middle mr-1">
              add
            </span>
            Add hook
          </button>
        </div>

        {/* Error banner */}
        {error && (
          <div className="rounded-xl border border-error/30 bg-error/10 p-3 text-xs text-error">
            {error}
          </div>
        )}

        {/* List */}
        {loading ? (
          <div className="text-center py-16 text-sm text-on-surface-variant/60">
            Loading hooks…
          </div>
        ) : hooks.length === 0 ? (
          <div
            className="text-center py-12 rounded-2xl"
            style={glassCard}
          >
            <span className="material-symbols-outlined text-4xl text-on-surface-variant/40 mb-2 inline-block">
              webhook
            </span>
            <p className="text-sm font-medium text-on-surface mb-1">
              No hooks registered.
            </p>
            <p className="text-xs text-on-surface-variant/60 max-w-md mx-auto leading-relaxed">
              Add your first hook above. A common starter is the{" "}
              <span className="font-mono">slack-approval</span> built-in
              on PreToolUse — installs in seconds with just a webhook URL,
              routes destructive-tool approvals through your existing
              Slack #soc-ops channel.
            </p>
          </div>
        ) : (
          <div className="grid gap-3">
            {hooks.map((h) => (
              <HookRowCard
                key={h.id}
                hook={h}
                onToggle={handleToggle}
                onEdit={() => {
                  setEditing(h);
                  setAdding(false);
                }}
                onDelete={() => handleDelete(h.id, h.name)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Edit modal — inline drawer, pinned right */}
      {editing && (
        <HookEditor
          hook={editing}
          isNew={adding}
          onCancel={() => {
            setEditing(null);
            setAdding(false);
          }}
          onSaved={() => {
            setEditing(null);
            setAdding(false);
            void refresh();
          }}
        />
      )}
    </div>
  );
}

// ─── List row card ──────────────────────────────────────────────────

function HookRowCard({
  hook,
  onToggle,
  onEdit,
  onDelete,
}: {
  hook: HookRow;
  onToggle: (id: string, enabled: boolean) => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const enabled = hook.enabled !== false;
  const transportLabel =
    hook.transport.type === "http"
      ? `HTTP ${truncate(hook.transport.url, 60)}`
      : hook.transport.type === "command"
        ? `cmd ${truncate(hook.transport.command, 60)}`
        : hook.transport.type === "agent"
          ? `tool ${hook.transport.toolName}`
          : hook.transport.type === "plugin"
            ? `plugin ${hook.transport.handlerName}`
            : `builtin ${hook.transport.name}`;
  const transportBadge =
    hook.transport.type === "builtin"
      ? { label: "built-in", className: "bg-secondary/15 text-secondary" }
      : hook.transport.type === "http"
        ? { label: "http", className: "bg-primary/10 text-primary" }
        : hook.transport.type === "command"
          ? { label: "cmd", className: "bg-tertiary/10 text-tertiary" }
          : hook.transport.type === "plugin"
            ? { label: "plugin", className: "bg-tertiary/15 text-tertiary" }
            : { label: "agent", className: "bg-on-surface-variant/15 text-on-surface-variant" };
  return (
    <div
      className={cn(
        "rounded-2xl p-4 flex items-start gap-4 transition-opacity",
        !enabled && "opacity-60",
      )}
      style={glassCard}
    >
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label={enabled ? "Disable hook" : "Enable hook"}
        onClick={() => onToggle(hook.id, !enabled)}
        className={cn(
          "relative w-9 h-5 rounded-full transition-colors shrink-0 mt-1",
          enabled ? "bg-primary" : "bg-outline/30",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform",
            enabled ? "translate-x-4" : "translate-x-0.5",
          )}
        />
      </button>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1 flex-wrap">
          <span className="font-mono text-sm font-semibold text-on-surface truncate">
            {hook.name || "(unnamed)"}
          </span>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-primary/15 text-primary">
            {hook.event}
          </span>
          <span
            className={cn("text-[10px] font-mono px-1.5 py-0.5 rounded", transportBadge.className)}
            title={`Transport: ${hook.transport.type}`}
          >
            {transportBadge.label}
          </span>
          {hook.matcher?.toolGlob && (
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-tertiary/15 text-tertiary">
              tool:{hook.matcher.toolGlob}
            </span>
          )}
          {hook.failurePolicy === "block" && (
            <span
              className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-error/15 text-error"
              title="Hook errors deny the gated action"
            >
              fail-closed
            </span>
          )}
          <span className="text-[10px] font-mono text-on-surface-variant/60 ml-auto">
            priority {hook.priority ?? 100}
          </span>
        </div>
        {hook.description && (
          <p className="text-xs text-on-surface-variant mb-1.5">
            {hook.description}
          </p>
        )}
        <div className="text-[11px] text-on-surface-variant/70 font-mono">
          {transportLabel}
        </div>
      </div>
      <div className="flex flex-col gap-1.5 shrink-0">
        <button
          type="button"
          onClick={onEdit}
          aria-label="Edit hook"
          className="p-1.5 rounded hover:bg-white/5 text-on-surface-variant hover:text-on-surface transition-colors"
        >
          <span className="material-symbols-outlined text-lg">edit</span>
        </button>
        <button
          type="button"
          onClick={onDelete}
          aria-label="Delete hook"
          className="p-1.5 rounded hover:bg-white/5 text-on-surface-variant hover:text-error transition-colors"
        >
          <span className="material-symbols-outlined text-lg">delete</span>
        </button>
      </div>
    </div>
  );
}

// ─── Editor drawer ──────────────────────────────────────────────────

function HookEditor({
  hook,
  isNew,
  onCancel,
  onSaved,
}: {
  hook: HookRow;
  isNew: boolean;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<HookRow>(hook);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Builtin catalog — fetched once on editor open. Empty array while
  // loading + safe to render "no builtins available" if the fetch fails.
  const [builtins, setBuiltins] = useState<BuiltinSpecMeta[]>([]);
  const [builtinsLoading, setBuiltinsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/agent/hooks/builtins", { cache: "no-store" });
        if (!r.ok) throw new Error(`builtins fetch ${r.status}`);
        const data = (await r.json()) as { builtins?: BuiltinSpecMeta[] };
        if (!cancelled) setBuiltins(data.builtins ?? []);
      } catch (err) {
        if (!cancelled) {
          console.warn("hooks: failed to load builtin catalog:", err);
        }
      } finally {
        if (!cancelled) setBuiltinsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const update = useCallback(<K extends keyof HookRow>(key: K, value: HookRow[K]) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  }, []);

  const updateTransport = useCallback(
    (transport: HookRow["transport"]) => {
      setDraft((prev) => ({ ...prev, transport }));
    },
    [],
  );

  /** Apply a config-field default into the working draft when an operator
   *  picks a builtin. Each field's `defaultValue` (if any) seeds the
   *  starting config; the operator then edits in place. */
  const seedBuiltinConfig = useCallback(
    (spec: BuiltinSpecMeta): Record<string, unknown> => {
      const out: Record<string, unknown> = {};
      for (const field of spec.configFields) {
        if (field.defaultValue !== undefined) {
          out[field.key] = field.defaultValue;
        }
      }
      return out;
    },
    [],
  );

  const handleSave = useCallback(async () => {
    setError(null);
    if (!draft.name.trim()) {
      setError("Name is required.");
      return;
    }
    if (draft.transport.type === "http" && !draft.transport.url.trim()) {
      setError("HTTP transport requires a url.");
      return;
    }
    if (
      draft.transport.type === "command" &&
      !draft.transport.command.trim()
    ) {
      setError("Command transport requires a command.");
      return;
    }
    if (draft.transport.type === "builtin") {
      // Alias the narrowed transport so the closures below preserve the
      // discriminator (TS doesn't carry narrowing across `.find()` lambdas).
      const builtinTransport = draft.transport;
      if (!builtinTransport.name) {
        setError("Built-in transport requires a name selection.");
        return;
      }
      const spec = builtins.find((b) => b.name === builtinTransport.name);
      if (!spec) {
        setError(`Built-in '${builtinTransport.name}' is not available in this image.`);
        return;
      }
      // Pre-check required fields client-side. The agent-side
      // validateConfig is still the source of truth for the full
      // shape (URL parsing, etc.); this just gives the operator
      // immediate feedback before the round-trip.
      for (const field of spec.configFields) {
        if (field.required) {
          const v = (builtinTransport.config ?? {})[field.key];
          if (v === undefined || v === null || (typeof v === "string" && !v.trim())) {
            setError(`Built-in '${spec.displayName}' requires "${field.label}".`);
            return;
          }
        }
      }
    }
    if (draft.transport.type === "plugin") {
      if (!draft.transport.handlerName?.trim()) {
        setError("Plugin transport requires a handler-name selection.");
        return;
      }
    }
    setSaving(true);
    try {
      const r = isNew
        ? await fetch("/api/agent/hooks", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(draft),
          })
        : await fetch(`/api/agent/hooks/${encodeURIComponent(draft.id)}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(draft),
          });
      if (!r.ok) {
        const text = await r.text().catch(() => "");
        throw new Error(`save ${r.status}: ${text.slice(0, 200)}`);
      }
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }, [draft, isNew, onSaved, builtins]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-stretch justify-end bg-black/40"
      onClick={onCancel}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-xl h-full overflow-y-auto p-6 space-y-4 custom-scrollbar"
        style={{
          background: "var(--m3-surface-container)",
          borderLeft: "0.5px solid var(--glass-border)",
        }}
      >
        <div className="flex items-center justify-between">
          <h2 className="font-headline text-xl font-bold text-on-surface">
            {isNew ? "New hook" : "Edit hook"}
          </h2>
          <button
            type="button"
            onClick={onCancel}
            aria-label="Close editor"
            className="p-1.5 rounded hover:bg-white/5 text-on-surface-variant hover:text-on-surface"
          >
            <span className="material-symbols-outlined text-lg">close</span>
          </button>
        </div>

        <Field label="Name">
          <input
            type="text"
            value={draft.name}
            onChange={(e) => update("name", e.target.value)}
            className="input-base"
            placeholder='e.g. "block prod caldera ops"'
          />
        </Field>

        <Field label="Description (optional)">
          <input
            type="text"
            value={draft.description ?? ""}
            onChange={(e) => update("description", e.target.value)}
            className="input-base"
          />
        </Field>

        <Field label="Event">
          <select
            value={draft.event}
            onChange={(e) =>
              update("event", e.target.value as HookEvent)
            }
            className="input-base"
          >
            {HOOK_EVENTS.map((ev) => (
              <option key={ev} value={ev}>
                {ev}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Tool glob (optional, only for PreToolUse / PostToolUse)">
          <input
            type="text"
            value={draft.matcher?.toolGlob ?? ""}
            onChange={(e) =>
              update("matcher", {
                ...(draft.matcher ?? {}),
                toolGlob: e.target.value || undefined,
              })
            }
            className="input-base font-mono"
            placeholder="e.g. caldera_*, xsiam_*"
          />
        </Field>

        <Field label="Trigger prefix (optional)">
          <input
            type="text"
            value={draft.matcher?.triggerPrefix ?? ""}
            onChange={(e) =>
              update("matcher", {
                ...(draft.matcher ?? {}),
                triggerPrefix: e.target.value || undefined,
              })
            }
            className="input-base font-mono"
            placeholder="e.g. job: (only fires for scheduled runs)"
          />
        </Field>

        <Field label="Transport">
          <select
            value={draft.transport.type}
            onChange={(e) => {
              const t = e.target.value as TransportKind;
              if (t === "http") {
                updateTransport({ type: "http", url: "" });
              } else if (t === "command") {
                updateTransport({ type: "command", command: "" });
              } else if (t === "builtin") {
                // Default to the first registered builtin if available;
                // operator can change. When no builtins are loaded yet,
                // store an empty name + config — the form will surface
                // a "loading…" placeholder + block save in handleSave.
                const first = builtins[0];
                updateTransport({
                  type: "builtin",
                  name: first?.name ?? "",
                  config: first ? seedBuiltinConfig(first) : {},
                });
              } else if (t === "plugin") {
                updateTransport({
                  type: "plugin",
                  handlerName: "",
                  config: {},
                });
              } else {
                updateTransport({ type: "agent", toolName: "" });
              }
            }}
            className="input-base"
          >
            <option value="builtin">Built-in (in-process, no subprocess)</option>
            <option value="plugin">Plugin handler (entry-point)</option>
            <option value="http">HTTP webhook</option>
            <option value="command">Shell command</option>
            <option value="agent">Agent tool (reserved, MCP-tool dispatch)</option>
          </select>
        </Field>

        {draft.transport.type === "http" && (
          <Field label="URL">
            <input
              type="url"
              value={draft.transport.url}
              onChange={(e) =>
                updateTransport({
                  type: "http",
                  url: e.target.value,
                  headers:
                    draft.transport.type === "http"
                      ? draft.transport.headers
                      : undefined,
                })
              }
              className="input-base font-mono"
              placeholder="https://hooks.slack.com/services/..."
            />
          </Field>
        )}

        {draft.transport.type === "command" && (
          <Field label="Command">
            <input
              type="text"
              value={draft.transport.command}
              onChange={(e) =>
                updateTransport({
                  type: "command",
                  command: e.target.value,
                  cwd:
                    draft.transport.type === "command"
                      ? draft.transport.cwd
                      : undefined,
                  env:
                    draft.transport.type === "command"
                      ? draft.transport.env
                      : undefined,
                })
              }
              className="input-base font-mono"
              placeholder='e.g. /usr/local/bin/policy-check.sh'
            />
          </Field>
        )}

        {draft.transport.type === "agent" && (
          <Field label="Tool name">
            <input
              type="text"
              value={draft.transport.toolName}
              onChange={(e) =>
                updateTransport({
                  type: "agent",
                  toolName: e.target.value,
                })
              }
              className="input-base font-mono"
              placeholder="e.g. plugin_corp_policy_check"
            />
          </Field>
        )}

        {draft.transport.type === "builtin" && (
          <BuiltinConfigSection
            transport={draft.transport}
            builtins={builtins}
            builtinsLoading={builtinsLoading}
            onPickSpec={(spec) =>
              updateTransport({
                type: "builtin",
                name: spec.name,
                config: seedBuiltinConfig(spec),
              })
            }
            onConfigChange={(config) =>
              updateTransport({
                type: "builtin",
                name:
                  draft.transport.type === "builtin"
                    ? draft.transport.name
                    : "",
                config,
              })
            }
          />
        )}

        {draft.transport.type === "plugin" && (
          <PluginHandlerConfigSection
            transport={draft.transport}
            onPick={(handlerName) =>
              updateTransport({
                type: "plugin",
                handlerName,
                config:
                  draft.transport.type === "plugin"
                    ? (draft.transport.config ?? {})
                    : {},
                timeoutS:
                  draft.transport.type === "plugin"
                    ? draft.transport.timeoutS
                    : undefined,
              })
            }
            onConfigChange={(parsed) =>
              updateTransport({
                type: "plugin",
                handlerName:
                  draft.transport.type === "plugin"
                    ? draft.transport.handlerName
                    : "",
                config: parsed,
                timeoutS:
                  draft.transport.type === "plugin"
                    ? draft.transport.timeoutS
                    : undefined,
              })
            }
            onTimeoutChange={(timeoutS) =>
              updateTransport({
                type: "plugin",
                handlerName:
                  draft.transport.type === "plugin"
                    ? draft.transport.handlerName
                    : "",
                config:
                  draft.transport.type === "plugin"
                    ? (draft.transport.config ?? {})
                    : {},
                timeoutS,
              })
            }
          />
        )}

        <div className="grid grid-cols-2 gap-3">
          <Field label="Priority (lower runs first)">
            <input
              type="number"
              min={0}
              max={1000}
              value={draft.priority ?? 100}
              onChange={(e) =>
                update("priority", Number(e.target.value) || 100)
              }
              className="input-base"
            />
          </Field>
          <Field label="Timeout (ms)">
            <input
              type="number"
              min={100}
              max={60000}
              value={draft.timeoutMs ?? 5000}
              onChange={(e) =>
                update("timeoutMs", Number(e.target.value) || 5000)
              }
              className="input-base"
            />
          </Field>
        </div>

        <Field label="Failure policy">
          <select
            value={draft.failurePolicy ?? "warn"}
            onChange={(e) =>
              update(
                "failurePolicy",
                e.target.value as HookRow["failurePolicy"],
              )
            }
            className="input-base"
          >
            <option value="warn">warn — log + allow (most lenient)</option>
            <option value="allow">allow — silent no-op on error</option>
            <option value="block">block — deny on error (strict)</option>
          </select>
        </Field>

        {error && (
          <div className="rounded-xl border border-error/30 bg-error/10 p-3 text-xs text-error">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="px-4 py-2 rounded-xl text-xs font-medium text-on-surface-variant hover:text-on-surface hover:bg-white/5 transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving}
            className="px-4 py-2 rounded-xl text-xs font-medium text-on-primary-container bg-primary-container/30 hover:bg-primary-container/50 transition-colors disabled:opacity-50"
          >
            {saving ? "Saving…" : isNew ? "Create" : "Save"}
          </button>
        </div>

        <style jsx>{`
          .input-base {
            width: 100%;
            padding: 0.625rem 0.75rem;
            border-radius: 0.75rem;
            font-size: 0.8125rem;
            color: var(--m3-on-surface);
            background: var(--m3-surface-container-low);
            border: 0.5px solid var(--glass-border);
            outline: none;
            font-family: inherit;
          }
          .input-base:focus {
            border-color: rgba(25, 99, 179, 0.4);
            box-shadow: 0 0 0 2px rgba(25, 99, 179, 0.15);
          }
        `}</style>
      </div>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-label text-on-surface-variant/80">
        {label}
      </label>
      {children}
    </div>
  );
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  return s.slice(0, n - 1) + "…";
}

// ─── Builtin config form ────────────────────────────────────────────

/**
 * Renders the builtin picker + dynamic config form for the chosen
 * builtin. The picker is a dropdown of registered builtins; selecting
 * one swaps the dynamic form below to that builtin's `configFields`.
 *
 * Each config-field type maps to one input shape:
 *   - "string" / "url" → text input
 *   - "secret-ref" → text input with a "secret:<NAME>" hint
 *   - "number" → number input (clamped by min/max)
 *   - "boolean" → checkbox
 *   - "select" → dropdown of provided options
 *
 * The agent-side `validateConfig` re-validates server-side; this form
 * is operator-affordance, not security boundary.
 */
function BuiltinConfigSection({
  transport,
  builtins,
  builtinsLoading,
  onPickSpec,
  onConfigChange,
}: {
  transport: Extract<HookRow["transport"], { type: "builtin" }>;
  builtins: BuiltinSpecMeta[];
  builtinsLoading: boolean;
  onPickSpec: (spec: BuiltinSpecMeta) => void;
  onConfigChange: (config: Record<string, unknown>) => void;
}) {
  const selectedSpec = builtins.find((b) => b.name === transport.name);

  if (builtinsLoading) {
    return (
      <div className="rounded-xl border border-outline/20 bg-surface-container-low/40 p-3 text-xs text-on-surface-variant">
        Loading built-in registry…
      </div>
    );
  }
  if (builtins.length === 0) {
    return (
      <div className="rounded-xl border border-error/30 bg-error/10 p-3 text-xs text-error">
        No built-ins are registered in this image. Pick a different transport
        or check that <code>/api/agent/hooks/builtins</code> is reachable.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <Field label="Built-in">
        <select
          value={transport.name}
          onChange={(e) => {
            const spec = builtins.find((b) => b.name === e.target.value);
            if (spec) onPickSpec(spec);
          }}
          className="input-base"
        >
          {builtins.map((spec) => (
            <option key={spec.name} value={spec.name}>
              {spec.displayName}
            </option>
          ))}
        </select>
      </Field>

      {selectedSpec && (
        <>
          <div className="rounded-xl border border-outline/20 bg-surface-container-low/40 p-3 text-xs text-on-surface-variant leading-relaxed">
            <span className="material-symbols-outlined text-sm align-middle mr-1 text-secondary">
              {selectedSpec.icon || "info"}
            </span>
            {selectedSpec.description}
          </div>

          {selectedSpec.configFields.length === 0 && (
            <p className="text-xs text-on-surface-variant/70 italic">
              This built-in has no configuration fields.
            </p>
          )}

          {selectedSpec.configFields.map((field) => (
            <BuiltinConfigField
              key={field.key}
              field={field}
              value={transport.config[field.key]}
              onChange={(v) =>
                onConfigChange({ ...transport.config, [field.key]: v })
              }
            />
          ))}
        </>
      )}
    </div>
  );
}

function BuiltinConfigField({
  field,
  value,
  onChange,
}: {
  field: BuiltinConfigFieldMeta;
  value: unknown;
  onChange: (next: unknown) => void;
}) {
  const labelWithRequired = field.required ? `${field.label} *` : field.label;

  if (field.type === "boolean") {
    return (
      <div className="flex items-start gap-2 pt-1">
        <input
          type="checkbox"
          checked={value === true}
          onChange={(e) => onChange(e.target.checked)}
          className="mt-0.5 w-4 h-4 rounded accent-primary"
        />
        <div className="flex-1">
          <label className="text-xs font-label text-on-surface-variant/80">
            {labelWithRequired}
          </label>
          {field.helper && (
            <p className="text-[11px] text-on-surface-variant/60 mt-0.5">
              {field.helper}
            </p>
          )}
        </div>
      </div>
    );
  }

  if (field.type === "number") {
    return (
      <Field label={labelWithRequired}>
        <input
          type="number"
          value={typeof value === "number" ? value : ""}
          min={field.min}
          max={field.max}
          onChange={(e) =>
            onChange(e.target.value === "" ? undefined : Number(e.target.value))
          }
          className="input-base font-mono"
          placeholder={field.placeholder}
        />
        {field.helper && (
          <p className="text-[11px] text-on-surface-variant/60 mt-0.5">
            {field.helper}
          </p>
        )}
      </Field>
    );
  }

  if (field.type === "select") {
    return (
      <Field label={labelWithRequired}>
        <select
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          className="input-base"
        >
          <option value="">(pick one)</option>
          {(field.options ?? []).map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        {field.helper && (
          <p className="text-[11px] text-on-surface-variant/60 mt-0.5">
            {field.helper}
          </p>
        )}
      </Field>
    );
  }

  // string / url / secret-ref — all rendered as text inputs.
  return (
    <Field label={labelWithRequired}>
      <input
        type={field.type === "url" ? "url" : "text"}
        value={typeof value === "string" ? value : ""}
        onChange={(e) => onChange(e.target.value)}
        className="input-base font-mono"
        placeholder={field.placeholder}
      />
      {field.helper && (
        <p className="text-[11px] text-on-surface-variant/60 mt-0.5">
          {field.helper}
        </p>
      )}
    </Field>
  );
}

/**
 * Plugin-handler transport config UI.
 *
 * Plugin handlers come from the entry-point system (phantom.hooks
 * group). Schema is plugin-defined — we can't introspect a Python
 * entry-point's config shape from TS, so we ship a generic JSON
 * editor + a dropdown of discovered handlers. The plugin author
 * documents their own config contract; the operator types JSON.
 *
 * Discovery: GET /api/agent/plugin-hooks. Refreshes whenever the
 * operator clicks Refresh (handler installs after page-load aren't
 * picked up otherwise).
 */
function PluginHandlerConfigSection({
  transport,
  onPick,
  onConfigChange,
  onTimeoutChange,
}: {
  transport: Extract<HookRow["transport"], { type: "plugin" }>;
  onPick: (handlerName: string) => void;
  onConfigChange: (parsed: Record<string, unknown>) => void;
  onTimeoutChange: (timeoutS: number | undefined) => void;
}) {
  const [handlers, setHandlers] = useState<
    { name: string; dist_name: string; dist_version: string; target: string }[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [configJson, setConfigJson] = useState(
    JSON.stringify(transport.config ?? {}, null, 2),
  );
  const [jsonErr, setJsonErr] = useState<string | null>(null);

  const refresh = useCallback(
    async (force: boolean = false) => {
      setLoading(true);
      setError(null);
      try {
        const url = force
          ? "/api/agent/plugin-hooks?refresh=1"
          : "/api/agent/plugin-hooks";
        const r = await fetch(url, { cache: "no-store" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = (await r.json()) as {
          handlers?: typeof handlers;
        };
        setHandlers(data.handlers ?? []);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    },
    [],
  );
  useEffect(() => {
    void refresh(false);
  }, [refresh]);

  const handleConfigChange = (v: string) => {
    setConfigJson(v);
    try {
      const parsed = JSON.parse(v) as Record<string, unknown>;
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
        setJsonErr("Config must be a JSON object.");
        return;
      }
      setJsonErr(null);
      onConfigChange(parsed);
    } catch (err) {
      setJsonErr(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="rounded-xl border border-outline/20 bg-surface-container-low/40 p-3 space-y-3">
      <div className="flex items-center gap-2">
        <span className="material-symbols-outlined text-sm text-tertiary">
          extension
        </span>
        <span className="text-xs font-semibold text-on-surface">
          Plugin handler
        </span>
        <button
          type="button"
          onClick={() => void refresh(true)}
          className="ml-auto text-[10px] px-2 py-0.5 rounded border border-outline/30 text-on-surface-variant hover:bg-white/5"
          title="Re-walk entry-points (use after installing a plugin)"
        >
          Refresh
        </button>
      </div>

      {error && (
        <div className="text-xs text-error">Discovery failed: {error}</div>
      )}

      <Field label="Handler">
        {loading ? (
          <div className="text-xs text-on-surface-variant/60 italic">
            Loading registered handlers…
          </div>
        ) : handlers.length === 0 ? (
          <div className="rounded border border-outline/20 bg-surface-container-low/40 p-2 text-xs text-on-surface-variant/70">
            No plugin handlers discovered. Install a package targeting the{" "}
            <code className="font-mono">phantom.hooks</code> entry-point group
            at{" "}
            <a
              href="/observability/plugins"
              className="link"
              target="_blank"
              rel="noreferrer"
            >
              /observability/plugins
            </a>
            , then click Refresh.
          </div>
        ) : (
          <select
            value={transport.handlerName}
            onChange={(e) => onPick(e.target.value)}
            className="input-base font-mono"
          >
            <option value="">— pick a handler —</option>
            {handlers.map((h) => (
              <option key={h.name} value={h.name}>
                {h.name} ({h.dist_name || "unknown"} {h.dist_version})
              </option>
            ))}
          </select>
        )}
      </Field>

      <Field label="Config (JSON object)">
        <textarea
          value={configJson}
          onChange={(e) => handleConfigChange(e.target.value)}
          rows={6}
          className="input-base font-mono text-xs"
          placeholder='{"key": "value"}'
        />
        {jsonErr && (
          <p className="text-xs text-error mt-1">JSON error: {jsonErr}</p>
        )}
        <p className="text-[11px] text-on-surface-variant/60 mt-1">
          Schema is plugin-defined. Check the plugin&apos;s README for required
          fields.
        </p>
      </Field>

      <Field label="Timeout (seconds, optional)">
        <input
          type="number"
          min={1}
          max={60}
          value={transport.timeoutS ?? ""}
          onChange={(e) => {
            const n = Number(e.target.value);
            onTimeoutChange(Number.isFinite(n) && n > 0 ? n : undefined);
          }}
          className="input-base"
          placeholder="5"
        />
        <p className="text-[11px] text-on-surface-variant/60 mt-1">
          MCP-side cap of 60s applies regardless. The hook&apos;s overall
          timeout (ms) above also bounds the fetch on the agent side.
        </p>
      </Field>
    </div>
  );
}
