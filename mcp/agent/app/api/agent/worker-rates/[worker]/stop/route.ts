/**
 * /api/agent/worker-rates/[worker]/stop — stop one generation worker.
 *
 * Stopping also releases the worker's share of the aggregate rate ceiling and
 * its burst slot, so this is how an operator reclaims budget without
 * restarting the container.
 */

import { proxyToMcp } from "@/lib/mcp-proxy";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ worker: string }> },
) {
  const { worker } = await params;
  return proxyToMcp(
    request,
    `/api/v1/worker-rates/${encodeURIComponent(worker)}/stop`,
  );
}
