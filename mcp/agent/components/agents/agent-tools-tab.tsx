"use client";

import * as React from "react";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { updateAgent } from "@/lib/api/agents";
import type { Agent, AgentToolsConfig } from "@/lib/api/types";

interface AgentToolsTabProps {
  agent: Agent;
  onAgentUpdated?: (agent: Agent) => void;
}

function parseToolsConfig(agent: Agent): AgentToolsConfig {
  return {
    allowedTools: agent.toolsConfig?.allowedTools ?? [],
    deniedTools: agent.toolsConfig?.deniedTools ?? [],
  };
}

export function AgentToolsTab({ agent, onAgentUpdated }: AgentToolsTabProps) {
  const initial = parseToolsConfig(agent);
  const [allowedText, setAllowedText] = React.useState(
    (initial.allowedTools ?? []).join("\n"),
  );
  const [deniedText, setDeniedText] = React.useState(
    (initial.deniedTools ?? []).join("\n"),
  );
  const [saving, setSaving] = React.useState(false);
  const [saveStatus, setSaveStatus] = React.useState<
    "idle" | "success" | "error"
  >("idle");
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);

  React.useEffect(() => {
    const cfg = parseToolsConfig(agent);
    setAllowedText((cfg.allowedTools ?? []).join("\n"));
    setDeniedText((cfg.deniedTools ?? []).join("\n"));
  }, [agent]);

  function parseLines(text: string): string[] {
    return text
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
  }

  const currentAllowed = parseLines(allowedText);
  const currentDenied = parseLines(deniedText);

  const isDirty =
    JSON.stringify(currentAllowed) !==
      JSON.stringify(initial.allowedTools ?? []) ||
    JSON.stringify(currentDenied) !==
      JSON.stringify(initial.deniedTools ?? []);

  async function handleSave() {
    setSaving(true);
    setSaveStatus("idle");
    setErrorMessage(null);

    const toolsConfig: AgentToolsConfig = {
      allowedTools: currentAllowed,
      deniedTools: currentDenied,
    };

    const result = await updateAgent(agent.agent_id, { toolsConfig });

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
      <p className="text-sm text-on-surface-variant">
        Control which tools this agent can use. If the allow list is empty, all
        tools are permitted unless explicitly denied.
      </p>

      {/* Allowed Tools */}
      <div className="space-y-2">
        <Label htmlFor="agent-allowed-tools">Allowed Tools</Label>
        <textarea
          id="agent-allowed-tools"
          value={allowedText}
          onChange={(e) => setAllowedText(e.target.value)}
          placeholder={"read_file\nshell_exec\nweb_search"}
          rows={6}
          className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-y font-mono"
        />
        <p className="text-xs text-on-surface-variant/60">
          One tool name per line. Leave empty to allow all tools.
        </p>
      </div>

      {/* Denied Tools */}
      <div className="space-y-2">
        <Label htmlFor="agent-denied-tools">Denied Tools</Label>
        <textarea
          id="agent-denied-tools"
          value={deniedText}
          onChange={(e) => setDeniedText(e.target.value)}
          placeholder={"shell_exec\ndelete_file"}
          rows={6}
          className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-y font-mono"
        />
        <p className="text-xs text-on-surface-variant/60">
          One tool name per line. These tools will be blocked even if present in
          the allow list.
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
          {saving ? "Saving..." : "Save Tool Config"}
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
