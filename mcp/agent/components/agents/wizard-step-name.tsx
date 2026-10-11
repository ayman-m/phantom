"use client";

import type { ChangeEvent } from "react";

/** Template definition for agent presets. */
export interface AgentTemplate {
  id: string;
  label: string;
  icon: string;
  model: string;
  tools: string[];
  systemPrompt: string;
  description: string;
}

export const AGENT_TEMPLATES: AgentTemplate[] = [
  {
    id: "coder",
    label: "Coder",
    icon: "code",
    model: "claude-sonnet-4-20250514",
    tools: [
      "spawn_subagent",
      "claude_code_start",
      "claude_code_status",
      "claude_code_output",
      "claude_code_cancel",
    ],
    systemPrompt:
      "You are a coding assistant. You write clean, well-tested code following the project's conventions. You use tools to run code, read files, and execute shell commands as needed.",
    description: "AI coding assistant with Claude Code tools",
  },
  {
    id: "researcher",
    label: "Researcher",
    icon: "science",
    model: "claude-opus-4-20250514",
    tools: ["spawn_subagent"],
    systemPrompt:
      "You are a research analyst. You break down complex questions, gather evidence, and produce structured analyses with citations.",
    description: "Deep research and analysis agent",
  },
  {
    id: "reviewer",
    label: "Reviewer",
    icon: "rate_review",
    model: "claude-haiku-4-20250514",
    tools: ["check_subagent"],
    systemPrompt:
      "You review code changes for correctness, style, and potential issues. Provide constructive feedback with specific line references.",
    description: "Automated code review agent",
  },
];

export interface WizardStepNameProps {
  name: string;
  description: string;
  onNameChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
  onApplyTemplate: (template: AgentTemplate) => void;
  selectedTemplate: string | null;
}

export function WizardStepName({
  name,
  description,
  onNameChange,
  onDescriptionChange,
  onApplyTemplate,
  selectedTemplate,
}: WizardStepNameProps) {
  return (
    <div className="space-y-8">
      {/* Template Selector */}
      <div>
        <label className="block text-xs font-label uppercase tracking-widest text-on-surface-variant mb-3">
          Start from template (optional)
        </label>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {AGENT_TEMPLATES.map((tpl) => (
            <button
              key={tpl.id}
              type="button"
              onClick={() => onApplyTemplate(tpl)}
              className={`p-4 rounded-xl border text-left transition-all ${
                selectedTemplate === tpl.id
                  ? "border-primary bg-primary/10 shadow-[0_0_12px_rgba(25,99,179,0.2)]"
                  : "border-white/10 bg-white/5 hover:bg-white/10 hover:border-white/20"
              }`}
              aria-pressed={selectedTemplate === tpl.id}
            >
              <div className="flex items-center gap-3 mb-2">
                <span className="material-symbols-outlined text-primary">
                  {tpl.icon}
                </span>
                <span className="font-headline font-bold">{tpl.label}</span>
              </div>
              <p className="text-xs text-on-surface-variant">{tpl.description}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Name Input */}
      <div>
        <label
          htmlFor="agent-name"
          className="block text-xs font-label uppercase tracking-widest text-on-surface-variant mb-2"
        >
          Agent Name
        </label>
        <input
          id="agent-name"
          type="text"
          value={name}
          onChange={(e: ChangeEvent<HTMLInputElement>) => onNameChange(e.target.value)}
          placeholder="e.g. My Coding Agent"
          className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-on-surface placeholder:text-on-surface-variant/50 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-colors"
          aria-label="Agent name"
        />
      </div>

      {/* Description Input */}
      <div>
        <label
          htmlFor="agent-description"
          className="block text-xs font-label uppercase tracking-widest text-on-surface-variant mb-2"
        >
          Description
        </label>
        <textarea
          id="agent-description"
          value={description}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) =>
            onDescriptionChange(e.target.value)
          }
          placeholder="Describe what this agent does..."
          rows={3}
          className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-on-surface placeholder:text-on-surface-variant/50 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-colors resize-none"
          aria-label="Agent description"
        />
      </div>
    </div>
  );
}
