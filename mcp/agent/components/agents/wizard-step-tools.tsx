"use client";

import type { ToolDescriptor } from "@/lib/api/types";

export interface WizardStepToolsProps {
  tools: ToolDescriptor[];
  selectedTools: string[];
  onToggleTool: (toolName: string) => void;
  loading: boolean;
}

export function WizardStepTools({
  tools,
  selectedTools,
  onToggleTool,
  loading,
}: WizardStepToolsProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="flex items-center gap-3 text-on-surface-variant">
          <span className="material-symbols-outlined animate-spin">progress_activity</span>
          <span className="text-sm">Loading available tools...</span>
        </div>
      </div>
    );
  }

  if (tools.length === 0) {
    return (
      <div className="text-center py-12">
        <span className="material-symbols-outlined text-4xl text-on-surface-variant mb-2 block">
          build
        </span>
        <p className="text-sm text-on-surface-variant">
          No tools registered yet. Tools will be available once the tool-execution
          service is configured.
        </p>
      </div>
    );
  }

  // Group tools by their group field
  const groups = new Map<string, ToolDescriptor[]>();
  for (const tool of tools) {
    const group = tool.group || "Other";
    const existing = groups.get(group) ?? [];
    existing.push(tool);
    groups.set(group, existing);
  }

  const sortedGroupNames = Array.from(groups.keys()).sort();

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <label className="block text-xs font-label uppercase tracking-widest text-on-surface-variant">
          Select Tools
        </label>
        <span className="text-xs text-on-surface-variant">
          {selectedTools.length} selected
        </span>
      </div>

      {sortedGroupNames.map((groupName) => {
        const groupTools = groups.get(groupName) ?? [];
        return (
          <div key={groupName}>
            <h4 className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant/60 mb-2">
              {groupName}
            </h4>
            <div className="space-y-2">
              {groupTools.map((tool) => {
                const isSelected = selectedTools.includes(tool.name);
                return (
                  <label
                    key={tool.name}
                    className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-all ${
                      isSelected
                        ? "border-primary/30 bg-primary/5"
                        : "border-white/10 bg-white/5 hover:bg-white/8"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => onToggleTool(tool.name)}
                      className="mt-0.5 h-4 w-4 rounded border-white/30 bg-white/5 text-primary focus:ring-primary/50 accent-[#1963B3]"
                      aria-label={`Select ${tool.name}`}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <code className="text-sm font-mono font-medium text-on-surface">
                          {tool.name}
                        </code>
                      </div>
                      {tool.description && (
                        <p className="text-xs text-on-surface-variant mt-0.5 line-clamp-2">
                          {tool.description}
                        </p>
                      )}
                    </div>
                  </label>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
