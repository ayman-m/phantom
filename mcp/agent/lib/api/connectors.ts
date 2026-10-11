import { apiRequest, listRequest } from "./client";
import type { ApiRequestOptions } from "./client";

/** Connector info as returned by GET /api/v1/connectors. */
export interface ConnectorInfo {
  provider: string;
  scopes: string[];
  connected: boolean;
}

/** Status response from GET /api/v1/connectors/{provider}/status. */
export interface ConnectorStatus {
  provider: string;
  connected: boolean;
  expired: boolean;
}

/** Auth initiation response from POST /api/v1/connectors/{provider}/auth. */
interface InitiateAuthResponse {
  auth_url: string;
}

/** List all available connectors with connection status. */
export function listConnectors(options?: ApiRequestOptions) {
  return listRequest<ConnectorInfo>("/api/v1/connectors", options);
}

/** Initiate an OAuth flow for a provider. Returns the authorization URL. */
export async function initiateAuth(
  provider: string,
  options?: ApiRequestOptions,
) {
  return apiRequest<InitiateAuthResponse>(
    `/api/v1/connectors/${encodeURIComponent(provider)}/auth`,
    { ...options, method: "POST" },
  );
}

/** Disconnect (revoke) a provider's OAuth token. */
export function disconnectProvider(
  provider: string,
  options?: ApiRequestOptions,
) {
  return apiRequest<{ status: string }>(
    `/api/v1/connectors/${encodeURIComponent(provider)}`,
    { ...options, method: "DELETE" },
  );
}

/** Check a provider's connection status. */
export function getProviderStatus(
  provider: string,
  options?: ApiRequestOptions,
) {
  return apiRequest<ConnectorStatus>(
    `/api/v1/connectors/${encodeURIComponent(provider)}/status`,
    options,
  );
}
