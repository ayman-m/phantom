/**
 * Log destinations API client.
 *
 * Read tools call /api/agent/log-destinations/* (thin Next.js proxies
 * to the MCP). Write/probe operations go through the same proxy with
 * bearer auth from runtime-config; the credential boundary lives on
 * the MCP side (operator-UI-only; agent has no write tools).
 */

import { apiRequest } from "./client";

// ── Manifest shape (matches DestinationTypeManifest.to_dict()) ──

export interface DestinationFieldDef {
  name: string;
  display: string;
  type: ConfigParamType;
  required?: boolean;
  defaultValue?: string | null;
  description?: string;
  options?: string[];
  visible_when?: { field: string; value: string | string[] };
}

export type ConfigParamType =
  | "text"
  | "url"
  | "string"
  | "number"
  | "password"
  | "secret"
  | "textarea"
  | "select"
  | "radio"
  | "multi_select"
  | "boolean"
  | "array"
  | "json";

export interface DestinationTypeManifest {
  schema_version: number;
  id: string;
  name: string;
  description: string;
  category: string;
  icon: string;
  iconColor: string;
  iconBg: string;
  fields: DestinationFieldDef[];
  handler: string;
  probe?: { send_test_message?: boolean };
}

// ── Destination row shape ───────────────────────────────────────

export interface LogDestination {
  id: string;
  name: string;
  type_id: string;
  config: Record<string, string>;
  // Secret slots; values are "***" sentinels (server redacts).
  secrets: Record<string, string>;
  enabled: boolean;
  is_default: boolean;
  description?: string | null;
  created_at: string;
  updated_at: string;
  last_probe_at?: string | null;
  last_probe_ok?: boolean | null;
  last_probe_error?: string | null;
  consecutive_failures: number;
}

// ── Catalog endpoints ────────────────────────────────────────────

export async function listDestinationTypes(): Promise<DestinationTypeManifest[]> {
  const result = await apiRequest<{ types: DestinationTypeManifest[] }>(
    "/api/v1/destination-types",
  );
  if (!result.ok) return [];
  return result.data.types || [];
}

export async function getDestinationType(
  typeId: string,
): Promise<DestinationTypeManifest | null> {
  const result = await apiRequest<{ type: DestinationTypeManifest }>(
    `/api/v1/destination-types/${encodeURIComponent(typeId)}`,
  );
  if (!result.ok) return null;
  return result.data.type ?? null;
}

// ── CRUD endpoints ───────────────────────────────────────────────

export async function listDestinations(params?: {
  type_id?: string;
  enabled_only?: boolean;
}): Promise<LogDestination[]> {
  const qs = new URLSearchParams();
  if (params?.type_id) qs.set("type_id", params.type_id);
  if (params?.enabled_only) qs.set("enabled_only", "true");
  const path = qs.toString()
    ? `/api/v1/log-destinations?${qs}`
    : `/api/v1/log-destinations`;
  const result = await apiRequest<{ destinations: LogDestination[] }>(path);
  if (!result.ok) return [];
  return result.data.destinations || [];
}

export async function getDestination(
  id: string,
): Promise<LogDestination | null> {
  const result = await apiRequest<{ destination: LogDestination }>(
    `/api/v1/log-destinations/${encodeURIComponent(id)}`,
  );
  if (!result.ok) return null;
  return result.data.destination ?? null;
}

export async function createDestination(data: {
  name: string;
  type_id: string;
  config: Record<string, string>;
  secrets?: Record<string, string>;
  description?: string;
  enabled?: boolean;
  is_default?: boolean;
}) {
  return apiRequest<{ destination: LogDestination }>(
    "/api/v1/log-destinations",
    { method: "POST", body: data },
  );
}

export async function updateDestination(
  id: string,
  data: Partial<{
    name: string;
    config: Record<string, string>;
    // "***" sentinel preserves an existing secret; "" deletes it.
    secrets: Record<string, string>;
    enabled: boolean;
    is_default: boolean;
    description: string | null;
  }>,
) {
  return apiRequest<{ destination: LogDestination }>(
    `/api/v1/log-destinations/${encodeURIComponent(id)}`,
    { method: "PATCH", body: data },
  );
}

export async function deleteDestination(id: string) {
  return apiRequest<{ ok: true }>(
    `/api/v1/log-destinations/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
}

export interface ProbeResult {
  ok: boolean;
  error: string | null;
  latency_ms: number;
  dry_run: boolean;
}

export async function probeDestination(
  id: string,
  overrides?: {
    config?: Record<string, string>;
    secrets?: Record<string, string>;
  },
) {
  return apiRequest<ProbeResult>(
    `/api/v1/log-destinations/${encodeURIComponent(id)}/probe`,
    { method: "POST", ...(overrides ? { body: overrides } : {}) },
  );
}

export async function setDefaultDestination(id: string) {
  return apiRequest<{ destination: LogDestination }>(
    `/api/v1/log-destinations/${encodeURIComponent(id)}/set-default`,
    { method: "POST" },
  );
}
