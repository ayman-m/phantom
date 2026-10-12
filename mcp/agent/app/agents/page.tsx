"use client";

/**
 * /agents
 *
 * Operator surface for the agent-definition registry. List
 * (operator + plugin + builtin) definitions, toggle enable, edit,
 * delete, view recent runs (subagent task history).
 *
 * The model invokes subagent_create with one of these definitions
 * inside chat — operators don't typically run subagents directly
 * from this page (though /tasks can show recent runs and link to
 * their sidechain transcripts).
 */

import { useCallback, useEffect, useState } from "react";
import { confirmAction } from "@/lib/stores/confirm";
import Link from "next/link";
import { cn } from "@/lib/utils";
import {
  deleteAgentDefinition,
  listAgentDefinitions,
  originBadgeTone,
  patchAgentDefinition,
  upsertAgentDefinition,
  type AgentDefinition,
} from "@/lib/api/agent-definitions";

const glassCard = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

export default function AgentsPage() {
  const [defs, setDefs] = useState<AgentDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<AgentDefinition | null>(null);
  const [adding, setAdding] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listAgentDefinitions();
      setDefs(data.agent_definitions);
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
        await patchAgentDefinition(id, { enabled });
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
        title: `Delete agent "${name}"?`,
        message:
          "Plugin-contributed agents will reappear on the next plugin reload.",
        confirmLabel: "Delete",
        tone: "danger",
      });
      if (!accepted) return;
      try {
        await deleteAgentDefinition(id);
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
        {/* Header — matches /skills layout pattern */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <span className="material-symbols-outlined text-2xl text-primary">
                groups
              </span>
              <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
                Agents
              </h1>
            </div>
            <p className="text-sm text-on-surface-variant ml-9">
              Subagent definitions — system prompt + scoped tool catalog. Spawned via <code className="font-mono">subagent_create</code>; runs appear in <Link href="/tasks" className="link">/tasks</Link>.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setEditing({
                id: crypto.randomUUID(),
                name: "",
                description: "",
                system_prompt: "",
                tools_allowed: [],
                tools_denied: [],
                model: null,
                max_turns: 10,
                isolation: "fresh_session",
                origin: "operator",
                enabled: true,
                created_at: "",
                updated_at: "",
              });
              setAdding(true);
            }}
            className="px-4 py-2 rounded-xl text-xs font-medium text-on-primary-container bg-primary-container/30 hover:bg-primary-container/50 transition-colors"
          >
            <span className="material-symbols-outlined text-base align-middle mr-1">
              add
            </span>
            New agent
          </button>
        </div>

        {error && (
          <div className="rounded-xl border border-error/30 bg-error/10 p-3 text-xs text-error">
            {error}
          </div>
        )}

        {loading ? (
          <div className="text-center py-16 text-sm text-on-surface-variant/60">
            Loading agents…
          </div>
        ) : defs.length === 0 ? (
          <div
            className="text-center py-12 rounded-2xl"
            style={glassCard}
          >
            <span className="material-symbols-outlined text-4xl text-on-surface-variant/40 mb-2 inline-block">
              groups
            </span>
            <p className="text-sm font-medium text-on-surface mb-1">
              No agents registered.
            </p>
            <p className="text-xs text-on-surface-variant/60 max-w-md mx-auto leading-relaxed">
              Add an agent above, OR drop a plugin under{" "}
              <code className="font-mono">bundles/spark/plugins/</code>{" "}
              with an{" "}
              <code className="font-mono">agents:</code> block. The
              reference plugin <code className="font-mono">example-vendor</code>{" "}
              ships three: red-team-emulator, blue-team-validator,
              coverage-reporter.
            </p>
          </div>
        ) : (
          <div className="grid gap-2">
            {defs.map((d) => (
              <AgentRowCard
                key={d.id}
                def={d}
                onToggle={handleToggle}
                onEdit={() => {
                  setEditing(d);
                  setAdding(false);
                }}
                onDelete={() => handleDelete(d.id, d.name)}
              />
            ))}
          </div>
        )}
      </div>

      {editing && (
        <AgentEditor
          def={editing}
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

function AgentRowCard({
  def,
  onToggle,
  onEdit,
  onDelete,
}: {
  def: AgentDefinition;
  onToggle: (id: string, enabled: boolean) => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const tone = originBadgeTone(def.origin);
  return (
    <div
      className={cn(
        "rounded-2xl p-4 flex items-start gap-3 transition-opacity",
        !def.enabled && "opacity-60",
      )}
      style={glassCard}
    >
      <button
        type="button"
        role="switch"
        aria-checked={def.enabled}
        aria-label={def.enabled ? "Disable agent" : "Enable agent"}
        onClick={() => onToggle(def.id, !def.enabled)}
        className={cn(
          "relative w-9 h-5 rounded-full transition-colors shrink-0 mt-1",
          def.enabled ? "bg-primary" : "bg-outline/30",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform",
            def.enabled ? "translate-x-4" : "translate-x-0.5",
          )}
        />
      </button>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1 flex-wrap">
          <span className="font-mono text-sm font-semibold text-on-surface truncate">
            {def.name}
          </span>
          <span
            className={cn(
              "text-[10px] font-mono px-1.5 py-0.5 rounded",
              tone.bg,
              tone.fg,
            )}
            title={`Origin: ${def.origin}`}
          >
            {tone.label}
          </span>
          {def.model && (
            <span
              className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/5 text-on-surface-variant"
              title="Model override"
            >
              {def.model}
            </span>
          )}
          <span
            className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/5 text-on-surface-variant"
            title="Max turns budget"
          >
            ≤{def.max_turns} turns
          </span>
        </div>
        {def.description && (
          <p className="text-xs text-on-surface-variant mb-1.5 leading-relaxed">
            {def.description}
          </p>
        )}
        <div className="flex items-center gap-2 text-[11px] font-mono text-on-surface-variant/70 flex-wrap">
          {def.tools_allowed.length > 0 ? (
            <>
              <span title="Tools allowed (glob list)">
                <span className="material-symbols-outlined text-[12px] align-middle mr-0.5 text-secondary">
                  check_circle
                </span>
                {def.tools_allowed.length === 1
                  ? def.tools_allowed[0]
                  : `${def.tools_allowed.length} allow patterns`}
              </span>
            </>
          ) : (
            <span className="text-error">
              <span className="material-symbols-outlined text-[12px] align-middle mr-0.5">
                warning
              </span>
              No allowlist (sees ALL tools)
            </span>
          )}
          {def.tools_denied.length > 0 && (
            <span title="Tools denied">
              <span className="material-symbols-outlined text-[12px] align-middle mr-0.5 text-error/80">
                block
              </span>
              {def.tools_denied.length} deny patterns
            </span>
          )}
        </div>
      </div>
      <div className="flex flex-col gap-1.5 shrink-0">
        <button
          type="button"
          onClick={onEdit}
          aria-label="Edit agent"
          className="p-1.5 rounded hover:bg-white/5 text-on-surface-variant hover:text-on-surface transition-colors"
        >
          <span className="material-symbols-outlined text-lg">edit</span>
        </button>
        <button
          type="button"
          onClick={onDelete}
          aria-label="Delete agent"
          className="p-1.5 rounded hover:bg-white/5 text-on-surface-variant hover:text-error transition-colors"
        >
          <span className="material-symbols-outlined text-lg">delete</span>
        </button>
      </div>
    </div>
  );
}

function AgentEditor({
  def,
  isNew,
  onCancel,
  onSaved,
}: {
  def: AgentDefinition;
  isNew: boolean;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<AgentDefinition>(def);
  const [allowedText, setAllowedText] = useState(
    def.tools_allowed.join("\n"),
  );
  const [deniedText, setDeniedText] = useState(
    def.tools_denied.join("\n"),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = useCallback(async () => {
    setError(null);
    if (!draft.name.trim()) {
      setError("Name is required.");
      return;
    }
    if (!draft.system_prompt.trim()) {
      setError("System prompt is required.");
      return;
    }
    setSaving(true);
    try {
      const body: Partial<AgentDefinition> = {
        ...draft,
        tools_allowed: allowedText
          .split("\n")
          .map((s) => s.trim())
          .filter((s) => s.length > 0),
        tools_denied: deniedText
          .split("\n")
          .map((s) => s.trim())
          .filter((s) => s.length > 0),
      };
      if (isNew) {
        await upsertAgentDefinition(body);
      } else {
        await patchAgentDefinition(draft.id, body);
      }
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }, [draft, allowedText, deniedText, isNew, onSaved]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-stretch justify-end bg-black/40"
      onClick={onCancel}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl h-full overflow-y-auto p-6 space-y-4 custom-scrollbar"
        style={{
          background: "var(--m3-surface-container)",
          borderLeft: "0.5px solid var(--glass-border)",
        }}
      >
        <div className="flex items-center justify-between">
          <h2 className="font-headline text-xl font-bold text-on-surface">
            {isNew ? "New agent" : `Edit ${draft.name}`}
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

        {draft.origin.startsWith("plugin:") && !isNew && (
          <div className="rounded-xl border border-tertiary/30 bg-tertiary/10 p-3 text-xs text-tertiary">
            <span className="material-symbols-outlined text-sm align-middle mr-1">
              info
            </span>
            This agent comes from{" "}
            <code className="font-mono">{draft.origin}</code>. Edits
            here persist, but a plugin reload will overwrite them.
            For permanent changes, clone via &ldquo;New agent&rdquo; with
            origin=operator.
          </div>
        )}

        <Field label="Name (unique identifier)">
          <input
            type="text"
            value={draft.name}
            onChange={(e) => setDraft((p) => ({ ...p, name: e.target.value }))}
            disabled={!isNew}
            className="input-base font-mono"
            placeholder="e.g. red-team-emulator"
          />
        </Field>

        <Field label="Description">
          <input
            type="text"
            value={draft.description}
            onChange={(e) =>
              setDraft((p) => ({ ...p, description: e.target.value }))
            }
            className="input-base"
          />
        </Field>

        <Field label="System prompt">
          <textarea
            value={draft.system_prompt}
            onChange={(e) =>
              setDraft((p) => ({ ...p, system_prompt: e.target.value }))
            }
            className="input-base font-body min-h-[200px]"
            placeholder="The system instruction the subagent runs with…"
          />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Tools allowed (one glob per line; empty = all)">
            <textarea
              value={allowedText}
              onChange={(e) => setAllowedText(e.target.value)}
              className="input-base font-mono min-h-[120px]"
              placeholder={"caldera_*\nxsiam_get_*"}
            />
          </Field>
          <Field label="Tools denied (one glob per line)">
            <textarea
              value={deniedText}
              onChange={(e) => setDeniedText(e.target.value)}
              className="input-base font-mono min-h-[120px]"
              placeholder={"*_delete\ncaldera_delete_*"}
            />
          </Field>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <Field label="Max turns (1-50)">
            <input
              type="number"
              min={1}
              max={50}
              value={draft.max_turns}
              onChange={(e) =>
                setDraft((p) => ({
                  ...p,
                  max_turns: Number(e.target.value) || 10,
                }))
              }
              className="input-base"
            />
          </Field>
          <Field label="Isolation">
            <select
              value={draft.isolation}
              onChange={(e) =>
                setDraft((p) => ({
                  ...p,
                  isolation: e.target.value as
                    | "fresh_session"
                    | "parent_session",
                }))
              }
              className="input-base"
            >
              <option value="fresh_session">fresh_session (default)</option>
              <option value="parent_session">parent_session (advanced)</option>
            </select>
          </Field>
          <Field label="Model override (empty = inherit)">
            <input
              type="text"
              value={draft.model ?? ""}
              onChange={(e) =>
                setDraft((p) => ({
                  ...p,
                  model: e.target.value || null,
                }))
              }
              className="input-base font-mono"
              placeholder="(inherit)"
            />
          </Field>
        </div>

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
          .input-base:disabled {
            opacity: 0.6;
            cursor: not-allowed;
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
