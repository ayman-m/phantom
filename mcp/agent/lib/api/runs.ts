import { apiRequest, listRequest } from "./client";
import type { ApiRequestOptions } from "./client";
import type { Run, CreateRunOptions } from "./types";

/** List runs from GET /api/v1/runs, optionally filtered by status. */
export function listRuns(
  params?: { status?: string },
  options?: ApiRequestOptions,
) {
  const query = params?.status ? `?status=${encodeURIComponent(params.status)}` : "";
  return listRequest<Run>(`/api/v1/runs${query}`, options);
}

/** Create a new run within a session via POST /api/v1/sessions/:sessionId/runs. */
export function createRun(
  sessionId: string,
  message: string,
  runOptions?: CreateRunOptions,
  options?: ApiRequestOptions,
) {
  return apiRequest<Run>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/runs`,
    { ...options, method: "POST", body: { input: message, ...runOptions } },
  );
}

/** Fetch a single run by ID from GET /api/v1/runs/:id. */
export function getRun(id: string, options?: ApiRequestOptions) {
  return apiRequest<Run>(`/api/v1/runs/${encodeURIComponent(id)}`, options);
}

/** Cancel a run by ID via POST /api/v1/runs/:id/cancel. */
export function cancelRun(id: string, options?: ApiRequestOptions) {
  return apiRequest<Run>(
    `/api/v1/runs/${encodeURIComponent(id)}/cancel`,
    { ...options, method: "POST" },
  );
}

/** Create a run for an agent (implicitly creates a session) via POST /api/v1/runs. */
export function createAgentRun(
  agentId: string,
  message: string,
  runOptions?: CreateRunOptions,
  options?: ApiRequestOptions,
) {
  return apiRequest<Run>(`/api/v1/runs`, {
    ...options,
    method: "POST",
    body: { agent_id: agentId, input: message, ...runOptions },
  });
}

/** Abort a run by ID with a reason via POST /api/v1/runs/:id/abort. */
export function abortRun(
  id: string,
  reason?: string,
  options?: ApiRequestOptions,
) {
  return apiRequest<Run>(
    `/api/v1/runs/${encodeURIComponent(id)}/abort`,
    { ...options, method: "POST", body: { reason } },
  );
}
