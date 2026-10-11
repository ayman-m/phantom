"use client";

import * as React from "react";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { updateAgent } from "@/lib/api/agents";
import { listSkills } from "@/lib/api/skills";
import type { Agent, AgentSkillsConfig, SkillDescriptor } from "@/lib/api/types";

interface AgentSkillsTabProps {
  agent: Agent;
  onAgentUpdated?: (agent: Agent) => void;
}

function parseSkillsConfig(agent: Agent): AgentSkillsConfig {
  return {
    enabledSkills: agent.skillsConfig?.enabledSkills ?? [],
  };
}

export function AgentSkillsTab({ agent, onAgentUpdated }: AgentSkillsTabProps) {
  const initial = parseSkillsConfig(agent);
  const [enabledSkills, setEnabledSkills] = React.useState<Set<string>>(
    new Set(initial.enabledSkills ?? []),
  );
  const [availableSkills, setAvailableSkills] = React.useState<
    SkillDescriptor[]
  >([]);
  const [loadingSkills, setLoadingSkills] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [saveStatus, setSaveStatus] = React.useState<
    "idle" | "success" | "error"
  >("idle");
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);

  // Fetch available skills on mount
  React.useEffect(() => {
    let cancelled = false;
    async function fetchSkills() {
      setLoadingSkills(true);
      const result = await listSkills();
      if (!cancelled) {
        if (result.ok) {
          setAvailableSkills(result.data);
        }
        setLoadingSkills(false);
      }
    }
    fetchSkills();
    return () => {
      cancelled = true;
    };
  }, []);

  React.useEffect(() => {
    const cfg = parseSkillsConfig(agent);
    setEnabledSkills(new Set(cfg.enabledSkills ?? []));
  }, [agent]);

  function toggleSkill(skillName: string) {
    setEnabledSkills((prev) => {
      const next = new Set(prev);
      if (next.has(skillName)) {
        next.delete(skillName);
      } else {
        next.add(skillName);
      }
      return next;
    });
  }

  const isDirty =
    JSON.stringify([...enabledSkills].sort()) !==
    JSON.stringify([...(initial.enabledSkills ?? [])].sort());

  async function handleSave() {
    setSaving(true);
    setSaveStatus("idle");
    setErrorMessage(null);

    const skillsConfig: AgentSkillsConfig = {
      enabledSkills: [...enabledSkills],
    };

    const result = await updateAgent(agent.agent_id, { skillsConfig });

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
        Enable or disable skills for this agent. Skills provide specialized
        capabilities such as code review, deployment, or data analysis.
      </p>

      {loadingSkills ? (
        <p className="text-sm text-on-surface-variant">Loading skills...</p>
      ) : availableSkills.length === 0 ? (
        <div className="glass-panel p-6 rounded-xl text-center">
          <p className="text-sm text-on-surface-variant">
            No skills available. Skills will appear here once registered.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {availableSkills.map((skill) => (
            <div
              key={skill.name}
              className="flex items-center justify-between glass-panel p-4 rounded-xl"
            >
              <div className="space-y-0.5">
                <Label
                  htmlFor={`skill-${skill.name}`}
                  className="text-sm font-medium cursor-pointer"
                >
                  {skill.displayName}
                </Label>
                <p className="text-xs text-on-surface-variant/60">
                  {skill.description}
                </p>
                {!skill.eligibility.eligible && skill.eligibility.reason && (
                  <p className="text-xs text-amber-400/80">
                    {skill.eligibility.reason}
                  </p>
                )}
              </div>
              <Switch
                id={`skill-${skill.name}`}
                checked={enabledSkills.has(skill.name)}
                onCheckedChange={() => toggleSkill(skill.name)}
                disabled={!skill.eligibility.eligible}
                aria-label={`Toggle ${skill.displayName}`}
              />
            </div>
          ))}
        </div>
      )}

      {/* Save */}
      <div className="flex items-center gap-3">
        <Button
          type="button"
          disabled={!isDirty || saving}
          onClick={handleSave}
          className="bg-primary hover:bg-primary/90"
        >
          {saving ? "Saving..." : "Save Skills Config"}
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
