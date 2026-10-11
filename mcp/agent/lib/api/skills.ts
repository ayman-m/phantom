import { apiRequest, listRequest } from "./client";
import type { ApiRequestOptions } from "./client";
import type { SkillDescriptor } from "./types";

/** Payload for creating a skill. */
export interface CreateSkillPayload {
  name: string;
  description: string;
  content: string;
  category: string;
}

/** Payload for updating an existing skill. */
export interface UpdateSkillPayload {
  description?: string;
  content?: string;
  category?: string;
}

/** List available skills from GET /api/v1/skills. */
export function listSkills(
  eligibleOnly?: boolean,
  options?: ApiRequestOptions,
) {
  const query =
    eligibleOnly === undefined ? "" : `?eligible_only=${eligibleOnly}`;
  return listRequest<SkillDescriptor>(`/api/v1/skills${query}`, options);
}

/** Fetch a single skill by name from GET /api/v1/skills/:name. */
export function getSkill(name: string, options?: ApiRequestOptions) {
  return apiRequest<SkillDescriptor>(
    `/api/v1/skills/${encodeURIComponent(name)}`,
    options,
  );
}

/** Create a new skill via POST /api/v1/skills. */
export function createSkill(
  payload: CreateSkillPayload,
  options?: ApiRequestOptions,
) {
  return apiRequest<SkillDescriptor>("/api/v1/skills", {
    ...options,
    method: "POST",
    body: payload,
  });
}

/** Update an existing skill via PUT /api/v1/skills/:name. */
export function updateSkill(
  name: string,
  payload: UpdateSkillPayload,
  options?: ApiRequestOptions,
) {
  return apiRequest<SkillDescriptor>(
    `/api/v1/skills/${encodeURIComponent(name)}`,
    { ...options, method: "PUT", body: payload },
  );
}

/** Delete a skill via DELETE /api/v1/skills/:name. */
export function deleteSkill(name: string, options?: ApiRequestOptions) {
  return apiRequest<void>(
    `/api/v1/skills/${encodeURIComponent(name)}`,
    { ...options, method: "DELETE" },
  );
}
