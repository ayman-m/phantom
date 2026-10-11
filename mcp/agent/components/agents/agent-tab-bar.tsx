"use client";

import * as React from "react";

export type AgentTab = "overview" | "model" | "tools" | "prompt" | "workspace";

const TABS: { key: AgentTab; label: string; icon: string }[] = [
  { key: "overview", label: "Overview", icon: "dashboard" },
  { key: "model", label: "Model", icon: "model_training" },
  { key: "tools", label: "Tools", icon: "construction" },
  { key: "prompt", label: "Prompt", icon: "edit_note" },
  { key: "workspace", label: "Workspace", icon: "folder_open" },
];

interface AgentTabBarProps {
  activeTab: AgentTab;
  onTabChange: (tab: AgentTab) => void;
  dirtyTabs?: Set<AgentTab>;
}

export function AgentTabBar({ activeTab, onTabChange, dirtyTabs }: AgentTabBarProps) {
  return (
    <nav className="flex items-center gap-8 border-b border-white/10 mb-8">
      {TABS.map((tab) => {
        const isActive = activeTab === tab.key;
        const isDirty = dirtyTabs?.has(tab.key);
        return (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onTabChange(tab.key)}
            className={`relative pb-3 text-sm font-label uppercase tracking-widest transition-colors ${
              isActive
                ? "text-secondary border-b-2 border-secondary font-bold"
                : "text-on-surface-variant hover:text-on-surface"
            }`}
          >
            {tab.label}
            {isDirty && (
              <span className="absolute -top-0.5 -right-2 w-2 h-2 rounded-full bg-primary" />
            )}
          </button>
        );
      })}
    </nav>
  );
}
