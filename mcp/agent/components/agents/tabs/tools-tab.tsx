"use client";

import * as React from "react";
import { updateAgent } from "@/lib/api/agents";
import type { Agent, ToolDescriptor } from "@/lib/api/types";

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

interface ToolsTabProps {
  agent: Agent;
  tools: ToolDescriptor[];
  onAgentUpdated: (agent: Agent) => void;
  onDirtyChange?: (dirty: boolean) => void;
}

interface ToolGroup {
  name: string;
  icon: string;
  iconColor: string;
  tools: ToolDescriptor[];
}

const GROUP_CONFIG: Record<string, { icon: string; iconColor: string }> = {
  orchestration: { icon: "hub", iconColor: "text-primary" },
  session: { icon: "forum", iconColor: "text-tertiary" },
  sandbox: { icon: "shield", iconColor: "text-error" },
};

const BUILTIN_GROUPS: ToolGroup[] = [
  {
    name: "Orchestration",
    icon: "hub",
    iconColor: "text-primary",
    tools: [
      { name: "spawn_subagent", description: "Start a child agent run with a specific agent ID and task", group: "orchestration", inputSchema: {} },
      { name: "check_subagent", description: "Poll a child run for status and result", group: "orchestration", inputSchema: {} },
      { name: "delegate_to_team", description: "Delegate a task to a team member selected by role/priority", group: "orchestration", inputSchema: {} },
      { name: "fan_out", description: "Dispatch the same task to multiple agents in parallel", group: "orchestration", inputSchema: {} },
      { name: "fan_in", description: "Collect and merge results from fan_out runs", group: "orchestration", inputSchema: {} },
      { name: "consensus", description: "Run a task on N agents and return majority-agreed result", group: "orchestration", inputSchema: {} },
    ],
  },
  {
    name: "Session",
    icon: "forum",
    iconColor: "text-tertiary",
    tools: [
      { name: "sessions_list", description: "List sessions for the current agent", group: "session", inputSchema: {} },
      { name: "sessions_history", description: "Retrieve message history for a session", group: "session", inputSchema: {} },
      { name: "sessions_send", description: "Send a message to another session", group: "session", inputSchema: {} },
      { name: "memory_search", description: "Search memory entries within the current run", group: "session", inputSchema: {} },
    ],
  },
  {
    name: "Sandbox",
    icon: "shield",
    iconColor: "text-error",
    tools: [
      { name: "shell_exec", description: "Execute a shell command in the agent sandbox", group: "sandbox", inputSchema: {} },
      { name: "file_read", description: "Read a file from the agent workspace", group: "sandbox", inputSchema: {} },
      { name: "file_write", description: "Write a file to the agent workspace", group: "sandbox", inputSchema: {} },
    ],
  },
];

export function ToolsTab({
  agent,
  tools,
  onAgentUpdated,
  onDirtyChange,
}: ToolsTabProps) {
  // Merge API tools with builtins, preferring API data when available
  const groups = React.useMemo<ToolGroup[]>(() => {
    if (tools.length === 0) return BUILTIN_GROUPS;

    const toolMap = new Map(tools.map((t) => [t.name, t]));
    const groupMap = new Map<string, ToolGroup>();

    // Start with builtin groups structure
    for (const bg of BUILTIN_GROUPS) {
      const merged: ToolDescriptor[] = bg.tools.map((bt) => toolMap.get(bt.name) ?? bt);
      groupMap.set(bg.name.toLowerCase().replace(/\s+/g, "-"), {
        ...bg,
        tools: merged,
      });
    }

    // Add any tools from API not in builtins
    for (const t of tools) {
      const gKey = t.group || "other";
      if (!groupMap.has(gKey)) {
        const cfg = GROUP_CONFIG[gKey] ?? { icon: "extension", iconColor: "text-on-surface-variant" };
        groupMap.set(gKey, {
          name: gKey.charAt(0).toUpperCase() + gKey.slice(1).replace(/-/g, " "),
          ...cfg,
          tools: [],
        });
      }
      const group = groupMap.get(gKey)!;
      if (!group.tools.some((gt) => gt.name === t.name)) {
        group.tools.push(t);
      }
    }

    return Array.from(groupMap.values());
  }, [tools]);

  // Build enabled set from agent config
  const initialEnabled = React.useMemo(() => {
    const cfg = agent.toolsConfig;
    const allTools = groups.flatMap((g) => g.tools.map((t) => t.name));
    // If allowedTools is set, use it. Otherwise all tools are enabled
    // minus denied ones.
    if (cfg?.allowedTools && cfg.allowedTools.length > 0) {
      return new Set(cfg.allowedTools);
    }
    const denied = new Set(cfg?.deniedTools ?? []);
    return new Set(allTools.filter((n) => !denied.has(n)));
  }, [agent.toolsConfig, groups]);

  const [enabledTools, setEnabledTools] = React.useState<Set<string>>(
    new Set(initialEnabled),
  );
  const [saving, setSaving] = React.useState(false);
  const [saveStatus, setSaveStatus] = React.useState<
    "idle" | "success" | "error"
  >("idle");

  React.useEffect(() => {
    setEnabledTools(new Set(initialEnabled));
  }, [initialEnabled]);

  const isDirty =
    JSON.stringify([...enabledTools].sort()) !==
    JSON.stringify([...initialEnabled].sort());

  React.useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);

  function toggleTool(name: string) {
    setEnabledTools((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function selectAll(group: ToolGroup) {
    setEnabledTools((prev) => {
      const next = new Set(prev);
      for (const t of group.tools) next.add(t.name);
      return next;
    });
  }

  function deselectAll(group: ToolGroup) {
    setEnabledTools((prev) => {
      const next = new Set(prev);
      for (const t of group.tools) next.delete(t.name);
      return next;
    });
  }

  async function handleSave() {
    setSaving(true);
    setSaveStatus("idle");

    const allTools = groups.flatMap((g) => g.tools.map((t) => t.name));
    const denied = allTools.filter((n) => !enabledTools.has(n));

    // Send tool_allow/tool_deny directly as proto-compatible fields.
    const result = await updateAgent(agent.agent_id, {
      tool_allow: [...enabledTools],
      tool_deny: denied,
    } as Record<string, unknown>);
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

  function handleCancel() {
    setEnabledTools(new Set(initialEnabled));
  }

  const enabledCount = enabledTools.size;

  return (
    <div className="space-y-6">
      {/* Tool Groups Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {groups.map((group) => {
          const allSelected = group.tools.every((t) =>
            enabledTools.has(t.name),
          );
          return (
            <div
              key={group.name}
              className="rounded-xl overflow-hidden"
              style={glassStyle}
            >
              {/* Group Header */}
              <div className="flex items-center justify-between px-5 py-4 border-b border-white/[0.06]">
                <div className="flex items-center gap-2.5">
                  <span
                    className={`material-symbols-outlined text-lg ${group.iconColor}`}
                  >
                    {group.icon}
                  </span>
                  <h3 className="text-sm font-headline font-bold text-on-surface">
                    {group.name}
                  </h3>
                  <span className="text-[10px] font-mono text-on-surface-variant/50">
                    {group.tools.filter((t) => enabledTools.has(t.name)).length}/
                    {group.tools.length}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    allSelected ? deselectAll(group) : selectAll(group)
                  }
                  className="text-[10px] font-label font-bold uppercase tracking-widest text-primary hover:text-primary/80 transition-colors"
                >
                  {allSelected ? "Deselect All" : "Select All"}
                </button>
              </div>

              {/* Tools List */}
              <div className="divide-y divide-white/[0.04]">
                {group.tools.map((tool) => {
                  const checked = enabledTools.has(tool.name);
                  return (
                    <label
                      key={tool.name}
                      className="flex items-start gap-3 px-5 py-3 hover:bg-white/[0.02] transition-colors cursor-pointer"
                    >
                      <div className="pt-0.5">
                        <div
                          className={`w-4 h-4 rounded border flex items-center justify-center transition-colors ${
                            checked
                              ? "bg-primary border-primary"
                              : "border-on-surface-variant/30 bg-transparent"
                          }`}
                        >
                          {checked && (
                            <span className="material-symbols-outlined text-xs text-on-primary-container">
                              check
                            </span>
                          )}
                        </div>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleTool(tool.name)}
                          className="sr-only"
                        />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-mono text-on-surface">
                          {tool.name}
                        </p>
                        <p className="text-xs text-on-surface-variant/60 mt-0.5">
                          {tool.description}
                        </p>
                      </div>
                    </label>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {/* Footer Bar */}
      <div
        className="flex items-center justify-between rounded-xl px-5 py-4"
        style={glassStyle}
      >
        <div className="flex items-center gap-3">
          <span className="text-sm text-on-surface-variant">
            <span className="font-bold text-on-surface">{enabledCount}</span>{" "}
            tools enabled
          </span>
          {saveStatus === "success" && (
            <span className="flex items-center gap-1.5 text-xs text-[#7bdc7b]">
              <span className="material-symbols-outlined text-base">
                check_circle
              </span>
              Saved
            </span>
          )}
          {saveStatus === "error" && (
            <span className="flex items-center gap-1.5 text-xs text-error">
              <span className="material-symbols-outlined text-base">error</span>
              Failed to save
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleCancel}
            disabled={!isDirty}
            className="px-4 py-2 rounded-lg text-sm font-label text-on-surface-variant hover:text-on-surface hover:bg-white/5 disabled:opacity-30 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!isDirty || saving}
            className="px-6 py-2.5 rounded-lg font-label font-bold text-xs uppercase tracking-widest text-on-primary-container disabled:opacity-30 transition-all hover:scale-[1.02] active:scale-95"
            style={{
              background: "linear-gradient(135deg, #1963b3 0%, #2d8df0 100%)",
            }}
          >
            {saving ? "Saving..." : "Save Tool Config"}
          </button>
        </div>
      </div>
    </div>
  );
}
