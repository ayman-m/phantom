/**
 * /api/agent/destination-types — catalog of available type manifests.
 *
 * Read-only; manifests are immutable at runtime (ship in the agent
 * image at /app/bundle/destinations/<id>/spec.yaml). The form engine
 * uses these to render the dynamic CRUD form.
 */

import { proxyToMcp } from "@/lib/mcp-proxy";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  return proxyToMcp(request, "/api/v1/destination-types");
}
