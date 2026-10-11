import { apiRequest, listRequest } from "./client";
import type { ApiRequestOptions } from "./client";
import type { Agent, AgentStats, CreateAgentRequest, UpdateAgentRequest } from "./types";

/** List all agents from GET /api/v1/agents. */
export function listAgents(options?: ApiRequestOptions) {
  return listRequest<Agent>("/api/v1/agents", options);
}

/** Fetch a single agent by ID from GET /api/v1/agents/:id. */
export function getAgent(id: string, options?: ApiRequestOptions) {
  return apiRequest<Agent>(`/api/v1/agents/${encodeURIComponent(id)}`, options);
}

/** Create a new agent via POST /api/v1/agents. */
export function createAgent(
  data: CreateAgentRequest,
  options?: ApiRequestOptions,
) {
  return apiRequest<Agent>("/api/v1/agents", {
    ...options,
    method: "POST",
    body: data,
  });
}

/** Update an agent by ID via PUT /api/v1/agents/:id. */
export function updateAgent(
  id: string,
  data: UpdateAgentRequest,
  options?: ApiRequestOptions,
) {
  return apiRequest<Agent>(`/api/v1/agents/${encodeURIComponent(id)}`, {
    ...options,
    method: "PUT",
    body: data,
  });
}

/** Delete an agent by ID via DELETE /api/v1/agents/:id. */
export function deleteAgent(id: string, options?: ApiRequestOptions) {
  return apiRequest<void>(
    `/api/v1/agents/${encodeURIComponent(id)}`,
    { ...options, method: "DELETE" },
  );
}

/** Fetch agent activity stats from GET /api/v1/agents/:id/stats?window=:window. */
export function getAgentStats(
  id: string,
  window = "7d",
  options?: ApiRequestOptions,
) {
  const params = new URLSearchParams({ window });
  return apiRequest<AgentStats>(
    `/api/v1/agents/${encodeURIComponent(id)}/stats?${params.toString()}`,
    options,
  );
}
