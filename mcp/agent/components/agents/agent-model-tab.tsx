"use client";

import * as React from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { updateAgent } from "@/lib/api/agents";
import type { Agent, AgentModelConfig } from "@/lib/api/types";

const THINK_LEVEL_OPTIONS = [
  { value: "none", label: "None" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
];

interface AgentModelTabProps {
  agent: Agent;
  onAgentUpdated?: (agent: Agent) => void;
}

function parseModelConfig(agent: Agent): AgentModelConfig {
  return {
    defaultModel: agent.modelConfig?.defaultModel ?? agent.model ?? "",
    fallbackModels: agent.modelConfig?.fallbackModels ?? [],
    thinkLevel: agent.modelConfig?.thinkLevel ?? "none",
  };
}

export function AgentModelTab({ agent, onAgentUpdated }: AgentModelTabProps) {
  const initial = parseModelConfig(agent);
  const [defaultModel, setDefaultModel] = React.useState(
    initial.defaultModel ?? "",
  );
  const [fallbackModelsText, setFallbackModelsText] = React.useState(
    (initial.fallbackModels ?? []).join(", "),
  );
  const [thinkLevel, setThinkLevel] = React.useState<string>(
    initial.thinkLevel ?? "none",
  );
  const [saving, setSaving] = React.useState(false);
  const [saveStatus, setSaveStatus] = React.useState<
    "idle" | "success" | "error"
  >("idle");
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);

  React.useEffect(() => {
    const cfg = parseModelConfig(agent);
    setDefaultModel(cfg.defaultModel ?? "");
    setFallbackModelsText((cfg.fallbackModels ?? []).join(", "));
    setThinkLevel(cfg.thinkLevel ?? "none");
  }, [agent]);

  const currentFallbacks = fallbackModelsText
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  const isDirty =
    defaultModel !== (initial.defaultModel ?? "") ||
    JSON.stringify(currentFallbacks) !==
      JSON.stringify(initial.fallbackModels ?? []) ||
    thinkLevel !== (initial.thinkLevel ?? "none");

  async function handleSave() {
    setSaving(true);
    setSaveStatus("idle");
    setErrorMessage(null);

    const modelConfig: AgentModelConfig = {
      defaultModel: defaultModel || null,
      fallbackModels: currentFallbacks,
      thinkLevel: thinkLevel as AgentModelConfig["thinkLevel"],
    };

    const result = await updateAgent(agent.agent_id, {
      model: defaultModel || null,
      modelConfig,
    });

    setSaving(false);

    if (result.ok) {
      setSaveStatus("success");
      onAgentUpdated?.(result.data);
      setTimeout(() => setSaveStatus("idle"), 2000);
    } else {
      setSaveStatus("error");
      setErrorMessage(result.error.message);
    }
  }

  return (
    <div className="space-y-6">
      {/* Default Model */}
      <div className="space-y-2">
        <Label htmlFor="agent-default-model">Default Model</Label>
        <Input
          id="agent-default-model"
          value={defaultModel}
          onChange={(e) => setDefaultModel(e.target.value)}
          placeholder="e.g. claude-sonnet-4-20250514"
        />
        <p className="text-xs text-on-surface-variant/60">
          The primary model used for this agent&apos;s runs.
        </p>
      </div>

      {/* Fallback Models */}
      <div className="space-y-2">
        <Label htmlFor="agent-fallback-models">Fallback Models</Label>
        <Input
          id="agent-fallback-models"
          value={fallbackModelsText}
          onChange={(e) => setFallbackModelsText(e.target.value)}
          placeholder="gpt-4o, claude-sonnet-4-20250514"
        />
        <p className="text-xs text-on-surface-variant/60">
          Comma-separated list of models to try if the default is unavailable.
        </p>
      </div>

      {/* Think Level */}
      <div className="space-y-2">
        <Label htmlFor="agent-think-level">Think Level</Label>
        <Select
          id="agent-think-level"
          value={thinkLevel}
          onChange={(e) => setThinkLevel(e.target.value)}
          options={THINK_LEVEL_OPTIONS}
          className="w-48"
        />
        <p className="text-xs text-on-surface-variant/60">
          Controls the depth of reasoning applied before the agent responds.
        </p>
      </div>

      {/* Save */}
      <div className="flex items-center gap-3">
        <Button
          type="button"
          disabled={!isDirty || saving}
          onClick={handleSave}
          className="bg-primary hover:bg-primary/90"
        >
          {saving ? "Saving..." : "Save Model Config"}
        </Button>
        {saveStatus === "success" && (
          <span className="text-xs text-green-400" role="status">
            Saved successfully
          </span>
        )}
        {saveStatus === "error" && (
          <span className="text-xs text-destructive" role="alert">
            {errorMessage ?? "Failed to save"}
          </span>
        )}
      </div>
    </div>
  );
}
