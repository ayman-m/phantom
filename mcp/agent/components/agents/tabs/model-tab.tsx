"use client";

import * as React from "react";
import { updateAgent } from "@/lib/api/agents";
import type { Agent, AgentModelConfig, ModelInfo } from "@/lib/api/types";

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

interface ModelTabProps {
  agent: Agent;
  models: ModelInfo[];
  onAgentUpdated: (agent: Agent) => void;
  onDirtyChange?: (dirty: boolean) => void;
}

const THINK_LEVELS = [
  {
    value: "none" as const,
    label: "OFF",
    description: "No extended reasoning. Direct responses only.",
  },
  {
    value: "low" as const,
    label: "LOW",
    description: "Brief internal reasoning before responding.",
  },
  {
    value: "medium" as const,
    label: "MEDIUM",
    description: "Moderate chain-of-thought for complex tasks.",
  },
  {
    value: "high" as const,
    label: "HIGH",
    description: "Deep multi-step reasoning for difficult problems.",
  },
  {
    value: "adaptive" as const,
    label: "ADAPTIVE",
    description: "Automatically adjusts depth based on task complexity.",
  },
];

function getProviderColor(provider: string): string {
  switch (provider.toLowerCase()) {
    case "anthropic":
      return "bg-[#d97706]/20 text-[#d97706]";
    case "openai":
      return "bg-[#10a37f]/20 text-[#10a37f]";
    case "google":
      return "bg-[#4285f4]/20 text-[#4285f4]";
    default:
      return "bg-primary-container/20 text-primary";
  }
}

export function ModelTab({
  agent,
  models,
  onAgentUpdated,
  onDirtyChange,
}: ModelTabProps) {
  const initialConfig: AgentModelConfig = {
    defaultModel: agent.modelConfig?.defaultModel ?? agent.model ?? "",
    fallbackModels: agent.modelConfig?.fallbackModels ?? [],
    thinkLevel: agent.modelConfig?.thinkLevel ?? "none",
  };

  const [selectedModel, setSelectedModel] = React.useState(
    initialConfig.defaultModel ?? "",
  );
  const [fallbackModels, setFallbackModels] = React.useState<string[]>(
    initialConfig.fallbackModels ?? [],
  );
  const [thinkLevel, setThinkLevel] = React.useState<string>(
    initialConfig.thinkLevel ?? "none",
  );
  const [saving, setSaving] = React.useState(false);
  const [saveStatus, setSaveStatus] = React.useState<
    "idle" | "success" | "error"
  >("idle");

  React.useEffect(() => {
    const cfg: AgentModelConfig = {
      defaultModel: agent.modelConfig?.defaultModel ?? agent.model ?? "",
      fallbackModels: agent.modelConfig?.fallbackModels ?? [],
      thinkLevel: agent.modelConfig?.thinkLevel ?? "none",
    };
    setSelectedModel(cfg.defaultModel ?? "");
    setFallbackModels(cfg.fallbackModels ?? []);
    setThinkLevel(cfg.thinkLevel ?? "none");
  }, [agent]);

  const isDirty =
    selectedModel !== (initialConfig.defaultModel ?? "") ||
    JSON.stringify(fallbackModels) !==
      JSON.stringify(initialConfig.fallbackModels ?? []) ||
    thinkLevel !== (initialConfig.thinkLevel ?? "none");

  React.useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);

  // Group models by provider
  const grouped = React.useMemo(() => {
    const map = new Map<string, ModelInfo[]>();
    for (const m of models) {
      const list = map.get(m.provider) ?? [];
      list.push(m);
      map.set(m.provider, list);
    }
    return map;
  }, [models]);

  const selectedModelInfo = models.find(
    (m) => m.model === selectedModel || `${m.provider}/${m.model}` === selectedModel,
  );

  function addFallback(model: string) {
    if (!fallbackModels.includes(model)) {
      setFallbackModels([...fallbackModels, model]);
    }
  }

  function removeFallback(index: number) {
    setFallbackModels(fallbackModels.filter((_, i) => i !== index));
  }

  async function handleSave() {
    setSaving(true);
    setSaveStatus("idle");

    const modelConfig: AgentModelConfig = {
      defaultModel: selectedModel || null,
      fallbackModels,
      thinkLevel: thinkLevel as AgentModelConfig["thinkLevel"],
    };

    const result = await updateAgent(agent.agent_id, {
      model: selectedModel || null,
      modelConfig,
    });

    setSaving(false);

    if (result.ok) {
      setSaveStatus("success");
      onAgentUpdated(result.data);
      setTimeout(() => setSaveStatus("idle"), 2000);
    } else {
      setSaveStatus("error");
      setTimeout(() => setSaveStatus("idle"), 3000);
    }
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Model Selector + Fallbacks */}
        <div className="lg:col-span-2 space-y-6">
          {/* Default Model Selector */}
          <div className="rounded-xl p-5 space-y-4" style={glassStyle}>
            <h3 className="text-xs font-label uppercase tracking-widest text-on-surface-variant">
              Default Model
            </h3>
            <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
              {Array.from(grouped.entries()).map(([provider, providerModels]) => (
                <div key={provider} className="space-y-2">
                  <p className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant/60 pt-2">
                    {provider}
                  </p>
                  {providerModels.map((m) => {
                    const modelKey = m.model;
                    const isSelected =
                      selectedModel === modelKey ||
                      selectedModel === `${m.provider}/${m.model}`;
                    return (
                      <button
                        key={modelKey}
                        type="button"
                        onClick={() => setSelectedModel(modelKey)}
                        className={`w-full flex items-center gap-3 p-3 rounded-lg text-left transition-all ${
                          isSelected
                            ? "bg-primary/[0.08] border border-primary/30"
                            : "bg-white/[0.02] border border-transparent hover:bg-white/[0.04]"
                        }`}
                      >
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${getProviderColor(m.provider)}`}
                        >
                          {m.provider}
                        </span>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-mono text-on-surface truncate">
                            {m.displayName || m.model}
                          </p>
                          <p className="text-[10px] text-on-surface-variant">
                            {(m.contextWindow / 1000).toFixed(0)}K context
                          </p>
                        </div>
                        <div className="flex items-center gap-1.5">
                          {m.supportsThinking && (
                            <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-tertiary-container/20 text-tertiary">
                              Think
                            </span>
                          )}
                          {m.supportsTools && (
                            <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-secondary-container/20 text-secondary">
                              Tools
                            </span>
                          )}
                        </div>
                        {isSelected && (
                          <span className="material-symbols-outlined text-primary text-base">
                            check_circle
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              ))}
              {models.length === 0 && (
                <p className="text-sm text-on-surface-variant py-4 text-center">
                  No models available.
                </p>
              )}
            </div>

            {/* Capabilities preview */}
            {selectedModelInfo && (
              <div className="pt-3 border-t border-white/[0.06] space-y-2">
                <p className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant">
                  Capabilities
                </p>
                <div className="space-y-1.5">
                  {[
                    {
                      label: "Reasoning",
                      value: selectedModelInfo.supportsThinking ? 90 : 50,
                    },
                    {
                      label: "Speed",
                      value:
                        selectedModelInfo.contextWindow > 100000 ? 60 : 85,
                    },
                    {
                      label: "Context",
                      value: Math.min(
                        (selectedModelInfo.contextWindow / 200000) * 100,
                        100,
                      ),
                    },
                  ].map((cap) => (
                    <div key={cap.label} className="flex items-center gap-3">
                      <span className="text-[10px] font-label text-on-surface-variant w-16">
                        {cap.label}
                      </span>
                      <div className="flex-1 h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
                        <div
                          className="h-full bg-primary rounded-full transition-all"
                          style={{ width: `${cap.value}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Fallback Models */}
          <div className="rounded-xl p-5 space-y-4" style={glassStyle}>
            <h3 className="text-xs font-label uppercase tracking-widest text-on-surface-variant">
              Fallback Models
            </h3>
            {fallbackModels.length === 0 ? (
              <p className="text-sm text-on-surface-variant">
                No fallback models configured.
              </p>
            ) : (
              <div className="space-y-2">
                {fallbackModels.map((fb, i) => (
                  <div
                    key={`${fb}-${i}`}
                    className="flex items-center gap-3 p-3 rounded-lg bg-white/[0.02]"
                  >
                    <span className="material-symbols-outlined text-on-surface-variant/40 text-base cursor-grab">
                      drag_indicator
                    </span>
                    <span className="text-xs font-bold text-on-surface-variant/50 w-5">
                      {i + 1}
                    </span>
                    <span className="flex-1 text-sm font-mono text-on-surface">
                      {fb}
                    </span>
                    <button
                      type="button"
                      onClick={() => removeFallback(i)}
                      className="text-on-surface-variant hover:text-error transition-colors"
                      aria-label={`Remove fallback model ${fb}`}
                    >
                      <span className="material-symbols-outlined text-base">
                        close
                      </span>
                    </button>
                  </div>
                ))}
              </div>
            )}
            {/* Add Fallback dropdown */}
            <select
              value=""
              onChange={(e) => {
                if (e.target.value) addFallback(e.target.value);
              }}
              className="w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/[0.08] text-sm text-on-surface-variant outline-none"
            >
              <option value="">+ Add Fallback Model</option>
              {models
                .filter(
                  (m) =>
                    m.model !== selectedModel &&
                    !fallbackModels.includes(m.model),
                )
                .map((m) => (
                  <option key={m.model} value={m.model}>
                    {m.provider} / {m.displayName || m.model}
                  </option>
                ))}
            </select>
          </div>
        </div>

        {/* Right Column: Think Level */}
        <div>
          <div className="rounded-xl p-5 space-y-4" style={glassStyle}>
            <h3 className="text-xs font-label uppercase tracking-widest text-on-surface-variant">
              Think Level
            </h3>
            <div className="space-y-2">
              {THINK_LEVELS.map((level) => {
                const isSelected = thinkLevel === level.value;
                return (
                  <button
                    key={level.value}
                    type="button"
                    onClick={() => setThinkLevel(level.value)}
                    className={`w-full flex items-start gap-3 p-3 rounded-lg text-left transition-all ${
                      isSelected
                        ? "bg-primary/[0.08] border border-primary/30"
                        : "bg-white/[0.02] border border-transparent hover:bg-white/[0.04]"
                    }`}
                  >
                    <div
                      className={`mt-0.5 w-4 h-4 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
                        isSelected
                          ? "border-primary"
                          : "border-on-surface-variant/40"
                      }`}
                    >
                      {isSelected && (
                        <div className="w-2 h-2 rounded-full bg-primary" />
                      )}
                    </div>
                    <div>
                      <p
                        className={`text-sm font-label font-bold uppercase tracking-wider ${
                          isSelected
                            ? "text-primary"
                            : "text-on-surface-variant"
                        }`}
                      >
                        {level.label}
                      </p>
                      <p className="text-xs text-on-surface-variant/60 mt-0.5">
                        {level.description}
                      </p>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Save Bar */}
      <div
        className="flex items-center justify-between rounded-xl px-5 py-4"
        style={glassStyle}
      >
        <div className="flex items-center gap-2">
          {saveStatus === "success" && (
            <span className="flex items-center gap-1.5 text-xs text-[#7bdc7b]">
              <span className="material-symbols-outlined text-base">
                check_circle
              </span>
              Model config saved
            </span>
          )}
          {saveStatus === "error" && (
            <span className="flex items-center gap-1.5 text-xs text-error">
              <span className="material-symbols-outlined text-base">error</span>
              Failed to save
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={handleSave}
          disabled={!isDirty || saving}
          className="px-6 py-2.5 rounded-lg font-label font-bold text-xs uppercase tracking-widest text-on-primary-container disabled:opacity-30 transition-all hover:scale-[1.02] active:scale-95"
          style={{
            background: "linear-gradient(135deg, #1963b3 0%, #2d8df0 100%)",
          }}
        >
          {saving ? "Saving..." : "Save Model Config"}
        </button>
      </div>
    </div>
  );
}
