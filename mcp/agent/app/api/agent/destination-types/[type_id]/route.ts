/**
 * Per-type manifest proxy.
 */

import { proxyToMcp } from "@/lib/mcp-proxy";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ type_id: string }> },
) {
  const { type_id } = await params;
  return proxyToMcp(
    request,
    `/api/v1/destination-types/${encodeURIComponent(type_id)}`,
  );
}
