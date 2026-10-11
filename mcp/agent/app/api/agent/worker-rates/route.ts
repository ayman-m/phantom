/**
 * /api/agent/worker-rates — live generation rates + ceilings.
 *
 * The browser cannot reach xlog: it is not exposed outside the docker network
 * and its bearer token must never reach client code. This proxies to the MCP,
 * which in turn calls xlog with the server-side token.
 *
 * GET → per-worker admitted rates, aggregate consumption, and the ceilings
 *       those are judged against.
 */

import { proxyToMcp } from "@/lib/mcp-proxy";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  return proxyToMcp(request, "/api/v1/worker-rates");
}
