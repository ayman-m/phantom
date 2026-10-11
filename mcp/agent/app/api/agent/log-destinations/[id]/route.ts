/**
 * Per-destination proxy — GET / PATCH / DELETE one log destination.
 */

import { proxyToMcp } from "@/lib/mcp-proxy";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return proxyToMcp(
    request,
    `/api/v1/log-destinations/${encodeURIComponent(id)}`,
  );
}

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return proxyToMcp(
    request,
    `/api/v1/log-destinations/${encodeURIComponent(id)}`,
  );
}

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return proxyToMcp(
    request,
    `/api/v1/log-destinations/${encodeURIComponent(id)}`,
  );
}
