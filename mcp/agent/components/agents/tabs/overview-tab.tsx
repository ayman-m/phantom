"use client";

import * as React from "react";
import Link from "next/link";
import { updateAgent } from "@/lib/api/agents";
import type { Agent, AgentStats, Session } from "@/lib/api/types";
import type { Team } from "@/lib/api/teams";

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

interface OverviewTabProps {
  agent: Agent;
  stats: AgentStats | null;
  sessions: Session[];
  teams: Team[];
  onAgentUpdated: (agent: Agent) => void;
}

function formatRelativeTime(dateStr?: string | null): string {
  if (!dateStr) return "Never";
  const value = new Date(dateStr);
  if (Number.isNaN(value.getTime())) return "Unknown";
  const diffMs = Date.now() - value.getTime();
  const diffSeconds = Math.floor(diffMs / 1000);
  if (diffSeconds < 60) return `${diffSeconds}s ago`;
  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toString();
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return "Unknown";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

export function OverviewTab({
  agent,
  stats,
  sessions,
  teams,
  onAgentUpdated,
}: OverviewTabProps) {
  const [description, setDescription] = React.useState(agent.description);
  const [standingOrders, setStandingOrders] = React.useState(agent.standing_orders ?? "");
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    setDescription(agent.description);
  }, [agent.description]);

  React.useEffect(() => {
    setStandingOrders(agent.standing_orders ?? "");
  }, [agent.standing_orders]);

  const isDescriptionDirty = description !== agent.description;
  const isOrdersDirty = standingOrders !== (agent.standing_orders ?? "");
  const isDirty = isDescriptionDirty || isOrdersDirty;

  async function handleSave() {
    if (!isDirty) return;
    setSaving(true);
    const payload: Record<string, string> = {};
    if (isDescriptionDirty) payload.description = description;
    if (isOrdersDirty) payload.standing_orders = standingOrders;
    const result = await updateAgent(agent.agent_id, payload);
    setSaving(false);
    if (result.ok) {
      onAgentUpdated(result.data);
    }
  }

  const totalRuns = stats?.total_runs ?? 0;
  const totalTokens =
    (stats?.total_input_tokens ?? 0) + (stats?.total_output_tokens ?? 0);
  const avgDuration = stats?.recent_runs.length
    ? Math.round(
        stats.recent_runs.reduce((sum, r) => {
          if (!r.created_at || !r.completed_at) return sum;
          return (
            sum +
            new Date(r.completed_at).getTime() -
            new Date(r.created_at).getTime()
          );
        }, 0) / stats.recent_runs.length / 1000,
      )
    : 0;

  const recentSessions = sessions.slice(0, 5);
  const agentTeams = teams.filter((t) =>
    t.members.some((m) => m.agent_id === agent.agent_id),
  );

  const statCards = [
    {
      label: "Total Runs",
      value: formatNumber(totalRuns),
      icon: "play_circle",
      color: "text-primary",
      bgColor: "bg-primary-container/20",
    },
    {
      label: "Total Tokens",
      value: formatNumber(totalTokens),
      icon: "generating_tokens",
      color: "text-secondary",
      bgColor: "bg-secondary-container/20",
    },
    {
      label: "Avg Duration",
      value: avgDuration > 0 ? `${avgDuration}s` : "--",
      icon: "timer",
      color: "text-tertiary",
      bgColor: "bg-tertiary-container/20",
    },
    {
      label: "Last Active",
      value: formatRelativeTime(agent.lastActiveAt),
      icon: "schedule",
      color: "text-on-surface-variant",
      bgColor: "bg-surface-container-high/30",
    },
  ];

  return (
    <div className="space-y-6">
      {/* Description */}
      <div className="rounded-xl p-5 space-y-3" style={glassStyle}>
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-label uppercase tracking-widest text-on-surface-variant">
            Description
          </h3>
          {isDescriptionDirty && (
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="text-xs font-label font-bold uppercase tracking-widest text-primary hover:text-primary/80 transition-colors disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save"}
            </button>
          )}
        </div>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Describe what this agent does..."
          rows={3}
          className="w-full bg-transparent text-sm text-on-surface placeholder:text-on-surface-variant/40 resize-none outline-none"
        />
      </div>

      {/* Standing Orders */}
      <div className="rounded-xl p-5 space-y-3" style={glassStyle}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-base text-on-surface-variant">
              shield
            </span>
            <h3 className="text-xs font-label uppercase tracking-widest text-on-surface-variant">
              Standing Orders
            </h3>
          </div>
          {isOrdersDirty && (
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="text-xs font-label font-bold uppercase tracking-widest text-primary hover:text-primary/80 transition-colors disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save"}
            </button>
          )}
        </div>
        <textarea
          value={standingOrders}
          onChange={(e) => setStandingOrders(e.target.value)}
          placeholder="Instructions that apply to every run..."
          rows={4}
          className="w-full bg-transparent text-sm text-on-surface placeholder:text-on-surface-variant/40 resize-none outline-none font-mono"
        />
        <p className="text-[10px] text-on-surface-variant/50">
          Instructions that apply to every run. Use for safety guidelines,
          behavioral constraints, and operational boundaries.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Stats + Sessions */}
        <div className="lg:col-span-2 space-y-6">
          {/* Stats Grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {statCards.map((card) => (
              <div
                key={card.label}
                className="rounded-xl p-4 hover:bg-white/[0.02] transition-colors"
                style={glassStyle}
              >
                <div className="flex items-center justify-between mb-3">
                  <span className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant">
                    {card.label}
                  </span>
                  <div
                    className={`w-8 h-8 rounded-lg ${card.bgColor} flex items-center justify-center`}
                  >
                    <span
                      className={`material-symbols-outlined text-base ${card.color}`}
                    >
                      {card.icon}
                    </span>
                  </div>
                </div>
                <p className={`text-xl font-headline font-bold ${card.color}`}>
                  {card.value}
                </p>
              </div>
            ))}
          </div>

          {/* Recent Sessions Table */}
          <div className="rounded-xl overflow-hidden" style={glassStyle}>
            <div className="px-5 py-4 border-b border-white/[0.06]">
              <h3 className="text-xs font-label uppercase tracking-widest text-on-surface-variant">
                Recent Sessions
              </h3>
            </div>
            {recentSessions.length === 0 ? (
              <div className="p-8 text-center">
                <p className="text-sm text-on-surface-variant">
                  No sessions yet
                </p>
              </div>
            ) : (
              <table className="w-full text-left">
                <thead>
                  <tr className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant border-b border-white/[0.04]">
                    <th className="px-5 py-3 font-semibold">Session ID</th>
                    <th className="px-5 py-3 font-semibold">Created</th>
                    <th className="px-5 py-3 font-semibold">Runs</th>
                    <th className="px-5 py-3 font-semibold">Model</th>
                    <th className="px-5 py-3 font-semibold">Tokens</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {recentSessions.map((session) => {
                    const tokens =
                      parseInt(session.total_input_tokens, 10) +
                      parseInt(session.total_output_tokens, 10);
                    return (
                      <tr
                        key={session.session_id}
                        className="hover:bg-white/[0.02] transition-colors"
                      >
                        <td className="px-5 py-3">
                          <Link
                            href={`/agents/${agent.agent_id}/sessions/${session.session_id}`}
                            className="font-mono text-sm text-primary hover:underline"
                          >
                            {session.session_id.slice(0, 12)}...
                          </Link>
                        </td>
                        <td className="px-5 py-3 text-sm text-on-surface/80">
                          {formatDate(session.created_at)}
                        </td>
                        <td className="px-5 py-3 text-sm font-mono text-on-surface/80">
                          {session.run_count}
                        </td>
                        <td className="px-5 py-3 text-sm font-mono text-on-surface/80">
                          {session.last_model || "--"}
                        </td>
                        <td className="px-5 py-3 text-sm font-mono text-on-surface/80">
                          {formatNumber(tokens)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Right Column: Team Membership */}
        <div className="space-y-4">
          <div className="rounded-xl p-5 space-y-4" style={glassStyle}>
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-label uppercase tracking-widest text-on-surface-variant">
                Team Membership
              </h3>
              <Link
                href="/agents/teams"
                className="text-xs font-label font-bold uppercase tracking-widest text-primary hover:text-primary/80 transition-colors"
              >
                Assign to Team
              </Link>
            </div>
            {agentTeams.length === 0 ? (
              <p className="text-sm text-on-surface-variant">
                Not assigned to any teams.
              </p>
            ) : (
              <div className="space-y-3">
                {agentTeams.map((team) => {
                  const member = team.members.find(
                    (m) => m.agent_id === agent.agent_id,
                  );
                  return (
                    <Link
                      key={team.team_id}
                      href={`/agents/teams`}
                      className="flex items-center justify-between p-3 rounded-lg bg-white/[0.02] hover:bg-white/[0.05] transition-colors"
                    >
                      <div>
                        <p className="text-sm font-medium text-on-surface">
                          {team.name}
                        </p>
                        <p className="text-xs text-on-surface-variant">
                          Role: {member?.role || "member"}
                        </p>
                      </div>
                      <span className="material-symbols-outlined text-base text-on-surface-variant">
                        chevron_right
                      </span>
                    </Link>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
