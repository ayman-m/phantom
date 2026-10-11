"use client";

import * as React from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { updateAgent } from "@/lib/api/agents";
import type { Agent } from "@/lib/api/types";

interface AgentGeneralTabProps {
  agent: Agent;
  onAgentUpdated?: (agent: Agent) => void;
}

export function AgentGeneralTab({ agent, onAgentUpdated }: AgentGeneralTabProps) {
  const [name, setName] = React.useState(agent.name);
  const [description, setDescription] = React.useState(agent.description);
  const [systemPrompt, setSystemPrompt] = React.useState(
    agent.systemPrompt ?? "",
  );
  const [saving, setSaving] = React.useState(false);
  const [saveStatus, setSaveStatus] = React.useState<
    "idle" | "success" | "error"
  >("idle");
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);

  // Sync local state when the parent passes a new agent object
  React.useEffect(() => {
    setName(agent.name);
    setDescription(agent.description);
    setSystemPrompt(agent.systemPrompt ?? "");
  }, [agent.name, agent.description, agent.systemPrompt]);

  const isDirty =
    name !== agent.name ||
    description !== agent.description ||
    systemPrompt !== (agent.systemPrompt ?? "");

  async function handleSave() {
    setSaving(true);
    setSaveStatus("idle");
    setErrorMessage(null);

    const result = await updateAgent(agent.agent_id, {
      name,
      description,
      systemPrompt: systemPrompt || null,
    });

    setSaving(false);

    if (result.ok) {
      setSaveStatus("success");
      onAgentUpdated?.(result.data);
      // Clear success indicator after 2 seconds
      setTimeout(() => setSaveStatus("idle"), 2000);
    } else {
      setSaveStatus("error");
      setErrorMessage(result.error.message);
    }
  }

  return (
    <div className="space-y-6">
      {/* Name */}
      <div className="space-y-2">
        <Label htmlFor="agent-name">Name</Label>
        <Input
          id="agent-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Agent name"
        />
      </div>

      {/* Description */}
      <div className="space-y-2">
        <Label htmlFor="agent-description">Description</Label>
        <Input
          id="agent-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Brief description of this agent"
        />
      </div>

      {/* System Prompt */}
      <div className="space-y-2">
        <Label htmlFor="agent-system-prompt">System Prompt</Label>
        <textarea
          id="agent-system-prompt"
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          placeholder="Enter the system prompt for this agent..."
          rows={8}
          className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-y font-mono"
        />
        <p className="text-xs text-on-surface-variant/60">
          Instructions that define how this agent behaves. Supports markdown.
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
          {saving ? "Saving..." : "Save Changes"}
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
