"use client";

import * as React from "react";
import { updateAgent } from "@/lib/api/agents";
import type { Agent } from "@/lib/api/types";

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

interface PromptTabProps {
  agent: Agent;
  onAgentUpdated: (agent: Agent) => void;
  onDirtyChange?: (dirty: boolean) => void;
}

interface TemplateVariable {
  name: string;
  description: string;
}

const TEMPLATE_VARIABLES: TemplateVariable[] = [
  { name: "{{agent_name}}", description: "The name of this agent" },
  { name: "{{agent_id}}", description: "Unique identifier for this agent" },
  { name: "{{agent_description}}", description: "Agent description text" },
  { name: "{{session_id}}", description: "Current session identifier" },
  { name: "{{run_id}}", description: "Current run identifier" },
  { name: "{{model}}", description: "Model being used for this run" },
  { name: "{{think_level}}", description: "Current thinking level setting" },
  { name: "{{timestamp}}", description: "Current UTC timestamp" },
  { name: "{{date}}", description: "Current date in YYYY-MM-DD format" },
  { name: "{{tools}}", description: "List of enabled tools" },
  { name: "{{team_name}}", description: "Name of the agent team if assigned" },
  { name: "{{user_input}}", description: "The user message or task input" },
  { name: "{{memory_context}}", description: "Relevant memory entries from search" },
  { name: "{{workspace_files}}", description: "List of files in workspace" },
];

const VAR_REGEX = /(\{\{[a-z_]+\}\})/g;

function highlightTemplateVars(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  const segments = text.split(VAR_REGEX);

  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    if (VAR_REGEX.test(seg)) {
      parts.push(
        <span
          key={i}
          className="text-primary bg-primary/[0.1] px-0.5 rounded"
        >
          {seg}
        </span>,
      );
    } else {
      parts.push(seg);
    }
  }

  return parts;
}

export function PromptTab({
  agent,
  onAgentUpdated,
  onDirtyChange,
}: PromptTabProps) {
  const [prompt, setPrompt] = React.useState(agent.systemPrompt ?? "");
  const [saving, setSaving] = React.useState(false);
  const [saveStatus, setSaveStatus] = React.useState<
    "idle" | "success" | "error"
  >("idle");
  const [varSearch, setVarSearch] = React.useState("");
  const [showPreview, setShowPreview] = React.useState(false);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  React.useEffect(() => {
    setPrompt(agent.systemPrompt ?? "");
  }, [agent.systemPrompt]);

  const isDirty = prompt !== (agent.systemPrompt ?? "");

  React.useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);

  const lineCount = prompt.split("\n").length;
  const charCount = prompt.length;

  const filteredVars = TEMPLATE_VARIABLES.filter(
    (v) =>
      v.name.toLowerCase().includes(varSearch.toLowerCase()) ||
      v.description.toLowerCase().includes(varSearch.toLowerCase()),
  );

  function insertVariable(varName: string) {
    const textarea = textareaRef.current;
    if (!textarea) return;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const before = prompt.slice(0, start);
    const after = prompt.slice(end);
    const newPrompt = `${before}${varName}${after}`;
    setPrompt(newPrompt);
    // Restore cursor position after the inserted variable
    requestAnimationFrame(() => {
      textarea.focus();
      const newPos = start + varName.length;
      textarea.setSelectionRange(newPos, newPos);
    });
  }

  function handleReset() {
    setPrompt(agent.systemPrompt ?? "");
  }

  async function handleSave() {
    setSaving(true);
    setSaveStatus("idle");

    const result = await updateAgent(agent.agent_id, {
      systemPrompt: prompt || null,
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
      <div className="grid grid-cols-1 lg:grid-cols-10 gap-6">
        {/* Left: Editor */}
        <div className="lg:col-span-7">
          <div className="rounded-xl overflow-hidden" style={glassStyle}>
            {/* Editor Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06] bg-surface-container-lowest/60">
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5">
                  <span className="w-3 h-3 rounded-full bg-error/60" />
                  <span className="w-3 h-3 rounded-full bg-[#d97706]/60" />
                  <span className="w-3 h-3 rounded-full bg-[#7bdc7b]/60" />
                </div>
                <span className="text-xs font-mono text-on-surface-variant/60 ml-2">
                  system-prompt.md
                </span>
              </div>
              <div className="flex items-center gap-2">
                {saveStatus === "success" && (
                  <span className="text-xs text-[#7bdc7b]">Saved</span>
                )}
                {saveStatus === "error" && (
                  <span className="text-xs text-error">Failed to save</span>
                )}
              </div>
            </div>

            {/* Editor Content */}
            {showPreview ? (
              <div className="p-5 min-h-[400px] max-h-[600px] overflow-y-auto bg-surface-container-lowest/40">
                <div className="font-mono text-sm text-on-surface/90 leading-relaxed whitespace-pre-wrap">
                  {highlightTemplateVars(prompt)}
                </div>
              </div>
            ) : (
              <textarea
                ref={textareaRef}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Enter the system prompt template for this agent..."
                className="w-full min-h-[400px] max-h-[600px] p-5 bg-surface-container-lowest/40 font-mono text-sm text-on-surface/90 leading-relaxed resize-y outline-none placeholder:text-on-surface-variant/30"
                spellCheck={false}
              />
            )}

            {/* Editor Footer */}
            <div className="flex items-center justify-between px-4 py-2.5 border-t border-white/[0.06] bg-surface-container-lowest/60">
              <div className="flex items-center gap-4 text-[10px] font-mono text-on-surface-variant/50">
                <span>{charCount} chars</span>
                <span>{lineCount} lines</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleReset}
                  disabled={!isDirty}
                  className="px-3 py-1.5 rounded text-[10px] font-label font-bold uppercase tracking-widest text-on-surface-variant hover:text-on-surface hover:bg-white/5 disabled:opacity-30 transition-colors"
                >
                  Reset
                </button>
                <button
                  type="button"
                  onClick={() => setShowPreview(!showPreview)}
                  className={`px-3 py-1.5 rounded text-[10px] font-label font-bold uppercase tracking-widest transition-colors ${
                    showPreview
                      ? "text-primary bg-primary/10"
                      : "text-on-surface-variant hover:text-on-surface hover:bg-white/5"
                  }`}
                >
                  {showPreview ? "Edit" : "Preview"}
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Right: Variables Panel */}
        <div className="lg:col-span-3">
          <div
            className="rounded-xl overflow-hidden h-full flex flex-col"
            style={glassStyle}
          >
            <div className="px-4 py-3 border-b border-white/[0.06]">
              <h3 className="text-xs font-label uppercase tracking-widest text-on-surface-variant mb-3">
                Available Variables
              </h3>
              <div className="relative">
                <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-base text-on-surface-variant/40">
                  search
                </span>
                <input
                  type="text"
                  value={varSearch}
                  onChange={(e) => setVarSearch(e.target.value)}
                  placeholder="Search variables..."
                  className="w-full pl-8 pr-3 py-2 rounded-lg bg-white/[0.03] border border-white/[0.08] text-sm text-on-surface outline-none placeholder:text-on-surface-variant/30"
                />
              </div>
            </div>

            <div className="flex-1 overflow-y-auto max-h-[500px]">
              <div className="divide-y divide-white/[0.04]">
                {filteredVars.map((v) => (
                  <button
                    key={v.name}
                    type="button"
                    onClick={() => insertVariable(v.name)}
                    className="w-full flex items-start gap-2 px-4 py-3 text-left hover:bg-white/[0.03] transition-colors group"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-mono text-primary">
                        {v.name}
                      </p>
                      <p className="text-[10px] text-on-surface-variant/60 mt-0.5">
                        {v.description}
                      </p>
                    </div>
                    <span className="material-symbols-outlined text-base text-on-surface-variant/0 group-hover:text-primary/60 transition-colors mt-0.5">
                      add
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Save Bar */}
      <div
        className="flex items-center justify-end rounded-xl px-5 py-4"
        style={glassStyle}
      >
        <button
          type="button"
          onClick={handleSave}
          disabled={!isDirty || saving}
          className="px-6 py-2.5 rounded-lg font-label font-bold text-xs uppercase tracking-widest text-on-primary-container disabled:opacity-30 transition-all hover:scale-[1.02] active:scale-95"
          style={{
            background: "linear-gradient(135deg, #1963b3 0%, #2d8df0 100%)",
          }}
        >
          {saving ? "Saving..." : "Save Prompt"}
        </button>
      </div>
    </div>
  );
}
