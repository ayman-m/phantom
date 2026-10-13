"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { isRecord, resolveConfig, type ActionPolicy, type AgentConfig } from "@/lib/personality-config";
import { cn } from "@/lib/utils";

/**
 * Phantom personality page. Persists one JSON blob through
 * /api/agent/personality (the MCP's SqlitePersonalityStore), debounced
 * 600ms after the last change so a burst of edits doesn't flood the MCP.
 *
 * Fields read at runtime:
 *   - actionPolicy  -> app/api/chat/route.ts (fetchPersonalityForPrompt)
 *   - personalityMd -> lib/system-prompt.ts (renderPersonaBlock)
 * Do not add a control here unless something reads the value. Keys that
 * an older install stored but this page no longer shows are dropped on
 * load (see PAGE_KEYS) and disappear from the stored blob on the next save.
 *
 * The page carries no defaults of its own. The canonical default document
 * is DEFAULT_PERSONALITY in the MCP's personality_store.py; the page reads
 * it from /api/agent/personality/defaults to fill any key a stored blob
 * lacks and for Reset Defaults.
 */

// ─── Glass Style Constants ───────────────────────────────────────────────────

const glassCard = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

// ─── Page Component ──────────────────────────────────────────────────────────

// Personality persists as a single JSON blob via /api/agent/personality
// (the MCP's SqlitePersonalityStore). No packing/unpacking: the wire
// payload matches AgentConfig 1:1.

async function fetchPersonalityDoc(url: string): Promise<Record<string, unknown>> {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${url} returned ${r.status}`);
  const data = (await r.json()) as { personality?: unknown };
  return isRecord(data.personality) ? data.personality : {};
}

export default function PersonalityPage() {
  // null until the stored blob and the defaults have both loaded. Nothing
  // renders (and nothing can auto-save) before that, so a failed load can
  // never overwrite the stored persona with a half-built document.
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const configRef = useRef<AgentConfig | null>(null);
  const defaultsRef = useRef<Record<string, unknown> | null>(null);

  // Initial load: take the stored blob and the defaults, keep only the
  // keys this page owns, and lay the stored values over the defaults so a
  // missing field keeps its default.
  const load = useCallback(async (isCancelled: () => boolean = () => false) => {
    setLoadError(null);
    try {
      const [defaults, stored] = await Promise.all([
        fetchPersonalityDoc("/api/agent/personality/defaults"),
        fetchPersonalityDoc("/api/agent/personality"),
      ]);
      const merged = resolveConfig(defaults, stored);
      if (!merged) throw new Error("the default personality is incomplete");
      if (isCancelled()) return;
      defaultsRef.current = defaults;
      configRef.current = merged;
      setConfig(merged);
    } catch (err) {
      if (!isCancelled()) {
        setLoadError(err instanceof Error ? err.message : "could not load the personality");
      }
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void load(() => cancelled);
    return () => {
      cancelled = true;
    };
  }, [load]);

  // Real auto-save: debounced 600ms after the last change, so typing in
  // the editor does not send one PUT per keystroke.
  const triggerSave = useCallback(() => {
    setSaveStatus("saving");
    setErrorMessage(null);
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    saveTimeoutRef.current = setTimeout(async () => {
      try {
        const r = await fetch("/api/agent/personality", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ personality: configRef.current }),
        });
        if (!r.ok) {
          const data = (await r.json().catch(() => ({}))) as { error?: string };
          setErrorMessage(data.error || `save ${r.status}`);
          setSaveStatus("error");
          return;
        }
        setSaveStatus("saved");
        setTimeout(() => setSaveStatus("idle"), 2000);
      } catch (err) {
        setErrorMessage(err instanceof Error ? err.message : "save failed");
        setSaveStatus("error");
      }
    }, 600);
  }, []);

  // Cleanup timeout on unmount.
  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    };
  }, []);

  const updateConfig = useCallback(
    <K extends keyof AgentConfig>(key: K, value: AgentConfig[K]) => {
      setConfig((prev) => {
        if (!prev) return prev;
        const next = { ...prev, [key]: value };
        configRef.current = next;
        return next;
      });
      triggerSave();
    },
    [triggerSave],
  );

  // Reset Defaults: the MCP's default document, not a copy held here.
  const handleReset = useCallback(() => {
    if (!defaultsRef.current) return;
    const next = resolveConfig(defaultsRef.current, {});
    if (!next) return;
    setConfig(next);
    configRef.current = next;
    triggerSave();
  }, [triggerSave]);

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-8 space-y-6">
        {/* Header — matches /skills layout pattern. No breadcrumb, for
            consistency with every other page in /settings/*. */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <span className="material-symbols-outlined text-2xl text-primary">
                psychology
              </span>
              <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
                Personality
              </h1>
            </div>
            <p className="text-sm text-on-surface-variant ml-9">
              Set the persona and the action policy Phantom follows.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <SaveIndicator status={saveStatus} errorMessage={errorMessage} />
            <button
              type="button"
              onClick={handleReset}
              disabled={config === null}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-label font-medium text-on-surface-variant hover:text-on-surface transition-all hover:bg-white/5 disabled:opacity-40"
              style={{
                border: "0.5px solid var(--glass-border)",
              }}
            >
              <span className="material-symbols-outlined text-sm">restart_alt</span>
              Reset Defaults
            </button>
          </div>
        </div>

      {config === null ? (
        <LoadState error={loadError} onRetry={() => void load()} />
      ) : (
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* No "Personality & Tone" slider panel: separate sliders
            (responseStyle / proactivity / confidence) would drift out
            of sync with the markdown editor. The markdown
            IS the source of truth (see the Persona Document section
            below + system-prompt.ts:renderPersonaBlock). */}

        {/* Action Policy — local vs external boundary */}
        <div className="lg:col-span-2">
        <ConfigSection
          title="Action Policy"
          subtitle="Local vs external surface"
          icon="route"
          borderColor="rgba(105, 220, 173, 0.3)"
          glowColor="rgba(105, 220, 173, 0.08)"
        >
          <div
            className="px-3 py-2.5 rounded-lg text-[11px] text-on-surface-variant/80 leading-relaxed"
            style={{
              background: "rgba(105, 220, 173, 0.06)",
              border: "0.5px solid rgba(105, 220, 173, 0.18)",
            }}
          >
            <span className="material-symbols-outlined text-sm align-middle mr-1 text-secondary">
              info
            </span>
            Tells the agent how to classify each request: <strong>local</strong>{" "}
            (configure the agent itself) or <strong>external</strong> (act on
            the SOC environment). When confidence is low, the agent asks you to
            disambiguate rather than guessing — preventing &ldquo;I asked it to
            schedule a job, it ran the job instead&rdquo;.
          </div>

          <CategoryListControl
            label="Local categories"
            description="Tools that mutate the agent's own runtime state (jobs, settings, persona, skills)."
            value={config.actionPolicy.localCategories}
            onChange={(next) =>
              updateConfig("actionPolicy", {
                ...config.actionPolicy,
                localCategories: next,
              })
            }
          />

          <CategoryListControl
            label="External categories"
            description="Tools that act on the SOC environment outside the agent boundary."
            value={config.actionPolicy.externalCategories}
            onChange={(next) =>
              updateConfig("actionPolicy", {
                ...config.actionPolicy,
                externalCategories: next,
              })
            }
          />

          <ToggleControl
            label="Ask when unsure"
            description="When the agent can't confidently classify a request, emit a clarifying question instead of guessing. Strongly recommended ON."
            enabled={config.actionPolicy.askWhenUnsure}
            onChange={(v) =>
              updateConfig("actionPolicy", {
                ...config.actionPolicy,
                askWhenUnsure: v,
              })
            }
          />

          <SegmentedControl
            label="Local action confirmation"
            options={[
              { value: "approve-card", label: "Approval card" },
              { value: "soft", label: "Soft confirm" },
              { value: "off", label: "Off" },
            ]}
            value={config.actionPolicy.confirmLocalActions}
            onChange={(v) =>
              updateConfig("actionPolicy", {
                ...config.actionPolicy,
                confirmLocalActions: v as ActionPolicy["confirmLocalActions"],
              })
            }
          />

          <SegmentedControl
            label="External action confirmation"
            options={[
              { value: "approve-card", label: "Approval card" },
              { value: "soft", label: "Soft confirm" },
              { value: "off", label: "Off" },
            ]}
            value={config.actionPolicy.confirmExternalActions}
            onChange={(v) =>
              updateConfig("actionPolicy", {
                ...config.actionPolicy,
                confirmExternalActions: v as ActionPolicy["confirmExternalActions"],
              })
            }
          />
        </ConfigSection>
        </div>

        {/* Advanced — Full Width */}
        <div className="lg:col-span-2">
          <ConfigSection
            title="Advanced"
            subtitle="Personality.md"
            icon="code"
            borderColor="var(--glass-border)"
            glowColor="rgba(140, 145, 157, 0.05)"
          >
            <PersonalityEditor
              value={config.personalityMd}
              onChange={(v) => updateConfig("personalityMd", v)}
            />
          </ConfigSection>
        </div>
      </div>
      )}
      </div>
    </div>
  );
}

// ─── Load State ──────────────────────────────────────────────────────────────

/** Shown until the stored blob and the defaults have loaded, or when the
 * load failed. The editor is not rendered in either case. */
function LoadState({ error, onRetry }: { error: string | null; onRetry: () => void }) {
  if (error === null) {
    return (
      <p className="text-sm text-on-surface-variant" role="status">
        Loading…
      </p>
    );
  }
  return (
    <div className="flex items-center gap-3 text-sm" role="alert">
      <span className="material-symbols-outlined text-lg text-error">error</span>
      <span className="text-on-surface-variant">Could not load the personality: {error}</span>
      <button
        type="button"
        onClick={onRetry}
        className="px-3 py-1.5 text-[11px] font-headline font-bold uppercase tracking-widest rounded-lg bg-primary/15 text-primary hover:bg-primary/20 transition-colors"
      >
        Retry
      </button>
    </div>
  );
}

// ─── Config Section Wrapper ──────────────────────────────────────────────────

function ConfigSection({
  title,
  subtitle,
  icon,
  borderColor,
  glowColor,
  children,
}: {
  title: string;
  subtitle?: string;
  icon: string;
  borderColor: string;
  glowColor: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="rounded-2xl p-6 space-y-5"
      style={{
        ...glassCard,
        borderLeft: `2px solid ${borderColor}`,
        boxShadow: `0 0 30px ${glowColor}`,
      }}
    >
      {/* Section header */}
      <div className="flex items-center gap-3">
        <span
          className="material-symbols-outlined text-lg"
          style={{ color: borderColor.replace("0.3", "0.8").replace("0.2", "0.7") }}
        >
          {icon}
        </span>
        <div>
          <h2 className="text-sm font-headline font-bold text-on-surface uppercase tracking-wider">
            {title}
          </h2>
          {subtitle && (
            <span className="text-[10px] text-on-surface-variant/60 font-mono">{subtitle}</span>
          )}
        </div>
      </div>
      {children}
    </div>
  );
}

// ─── Segmented Control ───────────────────────────────────────────────────────

function SegmentedControl({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: string; label: string }[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-2">
      <label className="text-xs font-label text-on-surface-variant/80">{label}</label>
      <div
        className="flex rounded-xl overflow-hidden"
        style={{
          background: "var(--m3-surface-container-low)",
          border: "0.5px solid rgba(140, 145, 157, 0.1)",
        }}
        role="radiogroup"
        aria-label={label}
      >
        {options.map((opt) => {
          const isActive = value === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              role="radio"
              aria-checked={isActive}
              onClick={() => onChange(opt.value)}
              className={cn(
                "flex-1 py-2 text-xs font-label font-medium transition-all",
                isActive
                  ? "text-white shadow-sm"
                  : "text-on-surface-variant/60 hover:text-on-surface-variant",
              )}
              style={
                isActive
                  ? {
                      background: "linear-gradient(135deg, #1963B3, #2D8DF0)",
                      borderRadius: "0.625rem",
                      margin: "2px",
                    }
                  : { margin: "2px" }
              }
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ─── Toggle Control ──────────────────────────────────────────────────────────

function ToggleControl({
  label,
  description,
  enabled,
  onChange,
}: {
  label: string;
  description?: string;
  enabled: boolean;
  onChange: (enabled: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <p className="text-xs font-label text-on-surface-variant/80">{label}</p>
        {description && (
          <p className="text-[10px] text-on-surface-variant/50 font-body mt-0.5">{description}</p>
        )}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label={label}
        onClick={() => onChange(!enabled)}
        className={cn(
          "relative w-11 h-6 rounded-full transition-colors duration-200 shrink-0",
          enabled ? "bg-primary" : "bg-white/10",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 w-5 h-5 rounded-full bg-white shadow-sm transition-transform duration-200",
            enabled ? "translate-x-[22px]" : "translate-x-0.5",
          )}
        />
      </button>
    </div>
  );
}

// ─── Save Indicator ──────────────────────────────────────────────────────────

function SaveIndicator({
  status,
  errorMessage,
}: {
  status: "idle" | "saving" | "saved" | "error";
  errorMessage?: string | null;
}) {
  if (status === "idle") return null;

  if (status === "error") {
    return (
      <div className="flex items-center gap-1.5 text-xs font-label" title={errorMessage ?? undefined}>
        <span className="material-symbols-outlined text-sm text-error">error</span>
        <span className="text-error/80">{errorMessage || "Save failed"}</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1.5 text-xs font-label">
      {status === "saving" ? (
        <>
          <span className="material-symbols-outlined text-sm text-on-surface-variant/60 animate-spin">
            sync
          </span>
          <span className="text-on-surface-variant/60">Saving...</span>
        </>
      ) : (
        <>
          <span className="material-symbols-outlined text-sm text-secondary">check_circle</span>
          <span className="text-secondary/80">Saved</span>
        </>
      )}
    </div>
  );
}

// ─── Personality Editor ──────────────────────────────────────────────────────

function PersonalityEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const [isFullscreen, setIsFullscreen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleCopy = useCallback(() => {
    void navigator.clipboard.writeText(value);
  }, [value]);

  return (
    <div className="space-y-2">
      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-on-surface-variant/50 font-mono uppercase tracking-wider">
            Markdown
          </span>
          <span className="text-[10px] text-on-surface-variant/40 font-mono">
            {value.split("\n").length} lines
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={handleCopy}
            className="p-1.5 rounded-md hover:bg-white/5 transition-colors"
            aria-label="Copy content"
          >
            <span className="material-symbols-outlined text-sm text-on-surface-variant/60">
              content_copy
            </span>
          </button>
          <button
            type="button"
            onClick={() => setIsFullscreen((prev) => !prev)}
            className="p-1.5 rounded-md hover:bg-white/5 transition-colors"
            aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
          >
            <span className="material-symbols-outlined text-sm text-on-surface-variant/60">
              {isFullscreen ? "fullscreen_exit" : "fullscreen"}
            </span>
          </button>
        </div>
      </div>

      {/* Editor */}
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "w-full rounded-xl px-4 py-3 text-sm font-mono text-on-surface leading-relaxed outline-none resize-none custom-scrollbar transition-all",
          isFullscreen ? "h-[500px]" : "h-[240px]",
        )}
        style={{
          // Not a hardcoded rgba(8, 8, 20, 0.6): that looked read-only on
          // the light theme because
          // the bg was darker than the surrounding panel; the
          // text-cursor caret all but disappeared. Lifted to a
          // theme-aware token so the editor reads as a writable
          // surface in both modes. (Editing was already wired:
          // textarea is controlled with onChange → updateConfig →
          // triggerSave → PUT /api/agent/personality, debounced 600ms.)
          background: "var(--m3-surface-container-low)",
          border: "0.5px solid var(--glass-border)",
        }}
        spellCheck={false}
        aria-label="Personality.md editor"
      />
    </div>
  );
}

// ─── Category List Control (Action Policy) ───────────────────────────────────

/**
 * Editable list of category strings rendered as removable chips with
 * an Add input. Used by the Action Policy section to let the operator
 * tweak which tool categories the agent considers "local" vs
 * "external". Categories are bare strings (e.g. "jobs", "xlog") that
 * the chat-route system instruction prefix-matches against tool names
 * — so "jobs" covers jobs_create, jobs_update, jobs_delete, etc.
 *
 * Defensive: ignores empty / whitespace-only adds, dedupes case-
 * insensitively, sorts on display only (preserves insertion order
 * underneath so the round-trip diff stays stable).
 */
function CategoryListControl({
  label,
  description,
  value,
  onChange,
}: {
  label: string;
  description?: string;
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const [draft, setDraft] = useState("");

  function add() {
    const trimmed = draft.trim().toLowerCase();
    if (!trimmed) return;
    if (value.some((v) => v.toLowerCase() === trimmed)) {
      setDraft("");
      return;
    }
    onChange([...value, trimmed]);
    setDraft("");
  }

  function remove(cat: string) {
    onChange(value.filter((v) => v !== cat));
  }

  return (
    <div className="space-y-2">
      <div>
        <label className="text-xs font-label text-on-surface-variant/80">
          {label}
        </label>
        {description && (
          <p className="text-[10px] text-on-surface-variant/50 font-body mt-0.5">
            {description}
          </p>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {value.length === 0 ? (
          <span className="text-[11px] text-on-surface-variant/40 italic">
            (empty — click Add to introduce a category)
          </span>
        ) : (
          value.map((cat) => (
            <button
              key={cat}
              type="button"
              onClick={() => remove(cat)}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-mono group"
              style={{
                background: "var(--glass-bg-strong)",
                border: "0.5px solid var(--glass-border)",
              }}
              title={`Remove ${cat}`}
            >
              <span className="text-on-surface">{cat}</span>
              <span
                className="material-symbols-outlined text-[12px] text-on-surface-variant/60 group-hover:text-error transition-colors"
                aria-hidden
              >
                close
              </span>
            </button>
          ))
        )}
      </div>
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder="Add a category…"
          className="flex-1 px-3 py-1.5 text-xs font-mono rounded-lg bg-surface-container-low border border-outline-variant/30 outline-none focus:border-primary/50 text-on-surface placeholder:text-on-surface-variant/40"
        />
        <button
          type="button"
          onClick={add}
          disabled={!draft.trim()}
          className="px-3 py-1.5 text-[11px] font-headline font-bold uppercase tracking-widest rounded-lg bg-primary/15 text-primary hover:bg-primary/20 transition-colors disabled:opacity-40"
        >
          Add
        </button>
      </div>
    </div>
  );
}
