/**
 * Marketplace API client — fetches connector specs from the GitHub-backed
 * marketplace via the Next.js API route, and manages installed connectors
 * and instances via the gateway API.
 */

import { apiRequest, listRequest } from "./client";

export interface MarketplaceConnector {
  id: string;
  name: string;
  type: string;
  version: string;
  publisher: string;
  description: string;
  longDescription: string;
  category: string;
  tags: string[];
  icon: string;
  iconColor: string;
  iconBg: string;
  toolCount: number;
  installs: string;
  installCount: number;
  status: "installed" | "not_installed";
  /** "user" for a connector the operator uploaded; absent for bundle connectors. */
  origin?: "bundle" | "user";
  reliability: string;
  authType: string;
  tools: Array<{
    name: string;
    method: string;
    description: string;
    args: Array<{
      name: string;
      type: string;
      description: string;
      required: boolean;
      defaultValue?: string;
    }>;
    outputPath?: string;
  }>;
  config: Array<{
    display: string;
    name: string;
    type: string;
    required: boolean;
    defaultValue?: string;
    options?: string[];
    description?: string;
  }>;
  versions: Array<{ version: string; date: string; changes: string[] }>;
  setupGuide: string;
  dockerImage: string;
  runtime: string;
  sdkLanguage: string;
  sdkPackage: string;
  ingestion: { enabled: boolean; mode: string; description: string };
  topAgents: Array<{ name: string; color: string }>;
}

/**
 * Fetch every connector the marketplace shows: the bundle connectors from the
 * curated catalogue, plus the connectors the operator uploaded (read from the
 * MCP's marketplace catalogue, behind the session). A failure on the uploaded
 * list leaves the bundle cards in place.
 */
export async function listMarketplaceConnectors(): Promise<MarketplaceConnector[]> {
  const [bundle, uploaded] = await Promise.all([
    fetch("/api/marketplace/connectors")
      .then((res) => (res.ok ? (res.json() as Promise<MarketplaceConnector[]>) : []))
      .catch(() => [] as MarketplaceConnector[]),
    fetch("/api/agent/marketplace/catalog/user")
      .then((res) => (res.ok ? (res.json() as Promise<MarketplaceConnector[]>) : []))
      .catch(() => [] as MarketplaceConnector[]),
  ]);
  const known = new Set(bundle.map((c) => c.id));
  return [...bundle, ...uploaded.filter((c) => !known.has(c.id))];
}

/** Fetch a single bundle connector by ID (an uploaded connector answers null). */
export async function getMarketplaceConnector(id: string): Promise<MarketplaceConnector | null> {
  try {
    const res = await fetch(`/api/marketplace/connectors/${encodeURIComponent(id)}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// ── Installed connector operations ─────────────────────────────────────────

/** Install a connector from the marketplace. */
export async function installConnector(connectorId: string, version: string) {
  return apiRequest<{ id: string; connector_id: string; version: string }>(
    "/api/v1/marketplace/install",
    { method: "POST", body: { connector_id: connectorId, version } },
  );
}

/** Uninstall a connector. */
export async function uninstallConnector(connectorId: string) {
  return apiRequest<void>(
    `/api/v1/marketplace/${encodeURIComponent(connectorId)}/uninstall`,
    { method: "DELETE" },
  );
}

/** Delete a connector the operator uploaded (refused while it has instances). */
export async function deleteUploadedConnector(connectorId: string) {
  return apiRequest<{ connector_id: string; deleted: boolean }>(
    `/api/v1/marketplace/${encodeURIComponent(connectorId)}`,
    { method: "DELETE" },
  );
}

/** List installed connectors. */
export async function listInstalledConnectors() {
  // The gateway wraps the array in {"data": [...]}, so we parse the envelope
  // and extract the inner array.
  const result = await apiRequest<{
    data: Array<{ id: string; connector_id: string; version: string; execution_mode: string }>;
  }>("/api/v1/marketplace/installed");

  if (!result.ok) return result;

  // Unwrap the envelope — return the inner array as result.data
  const arr = Array.isArray(result.data)
    ? result.data
    : (result.data?.data ?? []);

  return { ok: true as const, data: arr };
}

// ── Instance operations ────────────────────────────────────────────────────

export interface ConnectorInstance {
  id: string;
  name: string;
  connector_id: string;
  config: Record<string, string>;
  // Redacted secret slot map — keys are slot names (e.g.
  // "caldera_api_key"), values are the literal "***" sentinel when
  // a secret is configured. Surfaces "which slots are populated"
  // without exposing values. Empty object when the connector has
  // no secret slots.
  secrets: Record<string, string>;
  /** Legacy key; the server does not send it. Read `state`. */
  status?: string;
  /** Connection health of the connector: connected | failed | needs-auth | pending | disabled. */
  state?: string;
  enabled: boolean;
  is_channel: boolean;
  workspace_ids: string[];
  created_at: string;
  updated_at: string;
  // Per-instance disabled-tools list. Empty = all
  // tools the connector ships are exposed to the agent. Populated
  // names are filtered out of the agent's tool catalog at registration.
  disabled_tools?: string[];
}

export async function createInstance(data: {
  name: string;
  connector_id: string;
  config: Record<string, string>;
  /**
   * Per-instance secret slots — separate from
   * `config` because the backend writes these into SecretStore
   * (encrypted at rest under PHANTOM_SECRET_KEK) rather than the
   * instances row's plaintext config_json column.
   *
   * Form values of `type:"secret"` (like api_key) must go here, not
   * into `config`: the connector probe reads secrets only from
   * SecretStore, and `config` is stored in plaintext.
   * CreateInstancePanel.handleSave classifies each form value by its
   * ConfigParam.type and passes secrets here.
   */
  secrets?: Record<string, string>;
  /**
   * Per-instance disabled-tools list — names of
   * tools the operator wants OFF for this instance from the moment
   * it boots. Empty/missing → every tool the connector ships is
   * exposed (legacy behaviour). The same list is editable post-create
   * via the toggle panel on the existing-instance row (PATCH path).
   */
  disabled_tools?: string[];
}) {
  return apiRequest<ConnectorInstance>("/api/v1/instances", {
    method: "POST",
    body: data,
  });
}

export async function listInstances(params?: {
  connector_id?: string;
  workspace_id?: string;
}) {
  const qs = new URLSearchParams();
  if (params?.connector_id) qs.set("connector_id", params.connector_id);
  if (params?.workspace_id) qs.set("workspace_id", params.workspace_id);
  const path = qs.toString() ? `/api/v1/instances?${qs}` : "/api/v1/instances";

  // The phantom MCP returns `{instances: [...]}` (named-envelope shape),
  // not the Spark gateway's `{data: [...]}`. listRequest() handles all
  // three shapes correctly — bare array, generic envelope, and named
  // envelope — so the /connectors Instances tab actually renders the
  // operator's instances instead of always showing 0. See client.ts
  // listRequest doc-comment for the full envelope-detection rationale.
  return listRequest<ConnectorInstance>(path);
}

export async function getInstance(id: string) {
  return apiRequest<ConnectorInstance>(
    `/api/v1/instances/${encodeURIComponent(id)}`,
  );
}

export async function updateInstance(
  id: string,
  data: Partial<{
    name: string;
    config: Record<string, string>;
    enabled: boolean;
    is_channel: boolean;
    // Per-instance disabled-tools list. Send the full
    // post-edit list (replacement semantics, not patch-merge). Empty
    // array → all tools enabled.
    disabled_tools: string[];
  }>,
) {
  // Phantom's instance route uses PATCH (partial-update semantics) —
  // the older Spark-gateway shape was PUT. Switching to PATCH lets us
  // send a single field (e.g. {enabled: true}) without re-asserting
  // every other field.
  return apiRequest<{ instance: ConnectorInstance }>(
    `/api/v1/instances/${encodeURIComponent(id)}`,
    { method: "PATCH", body: data },
  );
}

export async function deleteInstance(id: string) {
  return apiRequest<void>(
    `/api/v1/instances/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
}

/** Response from POST /api/v1/instances/{id}/test. */
export interface InstanceTestResult {
  instance: ConnectorInstance;
  probe_implemented: boolean;
  // Present when probe_implemented=true:
  ok?: boolean;
  error?: string | null;
  is_auth_error?: boolean;
  dry_run?: boolean;
  // Connector-state row after the probe (state, last_error, etc.).
  connector_state?: {
    connector_id: string;
    state: string;
    last_probed_at: string | null;
    last_error: string | null;
    consecutive_failures: number;
  } | null;
}

/**
 * Run a probe for the instance.
 *
 * `overrides` lets the operator dry-run with form values from the
 * edit dialog before saving — pass `{config, secrets}`. Per-secret
 * "***" sentinel = "use the persisted value for that slot." When
 * `overrides` is omitted, the probe uses the persisted config and
 * the result is recorded into connector_state. When overrides are
 * present, dry_run defaults to true and the probe outcome doesn't
 * pollute the connector's connection history.
 */
export async function testInstance(
  id: string,
  overrides?: {
    config?: Record<string, string>;
    secrets?: Record<string, string>;
    dry_run?: boolean;
  },
) {
  return apiRequest<InstanceTestResult>(
    `/api/v1/instances/${encodeURIComponent(id)}/test`,
    {
      method: "POST",
      ...(overrides ? { body: overrides } : {}),
    },
  );
}

export async function assignWorkspace(instanceId: string, workspaceId: string) {
  return apiRequest<ConnectorInstance>(
    `/api/v1/instances/${encodeURIComponent(instanceId)}/assign`,
    { method: "POST", body: { workspace_id: workspaceId } },
  );
}

export async function unassignWorkspace(instanceId: string, workspaceId: string) {
  return apiRequest<ConnectorInstance>(
    `/api/v1/instances/${encodeURIComponent(instanceId)}/unassign`,
    { method: "POST", body: { workspace_id: workspaceId } },
  );
}
