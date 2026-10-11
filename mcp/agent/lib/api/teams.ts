import { apiRequest, listRequest } from "./client";
import type { ApiRequestOptions } from "./client";

// ─── Types ────────────────────────────────────────────────────────────────────

/** A member within an agent team. */
export interface TeamMember {
  agent_id: string;
  role: string;
  priority: number;
}

/** Agent team entity returned by the API (proto JSON / snake_case). */
export interface Team {
  team_id: string;
  name: string;
  description: string;
  supervisor_id: string;
  members: TeamMember[];
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** Payload for creating a team. */
export interface CreateTeamPayload {
  name: string;
  description: string;
  supervisor_id: string;
  members?: TeamMember[];
  config?: Record<string, unknown>;
}

/** Payload for updating a team. */
export interface UpdateTeamPayload {
  team_id: string;
  name?: string;
  description?: string;
  supervisor_id?: string;
  members?: TeamMember[];
  config?: Record<string, unknown>;
}

// ─── API Helpers ──────────────────────────────────────────────────────────────

/** List teams from GET /api/v1/teams. */
export function listTeams(options?: ApiRequestOptions) {
  return listRequest<Team>("/api/v1/teams", options);
}

/** Get a single team by ID from GET /api/v1/teams/:id. */
export function getTeam(id: string, options?: ApiRequestOptions) {
  return apiRequest<Team>(
    `/api/v1/teams/${encodeURIComponent(id)}`,
    options,
  );
}

/** Create a new team via POST /api/v1/teams. */
export function createTeam(payload: CreateTeamPayload, options?: ApiRequestOptions) {
  return apiRequest<Team>("/api/v1/teams", {
    ...options,
    method: "POST",
    body: payload,
  });
}

/** Update an existing team via PUT /api/v1/teams/:id. */
export function updateTeam(id: string, payload: UpdateTeamPayload, options?: ApiRequestOptions) {
  return apiRequest<Team>(
    `/api/v1/teams/${encodeURIComponent(id)}`,
    { ...options, method: "PUT", body: payload },
  );
}

/** Delete a team via DELETE /api/v1/teams/:id. */
export function deleteTeam(id: string, options?: ApiRequestOptions) {
  return apiRequest<void>(
    `/api/v1/teams/${encodeURIComponent(id)}`,
    { ...options, method: "DELETE" },
  );
}
