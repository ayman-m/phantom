/**
 * /api/agent/log-destinations/{id}/probe — fire the type's probe handler.
 *
 * Optional body shape: {config?: {...}, secrets?: {...}} for dry-run
 * override (test-before-save UX). Without overrides, runs against the
 * persisted row and records the outcome.
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
    `/api/v1/log-destinations/${encodeURIComponent(id)}/probe`,
  );
}
