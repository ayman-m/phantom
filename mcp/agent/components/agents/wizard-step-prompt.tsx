"use client";

import type { ChangeEvent } from "react";

export interface WizardStepPromptProps {
  systemPrompt: string;
  onSystemPromptChange: (value: string) => void;
}

export function WizardStepPrompt({
  systemPrompt,
  onSystemPromptChange,
}: WizardStepPromptProps) {
  const charCount = systemPrompt.length;
  const lineCount = systemPrompt.split("\n").length;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <label
          htmlFor="system-prompt"
          className="block text-xs font-label uppercase tracking-widest text-on-surface-variant"
        >
          System Prompt
        </label>
        <span className="text-[10px] text-on-surface-variant/60">
          {charCount} chars &middot; {lineCount} lines
        </span>
      </div>

      <textarea
        id="system-prompt"
        value={systemPrompt}
        onChange={(e: ChangeEvent<HTMLTextAreaElement>) =>
          onSystemPromptChange(e.target.value)
        }
        placeholder="Enter the system prompt that defines this agent's behavior..."
        rows={12}
        className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-on-surface font-mono text-sm placeholder:text-on-surface-variant/50 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-colors resize-y leading-relaxed"
        aria-label="System prompt"
      />

      <p className="text-xs text-on-surface-variant">
        The system prompt sets the agent&apos;s identity and behavior. Be specific about
        the agent&apos;s role, capabilities, and constraints.
      </p>
    </div>
  );
}
