/**
 * Agent definition client
 *
 * Wraps `/api/agent/agent-definitions` (proxy to the MCP's
 * `/api/v1/agent-definitions`). Used by the /agents page and any
 * future "agent picker" UI.
 */

export type AgentIsolation = "parent_session" | "fresh_session";

export interface AgentDefinition {
  id: string;
  name: string;
  description: string;
  /** The system prompt the subagent runs with. NOT inherited from
   *  the parent. */
  system_prompt: string;
  /** Glob list. Empty = all tools (NOT recommended). */
  tools_allowed: string[];
  /** Glob list. Deny wins when both lists match. */
  tools_denied: string[];
  /** null = inherit parent's effective model. */
  model: string | null;
  /** Subagent loop budget. 1..50; default 10. */
  max_turns: number;
  isolation: AgentIsolation;
  /** 'operator' | 'plugin:<name>' | 'builtin'. Provenance for the
   *  /agents UI badge. */
  origin: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface AgentDefinitionListResponse {
  agent_definitions: AgentDefinition[];
  count: number;
}

export async function listAgentDefinitions(params: {
  origin?: string;
  enabled_only?: boolean;
} = {}): Promise<AgentDefinitionListResponse> {
  const sp = new URLSearchParams();
  if (params.origin) sp.set("origin", params.origin);
  if (params.enabled_only) sp.set("enabled_only", "1");
  const qs = sp.toString();
  const r = await fetch(
    `/api/agent/agent-definitions${qs ? `?${qs}` : ""}`,
    { cache: "no-store" },
  );
  if (!r.ok) throw new Error(`agent-definitions list ${r.status}`);
  return (await r.json()) as AgentDefinitionListResponse;
}

export async function getAgentDefinition(
  id: string,
): Promise<AgentDefinition | null> {
  const r = await fetch(
    `/api/agent/agent-definitions/${encodeURIComponent(id)}`,
    { cache: "no-store" },
  );
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`agent-definitions get ${r.status}`);
  const data = (await r.json()) as { agent_definition: AgentDefinition };
  return data.agent_definition;
}

export async function upsertAgentDefinition(
  body: Partial<AgentDefinition>,
): Promise<AgentDefinition> {
  const r = await fetch(`/api/agent/agent-definitions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`agent-definitions upsert ${r.status}: ${text.slice(0, 200)}`);
  }
  const data = (await r.json()) as { agent_definition: AgentDefinition };
  return data.agent_definition;
}

export async function patchAgentDefinition(
  id: string,
  body: Partial<AgentDefinition>,
): Promise<AgentDefinition> {
  const r = await fetch(
    `/api/agent/agent-definitions/${encodeURIComponent(id)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (!r.ok) throw new Error(`agent-definitions patch ${r.status}`);
  const data = (await r.json()) as { agent_definition: AgentDefinition };
  return data.agent_definition;
}

export async function deleteAgentDefinition(id: string): Promise<void> {
  const r = await fetch(
    `/api/agent/agent-definitions/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
  if (!r.ok) throw new Error(`agent-definitions delete ${r.status}`);
}

export function originBadgeTone(origin: string): {
  bg: string;
  fg: string;
  label: string;
} {
  if (origin.startsWith("plugin:")) {
    return {
      bg: "bg-tertiary/15",
      fg: "text-tertiary",
      label: origin,
    };
  }
  if (origin === "builtin") {
    return {
      bg: "bg-primary/15",
      fg: "text-primary",
      label: "builtin",
    };
  }
  return {
    bg: "bg-secondary/15",
    fg: "text-secondary",
    label: "operator",
  };
}
