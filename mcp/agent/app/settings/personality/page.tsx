"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/**
 * Phantom personality page — ported from spark/services/ui's
 * /command/agent. Adaptations:
 *   - Spark's auto-save was a UI simulation (a setTimeout that flipped
 *     the indicator without persisting). This wires it to phantom's
 *     real /api/agent/settings PUT, debounced 600ms after the last
 *     change so a slider drag doesn't flood the MCP. Initial load on
 *     mount via the matching GET.
 *   - MODEL_OPTIONS narrowed to phantom's Vertex Gemini catalog
 *     (Anthropic + OpenAI are WIP — see /providers).
 *
 * The settings keys we read/write are namespaced under `personality.*`
 * in the phantom MCP's settings_store so they don't collide with other
 * runtime tunables.
 */

// ─── Types ───────────────────────────────────────────────────────────────────

interface ActionPolicy {
  /** Tool categories the agent classifies as "operating on itself".
   * Local-tagged turns require an inline approval card before the
   * underlying tool fires (humanRequired[] enforcement). */
  localCategories: string[];
  /** Tool categories the agent classifies as "operating on the SOC
   * environment outside the agent". Subject to confirmExternalActions
   * (default: soft confirmation in chat). */
  externalCategories: string[];
  /** When the agent's classification confidence is low, ASK the
   * operator for clarification rather than guessing. Strongly
   * recommended ON. */
  askWhenUnsure: boolean;
  /** UX cadence for local-side actions before they execute. */
  confirmLocalActions: "approve-card" | "soft" | "off";
  /** UX cadence for external-side actions before they execute. */
  confirmExternalActions: "approve-card" | "soft" | "off";
}

interface AgentConfig {
  // ── Personality & Tone ─────────────────────────────────────────
  // There are no structured "tone" knobs (responseStyle, proactivity,
  // confidence) or "thinking" knobs (logicDepth, planningDepth,
  // delegationStyle). Operators express tone and reasoning
  // style through `personalityMd` (free-form markdown) instead —
  // single source of truth, no drift between sliders and the
  // markdown saying contradictory things. Old blobs that still have
  // these fields silently pass through the store and are ignored on
  // read (no migration needed).

  // Autonomy & Permissions
  permissionLevel: number; // 0-100 (0=Ask Everything, 100=Full Auto)

  // Action Policy — local vs external boundary
  actionPolicy: ActionPolicy;

  // Model & Execution
  defaultModel: string;
  fallbackModel: string;
  maxConcurrentRuns: number;

  // Notifications
  dailySummary: boolean;
  summaryTime: string; // HH:mm
  escalationThreshold: number; // 0-100

  // Advanced
  personalityMd: string;

  // ── Caching, compaction and memory tuning knobs ────────────────
  // Surfaced as runtime settings instead of process-env / source
  // constants so an operator can tune them without a redeploy.
  /** Enable Vertex cachedContents for the
   *  stable system prompt (~25% billing on cached portions).
   *  Off by default until per-model gating is reliable (also
   *  opt-in via PHANTOM_VERTEX_CACHE=1; this setting is the
   *  operator-friendly equivalent). */
  vertexCacheEnabled: boolean;
  /** Minimum messages-dropped count below
   *  which auto-compaction is a no-op (avoids burning a
   *  summarizer call to compact 1-2 trivial turns). The
   *  default is 5; the slider lets the
   *  operator dial it down on chatty sessions or up to suppress. */
  autoCompactMinDropped: number;
  /** MMR (maximal marginal relevance)
   *  lambda for memory_store.search. 1.0 = pure relevance,
   *  0.0 = pure diversity. Default 0.7 favors relevance with a
   *  diversity tilt. Per-call tool args override this. */
  memoryMmrLambda: number;
  /** Exponential temporal-decay lambda
   *  applied to age-in-days when ranking memory results.
   *  0.0 = no decay (treat all ages equally). Default 0.01
   *  ≈ "10 days old loses 10% of its score". Per-call tool
   *  args override this. */
  memoryTemporalDecayLambda: number;
}

const DEFAULT_CONFIG: AgentConfig = {
  permissionLevel: 40,
  actionPolicy: {
    localCategories: [
      "jobs",
      "settings",
      "personality",
      "instances",
      "providers",
      "approvals",
      "notifications",
      "skills",
      "api-keys",
      "memory",
      "knowledge",
    ],
    externalCategories: ["xlog", "caldera", "xsiam", "simulations", "http-sender", "wec-sender"],
    askWhenUnsure: true,
    confirmLocalActions: "approve-card",
    confirmExternalActions: "off",
  },
  defaultModel: "gemini-3.1-pro-preview",
  fallbackModel: "gemini-2.5-flash",
  maxConcurrentRuns: 3,
  dailySummary: true,
  summaryTime: "09:00",
  escalationThreshold: 60,
  // Tuning defaults — match the existing chat-route +
  // memory-store defaults so loading a fresh AgentConfig changes
  // nothing observable until the operator moves a slider.
  vertexCacheEnabled: false,
  autoCompactMinDropped: 5,
  memoryMmrLambda: 0.7,
  memoryTemporalDecayLambda: 0.01,
  personalityMd: `# Phantom Personality

You are Phantom, a continuous SOC simulation agent. You orchestrate
synthetic security log generation, MITRE ATT&CK scenario emulation,
and detection-validation workflows across xlog, Caldera, and XSIAM.

## Tone
- Operationally precise: name tools, scenarios, IOCs, XQL queries explicitly
- Concise by default; expand when asked or when stakes are high
- Confident on what you've actually executed; honest about what's
  inferred or unverified

## Principles
- Always cite the connector + tool you used (xlog.create_scenario_worker,
  caldera.start_operation, xsiam.execute_xql_query, …) so operators can
  reproduce
- Generate IOCs through the foundation skills first (shared IOC pool,
  device topology) before scenarios consume them — keeps cross-scenario
  telemetry coherent
- Verify detection coverage with XQL after every scenario; surface gaps
  before the operator asks
- Refuse to take destructive actions (real-tenant log injection, real
  Caldera operations against unscoped agents) without explicit user
  confirmation
`,
};

// Phantom's chat path is Vertex Gemini only today (Anthropic + OpenAI
// are WIP — see /providers). This list mirrors /api/agent/models.
const MODEL_OPTIONS = [
  { value: "gemini-3.1-pro-preview", label: "Gemini 3.1 Pro (preview)" },
  { value: "gemini-3.0-pro", label: "Gemini 3.0 Pro" },
  { value: "gemini-2.5-pro", label: "Gemini 2.5 Pro" },
  { value: "gemini-2.5-flash", label: "Gemini 2.5 Flash" },
  { value: "gemini-2.5-flash-lite", label: "Gemini 2.5 Flash Lite" },
];

// ─── Glass Style Constants ───────────────────────────────────────────────────

const glassCard = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

// ─── Page Component ──────────────────────────────────────────────────────────

// Personality persists as a single JSON blob via /api/agent/personality
// (backed by setup.json's free-form key/value, not the strict-whitelist
// MCP settings store). No packing/unpacking — the wire payload matches
// AgentConfig 1:1.

export default function PersonalityPage() {
  const [config, setConfig] = useState<AgentConfig>(DEFAULT_CONFIG);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const configRef = useRef<AgentConfig>(DEFAULT_CONFIG);

  // Initial load — pull whatever blob is in setup.json under
  // values.personality and merge over defaults. Missing fields keep
  // their default values.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/agent/personality", { cache: "no-store" });
        if (!r.ok) return;
        const data = (await r.json()) as { personality?: Partial<AgentConfig> };
        const merged = { ...DEFAULT_CONFIG, ...(data.personality ?? {}) };
        if (!cancelled) {
          setConfig(merged);
          configRef.current = merged;
        }
      } catch {
        // Empty blob — fall back to defaults.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Real auto-save: debounced 600ms after the last change. Slider
  // drags would otherwise flood the MCP with one PUT per pixel.
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
        const next = { ...prev, [key]: value };
        configRef.current = next;
        return next;
      });
      triggerSave();
    },
    [triggerSave],
  );

  const handleReset = useCallback(() => {
    setConfig(DEFAULT_CONFIG);
    configRef.current = DEFAULT_CONFIG;
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
              Fine-tune how Phantom thinks, responds, and operates.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <SaveIndicator status={saveStatus} errorMessage={errorMessage} />
            <button
              type="button"
              onClick={handleReset}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-label font-medium text-on-surface-variant hover:text-on-surface transition-all hover:bg-white/5"
              style={{
                border: "0.5px solid var(--glass-border)",
              }}
            >
              <span className="material-symbols-outlined text-sm">restart_alt</span>
              Reset Defaults
            </button>
          </div>
        </div>

      {/* Bento Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* No "Personality & Tone" slider panel: separate sliders
            (responseStyle / proactivity / confidence) would drift out
            of sync with the markdown editor. The markdown
            IS the source of truth (see the Persona Document section
            below + system-prompt.ts:renderPersonaBlock). */}

        {/* Autonomy & Permissions */}
        <ConfigSection
          title="Autonomy & Permissions"
          icon="admin_panel_settings"
          borderColor="rgba(123, 220, 123, 0.3)"
          glowColor="rgba(123, 220, 123, 0.08)"
        >
          <SliderControl
            label="Permission Level"
            value={config.permissionLevel}
            onChange={(v) => updateConfig("permissionLevel", v)}
            leftLabel="Ask Everything"
            rightLabel="Full Auto"
            color="#7bdc7b"
          />
          {config.permissionLevel > 75 && (
            <div
              className="flex items-start gap-2 px-3 py-2.5 rounded-lg text-xs"
              style={{
                background: "rgba(251, 188, 48, 0.08)",
                border: "0.5px solid rgba(251, 188, 48, 0.2)",
              }}
            >
              <span className="material-symbols-outlined text-sm text-tertiary mt-0.5">
                warning
              </span>
              <span className="text-tertiary/90 font-body leading-relaxed">
                High autonomy mode. Spark may execute operations without confirmation.
              </span>
            </div>
          )}
        </ConfigSection>

        {/* 2.5 Action Policy — local vs external boundary */}
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

        {/* No "Thinking & Reasoning" slider panel: logicDepth /
            planningDepth / delegationStyle would have no effect on the
            system prompt. Operators describe reasoning style in
            the persona markdown ("think step-by-step before…",
            "delegate to a sub-agent when…") which actually feeds the
            prompt. */}

        {/* Model & Execution */}
        <ConfigSection
          title="Model & Execution"
          icon="memory"
          borderColor="rgba(25, 99, 179, 0.3)"
          glowColor="rgba(25, 99, 179, 0.08)"
        >
          <SelectControl
            label="Default Model"
            value={config.defaultModel}
            options={MODEL_OPTIONS}
            onChange={(v) => updateConfig("defaultModel", v)}
          />
          <SelectControl
            label="Fallback Model"
            value={config.fallbackModel}
            options={MODEL_OPTIONS}
            onChange={(v) => updateConfig("fallbackModel", v)}
          />
          <StepperControl
            label="Max Concurrent Runs"
            value={config.maxConcurrentRuns}
            min={1}
            max={10}
            onChange={(v) => updateConfig("maxConcurrentRuns", v)}
          />
        </ConfigSection>

        {/* 5. Notifications & Escalation */}
        <ConfigSection
          title="Notifications"
          icon="notifications_active"
          borderColor="rgba(255, 180, 171, 0.3)"
          glowColor="rgba(255, 180, 171, 0.08)"
        >
          <ToggleControl
            label="Daily Summary"
            description="Receive a daily digest of Spark activity"
            enabled={config.dailySummary}
            onChange={(v) => updateConfig("dailySummary", v)}
          />
          {config.dailySummary && (
            <TimePickerControl
              label="Summary Time"
              value={config.summaryTime}
              onChange={(v) => updateConfig("summaryTime", v)}
            />
          )}
          <SliderControl
            label="Escalation Threshold"
            value={config.escalationThreshold}
            onChange={(v) => updateConfig("escalationThreshold", v)}
            leftLabel="Escalate Often"
            rightLabel="Handle Silently"
            color="#ffb4ab"
          />
        </ConfigSection>

        {/* Tuning. Context-budget compaction, MMR +
            temporal-decay memory ranking, and Vertex context caching
            each have a default; this section exposes them as runtime
            knobs so an operator can tune
            without a redeploy. The actual wiring through to the
            chat-route and memory_store happens server-side; this
            section is the UI surface. */}
        <ConfigSection
          title="Tuning"
          subtitle="Chat + memory knobs"
          icon="tune"
          borderColor="rgba(167, 200, 255, 0.3)"
          glowColor="rgba(167, 200, 255, 0.05)"
        >
          <ToggleControl
            label="Vertex prompt caching"
            enabled={config.vertexCacheEnabled}
            onChange={(v) => updateConfig("vertexCacheEnabled", v)}
            description="Cache the stable system prompt with Vertex cachedContents API. Cached input tokens bill at ~25% of standard rate. Off by default until per-model support stabilizes."
          />
          <RangeNumberControl
            label="Auto-compact threshold"
            value={config.autoCompactMinDropped}
            onChange={(v) => updateConfig("autoCompactMinDropped", v)}
            min={1}
            max={50}
            step={1}
            description="Minimum number of messages dropped at the budget edge before auto-compaction fires. Lower = compact more aggressively; higher = avoid summarizer calls on light pruning."
            valueFormatter={(v) => `${v} message${v === 1 ? "" : "s"}`}
          />
          <RangeNumberControl
            label="Memory MMR λ"
            value={config.memoryMmrLambda}
            onChange={(v) => updateConfig("memoryMmrLambda", v)}
            min={0}
            max={1}
            step={0.05}
            description="Maximal-marginal-relevance lambda used by memory_store.search when the tool call doesn't override. 1.0 = pure relevance, 0.0 = pure diversity. Default 0.7 favors relevance."
            valueFormatter={(v) => v.toFixed(2)}
          />
          <RangeNumberControl
            label="Memory temporal decay λ"
            value={config.memoryTemporalDecayLambda}
            onChange={(v) => updateConfig("memoryTemporalDecayLambda", v)}
            min={0}
            max={0.05}
            step={0.001}
            description="Exponential decay applied to memory age (days). 0.0 disables decay. Default 0.01 ≈ ~10% score loss per 10 days old. Per-call tool args override."
            valueFormatter={(v) => v.toFixed(3)}
          />
        </ConfigSection>

        {/* 6. Advanced — Full Width */}
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
      </div>
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

// ─── Range / Number Control ─────────────────────────────────────────────────

/**
 * Numeric slider with custom min/max/step + a formatter for the
 * displayed value. Used for the auto-compact threshold
 * (integer 1-50) and the two memory lambdas (floats 0..1 / 0..0.05).
 *
 * Differs from SliderControl (which is hard-coded to 0-100 and a "%"
 * suffix): this one carries arbitrary numeric ranges with a
 * formatter so float values render cleanly.
 */
function RangeNumberControl({
  label,
  value,
  onChange,
  min,
  max,
  step,
  description,
  valueFormatter,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  step: number;
  description?: string;
  valueFormatter?: (value: number) => string;
}) {
  const formatted = valueFormatter ? valueFormatter(value) : String(value);
  // Position the gradient stop based on where in the range we are.
  const pct =
    max > min ? Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100)) : 0;
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <label className="text-xs font-label text-on-surface-variant/80">
          {label}
        </label>
        <span className="text-xs font-mono text-on-surface-variant/70">
          {formatted}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
        aria-label={label}
        style={{
          background: `linear-gradient(to right, #a7c8ff ${pct}%, rgba(140, 145, 157, 0.15) ${pct}%)`,
          accentColor: "#a7c8ff",
        }}
      />
      {description && (
        <p className="text-[10px] text-on-surface-variant/60 leading-relaxed">
          {description}
        </p>
      )}
    </div>
  );
}

// ─── Slider Control ──────────────────────────────────────────────────────────

function SliderControl({
  label,
  value,
  onChange,
  leftLabel,
  rightLabel,
  color,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  leftLabel: string;
  rightLabel: string;
  color: string;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-xs font-label text-on-surface-variant/80">{label}</label>
        <span className="text-xs font-mono text-on-surface-variant/60">{value}%</span>
      </div>
      <input
        type="range"
        min={0}
        max={100}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
        aria-label={label}
        style={{
          background: `linear-gradient(to right, ${color} ${value}%, rgba(140, 145, 157, 0.15) ${value}%)`,
          accentColor: color,
        }}
      />
      <div className="flex justify-between">
        <span className="text-[10px] text-on-surface-variant/50 font-label">{leftLabel}</span>
        <span className="text-[10px] text-on-surface-variant/50 font-label">{rightLabel}</span>
      </div>
    </div>
  );
}

// ─── Select Control ──────────────────────────────────────────────────────────

function SelectControl({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-2">
      <label className="text-xs font-label text-on-surface-variant/80">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-2.5 rounded-xl text-sm font-body text-on-surface bg-transparent outline-none cursor-pointer appearance-none"
        style={{
          background: "var(--m3-surface-container-low)",
          border: "0.5px solid var(--glass-border)",
          backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M3 5l3 3 3-3' stroke='%238c919d' stroke-width='1.5' fill='none'/%3E%3C/svg%3E")`,
          backgroundRepeat: "no-repeat",
          backgroundPosition: "right 12px center",
        }}
        aria-label={label}
      >
        {/* No custom bg on <option> — browsers ignore most <option>
            styling and defer to the page's color-scheme. With our
            `data-theme` CSS-vars setup, that gives correct OS-native
            styling (dark options in dark mode, light in light mode)
            instead of fighting the browser. */}
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}

// ─── Stepper Control ─────────────────────────────────────────────────────────

function StepperControl({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="space-y-2">
      <label className="text-xs font-label text-on-surface-variant/80">{label}</label>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => onChange(Math.max(min, value - 1))}
          disabled={value <= min}
          className="w-9 h-9 rounded-xl flex items-center justify-center transition-all disabled:opacity-30 hover:bg-white/5"
          style={{
            background: "var(--m3-surface-container-low)",
            border: "0.5px solid var(--glass-border)",
          }}
          aria-label={`Decrease ${label}`}
        >
          <span className="material-symbols-outlined text-sm text-on-surface-variant">remove</span>
        </button>
        <span
          className="w-14 text-center text-lg font-headline font-bold text-on-surface py-1.5 rounded-xl"
          style={{
            background: "var(--m3-surface-container-low)",
            border: "0.5px solid var(--glass-border)",
          }}
        >
          {value}
        </span>
        <button
          type="button"
          onClick={() => onChange(Math.min(max, value + 1))}
          disabled={value >= max}
          className="w-9 h-9 rounded-xl flex items-center justify-center transition-all disabled:opacity-30 hover:bg-white/5"
          style={{
            background: "var(--m3-surface-container-low)",
            border: "0.5px solid var(--glass-border)",
          }}
          aria-label={`Increase ${label}`}
        >
          <span className="material-symbols-outlined text-sm text-on-surface-variant">add</span>
        </button>
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

// ─── Time Picker Control ─────────────────────────────────────────────────────

function TimePickerControl({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-2">
      <label className="text-xs font-label text-on-surface-variant/80">{label}</label>
      <input
        type="time"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="px-3 py-2 rounded-xl text-sm font-mono text-on-surface bg-transparent outline-none"
        style={{
          background: "var(--m3-surface-container-low)",
          border: "0.5px solid var(--glass-border)",
        }}
        aria-label={label}
      />
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
