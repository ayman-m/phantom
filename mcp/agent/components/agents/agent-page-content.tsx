"use client";

import * as React from "react";
import { AgentPageHeader } from "./agent-page-header";
import { AgentTabBar, type AgentTab } from "./agent-tab-bar";
import { OverviewTab } from "./tabs/overview-tab";
import { ModelTab } from "./tabs/model-tab";
import { ToolsTab } from "./tabs/tools-tab";
import { PromptTab } from "./tabs/prompt-tab";
import { WorkspaceTab } from "./tabs/workspace-tab";
import type { Agent, AgentStats, Session, ModelInfo, ToolDescriptor } from "@/lib/api/types";
import type { Team } from "@/lib/api/teams";

interface AgentPageContentProps {
  agent: Agent;
  stats: AgentStats | null;
  sessions: Session[];
  models: ModelInfo[];
  tools: ToolDescriptor[];
  teams: Team[];
  initialTab?: string;
}

export function AgentPageContent({
  agent: initialAgent,
  stats,
  sessions,
  models,
  tools,
  teams,
  initialTab,
}: AgentPageContentProps) {
  const [agent, setAgent] = React.useState<Agent>(initialAgent);
  const [dirtyTabs, setDirtyTabs] = React.useState<Set<AgentTab>>(new Set());
  const [activeTab, setActiveTab] = React.useState<AgentTab>(
    (initialTab as AgentTab) || "overview",
  );

  React.useEffect(() => {
    setAgent(initialAgent);
  }, [initialAgent]);

  // Update URL without triggering navigation (for bookmarkability)
  const handleTabChange = React.useCallback((tab: AgentTab) => {
    setActiveTab(tab);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", tab);
    window.history.replaceState({}, "", url.toString());
  }, []);

  function handleAgentUpdated(updated: Agent) {
    setAgent(updated);
  }

  function makeDirtyHandler(tab: AgentTab) {
    return (dirty: boolean) => {
      setDirtyTabs((prev) => {
        const next = new Set(prev);
        if (dirty) next.add(tab);
        else next.delete(tab);
        return next;
      });
    };
  }

  return (
    <>
      {/* Header */}
      <AgentPageHeader
        agent={agent}
        presence={null}
        onAgentUpdated={handleAgentUpdated}
      />

      {/* Tab Bar */}
      <AgentTabBar
        activeTab={activeTab}
        onTabChange={handleTabChange}
        dirtyTabs={dirtyTabs}
      />

      {/* Tab Content */}
      <div role="tabpanel">
        {activeTab === "overview" && (
          <OverviewTab
            agent={agent}
            stats={stats}
            sessions={sessions}
            teams={teams}
            onAgentUpdated={handleAgentUpdated}
          />
        )}
        {activeTab === "model" && (
          <ModelTab
            agent={agent}
            models={models}
            onAgentUpdated={handleAgentUpdated}
            onDirtyChange={makeDirtyHandler("model")}
          />
        )}
        {activeTab === "tools" && (
          <ToolsTab
            agent={agent}
            tools={tools}
            onAgentUpdated={handleAgentUpdated}
            onDirtyChange={makeDirtyHandler("tools")}
          />
        )}
        {activeTab === "prompt" && (
          <PromptTab
            agent={agent}
            onAgentUpdated={handleAgentUpdated}
            onDirtyChange={makeDirtyHandler("prompt")}
          />
        )}
        {activeTab === "workspace" && (
          <WorkspaceTab agentId={agent.agent_id} />
        )}
      </div>
    </>
  );
}
