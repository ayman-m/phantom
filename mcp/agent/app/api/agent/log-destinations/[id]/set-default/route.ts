/**
 * /api/agent/log-destinations/{id}/set-default — promote to default-of-type.
 *
 * Clears `is_default` on all siblings sharing the same type_id in the
 * same transaction. Single-default-per-type invariant per spec section 2.
 */

import { proxyToMcp } from "@/lib/mcp-proxy";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return proxyToMcp(
    request,
    `/api/v1/log-destinations/${encodeURIComponent(id)}/set-default`,
  );
}
