/**
 * /api/agent/workers — the xlog data workers currently registered.
 *
 * The browser cannot reach xlog (not exposed outside the docker network, and
 * its bearer token must never reach client code). This forwards to the MCP,
 * which asks xlog's listWorkers — the same list the agent's xlog.list_workers
 * tool returns. Read-only; stopping a worker goes through
 * /api/agent/worker-rates/{worker}/stop.
 */

import { proxyToMcp } from "@/lib/mcp-proxy";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  return proxyToMcp(request, "/api/v1/workers");
}
