import { apiRequest } from "./client";
import type { ApiRequestOptions, ApiResult } from "./client";
import type { HealthStatus, ServiceStatus } from "./types";
import { resolveGatewayUrl } from "@/lib/gateway-url.server";

/** Gateway /readyz response shape. */
interface ReadyzResponse {
  status: string;
  reason?: string;
  deploy_mode?: string;
}

/**
 * Fetch /readyz directly from the gateway.
 *
 * Unlike apiRequest (which uses NEXT_PUBLIC_GATEWAY_URL for client-side
 * relative paths), health checks MUST reach the gateway directly when
 * running server-side. The server-side resolver returns the Docker-internal
 * URL (http://api-gateway:8080) while apiRequest would resolve /readyz
 * against the Next.js app origin (http://localhost:3001) which is wrong.
 */
async function fetchReadyz(
  options?: ApiRequestOptions,
): Promise<ApiResult<ReadyzResponse>> {
  const gatewayUrl = resolveGatewayUrl();
  const url = `${gatewayUrl}/readyz`;

  try {
    const response = await fetch(url, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...(options?.token
          ? { Authorization: `Bearer ${options.token}` }
          : {}),
      },
      signal: options?.signal ?? AbortSignal.timeout(3000),
    });

    if (!response.ok) {
      // /readyz returned non-200 (e.g. 503 when DB is down)
      try {
        const data = (await response.json()) as ReadyzResponse;
        return { ok: true, data };
      } catch {
        return {
          ok: false,
          error: {
            code: `HTTP_${response.status}`,
            message: response.statusText,
            retryable: false,
          },
        };
      }
    }

    const data = (await response.json()) as ReadyzResponse;
    return { ok: true, data };
  } catch {
    return {
      ok: false,
      error: {
        code: "FETCH_ERROR",
        message: "Gateway unreachable",
        retryable: false,
      },
    };
  }
}

/**
 * Fetch overall platform health.
 *
 * The gateway exposes /healthz (unauthenticated, always returns {"status":"ok"})
 * and /readyz (unauthenticated, checks DB + gRPC). We use /readyz so we get a
 * real liveness signal — if the database is down, the dashboard should show it.
 *
 * The response shape differs from the HealthStatus type, so we normalize it.
 */
export async function getHealth(
  options?: ApiRequestOptions,
): Promise<ReturnType<typeof apiRequest<HealthStatus>>> {
  const result = await fetchReadyz(options);

  if (result.ok) {
    // Normalize gateway response to HealthStatus shape
    const gwStatus = result.data.status;
    const normalized: HealthStatus = {
      status:
        gwStatus === "ready" || gwStatus === "ok" ? "healthy" : "unhealthy",
      version: result.data.deploy_mode ?? "unknown",
      uptime: 0, // gateway doesn't expose uptime
    };
    return { ok: true, data: normalized };
  }

  // Gateway unreachable
  return {
    ok: true,
    data: {
      status: "unhealthy",
      version: "unknown",
      uptime: 0,
    },
  };
}

/**
 * Fetch per-service status.
 *
 * The gateway doesn't have a dedicated per-service status endpoint yet.
 * We synthesize a minimal status list from the gateway's /readyz response
 * until a proper /api/v1/status endpoint is implemented.
 */
export async function getStatus(
  options?: ApiRequestOptions,
): Promise<ReturnType<typeof apiRequest<ServiceStatus[]>>> {
  const result = await fetchReadyz(options);

  const now = new Date().toISOString();

  if (result.ok) {
    const isReady =
      result.data.status === "ready" || result.data.status === "ok";
    const services: ServiceStatus[] = [
      {
        name: "api-gateway",
        status: "healthy",
        responseTime: 0,
        lastChecked: now,
      },
      {
        name: "postgres",
        status: isReady ? "healthy" : "unhealthy",
        responseTime: 0,
        lastChecked: now,
      },
      {
        name: "control-plane",
        status: isReady ? "healthy" : "unhealthy",
        responseTime: 0,
        lastChecked: now,
      },
    ];
    return { ok: true, data: services };
  }

  // Gateway unreachable — all services unknown
  return {
    ok: true,
    data: [
      {
        name: "api-gateway",
        status: "unhealthy",
        responseTime: 0,
        lastChecked: now,
      },
    ],
  };
}
